from __future__ import annotations

from contextvars import ContextVar

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
agent_ctx: ContextVar[str | None] = ContextVar("agent", default=None)
tool_ctx: ContextVar[str | None] = ContextVar("tool", default=None)
trace_id_ctx: ContextVar[str | None] = ContextVar("trace_id", default=None)
