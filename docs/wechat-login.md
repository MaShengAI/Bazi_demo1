# 微信公众号登录开发与上线

本项目使用服务号“网页授权”完成登录，不把 AppSecret 或微信 access_token 发送到浏览器。认证审核期间可以完成全部代码、数据库和界面开发；在公众号获得网页授权能力并配置域名之前，生产环境保持登录关闭。

## 当前实现

- `disabled`：默认模式，不显示登录入口，现有匿名排盘与 AI 分析保持原样。
- `mock`：仅用于隔离的本地或测试环境，自动模拟一个微信用户，不访问微信服务器。
- `live`：跳转微信网页授权，回调后创建或更新用户，并签发服务端会话。
- 默认使用 `snsapi_base`，只取得稳定的 openid，用户显示名为“微信用户”；若产品明确需要头像昵称，可改为 `snsapi_userinfo`，这会要求用户确认授权。
- 登录用户的报告归属于本人，其他用户访问时统一返回“不存在”，避免泄露报告是否存在。
- 历史匿名报告不自动绑定到任何微信账号，升级后仍可通过原有浏览器任务记录访问。

## 认证审核期间

公开服务器保留：

```env
BAZI_WECHAT_AUTH_MODE=disabled
BAZI_AUTH_REQUIRED_FOR_ANALYSIS=false
```

这样可以安全部署数据库表和前端代码，但不会出现一个尚不可用的登录按钮。开发机需要演示登录流程时使用：

```env
BAZI_WECHAT_AUTH_MODE=mock
BAZI_WECHAT_OAUTH_CALLBACK_URL=http://127.0.0.1:8000/api/v1/auth/wechat/callback
BAZI_SESSION_COOKIE_SECURE=false
BAZI_AUTH_REQUIRED_FOR_ANALYSIS=true
```

`mock` 不能用于公网生产环境。

## 审核通过后的公众平台配置

1. 在公众号后台取得 AppID 和 AppSecret，AppSecret 只保存到服务器的 `deploy/.env.preprod`。
2. 在网页授权设置中填写 H5 域名，只填域名，不带 `https://` 和路径。
3. 确认该域名的 HTTPS 证书有效，并且微信访问时不会跳到另一个域名。
4. 回调地址固定为 `https://你的域名/api/v1/auth/wechat/callback`。
5. 先用测试用户真机验收，再决定是否强制所有 AI 分析必须登录。

服务器配置示例：

```env
BAZI_WECHAT_AUTH_MODE=live
BAZI_WECHAT_APP_ID=真实AppID
BAZI_WECHAT_APP_SECRET=真实AppSecret
BAZI_WECHAT_OAUTH_CALLBACK_URL=https://你的域名/api/v1/auth/wechat/callback
BAZI_WECHAT_OAUTH_SCOPE=snsapi_base
BAZI_SESSION_COOKIE_SECURE=true
BAZI_AUTH_REQUIRED_FOR_ANALYSIS=false
BAZI_USER_ANALYSIS_LIMIT_PER_24H=0
```

建议分两次启用：第一阶段保持 `BAZI_AUTH_REQUIRED_FOR_ANALYSIS=false`，只验证登录、退出和历史报告；稳定后再改成 `true`。每天陆续约 100 份报告的场景可以先把单用户限制保持 `0`（不限制），观测一周后再决定是否设置，例如 `10`。

## 数据库与会话安全

迁移 `20260929_0004` 新增用户、微信身份、会话和 OAuth state 表，并给 `charts` 添加可空的 `user_id`。迁移只新增结构，不删除已有报告。

- OAuth state 一次性使用，10 分钟过期，数据库只保存 SHA-256 哈希。
- 会话 Cookie 为 HttpOnly、Secure、SameSite=Lax，默认 30 天；数据库只保存会话令牌哈希。
- 网页授权 access_token 只用于当次微信接口调用，不写入数据库。
- 回跳地址只允许本站相对路径，防止开放重定向。
- AppSecret 只进入 API 容器，不进入前端、Web 或 worker。

## 上线顺序

```sh
git pull --ff-only origin main
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml -f deploy/compose.baota.yaml stop worker
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml -f deploy/compose.baota.yaml build migrate
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml -f deploy/compose.baota.yaml run --rm migrate
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml -f deploy/compose.baota.yaml up -d --build --scale worker=3 api worker
```

先保持 `disabled` 部署并确认现有功能无回归；审核通过、后台域名配置生效后，修改环境变量为 `live` 并只重建 API：

```sh
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml -f deploy/compose.baota.yaml up -d --force-recreate api
```

## 真机验收

1. 微信内打开页面，未登录状态出现“微信登录”。
2. 点击后完成授权并返回原页面，不发生循环跳转。
3. 提交一份报告，在“我的报告”里可以打开。
4. 退出后该账号报告不能仅凭 job_id 打开；重新登录后可以恢复。
5. 用另一个微信账号登录，不能看到第一个账号的报告。
6. 检查 API、Web、worker 日志，不能出现 AppSecret、Cookie 或微信 access_token。
7. 最后再把 `BAZI_AUTH_REQUIRED_FOR_ANALYSIS` 改为 `true`，验证登录前填写的表单能在登录返回后自动提交一次。
