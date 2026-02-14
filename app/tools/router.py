from __future__ import annotations

import json
from typing import Any, Callable

from app.core.progress import progress_broker
from app.tools.inventory_tools import (
    inventory_markdown_calculator,
    inventory_query_tool,
    inventory_replenishment_tool,
    inventory_vendor_info_tool,
)

ToolHandler = Callable[..., dict[str, Any]]


_API_PATH_TO_TOOL: dict[str, tuple[str, ToolHandler]] = {
    "/query-inventory": ("inventory_query", inventory_query_tool),
    "/calculate-replenishment": ("inventory_replenishment", inventory_replenishment_tool),
    "/get-vendor-info": ("inventory_vendor_info", inventory_vendor_info_tool),
    "/calculate-markdown": ("inventory_markdown", inventory_markdown_calculator),
}

_TOOL_PROGRESS_NAME: dict[str, str] = {
    "inventory_query": "库存查询 API",
    "inventory_replenishment": "补货测算 API",
    "inventory_vendor_info": "供应商信息 API",
    "inventory_markdown": "折扣测算 API",
}


def _extract_properties(event: dict[str, Any]) -> dict[str, Any]:
    properties = (
        event.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("properties", [])
    )
    params: dict[str, Any] = {}
    for prop in properties:
        if isinstance(prop, dict) and "name" in prop:
            params[str(prop["name"])] = prop.get("value")
    return params


def _normalize_args(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "inventory_query":
        return {
            "query_type": params.get("query_type", "all"),
            "category": params.get("category"),
            "sku": params.get("sku"),
            "limit": int(params["limit"]) if params.get("limit") not in (None, "") else None,
            "min_velocity": float(params["min_velocity"]) if params.get("min_velocity") not in (None, "") else None,
            "max_velocity": float(params["max_velocity"]) if params.get("max_velocity") not in (None, "") else None,
        }
    if tool_name == "inventory_replenishment":
        skus = params.get("skus")
        if isinstance(skus, str):
            skus = [sku.strip() for sku in skus.split(",") if sku.strip()]
        return {
            "target_days": int(params["target_days"]) if params.get("target_days") not in (None, "") else None,
            "skus": skus,
        }
    if tool_name == "inventory_vendor_info":
        return {"vendor_id": params.get("vendor_id")}
    return {
        "sku": params.get("sku"),
        "min_age_days": float(params["min_age_days"]) if params.get("min_age_days") not in (None, "") else None,
        "max_velocity": float(params["max_velocity"]) if params.get("max_velocity") not in (None, "") else None,
    }


def invoke_tool_via_router(event: dict[str, Any]) -> dict[str, Any]:
    api_path = event.get("apiPath")
    if api_path not in _API_PATH_TO_TOOL:
        raise ValueError(f"Unsupported apiPath: {api_path}")

    tool_name, handler = _API_PATH_TO_TOOL[api_path]
    params = _extract_properties(event)
    args = _normalize_args(tool_name, params)
    result = handler(**args)

    return {
        "tool": tool_name,
        "args": args,
        "result": result,
        "bedrock_router_response": {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": event.get("actionGroup", "inventory-tools"),
                "apiPath": api_path,
                "httpMethod": event.get("httpMethod", "POST"),
                "httpStatusCode": 200,
                "responseBody": {
                    "application/json": {
                        "body": json.dumps(result, ensure_ascii=False),
                    }
                },
            },
        },
    }


def route_tool_call(tool_name: str, tool_args: dict[str, Any] | None = None) -> dict[str, Any]:
    tool_args = tool_args or {}
    path_by_tool = {
        "inventory_query": "/query-inventory",
        "inventory_replenishment": "/calculate-replenishment",
        "inventory_vendor_info": "/get-vendor-info",
        "inventory_markdown": "/calculate-markdown",
    }
    api_path = path_by_tool.get(tool_name)
    if not api_path:
        raise ValueError(f"Unsupported tool: {tool_name}")

    event = {
        "actionGroup": "inventory-tools",
        "apiPath": api_path,
        "httpMethod": "POST",
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": [
                        {"name": key, "value": value} for key, value in tool_args.items() if value is not None
                    ]
                }
            }
        },
    }
    tool_label = _TOOL_PROGRESS_NAME.get(tool_name, "业务工具 API")
    progress_broker.publish(
        {
            "phase": "tool",
            "text": f"正在调用{tool_label}",
            "tool": tool_name,
            "member_status": "running",
        }
    )
    result = invoke_tool_via_router(event)
    progress_broker.publish(
        {
            "phase": "tool",
            "text": f"{tool_label}执行完成",
            "tool": tool_name,
            "member_status": "success",
        }
    )
    return result
