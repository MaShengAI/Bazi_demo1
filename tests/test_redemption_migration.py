"""Preserve previously granted weekly/refund coupons while adding code rewards."""

import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from app.commerce_models import CardWallet, WeeklyCoupon
from app.database import Database
from app.models import UserRecord
from app.services.redemptions import RedemptionService


def test_upgrade_preserves_old_grants_and_enables_independent_rewards(tmp_path, monkeypatch):
    url = "sqlite+pysqlite:///" + (tmp_path / "codes.sqlite3").as_posix()
    monkeypatch.setenv("BAZI_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261101_0007")
    db = Database(url)
    uid = str(uuid.uuid4())
    with db.session() as s:
        s.add(UserRecord(id=uid, status="active"))
        s.flush()
        s.add(CardWallet(user_id=uid, balance=3))
        for period, source in [("2026-11-02", None), (None, uuid.uuid4().hex)]:
            s.execute(
                text(
                    "INSERT INTO weekly_coupons (id,user_id,period_start,source_refund_id,expires_at) "
                    "VALUES (:id,:uid,:period,:source,'2099-01-01')"
                ),
                {"id": str(uuid.uuid4()), "uid": uid, "period": period, "source": source},
            )
        s.commit()
    command.upgrade(config, "head")
    with db.session() as s:
        old = list(s.scalars(select(WeeklyCoupon)))
        assert len(old) == 2 and all(c.amount == 5000 and c.source_code_id is None for c in old)
        assert s.get(CardWallet, uid).balance == 3
    service = RedemptionService(db)
    batch = service.generate(
        kind="coupon",
        value=3000,
        quantity=1,
        label="迁移验收",
        request_key=uuid.uuid4().hex,
        operator="owner",
    )
    result = service.redeem(uid, batch["codes"][0])
    assert result["value"] == 3000
    with db.session() as s:
        assert len(list(s.scalars(select(WeeklyCoupon)))) == 3
        assert s.get(CardWallet, uid).balance == 3
        assert not s.execute(text("PRAGMA foreign_key_check")).all()
    db.dispose()
