# 确定性八字排盘 API

一个以 FastAPI 提供服务、以版本化规则表计算结果的八字排盘后端。核心排盘不依赖大模型或在线排盘服务；可选的详细分析接口会在排盘完成后，把经过字段裁剪的结构化结果发送给服务端配置的 OpenAI 兼容模型。

## 已实现规则

- 年柱：立春分钟边界换年。
- 月柱：十二个“节”换月，中气不换月。
- 日柱：真太阳时 23:00 子初换日，`lunar-python` 适配层固定使用 sect 1。
- 时柱：真太阳时，子时为 23:00—00:59，五鼠遁定时干。
- 时区：`zoneinfo` + `tzdata`，解析历史 UTC offset 和 DST；重复或不存在的当地时间返回结构化 422。
- 真太阳时：标准时间 + 经度修正 + NOAA fractional-year 均时差。
- 十神、藏干、纳音、十二长生、旬空：本地不可变规则表。
- 神煞：版本化的 55 条规则目录，每条命中附规则 ID 和证据，见 `docs/shensha-rules.md`。
- 大运：年干阴阳与男女定顺逆，只取前/后一个“节”，按整数秒执行三天一岁换算。
- 流年：以立春至下一立春为一个干支年。
- AI详细分析：八个独立板块，每部分目标约1500字；支持 DeepSeek 等 OpenAI 兼容接口。

## 安装与启动

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload
```

接口文档：

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- 静态规范：`openapi.json`

## 微信 H5 前端 MVP

前端位于 `frontend/`，使用 React、TypeScript 和 Vite，针对微信内置浏览器、iOS Safari 和 Android WebView 适配。开发时由 Vite 将 `/api` 请求转发给本机 FastAPI，因此不需要放宽后端跨域策略。

先在一个 PowerShell 窗口启动后端：

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
```

再开一个 PowerShell 窗口启动前端：

```powershell
cd frontend
pnpm install
pnpm dev
```

浏览器访问 `http://127.0.0.1:5173`。普通排盘只需要 FastAPI 进程；即使没有 MySQL、worker 或模型密钥，`POST /api/v1/charts` 仍可正常工作。AI 分析还需按照下方“AI详细分析”章节启动数据库与独立 worker。

前端验证命令：

```powershell
cd frontend
pnpm test
pnpm typecheck
pnpm build
pnpm exec playwright install chromium
pnpm test:e2e
```

页面只在浏览器本地保存用于恢复进度的 `job_id` 和 `chart_id`，不会保存出生表单、模型密钥或数据库密码。`BAZI_LLM_API_KEY` 只能设置在后端 worker 的环境中，切勿写入任何 `VITE_*` 环境变量或前端代码。

H5 已实现中文分钟级时间选择器、刘海屏与底部安全区、软键盘和横竖屏适配、自定义确认弹窗、后台暂停和前台恢复轮询、弱网指数退避、离线提示、隐私确认，以及微信缓存旧版本时的刷新提醒。端到端测试覆盖 390×844 微信 iPhone、393×851 微信 Android 和 320×568 小屏环境。

微信 JS-SDK 当前未接入，未来签名接口与密钥边界见 `docs/wechat-h5.md`。

## 微信 H5 预发布部署

预发布栈包含 React 静态站点、Nginx、FastAPI、AI worker 与 MySQL 8.4。任务队列使用已有的 MySQL 租约表，不依赖 Redis，因此 Compose 没有加入无实际用途的 Redis。页面与 API 共用一个 HTTPS 域名，Nginx 只把 `/api/v1/` 和 `/health` 转发给 FastAPI；生产构建只使用相对路径。

服务器首次部署的最短流程：

```powershell
Copy-Item deploy/.env.preprod.example deploy/.env.preprod
# 填写环境变量，并把 fullchain.pem / privkey.pem 放入配置的 TLS_CERT_DIR
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
python deploy/preflight.py --env-file deploy/.env.preprod
docker compose --env-file deploy/.env.preprod -f deploy/compose.yaml up -d --build
python deploy/preflight.py --env-file deploy/.env.preprod --skip-ports --live
```

