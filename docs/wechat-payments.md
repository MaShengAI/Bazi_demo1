# 微信内 JSAPI 支付与解读卡（默认关闭）

本次只改本地代码，不会自动修改服务器、接入商户或发起真实扣款。必须先做隔离测试，完成商户配置与验收后才能开放购买。网页 HTTPS 证书和微信支付商户 API 证书/密钥是两套东西，不能混用。

## 已实现的规则

| 商品 | 卡数 | 原价 | 使用当周券后 |
| --- | ---: | ---: | ---: |
| 单次八字精批卡 | 1 | 88 元 | 38 元 |
| 双人八字精批套餐 | 2 | 158 元 | 108 元 |
| 全家福八字精批卡 | 5 | 228 元 | 178 元 |

三档交付相同类型的完整八板块 AI 文化解读，只区别次数。卡归购买账户，可为不同出生资料使用，无使用期限。基础确定性排盘不扣卡。

- 新注册用户立即获得当周 50 元站内券；老用户每周一北京时间 08:00 自动获得新券，到下周一 08:00 失效。每周最多一张，适用于全部三档，每单限一张，不叠加、不提现。离线期间不会累积有效券；只补当周券。
- 发券进程每 30 秒检查周边界；有效期按边界精确计算，实际批量入账可能晚几十秒（大批量账户还取决于处理时间）。登录、查看账户、下单均有当周补发兜底。
- 下单锁定券，后台确认付款才核销；关单确认成功才释放未过期券。取消微信收银台不等于关闭订单。
- 订单默认可支付 15 分钟；用券订单不超过券到期时间。为避免微信将过短支付期限自动延长，券到期前最后两分钟不新建用券订单，最后一分钟不再次调起旧订单支付。
- 首次成功创建新报告任务才扣一张卡；创建失败事务回滚，不扣卡。相同参数、同一账户、同一规则/模型版本的已有任务会去重，不再扣卡。重看、失败/取消板块重试不扣卡。
- 取消任务暂不自动退卡，已有内容保留并可免费重试；删除报告后再生成是新任务，会再扣卡。卡扣减账本不会随报告删除而删除。
- 人工退款咨询渠道：QQ **836493209**。购买区（未登录也可见）及最近购买记录展示联系方式；购买记录展示订单号，便于用户申请。用户提供订单号及退款原因，人工核实处理；不得索要微信密码、支付密码或短信验证码。此入口仅提供联系方式，不会自动退款、退卡或改变券状态，也不代表申请必然获批；不设置排除法定权利的“一律不退”条款。

以上取消/删除规则是本版保守实现，不是已确定的对外退款条款。**现金退款、退款后的卡回收、争议退款和商户账单对账尚未实现；确定售后规则并补齐处理流程前，不应面向公众开放真实购买。** 不要只在商户后台退款而不核对本站剩余卡与账本，也不要手动修改钱包余额。

## 文件入口

- `app/payment_config.py`：默认 `disabled`，服务器以整数“分”配置价格。
- `app/services/payments.py`：订单、券占用、服务端验单、到账与查单补偿。
- `app/integrations/wechat_pay.py`：API v3 RSA 签名、公钥验签、AES-GCM 通知解密。
- `app/services/cards.py`：周边界、账户锁和报告扣卡。
- `app/coupon_scheduler.py`：周一批量发券，不接触商户或 AI 密钥。
- `migrations/versions/20261020_0005_card_payments.py`：四张新增表，不改变已有报告正文。
- 前端 `CardShop`：余额、券、三档套餐、订单确认、收银台、查单、关单及最近 20 条订单。

## 先在本地隔离数据库测试（不扣款）

不要把正式 MySQL 数据库改成模拟模式。新开本地 PowerShell，在项目根目录执行：

```powershell
$env:BAZI_DATABASE_URL = 'sqlite+pysqlite:///.codex-tmp/payments-local.sqlite3'
$env:BAZI_WECHAT_AUTH_MODE = 'mock'
$env:BAZI_WECHAT_OAUTH_CALLBACK_URL = 'http://127.0.0.1:5173/api/v1/auth/wechat/callback'
$env:BAZI_SESSION_COOKIE_SECURE = 'false'
$env:BAZI_PAY_MODE = 'mock'
New-Item -ItemType Directory -Force .codex-tmp
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端，在 `frontend` 目录执行 `pnpm dev`，访问 `http://127.0.0.1:5173`。测试结束关闭该 PowerShell，避免环境变量带入正式运行。

