# 微信 H5 预发布部署手册

本手册只针对预发布服务器，不会授权脚本连接或修改真实生产环境。目标拓扑为：公网 `443/80 -> Nginx -> React 或 FastAPI`，FastAPI 与2个 worker 通过内部 Docker 网络访问 MySQL；每个 worker 默认并发4个 section。MySQL 不映射宿主机端口。AI 队列使用 MySQL 的 section 租约与 `SKIP LOCKED`，项目当前不需要 Redis。

## 1. 域名、服务器与防火墙

1. 准备一台安装了 Docker Engine、Compose v2 和 Python 3.11+ 的 Linux 服务器，建议至少 2 核、4 GB 内存和独立数据盘。
2. 为预发布域名添加 A/AAAA 记录并指向服务器公网地址。若暂不稳定使用 IPv6，不要添加无法连通的 AAAA 记录。
3. 云安全组与主机防火墙只对公网开放 TCP 80、443 和受限来源的运维 SSH 端口。不要开放 3306、8000。
4. 启用公众号登录前，在微信公众平台配置网页授权域名；未来启用 JS-SDK 时再配置 JS 接口安全域名。详细步骤见 [微信公众号登录开发与上线](wechat-login.md)。

## 2. HTTPS

使用受信任 CA（例如 ACME 客户端签发）的完整链证书。配置目录中必须有：

- `fullchain.pem`：站点证书和中间证书；
- `privkey.pem`：私钥，仅服务器管理员可读。

默认示例使用 `deploy/certs`，真实 PEM 已被 Git 忽略。先签发证书，再启动 Nginx；续期后执行：

```sh
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml exec web nginx -t
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml restart web
```

Nginx 强制 HTTP 308 跳转 HTTPS，启用 TLS 1.2/1.3、HSTS、CSP、拒绝 iframe、MIME 嗅探保护、权限策略和来源策略。请求体上限 1 MB；客户端请求体 20 秒、上游连接 5 秒、发送 30 秒、读取 300 秒。若将来确实增加上传，先按接口单独放宽，不要全站放宽。

## 3. 环境变量与密钥边界

```sh
cp deploy/.env.preprod.example deploy/.env.preprod
chmod 600 deploy/.env.preprod
```

填写真实域名、证书目录、两个不同的 MySQL 随机密码和 DeepSeek 密钥。MySQL 密码必须为至少 20 位 URL-safe 字符。启用微信登录时还需填写 AppID、AppSecret 和 HTTPS 回调地址。不要把密钥写入 `VITE_*`、源码、Compose build args 或公开配置。

Compose 的 `BAZI_LLM_API_KEY` 只在 `worker.environment` 中出现，`BAZI_WECHAT_APP_SECRET` 只在 `api.environment` 中出现；Web 和前端构建阶段都不持有这些密钥。应用日志不记录请求体、提示词、Authorization、Cookie 或环境变量，并会对常见密钥、Bearer 值和数据库 URL 密码二次脱敏。

## 4. 首次启动

在源码目录构建前端并执行一键检查：

```sh
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm build
cd ..
python3 deploy/preflight.py --env-file deploy/.env.preprod
```

检查覆盖必需变量、占位符、密码强度、证书有效期、80/443 可绑定、Compose 配置，以及前端产物中的 `localhost`、后端变量名和真实密钥。随后启动：

```sh
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml ps
python3 deploy/preflight.py --env-file deploy/.env.preprod --skip-ports --live
```

启动顺序由健康条件保证：MySQL 健康后，`migrate` 执行 Alembic upgrade；迁移成功后 API 与 worker 启动；API 健康后 Nginx 启动。API、worker、MySQL、Nginx 都有容器健康检查并采用 `unless-stopped` 自动重启（一次性 migrate 除外）。

健康端点：

- `/health/live`：只判断 API 进程与本地排盘服务可运行，数据库故障时仍为 200；
- `/health/ready`：同时探测数据库，数据库故障时为 503；
- worker：容器内检查数据库和持续更新的心跳文件；
- MySQL：容器内 `mysqladmin ping`。

## 5. 数据库迁移、备份与恢复

查看当前迁移版本：

```sh
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml run --rm migrate python -m alembic current
```

每次升级前执行一致性备份：

```sh
ENV_FILE=deploy/.env.preprod sh deploy/backup.sh
```

脚本使用 `--single-transaction` 生成 `deploy/backups/bazi-时间.sql.gz` 并执行 gzip 完整性校验。备份目录需另行同步到加密的异机存储，并定期在隔离环境演练恢复。

恢复会写入数据库，必须停 API/worker、明确指定备份并给出确认口令：

```sh
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml stop api worker
CONFIRM_RESTORE=RESTORE_BAZI ENV_FILE=deploy/.env.preprod sh deploy/restore.sh deploy/backups/bazi-时间.sql.gz
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml up -d api worker
```

Compose 没有 `down -v`、自动 downgrade 或清表步骤。不要在部署/回滚中执行 `docker compose down -v`。Alembic downgrade 可能删除表，只能在已验证备份的维护窗口人工评审后执行。

## 6. 升级与回滚

升级：

```sh
ENV_FILE=deploy/.env.preprod sh deploy/backup.sh
git fetch --tags
git checkout <已审核版本>
python3 deploy/preflight.py --env-file deploy/.env.preprod --skip-ports
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml up -d --build
python3 deploy/preflight.py --env-file deploy/.env.preprod --skip-ports --live
```

回滚优先只回滚应用镜像/代码到上一已知可用版本，再重新 `up -d --build`。数据库采用只向前兼容迁移；不要自动 downgrade。若新版本已经写入不兼容数据，则进入维护窗口，先保留故障现场备份，再按明确确认流程恢复升级前备份。

前端资源文件带哈希并长期缓存，`index.html` 与 `version.json` 禁用缓存；版本检测会提示微信用户刷新，因此升级后无需清 CDN。若接入 CDN，必须保持这两类文件不缓存，并让 `/api/v1` 绕过静态缓存。

## 7. 日志与故障排查

FastAPI 与 worker 输出单行 JSON。API 日志包含 `request_id`、方法、路径、状态码和耗时；提交 AI 任务时同一 `request_id` 日志包含 `job_id`/`chart_id`；worker 的领取、板块尝试和完成日志均包含 `job_id`。Nginx 同样生成 request ID 并通过响应头返回。容器日志按 10 MB × 5 文件轮转。

常用只读检查：

```sh
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml ps
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml logs --tail=200 api worker web mysql migrate
curl -fsS https://你的域名/health/live
curl -fsS https://你的域名/health/ready
```

- 页面打不开：检查 DNS、80/443 防火墙、证书链与 `web` 日志。
- 页面正常但 API 502：检查 `api` 健康与 Nginx 上游日志。
- 普通排盘正常但 AI 提交 503：查看 `/health/ready`、MySQL 和迁移日志。
- AI 一直 pending：检查 worker 健康、DeepSeek 网络/余额/配额，并按 `job_id` 检索日志。
- MySQL 不可用：不要重启/清空数据卷；先确认磁盘空间、权限和错误日志。`POST /api/v1/charts` 应继续正常。
- 微信仍显示旧页面：确认 `index.html`/`version.json` 无缓存、静态文件名已变更，并按真机清单验证刷新提示。

完成自动检查后，继续执行 [微信真机验收清单](wechat-preproduction-checklist.md)。

