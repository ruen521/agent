from __future__ import annotations

from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any, Callable
import uuid

from app.agents.prompts import TEAM_V1_MEMBER_PROMPTS, TEAM_V1_RAG_QUERY_TEMPLATES
from app.agents.team_v1.rag_store import LocalRagStore
from app.agents.team_v1.schemas import MemberExecutionRecord, TeamV1RagSummary, TeamV1Summary
from app.agents.team_v1.tool_summary import build_compact_tool_summary_text

TEAM_V1_MEMBER_ORDER = [
    "exception_investigator",
    "stockout_sentinel",
    "replenishment_planner",
    "markdown_clearance_coach",
]

TEAM_V1_MEMBER_LABELS = {
    "stockout_sentinel": "缺货哨兵",
    "replenishment_planner": "补货规划",
    "exception_investigator": "异常侦测",
    "markdown_clearance_coach": "清仓教练",
    "inventory_copilot": "综合聚合器",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_team_v1_plan(orchestration_options: dict[str, Any] | None) -> list[str]:
    options = orchestration_options if isinstance(orchestration_options, dict) else {}
    allow = options.get("member_allowlist") if isinstance(options.get("member_allowlist"), list) else []
    deny = options.get("member_denylist") if isinstance(options.get("member_denylist"), list) else []
    allow_set = {str(item).strip() for item in allow if str(item).strip()}
    deny_set = {str(item).strip() for item in deny if str(item).strip()}

    plan: list[str] = []
    for member_id in TEAM_V1_MEMBER_ORDER:
        if allow_set and member_id not in allow_set:
            continue
        if member_id in deny_set:
            continue
        plan.append(member_id)

    if not plan:
        return list(TEAM_V1_MEMBER_ORDER)
    return plan


def make_run_id() -> str:
    return f"teamv1-{uuid.uuid4().hex[:12]}"


def rag_root_dir(project_root: Path) -> Path:
    return project_root / "data" / "team_v1_runs"


def build_rag_store(*, run_id: str, project_root: Path) -> LocalRagStore:
    return LocalRagStore(run_id=run_id, root_dir=rag_root_dir(project_root))


def rag_query_for_member(
    *,
    member_id: str,
    objective: str,
    shared_keywords: list[str],
) -> str:
    template = TEAM_V1_RAG_QUERY_TEMPLATES.get(member_id, "请检索与当前任务相关的库存证据")
    keywords_text = "、".join([item for item in shared_keywords if item])
    if keywords_text:
        return f"{template}。目标：{objective}。关键词：{keywords_text}"
    return f"{template}。目标：{objective}。"


def _retrieval_context_text(member_id: str, hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "RAG检索结果：无可复用证据。"
    lines = [
        f"RAG检索结果（成员={TEAM_V1_MEMBER_LABELS.get(member_id, member_id)}，共{len(hits)}条）："
    ]
    for index, hit in enumerate(hits, start=1):
        lines.append(
            f"{index}. [{hit.get('evidence_id', '-')}] {hit.get('title_cn', '-')}: {hit.get('content_excerpt', '')}"
        )
    return "\n".join(lines)


def _tool_content_summary(tool_output: dict[str, Any]) -> str:
    return build_compact_tool_summary_text(tool_output, max_chars=2800)


def execute_member(
    *,
    member_id: str,
    base_state: dict[str, Any],
    objective: str,
    rag_store: LocalRagStore,
    specialist_runner: Callable[[str, dict[str, Any]], dict[str, Any]],
    query_rewrite_fn: Callable[..., dict[str, Any]] | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    started_at = utc_now_iso()
    started_ts = time.perf_counter()
    shared_outputs = base_state.get("team_v1_member_tool_outputs") or {}
    prior_member_ids = [
        str(item).strip()
        for item in shared_outputs.keys()
        if str(item).strip() and str(item).strip() != member_id
    ]
    query = ""
    retrieval_hits: list[dict[str, Any]] = []
    if prior_member_ids:
        initial_query = rag_query_for_member(
            member_id=member_id,
            objective=objective,
            shared_keywords=prior_member_ids,
        )
        query = initial_query
        safe_top_k = max(1, int(top_k))
        coarse_hits = [
            hit
            for hit in rag_store.search(initial_query, top_k=min(24, max(8, safe_top_k * 2)))
            if str(hit.get("member_id") or "") in prior_member_ids
        ]
        if query_rewrite_fn is not None:
            try:
                rewritten = query_rewrite_fn(
                    member_id=member_id,
                    objective=objective,
                    base_query=initial_query,
                    prior_member_ids=prior_member_ids,
                    coarse_hits=coarse_hits,
                    default_top_k=safe_top_k,
                )
                if isinstance(rewritten, dict):
                    rewritten_query = str(rewritten.get("query") or "").strip()
                    if rewritten_query:
                        query = rewritten_query
                    safe_top_k = max(1, min(12, int(rewritten.get("top_k", safe_top_k))))
            except Exception:
                safe_top_k = max(1, int(top_k))
        retrieval_hits = [
            hit
            for hit in rag_store.search(query, top_k=safe_top_k)
            if str(hit.get("member_id") or "") in prior_member_ids
        ]

    member_prompt = TEAM_V1_MEMBER_PROMPTS.get(member_id, "")
    retrieval_context = (
        "RAG检索结果：本轮无上游成员证据，按职责直接执行。"
        if not prior_member_ids
        else _retrieval_context_text(member_id, retrieval_hits)
    )
    enhanced_messages = [
        *list(base_state.get("messages", [])),
        {
            "role": "system",
            "content": (
                f"你当前身份：{TEAM_V1_MEMBER_LABELS.get(member_id, member_id)}。{member_prompt}\n"
                "你只能输出自己职责域结论，不要输出其他域模板。\n"
                f"{retrieval_context}"
            ),
        },
    ]
    member_state = {
        **base_state,
        "agent": member_id,
        "messages": enhanced_messages,
    }

    result_status = "success"
    error_code = ""
    error_message = ""
    response_text = ""
    summary = ""
    structured_output: dict[str, Any] = {}
    tool_outputs: dict[str, Any] = {}
    tool_trace: list[dict[str, Any]] = []

    try:
        result = specialist_runner(member_id, member_state)
        response_text = str(result.get("response_text") or "").strip()
        summary = str(result.get("reasoning") or response_text or "已完成").strip()
        structured_output = result.get("structured_output") if isinstance(result.get("structured_output"), dict) else {}
        tool_outputs = result.get("tool_output") if isinstance(result.get("tool_output"), dict) else {}
        traces = result.get("tool_trace")
        tool_trace = traces if isinstance(traces, list) else []
    except Exception as exc:
        result_status = "failed"
        error_code = "TEAM_V1_MEMBER_ERROR"
        error_message = f"{type(exc).__name__}: {str(exc)}"
        response_text = ""
        summary = f"{TEAM_V1_MEMBER_LABELS.get(member_id, member_id)}执行失败"
        structured_output = {}
        tool_outputs = {}
        tool_trace = []

    for trace in tool_trace or [{"tool": "unknown"}]:
        tool_name = str(trace.get("tool") or "unknown")
        rag_store.append_evidence(
            member_id=member_id,
            tool_name=tool_name,
            title_cn=f"{TEAM_V1_MEMBER_LABELS.get(member_id, member_id)}-{tool_name}-证据",
            content_text_cn=(
                f"成员结论：{response_text or summary}\n"
                f"工具输出摘要：{_tool_content_summary(tool_outputs)}"
            ),
            raw_json=tool_outputs,
        )

    ended_at = utc_now_iso()
    latency_ms = round((time.perf_counter() - started_ts) * 1000, 2)
    execution = MemberExecutionRecord(
        member_id=member_id,
        member_label=TEAM_V1_MEMBER_LABELS.get(member_id, member_id),
        result_status=result_status,
        summary=summary,
        response_text=response_text,
        structured_output=structured_output,
        tool_outputs=tool_outputs,
        retrieval_query=query,
        retrieval_hits=retrieval_hits,
        tool_trace=tool_trace,
        started_at=started_at,
        ended_at=ended_at,
        latency_ms=latency_ms,
        error_code=error_code,
        error_message=error_message,
    )
    return execution.model_dump()


def build_team_summary(execution: list[dict[str, Any]]) -> dict[str, Any]:
    success = [item for item in execution if str(item.get("result_status") or "").lower() == "success"]
    failed = [item for item in execution if str(item.get("result_status") or "").lower() == "failed"]
    summary = TeamV1Summary(
        success_count=len(success),
        failure_count=len(failed),
        partial_success_count=0,
        successful_members=[str(item.get("member_id") or "") for item in success],
        failed_members=[
            {
                "member_id": str(item.get("member_id") or ""),
                "result_status": str(item.get("result_status") or ""),
                "error_code": str(item.get("error_code") or ""),
            }
            for item in failed
        ],
    )
    return summary.model_dump()


def build_rag_summary(*, rag_store: LocalRagStore, retrieval_trace: list[dict[str, Any]]) -> dict[str, Any]:
    summary = TeamV1RagSummary(
        run_dir=str(rag_store.run_dir),
        evidence_count=len(rag_store.list_evidence()),
        retrieval_event_count=len(retrieval_trace),
    )
    return summary.model_dump()


def build_workflow_results(execution: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in execution:
        if not isinstance(item, dict):
            continue
        status = "DONE" if str(item.get("result_status") or "").lower() == "success" else "FAILED"
        rows.append(
            {
                "agent_id": str(item.get("member_id") or ""),
                "label": str(item.get("member_label") or item.get("member_id") or "成员"),
                "status": status,
                "summary": str(item.get("summary") or ""),
                "response_text": str(item.get("response_text") or ""),
                "started_at": str(item.get("started_at") or ""),
                "finished_at": str(item.get("ended_at") or ""),
                "structured_output": item.get("structured_output") if isinstance(item.get("structured_output"), dict) else {},
            }
        )
    return rows