点击微信登录（本地自动模拟）后应有一张 50 元券。选择商品，核对订单，点击“模拟支付（不扣款）”；余额按 1/2/5 张增加。再次确认同一订单不重复增加；新报告扣一张；无卡时新报告返回 402，普通排盘仍可用。重新打开页面应恢复待支付订单。

模拟支付要求 mock 登录与本地域名，公共域名直接拒绝。它不是微信的沙箱，不会连接真实收银台，也不能替代手机真机验收。测试账户、测试卡和测试券不要迁入正式库。

## 正式接入前需要准备（不要在聊天里发送）

1. 与当前公众号 AppID 已关联的商户号，并确认开通 **JSAPI 支付**，真实商品/经营类目符合商户审核要求。这里不是“微信外浏览器 H5 支付”。
2. 在商户平台配置支付授权目录：本项目当前首页支付入口是 `https://destiny.miaohe.club/`。若以后换子路径，按官方规则重新核对目录。公众号网页授权域名也要继续有效。
3. **商户 API 证书序列号**、对应的 **商户私钥 `apiclient_key.pem`**。
4. **微信支付公钥 ID `PUB_KEY_ID_...`** 与对应公钥文件。本版使用公钥模式，不自动下载或切换平台证书。
5. 自己设置的 32 字节 API v3 密钥，用于解密支付成功通知。不是 AppSecret，也不是 SSL 私钥。
6. 回调地址 `https://destiny.miaohe.club/api/v1/payments/wechat/notify`。

把商户私钥、公钥放入服务器非网站目录 `/root/bazi-payment-secrets/`，分别命名 `apiclient_key.pem`、`wechatpay_public.pem`。准备阶段目录为 root:root / 700，三个文件（含下文的 payment.env）均为 root:root / 600。Compose 只将两个明确的密钥文件只读绑定到 API，不挂载整个目录、不把 payment.env 暴露成容器文件；不存在的文件会报错，不自动创建同名目录。AI worker、发券进程与迁移服务不接收商户密钥。

API 以 UID 10001 运行。真正挂载验收前需再次核对镜像运行 UID，并将**仅这两个密钥文件**的属主设为该 UID，保持 600；目录和 payment.env 继续 root:root / 700、600，不递归 chown 整个目录。单文件绑定后，容器从自己的 `/run/bazi-pay/` 读取，不需要遍历宿主机 `/root`。必须通过 API 运行用户的实际挂载读取检查，不能只以 root 下 OpenSSL 成功代替验收。准备检查脚本要求三个文件均为 root 所有，因此只适用于调整容器读取权限之前的阶段；之后不要为让准备脚本通过而反复改回属主。禁止把私钥放前端、public、dist、Git、网站目录或提交给聊天。

`deploy/.env.payments.example` 只有占位项；真实支付值单独保存在 `/root/bazi-payment-secrets/payment.env`，保留原有 `deploy/.env.preprod`。部署支付 override 时按顺序指定两个 `--env-file`，后者覆盖支付项；先确认当前 shell 没有同名 BAZI_PAY_* 环境变量覆盖它。**不要 source 文件，不要打印普通 `docker compose config`、`config --environment` 或容器完整 inspect，它们可能显示密钥。** 只验证配置语法时使用 `config --quiet`。容器私钥路径由 override 指定为 `/run/bazi-pay/apiclient_key.pem`。自定义运行时需设置 `BAZI_PAY_PRIVATE_KEY_PATH`、`BAZI_PAY_PUBLIC_KEY_PATH`。

当前 OAuth 保持 `snsapi_base` 即可获取同一 AppID 的付款 OpenID，不需要为了支付索取头像昵称。本站账户与支付者身份必须匹配。

## CDN / Nginx

- 腾讯 CDN 的 **整个 `/api` 路径必须不缓存**，尤其订单、登录、报告、账户、通知。关闭可能改变通知请求的鉴权、重定向跟随、正文改写等配置。应用也对 `/api/v1/` 返回 `private, no-store`；CDN 不得强制覆盖。
- API v3 回调是公网 HTTPS POST，不依赖浏览器登录 Cookie；原始正文和 `Wechatpay-*` 头必须完整透传。不要把公众号 JSIP 白名单误当支付回调 IP 白名单。
- 保留现有 Nginx `/api/v1/` 代理即可；开启支付前验证公网通知路由可到达（空 POST 返回签名错误是预期，不能为“测试成功”关闭验签）。静态资源仍可 CDN 缓存。
- 校准服务器 NTP；回调/应答验签仅接受配置的微信公钥 ID 与 5 分钟内的签名时间戳。留意公钥轮换，更新文件/ID 后重建 API。

