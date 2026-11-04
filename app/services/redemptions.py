"""Atomic one-code/one-grant operations. No merchant or model API calls."""

from __future__ import annotations

import calendar
import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.commerce_models import (
    CardLedger,
    CardWallet,
    RedemptionAttempt,
    RedemptionBatch,
    RedemptionCode,
    WeeklyCoupon,
)
from app.database import Database
from app.services.cards import PaymentError, lock_user, now_utc
from app.services.payments import iso

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def month_later(now: datetime) -> datetime:
    local = now.replace(tzinfo=UTC).astimezone(ZoneInfo("Asia/Shanghai"))
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    end = local.replace(
        year=year, month=month, day=min(local.day, calendar.monthrange(year, month)[1])
    )
    return end.astimezone(UTC).replace(tzinfo=None)


def code_digest(code: str) -> str:
    normalized = re.sub(r"[\s-]", "", code).upper()
    if not re.fullmatch(r"[A-HJ-NP-Z2-9]{20}", normalized):
        raise PaymentError(400, "code_unavailable", "兑换码无效、已使用、已过期或已停用")
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def batch_json(batch: RedemptionBatch) -> dict:
    return {
        "id": batch.id,
        "label": batch.label,
        "kind": batch.kind,
        "value": batch.value,
        "quantity": batch.quantity,
        "operator": batch.operator,
        "created_at": iso(batch.created_at),
        "expires_at": iso(batch.expires_at),
    }


def receipt(code: RedemptionCode, batch: RedemptionBatch, repeated: bool) -> dict:
    redeemed_at = code.redeemed_at
    if redeemed_at is None:
        raise PaymentError(409, "code_unavailable", "兑换尚未完成，请刷新后核对")
    return {
        "kind": batch.kind,
        "value": batch.value,
        "already_redeemed": repeated,
        "redeemed_at": iso(redeemed_at),
        "coupon_expires_at": iso(redeemed_at + timedelta(days=7))
        if batch.kind == "coupon"
        else None,
    }


