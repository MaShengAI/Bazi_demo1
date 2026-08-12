from datetime import datetime

from app.domain.solar_time.service import calculate_true_solar_time, equation_of_time_seconds
from app.domain.timezone.service import normalize_local_time


def test_longitude_correction_direction() -> None:
    normalized = normalize_local_time(datetime(2000, 1, 1, 12, 0), "Asia/Shanghai")
    east = calculate_true_solar_time(normalized, 121.0, 31.0)
    west = calculate_true_solar_time(normalized, 119.0, 31.0)
    assert east.longitude_correction_seconds == 240
    assert west.longitude_correction_seconds == -240
    assert east.true_solar_datetime > west.true_solar_datetime


def test_equation_of_time_is_present_and_plausible() -> None:
    seconds = equation_of_time_seconds(datetime(2024, 2, 11, 12, 0))
    assert -16 * 60 < seconds < -12 * 60


def test_true_solar_time_can_cross_date() -> None:
    normalized = normalize_local_time(datetime(2000, 1, 1, 0, 1), "Etc/GMT")
    result = calculate_true_solar_time(normalized, -7.5, 0)
    assert result.true_solar_datetime.date().isoformat() == "1999-12-31"
