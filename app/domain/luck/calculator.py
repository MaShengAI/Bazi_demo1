from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction

from app.domain.bazi.calculator import FourPillars
from app.domain.calendar.solar_terms import SolarTermRepository
from app.domain.rules.constants import STEM_YANG
from app.domain.rules.core import cycle_pillar, pillar_details, pillar_index, ten_god
from app.domain.rules.shensha import calculate_shensha


@dataclass(frozen=True)
class LuckDirection:
    """大运顺逆及其可展示的判断依据。"""

    gender: str
    year_stem: str
    year_stem_yin_yang: str
    direction: str
    direction_reason: str

    @property
    def forward(self) -> bool:
        return self.direction == "forward"

    def to_dict(self) -> dict[str, str]:
        return {
            "gender": self.gender,
            "year_stem": self.year_stem,
            "year_stem_yin_yang": self.year_stem_yin_yang,
            "direction": self.direction,
            "direction_reason": self.direction_reason,
        }


def determine_direction(year_stem: str, gender: str) -> LuckDirection:
    """阳年男、阴年女顺行；阴年男、阳年女逆行。"""
    yang = STEM_YANG[year_stem]
    forward = (yang and gender == "male") or (not yang and gender == "female")
    yin_yang = "yang" if yang else "yin"
    gender_cn = "男" if gender == "male" else "女"
    return LuckDirection(
        gender=gender,
        year_stem=year_stem,
        year_stem_yin_yang=yin_yang,
        direction="forward" if forward else "backward",
        direction_reason=(
            f"{'阳' if yang else '阴'}年生{gender_cn}，{'顺行' if forward else '逆行'}"
        ),
    )


def _add_calendar(
    value: datetime, years: int = 0, months: int = 0, days: int = 0, seconds: int = 0
) -> datetime:
    """按公历添加年月日；目标月没有原日期时截到月底。"""
    total_month = value.month - 1 + months
    year = value.year + years + total_month // 12
    month = total_month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day) + timedelta(days=days, seconds=seconds)


