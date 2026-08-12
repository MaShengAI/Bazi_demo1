from __future__ import annotations

from types import MappingProxyType

RULESET_VERSION = "bazi-core-1.0.0"

# 基础顺序同时承担索引语义，修改顺序会改变六十甲子等全部推导结果。
STEMS = ("甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸")
BRANCHES = ("子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥")
CHANG_SHENG = ("长生", "沐浴", "冠带", "临官", "帝旺", "衰", "病", "死", "墓", "绝", "胎", "养")

STEM_ELEMENT = MappingProxyType(
    dict(zip(STEMS, ("木", "木", "火", "火", "土", "土", "金", "金", "水", "水"), strict=True))
)
STEM_YANG = MappingProxyType({stem: i % 2 == 0 for i, stem in enumerate(STEMS)})

HIDDEN_STEMS = MappingProxyType(
    {
        "子": ("癸",),
        "丑": ("己", "癸", "辛"),
        "寅": ("甲", "丙", "戊"),
        "卯": ("乙",),
        "辰": ("戊", "乙", "癸"),
        "巳": ("丙", "庚", "戊"),
        "午": ("丁", "己"),
        "未": ("己", "丁", "乙"),
        "申": ("庚", "壬", "戊"),
        "酉": ("辛",),
        "戌": ("戊", "辛", "丁"),
        "亥": ("壬", "甲"),
    }
)

HIDDEN_ROLES = ("本气", "中气", "余气")

# 这里固化 lunar-python 1.4.8 的十二长生起点偏移，避免第三方库升级后结果静默变化。
CHANG_SHENG_OFFSET = MappingProxyType(
    {"甲": 1, "乙": 6, "丙": 10, "丁": 9, "戊": 10, "己": 9, "庚": 7, "辛": 0, "壬": 4, "癸": 3}
)

# 每个纳音连续对应六十甲子中的两个干支，因此这里只需保存30个名称。
NAYIN_PAIRS = (
    "海中金",
    "炉中火",
    "大林木",
    "路旁土",
    "剑锋金",
    "山头火",
    "涧下水",
    "城头土",
    "白蜡金",
    "杨柳木",
    "泉中水",
    "屋上土",
    "霹雳火",
    "松柏木",
    "长流水",
    "沙中金",
    "山下火",
    "平地木",
    "壁上土",
    "金箔金",
    "覆灯火",
    "天河水",
    "大驿土",
    "钗钏金",
    "桑柘木",
    "大溪水",
    "沙中土",
    "天上火",
    "石榴木",
    "大海水",
)

# 月柱与起运只使用“节”；QI_NAMES 中的中气不参与换月。
JIE_NAMES = (
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
)
QI_NAMES = (
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
)
SOLAR_TERM_ORDER = (
    "小寒",
    "大寒",
    "立春",
    "雨水",
    "惊蛰",
    "春分",
    "清明",
    "谷雨",
    "立夏",
    "小满",
    "芒种",
    "夏至",
    "小暑",
    "大暑",
    "立秋",
    "处暑",
    "白露",
    "秋分",
    "寒露",
    "霜降",
    "立冬",
    "小雪",
    "大雪",
    "冬至",
)
MONTH_JIE_INDEX = MappingProxyType(
    {
        name: i
        for i, name in enumerate(
            (
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
            )
        )
    }
)


def sexagenary_cycle() -> tuple[str, ...]:
    """按照天干十位、地支十二位的最小公倍数生成六十甲子。"""
    return tuple(STEMS[i % 10] + BRANCHES[i % 12] for i in range(60))


SEXAGENARY_CYCLE = sexagenary_cycle()
NAYIN = MappingProxyType({pillar: NAYIN_PAIRS[i // 2] for i, pillar in enumerate(SEXAGENARY_CYCLE)})


def validate_rule_tables() -> None:
    """模块加载时做快速完整性校验，规则表损坏就立即失败。"""
    assert len(STEMS) == 10 and len(set(STEMS)) == 10
    assert len(BRANCHES) == 12 and len(set(BRANCHES)) == 12
    assert len(SEXAGENARY_CYCLE) == 60 and len(set(SEXAGENARY_CYCLE)) == 60
    assert len(NAYIN) == 60
    assert set(HIDDEN_STEMS) == set(BRANCHES)
    assert set(JIE_NAMES).isdisjoint(QI_NAMES)
    assert set(JIE_NAMES) | set(QI_NAMES) == set(SOLAR_TERM_ORDER)


# 启动阶段主动校验，禁止带着不完整规则继续提供排盘结果。
validate_rule_tables()
