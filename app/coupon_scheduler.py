"""No merchant/LLM secrets required. Run one process; duplicate runs are safe."""

from __future__ import annotations

import logging
import os
import time

from sqlalchemy import select

from app.database import Database
from app.models import UserRecord
from app.services.cards import ensure_account, lock_user, now_utc, week_window

logger = logging.getLogger("bazi.coupons")


def issue_current_week(database: Database) -> int:
    """Small keyset batches; one transaction per user avoids locking the user table."""
    count, after = 0, ""
    window = week_window(now_utc())
    while True:
        with database.session() as session:
            ids = session.scalars(
                select(UserRecord.id)
                .where(UserRecord.id > after, UserRecord.status == "active")
                .order_by(UserRecord.id)
                .limit(200)
            ).all()
        if not ids:
            return count
        for user_id in ids:
            now = now_utc()
            if week_window(now) != window:
                return count  # Restart at the new boundary rather than issue the old week.
            with database.session() as session:
                lock_user(session, user_id)
                ensure_account(session, user_id, now)
                session.commit()
            count += 1
        after = ids[-1]


def main() -> None:
    if os.getenv("BAZI_PAY_MODE", "disabled") == "disabled":
        return
    database = Database.from_env()
    if database is None:
        raise ValueError("Coupon scheduler requires BAZI_DATABASE_URL")
    last_window = None
    try:
        while True:
            current = week_window(now_utc())
            if current != last_window:
                try:
                    issue_current_week(database)
                    last_window = current
                except Exception as exc:
                    logger.error("coupon_issuance_failed: %s", type(exc).__name__)
            time.sleep(30)
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
