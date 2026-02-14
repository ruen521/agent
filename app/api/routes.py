from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import math
import queue
import re
import threading
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from app.agents.lifecycle import get_agent_lifecycle, prepare_agent
from app.agents.prompts import PROMPT_PRESETS
from app.core.context import agent_ctx
from app.core.context import request_id_ctx, trace_id_ctx
from app.core.progress import progress_broker
from app.core.settings import settings
from app.agents.graph import run_agent, run_agent_updates
from app.data.repository import load_data
from app.core.metrics import metrics
from app.reports.schemas import ExportRequest
from app.reports.service import (
    create_export_job,
    dispatch_export_job,
    export_status_payload,
    resolve_download,
)
from app.spapi.client import SpApiClient
from app.tools.stats import stats_calculator

router = APIRouter()

AGENTS = [
    {
        "id": "stockout_sentinel",
        "name": "Stockout Sentinel Agent",
        "friendly_name": "Stockout Sentinel",
        "description": "Detects stockout risks and prioritizes urgent actions.",
        "status": "ready",
        "updated": "2026-02-03",
    },
    {
        "id": "replenishment_planner",
        "name": "Replenishment Planner Agent",
        "friendly_name": "Replenishment Planner",
        "description": "Generates optimized replenishment plans.",
        "status": "ready",
        "updated": "2026-02-03",
    },
    {
        "id": "exception_investigator",
        "name": "Exception Investigator Agent",
        "friendly_name": "Exception Investigator",
        "description": "Flags data anomalies and inconsistencies.",
        "status": "ready",
        "updated": "2026-02-03",
    },
    {
        "id": "markdown_clearance_coach",
        "name": "Markdown and Clearance Coach Agent",
        "friendly_name": "Markdown Coach",
        "description": "Recommends markdown strategies for aging inventory.",
        "status": "ready",
        "updated": "2026-02-03",
    },
    {
        "id": "inventory_copilot",
        "name": "Inventory Copilot Agent",
        "friendly_name": "Inventory Copilot",
        "description": "Conversational interface for inventory insights.",
        "status": "ready",
        "updated": "2026-02-03",
    },
]

for _agent in AGENTS:
    _agent["friendly_name_legacy"] = _agent["friendly_name"]

AGENT_ALIAS_MAP = {
    "stockout": "stockout_sentinel",
    "replenishment": "replenishment_planner",
    "exceptions": "exception_investigator",
    "markdown": "markdown_clearance_coach",
    "copilot": "inventory_copilot",
}

REVERSE_ALIAS_MAP = {v: k for k, v in AGENT_ALIAS_MAP.items()}
_ERROR_CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


def _resolve_agent(agent: str) -> str:
    if agent in {item["id"] for item in AGENTS}:
        return agent
    return AGENT_ALIAS_MAP.get(agent, agent)


def _resolve_collab_mode(parameters: dict[str, Any] | None) -> str:
    mode = str((parameters or {}).get("mode", "planner")).strip().lower()
    if mode == "team_v2":
        return "team"
    return mode if mode in {"planner", "team"} else "planner"


def _resolve_orchestration(parameters: dict[str, Any] | None) -> dict[str, Any] | None:
    orchestration = (parameters or {}).get("orchestration")
    return orchestration if isinstance(orchestration, dict) else None


def _resolve_input_text(raw_input: str, parameters: dict[str, Any] | None) -> str:
    preset_key = str((parameters or {}).get("prompt_preset", "")).strip()
    if preset_key:
        preset_prompt = PROMPT_PRESETS.get(preset_key)
        if preset_prompt:
            return preset_prompt
    return str(raw_input or "").strip()


def _build_agent_state(
    *,
    agent_id: str,
    input_text: str,
    session_id: str,
    collab_mode: str,
    orchestration_options: dict[str, Any] | None,
    forced_tool: Any,
    forced_args: Any,
) -> dict[str, Any]:
    return {
        "agent": agent_id,
        "input": input_text,
        "session_id": session_id,
        "collab_mode": collab_mode,
        "orchestration_options": orchestration_options,
        "messages": [],
        "tool_output": None,
        "response_text": "",
        "reasoning": "",
        "structured_output": {},
        "forced_tool": forced_tool,
        "forced_args": forced_args,
        "tool_trace": [],
        "plan": [],
        "past_steps": [],
        "steps_executed": 0,
        "replan_count": 0,
    }


class InvokeRequest(BaseModel):
    agent: str
    input: str
    session_id: str | None = None
    parameters: dict[str, Any] | None = None


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _parse_runtime_error(exc: Exception) -> tuple[str, str]:
    message = str(exc).strip()
    if ":" in message:
        head, tail = message.split(":", 1)
        code = head.strip()
        if _ERROR_CODE_PATTERN.match(code):
            parsed_message = tail.strip() or message
            return code, parsed_message
    return "AGENT_EXECUTION_ERROR", message or type(exc).__name__


