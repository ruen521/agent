from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from typing import Any, Generator, Sequence

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    InventoryItem,
    TeamArtifact,
    TeamMemberMemory,
    TeamRun,
    TeamSharedState,
    Vendor,
    VendorCallLog,
)

logger = logging.getLogger("app.db")


class MysqlRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False)

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)
        try:
            self._migrate_legacy_schema()
        except Exception as exc:
            logger.warning("mysql_schema_migration_skipped", extra={"error_code": type(exc).__name__})

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_inventory_items(
        self,
        query_type: str = "all",
        category: str | None = None,
        sku: str | None = None,
        skus: Sequence[str] | None = None,
        vendor_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        with self.session() as session:
            query = select(InventoryItem)

            # 按查询类型过滤
            if query_type == "low_stock":
                query = query.where(InventoryItem.current_stock < InventoryItem.reorder_point)
            elif query_type == "by_category" and category:
                query = query.where(InventoryItem.category == category)
            elif query_type == "by_sku" and sku:
                query = query.where(InventoryItem.sku == sku)
            elif query_type == "stockout_risk":
                # 只查询有销售速度且库存较低的商品
                query = query.where(
                    InventoryItem.daily_sales_velocity > 0,
                    InventoryItem.current_stock / InventoryItem.daily_sales_velocity <= 7
                )
            if skus:
                query = query.where(InventoryItem.sku.in_(list(skus)))
            if vendor_id:
                query = query.where(InventoryItem.vendor_id == vendor_id)

            # 限制返回数量
            if limit:
                query = query.limit(limit)

            items = session.execute(query).scalars().all()
            return [_item_to_dict(item) for item in items]

    def get_vendors(self) -> list[dict[str, Any]]:
        with self.session() as session:
            vendors = session.execute(select(Vendor)).scalars().all()
            return [_vendor_to_dict(vendor) for vendor in vendors]

    def get_vendor_call_logs(self) -> list[dict[str, Any]]:
        with self.session() as session:
            logs = session.execute(select(VendorCallLog)).scalars().all()
            return [
                {
                    "id": log.id,
                    "VendorID": log.vendor_id,
                    "ContactTime": log.contact_time.isoformat(),
                    "Duration": log.duration,
                    "Outcome": log.outcome or "",
                    "Notes": log.notes or "",
                    "RecordingURL": log.recording_url or "",
                }
                for log in logs
            ]

    def get_replenishment_plans(self) -> list[dict[str, Any]]:
        columns = self._table_columns("replenishment_plans")
        select_columns = [
            column
            for column in ("id", "created_at", "created_by", "total_cost", "vendor_groups", "status")
            if column in columns
        ]
        if not select_columns:
            return []

        with self.session() as session:
            sql = (
                f"SELECT {', '.join(select_columns)} "
                "FROM replenishment_plans "
                "ORDER BY id DESC"
            )
            rows = session.execute(text(sql)).mappings().all()
            return [
                {
                    "id": int(row.get("id") or 0),
                    "created_at": _format_datetime(row.get("created_at")),
                    "created_by": str(row.get("created_by") or ""),
                    "total_cost": float(row.get("total_cost") or 0),
                    "vendor_groups": _parse_json_column(row.get("vendor_groups")),
                    "status": str(row.get("status") or "DRAFT"),
                }
                for row in rows
            ]

    def save_replenishment_plans(self, plans: list[dict[str, Any]]) -> None:
        columns = self._table_columns("replenishment_plans")
        with self.session() as session:
            for plan in plans:
                payload: dict[str, Any] = {
                    "created_at": _parse_datetime(plan.get("created_at")),
                    "total_cost": float(plan.get("total_cost", 0)),
                    "vendor_groups": json.dumps(plan.get("vendor_groups", {}), ensure_ascii=False),
                }
                if "created_by" in columns:
                    payload["created_by"] = str(plan.get("created_by") or "replenishment_planner")
                if "status" in columns:
                    payload["status"] = str(plan.get("status") or "DRAFT")

                col_names = ", ".join(payload.keys())
                placeholders = ", ".join(f":{key}" for key in payload.keys())
                session.execute(
                    text(f"INSERT INTO replenishment_plans ({col_names}) VALUES ({placeholders})"),
                    payload,
                )

    def create_team_run(
        self,
        *,
        run_id: str,
        session_id: str,
        objective: str,
        topology_version: str,
        status: str,
        orchestration_options: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.utcnow()
        with self.session() as session:
            record = session.execute(select(TeamRun).where(TeamRun.run_id == run_id)).scalar_one_or_none()
            if record is None:
                session.add(
                    TeamRun(
                        run_id=run_id,
                        session_id=session_id,
                        objective=objective,
                        topology_version=topology_version,
                        status=status,
                        orchestration_options=orchestration_options,
                        error_code=None,
                        error_message=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return
            record.session_id = session_id
            record.objective = objective
            record.topology_version = topology_version
            record.status = status
            record.orchestration_options = orchestration_options
            record.updated_at = now

    def update_team_run_status(
        self,
        *,
        run_id: str,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.session() as session:
            record = session.execute(select(TeamRun).where(TeamRun.run_id == run_id)).scalar_one_or_none()
            if record is None:
                return
            record.status = status
            record.error_code = error_code
            record.error_message = error_message
            record.updated_at = datetime.utcnow()

    def get_team_shared_state(self, run_id: str) -> dict[str, dict[str, Any]]:
        with self.session() as session:
            rows = session.execute(
                select(TeamSharedState).where(TeamSharedState.run_id == run_id)
            ).scalars().all()
            return {
                row.state_key: {
                    "value": row.state_value,
                    "version": int(row.version),
                    "producer_member": row.producer_member or "",
                    "updated_at": _format_datetime(row.updated_at),
                }
                for row in rows
            }

    def upsert_team_shared_state(
        self,
        *,
        run_id: str,
        key: str,
        value: Any,
        version: int,
        producer_member: str,
    ) -> None:
        with self.session() as session:
            record = session.execute(
                select(TeamSharedState).where(
                    TeamSharedState.run_id == run_id,
                    TeamSharedState.state_key == key,
                )
            ).scalar_one_or_none()
            now = datetime.utcnow()
            if record is None:
                session.add(
                    TeamSharedState(
                        run_id=run_id,
                        state_key=key,
                        state_value=value,
                        version=version,
                        producer_member=producer_member,
                        updated_at=now,
                    )
                )
                return
            record.state_value = value
            record.version = version
            record.producer_member = producer_member
            record.updated_at = now

    def get_member_memory(
        self,
        *,
        member_id: str,
        scope: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self.session() as session:
            rows = session.execute(
                select(TeamMemberMemory)
                .where(
                    TeamMemberMemory.member_id == member_id,
                    TeamMemberMemory.scope == scope,
                )
                .order_by(TeamMemberMemory.id.desc())
                .limit(max(1, int(limit)))
            ).scalars().all()
            # Keep chronological order when injecting context.
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "member_id": row.member_id,
                    "scope": row.scope,
                    "content": row.content,
                    "memory_json": row.memory_json,
                    "created_at": _format_datetime(row.created_at),
                }
                for row in reversed(rows)
            ]

    def append_member_memory(
        self,
        *,
        run_id: str,
        member_id: str,
        scope: str,
        content: str,
        memory_json: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        with self.session() as session:
            session.add(
                TeamMemberMemory(
                    run_id=run_id,
                    member_id=member_id,
                    scope=scope,
                    content=content,
                    memory_json=memory_json,
                    created_at=datetime.utcnow(),
                )
            )

    def save_team_artifact(
        self,
        *,
        run_id: str,
        member_id: str,
        kind: str,
        file_name: str,
        file_path: str,
        content_type: str | None = None,
        artifact_meta: dict[str, Any] | list[Any] | None = None,
    ) -> int:
        with self.session() as session:
            row = TeamArtifact(
                run_id=run_id,
                member_id=member_id,
                kind=kind,
                file_name=file_name,
                file_path=file_path,
                content_type=content_type,
                artifact_meta=artifact_meta,
                created_at=datetime.utcnow(),
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def list_team_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self.session() as session:
            rows = session.execute(
                select(TeamArtifact)
                .where(TeamArtifact.run_id == run_id)
                .order_by(TeamArtifact.id.asc())
            ).scalars().all()
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "member_id": row.member_id,
                    "kind": row.kind,
                    "file_name": row.file_name,
                    "file_path": row.file_path,
                    "content_type": row.content_type,
                    "artifact_meta": row.artifact_meta,
                    "created_at": _format_datetime(row.created_at),
                }
                for row in rows
            ]

    def _table_columns(self, table_name: str) -> set[str]:
        inspector = inspect(self.engine)
        return {column["name"] for column in inspector.get_columns(table_name)}

    def _migrate_legacy_schema(self) -> None:
        inspector = inspect(self.engine)
        table_names = set(inspector.get_table_names())
        if "inventory_items" in table_names:
            self._migrate_inventory_items(inspector)
        if "vendor_call_logs" in table_names:
            self._migrate_vendor_call_logs(inspector)
        if "replenishment_plans" in table_names:
            self._migrate_replenishment_plans(inspector)

    def _migrate_inventory_items(self, inspector) -> None:
        columns = {col["name"] for col in inspector.get_columns("inventory_items")}
        alters = []
        if "selling_price" not in columns:
            alters.append("ADD COLUMN selling_price DOUBLE NULL")
        if "gross_margin_pct" not in columns:
            alters.append("ADD COLUMN gross_margin_pct DOUBLE NULL")
        if "holding_cost_pct" not in columns:
            alters.append("ADD COLUMN holding_cost_pct DOUBLE NULL")
        if "substitute_skus" not in columns:
            alters.append("ADD COLUMN substitute_skus JSON NULL")
        self._run_alter("inventory_items", alters)

    def _migrate_vendor_call_logs(self, inspector) -> None:
        columns = {col["name"] for col in inspector.get_columns("vendor_call_logs")}
        alters = []
        if "duration" not in columns:
            alters.append("ADD COLUMN duration INT NULL")
        if "outcome" not in columns:
            alters.append("ADD COLUMN outcome VARCHAR(64) NULL")
        if "recording_url" not in columns:
            alters.append("ADD COLUMN recording_url VARCHAR(1024) NULL")
        self._run_alter("vendor_call_logs", alters)

    def _migrate_replenishment_plans(self, inspector) -> None:
        columns = {col["name"] for col in inspector.get_columns("replenishment_plans")}
        alters = []
        if "created_by" not in columns:
            alters.append("ADD COLUMN created_by VARCHAR(128) NULL")
        if "status" not in columns:
            alters.append("ADD COLUMN status VARCHAR(64) NULL")
        self._run_alter("replenishment_plans", alters)

    def _run_alter(self, table_name: str, alters: list[str]) -> None:
        if not alters:
            return
        with self.engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table_name} " + ", ".join(alters)))


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return datetime.utcnow()


def _format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return ""


def _parse_json_column(value: Any) -> dict[str, Any] | list[Any]:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _item_to_dict(item: InventoryItem) -> dict[str, Any]:
    return {
        "SKU": item.sku,
        "Name": item.name,
        "Category": item.category,
        "CurrentStock": item.current_stock,
        "ReorderPoint": item.reorder_point,
        "DailySalesVelocity": item.daily_sales_velocity,
        "UnitCost": item.unit_cost,
        "SellingPrice": item.selling_price if item.selling_price is not None else item.unit_cost * 1.3,
        "GrossMarginPct": item.gross_margin_pct if item.gross_margin_pct is not None else 0.35,
        "HoldingCostPct": item.holding_cost_pct if item.holding_cost_pct is not None else 0.0007,
        "SubstituteSKUs": item.substitute_skus or [],
        "VendorID": item.vendor_id,
        "LeadTimeDays": item.lead_time_days,
        "LastUpdated": item.last_updated.isoformat() if item.last_updated else "",
    }


def _vendor_to_dict(vendor: Vendor) -> dict[str, Any]:
    return {
        "VendorID": vendor.vendor_id,
        "Name": vendor.name,
        "PhoneNumber": vendor.phone_number or "",
        "Email": vendor.email or "",
        "LeadTimeDays": vendor.lead_time_days,
        "MinimumOrder": vendor.minimum_order,
        "Rating": vendor.rating,
    }
