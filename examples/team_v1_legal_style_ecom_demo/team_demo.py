from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.agents import graph


def _mock_route_tool_call(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "inventory_query":
        query_type = str(tool_args.get("query_type", "all"))
        if query_type == "stockout_risk":
            result = {
                "count": 2,
                "items": [
                    {
                        "SKU": "APP-000090",
                        "VendorID": "V001",
                        "days_until_stockout": 2,
                        "shortage_amount": 150,
                        "revenue_at_risk": 4291.0,
                        "urgency_level": "CRITICAL",
                        "vendor_name": "华东供应商A",
                        "vendor_phone": "13800000000",
                        "vendor_email": "a@vendor.com",
                        "vendor_lead_time_days": 5,
                    },
                    {
                        "SKU": "APP-000203",
                        "VendorID": "V002",
                        "days_until_stockout": 4,
                        "shortage_amount": 80,
                        "revenue_at_risk": 1472.0,
                        "urgency_level": "HIGH",
                        "vendor_name": "华南供应商B",
                        "vendor_phone": "13900000000",
                        "vendor_email": "b@vendor.com",
                        "vendor_lead_time_days": 7,
                    },
                ],
            }
        else:
            result = {
                "count": 3,
                "items": [
                    {
                        "SKU": "APP-000078",
                        "Category": "Home",
                        "SellingPrice": 99.0,
                        "UnitCost": 48.0,
                        "DailySalesVelocity": 0.1,
                        "LeadTimeDays": 10,
                        "ReorderPoint": 3,
                        "CurrentStock": 120,
                    },
                    {
                        "SKU": "APP-000090",
                        "Category": "Home",
                        "SellingPrice": 79.0,
                        "UnitCost": 42.0,
                        "DailySalesVelocity": 18.0,
                        "LeadTimeDays": 6,
                        "ReorderPoint": 20,
                        "CurrentStock": 22,
                    },
                    {
                        "SKU": "APP-000203",
                        "Category": "Beauty",
                        "SellingPrice": 39.0,
                        "UnitCost": 29.0,
                        "DailySalesVelocity": 12.0,
                        "LeadTimeDays": 8,
                        "ReorderPoint": 15,
                        "CurrentStock": 17,
                    },
                ],
            }
    elif tool_name == "inventory_replenishment":
        result = {
            "vendor_groups": [
                {
                    "vendor_id": "V001",
                    "vendor_name": "华东供应商A",
                    "total_cost": 12800.0,
                    "items": [
                        {
                            "SKU": "APP-000090",
                            "recommended_qty": 300,
                            "line_cost": 12600.0,
                            "expected_delivery_date": "2026-02-18",
                        }
                    ],
                }
            ],
            "total_cost": 12800.0,
            "target_safety_days": 14,
        }
    elif tool_name == "inventory_vendor_info":
        result = {
            "count": 2,
            "vendors": [
                {
                    "VendorID": "V001",
                    "vendor_name": "华东供应商A",
                    "phone": "13800000000",
                },
                {
                    "VendorID": "V002",
                    "vendor_name": "华南供应商B",
                    "phone": "13900000000",
                },
            ],
        }
    elif tool_name == "inventory_markdown":
        result = {
            "count": 2,
            "items": [
                {
                    "SKU": "APP-000635",
                    "recommended_markdown": 0.5,
                    "days_to_clear": 45,
                    "net_benefit": 980.0,
                    "status": "AGGRESSIVE_CLEARANCE",
                },
                {
                    "SKU": "APP-000450",
                    "recommended_markdown": 0.3,
                    "days_to_clear": 30,
                    "net_benefit": 420.0,
                    "status": "MARKDOWN_NOW",
                },
            ],
        }
    else:
        raise ValueError(f"unsupported tool: {tool_name}")

    return {
        "tool": tool_name,
        "args": tool_args,
        "result": result,
        "bedrock_router_response": {
            "response": {
                "apiPath": f"/{tool_name}",
                "httpStatusCode": 200,
            }
        },
    }


def _mock_llm_response(agent_id: str, tool_summary: str, _messages: list[dict[str, str]], _tool_output: dict[str, Any] | None = None) -> str:
    if agent_id == "inventory_copilot":
        return f"[综合结论] {tool_summary}"
    return f"[{agent_id}] {tool_summary}"


def _patch_for_mock() -> None:
    graph.route_tool_call = _mock_route_tool_call
    graph._llm_response = _mock_llm_response
    graph.append_session_messages = lambda _sid, _msgs: None
    graph.get_session_messages = lambda _sid: []


def run_demo(*, live: bool) -> dict[str, Any]:
    if not live:
        _patch_for_mock()

    state = {
        "agent": "inventory_copilot",
        "input": "请执行一次固定巡检并输出综合建议",
        "session_id": "demo-team-v1",
        "collab_mode": "team",
        "orchestration_options": None,
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
    return graph.run_agent(state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="use real LLM and real tool router")
    args = parser.parse_args()

    result = run_demo(live=args.live)
    structured = result.get("structured_output") if isinstance(result.get("structured_output"), dict) else {}
    tool_output = result.get("tool_output") if isinstance(result.get("tool_output"), dict) else {}

    run_dir = str((structured.get("rag_summary") or {}).get("run_dir") or "")
    run_path = Path(run_dir) if run_dir else None
    if run_path:
        run_path.mkdir(parents=True, exist_ok=True)
        (run_path / "demo_output.json").write_text(
            json.dumps(
                {
                    "response_text": result.get("response_text"),
                    "structured_output": structured,
                    "tool_output": tool_output,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    print("team_version:", structured.get("team_version"))
    print("status:", structured.get("status"))
    print("members:", [item.get("member_id") for item in structured.get("team_execution", []) if isinstance(item, dict)])
    print("rag_run_dir:", run_dir)
    print("rag_evidence_count:", len(tool_output.get("rag_corpus", []) if isinstance(tool_output.get("rag_corpus"), list) else []))


if __name__ == "__main__":
    main()