def _agent_http_error(exc: Exception, *, status_code: int = 502) -> HTTPException:
    error_code, error_message = _parse_runtime_error(exc)
    metrics.observe_agent_error(error_code)
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": error_code,
            "error_message": error_message,
        },
    )


@router.on_event("startup")
async def _startup() -> None:
    load_data()
    for agent in AGENTS:
        prepare_agent(agent["id"])


@router.get("/agents/list")
async def list_agents() -> dict[str, Any]:
    agents_payload = []
    for agent in AGENTS:
        lifecycle = get_agent_lifecycle(agent["id"])
        aliases = lifecycle.get("aliases", {}) if isinstance(lifecycle, dict) else {}
        agents_payload.append(
            {
                **agent,
                "friendly_name": REVERSE_ALIAS_MAP.get(agent["id"], agent["friendly_name"]),
                "status": "PREPARED" if lifecycle.get("prepared") else "NOT_PREPARED",
                "updated": lifecycle.get("updated", agent["updated"]),
                "lifecycle": {
                    "prepared": lifecycle.get("prepared", False),
                    "version": f"v{lifecycle.get('current_version', 0)}",
                    "alias": settings.agent_default_alias,
                    "alias_target": aliases.get(settings.agent_default_alias, ""),
                },
            }
        )
    return {"success": True, "count": len(agents_payload), "agents": agents_payload}


