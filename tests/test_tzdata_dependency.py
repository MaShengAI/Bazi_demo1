import importlib.metadata
from zoneinfo import TZPATH, ZoneInfo, reset_tzpath


def test_tzdata_package_is_explicit_fallback() -> None:
    assert importlib.metadata.version("tzdata") == "2025.2"
    original = TZPATH
    try:
        ZoneInfo.clear_cache()
        reset_tzpath([])
        zone = ZoneInfo("Asia/Shanghai")
        assert zone.key == "Asia/Shanghai"
    finally:
        ZoneInfo.clear_cache()
        reset_tzpath(original)
