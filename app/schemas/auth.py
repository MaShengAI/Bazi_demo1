from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AuthUserResponse(BaseModel):
    id: str
    display_name: str
    avatar_url: str | None = None


class AuthStateResponse(BaseModel):
    payments_enabled: bool = False
    payment_mode: str = "disabled"
    enabled: bool
    authenticated: bool
    require_for_analysis: bool
    analysis_limit_per_24h: int = Field(ge=0)
    user: AuthUserResponse | None = None


class AnalysisHistoryItem(BaseModel):
    pillars: list[str] = Field(default_factory=list)
    job_id: str
    chart_id: str
    status: str
    name: str | None = None
    birth_local_datetime: str | None = None
    completed_sections: int = Field(ge=0)
    total_sections: int = Field(ge=0)
    created_at: datetime


class ReportHistoryItem(BaseModel):
    """Account archive includes free charts without an analysis job."""

    pillars: list[str] = Field(default_factory=list)
    job_id: str | None = None
    chart_id: str
    status: str
    name: str | None = None
    birth_local_datetime: str | None = None
    completed_sections: int = Field(ge=0)
    total_sections: int = Field(ge=0)
    created_at: datetime