`migrate` 容器只执行 `alembic upgrade head`，不会运行 downgrade、drop、清空卷或删除已有数据。DeepSeek 密钥只注入 `worker`；`api`、`web` 和前端构建阶段都收不到该变量。升级前必须先备份，应用回滚默认不回退数据库结构。

完整的域名解析、服务器、防火墙、HTTPS、启动、迁移、备份、恢复、升级、回滚和故障排查步骤见 [预发布部署手册](docs/preproduction-deployment.md)。真实微信验收见 [微信真机验收清单](docs/wechat-preproduction-checklist.md)。

## 示例

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/charts `
  -ContentType application/json `
  -Body '{"name":"测试用户","gender":"male","birth_local_datetime":"1988-07-10T12:30","location_id":3101}'
```

成功响应包含 `location`、`time_normalization`、四柱、起运、大运流年、规则版本和 `calculation_trace`。日期输入必须严格为 `YYYY-MM-DDTHH:mm`，且不带秒数和时区偏移。

## AI详细分析

详细设计见 `docs/ai-analysis.md`。分析任务使用 MySQL 8 持久化，API 进程只负责提交和查询，独立 worker 负责调用模型。未配置数据库或模型时，普通 `POST /api/v1/charts` 仍然只做本地计算并正常工作。

先创建 MySQL 8 数据库并执行迁移：

```powershell
$env:BAZI_DATABASE_URL="mysql+pymysql://bazi_user:替换密码@127.0.0.1:3306/bazi?charset=utf8mb4"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

另开一个进程启动 worker。只有 worker 需要模型密钥：

```powershell
$env:BAZI_DATABASE_URL="mysql+pymysql://bazi_user:替换密码@127.0.0.1:3306/bazi?charset=utf8mb4"
$env:BAZI_LLM_API_KEY="sk-替换为控制台生成的真实密钥"
$env:BAZI_LLM_BASE_URL="https://api.deepseek.com/v1"
$env:BAZI_LLM_MODEL="deepseek-chat"
python -m app.worker
```

上面的凭据仅为格式示意。数据库连接和 API 密钥都只从环境变量读取；四张核心表不会保存密钥、Authorization 请求头或上游响应正文。可选配置包括：

- `BAZI_LLM_TIMEOUT_SECONDS`：单次请求超时，默认240秒；
- `BAZI_LLM_MAX_OUTPUT_TOKENS`：单板块最大输出，默认2600；
- `BAZI_LLM_TEMPERATURE`：默认0.35；
- `BAZI_ANALYSIS_PROMPT_VERSION`：提示词版本，默认 `bazi-analysis-1.0.0`；
- `BAZI_ANALYSIS_MAX_ATTEMPTS`：每次处理一个板块的最大尝试数，默认2；
- `BAZI_WORKER_POLL_SECONDS`：空队列轮询间隔，默认2秒；
- `BAZI_WORKER_LEASE_SECONDS`：section任务租约，默认600秒；
- `BAZI_WORKER_CONCURRENCY`：每个 worker 同时处理的 section 数，默认4；
- `BAZI_MAX_RUNNING_SECTIONS_PER_JOB`：单份报告同时运行的 section 上限，默认4；
- `BAZI_ANALYSIS_RETRY_DELAYS_SECONDS`：模型调用失败后的数据库退避秒数，默认 `30,60,120`。

调用示例：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/analyses `
  -ContentType application/json `
  -Body '{"name":"测试用户","gender":"male","birth_local_datetime":"1988-07-10T12:30","location_id":3101}'
