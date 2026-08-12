from __future__ import annotations

from dataclasses import dataclass

from app.domain.rules.constants import BRANCHES, NAYIN, SEXAGENARY_CYCLE

SHENSHA_RULESET_VERSION = "common-shensha-2.2.0"

PILLAR_KEYS = ("year", "month", "day", "hour")
PILLAR_NAMES = ("年柱", "月柱", "日柱", "时柱")
GAN_YANG = {"甲", "丙", "戊", "庚", "壬"}
ZHI_YANG = {"子", "寅", "辰", "午", "申", "戌"}
LIUCHONG = {
    "子": "午",
    "午": "子",
    "丑": "未",
    "未": "丑",
    "寅": "申",
    "申": "寅",
    "卯": "酉",
    "酉": "卯",
    "辰": "戌",
    "戌": "辰",
    "巳": "亥",
    "亥": "巳",
}
SEASON = {
    "寅": "春",
    "卯": "春",
    "辰": "春",
    "巳": "夏",
    "午": "夏",
    "未": "夏",
    "申": "秋",
    "酉": "秋",
    "戌": "秋",
    "亥": "冬",
    "子": "冬",
    "丑": "冬",
}

TIANYI_GUIREN = {
    "甲": "丑未",
    "戊": "丑未",
    "庚": "丑未",
    "乙": "子申",
    "己": "子申",
    "丙": "亥酉",
    "丁": "亥酉",
    "壬": "卯巳",
    "癸": "卯巳",
    "辛": "寅午",
}
TIANDE_GUIREN = {
    "寅": "丁",
    "卯": "申",
    "辰": "壬",
    "巳": "辛",
    "午": "亥",
    "未": "甲",
    "申": "癸",
    "酉": "寅",
    "戌": "丙",
    "亥": "乙",
    "子": "巳",
    "丑": "庚",
}
YUEDE_GUIREN = {
    "寅": "丙",
    "午": "丙",
    "戌": "丙",
    "亥": "甲",
    "卯": "甲",
    "未": "甲",
    "申": "壬",
    "子": "壬",
    "辰": "壬",
    "巳": "庚",
    "酉": "庚",
    "丑": "庚",
}
TIANDE_HE = {
    "寅": "壬",
    "卯": "寅",
    "辰": "丁",
    "巳": "丙",
    "午": "巳",
    "未": "己",
    "申": "戊",
    "酉": "亥",
    "戌": "辛",
    "亥": "庚",
    "子": "酉",
    "丑": "乙",
}
YUEDE_HE = {
    "寅": "辛",
    "午": "辛",
    "戌": "辛",
    "亥": "己",
    "卯": "己",
    "未": "己",
    "申": "丁",
    "子": "丁",
    "辰": "丁",
    "巳": "乙",
    "酉": "乙",
    "丑": "乙",
}
TIANSHA = {"春": {"戊寅"}, "夏": {"甲午"}, "秋": {"戊申"}, "冬": {"甲子"}}
LUSHEN = {
    "甲": "寅",
    "乙": "卯",
    "丙": "巳",
    "丁": "午",
    "戊": "巳",
    "己": "午",
    "庚": "申",
    "辛": "酉",
    "壬": "亥",
    "癸": "子",
}
YIMA = {
    "申": "寅",
    "子": "寅",
    "辰": "寅",
    "寅": "申",
    "午": "申",
    "戌": "申",
    "亥": "巳",
    "卯": "巳",
    "未": "巳",
    "巳": "亥",
    "酉": "亥",
    "丑": "亥",
}
TAIJI_GUIREN = {
    "甲": "子午",
    "庚": "子午",
    "乙": "丑未",
    "辛": "丑未",
    "丙": "寅申",
    "壬": "寅申",
    "丁": "卯酉",
    "癸": "卯酉",
    "戊": "辰巳戌亥",
    "己": "辰巳戌亥",
}
JIANGXING = {
    "申": "子",
    "子": "子",
    "辰": "子",
    "寅": "午",
    "午": "午",
    "戌": "午",
    "亥": "卯",
    "卯": "卯",
    "未": "卯",
    "巳": "酉",
    "酉": "酉",
    "丑": "酉",
}
XUETANG = {
    "甲": "巳",
    "乙": "午",
    "丙": "寅",
    "丁": "酉",
    "戊": "寅",
    "己": "酉",
    "庚": "亥",
    "辛": "子",
    "壬": "申",
    "癸": "卯",
}
CIGUAN = LUSHEN
GUOYIN = {
    "甲": "戌",
    "乙": "丑",
    "丙": "辰",
    "丁": "未",
    "戊": "丑",
    "己": "辰",
    "庚": "戌",
    "辛": "未",
    "壬": "丑",
    "癸": "戌",
}
SANQI = {
    "天上三奇": ("甲", "戊", "庚"),
    "地上三奇": ("乙", "丙", "丁"),
    "人中三奇": ("壬", "癸", "辛"),
}
WENCHANG = {
    "甲": "巳",
    "乙": "午",
    "丙": "申",
    "丁": "酉",
    "戊": "申",
    "己": "酉",
    "庚": "亥",
    "辛": "子",
    "壬": "寅",
    "癸": "卯",
}
HUAGAI = {
    "申": "辰",
    "子": "辰",
    "辰": "辰",
    "寅": "戌",
    "午": "戌",
    "戌": "戌",
    "亥": "未",
    "卯": "未",
    "未": "未",
    "巳": "丑",
    "酉": "丑",
    "丑": "丑",
}
TIANYI_YI = {
    "寅": "丑",
    "卯": "寅",
    "辰": "卯",
    "巳": "辰",
    "午": "巳",
    "未": "午",
    "申": "未",
    "酉": "申",
    "戌": "酉",
    "亥": "戌",
    "子": "亥",
    "丑": "子",
}
JINYU = {
    "甲": "辰",
    "乙": "巳",
    "丙": "未",
    "丁": "申",
    "戊": "未",
    "己": "申",
    "庚": "戌",
    "辛": "亥",
    "壬": "丑",
    "癸": "寅",
}
KONGWANG = {
    "甲子": "戌亥",
    "甲戌": "申酉",
    "甲申": "午未",
    "甲午": "辰巳",
    "甲辰": "寅卯",
    "甲寅": "子丑",
}
ZAISHA = {
    "申": "午",
    "子": "午",
    "辰": "午",
    "寅": "子",
    "午": "子",
    "戌": "子",
    "亥": "申",
    "卯": "申",
    "未": "申",
    "巳": "寅",
    "酉": "寅",
    "丑": "寅",
}
JIESHA = {
    "申": "巳",
    "子": "巳",
    "辰": "巳",
    "寅": "亥",
    "午": "亥",
    "戌": "亥",
    "亥": "寅",
    "卯": "寅",
    "未": "寅",
    "巳": "申",
    "酉": "申",
    "丑": "申",
}
WANGSHEN = {
    "申": "亥",
    "子": "亥",
    "辰": "亥",
    "寅": "巳",
    "午": "巳",
    "戌": "巳",
    "亥": "寅",
    "卯": "寅",
    "未": "寅",
    "巳": "申",
    "酉": "申",
    "丑": "申",
}
YANGREN = {
    "甲": "卯",
    "乙": "寅",
    "丙": "午",
    "丁": "巳",
    "戊": "午",
    "己": "巳",
    "庚": "酉",
    "辛": "申",
    "壬": "子",
    "癸": "亥",
}
FEIREN = {
    "甲": "酉",
    "乙": "申",
    "丙": "子",
    "丁": "亥",
    "戊": "子",
    "己": "亥",
    "庚": "卯",
    "辛": "寅",
    "壬": "午",
    "癸": "巳",
}
LIUXIA = {
    "甲": "酉",
    "乙": "戌",
    "丙": "未",
    "丁": "申",
    "戊": "巳",
    "己": "午",
    "庚": "辰",
    "辛": "卯",
    "壬": "亥",
    "癸": "巳",
}
SIFEI = {
    "春": {"庚申", "辛酉"},
    "夏": {"壬子", "癸亥"},
    "秋": {"甲寅", "乙卯"},
    "冬": {"丙午", "丁巳"},
}
TAOHUA = {
    "申": "酉",
    "子": "酉",
    "辰": "酉",
    "寅": "卯",
    "午": "卯",
    "戌": "卯",
    "亥": "子",
    "卯": "子",
    "未": "子",
    "巳": "午",
    "酉": "午",
    "丑": "午",
}
GUCHEN = {
    "寅": "巳",
    "卯": "巳",
    "辰": "巳",
    "巳": "申",
    "午": "申",
    "未": "申",
    "申": "亥",
    "酉": "亥",
    "戌": "亥",
    "亥": "寅",
    "子": "寅",
    "丑": "寅",
}
GUAXIU = {
    "寅": "丑",
    "卯": "丑",
    "辰": "丑",
    "巳": "辰",
    "午": "辰",
    "未": "辰",
    "申": "未",
    "酉": "未",
    "戌": "未",
    "亥": "戌",
    "子": "戌",
    "丑": "戌",
}
YINCHA_YANGCUO = {
    "丙子",
    "丁丑",
    "戊寅",
    "辛卯",
    "壬辰",
    "癸巳",
    "丙午",
    "丁未",
    "戊申",
    "辛酉",
    "壬戌",
    "癸亥",
}
KUIGANG = {"壬辰", "庚戌", "庚辰", "戊戌"}
GULUAN = {"乙巳", "丁巳", "辛亥", "戊申", "壬寅", "戊午"}
HONGLUAN = {
    "子": "卯",
    "丑": "寅",
    "寅": "丑",
    "卯": "子",
    "辰": "亥",
    "巳": "戌",
    "午": "酉",
    "未": "申",
    "申": "未",
    "酉": "午",
    "戌": "巳",
    "亥": "辰",
}
TIANXI = {
    "子": "酉",
    "丑": "申",
    "寅": "未",
    "卯": "午",
    "辰": "巳",
    "巳": "辰",
    "午": "卯",
    "未": "寅",
    "申": "丑",
    "酉": "子",
    "戌": "亥",
    "亥": "戌",
}
HONGYAN = {
    "甲": "午",
    "乙": "申",
    "丙": "寅",
    "丁": "未",
    "戊": "辰",
    "己": "辰",
    "庚": "戌",
    "辛": "酉",
    "壬": "子",
    "癸": "申",
}
SHIEDABAI = {"甲辰", "乙巳", "壬申", "丙申", "丁亥", "庚辰", "戊戌", "癸亥", "辛巳", "己丑"}
JINSHEN = {"乙丑", "己巳", "癸酉"}
TIANZHUAN = {"春": {"乙卯"}, "夏": {"丙午"}, "秋": {"辛酉"}, "冬": {"壬子"}}
DIZHUAN = {"春": {"辛卯"}, "夏": {"戊午"}, "秋": {"癸酉"}, "冬": {"丙子"}}
SANGMEN = dict(zip(BRANCHES, BRANCHES[2:] + BRANCHES[:2], strict=True))
DIAOKE = dict(zip(BRANCHES, BRANCHES[-2:] + BRANCHES[:-2], strict=True))
PIMA = dict(zip(BRANCHES, BRANCHES[-3:] + BRANCHES[:-3], strict=True))
SHILING = {"甲辰", "乙亥", "丙辰", "丁酉", "戊午", "庚戌", "辛巳", "壬寅", "癸未", "己丑"}
LIUXIU = {"丙午", "丁未", "戊申", "己酉", "壬子", "癸亥"}
BAZHUAN = {"甲寅", "乙卯", "丁未", "己未", "庚申", "辛酉", "癸丑", "戊戌"}
JIUCHOU = {"己卯", "辛卯", "乙酉", "丁酉", "己酉", "壬子", "壬午", "戊子", "戊午"}
TIANCHU = XUETANG
FUXING = {
    "甲": "寅",
    "乙": "丑",
    "丙": "辰",
    "丁": "亥",
    "戊": "申",
    "己": "未",
    "庚": "午",
    "辛": "巳",
    "壬": "辰",
    "癸": "卯",
}
DEXIU = {
    "寅": "丙丁",
    "午": "丙丁",
    "戌": "丙丁",
    "亥": "甲己",
    "卯": "甲己",
    "未": "甲己",
    "申": "壬癸",
    "子": "壬癸",
    "辰": "壬癸",
    "巳": "庚辛",
    "酉": "庚辛",
    "丑": "庚辛",
}
GONGLU_PAIRS = {
    ("癸亥", "癸丑"): "子",
    ("癸丑", "癸亥"): "子",
    ("丁巳", "丁未"): "午",
    ("己未", "己巳"): "午",
    ("戊辰", "戊午"): "巳",
}

