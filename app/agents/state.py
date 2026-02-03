from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict):
    agent: str
    input: str
    session_id: str
    messages: list[dict[str, str]]
    tool_output: dict[str, Any] | None
    response_text: str
    reasoning: str
    structured_output: dict[str, Any]
    forced_tool: str | None
    forced_args: dict[str, Any] | None
