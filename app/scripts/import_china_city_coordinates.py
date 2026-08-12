from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from app.repositories.locations import DEFAULT_CSV_PATH, load_china_locations


def _decode_source(path: Path) -> str:
    """优先按 UTF-8 解码；用户提供的旧式中文CSV则回退到 GB18030。"""
    payload = path.read_bytes()
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return payload.decode("gb18030")


def main() -> None:
    """验证外部城市表，成功后再原子替换项目内的 UTF-8 数据文件。"""
    parser = argparse.ArgumentParser(description="导入中国34个省级行政区的城市经纬度CSV")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_CSV_PATH)
    args = parser.parse_args()

    normalized = _decode_source(args.source).replace("\r\n", "\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", suffix=".csv", delete=False, dir=args.output.parent
    ) as temporary:
        temporary.write(normalized)
        temporary_path = Path(temporary.name)
    try:
        locations = load_china_locations(temporary_path)
        temporary_path.replace(args.output)
    finally:
        temporary_path.unlink(missing_ok=True)
    print(f"已导入{len(locations)}条中国城市记录：{args.output}")


if __name__ == "__main__":
    main()
