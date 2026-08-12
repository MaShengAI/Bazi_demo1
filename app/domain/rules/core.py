from __future__ import annotations

from app.domain.rules.constants import (
    BRANCHES,
    CHANG_SHENG,
    CHANG_SHENG_OFFSET,
    HIDDEN_ROLES,
    HIDDEN_STEMS,
    NAYIN,
    SEXAGENARY_CYCLE,
    STEM_ELEMENT,
    STEM_YANG,
    STEMS,
)

GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}


def ten_god(day_stem: str, other_stem: str) -> str:
    """以日干为参照，根据五行生克和阴阳同异计算十神。"""
    day_element = STEM_ELEMENT[day_stem]
    other_element = STEM_ELEMENT[other_stem]
    same_polarity = STEM_YANG[day_stem] == STEM_YANG[other_stem]
    if day_element == other_element:
        return "比肩" if same_polarity else "劫财"
    if GENERATES[day_element] == other_element:
        return "食神" if same_polarity else "伤官"
    if CONTROLS[day_element] == other_element:
        return "偏财" if same_polarity else "正财"
    if CONTROLS[other_element] == day_element:
        return "七杀" if same_polarity else "正官"
    return "偏印" if same_polarity else "正印"


def hidden_stem_details(branch: str, day_stem: str) -> list[dict[str, str]]:
    """保持本气、中气、余气顺序，并为每个藏干计算副星。"""
    return [
        {"stem": stem, "role": HIDDEN_ROLES[i], "secondary_star": ten_god(day_stem, stem)}
        for i, stem in enumerate(HIDDEN_STEMS[branch])
    ]


def chang_sheng(stem: str, branch: str) -> str:
    """计算某天干落在某地支上的十二长生状态。"""
    branch_index = BRANCHES.index(branch)
    stem_index = STEMS.index(stem)
    # 阳干顺排、阴干逆排，再用各天干的长生起点做偏移。
    direction = 1 if stem_index % 2 == 0 else -1
    return CHANG_SHENG[(CHANG_SHENG_OFFSET[stem] + direction * branch_index) % 12]


def xun_kong(pillar: str) -> tuple[str, str]:
    """由目标干支反推旬首，并取得该旬未覆盖的两个地支。"""
    stem_index = STEMS.index(pillar[0])
    branch_index = BRANCHES.index(pillar[1])
    xun_start_branch = (branch_index - stem_index) % 12
    return BRANCHES[(xun_start_branch - 2) % 12], BRANCHES[(xun_start_branch - 1) % 12]


def cycle_pillar(index: int) -> str:
    """允许任意正负索引在六十甲子中循环。"""
    return SEXAGENARY_CYCLE[index % 60]


def pillar_index(pillar: str) -> int:
    try:
        return SEXAGENARY_CYCLE.index(pillar)
    except ValueError as exc:
        raise ValueError(f"invalid sexagenary pillar: {pillar}") from exc


def pillar_details(
    pillar: str,
    day_stem: str,
    *,
    is_day: bool = False,
    shen_sha: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """把一个干支扩展为 API 所需的完整柱信息。"""
    stem = pillar[0]
    branch = pillar[1]
    hidden = hidden_stem_details(branch, day_stem)
    return {
        "pillar": pillar,
        "main_star": "日主" if is_day else ten_god(day_stem, stem),
        "heavenly_stem": stem,
        "earthly_branch": branch,
        "hidden_stems": hidden,
        "secondary_stars": [item["secondary_star"] for item in hidden],
        "na_yin": NAYIN[pillar],
        "star_fortune": chang_sheng(day_stem, branch),
        "self_seat": chang_sheng(stem, branch),
        "void": list(xun_kong(pillar)),
        "shen_sha": shen_sha or [],
    }
