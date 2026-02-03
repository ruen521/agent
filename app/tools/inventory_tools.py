from __future__ import annotations

if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[2]))

import logging
import time
import math
from datetime import datetime, timezone, timedelta
from typing import Any

from app.core.context import tool_ctx
from app.core.metrics import metrics
from app.data.repository import (
    get_inventory_items,
    get_vendors,
    load_data,
    save_replenishment_plans,
)
from app.core.settings import settings

logger = logging.getLogger("app.tools")


def _vendor_map() -> dict[str, dict[str, Any]]:
    return {vendor["VendorID"]: vendor for vendor in get_vendors()}


def _days_until_stockout(item: dict[str, Any]) -> float:
    velocity = float(item.get("DailySalesVelocity", 0) or 0)
    if velocity <= 0:
        return float("inf")
    return round(float(item.get("CurrentStock", 0)) / velocity, 2)


def _urgency_level(days_until_stockout: float) -> str:
    if days_until_stockout < 3:
        return "CRITICAL"
    if days_until_stockout <= 5:
        return "HIGH"
    if days_until_stockout <= 7:
        return "MEDIUM"
    return "LOW"


def inventory_query_tool(
    query_type: str = "all",
    category: str | None = None,
    sku: str | None = None,
    limit: int | None = None,
    min_velocity: float | None = None,
    max_velocity: float | None = None,
) -> dict[str, Any]:
    token = tool_ctx.set("inventory_query_tool")
    start = time.perf_counter()
    vendors = _vendor_map()

    # 直接从数据库层获取过滤后的数据
    items = get_inventory_items(query_type, category, sku, limit)

    if min_velocity is not None:
        items = [i for i in items if float(i.get("DailySalesVelocity", 0) or 0) >= float(min_velocity)]
    if max_velocity is not None:
        items = [i for i in items if float(i.get("DailySalesVelocity", 0) or 0) <= float(max_velocity)]

    enriched: list[dict[str, Any]] = []
    for item in items:
        days_until = _days_until_stockout(item)
        vendor = vendors.get(item["VendorID"], {})
        shortage = max(0, item["ReorderPoint"] - item["CurrentStock"])
        selling_price = float(item.get("SellingPrice", item.get("UnitCost", 0)))
        margin_pct = float(item.get("GrossMarginPct", 0.35))
        revenue_at_risk = round(shortage * selling_price * margin_pct, 2)
        enriched.append(
            {
                **item,
                "days_until_stockout": days_until,
                "urgency_level": _urgency_level(days_until),
                "shortage_amount": shortage,
                "vendor_name": vendor.get("Name", ""),
                "vendor_phone": vendor.get("PhoneNumber", ""),
                "vendor_email": vendor.get("Email", ""),
                "vendor_lead_time_days": vendor.get("LeadTimeDays", 0),
                "revenue_at_risk": revenue_at_risk,
            }
        )

    duration = (time.perf_counter() - start) * 1000
    logger.info(
        "tool_complete",
        extra={"tool": "inventory_query_tool", "latency_ms": round(duration, 2), "status": 200},
    )
    metrics.observe_tool("inventory_query_tool", round(duration, 2))
    tool_ctx.reset(token)
    return {"count": len(enriched), "items": enriched}


def inventory_replenishment_tool(
    safety_days: int = 14,
    target_days: int | None = None,
    skus: list[str] | None = None,
) -> dict[str, Any]:
    token = tool_ctx.set("inventory_replenishment_tool")
    start = time.perf_counter()
    vendors = _vendor_map()
    if target_days is not None:
        safety_days = target_days
    base_items = inventory_query_tool(query_type="low_stock")["items"]
    items = base_items
    if skus:
        sku_set = {s.lower() for s in skus}
        items = [i for i in base_items if i["SKU"].lower() in sku_set]

    plans: list[dict[str, Any]] = []
    total_cost = 0.0

    for item in items:
        velocity = float(item.get("DailySalesVelocity", 0) or 0)
        lead_time = int(item.get("LeadTimeDays", 0) or 0)
        target_stock = (velocity * lead_time) + (velocity * safety_days)
        recommended_qty = max(0, int(round(target_stock - item.get("CurrentStock", 0))))
        if recommended_qty == 0:
            continue

        line_cost = recommended_qty * float(item.get("UnitCost", 0))
        total_cost += line_cost
        plans.append(
            {
                "SKU": item["SKU"],
                "VendorID": item["VendorID"],
                "recommended_qty": recommended_qty,
                "unit_cost": item.get("UnitCost", 0),
                "line_cost": round(line_cost, 2),
                "eta_days": lead_time,
                "expected_delivery_date": (datetime.now(timezone.utc) + timedelta(days=lead_time)).date().isoformat(),
            }
        )

    vendor_groups: dict[str, dict[str, Any]] = {}
    for plan in plans:
        vendor_id = plan["VendorID"]
        vendor = vendors.get(vendor_id, {})
        group = vendor_groups.setdefault(
            vendor_id,
            {
                "vendor_id": vendor_id,
                "vendor_name": vendor.get("Name", ""),
                "minimum_order": vendor.get("MinimumOrder", 0),
                "lead_time_days": vendor.get("LeadTimeDays", 0),
                "items": [],
                "total_cost": 0.0,
            },
        )
        group["items"].append(plan)
        group["total_cost"] += plan["line_cost"]

    for group in vendor_groups.values():
        group["total_cost"] = round(group["total_cost"], 2)
        group["meets_minimum_order"] = group["total_cost"] >= group["minimum_order"]
        if not group["meets_minimum_order"]:
            group["warning"] = "Below vendor minimum order value"

    replenishment_plan = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_cost": round(total_cost, 2),
        "target_safety_days": safety_days,
        "vendor_groups": list(vendor_groups.values()),
    }

    save_replenishment_plans([replenishment_plan])
    duration = (time.perf_counter() - start) * 1000
    logger.info(
        "tool_complete",
        extra={
            "tool": "inventory_replenishment_tool",
            "latency_ms": round(duration, 2),
            "status": 200,
        },
    )
    metrics.observe_tool("inventory_replenishment_tool", round(duration, 2))
    tool_ctx.reset(token)
    return replenishment_plan


