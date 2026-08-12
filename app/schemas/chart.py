from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Gender(str, Enum):
    """大运顺逆规则只接受男、女两个确定选项。"""

    male = "male"
    female = "female"


class ChartRequest(BaseModel):
    """排盘输入模型；禁止额外字段，防止未支持的流派参数混入。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=100)
    gender: Gender
    birth_local_datetime: str
    location_id: int = Field(gt=0)

    @field_validator("birth_local_datetime")
    @classmethod
    def minute_precision_datetime(cls, value: str) -> str:
        """强制无秒、无偏移的当地钟表时间，并限制可靠计算范围。"""
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
        except ValueError as exc:
            raise ValueError("must use YYYY-MM-DDTHH:mm with no seconds or UTC offset") from exc
        if not datetime(1901, 1, 1) <= parsed <= datetime(2100, 12, 31, 23, 59):
            raise ValueError("birth datetime must be between 1901-01-01 and 2100-12-31")
        return value

    def parsed_birth(self) -> datetime:
        """转换为朴素时间，之后必须由出生地点的 IANA 时区解释。"""
        return datetime.strptime(self.birth_local_datetime, "%Y-%m-%dT%H:%M")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
