# 只读管理后台 v1

入口：`https://destiny.miaohe.club/admin`。独立账号密码，与客户微信登录无关。
范围为登录、搜索/分页报告列表、报告详情（出生资料、命盘、八个板块正文及内部指标）。
没有编辑、删除、重试、生成、退款或支付操作。不会自动补写历史报告。

## 权限与配置

- 默认关闭，缺少配置时后台不可用，客户功能保持原有行为。
- 单独的 MySQL 用户 `bazi_admin_reader`，只授予 `bazi.charts`、
  `bazi.analysis_jobs`、`bazi.analysis_sections` 三张表的 SELECT。
- 管理查询使用独立连接池，禁止非 SELECT 语句；MySQL 连接默认只读事务。
- 密码保存为随机盐 PBKDF2-HMAC-SHA256 哈希（600000 次），不保存明文。
- 随机会话令牌只在 HttpOnly、Secure、SameSite=Strict Cookie 中传输，Cookie
  路径限定 `/api/v1/admin`。服务端内存只保存令牌哈希，1 小时绝对过期，退出立即失效。
- 登录/退出要求精确匹配配置的 Origin。登录有每客户端及全局限速。
- 本版面向现有单 API 进程；API 重启后需要重新登录。未来扩容多个 API 进程前，
  应将会话及限速状态迁至共享存储。
- 所有管理 API 使用 `private, no-store`。不输出客户 OpenID、登录令牌、商户配置或密码。

私有配置位于 `/root/bazi-admin-secrets/admin.env`（目录 root:root 700、文件 600）。
不要放进 Git、前端构建或网站目录。字段：

```ini
BAZI_ADMIN_ENABLED='true'
BAZI_ADMIN_USERNAME='由你设置'
BAZI_ADMIN_PASSWORD_HASH='由设置脚本生成'
BAZI_ADMIN_DATABASE_URL='由设置脚本生成，仅查询账号'
BAZI_ADMIN_PUBLIC_ORIGIN='https://destiny.miaohe.club'
```

哈希含 `$`，env 文件的单引号必须保留，避免 Compose 插值。
只有 API 通过 `deploy/compose.admin.yaml` 接收这五个字段，worker 不接收。
生产 Cookie 强制 Secure；HTTP 仅允许隔离的本机 SQLite 测试。

## 部署顺序

使用本次交付包的 `setup_admin.py`，在服务器交互终端设置账号及隐藏输入的密码。
脚本创建单独的查询账号，不轮换现有应用/数据库密码；仅修改新账号的查询授权，
不修改报告、订单、余额或运行容器。重复执行复用原配置，不重设密码。
权限异常会停止，不会强制撤销别人的授权。

然后执行交付包 `install.py --apply`。更新前校验源文件、备份源码/旧镜像/前端，
只重建 API，三个 worker 保持运行。没有数据表迁移。支付保持关闭。
后台和客户页共用现有静态站点，`/admin` 由现有 SPA 回退处理；
`/api/v1/admin/*` 由现有 `/api/v1/` 反代处理，不需新增数据库公网端口或 Nginx 路由。

以后重新创建 API 容器时保留所有 env/Compose 文件：

```bash
cd /www/wwwroot/Bazi_demo1
docker compose --env-file deploy/.env.preprod --env-file /root/bazi-payment-secrets/payment.env --env-file /root/bazi-admin-secrets/admin.env -f deploy/compose.yaml -f deploy/compose.baota.yaml -f deploy/compose.payments.yaml -f deploy/compose.admin.yaml up -d --no-deps --no-build api
```

省略 admin 覆盖文件时默认禁用后台。通常的 `docker restart` 会保留容器已有配置。
忘记密码时在服务器重新设置密码哈希并重新创建 API，不能从数据库找回明文密码。

## 验收

未登录不能查询报告；客户微信登录不会获得管理权限。登录后搜索姓名/编号、按
状态/日期筛选、分页、查看详情、切换正文/命盘、退出后再刷新详情。日期筛选按北京
时间，出生时间保留输入的当地时间。报告正文以纯文本显示，不执行 HTML。
创建时间来自数据库默认时间，管理连接读取 MySQL 会话时区后统一转换；
worker 写入的完成时间按应用 UTC 转换，避免当前 MySQL `+08:00` 设置导致多加八小时。

前台免费排盘、微信登录及既有报告访问继续按原权限工作；管理后台只显示已持久化
的解读报告，不包含只点“开始排盘”而未保存的临时计算。
