"""Upgrade an existing weekly voucher already referenced by a paid order."""

import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from app.commerce_models import CardWallet, PaymentOrder, WeeklyCoupon
from app.database import Database
from app.models import UserRecord


def test_0007_preserves_existing_used_coupon_and_paid_order(tmp_path, monkeypatch):
    url = "sqlite+pysqlite:///" + (tmp_path / "gift-migration.sqlite3").as_posix()
    monkeypatch.setenv("BAZI_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261101_0006")
    db = Database(url)
    uid, cid, oid = str(uuid.uuid4()), str(uuid.uuid4()), uuid.uuid4().hex
    with db.session() as s:
        s.add(UserRecord(id=uid, status="active"))
        s.flush()
        s.add(CardWallet(user_id=uid, balance=1))
        s.execute(
            text(
                "INSERT INTO weekly_coupons "
                "(id,user_id,period_start,expires_at,redeemed_order_id) "
                "VALUES (:cid,:uid,'2026-10-26','2026-11-02',:oid)"
            ),
            {"cid": cid, "uid": uid, "oid": oid},
        )
        s.execute(
            text(
                "INSERT INTO payment_orders "
                "(id,user_id,idempotency_key,product_code,product_name,cards,"
                "original_amount,discount_amount,total_amount,coupon_id,app_id,mchid,"
                "payer_openid,status,provider_started,created_at,expires_at,paid_at) "
                "VALUES (:oid,:uid,:oid,'single','legacy',1,8800,5000,3800,:cid,"
                "'fixture','fixture','fixture','paid',0,'2026-10-31',"
                "'2026-10-31','2026-10-31')"
            ),
            {"cid": cid, "uid": uid, "oid": oid},
        )
        s.commit()
    command.upgrade(config, "20261101_0007")
    # Read current ORM models only after subsequent additive migrations too.
    with db.session() as s:
        assert s.execute(text("SELECT redeemed_order_id FROM weekly_coupons WHERE id=:id"), {"id": cid}).scalar_one() == oid
    command.upgrade(config, "head")
    with db.session() as s:
        c, o = s.get(WeeklyCoupon, cid), s.get(PaymentOrder, oid)
        assert c.source_refund_id is None and c.redeemed_order_id == oid
        assert o.coupon_id == cid and o.total_amount == 3800 and o.status == "paid"
        assert s.get(CardWallet, uid).balance == 1
        for _ in range(2):
            s.add(
                WeeklyCoupon(
                    user_id=uid,
                    source_refund_id=uuid.uuid4().hex,
                    period_start=None,
                    expires_at=c.expires_at,
                )
            )
        s.commit()
        assert len(list(s.scalars(select(WeeklyCoupon)))) == 3
        assert not s.execute(text("PRAGMA foreign_key_check")).all()
    db.dispose()
