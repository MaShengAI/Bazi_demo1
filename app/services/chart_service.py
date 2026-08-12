from __future__ import annotations

from app import __version__
from app.domain.bazi.calculator import calculate_four_pillars
from app.domain.calendar.solar_terms import SolarTermRepository
from app.domain.luck.calculator import (
    build_major_luck_cycles,
    calculate_luck_start,
    determine_direction,
)
from app.domain.rules.constants import RULESET_VERSION
from app.domain.rules.shensha import SHENSHA_RULESET_VERSION
from app.domain.solar_time.service import calculate_true_solar_time
from app.domain.timezone.service import normalize_local_time
from app.repositories.locations import LocationRepository
from app.schemas.chart import ChartRequest


class ChartServiceError(RuntimeError):
    """可以转换成统一 API 错误结构的业务异常。"""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ChartService:
    """严格按地点、时区、真太阳时、四柱、起运的顺序编排计算。"""

    def __init__(self, locations: LocationRepository, terms: SolarTermRepository):
        self.locations = locations
        self.terms = terms

    def calculate(self, request: ChartRequest) -> dict[str, object]:
        """生成完整排盘，并保留可供复核的计算轨迹。"""
        trace: list[dict[str, object]] = []

        # 地点决定时区和经纬度，因此必须是整个计算链的第一步。
        location = self.locations.get(request.location_id)
        if location is None:
            raise ChartServiceError("location_not_found", "未找到指定的中国城市地点ID")
        trace.append(
            {"step": 1, "operation": "resolve_location", "location_id": location.location_id}
        )

        # 先确定真实 UTC 瞬间与标准时间，后续不得再次手动扣除夏令时。
        normalized = normalize_local_time(request.parsed_birth(), location.timezone_id)
        trace.append(
            {
                "step": 2,
                "operation": "normalize_timezone_and_dst",
                "utc_instant": normalized.utc_instant.isoformat(),
                "dst_offset": normalized.dst_offset,
            }
        )
        # 真太阳时用于日柱、时柱；年月节气仍以同一个真实 UTC 瞬间比较。
        solar = calculate_true_solar_time(normalized, location.longitude, location.latitude)
        trace.append(
            {
                "step": 3,
                "operation": "calculate_true_solar_time",
                "longitude_correction_seconds": solar.longitude_correction_seconds,
                "equation_of_time_seconds": solar.equation_of_time_seconds,
            }
        )
        # 原始四柱供大运继续计算，展示结构则直接返回给 API 客户端。
        raw_pillars, pillar_payload = calculate_four_pillars(
            normalized.utc_instant,
            solar.true_solar_datetime,
            self.terms,
            gender=request.gender.value,
        )
        trace.append(
            {
                "step": 4,
                "operation": "calculate_four_pillars",
                "pillars": [raw_pillars.year, raw_pillars.month, raw_pillars.day, raw_pillars.hour],
                "day_rollover": "true_solar_23:00",
                "year_boundary": "li_chun",
                "month_boundary": "jie_only",
            }
        )
        gender = request.gender.value
        direction = determine_direction(raw_pillars.year[0], gender)
        luck_start, start_datetime = calculate_luck_start(
            normalized.utc_instant, solar.true_solar_datetime, direction, self.terms
        )
        cycles = build_major_luck_cycles(
            raw_pillars, solar.true_solar_datetime, start_datetime, direction, self.terms
        )
        trace.append(
            {
                "step": 5,
                "operation": "calculate_luck",
                "direction": direction.direction,
                "cycle_count": len(cycles),
            }
        )
        return {
            "request": request.model_dump(mode="json"),
            "location": location.to_dict(),
            "time_normalization": {**normalized.to_dict(), **solar.to_dict()},
            "pillars": pillar_payload,
            "luck_direction": direction.to_dict(),
            "luck_start": luck_start,
            "major_luck_cycles": cycles,
            "ruleset_versions": {
                "service": __version__,
                "core": RULESET_VERSION,
                "shen_sha": SHENSHA_RULESET_VERSION,
                "solar_terms": self.terms.metadata["dataset_version"],
                "lunar_python": self.terms.metadata["lunar_python_version"],
            },
            "calculation_trace": trace,
        }