class RedemptionService:
    def __init__(self, database: Database):
        self.database = database

    def generate(
        self, *, kind: str, value: int, quantity: int, label: str, request_key: str, operator: str
    ) -> dict:
        # Validate here too: CLI/internal callers must not bypass the HTTP schema.
        maximum = 100 if kind == "cards" else 100000
        if (
            kind not in {"cards", "coupon"}
            or type(value) is not int
            or not 1 <= value <= maximum
            or type(quantity) is not int
            or not 1 <= quantity <= 1000
            or not 1 <= len(label.strip()) <= 80
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", request_key)
        ):
            raise PaymentError(422, "invalid_reward", "请检查奖励数值和生成数量")
        now = now_utc()
        with self.database.session() as session:
            prior = session.scalar(
                select(RedemptionBatch).where(RedemptionBatch.request_key == request_key)
            )
            if prior:
                raise PaymentError(
                    409,
                    "batch_already_created",
                    "该批次已生成，请在列表核对；请勿重复生成。明码仅首次生成时提供。",
                )
            batch = RedemptionBatch(
                id=uuid.uuid4().hex,
                request_key=request_key,
                label=label.strip(),
                kind=kind,
                value=value,
                quantity=quantity,
                operator=operator,
                created_at=now,
                expires_at=month_later(now),
            )
            session.add(batch)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                raise PaymentError(
                    409, "batch_conflict", "批次已生成或发生冲突，请先刷新列表核对"
                ) from None
            codes = []
            for _ in range(quantity):
                raw = "".join(secrets.choice(ALPHABET) for _ in range(20))
                code = RedemptionCode(
                    id=uuid.uuid4().hex,
                    batch_id=batch.id,
                    code_hash=code_digest(raw),
                    suffix=raw[-4:],
                )
                session.add(code)
                codes.append("-".join(raw[i : i + 5] for i in range(0, 20, 5)))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                raise PaymentError(
                    409, "batch_conflict", "批次生成发生冲突，请先刷新列表核对"
                ) from None
            return {"batch": batch_json(batch), "codes": codes}

    def redeem(self, user_id: str, raw: str) -> dict:
        now = now_utc()
        # Persist a bounded attempt count even for invalid codes; survives API restarts.
        with self.database.session() as session:
            lock_user(session, user_id)
            count = session.scalar(
                select(func.count())
                .select_from(RedemptionAttempt)
                .where(
                    RedemptionAttempt.user_id == user_id,
                    RedemptionAttempt.created_at > now - timedelta(minutes=1),
                )
            )
            hourly = session.scalar(
                select(func.count())
                .select_from(RedemptionAttempt)
                .where(
                    RedemptionAttempt.user_id == user_id,
                    RedemptionAttempt.created_at > now - timedelta(hours=1),
                )
            )
            if (count or 0) >= 5 or (hourly or 0) >= 30:
                raise PaymentError(429, "redemption_rate_limited", "兑换操作过于频繁，请稍后再试")
            session.add(RedemptionAttempt(id=uuid.uuid4().hex, user_id=user_id, created_at=now))
            session.commit()
        digest = code_digest(raw)
        with self.database.session() as session:
            # Same lock order as checkout/report debit/refund: user, then reward rows.
            lock_user(session, user_id)
            code = session.scalar(
                select(RedemptionCode).where(RedemptionCode.code_hash == digest).with_for_update()
            )
            if code is None:
                raise PaymentError(400, "code_unavailable", "兑换码无效、已使用、已过期或已停用")
            batch = session.get(RedemptionBatch, code.batch_id)
            if batch is None:
                raise PaymentError(400, "code_unavailable", "兑换码无效、已使用、已过期或已停用")
            if code.redeemed_by == user_id:
                return receipt(code, batch, True)
            if code.deleted_at or code.redeemed_by or code.disabled_at or now >= batch.expires_at:
                raise PaymentError(400, "code_unavailable", "兑换码无效、已使用、已过期或已停用")
            # CAS also protects SQLite tests and a concurrent admin disable operation.
            changed = session.execute(
                update(RedemptionCode)
                .where(
                    RedemptionCode.id == code.id,
                    RedemptionCode.deleted_at.is_(None),
                    RedemptionCode.redeemed_by.is_(None),
                    RedemptionCode.disabled_at.is_(None),
                )
                .values(redeemed_by=user_id, redeemed_at=now)
            ).rowcount
            if changed != 1:
                raise PaymentError(409, "code_unavailable", "兑换码已使用或已停用，请刷新后核对")
            if batch.kind == "cards":
                wallet = session.get(
                    CardWallet, user_id, with_for_update=True, populate_existing=True
                )
                if wallet is None:
                    session.add(CardWallet(user_id=user_id, balance=batch.value))
                else:
                    wallet.balance += batch.value
                session.add(
                    CardLedger(
                        user_id=user_id,
                        event_key=f"redemption:{code.id}",
                        delta=batch.value,
                        created_at=now,
                    )
                )
            else:
                session.add(
                    WeeklyCoupon(
                        user_id=user_id,
                        period_start=None,
                        source_code_id=code.id,
                        amount=batch.value,
                        expires_at=now + timedelta(days=7),
                    )
                )
            session.commit()
            # Return persisted timestamp precision, including MySQL DATETIME(0),
            # so the initial receipt and concurrent retries have the same expiry.
            session.refresh(code)
            return receipt(code, batch, False)

    def listing(self, *, batch_id: str = "", status: str = "", page: int = 1) -> dict:
        now = now_utc()
        with self.database.session() as session:
            query = (
                select(RedemptionCode, RedemptionBatch)
                .join(RedemptionBatch)
                .where(RedemptionCode.deleted_at.is_(None))
            )
            if batch_id:
                query = query.where(RedemptionCode.batch_id == batch_id)
            if status == "redeemed":
                query = query.where(RedemptionCode.redeemed_by.is_not(None))
            elif status == "disabled":
                query = query.where(RedemptionCode.disabled_at.is_not(None))
            elif status in {"unused", "expired"}:
                query = query.where(
                    RedemptionCode.redeemed_by.is_(None),
                    RedemptionCode.disabled_at.is_(None),
                    RedemptionBatch.expires_at > now
                    if status == "unused"
                    else RedemptionBatch.expires_at <= now,
                )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.execute(
                query.order_by(RedemptionBatch.created_at.desc(), RedemptionCode.id)
                .offset((page - 1) * 50)
                .limit(50)
            )
            items = []
            for code, batch in rows:
                state = (
                    "redeemed"
                    if code.redeemed_by
                    else "disabled"
                    if code.disabled_at
                    else "expired"
                    if now >= batch.expires_at
                    else "unused"
                )
                items.append(
                    {
                        "id": code.id,
                        "masked_code": "••••-" + code.suffix,
                        "batch": batch_json(batch),
                        "status": state,
                        "redeemed_by": code.redeemed_by,
                        "redeemed_at": iso(code.redeemed_at) if code.redeemed_at else None,
                        "disabled_by": code.disabled_by,
                        "disabled_at": iso(code.disabled_at) if code.disabled_at else None,
                    }
                )
            batches = session.scalars(
                select(RedemptionBatch).order_by(RedemptionBatch.created_at.desc()).limit(200)
            )
            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": 50,
                "batches": [batch_json(b) for b in batches],
            }

    @staticmethod
    def code_ids(values: list[str]) -> list[str]:
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= 1000
            or any(
                not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value)
                for value in values
            )
        ):
            raise PaymentError(422, "invalid_codes", "请选择1～1000个有效兑换码")
        return sorted(set(values))

    def disable(self, code_id: str, operator: str) -> None:
        self.bulk_disable([code_id], operator)

    def bulk_disable(self, code_ids: list[str], operator: str) -> dict:
        ids = self.code_ids(code_ids)
        with self.database.session() as session:
            # Stable row-lock order across bulk requests and redemption transactions.
            rows = session.scalars(
                select(RedemptionCode)
                .where(RedemptionCode.id.in_(ids))
                .order_by(RedemptionCode.id)
                .with_for_update()
            ).all()
            if len(rows) != len(ids) or any(code.deleted_at for code in rows):
                raise PaymentError(404, "code_not_found", "兑换码不存在或已删除，请刷新列表")
            now = now_utc()
            for code in rows:
                if code.disabled_at:
                    continue
                batch = session.get(RedemptionBatch, code.batch_id)
                if batch is None or code.redeemed_by or now >= batch.expires_at:
                    raise PaymentError(
                        409,
                        "code_not_unused",
                        "只能停用尚未兑换且未过期的兑换码；状态已变化时请刷新列表",
                    )
            changed = 0
            for code in rows:
                if code.disabled_at is None:
                    code.disabled_at, code.disabled_by = now, operator
                    changed += 1
            session.commit()
            return {"selected": len(ids), "changed": changed}

    def bulk_delete(self, code_ids: list[str], operator: str) -> dict:
        ids = self.code_ids(code_ids)
        with self.database.session() as session:
            rows = session.scalars(
                select(RedemptionCode)
                .where(RedemptionCode.id.in_(ids))
                .order_by(RedemptionCode.id)
                .with_for_update()
            ).all()
            if len(rows) != len(ids):
                raise PaymentError(404, "code_not_found", "兑换码不存在，请刷新列表")
            if any(code.disabled_at is None and code.redeemed_by is None for code in rows):
                raise PaymentError(
                    409, "code_not_terminal", "只能删除已停用或已兑换的兑换码；本次未删除任何记录"
                )
            now = now_utc()
            changed = 0
            for code in rows:
                if code.deleted_at is None:
                    code.deleted_at, code.deleted_by = now, operator
                    changed += 1
            session.commit()
            return {"selected": len(ids), "changed": changed}
