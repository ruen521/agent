from __future__ import annotations

import json
from typing import Any


def _append_unique(target: list[str], value: Any, *, limit: int) -> None:
    text = str(value).strip() if value is not None else ""
    if not text or text in target:
        return
    if len(target) >= max(1, int(limit)):
        return
    target.append(text)


def _row_compact(row: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "SKU",
        "sku",
        "urgency_level",
        "urgency",
        "days_until_stockout",
        "days",
        "revenue_at_risk",
        "recommended_qty",
        "recommended_markdown",
        "status",
        "vendor_name",
        "expected_delivery_date",
        "line_cost",
        "total_cost",
        "net_benefit",
    ]
    compact: dict[str, Any] = {}
    for key in keep:
        if key in row and row.get(key) is not None:
            compact[key] = row.get(key)
    return compact


def build_compact_tool_summary_dict(
    tool_output: dict[str, Any] | None,
    *,
    max_skus: int = 40,
    max_vendors: int = 12,
    max_examples: int = 8,
) -> dict[str, Any]:
    if not isinstance(tool_output, dict):
        return {"overview": {"available": False}, "primary_skus": [], "vendors": [], "examples": []}

    overview: dict[str, Any] = {"available": True}
    for key in ("count", "total_cost", "target_safety_days", "created_at", "status"):
        value = tool_output.get(key)
        if isinstance(value, (str, int, float, bool)):
            overview[key] = value

    for key in ("items", "anomalies", "risks", "markdowns", "vendor_groups", "vendors"):
        value = tool_output.get(key)
        if isinstance(value, list):
            overview[f"{key}_count"] = len(value)

    primary_skus: list[str] = []
    vendors: list[str] = []
    examples: list[dict[str, Any]] = []

    def collect_from_rows(rows: list[Any]) -> None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            _append_unique(primary_skus, row.get("SKU") or row.get("sku"), limit=max_skus)
            _append_unique(
                vendors,
                row.get("vendor_name") or row.get("VendorName") or row.get("vendor") or row.get("supplier"),
                limit=max_vendors,
            )
            if len(examples) < max_examples:
                compact = _row_compact(row)
                if compact:
                    examples.append(compact)
            if len(primary_skus) >= max_skus and len(vendors) >= max_vendors and len(examples) >= max_examples:
                return

    for key in ("items", "anomalies", "risks", "markdowns", "vendors"):
        rows = tool_output.get(key)
        if isinstance(rows, list):
            collect_from_rows(rows)

    vendor_groups = tool_output.get("vendor_groups")
    if isinstance(vendor_groups, list):
        total_group_items = 0
        for group in vendor_groups:
            if not isinstance(group, dict):
                continue
            _append_unique(vendors, group.get("vendor_name") or group.get("vendor_id"), limit=max_vendors)
            items = group.get("items")
            if isinstance(items, list):
                total_group_items += len(items)
                collect_from_rows(items)
        if total_group_items:
            overview["vendor_group_item_count"] = total_group_items

    return {
        "overview": overview,
        "primary_skus": primary_skus[:max_skus],
        "vendors": vendors[:max_vendors],
        "examples": examples[:max_examples],
    }


def build_compact_tool_summary_text(
    tool_output: dict[str, Any] | None,
    *,
    max_chars: int = 3000,
) -> str:
    summary = build_compact_tool_summary_dict(tool_output)
    text = json.dumps(summary, ensure_ascii=False)
    limit = max(200, int(max_chars))
    return text if len(text) <= limit else text[: limit - 1] + "…"