def inventory_vendor_info_tool(vendor_id: str | None = None) -> dict[str, Any]:
    token = tool_ctx.set("inventory_vendor_info_tool")
    start = time.perf_counter()
    vendors = get_vendors()
    if vendor_id:
        filtered = [vendor for vendor in vendors if vendor["VendorID"].lower() == vendor_id.lower()]
        result = {"count": len(filtered), "vendors": filtered}
    else:
        result = {"count": len(vendors), "vendors": vendors}
    duration = (time.perf_counter() - start) * 1000
    logger.info(
        "tool_complete",
        extra={"tool": "inventory_vendor_info_tool", "latency_ms": round(duration, 2), "status": 200},
    )
    metrics.observe_tool("inventory_vendor_info_tool", round(duration, 2))
    tool_ctx.reset(token)
    return result


def inventory_markdown_calculator(
    sku: str | None = None,
    min_age_days: float | None = None,
    max_velocity: float | None = None,
) -> dict[str, Any]:
    token = tool_ctx.set("inventory_markdown_calculator")
    start = time.perf_counter()
    items = get_inventory_items()
    if sku:
        items = [item for item in items if item["SKU"].lower() == sku.lower()]
    if max_velocity is not None:
        items = [item for item in items if float(item.get("DailySalesVelocity", 0) or 0) <= max_velocity]

    results: list[dict[str, Any]] = []
    for item in items:
        velocity = float(item.get("DailySalesVelocity", 0) or 0)
        days_supply = float("inf") if velocity == 0 else round(item["CurrentStock"] / velocity, 2)

        if days_supply >= 180:
            markdown = 0.5
            multiplier = 3.0
        elif days_supply >= 90:
            markdown = 0.3
            multiplier = 2.5
        elif days_supply >= 60:
            markdown = 0.2
            multiplier = 2.0
        elif days_supply >= 45:
            markdown = 0.1
            multiplier = 1.5
        else:
            markdown = 0.0
            multiplier = 1.0

        expected_velocity = velocity * multiplier
        days_to_clear = float("inf") if expected_velocity == 0 else round(
            item["CurrentStock"] / expected_velocity, 2
        )
        selling_price = float(item.get("SellingPrice", item.get("UnitCost", 0)))
        revenue_at_markdown = round(item.get("CurrentStock", 0) * selling_price * (1 - markdown), 2)
        holding_pct = float(item.get("HoldingCostPct", settings.daily_holding_cost_pct))
        holding_cost_avoided = 0.0 if math.isinf(days_supply) else round(days_supply * holding_pct * selling_price, 2)
        net_benefit = round(
            revenue_at_markdown + holding_cost_avoided - (item.get("CurrentStock", 0) * float(item.get("UnitCost", 0))),
            2,
        )

        if min_age_days is not None and days_supply < min_age_days:
            continue

        results.append(
            {
                "SKU": item["SKU"],
                "days_of_supply": days_supply,
                "recommended_markdown": markdown,
                "expected_velocity_multiplier": multiplier,
                "days_to_clear": days_to_clear,
                "revenue_at_markdown": revenue_at_markdown,
                "holding_cost_avoided": holding_cost_avoided,
                "net_benefit": net_benefit,
            }
        )

    duration = (time.perf_counter() - start) * 1000
    logger.info(
        "tool_complete",
        extra={"tool": "inventory_markdown_calculator", "latency_ms": round(duration, 2), "status": 200},
    )
    metrics.observe_tool("inventory_markdown_calculator", round(duration, 2))
    tool_ctx.reset(token)
    return {"count": len(results), "items": results}


def main() -> None:
    load_data()
    print("inventory_query_tool(stockout_risk):")
    print(inventory_query_tool(query_type="stockout_risk"))
    print("\ninventory_replenishment_tool:")
    print(inventory_replenishment_tool())
    print("\ninventory_vendor_info_tool(V001):")
    print(inventory_vendor_info_tool(vendor_id="V001"))
    print("\ninventory_markdown_calculator(HOL-CTREE-6FT):")
    print(inventory_markdown_calculator(sku="HOL-CTREE-6FT"))


if __name__ == "__main__":
    main()