def _age_parts(gap_seconds: int) -> dict[str, int]:
    """把节气间隔一次性换算为传统360日年龄的年月日时分秒。"""
    # 换算是精确比例：1个实际秒对应120个起运年龄秒，中间无需四舍五入。
    age_seconds = gap_seconds * 120
    year_seconds = 360 * 86400
    month_seconds = 30 * 86400
    years, remainder = divmod(age_seconds, year_seconds)
    months, remainder = divmod(remainder, month_seconds)
    days, remainder = divmod(remainder, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return {
        "years": years,
        "months": months,
        "days": days,
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
        "traditional_age_seconds": age_seconds,
    }


def calculate_luck_start(
    birth_instant: datetime,
    true_solar_birth: datetime,
    direction: LuckDirection,
    terms: SolarTermRepository,
) -> tuple[dict[str, object], datetime]:
    """按顺逆选择前后一个“节”，并用整数秒计算起运年龄和日期。"""
    # “前一个/后一个”采用严格早于/晚于，正好在节上不会得到零间隔。
    reference = (
        terms.next_jie(birth_instant) if direction.forward else terms.previous_jie(birth_instant)
    )
    gap = (
        reference.utc_boundary - birth_instant
        if direction.forward
        else birth_instant - reference.utc_boundary
    )
    gap_seconds = int(gap.total_seconds())
    # Fraction 保留三天一岁的精确有理数，避免浮点累计误差。
    exact_years = Fraction(gap_seconds, 3 * 86400)
    exact_days = Fraction(gap_seconds, 720)
    parts = _age_parts(gap_seconds)
    start = _add_calendar(
        true_solar_birth,
        years=int(parts["years"]),
        months=int(parts["months"]),
        days=int(parts["days"]),
        seconds=(int(parts["hours"]) * 3600 + int(parts["minutes"]) * 60 + int(parts["seconds"])),
    )
    result = {
        "reference_jie": reference.name,
        "reference_jie_time": reference.to_dict(),
        "absolute_gap_seconds": gap_seconds,
        "start_age_years_exact": f"{exact_years.numerator}/{exact_years.denominator}",
        "start_age_days_exact": f"{exact_days.numerator}/{exact_days.denominator}",
        "start_age": {
            key: value for key, value in parts.items() if key != "traditional_age_seconds"
        },
        "start_datetime": start.isoformat(timespec="seconds"),
        "conversion_trace": {
            "formula": (
                "gap_seconds / (3 * 86400) years; equivalently gap_seconds * 120 "
                "traditional-age seconds"
            ),
            "traditional_age_seconds": parts["traditional_age_seconds"],
            "calendar_addition_base": "true_solar_datetime",
            "month_end_policy": "clamp_to_last_valid_day",
        },
    }
    return result, start


def _year_age(birth: datetime, instant: datetime) -> int:
    """按公历生日计算足岁，不用简单的年份相减冒充年龄。"""
    age = instant.year - birth.year
    if (instant.month, instant.day, instant.time()) < (birth.month, birth.day, birth.time()):
        age -= 1
    return max(age, 0)


def _annual_years(
    cycle_start: datetime,
    cycle_end: datetime,
    birth: datetime,
    pillars: FourPillars,
    gender: str,
    terms: SolarTermRepository,
) -> list[dict[str, object]]:
    """生成与当前大运区间相交的流年，每年从立春延续到下一立春。"""
    result = []
    for year in range(cycle_start.year - 1, cycle_end.year + 2):
        try:
            start_term = terms.named(year, "立春")
            end_term = terms.named(year + 1, "立春")
        except Exception:
            continue
        start_local = start_term.utc_boundary.astimezone(cycle_start.tzinfo)
        end_local = end_term.utc_boundary.astimezone(cycle_start.tzinfo)
        # 只保留与大运时间窗真正相交的立春年度，防止相邻大运重复流年。
        if end_local <= cycle_start or start_local >= cycle_end:
            continue
        pillar = cycle_pillar(year - 4)
        shensha = _target_shensha(pillars, pillar, gender, "流年柱")
        result.append(
            {
                "gregorian_year": year,
                "pillar": pillar,
                "heavenly_stem": pillar[0],
                "earthly_branch": pillar[1],
                "age": _year_age(birth, start_local),
                "start_at_li_chun": start_local.isoformat(timespec="minutes"),
                "end_at_next_li_chun": end_local.isoformat(timespec="minutes"),
                "ten_god": ten_god(pillars.day[0], pillar[0]),
                "na_yin": pillar_details(pillar, pillars.day[0])["na_yin"],
                "shen_sha": shensha,
            }
        )
    return result


def _target_shensha(
    pillars: FourPillars, target_pillar: str, gender: str, target_name: str
) -> list[dict[str, str]]:
    """把大运或流年作为目标柱，复用统一的 55 条神煞规则。"""
    hits = calculate_shensha(
        pillars.year,
        pillars.month,
        pillars.day,
        target_pillar,
        gender,
    )["hour"]
    return [{**hit, "evidence": hit["evidence"].replace("时柱", target_name)} for hit in hits]


def build_major_luck_cycles(
    pillars: FourPillars,
    birth: datetime,
    start: datetime,
    direction: LuckDirection,
    terms: SolarTermRepository,
) -> list[dict[str, object]]:
    """从月柱前进或后退，生成起运后至100周岁的全部十年大运。"""
    cutoff = _add_calendar(birth, years=100)
    month_index = pillar_index(pillars.month)
    step = 1 if direction.forward else -1
    result = []
    index = 1
    while True:
        # 每一运都直接从统一起运基准加整十年，避免逐段相加积累误差。
        cycle_start = _add_calendar(start, years=(index - 1) * 10)
        if cycle_start >= cutoff:
            break
        nominal_end = _add_calendar(start, years=index * 10)
        cycle_end = min(nominal_end, cutoff)
        pillar = cycle_pillar(month_index + step * index)
        shensha = _target_shensha(pillars, pillar, direction.gender, "大运柱")
        details = pillar_details(pillar, pillars.day[0], shen_sha=shensha)
        result.append(
            {
                "index": index,
                **details,
                "start_age": _year_age(birth, cycle_start),
                "end_age": min(_year_age(birth, cycle_end), 100),
                "start_datetime": cycle_start.isoformat(timespec="seconds"),
                "end_datetime": cycle_end.isoformat(timespec="seconds"),
                "ten_god_of_stem": details["main_star"],
                "annual_years": _annual_years(
                    cycle_start,
                    cycle_end,
                    birth,
                    pillars,
                    direction.gender,
                    terms,
                ),
            }
        )
        index += 1
    return result
