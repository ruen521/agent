from __future__ import annotations

from app.data.repository import load_data
from app.tools.inventory_tools import (
    inventory_markdown_calculator,
    inventory_query_tool,
    inventory_replenishment_tool,
    inventory_vendor_info_tool,
)
from app.tools.stats import stats_calculator


def setup_module() -> None:
    load_data()


def test_inventory_query_stockout_risk() -> None:
    result = inventory_query_tool(query_type="stockout_risk")
    assert result["count"] > 0
    for item in result["items"]:
        assert item["days_until_stockout"] <= 7
        assert "revenue_at_risk" in item


def test_inventory_replenishment_plan() -> None:
    plan = inventory_replenishment_tool()
    assert "vendor_groups" in plan
    for group in plan["vendor_groups"]:
        assert "meets_minimum_order" in group


def test_inventory_vendor_info() -> None:
    result = inventory_vendor_info_tool(vendor_id="V001")
    assert result["count"] == 1
    assert result["vendors"][0]["VendorID"] == "V001"


def test_inventory_markdown_calculator() -> None:
    result = inventory_markdown_calculator(sku="HOL-CTREE-6FT")
    assert result["count"] == 1
    item = result["items"][0]
    assert "recommended_markdown" in item
    assert "days_to_clear" in item


def test_stats_calculator() -> None:
    stats = stats_calculator()
    assert stats["total_skus"] == 30
    assert stats["total_categories"] == 9
