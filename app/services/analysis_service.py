from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from app.integrations.llm import LLMProvider, LLMProviderError
from app.schemas.chart import ChartRequest
from app.services.chart_service import ChartService

ANALYSIS_DISCLAIMER = (
    "本分析属于传统文化视角的参考性内容，不构成医疗诊断、投资建议、法律意见或"
    "对婚姻、生育、疾病、灾祸及人生事件的确定性预测。重要决定应结合现实信息并咨询专业人士。"
)

# 统一控制所有分析板块的长度
ANALYSIS_TARGET_CHARS = 3500
ANALYSIS_MINIMUM_CHARS = 2200
ANALYSIS_MAXIMUM_CHARS = 4000


@dataclass(frozen=True)
class AnalysisSectionSpec:
    code: str
    title: str
    focus: str
    include_annual_years: bool = False


ANALYSIS_SECTIONS = (
    AnalysisSectionSpec(
        "personality",
        "性格特点与行为模式",
        "1.原生家庭性格烙印分析。2.社交性格与职场人格分析。3.责任感与压力承受力分析与建议。4.核心自我与婚姻性格分析与建议。5.晚年心态等生活状态分析与建议。6.性格优点与不足分析与建议。",
    ),
    AnalysisSectionSpec(
        "relationship",
        "恋爱情感与婚姻状况预测",
        "1.自身婚恋性格特质。2.配偶基础特征(年龄/性格/品行/经济条件等)。3.配偶助力方向(事业/财运/家庭等维度)。4.关键婚动节点(早婚/晚婚倾向/成婚利好年份)。5.夫妻相处模式与沟通风格分析。6.婚姻潜在风险提示(情感纠葛/相处矛盾/关系裂痕等）。7.未来五年婚恋发展趋势。8.八字合婚互补与其他婚恋建议。",
    ),
    AnalysisSectionSpec(
        "children",
        "子女状况与关系预测",
        "1.子女数量倾向(多胎/独子等)。2.头胎性别倾向(男/女)。3.整体生育时间范围(如早育/晚育阶段)。4.育儿关键注意节点。5.流年与未来五年生育可能年份分析。6.与子女互动模式(亲密/疏离等)。7.子女成就指数。8.其他子女方面补充建议。",
    ),
    AnalysisSectionSpec(
        "education",
        "学业发展分析与建议",
        "1.先天学习天赋与思维类型偏向（文科/理科/艺术/技术）。2.学习行为模式与考场发挥特质。3.学历层级定位与升学潜力分析。4.分阶段学业起伏走势（小学/中学/大学）。5.未来五年学业考运、考证升学流年分析。6.中长期学习规划建议。7.学业提升方法与文昌相关调理建议。",
    ),
    AnalysisSectionSpec(
        "career",
        "事业发展分析与建议",
        "1.命局特质与职业适配方向。2.事业层级定位与发展路径。3.个人单干与合伙建议。4.未来五年大运流年事业发展运势。5.中长期大运走势与守成策略。6.风水调理与职场开运建议。",
    ),
    AnalysisSectionSpec(
        "wealth",
        "财运状况与求财建议",
        "1.命局财星配置与求财特质。2.命局特质与经济来源分析。3.收入结构分析与财富层级定位。4.破财风险点与守财策略。5.未来五年财运走势详解。6.中长期大运财富积累趋势。7.求财风水与理财开运建议。",
    ),
    AnalysisSectionSpec(
        "health",
        "个人健康与灾厄状况预测",
        "1.先天体质特征与五行失衡分析。2.优势器官与薄弱脏腑预警。3.潜在慢性病与健康风险。4.未来五年健康运势详解。5.中年大运健康隐患与防范。6.养生调理与起居开运建议。",
    ),
    AnalysisSectionSpec(
        "life_cycles",
        "大运流年与人生起伏运程",
        "1.今年所在的大运流年阶段指引。2.早年运势:学业与成长轨迹分析。3.青年磨炼:迷茫探索与压力应对分析。4.中年黄金期:事业家庭分析。5.中老年运势:守成稳健与身心调养分析。6.晚年福运与人生关键节点把握。",
        include_annual_years=True,
    ),
)

