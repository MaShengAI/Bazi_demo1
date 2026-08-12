from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy import text

from app.database import Database


def check_api(url: str) -> None:
    with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310 - fixed internal URL
        if response.status != 200:
            raise RuntimeError(f"API health returned HTTP {response.status}")


def check_database() -> None:
    database = Database.from_env()
    if database is None:
        raise RuntimeError("BAZI_DATABASE_URL is not configured")
    try:
        with database.session() as session:
            session.execute(text("SELECT 1"))
    finally:
        database.dispose()


def check_worker(path: Path, max_age: float) -> None:
    check_database()
    age = time.time() - path.stat().st_mtime
    if age > max_age:
        raise RuntimeError(f"worker heartbeat is stale ({age:.1f}s > {max_age:.1f}s)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Container health probes")
    parser.add_argument("component", choices=("api", "database", "worker"))
    parser.add_argument("--url", default="http://127.0.0.1:8000/health/live")
    parser.add_argument(
        "--heartbeat",
        type=Path,
        default=Path(
            os.getenv(
                "BAZI_WORKER_HEARTBEAT_FILE",
                str(Path(tempfile.gettempdir()) / "bazi-worker-heartbeat"),
            )
        ),
    )
    parser.add_argument("--max-age", type=float, default=90.0)
    args = parser.parse_args()
    try:
        if args.component == "api":
            check_api(args.url)
        elif args.component == "database":
            check_database()
        else:
            check_worker(args.heartbeat, args.max_age)
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print(f"unhealthy: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
