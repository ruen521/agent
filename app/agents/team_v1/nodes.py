from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from app.agents.team_v1 import runtime
from app.core.metrics import metrics
from app.core.progress import progress_broker

logger = logging.getLogger("app.agents")


def _publish_progress(
    text: str,
    *,
    phase: str,
    member_id: str = "",
    tool: str = "",
    member_status: str = "",
    team_state: dict[str, Any] | None = None,
) -> None:
    progress_broker.publish(
        {
            "phase": phase,
            "text": str(text or "").strip(),
            "member_id": member_id,
            "tool": tool,
            "member_status": member_status,
            "team_state": team_state or {},
        }
    )


def copilot_team_v1_plan_node(
    state: dict[str, Any],
    *,
    project_root: Path,
) -> dict[str, Any]:
    run_id = str(state.get("team_v1_run_id") or "").strip() or runtime.make_run_id()
    plan = runtime.resolve_team_v1_plan(state.get("orchestration_options"))
    rag_store = runtime.build_rag_store(run_id=run_id, project_root=project_root)

    _publish_progress(
        f"Team V1 已规划完成，成员顺序：{' -> '.join(plan)}",
        phase="team",
        member_status="running",
        team_state={"members": plan, "running_member": ""},
    )
    return {
        **state,
        "team_v1_run_id": run_id,
        "team_v1_plan": plan,
        "team_v1_queue": list(plan),
        "team_v1_execution": [],
        "team_v1_member_tool_outputs": {},
        "team_v1_rag_retrieval_trace": [],
        "team_v1_started_at": runtime.utc_now_iso(),
        "team_v1_rag_dir": str(rag_store.run_dir),
        "reasoning": "Team V1 planning completed.",
        "structured_output": {
            "team_version": "v1",
            "status": "team_v1_running",
            "team_plan": plan,
            "team_execution": [],
            "team_summary": {},
            "rag_summary": {
                "run_dir": str(rag_store.run_dir),
                "evidence_count": 0,
                "retrieval_event_count": 0,
            },
        },
    }


def copilot_team_v1_execute_node(
    state: dict[str, Any],
    *,
    specialist_runner: Callable[[str, dict[str, Any]], dict[str, Any]],
    query_rewrite_fn: Callable[..., dict[str, Any]] | None = None,
    project_root: Path,
) -> dict[str, Any]:
    queue = list(state.get("team_v1_queue") or [])
    if not queue:
        return state

    member_id = str(queue.pop(0))
    run_id = str(state.get("team_v1_run_id") or "").strip()
    rag_store = runtime.build_rag_store(run_id=run_id, project_root=project_root)

    _publish_progress(
        f"{runtime.TEAM_V1_MEMBER_LABELS.get(member_id, member_id)}开始执行",
        phase="team",
        member_id=member_id,
        member_status="running",
        team_state={"members": state.get("team_v1_plan", []), "running_member": member_id},
    )

    options = state.get("orchestration_options") if isinstance(state.get("orchestration_options"), dict) else {}
    raw_top_k = options.get("team_v1_member_rag_top_k", 8)
    try:
        member_top_k = max(1, min(12, int(raw_top_k)))
    except (TypeError, ValueError):
        member_top_k = 8

    execution_row = runtime.execute_member(
        member_id=member_id,
        base_state=state,
        objective=str(state.get("input") or ""),
        rag_store=rag_store,
        specialist_runner=specialist_runner,
        query_rewrite_fn=query_rewrite_fn,
        top_k=member_top_k,
    )

    next_execution = [*list(state.get("team_v1_execution") or []), execution_row]
    member_outputs = dict(state.get("team_v1_member_tool_outputs") or {})
    member_outputs[member_id] = execution_row.get("tool_outputs") if isinstance(execution_row.get("tool_outputs"), dict) else {}

    rag_trace = [*list(state.get("team_v1_rag_retrieval_trace") or [])]
    rag_trace.append(
        {
            "member_id": member_id,
            "query": str(execution_row.get("retrieval_query") or ""),
            "hits": execution_row.get("retrieval_hits") if isinstance(execution_row.get("retrieval_hits"), list) else [],
        }
    )

    _publish_progress(
        f"{runtime.TEAM_V1_MEMBER_LABELS.get(member_id, member_id)}执行完成",
        phase="team",
        member_id=member_id,
        member_status="success" if str(execution_row.get("result_status") or "") == "success" else "failed",
        team_state={"members": state.get("team_v1_plan", []), "running_member": queue[0] if queue else ""},
    )
    metrics.observe_team_v1_member(
        member_id=member_id,
        latency_ms=float(execution_row.get("latency_ms") or 0.0),
        success=str(execution_row.get("result_status") or "").lower() == "success",
    )

    return {
        **state,
        "team_v1_queue": queue,
        "team_v1_execution": next_execution,
        "team_v1_member_tool_outputs": member_outputs,
        "team_v1_rag_retrieval_trace": rag_trace,
        "steps_executed": int(state.get("steps_executed", 0)) + 1,
        "reasoning": f"Team V1 executed {member_id}.",
    }


