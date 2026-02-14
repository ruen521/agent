from __future__ import annotations

from app.tools.inventory_tools import inventory_markdown_calculator


def test_markdown_formula_for_45_to_60_days_uses_10pct_and_1_5x() -> None:
    item = {
        "SKU": "T-001",
        "CurrentStock": 55,
        "DailySalesVelocity": 1.0,
        "UnitCost": 10.0,
        "SellingPrice": 15.0,
    }

    # use existing calculator logic by monkeypatching repository import
    from app.tools import inventory_tools as module

    old_get_inventory_items = module.get_inventory_items
    try:
        module.get_inventory_items = lambda *args, **kwargs: [item]
        result = inventory_markdown_calculator(sku="T-001")
        assert result["count"] == 1
        row = result["items"][0]
        assert row["recommended_markdown"] == 0.1
        assert row["expected_velocity_multiplier"] == 1.5
        assert row["revenue_at_markdown"] == 495.0
    finally:
        module.get_inventory_items = old_get_inventory_items

