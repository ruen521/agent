from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict):
    agent: str
    input: str
    session_id: str
    collab_mode: str
    orchestration_options: dict[str, Any] | None
    messages: list[dict[str, str]]
    tool_output: dict[str, Any] | None
    response_text: str
    reasoning: str
    structured_output: dict[str, Any]
    forced_tool: str | None
    forced_args: dict[str, Any] | None
    tool_trace: list[dict[str, Any]]
    plan: list[dict[str, Any]]
    past_steps: list[dict[str, Any]]
    steps_executed: int
    replan_count: int
    team_v1_run_id: str
    team_v1_plan: list[str]
    team_v1_queue: list[str]
    team_v1_execution: list[dict[str, Any]]
    team_v1_started_at: str
    team_v1_member_tool_outputs: dict[str, dict[str, Any]]
    team_v1_rag_retrieval_trace: list[dict[str, Any]]
    team_v1_rag_dir: str
