from __future__ import annotations

import argparse
import http.client
import os
import re
import socket
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

PLACEHOLDER = re.compile(r"(?:replace|example|changeme|替换)", re.I)
DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)
TEXT_ARTIFACTS = {".html", ".js", ".css", ".json", ".map", ".txt"}
REQUIRED = (
    "H5_DOMAIN",
    "TLS_CERT_DIR",
    "MYSQL_DATABASE",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_ROOT_PASSWORD",
    "BAZI_LLM_API_KEY",
)


class Checks:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def ok(self, message: str) -> None:
        print(f"[OK] {message}")

    def fail(self, message: str) -> None:
        self.failures.append(message)
        print(f"[FAIL] {message}")

    def require(self, condition: bool, success: str, failure: str) -> None:
        self.ok(success) if condition else self.fail(failure)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number} is not KEY=VALUE")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return {**values, **{key: value for key, value in os.environ.items() if value}}


def check_environment(checks: Checks, values: dict[str, str]) -> None:
    missing = [key for key in REQUIRED if not values.get(key)]
    checks.require(not missing, "必需环境变量已填写", f"缺少环境变量: {', '.join(missing)}")
    domain = values.get("H5_DOMAIN", "")
    checks.require(
        bool(DOMAIN.fullmatch(domain)) and "localhost" not in domain.lower(),
        "H5_DOMAIN 是有效公网域名",
        "H5_DOMAIN 必须是无协议、无路径的公网域名",
    )
    for key in ("MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD"):
        value = values.get(key, "")
        checks.require(
            len(value) >= 20
            and quote(value, safe="-._~") == value
            and not PLACEHOLDER.search(value),
            f"{key} 长度和 URL 安全性通过",
            f"{key} 应为至少20位、非占位符的 URL-safe 随机值",
        )
    api_key = values.get("BAZI_LLM_API_KEY", "")
    checks.require(
        len(api_key) >= 16 and api_key.isascii() and not PLACEHOLDER.search(api_key),
        "DeepSeek 密钥格式通过（未输出密钥）",
        "BAZI_LLM_API_KEY 仍是占位符、过短或包含非 ASCII 字符",
    )


def check_certificates(checks: Checks, env_file: Path, values: dict[str, str]) -> None:
    raw_path = Path(values.get("TLS_CERT_DIR", ""))
    cert_dir = raw_path if raw_path.is_absolute() else (env_file.parent / raw_path).resolve()
    cert = cert_dir / "fullchain.pem"
    key = cert_dir / "privkey.pem"
    checks.require(cert.is_file() and key.is_file(), "HTTPS 证书文件存在", f"缺少 {cert} 或 {key}")
    if not cert.is_file():
        return
    try:
        decoded = ssl._ssl._test_decode_cert(str(cert))  # type: ignore[attr-defined]
        not_after = datetime.strptime(decoded["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=UTC
        )
        checks.require(not_after > datetime.now(UTC), "HTTPS 证书未过期", "HTTPS 证书已过期")
    except (OSError, KeyError, ValueError, ssl.SSLError) as exc:
        checks.fail(f"无法解析 HTTPS 证书: {exc}")


def check_ports(checks: Checks) -> None:
    for port in (80, 443):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError as exc:
            checks.fail(f"端口 {port} 不可用: {exc}")
        else:
            checks.ok(f"端口 {port} 可绑定")
        finally:
            sock.close()


def check_frontend(checks: Checks, dist: Path, values: dict[str, str]) -> None:
    if not dist.is_dir():
        checks.fail(f"前端产物不存在: {dist}（先运行 pnpm build）")
        return
    needles = {
        "localhost": re.compile(r"(?:localhost|127\.0\.0\.1)", re.I),
        "后端敏感变量名": re.compile(r"BAZI_(?:LLM_API_KEY|DATABASE_URL)", re.I),
    }
    secret = values.get("BAZI_LLM_API_KEY", "")
    hits: list[str] = []
    for path in dist.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_ARTIFACTS:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in needles.items():
            if pattern.search(content):
                hits.append(f"{path.relative_to(dist)}:{label}")
        if secret and secret in content:
            hits.append(f"{path.relative_to(dist)}:真实 DeepSeek 密钥")
    checks.require(
        not hits, "前端产物无密钥、后端变量名或 localhost", f"前端产物命中: {', '.join(hits)}"
    )


def check_compose(checks: Checks, root: Path, env_file: Path, values: dict[str, str]) -> None:
    environment = {**os.environ, **values}
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(env_file),
                "-f",
                str(root / "deploy" / "compose.yaml"),
                "config",
                "--quiet",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        checks.fail(f"无法运行 Docker Compose 配置检查: {exc}")
        return
    checks.require(
        result.returncode == 0,
        "Docker Compose 配置有效",
        "Docker Compose 配置无效（为避免泄密，错误输出未打印）",
    )


def check_live(checks: Checks, domain: str) -> None:
    try:
        socket.getaddrinfo(domain, 443)
        checks.ok("域名 DNS 可解析")
    except socket.gaierror as exc:
        checks.fail(f"域名 DNS 解析失败: {exc}")
        return

    try:
        connection = http.client.HTTPConnection(domain, 80, timeout=5)
        connection.request("GET", "/health/live")
        response = connection.getresponse()
        location = response.getheader("Location", "")
        checks.require(
            response.status in {301, 302, 307, 308} and location.startswith("https://"),
            "HTTP 自动跳转 HTTPS",
            f"HTTP 跳转异常: {response.status}",
        )
    except OSError as exc:
        checks.fail(f"HTTP 跳转检查失败: {exc}")

    context = ssl.create_default_context()
    for path, label in (
        ("/health/live", "HTTPS/API 健康检查"),
        ("/api/v1/locations/provinces", "同域 API 连通性"),
    ):
        try:
            request = urllib.request.Request(
                f"https://{domain}{path}", headers={"User-Agent": "bazi-preflight/1.0"}
            )
            with urllib.request.urlopen(request, timeout=10, context=context) as response:
                checks.require(
                    response.status == 200, f"{label}通过", f"{label}返回 HTTP {response.status}"
                )
        except (urllib.error.URLError, OSError) as exc:
            checks.fail(f"{label}失败: {exc}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="八字 H5 预发布一键检查")
    parser.add_argument("--env-file", type=Path, default=root / "deploy" / ".env.preprod")
    parser.add_argument("--dist", type=Path, default=root / "frontend" / "dist")
    parser.add_argument("--live", action="store_true", help="部署后额外检查 DNS、HTTPS 跳转和 API")
    parser.add_argument(
        "--skip-ports", action="store_true", help="升级已运行环境时跳过80/443占用检查"
    )
    parser.add_argument("--skip-compose", action="store_true")
    args = parser.parse_args()
    env_file = args.env_file.resolve()
    if not env_file.is_file():
        raise SystemExit(f"环境文件不存在: {env_file}")
    checks = Checks()
    try:
        values = load_env(env_file)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    check_environment(checks, values)
    check_certificates(checks, env_file, values)
    if not args.skip_ports:
        check_ports(checks)
    check_frontend(checks, args.dist.resolve(), values)
    if not args.skip_compose:
        check_compose(checks, root, env_file, values)
    if args.live:
        check_live(checks, values.get("H5_DOMAIN", ""))
    if checks.failures:
        print(f"\n预发布检查失败：{len(checks.failures)} 项")
        raise SystemExit(1)
    print("\n预发布检查全部通过")


if __name__ == "__main__":
    main()
