from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.settings import settings

logger = logging.getLogger("app.data")

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

_inventory_items: list[dict[str, Any]] = []
_vendors: list[dict[str, Any]] = []
_vendor_call_logs: list[dict[str, Any]] = []
_replenishment_plans: list[dict[str, Any]] = []

_repo = None


def _load_json(filename: str) -> list[dict[str, Any]]:
    path = _DATA_DIR / filename
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _get_mysql_repo():
    global _repo
    if not settings.database_url:
        return None
    if _repo is None:
        try:
            from app.db.mysql_repository import MysqlRepository
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("SQLAlchemy is required for MySQL support") from exc
        try:
            repo = MysqlRepository(settings.database_url)
            repo.create_tables()
            _repo = repo
        except Exception as exc:
            logger.error("mysql_unavailable", extra={"error_code": type(exc).__name__})
            _repo = None
            if settings.db_strict:
                raise
            return None
    return _repo


def load_data() -> None:
    repo = _get_mysql_repo()
    if repo:
        return
    global _inventory_items, _vendors, _vendor_call_logs, _replenishment_plans
    _inventory_items = _load_json("mock_inventory.json")
    _vendors = _load_json("mock_vendors.json")
    _vendor_call_logs = _load_json("mock_vendor_call_logs.json")
    _replenishment_plans = _load_json("mock_replenishment_plans.json")


def get_inventory_items(
    query_type: str = "all",
    category: str | None = None,
    sku: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    repo = _get_mysql_repo()
    if repo:
        return repo.get_inventory_items(query_type, category, sku, limit)

    # Mock 数据也需要过滤
    items = list(_inventory_items)

    if query_type == "low_stock":
        items = [item for item in items if item["CurrentStock"] < item["ReorderPoint"]]
    elif query_type == "by_category" and category:
        items = [item for item in items if item["Category"].lower() == category.lower()]
    elif query_type == "by_sku" and sku:
        items = [item for item in items if item["SKU"].lower() == sku.lower()]
    elif query_type == "stockout_risk":
        items = [
            item for item in items
            if item.get("DailySalesVelocity", 0) > 0
            and item["CurrentStock"] / item["DailySalesVelocity"] <= 7
        ]

    if limit:
        items = items[:limit]

    return items


def get_vendors() -> list[dict[str, Any]]:
    repo = _get_mysql_repo()
    if repo:
        return repo.get_vendors()
    return list(_vendors)


def get_vendor_call_logs() -> list[dict[str, Any]]:
    repo = _get_mysql_repo()
    if repo:
        return repo.get_vendor_call_logs()
    return list(_vendor_call_logs)


def get_replenishment_plans() -> list[dict[str, Any]]:
    repo = _get_mysql_repo()
    if repo:
        return repo.get_replenishment_plans()
    return list(_replenishment_plans)


def save_replenishment_plans(plans: list[dict[str, Any]]) -> None:
    repo = _get_mysql_repo()
    if repo:
        repo.save_replenishment_plans(plans)
        return
    global _replenishment_plans
    _replenishment_plans = list(plans)
    path = _DATA_DIR / "mock_replenishment_plans.json"
    path.write_text(json.dumps(_replenishment_plans, indent=2), encoding="utf-8")


def main() -> None:
    load_data()
    print({"inventory_items": len(get_inventory_items()), "vendors": len(get_vendors())})


if __name__ == "__main__":
    main()
