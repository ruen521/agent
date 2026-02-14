from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from experiments.reference_methods.db import ExperimentDb, upsert_rows
from experiments.reference_methods.xlsx_parsers import parse_fba_inventory_workbook, parse_sales_workbook


def _date_range(values: list[datetime.date]) -> dict[str, str]:
    if not values:
        return {"start": "", "end": ""}
    return {"start": min(values).isoformat(), "end": max(values).isoformat()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import real xlsx files into experiment_* MySQL tables")
    parser.add_argument("--sales-xlsx", default="data/real/销量统计.xlsx")
    parser.add_argument("--inventory-xlsx", default="data/real/FBA库存.xlsx")
    parser.add_argument("--database-url", default="")
    args = parser.parse_args()

    sales_path = Path(args.sales_xlsx)
    inventory_path = Path(args.inventory_xlsx)

    sales_rows = parse_sales_workbook(sales_path)
    inventory_rows = parse_fba_inventory_workbook(inventory_path)
    imported_at = datetime.now(timezone.utc).replace(tzinfo=None)

    db = ExperimentDb(args.database_url or None)
    db.ensure_tables()

    sales_payload = [
        {
            "as_of_date": row.as_of_date,
            "asin": row.asin,
            "units": row.units,
            "orders_count": row.orders_count,
            "amount": row.amount,
            "source_file": sales_path.name,
            "imported_at": imported_at,
        }
        for row in sales_rows
    ]

    inv_payload = [
        {
            "snapshot_date": row.snapshot_date,
            "asin": row.asin,
            "total_stock": row.total_stock,
            "sellable_stock": row.sellable_stock,
            "inbound_stock": row.inbound_stock,
            "avg_unit_cost": row.avg_unit_cost,
            "total_inventory_cost": row.total_inventory_cost,
            "total_goods_value": row.total_goods_value,
            "category": row.category,
            "product_name": row.product_name,
            "store_count": row.store_count,
            "warehouse_count": row.warehouse_count,
            "raw_row_count": row.raw_row_count,
            "source_file": inventory_path.name,
            "imported_at": imported_at,
        }
        for row in inventory_rows
    ]

    with db.session() as session:
        sales_inserted, sales_updated = upsert_rows(
            session,
            table="experiment_sales_daily",
            rows=sales_payload,
            key_fields=["as_of_date", "asin"],
        )
        inv_inserted, inv_updated = upsert_rows(
            session,
            table="experiment_inventory_snapshot_asin",
            rows=inv_payload,
            key_fields=["snapshot_date", "asin"],
        )

    sales_asins = {row.asin for row in sales_rows}
    inv_asins = {row.asin for row in inventory_rows}

    summary = {
        "sales": {
            "source": str(sales_path),
            "rows_inserted": sales_inserted,
            "rows_updated": sales_updated,
            "distinct_asin": len(sales_asins),
            "date_range": _date_range([row.as_of_date for row in sales_rows]),
        },
        "inventory": {
            "source": str(inventory_path),
            "rows_inserted": inv_inserted,
            "rows_updated": inv_updated,
            "distinct_asin": len(inv_asins),
            "date_range": _date_range([row.snapshot_date for row in inventory_rows]),
        },
        "intersection": {
            "sales_inventory_asin_overlap": len(sales_asins & inv_asins),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
