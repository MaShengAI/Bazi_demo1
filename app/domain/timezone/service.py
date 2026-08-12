from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TimeNormalizationError(ValueError):
    """携带稳定错误码的时区归一化异常。"""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class NormalizedTime:
    """同一个出生瞬间的钟表时间、标准时间和 UTC 表示。"""

    input_wall_time: str
    timezone: str
    utc_offset: str
    dst_offset: str
    standard_utc_offset: str
    standard_local_time: datetime
    utc_instant: datetime

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["standard_local_time"] = self.standard_local_time.isoformat()
        result["utc_instant"] = self.utc_instant.isoformat().replace("+00:00", "Z")
        return result


def _offset_text(value: timedelta) -> str:
    """把 timedelta 转成 API 友好的 ±HH:MM。"""
    total = int(value.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _valid_fold(wall_time: datetime, zone: ZoneInfo, fold: int) -> datetime | None:
    """用 UTC 往返验证某个 fold 是否真能表示输入的当地时间。"""
    candidate = wall_time.replace(tzinfo=zone, fold=fold)
    round_trip = candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    return candidate if round_trip == wall_time else None


def normalize_local_time(wall_time: datetime, timezone_id: str) -> NormalizedTime:
    """解析历史时区和 DST，并返回唯一的真实瞬间与当地标准时间。"""
    if wall_time.tzinfo is not None:
        raise TimeNormalizationError(
            "invalid_birth_datetime", "birth time must not contain an offset"
        )
    try:
        zone = ZoneInfo(timezone_id)
    except ZoneInfoNotFoundError as exc:
        raise TimeNormalizationError(
            "timezone_not_found", f"unknown IANA timezone: {timezone_id}"
        ) from exc

    # DST 切换附近必须同时尝试 fold=0/1：零个候选表示时间不存在，
    # 两个不同偏移的候选表示钟表时间重复，二者都不能静默猜测。
    candidates = [item for fold in (0, 1) if (item := _valid_fold(wall_time, zone, fold))]
    unique = {item.utcoffset() for item in candidates}
    if not candidates:
        raise TimeNormalizationError(
            "nonexistent_local_time",
            "the local wall time did not exist because of a clock transition",
        )
    if len(unique) > 1:
        raise TimeNormalizationError(
            "ambiguous_local_time",
            "the local wall time occurred twice because of a clock transition",
            {
                "candidate_offsets": sorted(
                    _offset_text(item) for item in unique if item is not None
                )
            },
        )

    aware = candidates[0]
    utc_offset = aware.utcoffset() or timedelta(0)
    dst_offset = aware.dst() or timedelta(0)
    # 标准偏移 = 当时总偏移 - DST。转换 UTC 时 zoneinfo 已考虑 DST，禁止再减一次。
    standard_offset = utc_offset - dst_offset
    standard_tz = timezone(standard_offset)
    utc_instant = aware.astimezone(UTC)
    standard_local = utc_instant.astimezone(standard_tz)
    return NormalizedTime(
        input_wall_time=wall_time.isoformat(timespec="minutes"),
        timezone=timezone_id,
        utc_offset=_offset_text(utc_offset),
        dst_offset=_offset_text(dst_offset),
        standard_utc_offset=_offset_text(standard_offset),
        standard_local_time=standard_local,
        utc_instant=utc_instant,
    )