RULE_CATALOG = (
    (1, "tianyi", "天乙贵人"),
    (2, "tiande", "天德贵人"),
    (3, "yuede", "月德贵人"),
    (4, "tiandehe", "天德合"),
    (5, "yuedehe", "月德合"),
    (6, "tianshe", "天赦日"),
    (7, "lushen", "禄神"),
    (8, "yima", "驿马"),
    (9, "taiji", "太极贵人"),
    (10, "jiangxing", "将星"),
    (11, "xuetang", "学堂"),
    (12, "ciguan", "词馆"),
    (13, "guoyin", "国印贵人"),
    (14, "sanqi", "三奇贵人"),
    (15, "wenchang", "文昌贵人"),
    (16, "huagai", "华盖"),
    (17, "tianyi_yi", "天医"),
    (18, "jinyu", "金舆"),
    (19, "kongwang", "空亡"),
    (20, "zaisha", "灾煞"),
    (21, "jiesha", "劫煞"),
    (22, "wangshen", "亡神"),
    (23, "yangren", "羊刃"),
    (24, "feiren", "飞刃"),
    (25, "xueren", "血刃"),
    (26, "liuxia", "流霞"),
    (27, "sifei", "四废日"),
    (28, "tianluodiwang", "天罗地网"),
    (29, "taohua", "桃花"),
    (30, "guchen", "孤辰"),
    (31, "guaxiu", "寡宿"),
    (32, "yinchayangcuo", "阴差阳错"),
    (33, "kuigang", "魁罡"),
    (34, "guluan", "孤鸾煞"),
    (35, "hongluan", "红鸾"),
    (36, "tianxi", "天喜"),
    (37, "goujiao", "勾绞煞"),
    (38, "hongyan", "红艳煞"),
    (39, "shiedabai", "十恶大败"),
    (40, "yuanchen", "元辰"),
    (41, "jinshen", "金神"),
    (42, "tianzhuan", "天转"),
    (43, "dizhuan", "地转"),
    (44, "sangmen", "丧门"),
    (45, "diaoke", "吊客"),
    (46, "pima", "披麻"),
    (47, "shiling", "十灵日"),
    (48, "liuxiu", "六秀日"),
    (49, "bazhuan", "八专"),
    (50, "jiuchou", "九丑"),
    (51, "tongzi", "童子煞"),
    (52, "tianchu", "天厨贵人"),
    (53, "fuxing", "福星贵人"),
    (54, "dexiu", "德秀贵人"),
    (55, "gonglu", "拱禄"),
)
RULE_META = {number: (code, name) for number, code, name in RULE_CATALOG}


