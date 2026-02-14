from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agents import graph
from app.agents.team_v1.runtime import TEAM_V1_MEMBER_ORDER


def _fake_route_tool_call(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    api_map = {
        "inventory_query": "/query-inventory",
        "inventory_replenishment": "/calculate-replenishment",
        "inventory_vendor_info": "/get-vendor-info",
        "inventory_markdown": "/calculate-markdown",
    }

    if tool_name == "inventory_query":
        query_type = str(tool_args.get("query_type", "all"))
        if query_type == "stockout_risk":
            result = {
                "count": 1,
                "items": [
                    {
                        "SKU": "A-001",
                        "VendorID": "V001",
                        "days_until_stockout": 2,
                        "shortage_amount": 10,
                        "revenue_at_risk": 1200.0,
                        "urgency_level": "HIGH",
                        "vendor_name": "Vendor A",
                        "vendor_phone": "123",
                        "vendor_email": "a@example.com",
                        "vendor_lead_time_days": 5,
                    }
                ],
            }
        else:
            result = {
                "count": 2,
                "items": [
                    {
                        "SKU": "A-001",
                        "Category": "Home",
                        "SellingPrice": 30.0,
                        "UnitCost": 10.0,
                        "DailySalesVelocity": 6.0,
                        "LeadTimeDays": 5,
                        "ReorderPoint": 20,
                        "CurrentStock": 5,
                    },
                    {
                        "SKU": "A-002",
                        "Category": "Home",
                        "SellingPrice": 12.0,
                        "UnitCost": 8.0,
                        "DailySalesVelocity": 1.0,
                        "LeadTimeDays": 5,
                        "ReorderPoint": 8,
                        "CurrentStock": 30,
                    },
                ],
            }
    elif tool_name == "inventory_replenishment":
        result = {
            "vendor_groups": [
                {
                    "vendor_id": "V001",
                    "vendor_name": "Vendor A",
                    "total_cost": 120.0,
                    "items": [
                        {
                            "SKU": "A-001",
                            "recommended_qty": 50,
                            "line_cost": 120.0,
                            "expected_delivery_date": "2026-02-18",
                        }
                    ],
                }
            ],
            "total_cost": 120.0,
            "target_safety_days": 14,
        }
    elif tool_name == "inventory_vendor_info":
        result = {
            "count": 1,
            "vendors": [{"VendorID": "V001", "vendor_name": "Vendor A", "phone": "123"}],
        }
    elif tool_name == "inventory_markdown":
        result = {
            "count": 1,
            "items": [
                {
                    "SKU": "A-010",
                    "recommended_markdown": 0.2,
                    "days_to_clear": 20,
                    "net_benefit": 100.0,
                    "status": "MONITOR",
                }
            ],
        }
    else:
        raise AssertionError(f"unexpected tool: {tool_name}")

    return {
        "tool": tool_name,
        "args": tool_args,
        "result": result,
        "bedrock_router_response": {
            "response": {
                "apiPath": api_map[tool_name],
                "httpStatusCode": 200,
            }
        },
    }


def _patch_common(monkeypatch) -> None:
    monkeypatch.setattr(graph, "route_tool_call", _fake_route_tool_call)
    monkeypatch.setattr(graph, "append_session_messages", lambda session_id, messages: None)
    monkeypatch.setattr(graph, "get_session_messages", lambda session_id: [])


def _base_copilot_state(session_id: str, user_input: str) -> dict[str, Any]:
    return {
        "agent": "inventory_copilot",
        "input": user_input,
        "session_id": session_id,
        "messages": [],
        "tool_output": None,
        "response_text": "",
        "reasoning": "",
        "structured_output": {},
        "forced_tool": None,
        "forced_args": None,
        "tool_trace": [],
        "plan": [],
        "past_steps": [],
        "steps_executed": 0,
        "replan_count": 0,
    }


def test_heuristic_plan_can_generate_multi_step_plan() -> None:
    steps = graph._heuristic_plan_steps("请先看缺货风险，再生成补货计划，并给供应商联系方式")
    tools = [step["tool"] for step in steps]
    assert "inventory_query" in tools
    assert "inventory_replenishment" in tools
    assert "inventory_vendor_info" in tools
    assert len(steps) >= 3


def test_inventory_copilot_runs_plan_execute_replan_loop(monkeypatch) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(graph._llm, "chat", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no llm")))

    with pytest.raises(RuntimeError, match="规划失败"):
        graph.run_agent(
            _base_copilot_state(
                session_id="test-plan-loop",
                user_input="请先看缺货风险，再补货，并给供应商信息",
            )
        )


def test_inventory_copilot_team_mode_runs_team_v1(monkeypatch, tmp_path: Path) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(graph, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(graph, "_llm_response", lambda *args, **kwargs: "ok")

    state = graph.run_agent(
        {
            **_base_copilot_state("test-team-v1", "请做完整库存协同分析"),
            "collab_mode": "team",
        }
    )

    structured = state["structured_output"]
    tool_output = state["tool_output"]

    assert structured["team_version"] == "v1"
    assert structured["status"] == "team_v1_completed"
    assert structured["team_plan"] == TEAM_V1_MEMBER_ORDER
    assert len(structured["team_execution"]) == 4
    assert all(isinstance(item.get("retrieval_hits"), list) for item in structured["team_execution"])
    assert all(isinstance(item.get("tool_outputs"), dict) for item in structured["team_execution"])

    assert isinstance(tool_output.get("workflow_results"), list)
    assert len(tool_output["workflow_results"]) == 4
    assert isinstance(tool_output.get("member_tool_outputs"), dict)
    assert len(tool_output["member_tool_outputs"]) == 4
    assert isinstance(tool_output.get("rag_corpus"), list)
    assert len(tool_output["rag_corpus"]) >= 4
    assert isinstance(tool_output.get("rag_retrieval_trace"), list)
    assert len(tool_output["rag_retrieval_trace"]) == 5
    assert any(
        isinstance(item, dict) and item.get("member_id") == "inventory_copilot"
        for item in tool_output["rag_retrieval_trace"]
    )
    run_dir = Path(str((structured.get("rag_summary") or {}).get("run_dir") or ""))
    assert run_dir.exists() is False


def test_team_v1_allow_deny_filter(monkeypatch, tmp_path: Path) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(graph, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(graph, "_llm_response", lambda *args, **kwargs: "ok")

    state = graph.run_agent(
        {
            **_base_copilot_state("test-team-v1-filter", "做协同分析"),
            "collab_mode": "team",
            "orchestration_options": {
                "member_allowlist": ["stockout_sentinel", "replenishment_planner"],
                "member_denylist": ["replenishment_planner"],
            },
        }
    )

    assert state["structured_output"]["team_plan"] == ["stockout_sentinel"]
    assert state["structured_output"]["status"] == "team_v1_completed"


def test_specialist_agent_runs_business_tool_directly(monkeypatch) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(graph, "_llm_response", lambda *args, **kwargs: "ok")

    state = graph.run_agent(
        {
            **_base_copilot_state("test-specialist-refresh", "看缺货"),
            "agent": "stockout_sentinel",
        }
    )

    traces = state["tool_trace"]
    assert traces
    assert traces[0]["tool"] == "inventory_query"
