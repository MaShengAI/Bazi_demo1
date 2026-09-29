# 微信 H5 集成边界

当前版本是标准 HTTPS H5，并已接入可开关的微信公众号网页授权登录；暂不接入支付或分享，也不会加载微信 JS-SDK。登录配置见 [微信公众号登录开发与上线](wechat-login.md)。

## 当前保证

- 前端只请求同源 `/api/v1` 与 `/health`，生产构建不包含 localhost。
- 页面仅在浏览器本地保存用于恢复进度的 `job_id`、`chart_id`；登录跳转前的出生表单仅临时保存在当前标签页的 sessionStorage，恢复提交后立即删除。
- DeepSeek 密钥只注入 `worker`，API 容器和 Web 容器都不持有该密钥。
- 微信 `AppSecret` 只注入 API 容器，worker、Web 容器和前端都不持有该密钥。
- 登录会话使用随机 HttpOnly、Secure、SameSite=Lax Cookie；数据库只保存令牌哈希，不保存明文会话令牌或网页授权 access_token。

## 后续接入 JS-SDK

需要分享能力时，新增同源后端接口 `POST /api/v1/wechat/js-sdk-signature`。后端根据当前页面 URL 生成临时签名；公众号 `AppSecret` 只能存放在后端秘密管理系统中。前端适配器只接收签名结果，不接触 `AppSecret`。

微信公众平台需要配置业务域名、JS接口安全域名和网页授权域名。签名必须使用去掉 URL hash 后的完整当前地址，且不能由前端自行计算。
