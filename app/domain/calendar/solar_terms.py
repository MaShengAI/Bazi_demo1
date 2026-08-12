from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.domain.rules.constants import JIE_NAMES, SOLAR_TERM_ORDER

# lunar-python 的节气输出按固定北京时间 UTC+8 解释，不能套用上海历史 DST。
BEIJING_FIXED = timezone(timedelta(hours=8), name="UTC+08:00")
DEFAULT_DATA_PATH = Path(__file__).parents[2] / "data" / "solar_terms.json"


class SolarTermDataError(RuntimeError):
    """节气表缺失、越界或完整性损坏。"""

    pass


def quantize_minute_half_up(value: datetime) -> datetime:
    """节气秒数只在此处执行一次 half-up 分钟量化。"""
    if value.tzinfo is None:
        raise ValueError("solar term datetime must be timezone-aware")
    base = value.replace(second=0, microsecond=0)
    return base + timedelta(minutes=1) if value.second >= 30 else base


@dataclass(frozen=True)
class SolarTerm:
    """一条节气的北京原值、UTC 原值和实际使用的分钟边界。"""

    name: str
    year: int
    beijing_raw: datetime
    utc_raw: datetime
    utc_boundary: datetime
    lunar_python_version: str

    @property
    def is_jie(self) -> bool:
        return self.name in JIE_NAMES

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "year": self.year,
            "beijing_raw": self.beijing_raw.isoformat(),
            "utc_raw": self.utc_raw.isoformat().replace("+00:00", "Z"),
            "utc_boundary": self.utc_boundary.isoformat().replace("+00:00", "Z"),
            "lunar_python_version": self.lunar_python_version,
        }


class SolarTermRepository:
    """加载版本化节气表，并提供立春、前后节等确定性查询。"""

    def __init__(self, path: Path = DEFAULT_DATA_PATH):
        self.path = path
        if not path.exists():
            raise SolarTermDataError(f"solar term data file is missing: {path}")
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        self.metadata = payload["metadata"]
        self.terms = tuple(self._parse(item) for item in payload["terms"])
        # 建立年份索引；查询单年时不必反复扫描完整的三百多年数据。
        self._by_year: dict[int, tuple[SolarTerm, ...]] = {}
        for year in range(int(self.metadata["start_year"]), int(self.metadata["end_year"]) + 1):
            self._by_year[year] = tuple(term for term in self.terms if term.year == year)
        self.validate()

    @staticmethod
    def _parse(item: dict[str, object]) -> SolarTerm:
        """把无偏移的北京原始字符串转换为带时区的 UTC 瞬间。"""
        raw = datetime.fromisoformat(str(item["beijing_raw"])).replace(tzinfo=BEIJING_FIXED)
        utc_raw = raw.astimezone(UTC)
        return SolarTerm(
            name=str(item["name"]),
            year=int(str(item["year"])),
            beijing_raw=raw,
            utc_raw=utc_raw,
            utc_boundary=quantize_minute_half_up(utc_raw),
            lunar_python_version=str(item["lunar_python_version"]),
        )

    def validate(self) -> None:
        """启动时验证每年24节气、固定顺序和时间单调性。"""
        for year, terms in self._by_year.items():
            if len(terms) != 24:
                raise SolarTermDataError(f"year {year} contains {len(terms)} terms instead of 24")
            if tuple(item.name for item in terms) != SOLAR_TERM_ORDER:
                raise SolarTermDataError(f"year {year} has an invalid solar-term order")
            if any(a.utc_raw >= b.utc_raw for a, b in zip(terms, terms[1:], strict=False)):
                raise SolarTermDataError(f"year {year} solar terms are not strictly increasing")

    def for_year(self, year: int) -> tuple[SolarTerm, ...]:
        try:
            return self._by_year[year]
        except KeyError as exc:
            raise SolarTermDataError(f"solar term data unavailable for year {year}") from exc

    def named(self, year: int, name: str) -> SolarTerm:
        item = next((item for item in self.for_year(year) if item.name == name), None)
        if item is None:
            raise SolarTermDataError(f"solar term {name} is unavailable for year {year}")
        return item

    def previous_jie(self, instant: datetime) -> SolarTerm:
        """返回严格早于出生瞬间的上一个“节”，不包含中气。"""
        candidates = [item for item in self.terms if item.is_jie and item.utc_boundary < instant]
        if not candidates:
            raise SolarTermDataError("no previous jie in supported data")
        return candidates[-1]

    def next_jie(self, instant: datetime) -> SolarTerm:
        """返回严格晚于出生瞬间的下一个“节”，不包含中气。"""
        candidate = next(
            (item for item in self.terms if item.is_jie and item.utc_boundary > instant), None
        )
        if candidate is None:
            raise SolarTermDataError("no next jie in supported data")
        return candidate

    def current_month_jie(self, instant: datetime) -> SolarTerm:
        """找到已发生的最近一个“节”，作为月柱所属月份。"""
        candidates = [item for item in self.terms if item.is_jie and item.utc_boundary <= instant]
        if not candidates:
            raise SolarTermDataError("no current month jie in supported data")
        return candidates[-1]
