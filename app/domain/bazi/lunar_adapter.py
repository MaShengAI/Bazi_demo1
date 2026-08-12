from __future__ import annotations

from datetime import datetime

from lunar_python import Solar


def day_pillar_at_true_solar_time(value: datetime) -> str:
    """取得日柱；sect=1 强制晚子时23点起算作次日。"""
    solar = Solar.fromYmdHms(
        value.year, value.month, value.day, value.hour, value.minute, value.second
    )
    eight_char = solar.getLunar().getEightChar()
    # lunar-python 默认 sect=2（午夜换日），本项目必须显式覆盖。
    eight_char.setSect(1)
    return eight_char.getDay()