@router.get("/agents/stats")
async def agent_stats(request: Request) -> dict[str, Any]:
    stats = stats_calculator()
    return {
        "success": True,
        "stats": stats,
        "request_id": _request_id(request),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/data/risks")
async def get_risks_data(request: Request, limit: int = 100) -> dict[str, Any]:
    """直接获取风险数据，不经过 Agent 和 LLM"""
    from app.tools.inventory_tools import inventory_query_tool

    tool_output = inventory_query_tool(query_type="stockout_risk", limit=limit)
    items = tool_output.get("items", [])

    risks = [
        {
            "sku": item["SKU"],
            "days": item["days_until_stockout"],
            "shortage": item["shortage_amount"],
            "revenue_at_risk": item["revenue_at_risk"],
            "urgency": item["urgency_level"],
        }
        for item in items
    ]

    return {
        "risks": risks,
        "count": len(risks),
        "request_id": _request_id(request),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/data/inventory")
async def get_inventory_data(
    request: Request,
    query_type: str = "all",
    category: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """直接获取库存数据，不经过 Agent 和 LLM"""
    from app.tools.inventory_tools import inventory_query_tool

    tool_output = inventory_query_tool(
        query_type=query_type, category=category, limit=limit
    )

    return {
        "items": tool_output.get("items", []),
        "count": tool_output.get("count", 0),
        "request_id": _request_id(request),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/agents/invoke")
async def invoke_agent(payload: InvokeRequest, request: Request) -> dict[str, Any]:
    resolved_agent = _resolve_agent(payload.agent)
    if resolved_agent not in {agent["id"] for agent in AGENTS}:
        raise HTTPException(status_code=404, detail="Unknown agent")

    session_id = payload.session_id or str(uuid.uuid4())
    forced_tool = (payload.parameters or {}).get("tool")
    forced_args = (payload.parameters or {}).get("args") if payload.parameters else None
    collab_mode = _resolve_collab_mode(payload.parameters)
    orchestration_options = _resolve_orchestration(payload.parameters)
    effective_input = _resolve_input_text(payload.input, payload.parameters)

    initial_state = _build_agent_state(
        agent_id=resolved_agent,
        input_text=effective_input,
        session_id=session_id,
        collab_mode=collab_mode,
        orchestration_options=orchestration_options,
        forced_tool=forced_tool,
        forced_args=forced_args,
    )

    token = agent_ctx.set(resolved_agent)
    try:
        state = run_agent(initial_state)
    except RuntimeError as exc:
        raise _agent_http_error(exc, status_code=502) from exc
    except Exception as exc:
        wrapped = RuntimeError(f"AGENT_EXECUTION_ERROR: {type(exc).__name__}: {str(exc)}")
        raise _agent_http_error(wrapped, status_code=500) from exc
    finally:
        agent_ctx.reset(token)

    short_name = REVERSE_ALIAS_MAP.get(resolved_agent, resolved_agent)

    return {
        "success": True,
        "agent": short_name,
        "response": {
            "text": state["response_text"],
            "reasoning": state["reasoning"],
            "structured_output": state["structured_output"],
            "tool_output": state.get("tool_output"),
            "tool_trace": state.get("tool_trace", []),
        },
        "response_text": state["response_text"],
        "session_id": session_id,
        "collab_mode": collab_mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": _request_id(request),
        "model": settings.qingyun_model,
    }


@router.post("/agents/invoke_stream")
async def invoke_agent_stream(payload: InvokeRequest, request: Request) -> StreamingResponse:
    resolved_agent = _resolve_agent(payload.agent)
    if resolved_agent not in {agent["id"] for agent in AGENTS}:
        raise HTTPException(status_code=404, detail="Unknown agent")

    session_id = payload.session_id or str(uuid.uuid4())
    forced_tool = (payload.parameters or {}).get("tool")
    forced_args = (payload.parameters or {}).get("args") if payload.parameters else None
    collab_mode = _resolve_collab_mode(payload.parameters)
    orchestration_options = _resolve_orchestration(payload.parameters)
    effective_input = _resolve_input_text(payload.input, payload.parameters)
    short_name = REVERSE_ALIAS_MAP.get(resolved_agent, resolved_agent)
    request_id = _request_id(request)

    initial_state = _build_agent_state(
        agent_id=resolved_agent,
        input_text=effective_input,
        session_id=session_id,
        collab_mode=collab_mode,
        orchestration_options=orchestration_options,
        forced_tool=forced_tool,
        forced_args=forced_args,
    )

    def _sse(event: str, data: dict[str, Any]) -> str:
        safe_data = _json_safe(data)
        return f"event: {event}\ndata: {json.dumps(safe_data, ensure_ascii=False)}\n\n"

    progress_broker.open(request_id)
    update_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

    def _worker() -> None:
        token = request_id_ctx.set(request_id)
        trace_token = trace_id_ctx.set(request_id)
        try:
            updates_iter = run_agent_updates(initial_state)
            for update in updates_iter:
                update_queue.put(("update", update))
            update_queue.put(("done", None))
        except Exception as exc:  # pragma: no cover - runtime dependent
            update_queue.put(("error", exc))
        finally:
            request_id_ctx.reset(token)
            trace_id_ctx.reset(trace_token)

    worker = threading.Thread(
        target=_worker,
        name=f"invoke_stream_worker_{request_id[:8]}",
        daemon=True,
    )
    worker.start()

    def _iter_node_events(update: dict[str, Any], final_state_ref: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(update, dict) or not update:
            return []
        payloads: list[dict[str, Any]] = []
        for node_name, node_state in update.items():
            if not isinstance(node_state, dict):
                continue

            event_payload: dict[str, Any] = {"node": node_name}
            trace = node_state.get("tool_trace")
            if isinstance(trace, list) and trace:
                latest_trace = trace[-1] if isinstance(trace[-1], dict) else {}
                if latest_trace:
                    event_payload["latest_tool"] = str(latest_trace.get("tool") or "")
                    event_payload["latest_tool_status"] = latest_trace.get("httpStatusCode")

            if node_name == "copilot_team_v1_plan":
                event_payload["run_id"] = node_state.get("team_v1_run_id", "")
                event_payload["team_plan"] = node_state.get("team_v1_plan", [])
            elif node_name == "copilot_team_v1_execute":
                execution = node_state.get("team_v1_execution", [])
                latest_step = execution[-1] if isinstance(execution, list) and execution else None
                event_payload["latest_step"] = latest_step
                event_payload["remaining"] = node_state.get("team_v1_queue", [])
                if isinstance(latest_step, dict):
                    traces = latest_step.get("tool_trace")
                    latest_trace = traces[-1] if isinstance(traces, list) and traces and isinstance(traces[-1], dict) else {}
                    event_payload["member_id"] = str(latest_step.get("member_id") or "")
                    event_payload["member_status"] = str(latest_step.get("result_status") or "")
                    event_payload["error_code"] = str(latest_step.get("error_code") or "")
                    event_payload["error_message"] = str(latest_step.get("error_message") or "")
                    event_payload["tool"] = str(latest_trace.get("tool") or "")
                    event_payload["latency_ms"] = latest_step.get("latency_ms")
            elif node_name == "copilot_team_v1_aggregate":
                event_payload["status"] = node_state.get("structured_output", {}).get("status", "")
                event_payload["team_summary"] = node_state.get("structured_output", {}).get("team_summary", {})
                event_payload["rag_summary"] = node_state.get("structured_output", {}).get("rag_summary", {})

            if node_name == "finalize":
                final_state_ref["state"] = node_state

            payloads.append(event_payload)
        return payloads

    def event_stream():
        final_state_ref: dict[str, Any] = {"state": None}
        worker_done = False
        try:
            agent_ctx.set(resolved_agent)
            yield _sse(
                "start",
                {
                    "agent": short_name,
                    "session_id": session_id,
                    "collab_mode": collab_mode,
                    "request_id": request_id,
                },
            )

            while True:
                agent_ctx.set(resolved_agent)
                for progress_item in progress_broker.drain(request_id, limit=100):
                    if not isinstance(progress_item, dict):
                        continue
                    yield _sse(
                        "update",
                        {
                            "node": "runtime_progress",
                            "status_text": str(progress_item.get("text") or ""),
                            "phase": str(progress_item.get("phase") or ""),
                            "member_id": str(progress_item.get("member_id") or ""),
                            "tool": str(progress_item.get("tool") or ""),
                            "member_status": str(progress_item.get("member_status") or ""),
                            "team_state": progress_item.get("team_state") if isinstance(progress_item.get("team_state"), dict) else {},
                            "timestamp": str(progress_item.get("timestamp") or ""),
                        },
                    )

                if worker_done and update_queue.empty():
                    break

                try:
                    item_type, item_payload = update_queue.get(timeout=0.25)
                except queue.Empty:
                    continue

                if item_type == "update":
                    for event_payload in _iter_node_events(item_payload, final_state_ref):
                        yield _sse("update", event_payload)
                    continue

                if item_type == "error":
                    raise item_payload

                if item_type == "done":
                    worker_done = True
                    continue

            final_state = final_state_ref["state"]
            if not isinstance(final_state, dict):
                yield _sse(
                    "error",
                    {
                        "success": False,
                        "error_code": "STREAM_NO_FINAL_STATE",
                        "error_message": "流式执行未返回最终状态",
                        "request_id": request_id,
                    },
                )
                return

            final_text = str(final_state.get("response_text", "") or "")
            app_logger = logging.getLogger("app.api")
            app_logger.info(
                "invoke_stream_done",
                extra={
                    "status": 200,
                    "response_len": len(final_text.strip()),
                    "agent": resolved_agent,
                },
            )

            yield _sse(
                "done",
                {
                    "success": True,
                    "agent": short_name,
                    "response": {
                        "text": final_state.get("response_text", ""),
                        "reasoning": final_state.get("reasoning", ""),
                        "structured_output": final_state.get("structured_output", {}),
                        "tool_output": final_state.get("tool_output"),
                        "tool_trace": final_state.get("tool_trace", []),
                    },
                    "response_text": final_state.get("response_text", ""),
                    "session_id": session_id,
                    "collab_mode": collab_mode,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "request_id": request_id,
                    "model": settings.qingyun_model,
                },
            )
        except RuntimeError as exc:
            error_code, error_message = _parse_runtime_error(exc)
            metrics.observe_agent_error(error_code)
            yield _sse(
                "error",
                {
                    "success": False,
                    "error_code": error_code,
                    "error_message": error_message,
                    "request_id": request_id,
                },
            )
        except Exception as exc:
            error_code = "AGENT_EXECUTION_ERROR"
            error_message = f"{type(exc).__name__}: {str(exc)}"
            metrics.observe_agent_error(error_code)
            yield _sse(
                "error",
                {
                    "success": False,
                    "error_code": error_code,
                    "error_message": error_message,
                    "request_id": request_id,
                },
            )
        finally:
            progress_broker.close(request_id)
            agent_ctx.set(None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/reports/exports")
async def create_report_export(
    payload: ExportRequest,
    request: Request,
) -> dict[str, Any]:
    job = create_export_job(payload)
    dispatch_export_job(job.job_id, payload)
    return {
        "success": True,
        "job_id": job.job_id,
        "status": job.status,
        "created_at": job.created_at.isoformat(),
        "request_id": _request_id(request),
    }


@router.get("/reports/exports/{job_id}")
async def get_report_export(job_id: str, request: Request) -> dict[str, Any]:
    status = export_status_payload(job_id)
    status["request_id"] = _request_id(request)
    return status


@router.get("/reports/exports/{job_id}/download")
async def download_report_export(job_id: str) -> FileResponse:
    file_path, filename = resolve_download(job_id)
    suffix = file_path.suffix.lower()
    media_type = "application/octet-stream"
    if suffix == ".pdf":
        media_type = "application/pdf"
    elif suffix == ".xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=filename,
    )


@router.get("/health")
async def health() -> dict[str, Any]:
    load_data()
    spapi_status = SpApiClient().health_check()
    return {
        "status": "ok",
        "data_loaded": True,
        "spapi": spapi_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics_endpoint() -> str:
    return metrics.export_prometheus()


@router.post("/agents/prepare")
async def prepare_agents() -> dict[str, Any]:
    prepared = []
    for agent in AGENTS:
        prepared.append({"id": agent["id"], "lifecycle": prepare_agent(agent["id"])})
    return {
        "success": True,
        "count": len(prepared),
        "agents": prepared,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
