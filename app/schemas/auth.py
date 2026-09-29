from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AuthUserResponse(BaseModel):
    id: str
    display_name: str
    avatar_url: str | None = None


class AuthStateResponse(BaseModel):
    enabled: bool
    authenticated: bool
    require_for_analysis: bool
    analysis_limit_per_24h: int = Field(ge=0)
    user: AuthUserResponse | None = None


class AnalysisHistoryItem(BaseModel):
    job_id: str
    chart_id: str
    status: str
    name: str | None = None
    birth_local_datetime: str | None = None
    completed_sections: int = Field(ge=0)
    total_sections: int = Field(ge=0)
    created_at: datetime
