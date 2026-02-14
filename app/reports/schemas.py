from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ExportFormat = Literal["pdf", "xlsx"]
ExportScope = Literal["global", "session", "table", "analysis"]
ExportAudience = Literal["external", "internal"]
ExportStatus = Literal["PENDING", "RUNNING", "DONE", "FAILED", "EXPIRED"]


class ExportRequest(BaseModel):
    format: ExportFormat
    scope: ExportScope
    audience: ExportAudience = "external"
    session_id: str | None = None
    agent_id: str | None = None
    title: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ExportJobRecord(BaseModel):
    job_id: str
    status: ExportStatus
    progress: int = 0
    format: ExportFormat
    scope: ExportScope
    audience: ExportAudience
    title: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    output_path: str
    error_message: str | None = None
