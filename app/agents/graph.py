from __future__ import annotations

import json
import logging
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

try:  # pragma: no cover - depends on optional dependency
    from langgraph.graph import END, StateGraph

    _LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover - handled at runtime
    END = None
    StateGraph = None
    _LANGGRAPH_AVAILABLE = False

from app.agents.memory import append_session_messages, get_session_messages
from app.agents.prompts import (
    PROMPTS,
    TEAM_V1_AGGREGATOR_PROMPT,
    TEAM_V1_AGGREGATOR_QUERY_PROMPT,
    TEAM_V1_MEMBER_QUERY_REWRITE_PROMPT,
    TEAM_V1_RAG_QUERY_TEMPLATES,
)
from app.agents.state import AgentState
from app.agents.team_v1 import nodes as team_v1_nodes
from app.agents.team_v1.tool_summary import build_compact_tool_summary_text
from app.core.context import agent_ctx, session_id_ctx
from app.core.settings import settings
from app.llm.qingyun_client import QingyunChatClient
from app.tools.router import route_tool_call

logger = logging.getLogger("app.agents")
_llm = QingyunChatClient()
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_TOOL_ALIASES = {
    "query": "inventory_query",
    "inventory_query": "inventory_query",
    "inventory-query-tool": "inventory_query",
    "replenishment": "inventory_replenishment",
    "inventory_replenishment": "inventory_replenishment",
    "inventory-replenishment-tool": "inventory_replenishment",
    "vendor": "inventory_vendor_info",
    "inventory_vendor_info": "inventory_vendor_info",
    "inventory-vendor-info-tool": "inventory_vendor_info",
    "markdown": "inventory_markdown",
    "inventory_markdown": "inventory_markdown",
    "inventory-markdown-calculator": "inventory_markdown",
}

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
    by_cat_price: dict[str, list[float]] = {}
    by_cat_velocity: dict[str, list[float]] = {}
    for item in items:
        cat = item.get("Category", "UNKNOWN")
        price = float(item.get("SellingPrice", item.get("UnitCost", 0)) or 0)
        velocity = float(item.get("DailySalesVelocity", 0) or 0)
        by_cat.setdefault(cat, []).append(price)
        by_cat_price.setdefault(cat, []).append(price)
        by_cat_velocity.setdefault(cat, []).append(velocity)
    cat_medians = {c: median(v) for c, v in by_cat.items() if v}
    cat_stats: dict[str, dict[str, float]] = {}
    for cat, prices in by_cat_price.items():
        price_arr = np.array(prices, dtype=float)
        if price_arr.size:
            price_mean = float(np.mean(price_arr))
            price_std = float(np.std(price_arr))
            price_cv = float(price_std / price_mean) if price_mean else 0.0
        else:
            price_mean = price_std = price_cv = 0.0
        velocity_arr = np.array(by_cat_velocity.get(cat, []), dtype=float)
        if velocity_arr.size:
            velocity_mean = float(np.mean(velocity_arr))
            velocity_std = float(np.std(velocity_arr))
            velocity_cv = float(velocity_std / velocity_mean) if velocity_mean else 0.0
        else:
            velocity_mean = velocity_std = velocity_cv = 0.0
        cat_stats[cat] = {
            "price_mean": price_mean,
            "price_std": price_std,
            "price_cv": price_cv,
            "velocity_mean": velocity_mean,
            "velocity_std": velocity_std,
            "velocity_cv": velocity_cv,
            "price_count": float(price_arr.size),
            "velocity_count": float(velocity_arr.size),
        }

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
        stats = cat_stats.get(cat, {})
        price_mean = stats.get("price_mean", 0.0)
        price_std = stats.get("price_std", 0.0)
        price_cv = stats.get("price_cv", 0.0)
        price_count = int(stats.get("price_count", 0))
        velocity_mean = stats.get("velocity_mean", 0.0)
        velocity_std = stats.get("velocity_std", 0.0)
        velocity_cv = stats.get("velocity_cv", 0.0)
        velocity_count = int(stats.get("velocity_count", 0))

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
        if price_count >= 3 and price_std > 0:
            price_z = (selling_price - price_mean) / price_std
            price_z_threshold = 2.5 if price_cv > 0.6 else 2.0
            if abs(price_z) >= price_z_threshold:
                anomalies.append(
                    {
                        "sku": sku,
                        "type": "price_zscore_outlier",
                        "note": (
                            f"Price z-score {price_z:.2f} (category CV {price_cv:.2f})."
                        ),
                        "recommendation": "Validate price, check for data entry or vendor updates.",
                    }
                )
        if velocity_count >= 3 and velocity_std > 0:
            velocity_z = (velocity - velocity_mean) / velocity_std
            velocity_z_threshold = 2.5 if velocity_cv > 0.6 else 2.0
            if abs(velocity_z) >= velocity_z_threshold:
                anomalies.append(
                    {
                        "sku": sku,
                        "type": "velocity_zscore_outlier",
                        "note": (
                            f"Velocity z-score {velocity_z:.2f} (category CV {velocity_cv:.2f})."
                        ),
                        "recommendation": "Review demand signals and validate velocity calculation.",
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
    items = tool_output.get("items", [])
    markdowns = [item for item in items if item.get("recommended_markdown", 0) > 0]
    status_counts: dict[str, int] = {}
    for item in items:
        status = item.get("status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = (
        f"Markdown review: {len(markdowns)} items need markdown; "
        f"{status_counts.get('STOCKOUT_RISK', 0)} stockout risks, "
        f"{status_counts.get('HEALTHY', 0)} healthy, "
        f"{status_counts.get('MONITOR', 0)} monitor."
        if items
        else "No inventory items available for markdown review."
    )
    return summary, {"markdowns": markdowns, "items": items, "status_counts": status_counts}


def _copilot_tool_choice(text: str) -> tuple[str, dict[str, Any]]:
    lower = text.lower()
    if "velocity" in lower or "日销" in lower or "销量" in lower:
        return "inventory_query", {"query_type": "all"}
    if "stockout" in lower or "risk" in lower:
        return "inventory_query", {"query_type": "stockout_risk"}
    if "replenish" in lower or "order" in lower:
        return "inventory_replenishment", {}
    if "vendor" in lower:
        return "inventory_vendor_info", {}
    if "markdown" in lower or "clearance" in lower:
        return "inventory_markdown", {}
    return "inventory_query", {"query_type": "all"}


def _resolve_tool_name(tool_name: str | None) -> str:
    if not tool_name:
        return "inventory_query"
    return _TOOL_ALIASES.get(tool_name, tool_name)


def _trace_entry(tool_call: dict[str, Any]) -> dict[str, Any]:
    bedrock = tool_call.get("bedrock_router_response", {})
    response = bedrock.get("response", {}) if isinstance(bedrock, dict) else {}
    return {
        "tool": tool_call.get("tool", ""),
        "apiPath": response.get("apiPath", ""),
        "httpStatusCode": response.get("httpStatusCode", 200),
        "args": tool_call.get("args", {}),
    }


def _invoke_tool(tool_name: str, tool_args: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    tool_name = _resolve_tool_name(tool_name)
    call = route_tool_call(tool_name, tool_args or {})
    return call.get("result", {}), _trace_entry(call)


def _extract_json_payload(text: str) -> dict[str, Any] | list[Any] | None:
    raw = text.strip()
    try:
        payload = json.loads(raw)
        if isinstance(payload, (dict, list)):
            return payload
    except Exception:
        pass
    if "```" not in raw:
        return None
    segments = raw.split("```")
    for segment in segments:
        candidate = segment.replace("json", "", 1).strip()
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
            if isinstance(payload, (dict, list)):
                return payload
        except Exception:
            continue
    return None


def _coerce_plan_steps(payload: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if payload is None:
        return []
    raw_steps = payload
    if isinstance(payload, dict):
        raw_steps = payload.get("steps", [])
    if not isinstance(raw_steps, list):
        return []
    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps):
        if isinstance(raw_step, str):
            tool_name, args = _copilot_tool_choice(raw_step)
            steps.append(
                {
                    "task": raw_step,
                    "tool": _resolve_tool_name(tool_name),
                    "args": args,
                }
            )
            continue
        if not isinstance(raw_step, dict):
            continue
        tool = _resolve_tool_name(str(raw_step.get("tool", "")).strip())
        if tool not in {
            "inventory_query",
            "inventory_replenishment",
            "inventory_vendor_info",
            "inventory_markdown",
        }:
            continue
        args = raw_step.get("args", {})
        steps.append(
            {
                "task": str(raw_step.get("task", f"step-{index + 1}")),
                "tool": tool,
                "args": args if isinstance(args, dict) else {},
            }
        )
    return steps


def _heuristic_plan_steps(text: str) -> list[dict[str, Any]]:
    lower = text.lower()
    steps: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_step(tool: str, args: dict[str, Any], task: str) -> None:
        if tool in seen:
            return
        seen.add(tool)
        steps.append({"task": task, "tool": tool, "args": args})

    if any(keyword in lower for keyword in ("stockout", "risk", "缺货", "风险")):
        add_step("inventory_query", {"query_type": "stockout_risk"}, "识别缺货风险商品")
    if any(keyword in lower for keyword in ("replenish", "order", "补货", "采购")):
        add_step("inventory_replenishment", {}, "生成补货计划")
    if any(keyword in lower for keyword in ("vendor", "supplier", "供应商", "联系方式")):
        add_step("inventory_vendor_info", {}, "查询供应商信息")
    if any(keyword in lower for keyword in ("markdown", "clearance", "折扣", "清仓")):
        add_step("inventory_markdown", {}, "评估清仓与折扣策略")

    if not steps:
        tool_name, args = _copilot_tool_choice(text)
        add_step(_resolve_tool_name(tool_name), args, "获取库存概览")

    return steps

def _planner_steps(state: AgentState) -> list[dict[str, Any]]:
    forced = _resolve_tool_name(state.get("forced_tool")) if state.get("forced_tool") else None
    if forced:
        return [
            {
                "task": f"执行强制工具 {forced}",
                "tool": forced,
                "args": state.get("forced_args") or {},
            }
        ]

    recent_messages = state.get("messages", [])[-8:]
    transcript = "\n".join(f"{m.get('role')}: {m.get('content', '')}" for m in recent_messages)
    planner_prompt = (
        "你是多步工具规划器。只返回 JSON，不要额外文本。格式："
        '{"steps":[{"task":"...","tool":"inventory_query|inventory_replenishment|inventory_vendor_info|inventory_markdown","args":{...}}]}。'
        "如果问题简单，steps 只返回 1 步；复杂问题返回多步。"
    )
    try:
        plan_text = _llm.chat(
            [
                {"role": "system", "content": planner_prompt},
                {"role": "user", "content": transcript},
            ],
            temperature=0.0,
        )
    except Exception as exc:
        raise RuntimeError(f"规划失败：{type(exc).__name__}: {str(exc)}") from exc
    steps = _coerce_plan_steps(_extract_json_payload(plan_text))
    if not steps:
        raise RuntimeError("规划失败：模型未返回有效步骤")
    return steps[: settings.planner_max_steps]


def _past_steps_summary(past_steps: list[dict[str, Any]]) -> str:
    if not past_steps:
        return "暂无已执行步骤。"
    lines: list[str] = []
    for index, item in enumerate(past_steps, start=1):
        tool = str(item.get("tool", ""))
        task = str(item.get("task", ""))
        output = item.get("output", {})
        count = output.get("count") if isinstance(output, dict) else None
        suffix = f"，返回数量={count}" if count is not None else ""
        lines.append(f"{index}. {task} ({tool}){suffix}")
    return "\n".join(lines)


def _compose_copilot_response(state: AgentState) -> str:
    past_steps = state.get("past_steps", [])
    aggregate = {"past_steps": past_steps, "latest_tool_output": state.get("tool_output")}
    summary = f"已完成 {len(past_steps)} 个步骤。"
    return _llm_response("inventory_copilot", summary, state["messages"], aggregate)


def _replanner_decision(state: AgentState) -> dict[str, Any]:
    if state.get("replan_count", 0) >= settings.planner_max_replans:
        return {"response": _compose_copilot_response(state)}
    if not state.get("plan"):
        return {"response": _compose_copilot_response(state)}

    replanner_prompt = (
        "你是重规划器。基于目标、剩余计划和已执行结果，决定是继续执行还是直接给最终回答。"
        "只返回 JSON，不要额外文本。格式二选一："
        '{"response":"..."} 或 {"steps":[{"task":"...","tool":"inventory_query|inventory_replenishment|inventory_vendor_info|inventory_markdown","args":{...}}]}'
    )
    state_payload = {
        "objective": state["input"],
        "remaining_plan": state.get("plan", []),
        "past_steps_summary": _past_steps_summary(state.get("past_steps", [])),
    }
    try:
        decision_text = _llm.chat(
            [
                {"role": "system", "content": replanner_prompt},
                {"role": "user", "content": json.dumps(state_payload, ensure_ascii=False)},
            ],
            temperature=0.0,
        )
    except Exception as exc:
        raise RuntimeError(f"重规划失败：{type(exc).__name__}: {str(exc)}") from exc
    payload = _extract_json_payload(decision_text)
    if isinstance(payload, dict) and isinstance(payload.get("response"), str):
        response = payload["response"].strip()
        if not response:
            raise RuntimeError("重规划失败：模型返回了空响应")
        return {"response": response}
    steps = _coerce_plan_steps(payload)
    if steps:
        return {"steps": steps[: settings.planner_max_steps]}
    raise RuntimeError("重规划失败：模型未返回有效响应或步骤")


def _llm_response(
    agent_id: str, tool_summary: str, messages: list[dict[str, str]], tool_output: dict[str, Any] | None = None
) -> str:
    system_prompt = PROMPTS.get(agent_id, "")
    is_team_v1_aggregate = (
        agent_id == "inventory_copilot"
        and isinstance(tool_output, dict)
        and tool_output.get("team_version") == "v1"
    )
    tool_context = ""
    if tool_output and not is_team_v1_aggregate:
        tool_context = build_compact_tool_summary_text(tool_output, max_chars=2600)
    llm_messages = [
        {"role": "system", "content": "所有回复必须使用中文，简洁清晰。"},
        {"role": "system", "content": system_prompt},
    ]

    if is_team_v1_aggregate:
        team_summary = tool_output.get("team_summary", {})
        rag_summary = tool_output.get("rag_summary", {})
        member_raw_conclusions = tool_output.get("member_raw_conclusions", [])
        aggregate_rag_hits = tool_output.get("aggregate_rag_hits", [])
        llm_messages.extend(
            [
                {
                    "role": "system",
                    "content": TEAM_V1_AGGREGATOR_PROMPT,
                },
                {
                    "role": "system",
                    "content": f"team_summary={json.dumps(team_summary, ensure_ascii=False)}",
                },
                {
                    "role": "system",
                    "content": f"member_raw_conclusions={json.dumps(member_raw_conclusions, ensure_ascii=False)}",
                },
                {
                    "role": "system",
                    "content": f"rag_summary={json.dumps(rag_summary, ensure_ascii=False)}",
                },
                {
                    "role": "system",
                    "content": f"aggregate_rag_hits={json.dumps(aggregate_rag_hits, ensure_ascii=False)}",
                },
            ]
        )
        llm_messages.extend(
            [
                *messages,
                {"role": "system", "content": f"Tool summary: {tool_summary}"},
            ]
        )
        response = _llm.chat(llm_messages).strip()
        if not response:
            raise RuntimeError(f"LLM_EMPTY_RESPONSE: {agent_id} 模型返回空内容")
        return response

    llm_messages.extend(
        [
            *messages,
            {"role": "system", "content": f"Tool summary: {tool_summary}"},
            {"role": "system", "content": f"Tool structured summary (SKU主键+关键指标): {tool_context}"},
        ]
    )
    response = _llm.chat(llm_messages).strip()
    if not response:
        raise RuntimeError(f"LLM_EMPTY_RESPONSE: {agent_id} 模型返回空内容")
    return response


def _team_v1_aggregate_rag_query(
    objective: str,
    member_raw_conclusions: list[dict[str, Any]],
    team_summary: dict[str, Any],
) -> str:
    payload = {
        "objective": objective,
        "team_summary": team_summary,
        "member_raw_conclusions": member_raw_conclusions,
    }
    try:
        query_text = _llm.chat(
            [
                {"role": "system", "content": TEAM_V1_AGGREGATOR_QUERY_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.0,
        ).strip()
        query_payload = _extract_json_payload(query_text)
        if isinstance(query_payload, dict):
            query = str(query_payload.get("query") or "").strip()
            if query:
                return query
        if query_text:
            return query_text.splitlines()[0][:200]
    except Exception:
        pass
    template = TEAM_V1_RAG_QUERY_TEMPLATES.get("inventory_copilot", "检索跨成员关键证据")
    return f"{template}。目标：{objective}。"


def _team_v1_member_rag_query_rewrite(
    *,
    member_id: str,
    objective: str,
    base_query: str,
    prior_member_ids: list[str],
    coarse_hits: list[dict[str, Any]],
    default_top_k: int,
) -> dict[str, Any]:
    payload = {
        "member_id": member_id,
        "objective": objective,
        "base_query": base_query,
        "prior_member_ids": prior_member_ids,
        "coarse_hits": coarse_hits[:8],
        "default_top_k": default_top_k,
    }
    safe_top_k = max(1, min(12, int(default_top_k)))
    try:
        rewritten_text = _llm.chat(
            [
                {"role": "system", "content": TEAM_V1_MEMBER_QUERY_REWRITE_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.0,
        ).strip()
        rewritten_payload = _extract_json_payload(rewritten_text)
        if isinstance(rewritten_payload, dict):
            query = str(rewritten_payload.get("query") or "").strip() or base_query
            top_k_raw = rewritten_payload.get("top_k", safe_top_k)
            try:
                top_k = max(1, min(12, int(top_k_raw)))
            except (TypeError, ValueError):
                top_k = safe_top_k
            return {"query": query, "top_k": top_k}
    except Exception:
        pass
    return {"query": base_query, "top_k": safe_top_k}


def load_session(state: AgentState) -> AgentState:
    session_id_ctx.set(state["session_id"])
    collab_mode = str(state.get("collab_mode") or "").strip()
    if collab_mode in {"team", "team_v2"}:
        # Team 协同执行要求单轮无历史记忆，避免跨轮次口径污染。
        messages = [{"role": "user", "content": state["input"]}]
    else:
        history = get_session_messages(state["session_id"])
        messages = history + [{"role": "user", "content": state["input"]}]
    return {**state, "messages": messages}


def stockout_agent(state: AgentState) -> AgentState:
    token = agent_ctx.set("stockout_sentinel")
    tool_output, trace_query = _invoke_tool("inventory_query", {"query_type": "stockout_risk"})
    vendor_ids = {item.get("VendorID") for item in tool_output.get("items", []) if item.get("VendorID")}
    vendor_contacts = {}
    traces = [trace_query]
    if vendor_ids:
        vendor_info, trace_vendor = _invoke_tool("inventory_vendor_info", {})
        traces.append(trace_vendor)
        for vendor in vendor_info.get("vendors", []):
            if vendor.get("VendorID") in vendor_ids:
                vendor_contacts[vendor["VendorID"]] = vendor
    summary, structured = _render_stockout(tool_output)
    response_text = _llm_response("stockout_sentinel", summary, state["messages"], tool_output)
    agent_ctx.reset(token)
    return {
        **state,
        "tool_output": {**tool_output, "vendor_contacts": vendor_contacts},
        "response_text": response_text,
        "reasoning": "Used stockout risk tool to identify urgent SKUs.",
        "structured_output": {**structured, "summary": summary, "vendors": list(vendor_contacts.values())},
        "tool_trace": traces,
    }


def replenishment_agent(state: AgentState) -> AgentState:
    token = agent_ctx.set("replenishment_planner")
    tool_output, trace_repl = _invoke_tool("inventory_replenishment", {})
    vendor_info, trace_vendor = _invoke_tool("inventory_vendor_info", {})
    summary, structured = _render_replenishment(tool_output)
    response_text = _llm_response("replenishment_planner", summary, state["messages"], tool_output)
    agent_ctx.reset(token)
    return {
        **state,
        "tool_output": {**tool_output, "vendors": vendor_info.get("vendors", [])},
        "response_text": response_text,
        "reasoning": "Generated replenishment plan using low stock items.",
        "structured_output": {**structured, "summary": summary, "vendors": vendor_info.get("vendors", [])},
        "tool_trace": [trace_repl, trace_vendor],
    }


def exception_agent(state: AgentState) -> AgentState:
    token = agent_ctx.set("exception_investigator")
    tool_output, trace_query = _invoke_tool("inventory_query", {"query_type": "all"})
    summary, structured = _render_exceptions(tool_output.get("items", []))
    response_text = _llm_response("exception_investigator", summary, state["messages"], structured)
    agent_ctx.reset(token)
    return {
        **state,
        "tool_output": tool_output,
        "response_text": response_text,
        "reasoning": "Scanned inventory data for anomalies.",
        "structured_output": {**structured, "summary": summary},
        "tool_trace": [trace_query],
    }


def markdown_agent(state: AgentState) -> AgentState:
    token = agent_ctx.set("markdown_clearance_coach")
    tool_output, trace_markdown = _invoke_tool("inventory_markdown", {})
    summary, structured = _render_markdown(tool_output)
    response_text = _llm_response("markdown_clearance_coach", summary, state["messages"], tool_output)
    agent_ctx.reset(token)
    return {
        **state,
        "tool_output": tool_output,
        "response_text": response_text,
        "reasoning": "Calculated markdown tiers based on days of supply.",
        "structured_output": {**structured, "summary": summary},
        "tool_trace": [trace_markdown],
    }


def _run_specialist(agent_id: str, state: AgentState) -> AgentState:
    runner_map = {
        "stockout_sentinel": stockout_agent,
        "replenishment_planner": replenishment_agent,
        "exception_investigator": exception_agent,
        "markdown_clearance_coach": markdown_agent,
    }
    runner = runner_map.get(agent_id)
    if runner is None:
        return state
    specialist_state = {**state, "agent": agent_id}
    return runner(specialist_state)


def copilot_planner_node(state: AgentState) -> AgentState:
    token = agent_ctx.set("inventory_copilot")
    steps = _planner_steps(state)
    agent_ctx.reset(token)
    return {
        **state,
        "plan": steps,
        "reasoning": f"Planned {len(steps)} step(s) for inventory copilot.",
        "structured_output": {
            "objective": state["input"],
            "plan": steps,
            "past_steps": state.get("past_steps", []),
        },
    }


def copilot_team_v1_plan_node(state: AgentState) -> AgentState:
    return team_v1_nodes.copilot_team_v1_plan_node(
        state,
        project_root=PROJECT_ROOT,
    )


def copilot_team_v1_execute_node(state: AgentState) -> AgentState:
    return team_v1_nodes.copilot_team_v1_execute_node(
        state,
        specialist_runner=_run_specialist,
        query_rewrite_fn=_team_v1_member_rag_query_rewrite,
        project_root=PROJECT_ROOT,
    )


def copilot_team_v1_aggregate_node(state: AgentState) -> AgentState:
    return team_v1_nodes.copilot_team_v1_aggregate_node(
        state,
        llm_response_fn=_llm_response,
        rag_query_fn=_team_v1_aggregate_rag_query,
        project_root=PROJECT_ROOT,
    )


def copilot_execute_node(state: AgentState) -> AgentState:
    token = agent_ctx.set("inventory_copilot")
    plan = state.get("plan", [])
    if not plan:
        agent_ctx.reset(token)
        return state

    current_step = plan[0]
    tool_name = _resolve_tool_name(str(current_step.get("tool", "inventory_query")))
    tool_args = current_step.get("args", {})
    tool_output, trace = _invoke_tool(tool_name, tool_args if isinstance(tool_args, dict) else {})
    past_steps = [
        *state.get("past_steps", []),
        {
            "task": current_step.get("task", ""),
            "tool": tool_name,
            "args": tool_args if isinstance(tool_args, dict) else {},
            "output": tool_output,
        },
    ]
    agent_ctx.reset(token)
    return {
        **state,
        "plan": plan[1:],
        "past_steps": past_steps,
        "tool_output": tool_output,
        "tool_trace": [*state.get("tool_trace", []), trace],
        "steps_executed": state.get("steps_executed", 0) + 1,
        "reasoning": f"Executed step with {tool_name}.",
        "structured_output": {
            "objective": state["input"],
            "remaining_plan": plan[1:],
            "past_steps": past_steps,
        },
    }


def copilot_replanner_node(state: AgentState) -> AgentState:
    token = agent_ctx.set("inventory_copilot")
    if state.get("steps_executed", 0) >= settings.planner_max_steps:
        response_text = _compose_copilot_response(state)
        agent_ctx.reset(token)
        return {
            **state,
            "response_text": response_text,
            "reasoning": "Stopped due to planner_max_steps limit.",
            "structured_output": {
                "objective": state["input"],
                "status": "max_steps_reached",
                "past_steps": state.get("past_steps", []),
                "tool_trace": state.get("tool_trace", []),
            },
        }

    decision = _replanner_decision(state)
    if "response" in decision:
        response_text = str(decision.get("response", "")).strip()
        if not response_text:
            raise RuntimeError("重规划失败：模型返回了空响应")
        agent_ctx.reset(token)
        return {
            **state,
            "response_text": response_text,
            "reasoning": "Replanner returned final response.",
            "structured_output": {
                "objective": state["input"],
                "status": "completed",
                "past_steps": state.get("past_steps", []),
                "tool_trace": state.get("tool_trace", []),
            },
        }

    next_steps = decision.get("steps", state.get("plan", []))
    agent_ctx.reset(token)
    return {
        **state,
        "plan": next_steps if isinstance(next_steps, list) else state.get("plan", []),
        "replan_count": state.get("replan_count", 0) + 1,
        "reasoning": "Replanned remaining steps.",
        "structured_output": {
            "objective": state["input"],
            "remaining_plan": next_steps if isinstance(next_steps, list) else state.get("plan", []),
            "past_steps": state.get("past_steps", []),
        },
    }


def forced_tool_agent(state: AgentState) -> AgentState:
    tool_name = _resolve_tool_name(state.get("forced_tool"))
    tool_args = state.get("forced_args") or {}
    tool_output, trace = _invoke_tool(tool_name, tool_args)

    return {
        **state,
        "tool_output": tool_output,
        "response_text": "Forced tool executed.",
        "reasoning": f"Forced tool call: {tool_name}.",
        "structured_output": {"tool": tool_name, "result": tool_output},
        "tool_trace": [trace],
    }


def finalize(state: AgentState) -> AgentState:
    collab_mode = str(state.get("collab_mode") or "").strip()
    if collab_mode not in {"team", "team_v2"}:
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
    if state["agent"] == "inventory_copilot" and state.get("collab_mode") in {"team", "team_v2"}:
        return "inventory_copilot_team_v1"
    return state["agent"]


def _copilot_should_continue(state: AgentState) -> str:
    if state.get("response_text"):
        return "finalize"
    if state.get("plan"):
        return "copilot_execute"
    return "finalize"


def _copilot_team_v1_should_continue(state: AgentState) -> str:
    if state.get("team_v1_queue"):
        return "copilot_team_v1_execute"
    return "copilot_team_v1_aggregate"


def build_graph():
    if not _LANGGRAPH_AVAILABLE:
        raise RuntimeError("langgraph is not installed")
    workflow = StateGraph(AgentState)
    workflow.add_node("load_session", load_session)
    workflow.add_node("stockout_sentinel", stockout_agent)
    workflow.add_node("replenishment_planner", replenishment_agent)
    workflow.add_node("exception_investigator", exception_agent)
    workflow.add_node("markdown_clearance_coach", markdown_agent)
    workflow.add_node("copilot_planner", copilot_planner_node)
    workflow.add_node("copilot_team_v1_plan", copilot_team_v1_plan_node)
    workflow.add_node("copilot_team_v1_execute", copilot_team_v1_execute_node)
    workflow.add_node("copilot_team_v1_aggregate", copilot_team_v1_aggregate_node)
    workflow.add_node("copilot_execute", copilot_execute_node)
    workflow.add_node("copilot_replanner", copilot_replanner_node)
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
            "inventory_copilot": "copilot_planner",
            "inventory_copilot_team_v1": "copilot_team_v1_plan",
            "forced_tool": "forced_tool_node",
        },
    )

    workflow.add_edge("copilot_team_v1_plan", "copilot_team_v1_execute")
    workflow.add_conditional_edges(
        "copilot_team_v1_execute",
        _copilot_team_v1_should_continue,
        {
            "copilot_team_v1_execute": "copilot_team_v1_execute",
            "copilot_team_v1_aggregate": "copilot_team_v1_aggregate",
        },
    )
    workflow.add_edge("copilot_team_v1_aggregate", "finalize")

    workflow.add_edge("copilot_planner", "copilot_execute")
    workflow.add_edge("copilot_execute", "copilot_replanner")
    workflow.add_conditional_edges(
        "copilot_replanner",
        _copilot_should_continue,
        {
            "copilot_execute": "copilot_execute",
            "finalize": "finalize",
        },
    )

    for node in (
        "stockout_sentinel",
        "replenishment_planner",
        "exception_investigator",
        "markdown_clearance_coach",
        "forced_tool_node",
    ):
        workflow.add_edge(node, "finalize")

    workflow.add_edge("finalize", END)
    return workflow.compile()


graph = build_graph() if _LANGGRAPH_AVAILABLE else None


def _prepare_graph_state(state: AgentState) -> AgentState:
    state.setdefault("tool_trace", [])
    state.setdefault("collab_mode", "planner")
    state.setdefault("plan", [])
    state.setdefault("past_steps", [])
    state.setdefault("steps_executed", 0)
    state.setdefault("replan_count", 0)
    state.setdefault("orchestration_options", None)
    state.setdefault("team_v1_run_id", "")
    state.setdefault("team_v1_plan", [])
    state.setdefault("team_v1_queue", [])
    state.setdefault("team_v1_execution", [])
    state.setdefault("team_v1_started_at", "")
    state.setdefault("team_v1_member_tool_outputs", {})
    state.setdefault("team_v1_rag_retrieval_trace", [])
    state.setdefault("team_v1_rag_dir", "")
    return state


def run_agent(state: AgentState) -> AgentState:
    if graph is None:
        raise RuntimeError("langgraph is not installed. Install it to use agents.")
    prepared = _prepare_graph_state(state)
    return graph.invoke(prepared)


def run_agent_updates(state: AgentState):
    if graph is None:
        raise RuntimeError("langgraph is not installed. Install it to use agents.")
    prepared = _prepare_graph_state(state)
    return graph.stream(prepared, stream_mode="updates")
