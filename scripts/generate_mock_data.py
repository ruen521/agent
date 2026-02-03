from __future__ import annotations

import argparse
import random
import sys
from datetime import date
from pathlib import Path

# 将项目根目录添加到 Python 路径
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from app.core.settings import settings

CATEGORIES = [
    "Holiday",
    "Electronics",
    "Home",
    "Outdoor",
    "Toys",
    "Apparel",
    "Kitchen",
    "Beauty",
    "Office",
    "Sports",
    "Pets",
    "Garden",
]

VENDOR_NAMES = [
    "Holiday Supplies Inc.",
    "Evergreen Wholesale",
    "Aurora Electronics",
    "Northwind Distribution",
    "Summit Outfitters",
    "Blue Harbor Imports",
    "Sunrise Consumer Goods",
    "Brightline Trading",
]


def _make_vendors(count: int) -> list[dict[str, object]]:
    vendors = []
    for idx in range(1, count + 1):
        name = VENDOR_NAMES[(idx - 1) % len(VENDOR_NAMES)]
        vendors.append(
            {
                "VendorID": f"V{idx:03d}",
                "Name": name,
                "PhoneNumber": f"+1-555-01{idx:03d}",
                "Email": f"orders{idx}@{name.lower().replace(' ', '')}.example",
                "LeadTimeDays": random.choice([7, 10, 12, 15, 18]),
                "MinimumOrder": random.choice([300, 400, 500, 800, 1000]),
                "Rating": round(random.uniform(4.0, 4.8), 2),
            }
        )
    return vendors


def _make_inventory(count: int, vendors: list[dict[str, object]]) -> list[dict[str, object]]:
    items = []
    for idx in range(1, count + 1):
        category = random.choice(CATEGORIES)
        vendor = random.choice(vendors)
        velocity = round(random.uniform(0.5, 15.0), 2)
        current_stock = random.randint(5, 200)
        reorder_point = max(10, int(current_stock * random.uniform(0.6, 1.4)))
        unit_cost = round(random.uniform(3.0, 75.0), 2)
        selling_price = round(unit_cost * random.uniform(1.2, 1.6), 2)
        gross_margin_pct = round((selling_price - unit_cost) / selling_price, 4) if selling_price else 0.35
        items.append(
            {
                "SKU": f"{category[:3].upper()}-{idx:06d}",
                "Name": f"{category} Item {idx:06d}",
                "Category": category,
                "CurrentStock": current_stock,
                "ReorderPoint": reorder_point,
                "DailySalesVelocity": velocity,
                "UnitCost": unit_cost,
                "SellingPrice": selling_price,
                "GrossMarginPct": gross_margin_pct,
                "HoldingCostPct": 0.0007,
                "SubstituteSKUs": [],
                "VendorID": vendor["VendorID"],
                "LeadTimeDays": vendor["LeadTimeDays"],
                "LastUpdated": date.today().isoformat(),
            }
        )
    return items


def _seed_mysql(vendors: list[dict[str, object]], items: list[dict[str, object]]) -> None:
    from sqlalchemy import delete
    from app.db.models import InventoryItem, Vendor
    from app.db.mysql_repository import MysqlRepository

    repo = MysqlRepository(settings.database_url)
    repo.create_tables()

    # 先删除 inventory_items（子表），再删除 vendors（父表）
    with repo.session() as session:
        session.execute(delete(InventoryItem))
        session.execute(delete(Vendor))

    # 先插入 vendors（父表）
    with repo.session() as session:
        for vendor in vendors:
            session.add(
                Vendor(
                    vendor_id=vendor["VendorID"],
                    name=vendor["Name"],
                    phone_number=vendor["PhoneNumber"],
                    email=vendor["Email"],
                    lead_time_days=vendor["LeadTimeDays"],
                    minimum_order=vendor["MinimumOrder"],
                    rating=vendor["Rating"],
                )
            )

    # 再插入 inventory_items（子表）
    with repo.session() as session:
        for item in items:
            session.add(
                InventoryItem(
                    sku=item["SKU"],
                    name=item["Name"],
                    category=item["Category"],
                    current_stock=item["CurrentStock"],
                    reorder_point=item["ReorderPoint"],
                    daily_sales_velocity=item["DailySalesVelocity"],
                    unit_cost=item["UnitCost"],
                    selling_price=item["SellingPrice"],
                    gross_margin_pct=item["GrossMarginPct"],
                    holding_cost_pct=item["HoldingCostPct"],
                    substitute_skus=item["SubstituteSKUs"],
                    vendor_id=item["VendorID"],
                    lead_time_days=item["LeadTimeDays"],
                    last_updated=date.fromisoformat(item["LastUpdated"]),
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=30)
    parser.add_argument("--vendors", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    vendors = _make_vendors(args.vendors)
    items = _make_inventory(args.items, vendors)

    if not settings.database_url:
        raise SystemExit("DATABASE_URL/MYSQL_URL not set")
    _seed_mysql(vendors, items)
    print(f"seeded vendors={len(vendors)} items={len(items)}")


if __name__ == "__main__":
    main()
