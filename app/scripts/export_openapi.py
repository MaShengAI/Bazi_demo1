from __future__ import annotations

import json
from pathlib import Path

from app.main import app


def main() -> None:
    """从当前 FastAPI 路由重新导出可提交版本库的 OpenAPI 文件。"""
    target = Path("openapi.json")
    target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
