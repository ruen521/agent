from __future__ import annotations

if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from typing import Any

from app.data.repository import load_data
from app.tools.inventory_tools import inventory_query_tool


def stats_calculator() -> dict[str, Any]:
    all_items = inventory_query_tool(query_type="all")["items"]
    stockout_risks = [item for item in all_items if item["days_until_stockout"] <= 7]
    critical_risks = [item for item in stockout_risks if item["days_until_stockout"] < 3]
    low_stock_items = [item for item in all_items if item["CurrentStock"] < item["ReorderPoint"]]
    categories = sorted({item["Category"] for item in all_items})

    return {
        "total_skus": len(all_items),
        "stockout_risks": len(stockout_risks),
        "critical_risks": len(critical_risks),
        "low_stock_items": len(low_stock_items),
        "total_categories": len(categories),
        "categories": categories,
    }


def main() -> None:
    load_data()
    print(stats_calculator())


if __name__ == "__main__":
    main()
