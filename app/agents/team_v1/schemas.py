from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RagEvidence(BaseModel):
    evidence_id: str
    run_id: str
    member_id: str
    tool_name: str
    title_cn: str
    content_text_cn: str
    raw_json: dict[str, Any] | list[Any] | str | None = None
    created_at: str


class MemberExecutionRecord(BaseModel):
    member_id: str
    member_label: str
    result_status: str
    summary: str
    response_text: str
    structured_output: dict[str, Any] = Field(default_factory=dict)
    tool_outputs: dict[str, Any] = Field(default_factory=dict)
    retrieval_query: str = ""
    retrieval_hits: list[dict[str, Any]] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    started_at: str
    ended_at: str
    latency_ms: float = 0.0
    error_code: str = ""
    error_message: str = ""


class TeamV1Summary(BaseModel):
    success_count: int = 0
    failure_count: int = 0
    partial_success_count: int = 0
    successful_members: list[str] = Field(default_factory=list)
    failed_members: list[dict[str, str]] = Field(default_factory=list)


class TeamV1RagSummary(BaseModel):
    run_dir: str
    evidence_count: int = 0
    retrieval_event_count: int = 0
