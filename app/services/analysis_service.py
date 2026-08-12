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
        "分析稳定性格倾向、思考和决策方式、人际互动、压力反应、优势、盲点及成长建议。",
    ),
    AnalysisSectionSpec(
        "relationship",
        "恋爱情感与婚姻状况预测",
        "分析亲密关系需求、表达方式、择偶倾向、相处矛盾和关系经营建议；不得断言必然婚变。",
    ),
    AnalysisSectionSpec(
        "children",
        "子女状况与关系预测",
        "分析传统命理中的子女缘、教养互动和关系课题；不得预测具体子女数量、性别或生育结果。",
    ),
    AnalysisSectionSpec(
        "education",
        "学业发展分析与建议",
        "分析学习方式、注意力和执行特点、适合的训练环境、阶段性阻力以及可执行的学习建议。",
    ),
    AnalysisSectionSpec(
        "career",
        "事业发展预测与建议",
        "分析工作动机、协作与管理风格、职业环境倾向、发展节奏、风险和可执行的事业建议。",
    ),
    AnalysisSectionSpec(
        "wealth",
        "财运状况与求财建议",
        "分析收入与资源管理倾向、求财方式、风险偏好和财务纪律；不得推荐具体证券或保证收益。",
    ),
    AnalysisSectionSpec(
        "health",
        "个人健康与灾厄状况预测",
        "只做生活方式与风险意识提醒，不诊断疾病、不预测死亡或重大灾祸；症状应建议就医。",
    ),
    AnalysisSectionSpec(
        "life_cycles",
        "大运流年与人生起伏运程",
        "结合起运、大运和流年按年龄与公历时间梳理主要阶段、转折窗口、机会和风险应对。",
        include_annual_years=True,
    ),
)

SYSTEM_PROMPT = """你是传统八字文化分析写作助手。你只能依据用户提供的结构化排盘事实撰写，
不得修改或重新计算四柱、十神、藏干、纳音、神煞、起运、大运和流年。

严格遵守以下规则：
1. 结论使用“倾向、可能、较容易”等概率语言，区分排盘事实与文化解释。
2. 不得声称能够确定预测婚姻、生育、疾病、死亡、灾祸、财富收益或具体事件。
3. 健康部分不得给出诊断或替代就医；财运部分不得给出具体投资标的或保证收益。
4. 不得仅凭单个神煞下结论，不得编造输入中没有的旺衰评分、格局、喜用神或现实经历。
5. 给出具体、可执行且现实的建议，并同时说明有利表现和潜在盲点。
6. 每次只写指定板块，目标约1500个中文字符，使用自然段；不要输出标题、编号、Markdown表格或免责声明。
"""


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
        target_chars: int = 1500,
        minimum_chars: int = 1100,
        maximum_chars: int = 1900,
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
    target_chars: int = 1500,
    minimum_chars: int = 1100,
    maximum_chars: int = 1900,
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
        f"长度要求：约{target_chars}个中文字符，建议控制在"
        f"{minimum_chars}—{maximum_chars}字符。{length_hint}\n"
        f"结构化排盘数据：\n{context_json}"
    )