@dataclass(frozen=True)
class ShenShaChart:
    year: str
    month: str
    day: str
    hour: str
    gender: str

    def __post_init__(self) -> None:
        if self.gender not in {"male", "female"}:
            raise ValueError("gender must be 'male' or 'female'")
        for pillar in self.pillars:
            if pillar not in SEXAGENARY_CYCLE:
                raise ValueError(f"invalid sexagenary pillar: {pillar}")

    @property
    def pillars(self) -> tuple[str, str, str, str]:
        return self.year, self.month, self.day, self.hour

    @property
    def stems(self) -> tuple[str, str, str, str]:
        return tuple(pillar[0] for pillar in self.pillars)  # type: ignore[return-value]

    @property
    def branches(self) -> tuple[str, str, str, str]:
        return tuple(pillar[1] for pillar in self.pillars)  # type: ignore[return-value]

    @property
    def season(self) -> str:
        return SEASON[self.month[1]]

    @property
    def xun(self) -> str:
        return SEXAGENARY_CYCLE[(SEXAGENARY_CYCLE.index(self.day) // 10) * 10]


class ShenShaCalculator:
    """将 55 条规则应用到已经确定的四柱，不在此处重新排盘。"""

    def __init__(self, chart: ShenShaChart):
        self.chart = chart
        self.results: list[list[dict[str, str]]] = [[], [], [], []]

    def add(self, rule: int, pillar: int, evidence: str, name: str | None = None) -> None:
        code, default_name = RULE_META[rule]
        hit_name = name or default_name
        rule_id = f"SS-{rule:03d}"
        for existing in self.results[pillar]:
            if existing["rule_id"] == rule_id and existing["name"] == hit_name:
                evidence_parts = existing["evidence"].split("；")
                if evidence not in evidence_parts:
                    existing["evidence"] = f"{existing['evidence']}；{evidence}"
                return
        hit = {
            "code": code,
            "name": hit_name,
            "rule_id": rule_id,
            "evidence": evidence,
        }
        self.results[pillar].append(hit)

    def branches(self, target: str, exclude: int | None = None) -> list[int]:
        return [
            index
            for index, branch in enumerate(self.chart.branches)
            if branch == target and index != exclude
        ]

    def stems(self, target: str) -> list[int]:
        return [index for index, stem in enumerate(self.chart.stems) if stem == target]

    def chars(self, target: str) -> list[int]:
        return [
            index
            for index, pillar in enumerate(self.chart.pillars)
            if target in (pillar[0], pillar[1])
        ]

    def add_branch_table(
        self, rule: int, table: dict[str, str], reference: str, reference_name: str
    ) -> None:
        target = table[reference]
        for index in self.branches(target):
            self.add(rule, index, f"{reference_name}={reference}，{PILLAR_NAMES[index]}支={target}")

    def add_day_stem_branch(self, rule: int, table: dict[str, str]) -> None:
        day_stem = self.chart.day[0]
        targets = table[day_stem]
        for index, branch in enumerate(self.chart.branches):
            if branch in targets:
                self.add(rule, index, f"日干={day_stem}，{PILLAR_NAMES[index]}支={branch}")

    def add_day_rule(self, rule: int, values: set[str], extra: str = "") -> None:
        if self.chart.day in values:
            suffix = f"，{extra}" if extra else ""
            self.add(rule, 2, f"日柱={self.chart.day}{suffix}")

    def calculate(self) -> dict[str, list[dict[str, str]]]:
        c = self.chart
        month_branch = c.month[1]

        self.add_day_stem_branch(1, TIANYI_GUIREN)
        for rule, table, stem_only in (
            (2, TIANDE_GUIREN, False),
            (3, YUEDE_GUIREN, True),
            (4, TIANDE_HE, False),
            (5, YUEDE_HE, True),
        ):
            target = table[month_branch]
            indices = self.stems(target) if stem_only else self.chars(target)
            for index in indices:
                self.add(rule, index, f"月支={month_branch}，{PILLAR_NAMES[index]}见{target}")
        self.add_day_rule(6, TIANSHA[c.season], f"季节={c.season}")
        self.add_day_stem_branch(7, LUSHEN)
        for reference_name, reference in (("年支", c.year[1]), ("日支", c.day[1])):
            self.add_branch_table(8, YIMA, reference, reference_name)
        self.add_day_stem_branch(9, TAIJI_GUIREN)
        for ref_index, reference_name, reference in ((0, "年支", c.year[1]), (2, "日支", c.day[1])):
            target = JIANGXING[reference]
            for index in self.branches(target, exclude=ref_index):
                self.add(
                    10,
                    index,
                    f"{reference_name}={reference}，{PILLAR_NAMES[index]}支={target}",
                )
        for rule, table in ((11, XUETANG), (12, CIGUAN), (13, GUOYIN)):
            self.add_day_stem_branch(rule, table)

        for label, sequence in SANQI.items():
            position = 0
            for stem in c.stems:
                if position < 3 and stem == sequence[position]:
                    position += 1
            if position == 3:
                for index, stem in enumerate(c.stems):
                    if stem in sequence:
                        self.add(
                            14,
                            index,
                            f"四柱天干顺排见{''.join(sequence)}",
                            f"三奇贵人({label})",
                        )

        self.add_day_stem_branch(15, WENCHANG)
        for reference_name, reference in (("年支", c.year[1]), ("日支", c.day[1])):
            self.add_branch_table(16, HUAGAI, reference, reference_name)
        target = TIANYI_YI[month_branch]
        for index in self.branches(target):
            self.add(17, index, f"月支={month_branch}，{PILLAR_NAMES[index]}支={target}")
        self.add_day_stem_branch(18, JINYU)
        for empty in KONGWANG[c.xun]:
            for index in self.branches(empty):
                self.add(19, index, f"日柱={c.day}属{c.xun}旬，空亡={empty}")
        self.add_branch_table(20, ZAISHA, c.year[1], "年支")
        for rule, table in ((21, JIESHA), (22, WANGSHEN)):
            for reference_name, reference in (("年支", c.year[1]), ("日支", c.day[1])):
                self.add_branch_table(rule, table, reference, reference_name)
        for rule, table in ((23, YANGREN), (24, FEIREN)):
            self.add_day_stem_branch(rule, table)
        for reference_name, reference in (("年支", c.year[1]), ("日支", c.day[1])):
            self.add_branch_table(25, JIESHA, reference, reference_name)
        self.add_day_stem_branch(26, LIUXIA)
        self.add_day_rule(27, SIFEI[c.season], f"季节={c.season}")

        reference_branches = {c.year[1], c.day[1]}
        if c.gender == "male" and reference_branches & {"辰", "戌"}:
            for index in self.branches("亥"):
                self.add(28, index, "男命，年支或日支见辰戌，四柱见亥", "天罗(天罗地网)")
        if c.gender == "female" and reference_branches & {"丑", "未"}:
            for index in self.branches("巳"):
                self.add(28, index, "女命，年支或日支见丑未，四柱见巳", "地网(天罗地网)")
        for reference_name, reference in (("年支", c.year[1]), ("日支", c.day[1])):
            self.add_branch_table(29, TAOHUA, reference, reference_name)
        self.add_branch_table(30, GUCHEN, c.year[1], "年支")
        self.add_branch_table(31, GUAXIU, c.year[1], "年支")
        self.add_day_rule(32, YINCHA_YANGCUO)
        self.add_day_rule(33, KUIGANG)
        self.add_day_rule(34, GULUAN)
        self.add_branch_table(35, HONGLUAN, c.year[1], "年支")
        self.add_branch_table(36, TIANXI, c.year[1], "年支")

        year_index = BRANCHES.index(c.year[1])
        forward, backward = BRANCHES[(year_index + 3) % 12], BRANCHES[(year_index - 3) % 12]
        same_yinyang = (c.year[0] in GAN_YANG) == (c.gender == "male")
        gou, jiao = (forward, backward) if same_yinyang else (backward, forward)
        for target, name in ((gou, "勾煞(勾绞)"), (jiao, "绞煞(勾绞)")):
            for index in self.branches(target):
                self.add(37, index, f"年柱={c.year}，性别={c.gender}，目标支={target}", name)
        self.add_day_stem_branch(38, HONGYAN)
        self.add_day_rule(39, SHIEDABAI)

        for reference_name, reference in (("年支", c.year[1]), ("日支", c.day[1])):
            chong_index = BRANCHES.index(LIUCHONG[reference])
            same_yinyang = (reference in ZHI_YANG) == (c.gender == "male")
            target = BRANCHES[(chong_index + 1 if same_yinyang else chong_index - 1) % 12]
            for index in self.branches(target):
                self.add(
                    40,
                    index,
                    f"{reference_name}={reference}，性别={c.gender}，目标支={target}",
                )
        if c.hour in JINSHEN:
            self.add(41, 3, f"时柱={c.hour}")
        self.add_day_rule(42, TIANZHUAN[c.season], f"季节={c.season}")
        self.add_day_rule(43, DIZHUAN[c.season], f"季节={c.season}")
        for rule, table in ((44, SANGMEN), (45, DIAOKE), (46, PIMA)):
            self.add_branch_table(rule, table, c.year[1], "年支")
        for rule, values in ((47, SHILING), (48, LIUXIU), (49, BAZHUAN), (50, JIUCHOU)):
            self.add_day_rule(rule, values)

        day_hour = {c.day[1], c.hour[1]}
        nayin_element = NAYIN[c.day][-1]
        seasonal_hit = (c.season in {"春", "秋"} and bool(day_hour & {"寅", "子"})) or (
            c.season in {"冬", "夏"} and bool(day_hour & {"卯", "未", "辰"})
        )
        nayin_targets = {
            "金": {"午", "卯"},
            "木": {"午", "卯"},
            "水": {"酉", "戌"},
            "火": {"酉", "戌"},
            "土": {"辰", "巳"},
        }
        if seasonal_hit or day_hour & nayin_targets[nayin_element]:
            self.add(
                51,
                2,
                f"季节={c.season}，日时支={c.day[1]}{c.hour[1]}，日柱纳音={NAYIN[c.day]}",
            )
        self.add_day_stem_branch(52, TIANCHU)
        self.add_day_stem_branch(53, FUXING)
        for target in DEXIU[month_branch]:
            for index in self.stems(target):
                self.add(54, index, f"月支={month_branch}，{PILLAR_NAMES[index]}干={target}")
        lu = GONGLU_PAIRS.get((c.day, c.hour))
        if lu:
            name = f"拱禄(拱{lu}禄)"
            evidence = f"日柱={c.day}，时柱={c.hour}，拱禄支={lu}"
            self.add(55, 2, evidence, name)
            self.add(55, 3, evidence, name)

        return dict(zip(PILLAR_KEYS, self.results, strict=True))


def calculate_shensha(
    year: str, month: str, day: str, hour: str, gender: str
) -> dict[str, list[dict[str, str]]]:
    """计算完整 55 条神煞规则，并按四柱返回命中列表。"""
    return ShenShaCalculator(ShenShaChart(year, month, day, hour, gender)).calculate()