```

提交成功立即返回 HTTP 202、`job_id` 和 `chart_id`。重复提交相同的排盘快照、模型 ID、提示词版本和规则版本时返回已有任务，不重复调用模型。查询和管理接口：

- `GET /api/v1/analyses/{job_id}/status`：查询任务进度；
- `GET /api/v1/analyses/{job_id}`：查询命盘快照和八个板块结果；
- `POST /api/v1/analyses/{job_id}/sections/{code}/retry`：单独重试失败板块；
- `POST /api/v1/analyses/{job_id}/cancel`：取消未完成任务；
- `DELETE /api/v1/analyses/{job_id}`：删除分析结果；
- `DELETE /api/v1/charts/{chart_id}`：删除出生信息、命盘快照及其全部分析与调用日志。

## 地点数据

程序只支持中国34个省级行政区，不提供其他国家和地区的排盘。`app/data/china_city_coordinates.csv` 内置392条城市经纬度记录，字段为 `id/province/city/longitude/latitude`，已经过以下启动校验：

- 必须完整覆盖34个省级行政区；
- 地点ID不能重复；
- “省份+城市”不能重复；
- 经纬度必须处于中国合理范围；
- 不能出现中国范围外的省份。

如需从原始 GBK/GB18030 或 UTF-8 CSV 重新导入：

```powershell
python -m app.scripts.import_china_city_coordinates path\to\longitude_latitude.csv
```

数据库默认生成到 `app/data/locations.sqlite3`，不会提交 Git。客户端只能提交稳定的 `location_id`，不能覆盖经纬度或 IANA 时区。

地点选择只保留两级接口：

- `GET /api/v1/locations/provinces`：返回34个省级行政区；
- `GET /api/v1/locations/cities?province=上海市`：返回该省级行政区的城市与 `location_id`。

不提供国家、区县、旧行政编码或单独地点详情接口。

包括香港、澳门、台湾在内的全部34个省级行政区统一使用北京时间 `Asia/Shanghai`。系统不会按照港澳台各自的历史时区或夏令时规则进行切换。

## 节气数据

`app/data/solar_terms.json` 由 `lunar-python 1.4.8` 离线生成，包含 1900—2201 年共 7248 条记录。1901—2100 年的保证范围恰好有 4800 条；额外年份用于1901边界和2100年出生者的百岁流年。

重新生成和校验：

```powershell
python -m app.scripts.generate_solar_terms
python -m app.scripts.validate_solar_terms
```

原始节气时间固定解释为北京时间 UTC+08:00，不使用 `Asia/Shanghai` 的历史 DST。秒级原值用于审计，边界值只在数据加载处执行一次 half-up 分钟量化。

## 起运日期约定

节气间隔先保存为整数秒。一秒实际间隔对应120秒传统年龄，因此换算满足：三天一岁、一天四个月、一小时五天。传统年龄按一年360日、每月30日拆分为年/月/日/时/分/秒。

`start_datetime` 以出生真太阳时为基准，依次添加整年、整月、整日和余下秒数；若目标月份没有原日期，则截到该月最后一天。每步大运均直接从该起运基准加整十年，避免逐段累计误差。

## 验证

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy app
```

## 适用范围与限制

- 出生输入范围为 1901-01-01 至 2100-12-31。
- 地点范围仅限内置中国34个省级行政区的392条城市记录。
- 均时差使用 NOAA 公布的 fractional-year 近似式，量化到秒；它不是高精度天文星历求解器。
- 新疆默认按出生证明上的官方北京时间解释，不自动采用民间“新疆时间”。
- 当前城市CSV的来源授权信息需要项目所有者在对外发布前确认，见 `NOTICE`。
- “神煞”没有跨流派的全集。本版本支持文档中列出的 55 条规则，不把该目录称为统一标准。
- 该项目用于历法与传统文化软件，不构成医疗、法律、金融或人生决策建议。
- AI文本是概率性文化解读，不能用于疾病诊断、投资决策或对婚姻、生育、灾祸的确定性判断。
