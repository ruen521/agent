from __future__ import annotations

import logging
from typing import Any
from statistics import median

try:  # pragma: no cover - depends on optional dependency
    from langgraph.graph import END, StateGraph
    _LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover - handled at runtime
    END = None
    StateGraph = None
    _LANGGRAPH_AVAILABLE = False

from app.agents.memory import append_session_messages, get_session_messages
from app.agents.prompts import PROMPTS
from app.agents.state import AgentState
from app.core.context import agent_ctx
from app.llm.qingyun_client import QingyunChatClient
from app.tools.inventory_tools import (
    inventory_markdown_calculator,
    inventory_query_tool,
    inventory_replenishment_tool,
    inventory_vendor_info_tool,
)

logger = logging.getLogger("app.agents")
_llm = QingyunChatClient()


def _summarize_stockout(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No stockout risks detected."
    top = items[:3]
    lines = [
        f"{item['SKU']} ({item['days_until_stockout']} days, ${item['revenue_at_risk']} risk)"
        for item in top
    ]
    return "Top risks: " + ", ".join(lines)


def _stockout_actions(item: dict[str, Any]) -> list[str]:
    actions = []
    if item["urgency_level"] in {"CRITICAL", "HIGH"}:
        actions.append("Expedite vendor order")
        actions.append("Consider temporary price increase")
    actions.append("Review substitute SKUs")
    return actions


def _render_stockout(tool_output: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    items = tool_output.get("items", [])
    risks = [
        {
            "sku": item["SKU"],
            "days": item["days_until_stockout"],
            "shortage": item["shortage_amount"],
            "revenue_at_risk": item["revenue_at_risk"],
            "urgency": item["urgency_level"],
            "vendor_name": item.get("vendor_name", ""),
            "vendor_phone": item.get("vendor_phone", ""),
            "vendor_email": item.get("vendor_email", ""),
            "lead_time_days": item.get("vendor_lead_time_days", 0),
            "actions": _stockout_actions(item),
        }
        for item in items
    ]
    summary = _summarize_stockout(items)
    return summary, {"risks": risks}


def _render_replenishment(tool_output: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    vendors = tool_output.get("vendor_groups", [])
    if not vendors:
        return "No replenishment required.", {"plan": tool_output}
    top_vendor = vendors[0]
    summary = (
        f"Prepared replenishment plan across {len(vendors)} vendors. "
        f"Top vendor {top_vendor.get('vendor_name')} total ${top_vendor.get('total_cost')}. "
        f"Target safety stock {tool_output.get('target_safety_days', 14)} days."
    )
    return summary, {"plan": tool_output}


def _render_exceptions(items: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    # 价格中位数按类别
    by_cat: dict[str, list[float]] = {}
    for item in items:
        by_cat.setdefault(item.get("Category", "UNKNOWN"), []).append(
            float(item.get("SellingPrice", item.get("UnitCost", 0)))
        )
    cat_medians = {c: median(v) for c, v in by_cat.items() if v}

    for item in items:
        sku = item["SKU"]
        velocity = float(item.get("DailySalesVelocity", 0))
        lead = float(item.get("LeadTimeDays", 0))
        reorder_point = float(item.get("ReorderPoint", 0))
        current_stock = float(item.get("CurrentStock", 0))
        selling_price = float(item.get("SellingPrice", item.get("UnitCost", 0)))
        unit_cost = float(item.get("UnitCost", 0))
        cat = item.get("Category", "UNKNOWN")
        cat_median = cat_medians.get(cat, selling_price or unit_cost)

        if velocity * lead > reorder_point * 1.2:
            anomalies.append(
                {
                    "sku": sku,
                    "type": "velocity_reorder_mismatch",
                    "note": "Velocity * lead time exceeds reorder point by >20%.",
                    "recommendation": "Review velocity and raise reorder point to 10-14 days coverage.",
                }
            )
        if selling_price > cat_median * 1.5 or selling_price < cat_median * 0.5:
            anomalies.append(
                {
                    "sku": sku,
                    "type": "price_outlier",
                    "note": f"Selling price deviates from category median by >50% (median {cat_median}).",
                    "recommendation": "Verify price entry and compare with vendor catalog.",
                }
            )
        if unit_cost >= selling_price:
            anomalies.append(
                {
                    "sku": sku,
                    "type": "negative_margin",
                    "note": "Unit cost is greater than or equal to selling price.",
                    "recommendation": "Correct price or cost; avoid negative margin sales.",
                }
            )
        if velocity > 0 and current_stock <= 0:
            anomalies.append(
                {
                    "sku": sku,
                    "type": "zero_stock_positive_velocity",
                    "note": "Velocity >0 but current stock is zero.",
                    "recommendation": "Check inventory sync and expedite replenishment.",
                }
            )
        if velocity == 0 and current_stock > reorder_point * 2:
            anomalies.append(
                {
                    "sku": sku,
                    "type": "stale_inventory",
                    "note": "No sales velocity with high on-hand stock.",
                    "recommendation": "Investigate listing status; consider markdown or delist.",
                }
            )

    summary = f"Detected {len(anomalies)} anomalies." if anomalies else "No anomalies detected."
    return summary, {"anomalies": anomalies}


def _render_markdown(tool_output: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    items = [item for item in tool_output.get("items", []) if item["recommended_markdown"] > 0]
    summary = (
        f"Found {len(items)} items needing markdown." if items else "No markdown needed."
    )
    return summary, {"markdowns": items}


def _copilot_tool_choice(text: str) -> tuple[str, dict[str, Any]]:
    lower = text.lower()
    if "stockout" in lower or "risk" in lower:
        return "inventory_query", {"query_type": "stockout_risk"}
    if "replenish" in lower or "order" in lower:
        return "inventory_replenishment", {}
    if "vendor" in lower:
        return "inventory_vendor_info", {}
    if "markdown" in lower or "clearance" in lower:
        return "inventory_markdown", {}
    return "inventory_query", {"query_type": "all"}


def _llm_or_fallback(
    agent_id: str, tool_summary: str, messages: list[dict[str, str]], tool_output: dict[str, Any] | None = None
) -> str:
    system_prompt = PROMPTS.get(agent_id, "")
    tool_context = ""
    if tool_output:
        import json

        tool_context = json.dumps(tool_output, ensure_ascii=False)[:4000]
    llm_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
        {"role": "system", "content": f"Tool summary: {tool_summary}"},
        {"role": "system", "content": f"Tool output JSON (truncated): {tool_context}"},
    ]
    return _llm.chat(llm_messages)


def load_session(state: AgentState) -> AgentState:
    history = get_session_messages(state["session_id"])
    messages = history + [{"role": "user", "content": state["input"]}]
    return {**state, "messages": messages}


def stockout_agent(state: AgentState) -> AgentState:
    token = agent_ctx.set("stockout_sentinel")
    tool_output = inventory_query_tool(query_type="stockout_risk")
    vendor_ids = {item.get("VendorID") for item in tool_output.get("items", []) if item.get("VendorID")}
    vendor_contacts = {}
    if vendor_ids:
        vendor_info = inventory_vendor_info_tool()
        for vendor in vendor_info.get("vendors", []):
            if vendor.get("VendorID") in vendor_ids:
                vendor_contacts[vendor["VendorID"]] = vendor
    summary, structured = _render_stockout(tool_output)
    response_text = _llm_or_fallback("stockout_sentinel", summary, state["messages"], tool_output)
    agent_ctx.reset(token)
    return {
        **state,
        "tool_output": {**tool_output, "vendor_contacts": vendor_contacts},
        "response_text": response_text,
        "reasoning": "Used stockout risk tool to identify urgent SKUs.",
        "structured_output": {**structured, "summary": summary, "vendors": list(vendor_contacts.values())},
    }


def replenishment_agent(state: AgentState) -> AgentState:
    token = agent_ctx.set("replenishment_planner")
    tool_output = inventory_replenishment_tool()
    vendor_info = inventory_vendor_info_tool()
    summary, structured = _render_replenishment(tool_output)
    response_text = _llm_or_fallback("replenishment_planner", summary, state["messages"], tool_output)
    agent_ctx.reset(token)
    return {
        **state,
        "tool_output": {**tool_output, "vendors": vendor_info.get("vendors", [])},
        "response_text": response_text,
        "reasoning": "Generated replenishment plan using low stock items.",
        "structured_output": {**structured, "summary": summary, "vendors": vendor_info.get("vendors", [])},
    }


def exception_agent(state: AgentState) -> AgentState:
    token = agent_ctx.set("exception_investigator")
    tool_output = inventory_query_tool(query_type="all")
    summary, structured = _render_exceptions(tool_output.get("items", []))
    response_text = _llm_or_fallback("exception_investigator", summary, state["messages"], structured)
    agent_ctx.reset(token)
    return {
        **state,
        "tool_output": tool_output,
        "response_text": response_text,
        "reasoning": "Scanned inventory data for anomalies.",
        "structured_output": {**structured, "summary": summary},
    }


def markdown_agent(state: AgentState) -> AgentState:
    token = agent_ctx.set("markdown_clearance_coach")
    tool_output = inventory_markdown_calculator()
    summary, structured = _render_markdown(tool_output)
    response_text = _llm_or_fallback("markdown_clearance_coach", summary, state["messages"], tool_output)
    agent_ctx.reset(token)
    return {
        **state,
        "tool_output": tool_output,
        "response_text": response_text,
        "reasoning": "Calculated markdown tiers based on days of supply.",
        "structured_output": {**structured, "summary": summary},
    }


def copilot_agent(state: AgentState) -> AgentState:
    token = agent_ctx.set("inventory_copilot")
    tool_name = state.get("forced_tool")
    tool_args = state.get("forced_args") or {}
    if not tool_name:
        tool_name, tool_args = _copilot_tool_choice(state["input"])

    if tool_name == "inventory_query":
        tool_output = inventory_query_tool(**tool_args)
    elif tool_name == "inventory_replenishment":
        tool_output = inventory_replenishment_tool(**tool_args)
    elif tool_name == "inventory_vendor_info":
        tool_output = inventory_vendor_info_tool(**tool_args)
    else:
        tool_output = inventory_markdown_calculator(**tool_args)

    summary = f"Used {tool_name} for inventory copilot response."
    response_text = _llm_or_fallback("inventory_copilot", summary, state["messages"], tool_output)
    agent_ctx.reset(token)
    return {
        **state,
        "tool_output": tool_output,
        "response_text": response_text,
        "reasoning": f"Selected tool {tool_name} based on user intent.",
        "structured_output": {"tool": tool_name, "result": tool_output},
    }


def forced_tool_agent(state: AgentState) -> AgentState:
    tool_name = state.get("forced_tool")
    tool_args = state.get("forced_args") or {}
    if tool_name == "inventory_query":
        tool_output = inventory_query_tool(**tool_args)
    elif tool_name == "inventory_replenishment":
        tool_output = inventory_replenishment_tool(**tool_args)
    elif tool_name == "inventory_vendor_info":
        tool_output = inventory_vendor_info_tool(**tool_args)
    else:
        tool_output = inventory_markdown_calculator(**tool_args)

    return {
        **state,
        "tool_output": tool_output,
        "response_text": "Forced tool executed.",
        "reasoning": f"Forced tool call: {tool_name}.",
        "structured_output": {"tool": tool_name, "result": tool_output},
    }


def finalize(state: AgentState) -> AgentState:
    append_session_messages(
        state["session_id"],
        [
            {"role": "user", "content": state["input"]},
            {"role": "assistant", "content": state.get("response_text", "")},
        ],
    )
    return state


def _route(state: AgentState) -> str:
    if state.get("forced_tool"):
        return "forced_tool"
    return state["agent"]


def build_graph():
    if not _LANGGRAPH_AVAILABLE:
        raise RuntimeError("langgraph is not installed")
    workflow = StateGraph(AgentState)
    workflow.add_node("load_session", load_session)
    workflow.add_node("stockout_sentinel", stockout_agent)
    workflow.add_node("replenishment_planner", replenishment_agent)
    workflow.add_node("exception_investigator", exception_agent)
    workflow.add_node("markdown_clearance_coach", markdown_agent)
    workflow.add_node("inventory_copilot", copilot_agent)
    workflow.add_node("forced_tool_node", forced_tool_agent)
    workflow.add_node("finalize", finalize)

    workflow.set_entry_point("load_session")
    workflow.add_conditional_edges(
        "load_session",
        _route,
        {
            "stockout_sentinel": "stockout_sentinel",
            "replenishment_planner": "replenishment_planner",
            "exception_investigator": "exception_investigator",
            "markdown_clearance_coach": "markdown_clearance_coach",
            "inventory_copilot": "inventory_copilot",
            "forced_tool": "forced_tool_node",
        },
    )

    for node in (
        "stockout_sentinel",
        "replenishment_planner",
        "exception_investigator",
        "markdown_clearance_coach",
        "inventory_copilot",
        "forced_tool_node",
    ):
        workflow.add_edge(node, "finalize")

    workflow.add_edge("finalize", END)
    return workflow.compile()


graph = build_graph() if _LANGGRAPH_AVAILABLE else None


def run_agent(state: AgentState) -> AgentState:
    if graph is None:
        raise RuntimeError("langgraph is not installed. Install it to use agents.")
    return graph.invoke(state)
