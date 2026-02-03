from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.context import agent_ctx, request_id_ctx, tool_ctx, trace_id_ctx


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        request_id = getattr(record, "request_id", None) or request_id_ctx.get()
        agent = getattr(record, "agent", None) or agent_ctx.get()
        tool = getattr(record, "tool", None) or tool_ctx.get()
        trace_id = getattr(record, "trace_id", None) or trace_id_ctx.get()

        if request_id:
            payload["request_id"] = request_id
        if agent:
            payload["agent"] = agent
        if tool:
            payload["tool"] = tool
        if trace_id:
            payload["trace_id"] = trace_id

        for key in ("latency_ms", "status", "error_code"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
