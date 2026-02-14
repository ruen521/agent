from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.team_v1 import runtime


def test_team_v1_execute_member_writes_rag_and_supports_retrieval(tmp_path: Path) -> None:
    rag_store = runtime.build_rag_store(run_id="unit-run", project_root=tmp_path)

    def runner_first(_member_id: str, _state: dict[str, Any]) -> dict[str, Any]:
        return {
            "response_text": "exception_investigator 已识别异常",
            "reasoning": "异常已识别",
            "structured_output": {"anomalies": [{"sku": "APP-1", "type": "price_outlier"}]},
            "tool_output": {"items": [{"SKU": "APP-1"}]},
            "tool_trace": [{"tool": "inventory_query"}],
        }

    first = runtime.execute_member(
        member_id="exception_investigator",
        base_state={"messages": [], "team_v1_member_tool_outputs": {}},
        objective="完成异常检测",
        rag_store=rag_store,
        specialist_runner=runner_first,
    )

    assert first["result_status"] == "success"
    assert isinstance(first["retrieval_hits"], list)
    assert isinstance(first["tool_outputs"], dict)

    evidence = rag_store.list_evidence()
    assert len(evidence) == 1
    assert evidence[0]["run_id"] == "unit-run"
    assert evidence[0]["member_id"] == "exception_investigator"
    assert evidence[0]["tool_name"] == "inventory_query"

    def runner_second(_member_id: str, _state: dict[str, Any]) -> dict[str, Any]:
        return {
            "response_text": "stockout_sentinel 已识别缺货风险",
            "reasoning": "缺货风险已识别",
            "structured_output": {"risks": [{"sku": "APP-1", "urgency": "HIGH"}]},
            "tool_output": {"items": [{"SKU": "APP-1", "days_until_stockout": 2}]},
            "tool_trace": [{"tool": "inventory_query"}],
        }

    second = runtime.execute_member(
        member_id="stockout_sentinel",
        base_state={"messages": [], "team_v1_member_tool_outputs": {"exception_investigator": first["tool_outputs"]}},
        objective="完成缺货风险检测",
        rag_store=rag_store,
        specialist_runner=runner_second,
    )

    assert second["result_status"] == "success"
    assert isinstance(second["retrieval_hits"], list)
    assert len(second["retrieval_hits"]) >= 1


def test_team_v1_summary_and_workflow_results() -> None:
    execution = [
        {
            "member_id": "exception_investigator",
            "member_label": "异常侦测",
            "result_status": "success",
            "summary": "ok",
            "response_text": "ok",
            "structured_output": {},
            "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": "2026-01-01T00:00:01+00:00",
        },
        {
            "member_id": "markdown_clearance_coach",
            "member_label": "清仓教练",
            "result_status": "failed",
            "summary": "failed",
            "response_text": "",
            "structured_output": {},
            "error_code": "TEAM_V1_MEMBER_ERROR",
            "started_at": "2026-01-01T00:00:01+00:00",
            "ended_at": "2026-01-01T00:00:02+00:00",
        },
    ]

    summary = runtime.build_team_summary(execution)
    workflow_results = runtime.build_workflow_results(execution)

    assert summary["success_count"] == 1
    assert summary["failure_count"] == 1
    assert len(summary["failed_members"]) == 1

    assert workflow_results[0]["status"] == "DONE"
    assert workflow_results[1]["status"] == "FAILED"
