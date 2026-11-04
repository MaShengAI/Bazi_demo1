"""Root-only operator commands. No public refund creation endpoint or admin UI writes."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from app.config import AuthSettings
from app.database import Database
from app.integrations.wechat_pay import WechatPayClient
from app.payment_config import PaymentSettings
from app.services.cards import PaymentError
from app.services.refunds import RefundService, amount_cents


def private_plan(path: Path) -> dict:
    info = path.stat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size > 16384
    ):
        raise ValueError("预览文件须为 root 所有、权限600的普通文件")
    return json.loads(path.read_bytes())


def save_plan(path: Path, data: dict) -> None:
    # Plans contain an order reference and operator reason; keep outside the website.
    if not path.is_absolute() or not path.resolve().is_relative_to(Path("/root")):
        raise ValueError("预览文件须保存到 /root 下")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        if sys.platform == "linux":
            os.fchmod(stream.fileno(), 0o600)
        else:
            raise ValueError("退款预览文件仅支持在 Linux 服务器上保存")
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    preview = commands.add_parser("preview", help="只读核对，保存有效期10分钟的预览")
    preview.add_argument("--order", required=True)
    preview.add_argument("--amount", required=True, help="退款人民币金额，例如38.00")
    preview.add_argument(
        "--cards", default=0, choices=[0], type=int, help="退款不回收解读卡，固定为0"
    )
    preview.add_argument("--reason", required=True, help="不超过80字节，会发给微信")
    preview.add_argument("--operator", required=True)
    preview.add_argument("--output", required=True, type=Path)
    submit = commands.add_parser("submit", help="真实原路退款；不回收卡；成功后赠50元七天券")
    submit.add_argument("--plan", required=True, type=Path)
    submit.add_argument("--confirm", required=True)
    for action in ("status", "sync", "retry"):
        command = commands.add_parser(action)
        command.add_argument("--refund", required=True)
        if action == "retry":
            command.add_argument("--confirm", required=True, help="RETRY:原退款单号")
    args = parser.parse_args(argv)
    database = None
    try:
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("仅限服务器 root 执行；只读管理后台没有此操作权限")
        settings, auth = PaymentSettings.from_env(), AuthSettings.from_env()
        database = Database.from_env()
        if database is None:
            raise ValueError("未配置数据库")
        if settings.mode == "mock" and not (database.engine.url.database or "").endswith("_test"):
            raise ValueError("模拟退款只允许专用测试数据库")
        client = WechatPayClient(settings, auth.app_id) if settings.mode == "live" else None
        service = RefundService(database, settings, auth, client)
        service.require_enabled()
        if args.action == "preview":
            result = service.preview(
                args.order, amount_cents(args.amount), args.cards, args.reason, args.operator
            )
            save_plan(args.output, result)
            print("PREVIEW_ONLY: 未发起退款或赠券；金额单位为分；不回收卡；成功后赠50元七天券。")
        elif args.action == "submit":
            result = service.submit(private_plan(args.plan), args.confirm)
        elif args.action == "status":
            result = service.status(args.refund)
        elif args.action == "sync":
            result = service.sync(args.refund)
        else:
            result = service.retry(args.refund, args.confirm)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action not in {"preview", "status"}:
            print("仅 success 表示已确认退款并发放赠券；其他状态不赠券；本次不回收解读卡。")
        return 0
    except PaymentError as exc:
        print("REFUND_STOPPED:", exc.code, str(exc))
        print("保留原退款单号及预览；不要换号重试或直接修改余额。")
        return 1
    except Exception as exc:
        print("REFUND_STOPPED:", type(exc).__name__, "私有输出已隐藏，请核对后处理。")
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
