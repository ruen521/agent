from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.core.context import agent_ctx
from app.core.settings import settings
from app.agents.graph import run_agent
from app.data.repository import load_data
from app.core.metrics import metrics
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


class InvokeRequest(BaseModel):
    agent: str
    input: str
    session_id: str | None = None
    parameters: dict[str, Any] | None = None


@router.on_event("startup")
async def _startup() -> None:
    load_data()


@router.get("/agents/list")
async def list_agents() -> dict[str, Any]:
    return {"success": True, "count": len(AGENTS), "agents": AGENTS}


@router.get("/agents/stats")
async def agent_stats(request: Request) -> dict[str, Any]:
    stats = stats_calculator()
    return {
        "success": True,
        "stats": stats,
        "request_id": getattr(request.state, "request_id", ""),
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
        "request_id": getattr(request.state, "request_id", ""),
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
        "request_id": getattr(request.state, "request_id", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/agents/invoke")
async def invoke_agent(payload: InvokeRequest, request: Request) -> dict[str, Any]:
    if payload.agent not in {agent["id"] for agent in AGENTS}:
        raise HTTPException(status_code=404, detail="Unknown agent")

    session_id = payload.session_id or str(uuid.uuid4())
    forced_tool = (payload.parameters or {}).get("tool")
    forced_args = (payload.parameters or {}).get("args") if payload.parameters else None

    token = agent_ctx.set(payload.agent)
    try:
        state = run_agent(
            {
                "agent": payload.agent,
                "input": payload.input,
                "session_id": session_id,
                "messages": [],
                "tool_output": None,
                "response_text": "",
                "reasoning": "",
                "structured_output": {},
                "forced_tool": forced_tool,
                "forced_args": forced_args,
            }
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    agent_ctx.reset(token)

    return {
        "success": True,
        "response": {
            "text": state["response_text"],
            "reasoning": state["reasoning"],
            "structured_output": state["structured_output"],
            "tool_output": state.get("tool_output"),
        },
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": getattr(request.state, "request_id", ""),
        "model": settings.qingyun_model,
    }


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
