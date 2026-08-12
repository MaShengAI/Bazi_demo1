from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

JobStatus = Literal["pending", "running", "partial", "completed", "failed", "cancelled"]
SectionStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class AnalysisAccepted(BaseModel):
    job_id: str
    chart_id: str
    status: JobStatus
    deduplicated: bool = False


class AnalysisSection(BaseModel):
    code: str
    title: str
    status: SectionStatus
    content: str | None = None
    char_count: int = Field(ge=0)
    length_status: Literal["ok", "short", "long"] | None = None
    retry_count: int = Field(ge=0)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AnalysisStatusResponse(BaseModel):
    job_id: str
    chart_id: str
    status: JobStatus
    model_id: str
    prompt_version: str
    request_hash: str
    cancel_requested: bool
    completed_sections: int
    failed_sections: int
    total_sections: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AnalysisResultResponse(AnalysisStatusResponse):
    chart: dict[str, object]
    sections: list[AnalysisSection]
    disclaimer: str


class DeleteResponse(BaseModel):
    deleted: bool = True
