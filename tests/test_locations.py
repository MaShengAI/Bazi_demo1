from pathlib import Path

import pytest

from app.repositories.locations import (
    CHINA_PROVINCES,
    LocationDataError,
    LocationRepository,
    load_china_locations,
)


def test_city_dataset_covers_exactly_34_provincial_regions() -> None:
    locations = load_china_locations()
    assert len(locations) == 392
    assert {item.province for item in locations} == set(CHINA_PROVINCES)
    assert len({item.location_id for item in locations}) == 392
    assert len({(item.province, item.city) for item in locations}) == 392


def test_all_34_regions_use_beijing_time(tmp_path: Path) -> None:
    repository = LocationRepository(path=tmp_path / "locations.sqlite3")
    assert {
        repository.get(location_id).timezone_id  # type: ignore[union-attr]
        for location_id in (1101, 3101, 7101, 8100, 8200)
    } == {"Asia/Shanghai"}


def test_foreign_or_incomplete_dataset_is_rejected(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.csv"
    invalid.write_text(
        "id,province,city,longitude,latitude\n9999,海外,纽约,74.0,40.7\n",
        encoding="utf-8",
    )
    with pytest.raises(LocationDataError):
        load_china_locations(invalid)
