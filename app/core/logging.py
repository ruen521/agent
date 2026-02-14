from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.context import agent_ctx, request_id_ctx, session_id_ctx, tool_ctx, trace_id_ctx


class JsonFormatter(logging.Formatter):
    _RESERVED_ATTRS = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    @staticmethod
    def _normalize_extra_value(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value if len(value) <= 300 else f"{value[:297]}..."
        if isinstance(value, (list, tuple)):
            return f"[len={len(value)}]"
        if isinstance(value, dict):
            return f"{{keys={list(value.keys())[:8]}}}"
        return str(value)

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
        session_id = getattr(record, "session_id", None) or session_id_ctx.get()

        if request_id:
            payload["request_id"] = request_id
        if agent:
            payload["agent"] = agent
        if tool:
            payload["tool"] = tool
        if trace_id:
            payload["trace_id"] = trace_id
        if session_id:
            payload["session_id"] = session_id

        for key in ("latency_ms", "status", "error_code", "run_id", "member_id", "attempt"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        # Include additional structured extras (e.g. llm metadata) for diagnostics.
        for key, value in record.__dict__.items():
            if key in payload or key in self._RESERVED_ATTRS:
                continue
            normalized = self._normalize_extra_value(value)
            if normalized is not None:
                payload[key] = normalized

        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
