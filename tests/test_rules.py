from lunar_python.util import LunarUtil

from app.domain.rules.constants import NAYIN, SEXAGENARY_CYCLE
from app.domain.rules.core import chang_sheng, hidden_stem_details, ten_god, xun_kong
from app.domain.rules.shensha import (
    RULE_CATALOG,
    SHENSHA_RULESET_VERSION,
    calculate_shensha,
)


def test_rule_tables_are_complete() -> None:
    assert len(SEXAGENARY_CYCLE) == 60
    assert len(NAYIN) == 60
    assert NAYIN["甲子"] == "海中金"
    assert NAYIN["癸亥"] == "大海水"
    assert all(NAYIN[pillar] == LunarUtil.NAYIN[pillar] for pillar in SEXAGENARY_CYCLE)


def test_ten_god_polarity_and_generation() -> None:
    assert ten_god("甲", "甲") == "比肩"
    assert ten_god("甲", "乙") == "劫财"
    assert ten_god("甲", "丙") == "食神"
    assert ten_god("甲", "丁") == "伤官"
    assert ten_god("甲", "庚") == "七杀"
    assert ten_god("甲", "辛") == "正官"


def test_hidden_stem_order_is_main_middle_residual() -> None:
    details = hidden_stem_details("辰", "甲")
    assert [(item["stem"], item["role"]) for item in details] == [
        ("戊", "本气"),
        ("乙", "中气"),
        ("癸", "余气"),
    ]


def test_chang_sheng_and_void() -> None:
    assert chang_sheng("甲", "亥") == "长生"
    assert chang_sheng("乙", "午") == "长生"
    assert xun_kong("甲子") == ("戌", "亥")
    assert xun_kong("甲戌") == ("申", "酉")
    assert xun_kong("甲寅") == ("子", "丑")
    assert all(
        "".join(xun_kong(pillar)) == LunarUtil.getXunKong(pillar) for pillar in SEXAGENARY_CYCLE
    )


def test_every_declared_shensha_rule_can_hit() -> None:
    def codes(result: dict[str, list[dict[str, str]]]) -> set[str]:
        return {hit["code"] for hits in result.values() for hit in hits}

    assert "taohua" in codes(calculate_shensha("甲子", "丙寅", "甲午", "丁酉", "male"))
    assert "yima" in codes(calculate_shensha("甲子", "丙寅", "甲午", "丁酉", "male"))
    assert "huagai" in codes(calculate_shensha("甲子", "戊辰", "甲午", "丁酉", "male"))
    assert "tianyi" in codes(calculate_shensha("甲子", "乙丑", "甲午", "丁酉", "male"))
    assert "wenchang" in codes(calculate_shensha("甲子", "己巳", "甲午", "丁酉", "male"))


def test_full_shensha_catalog_has_55_stable_rules() -> None:
    assert SHENSHA_RULESET_VERSION == "common-shensha-2.2.0"
    assert [number for number, _, _ in RULE_CATALOG] == list(range(1, 56))
    assert len({code for _, code, _ in RULE_CATALOG}) == 55
    assert len({name for _, _, name in RULE_CATALOG}) == 55


def test_full_shensha_merges_year_and_day_reference_evidence() -> None:
    result = calculate_shensha("甲子", "丁卯", "戊辰", "甲寅", "male")
    yima = [hit for hit in result["hour"] if hit["code"] == "yima"]
    assert len(yima) == 1
    assert "年支=子" in yima[0]["evidence"]
    assert "日支=辰" in yima[0]["evidence"]
    assert yima[0]["rule_id"] == "SS-008"


def test_gender_dependent_tianluodiwang_rule() -> None:
    male = calculate_shensha("戊辰", "乙卯", "甲子", "乙亥", "male")
    female = calculate_shensha("戊辰", "乙卯", "甲子", "乙亥", "female")
    assert any(hit["code"] == "tianluodiwang" for hit in male["hour"])
    assert not any(hit["code"] == "tianluodiwang" for hits in female.values() for hit in hits)


def test_gonglu_is_attached_to_day_and_hour_pillars() -> None:
    result = calculate_shensha("甲子", "丙寅", "癸亥", "癸丑", "male")
    assert [hit["name"] for hit in result["day"] if hit["code"] == "gonglu"] == ["拱禄(拱子禄)"]
    assert [hit["name"] for hit in result["hour"] if hit["code"] == "gonglu"] == ["拱禄(拱子禄)"]


def test_every_full_shensha_hit_has_auditable_fields() -> None:
    result = calculate_shensha("戊辰", "己未", "丙寅", "甲午", "male")
    hits = [hit for pillar_hits in result.values() for hit in pillar_hits]
    assert hits
    assert all(set(hit) == {"code", "name", "rule_id", "evidence"} for hit in hits)
    assert all(hit["rule_id"].startswith("SS-") and hit["evidence"] for hit in hits)
