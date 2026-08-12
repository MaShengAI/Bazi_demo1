from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
from typing import Any

from lunar_python import Solar

from app.domain.rules.constants import SOLAR_TERM_ORDER

# lunar-python 在跨年节气上可能返回英文内部键，先统一成中文标准名。
ALIASES = {
    "XIAO_HAN": "小寒",
    "DA_HAN": "大寒",
    "LI_CHUN": "立春",
    "YU_SHUI": "雨水",
    "JING_ZHE": "惊蛰",
    "CHUN_FEN": "春分",
    "QING_MING": "清明",
    "GU_YU": "谷雨",
    "LI_XIA": "立夏",
    "XIAO_MAN": "小满",
    "MANG_ZHONG": "芒种",
    "XIA_ZHI": "夏至",
    "XIAO_SHU": "小暑",
    "DA_SHU": "大暑",
    "LI_QIU": "立秋",
    "CHU_SHU": "处暑",
    "BAI_LU": "白露",
    "QIU_FEN": "秋分",
    "HAN_LU": "寒露",
    "SHUANG_JIANG": "霜降",
    "LI_DONG": "立冬",
    "XIAO_XUE": "小雪",
    "DA_XUE": "大雪",
    "DONG_ZHI": "冬至",
}


def generate(start_year: int, end_year: int) -> dict[str, Any]:
    """按年提取24节气，并把依赖版本写入数据集元信息。"""
    version = importlib.metadata.version("lunar-python")
    terms = []
    for year in range(start_year, end_year + 1):
        # 取年中日期可获得覆盖该公历年首尾的完整节气窗口。
        table = Solar.fromYmd(year, 7, 1).getLunar().getJieQiTable()
        found: dict[str, str] = {}
        for raw_name, solar in table.items():
            name = ALIASES.get(raw_name, raw_name)
            if solar.getYear() == year and name in SOLAR_TERM_ORDER:
                found[name] = solar.toYmdHms()
        # 任何一年缺少节气都中止生成，禁止写出不完整数据集。
        missing = set(SOLAR_TERM_ORDER) - set(found)
        if missing:
            raise RuntimeError(f"{year} is missing terms: {sorted(missing)}")
        for name in SOLAR_TERM_ORDER:
            terms.append(
                {
                    "name": name,
                    "year": year,
                    "beijing_raw": found[name],
                    "lunar_python_version": version,
                }
            )
    return {
        "metadata": {
            "dataset_version": f"solar-terms-{start_year}-{end_year}-lunar-python-{version}",
            "start_year": start_year,
            "end_year": end_year,
            "source_basis": "lunar-python output interpreted as fixed Beijing time UTC+08:00",
            "lunar_python_version": version,
            "record_count": len(terms),
        },
        "terms": terms,
    }


def main() -> None:
    """命令行入口，默认生成满足百岁流年边界的1900—2201年数据。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=1900)
    parser.add_argument("--end-year", type=int, default=2201)
    parser.add_argument("--output", type=Path, default=Path("app/data/solar_terms.json"))
    args = parser.parse_args()
    payload = generate(args.start_year, args.end_year)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"wrote {payload['metadata']['record_count']} records to {args.output}")


if __name__ == "__main__":
    main()