## 迁移与部署顺序（先备份，不能跳过）

以下是后续部署时的参考，不表示已替你执行。先备份正式 MySQL，并保留源码补丁和旧构建。确认 `git apply --check` 成功后再应用对应补丁。

先保持 `BAZI_PAY_MODE=disabled`，在服务器项目目录执行新增表迁移：

```bash
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml -f deploy/compose.baota.yaml run --rm --build migrate
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml -f deploy/compose.baota.yaml up -d --no-deps --build api
```

前端在服务器 `frontend` 下执行 `pnpm install --frozen-lockfile && pnpm build`（或上传已验证 dist）。不开支付时新前端保持旧流程。

完成隔离测试、测试 MySQL 并发验证、售后/退款流程以及商户配置后，才把 `/root/bazi-payment-secrets/payment.env` 中 `BAZI_PAY_MODE` 改为 `live`、`BAZI_PAY_ACCEPT_NEW_ORDERS` 改为 `true`。确认公众号为 live 登录且 Secure Cookie 开启、两个单文件挂载的 UID 读取验收通过，再运行（这一步会开放真实收款，需人工确认；不可提前照抄执行）：

```bash
docker compose --env-file deploy/.env.preprod --env-file /root/bazi-payment-secrets/payment.env -f deploy/compose.yaml -f deploy/compose.baota.yaml -f deploy/compose.payments.yaml up -d --no-deps --build api coupons
```

真实验收需由你在手机微信内人工发起：核对实际应付金额、收款商户、支付账单、卡到账、重复通知不重复加卡、关单释放券、网络中断后查单、周边界和多账户权限。不要因前端 `ok` 就认定交易成功。所有上线前的真实测试订单必须纳入账务/退款核对，不要偷偷修改正式售价到 0.01 元绕过验收。

## 安全与运维边界

- 订单价格、优惠、付款者、卡数由后台锁定；前端传入金额等未知字段会被拒绝。每用户仅保留一个待支付订单；同请求键幂等。订单全部操作校验所属账户，浏览器支付操作校验来源。
- 原始通知先验签、再解密、再校验 AppID、商户号、订单号、CNY 金额和 OpenID。只有支付成功交易可原子核销券、加卡、写唯一账本事件。重复通知/查单不会重复到账。
- API 每约 60 秒扫描待支付订单补查并关过期单；单轮时间取决于待查数量和网络。前端移除手动“查单”按钮，收银台返回后仍自动向后台确认；用户也可稍后查看购买记录。不把原始支付数据或密钥写日志。
- 网络不确定、下单应答丢失、微信报告不存在但是否受理尚不确定时，保留订单和券占用，不擅自推定未付款。反复失败需核对商户后台与 API 日志中的错误类型后人工处理，不直接改余额/删订单。不能保证所有异常自动恢复。
- 仅支持人民币普通商户 JSAPI / 微信支付公钥模式。人工退款及卡回收已在本地实现、默认关闭，尚未正式部署验收，详见 [人工退款](manual-refunds.md)；服务商模式、自动投诉处理和每日账单对账仍未实现，不应声称完整商业支付已上线。
- 暂停新购时设置 `BAZI_PAY_ACCEPT_NEW_ORDERS=false` 并重建 API：保留通知、查单、已有订单支付和已购卡消费。**不要在已有付款处理中随意切回 disabled**：该模式会连通知和补查一起关闭，并恢复旧的免费 AI 入口。紧急回退要保留支付服务处理存量单；不要删四张金融表。
- 迁移刻意拒绝自动 downgrade，避免误删支付账本。恢复旧代码不是恢复旧数据库，已收款记录必须保留并核对。

## 本地验证命令

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check app tests migrations
.venv/Scripts/python.exe -m mypy app
cd frontend
pnpm typecheck
pnpm test
pnpm build
```

SQLite 单元测试不能替代 MySQL 并发验证。可在**专用、已迁移、库名以 `_test` 结尾**的 MySQL 库设置 `BAZI_TEST_MYSQL_URL` 执行集成测试；未配置会明确跳过。禁止指向正式库。

官方依据：[JSAPI 下单](https://pay.wechatpay.cn/doc/v3/merchant/4012791856)、[调起支付](https://pay.wechatpay.cn/doc/v3/merchant/4012791857)、[关单](https://pay.wechatpay.cn/doc/v3/merchant/4012791860)、[支付成功通知](https://pay.wechatpay.cn/doc/v3/merchant/4012791861)。前端成功回调不保证可靠，必须以后端查单与通知为准。