SYSTEM_PROMPT = (
    "\n".join(
        (
            (
                "你是一位有三十年实战经验的八字命理分析师。说话自然亲切，像一位懂命理的"
                "老朋友在娓娓道来，专业不生硬、通俗不浅薄。你只能依据用户提供的结构化排盘"
                "事实撰写，不得修改或重新计算四柱、十神、藏干、纳音、神煞、起运、大运和流年。"
            ),
            "",
            "严格遵守以下规则：",
            (
                "1. 叙述口吻：全程第二人称，直接用“你”开头陈述。不使用第一人称，禁止"
                "出现：我认为、基于我的判断、依我看这类表述。"
            ),
            (
                "2. 避免使用“综上所述”、“从排盘来看”、“基于以上分析”、“由此可见”、"
                "“结合命局”等过渡、学术化话术，直接陈述内容。"
            ),
            (
                "3. 专业温和，不恐吓、不绝对宿命化。所有论断偏向趋势、倾向性描述，避免"
                "“一定会、必定、注定、大祸、必遭”这类极端吓人词语；区分先天特质和后天"
                "选择，强调后天行为可以影响走向。"
            ),
            "4. 不得仅凭单个神煞下结论，不得编造输入中没有的旺衰评分、格局、喜用神或现实经历。",
            "5. 不得声称能够确定预测婚姻、生育、疾病、死亡、灾祸、财富收益或具体事件。",
            (
                "6. 命理仅作为传统文化参考，不要当成确定事实。健康部分只讲体质倾向，不得"
                "给出诊断或替代就医；婚姻、事业、财运只描述趋势特质，财运部分不得给出具体"
                "投资标的或保证收益，强调个人选择、环境会改变结果。"
            ),
            "7. 用自然段落叙述，少用bullet point，像在跟人聊天一样，口语化但保持专业感。",
            (
                "8. 禁止额外输出：不要开头问候，不要结尾总结，不要额外提示语，不要输出"
                "标题、编号、Markdown表格或免责声明。只输出8个板块的解析文本。"
            ),
            "9. 每次只写指定板块，目标约3500个中文字符，且正文控制在2200—4000个中文字符.",
        )
    )
    + "\n"
)


class AnalysisServiceError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def build_model_context(
    chart: dict[str, object], *, include_annual_years: bool, analysis_date: date | None = None
) -> dict[str, object]:
    """只发送解读所需字段；姓名、经纬度、计算轨迹不会发送给外部模型。"""
    request = cast(dict[str, Any], chart["request"])
    location = cast(dict[str, Any], chart["location"])
    time_data = cast(dict[str, Any], chart["time_normalization"])
    pillars = cast(dict[str, dict[str, Any]], chart["pillars"])
    luck_start = cast(dict[str, Any], chart["luck_start"])
    cycles = cast(list[dict[str, Any]], chart["major_luck_cycles"])

    compact_pillars = {}
    for key, pillar in pillars.items():
        compact_pillars[key] = {
            field: pillar[field]
            for field in (
                "pillar",
                "main_star",
                "hidden_stems",
                "na_yin",
                "star_fortune",
                "self_seat",
                "void",
                "shen_sha",
            )
        }

    compact_cycles = []
    for cycle in cycles:
        item: dict[str, object] = {
            field: cycle[field]
            for field in (
                "index",
                "pillar",
                "start_age",
                "end_age",
                "start_datetime",
                "end_datetime",
                "ten_god_of_stem",
                "shen_sha",
            )
        }
        if include_annual_years:
            item["annual_years"] = [
                {
                    field: annual[field]
                    for field in (
                        "gregorian_year",
                        "pillar",
                        "age",
                        "ten_god",
                        "shen_sha",
                    )
                }
                for annual in cycle["annual_years"]
            ]
        compact_cycles.append(item)

    return {
        "analysis_date": (
            analysis_date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
        ).isoformat(),
        "profile": {
            "gender": request["gender"],
            "birth_local_datetime": request["birth_local_datetime"],
            "birth_city": location["name"],
            "true_solar_datetime": time_data["true_solar_datetime"],
        },
        "calculation_rules": {
            "year_boundary": "立春",
            "month_boundary": "十二节",
            "day_rollover": "真太阳时23:00",
            "ruleset_versions": chart["ruleset_versions"],
        },
        "pillars": compact_pillars,
        "luck": {
            "direction": chart["luck_direction"],
            "start": {
                "reference_jie": luck_start["reference_jie"],
                "start_age": luck_start["start_age"],
                "start_datetime": luck_start["start_datetime"],
            },
            "major_cycles": compact_cycles,
        },
    }