def copilot_team_v1_aggregate_node(
    state: dict[str, Any],
    *,
    llm_response_fn: Callable[[str, str, list[dict[str, str]], dict[str, Any] | None], str],
    rag_query_fn: Callable[[str, list[dict[str, Any]], dict[str, Any]], str],
    project_root: Path,
) -> dict[str, Any]:
    run_id = str(state.get("team_v1_run_id") or "")
    rag_store = runtime.build_rag_store(run_id=run_id, project_root=project_root)

    execution = list(state.get("team_v1_execution") or [])
    plan = list(state.get("team_v1_plan") or [])
    summary = runtime.build_team_summary(execution)

    failures = int(summary.get("failure_count") or 0)
    success = int(summary.get("success_count") or 0)
    if failures == 0:
        status = "team_v1_completed"
    elif success == 0:
        status = "team_v1_failed"
    else:
        status = "team_v1_partial"
    metrics.observe_team_v1_run(partial=status != "team_v1_completed")

    member_raw_conclusions = [
        {
            "member_id": str(item.get("member_id") or ""),
            "member_label": str(item.get("member_label") or ""),
            "result_status": str(item.get("result_status") or ""),
            "response_text_raw": str(item.get("response_text") or ""),
            "summary_raw": str(item.get("summary") or ""),
        }
        for item in execution
        if isinstance(item, dict)
    ]
    retrieval_query = rag_query_fn(str(state.get("input") or ""), member_raw_conclusions, summary)
    if not retrieval_query:
        retrieval_query = runtime.rag_query_for_member(
            member_id="inventory_copilot",
            objective=str(state.get("input") or ""),
            shared_keywords=[
                str(item.get("member_id") or "")
                for item in member_raw_conclusions
                if isinstance(item, dict)
            ],
        )
    aggregate_rag_hits = rag_store.search(retrieval_query, top_k=8)
    rag_trace = [*list(state.get("team_v1_rag_retrieval_trace") or [])]
    rag_trace.append(
        {
            "member_id": "inventory_copilot",
            "query": retrieval_query,
            "hits": aggregate_rag_hits,
        }
    )
    rag_summary = runtime.build_rag_summary(rag_store=rag_store, retrieval_trace=rag_trace)
    rag_corpus = rag_store.list_evidence()

    aggregate_tool_output = {
        "team_version": "v1",
        "team_plan": plan,
        "team_summary": summary,
        "rag_summary": rag_summary,
        "member_raw_conclusions": member_raw_conclusions,
        "aggregate_rag_hits": aggregate_rag_hits,
    }

    llm_summary = (
        f"Team V1 执行完成：成功 {summary.get('success_count', 0)}，"
        f"失败 {summary.get('failure_count', 0)}。"
    )
    try:
        response_text = llm_response_fn("inventory_copilot", llm_summary, state.get("messages", []), aggregate_tool_output)
    except Exception as exc:
        logger.warning("team_v1_aggregate_llm_failed", extra={"error": str(exc)})
        lines = [
            "Team V1 综合结论（降级模板）",
            f"执行状态：{status}",
            f"成功成员：{summary.get('success_count', 0)}，失败成员：{summary.get('failure_count', 0)}",
        ]
        for item in execution:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('member_label', item.get('member_id', '成员'))}: {item.get('summary', '无结论')}"
            )
        response_text = "\n".join(lines)

    _publish_progress(
        "Team V1 已完成综合聚合",
        phase="team",
        member_status="success" if status == "team_v1_completed" else "failed",
        team_state={"members": plan, "running_member": ""},
    )

    structured_output = {
        "team_version": "v1",
        "status": status,
        "team_plan": plan,
        "team_execution": execution,
        "team_summary": summary,
        "rag_summary": rag_summary,
    }

    tool_output = {
        "workflow_results": runtime.build_workflow_results(execution),
        "member_tool_outputs": dict(state.get("team_v1_member_tool_outputs") or {}),
        "rag_corpus": rag_corpus,
        "rag_retrieval_trace": rag_trace,
    }
    rag_store.clear_current_run()

    return {
        **state,
        "team_v1_rag_retrieval_trace": rag_trace,
        "response_text": response_text,
        "reasoning": "Team V1 aggregate response composed.",
        "structured_output": structured_output,
        "tool_output": tool_output,
    }
