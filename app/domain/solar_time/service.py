from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from app.domain.timezone.service import NormalizedTime


@dataclass(frozen=True)
class TrueSolarTime:
    """真太阳时结果及其两个可审计的修正量。"""

    longitude: float
    latitude: float
    standard_meridian: float
    longitude_correction_seconds: int
    equation_of_time_seconds: int
    true_solar_datetime: datetime

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["true_solar_datetime"] = self.true_solar_datetime.isoformat(timespec="seconds")
        return result


def equation_of_time_seconds(value: datetime) -> int:
    """用 NOAA 分数年近似式计算均时差，并且只在最后量化一次到秒。"""
    days = 366 if _is_leap(value.year) else 365
    gamma = 2 * math.pi / days * (value.timetuple().tm_yday - 1 + (value.hour - 12) / 24)
    minutes = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    return (
        int(math.floor(minutes * 60 + 0.5)) if minutes >= 0 else int(math.ceil(minutes * 60 - 0.5))
    )


def _is_leap(year: int) -> bool:
    """公历闰年判断，用于确定分数年的总天数。"""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def calculate_true_solar_time(
    normalized: NormalizedTime, longitude: float, latitude: float
) -> TrueSolarTime:
    """在去除 DST 的标准时间上叠加经度修正和均时差。"""
    # 中央经线由标准偏移决定，例如 UTC+8 对应东经120度。
    standard_seconds = int(
        (normalized.standard_local_time.utcoffset() or timedelta()).total_seconds()
    )
    standard_meridian = standard_seconds / 3600 * 15
    # 经度每相差1度，对应地方太阳时相差4分钟；东侧为正，西侧为负。
    longitude_seconds = int(round(4 * 60 * (longitude - standard_meridian)))
    eot_seconds = equation_of_time_seconds(normalized.standard_local_time)
    true_solar = normalized.standard_local_time + timedelta(seconds=longitude_seconds + eot_seconds)
    return TrueSolarTime(
        longitude=longitude,
        latitude=latitude,
        standard_meridian=standard_meridian,
        longitude_correction_seconds=longitude_seconds,
        equation_of_time_seconds=eot_seconds,
        true_solar_datetime=true_solar,
    )
