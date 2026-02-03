from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, InventoryItem, ReplenishmentPlan, Vendor, VendorCallLog


class MysqlRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False)

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)

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
                    "Notes": log.notes or "",
                }
                for log in logs
            ]

    def get_replenishment_plans(self) -> list[dict[str, Any]]:
        with self.session() as session:
            plans = session.execute(select(ReplenishmentPlan)).scalars().all()
            return [
                {
                    "id": plan.id,
                    "created_at": plan.created_at.isoformat(),
                    "total_cost": plan.total_cost,
                    "vendor_groups": plan.vendor_groups,
                }
                for plan in plans
            ]

    def save_replenishment_plans(self, plans: list[dict[str, Any]]) -> None:
        with self.session() as session:
            for plan in plans:
                session.add(
                    ReplenishmentPlan(
                        created_at=_parse_datetime(plan.get("created_at")),
                        total_cost=float(plan.get("total_cost", 0)),
                        vendor_groups=plan.get("vendor_groups", {}),
                    )
                )


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.utcnow()


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