class AnalysisService:
    def __init__(
        self,
        chart_service: ChartService,
        provider: LLMProvider,
        *,
        max_concurrency: int = 2,
        target_chars: int = ANALYSIS_TARGET_CHARS,
        minimum_chars: int = ANALYSIS_MINIMUM_CHARS,
        maximum_chars: int = ANALYSIS_MAXIMUM_CHARS,
        max_attempts: int = 2,
    ):
        self.chart_service = chart_service
        self.provider = provider
        self.target_chars = target_chars
        self.minimum_chars = minimum_chars
        self.maximum_chars = maximum_chars
        self.max_attempts = max_attempts
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def analyze(self, request: ChartRequest) -> dict[str, object]:
        chart = self.chart_service.calculate(request)
        tasks = [
            asyncio.create_task(self._generate_section(spec, chart)) for spec in ANALYSIS_SECTIONS
        ]
        try:
            sections = await asyncio.gather(*tasks)
        except Exception:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        warnings = [
            f"{section['title']}长度为{section['char_count']}字，未达到目标区间"
            for section in sections
            if section["length_status"] != "ok"
        ]
        return {
            "chart": chart,
            "analysis": {
                "model": self.provider.model_name,
                "section_target_chars": self.target_chars,
                "sections": sections,
                "warnings": warnings,
                "disclaimer": ANALYSIS_DISCLAIMER,
            },
        }

    async def _generate_section(
        self, spec: AnalysisSectionSpec, chart: dict[str, object]
    ) -> dict[str, object]:
        length_hint = ""
        content = ""
        for attempt in range(1, self.max_attempts + 1):
            user_prompt = build_section_prompt(
                spec,
                chart,
                target_chars=self.target_chars,
                minimum_chars=self.minimum_chars,
                maximum_chars=self.maximum_chars,
                length_hint=length_hint,
            )
            try:
                async with self._semaphore:
                    content = await self.provider.complete(SYSTEM_PROMPT, user_prompt)
            except LLMProviderError as exc:
                raise AnalysisServiceError(exc.code, str(exc), exc.details) from exc
            content = _normalize_content(content)
            count = _character_count(content)
            if self.minimum_chars <= count <= self.maximum_chars:
                break
            if attempt < self.max_attempts:
                direction = "扩写" if count < self.minimum_chars else "精简"
                length_hint = f"上次输出为{count}字符，请明显{direction}并重新完整作答。"

        count = _character_count(content)
        status = "ok"
        if count < self.minimum_chars:
            status = "short"
        elif count > self.maximum_chars:
            status = "long"
        return {
            "code": spec.code,
            "title": spec.title,
            "content": content,
            "char_count": count,
            "length_status": status,
        }

    async def close(self) -> None:
        await self.provider.close()


def _normalize_content(content: str) -> str:
    content = content.strip()
    content = re.sub(r"^```(?:markdown|text)?\s*", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


def _character_count(content: str) -> int:
    return len(re.sub(r"\s+", "", content))


def build_section_prompt(
    spec: AnalysisSectionSpec,
    chart: dict[str, object],
    *,
    target_chars: int = ANALYSIS_TARGET_CHARS,
    minimum_chars: int = ANALYSIS_MINIMUM_CHARS,
    maximum_chars: int = ANALYSIS_MAXIMUM_CHARS,
    length_hint: str = "",
    analysis_date: date | None = None,
) -> str:
    context = build_model_context(
        chart,
        include_annual_years=spec.include_annual_years,
        analysis_date=analysis_date,
    )
    context_json = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    return (
        f"本次板块：{spec.title}\n"
        f"写作重点：{spec.focus}\n"
        f"长度要求：目标约{target_chars}个中文字符，全文必须控制在"
        f"{minimum_chars}—{maximum_chars}字符。"
        f"必须完成最终正文后再结束回答。{length_hint}\n"
        f"结构化排盘数据：\n{context_json}"
    )
