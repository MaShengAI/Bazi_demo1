from __future__ import annotations

import csv
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parents[1] / "data" / "locations.sqlite3"
DEFAULT_CSV_PATH = Path(__file__).parents[1] / "data" / "china_city_coordinates.csv"

# 产品范围固定为中国34个省级行政区。这个集合既用于导入校验，也用于接口验收。
CHINA_PROVINCES = (
    "北京市",
    "天津市",
    "河北省",
    "山西省",
    "内蒙古自治区",
    "辽宁省",
    "吉林省",
    "黑龙江省",
    "上海市",
    "江苏省",
    "浙江省",
    "安徽省",
    "福建省",
    "江西省",
    "山东省",
    "河南省",
    "湖北省",
    "湖南省",
    "广东省",
    "广西壮族自治区",
    "海南省",
    "重庆市",
    "四川省",
    "贵州省",
    "云南省",
    "西藏自治区",
    "陕西省",
    "甘肃省",
    "青海省",
    "宁夏回族自治区",
    "新疆维吾尔自治区",
    "香港特别行政区",
    "澳门特别行政区",
    "台湾省",
)

# 产品规则要求34个省级行政区全部统一按北京时间解释出生证明时间。
CHINA_TIMEZONE_ID = "Asia/Shanghai"


@dataclass(frozen=True)
class Location:
    """中国城市地点记录；location_id 来自用户提供的城市经纬度表。"""

    location_id: int
    province: str
    city: str
    longitude: float
    latitude: float
    timezone_id: str
    coordinate_source: str = "用户提供的中国城市经纬度CSV"

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        # name 作为通用展示字段保留，方便前端直接显示而不必判断地点层级。
        result["name"] = self.city
        return result


SCHEMA = """
CREATE TABLE IF NOT EXISTS china_city_locations_v2 (
  location_id INTEGER PRIMARY KEY,
  province TEXT NOT NULL,
  city TEXT NOT NULL,
  longitude REAL NOT NULL,
  latitude REAL NOT NULL,
  timezone_id TEXT NOT NULL,
  coordinate_source TEXT NOT NULL,
  UNIQUE(province, city)
);
CREATE INDEX IF NOT EXISTS idx_china_location_province
ON china_city_locations_v2(province, city);
"""


class LocationDataError(RuntimeError):
    """中国城市CSV字段、范围或完整性不符合产品要求。"""


def load_china_locations(path: Path = DEFAULT_CSV_PATH) -> tuple[Location, ...]:
    """读取并验证城市数据，任何缺省省份、重复城市或非法坐标都会阻止启动。"""
    if not path.exists():
        raise LocationDataError(f"中国城市经纬度文件不存在：{path}")

    locations: list[Location] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"id", "province", "city", "longitude", "latitude"}
        if set(reader.fieldnames or ()) != required:
            raise LocationDataError(f"城市CSV字段必须恰好为：{sorted(required)}")
        for line_number, row in enumerate(reader, start=2):
            try:
                location = Location(
                    location_id=int(row["id"]),
                    province=row["province"].strip(),
                    city=row["city"].strip(),
                    longitude=float(row["longitude"]),
                    latitude=float(row["latitude"]),
                    timezone_id=CHINA_TIMEZONE_ID,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise LocationDataError(f"城市CSV第{line_number}行格式错误") from exc
            if location.province not in CHINA_PROVINCES:
                raise LocationDataError(
                    f"城市CSV第{line_number}行包含范围外省级行政区：{location.province}"
                )
            if not 70 <= location.longitude <= 140 or not 0 <= location.latitude <= 60:
                raise LocationDataError(f"城市CSV第{line_number}行经纬度超出中国合理范围")
            locations.append(location)

    ids = [item.location_id for item in locations]
    city_keys = [(item.province, item.city) for item in locations]
    if len(ids) != len(set(ids)):
        raise LocationDataError("城市CSV存在重复 location_id")
    if len(city_keys) != len(set(city_keys)):
        raise LocationDataError("城市CSV存在重复的省份+城市")
    actual_provinces = {item.province for item in locations}
    if actual_provinces != set(CHINA_PROVINCES):
        missing = sorted(set(CHINA_PROVINCES) - actual_provinces)
        extra = sorted(actual_provinces - set(CHINA_PROVINCES))
        raise LocationDataError(f"城市CSV未完整覆盖34个省级行政区；缺少={missing}，多出={extra}")
    return tuple(locations)


class LocationRepository:
    """只装载中国城市数据的 SQLite 只读查询仓库。"""

    def __init__(self, path: Path = DEFAULT_DB_PATH, source_path: Path = DEFAULT_CSV_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        source_locations = load_china_locations(source_path)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            # SQLite 在这里是可重建缓存；每次启动以版本库内CSV为唯一事实来源。
            connection.execute("DELETE FROM china_city_locations_v2")
            connection.executemany(
                """INSERT INTO china_city_locations_v2
                (location_id,province,city,longitude,latitude,timezone_id,coordinate_source)
                VALUES (?,?,?,?,?,?,?)""",
                [
                    (
                        item.location_id,
                        item.province,
                        item.city,
                        item.longitude,
                        item.latitude,
                        item.timezone_id,
                        item.coordinate_source,
                    )
                    for item in source_locations
                ],
            )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, location_id: int) -> Location | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM china_city_locations_v2 WHERE location_id=?", (location_id,)
            ).fetchone()
        return Location(**dict(row)) if row else None

    def provinces(self) -> list[dict[str, str]]:
        return [{"code": province, "name": province} for province in CHINA_PROVINCES]

    def cities(self, province: str) -> list[dict[str, object]]:
        if province not in CHINA_PROVINCES:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT location_id AS code, city AS name, longitude, latitude
                FROM china_city_locations_v2 WHERE province=? ORDER BY location_id""",
                (province,),
            ).fetchall()
        return [dict(row) for row in rows]
