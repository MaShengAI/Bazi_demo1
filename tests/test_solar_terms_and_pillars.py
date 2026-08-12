from datetime import timedelta

import pytest

from app.domain.bazi.calculator import hour_pillar, month_pillar, year_pillar
from app.domain.bazi.lunar_adapter import day_pillar_at_true_solar_time
from app.domain.calendar.solar_terms import SolarTermRepository


@pytest.fixture(scope="module")
def terms() -> SolarTermRepository:
    return SolarTermRepository()


def test_guaranteed_solar_term_table_is_complete(terms: SolarTermRepository) -> None:
    assert sum(len(terms.for_year(year)) for year in range(1901, 2101)) == 4800


def test_year_changes_at_quantized_li_chun(terms: SolarTermRepository) -> None:
    lichun = terms.named(1988, "立春").utc_boundary
    assert year_pillar(lichun - timedelta(minutes=1), terms) == "丁卯"
    assert year_pillar(lichun, terms) == "戊辰"
    assert year_pillar(lichun + timedelta(minutes=1), terms) == "戊辰"


@pytest.mark.parametrize(
    "jie",
    [
        "立春",
        "惊蛰",
        "清明",
        "立夏",
        "芒种",
        "小暑",
        "立秋",
        "白露",
        "寒露",
        "立冬",
        "大雪",
        "小寒",
    ],
)
def test_every_jie_changes_month_but_not_before_boundary(
    terms: SolarTermRepository, jie: str
) -> None:
    year = 1988
    boundary = terms.named(year, jie).utc_boundary
    before = month_pillar(
        boundary - timedelta(minutes=1), year_pillar(boundary - timedelta(minutes=1), terms), terms
    )
    at = month_pillar(boundary, year_pillar(boundary, terms), terms)
    assert before != at


@pytest.mark.parametrize(
    "qi",
    [
        "雨水",
        "春分",
        "谷雨",
        "小满",
        "夏至",
        "大暑",
        "处暑",
        "秋分",
        "霜降",
        "小雪",
        "冬至",
        "大寒",
    ],
)
def test_qi_does_not_change_month(terms: SolarTermRepository, qi: str) -> None:
    boundary = terms.named(1988, qi).utc_boundary
    before = month_pillar(
        boundary - timedelta(minutes=1), year_pillar(boundary - timedelta(minutes=1), terms), terms
    )
    after = month_pillar(
        boundary + timedelta(minutes=1), year_pillar(boundary + timedelta(minutes=1), terms), terms
    )
    assert before == after


def test_late_zi_hour_rolls_day_at_23_true_solar() -> None:
    from datetime import datetime

    before = day_pillar_at_true_solar_time(datetime(2024, 1, 1, 22, 59))
    at = day_pillar_at_true_solar_time(datetime(2024, 1, 1, 23, 0))
    next_midnight = day_pillar_at_true_solar_time(datetime(2024, 1, 2, 0, 0))
    assert before != at
    assert at == next_midnight


def test_hour_pillar_uses_23_as_zi_hour() -> None:
    from datetime import datetime

    assert hour_pillar("甲子", datetime(2024, 1, 1, 23, 0)).endswith("子")
    assert hour_pillar("甲子", datetime(2024, 1, 2, 0, 59)).endswith("子")
    assert hour_pillar("甲子", datetime(2024, 1, 2, 1, 0)).endswith("丑")


@pytest.mark.parametrize(
    ("hour", "branch"),
    [
        (23, "子"),
        (1, "丑"),
        (3, "寅"),
        (5, "卯"),
        (7, "辰"),
        (9, "巳"),
        (11, "午"),
        (13, "未"),
        (15, "申"),
        (17, "酉"),
        (19, "戌"),
        (21, "亥"),
    ],
)
def test_all_twelve_double_hour_boundaries(hour: int, branch: str) -> None:
    from datetime import datetime

    assert hour_pillar("甲子", datetime(2024, 1, 1, hour, 0)).endswith(branch)
