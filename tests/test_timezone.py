from datetime import datetime

import pytest

from app.domain.timezone.service import TimeNormalizationError, normalize_local_time


def test_shanghai_1988_dst_is_restored_to_standard_time() -> None:
    result = normalize_local_time(datetime(1988, 7, 10, 12, 30), "Asia/Shanghai")
    assert result.utc_offset == "+09:00"
    assert result.dst_offset == "+01:00"
    assert result.standard_utc_offset == "+08:00"
    assert result.standard_local_time.isoformat() == "1988-07-10T11:30:00+08:00"
    assert result.utc_instant.isoformat() == "1988-07-10T03:30:00+00:00"


def test_non_integer_standard_offset() -> None:
    result = normalize_local_time(datetime(2000, 1, 1, 12, 0), "Asia/Kathmandu")
    assert result.standard_utc_offset == "+05:45"


def test_ambiguous_fall_back_time_is_rejected() -> None:
    with pytest.raises(TimeNormalizationError) as caught:
        normalize_local_time(datetime(2024, 11, 3, 1, 30), "America/New_York")
    assert caught.value.code == "ambiguous_local_time"
    assert caught.value.details["candidate_offsets"] == ["-04:00", "-05:00"]


def test_nonexistent_spring_forward_time_is_rejected() -> None:
    with pytest.raises(TimeNormalizationError) as caught:
        normalize_local_time(datetime(2024, 3, 10, 2, 30), "America/New_York")
    assert caught.value.code == "nonexistent_local_time"
