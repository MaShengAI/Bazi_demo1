# 微信 H5 集成边界

当前版本是标准 HTTPS H5，不接入微信登录、支付或分享，也不会加载微信 JS-SDK。

## 当前保证

- 前端只请求同源 `/api/v1` 与 `/health`，生产构建不包含 localhost。
- 页面仅在浏览器本地保存 `job_id`、`chart_id`；不保存出生表单、数据库密码或模型密钥。
- DeepSeek 密钥只注入 `worker`，API 容器和 Web 容器都不持有该密钥。
- `frontend/src/wechat.ts` 是后续微信能力的唯一前端适配边界。

## 后续接入 JS-SDK

需要分享能力时，新增同源后端接口 `POST /api/v1/wechat/js-sdk-signature`。后端根据当前页面 URL 生成临时签名；公众号 `AppSecret` 只能存放在后端秘密管理系统中。前端适配器只接收签名结果，不接触 `AppSecret`。

微信公众平台需要配置业务域名、JS接口安全域名和网页授权域名。签名必须使用去掉 URL hash 后的完整当前地址，且不能由前端自行计算。
