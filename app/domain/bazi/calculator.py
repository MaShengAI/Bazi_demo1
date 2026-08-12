from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.bazi.lunar_adapter import day_pillar_at_true_solar_time
from app.domain.calendar.solar_terms import SolarTermRepository
from app.domain.rules.constants import BRANCHES, MONTH_JIE_INDEX, STEMS
from app.domain.rules.core import cycle_pillar, pillar_details
from app.domain.rules.shensha import calculate_shensha


@dataclass(frozen=True)
class FourPillars:
    """供后续大运计算使用的四个原始干支。"""

    year: str
    month: str
    day: str
    hour: str


def year_pillar(instant: datetime, terms: SolarTermRepository) -> str:
    """按真实瞬间与立春边界比较，立春之前仍归上一干支年。"""
    # 甲子年公元4年是六十甲子公历换算的锚点。
    year = instant.year
    lichun = terms.named(year, "立春")
    ganzhi_year = year if instant >= lichun.utc_boundary else year - 1
    return cycle_pillar(ganzhi_year - 4)


def month_pillar(instant: datetime, year_ganzhi: str, terms: SolarTermRepository) -> str:
    """只按十二个“节”换月，并用五虎遁由年干推出月干。"""
    current_jie = terms.current_month_jie(instant)
    month_index = MONTH_JIE_INDEX[current_jie.name]
    branch = BRANCHES[(2 + month_index) % 12]
    year_stem_index = STEMS.index(year_ganzhi[0])
    # 寅月起干：甲己丙、乙庚戊、丙辛庚、丁壬壬、戊癸甲。
    yin_month_stem = ((year_stem_index % 5) * 2 + 2) % 10
    stem = STEMS[(yin_month_stem + month_index) % 10]
    return stem + branch


def hour_pillar(day_ganzhi: str, true_solar: datetime) -> str:
    """以真太阳时23点为子初，并按五鼠遁推出时干。"""
    # 加1后整除2，可让23:00—00:59同时映射到子支索引0。
    branch_index = ((true_solar.hour + 1) // 2) % 12
    day_stem_index = STEMS.index(day_ganzhi[0])
    stem_index = ((day_stem_index % 5) * 2 + branch_index) % 10
    return STEMS[stem_index] + BRANCHES[branch_index]


def calculate_four_pillars(
    instant: datetime,
    true_solar: datetime,
    terms: SolarTermRepository,
    *,
    gender: str = "male",
) -> tuple[FourPillars, dict[str, dict[str, object]]]:
    """计算四柱，并组装十神、藏干、纳音、空亡和神煞等展示字段。"""
    year = year_pillar(instant, terms)
    month = month_pillar(instant, year, terms)
    day = day_pillar_at_true_solar_time(true_solar)
    hour = hour_pillar(day, true_solar)
    raw = FourPillars(year, month, day, hour)
    shensha_by_pillar = calculate_shensha(year, month, day, hour, gender)
    result: dict[str, dict[str, object]] = {}
    # 神煞对每一柱分别判断，日干始终是十神与十二长生的参照。
    for name, pillar in (("year", year), ("month", month), ("day", day), ("hour", hour)):
        shensha = shensha_by_pillar[name]
        result[name] = pillar_details(pillar, day[0], is_day=name == "day", shen_sha=shensha)
    return raw, result
