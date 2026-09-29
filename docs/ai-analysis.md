# AI分析持久化与任务系统

## 架构边界

`POST /api/v1/charts` 保持为纯本地确定性计算，不读取 MySQL，也不调用模型。持久化分析由两个独立进程组成：

1. FastAPI 接收出生信息，调用原有 `ChartService` 生成不可变排盘快照，写入任务后立即返回 HTTP 202。
2. 两个 `python -m app.worker` 进程使用数据库租约领取单个板块；每个进程默认并发处理4个板块。

项目没有使用 FastAPI `BackgroundTasks`。worker 进程退出不会丢失任务；租约到期后，其他 worker 会把中断的板块恢复为待处理。多个 worker 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 原子领取不同 section，而不是锁住整份报告。领取顺序优先处理各报告靠前的板块，避免一份报告长期独占全部执行槽。

## 数据模型

Alembic 迁移创建四张核心表：

- `charts`：原始出生请求、确定性排盘快照和快照哈希；
- `analysis_jobs`：报告汇总状态、模型 ID、服务商、提示词版本、规则版本和请求哈希；
- `analysis_sections`：八个独立调度单元各自的状态、正文、字符数、尝试/失败次数、`locked_at`、`locked_by`、租约截止时间、下次尝试时间和错误；
- `llm_call_logs`：每次模型调用的耗时、Token 用量、服务商 request ID 和脱敏错误。

任务状态为 `pending`、`running`、`partial`、`completed`、`failed`、`cancelled`。单个板块失败时，其他已完成正文不会回滚或覆盖；任务会成为 `partial`，失败板块可以通过 API 单独重新入队。

## 去重与恢复语义

任务请求哈希使用规范化 JSON 计算 SHA-256，输入包括完整排盘快照、模型 ID、提示词版本和规则版本。数据库对任务哈希设置唯一约束，因此并发重复提交也只会创建一个任务。每个板块另有包含板块代码的请求哈希。

worker 在模型调用前写入 `running` 调用日志并持续延长 section 租约，结束后只保存允许的元数据。若进程在调用中退出，恢复流程将未完成日志标记为租约过期并重新入队该板块。模型调用失败会通过 `next_attempt_at` 在数据库中安排 `30s -> 60s -> 120s` 指数退避；等待期间不占 worker 槽位，第四次仍失败才把板块标记为失败。外部模型协议通常不提供跨崩溃的 exactly-once 保证，因此极端情况下可能发生一次恢复性重试；已收到并提交的完成结果不会再次调用。

## 隐私与密钥

`BAZI_LLM_API_KEY` 只由 worker 从环境变量读取。数据库模型没有密钥、Authorization 头或请求头字段，日志也不会记录这些内容。上游错误仅保留内部错误码、可安全展示的简短错误、HTTP 状态和 request ID，不保存上游响应正文。

发送给模型的上下文不含姓名、经纬度和内部计算轨迹。出生时间、城市、性别、真太阳时和命盘结构会发送给已配置的模型服务商，部署方应在隐私政策中披露。

删除单个分析使用 `DELETE /api/v1/analyses/{job_id}`。删除出生信息使用 `DELETE /api/v1/charts/{chart_id}`，数据库级联删除其全部分析板块和模型调用日志。

## MySQL 8 配置

数据库应使用 `utf8mb4`。示例：

```sql
CREATE DATABASE bazi CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'bazi_user'@'%' IDENTIFIED BY '使用密码管理器生成的密码';
GRANT SELECT, INSERT, UPDATE, DELETE ON bazi.* TO 'bazi_user'@'%';
```

迁移账号还需要建表和修改表权限。生产环境建议迁移完成后，让运行账号只保留 DML 权限。

```powershell
$env:BAZI_DATABASE_URL="mysql+pymysql://bazi_user:URL编码后的密码@127.0.0.1:3306/bazi?charset=utf8mb4"
python -m alembic upgrade head
```

API 进程不要求模型密钥：

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

worker 进程配置模型密钥后独立启动。直接运行时启动一个进程、默认4路并发；Compose 通过 `deploy.replicas: 3` 启动三个相同 worker：

```powershell
$env:BAZI_LLM_API_KEY="sk-替换为真实ASCII密钥"
$env:BAZI_LLM_BASE_URL="https://api.deepseek.com/v1"
$env:BAZI_LLM_MODEL="deepseek-chat"
python -m app.worker
```

队列相关配置：

- `BAZI_WORKER_CONCURRENCY`：每个 worker 的并发 section 数，默认4；
- `BAZI_MAX_RUNNING_SECTIONS_PER_JOB`：单份报告同时运行的 section 上限，默认4；调度时优先选择当前运行 section 更少的报告；
- `BAZI_WORKER_LEASE_SECONDS`：section 租约时长，默认600秒，调用中会自动续租；
- `BAZI_WORKER_POLL_SECONDS`：空队列轮询间隔，默认2秒；
- `BAZI_ANALYSIS_RETRY_DELAYS_SECONDS`：调用失败后的调度退避，默认 `30,60,120`；
- `BAZI_ANALYSIS_MAX_ATTEMPTS`：输出篇幅不合格时，同一次 section 执行最多生成次数，默认2。

## API 流程

提交：

```http
POST /api/v1/analyses
Content-Type: application/json

{"name":"测试用户","gender":"male","birth_local_datetime":"1988-07-10T12:30","location_id":3101}
```

响应：

```json
{
  "job_id": "UUID",
  "chart_id": "UUID",
  "status": "pending",
  "deduplicated": false
}
```

轮询 `GET /api/v1/analyses/{job_id}/status`，完成或部分失败后使用 `GET /api/v1/analyses/{job_id}` 取得命盘快照和板块正文。八个板块代码为 `personality`、`relationship`、`children`、`education`、`career`、`wealth`、`health`、`life_cycles`。

## 测试

测试套件使用临时 SQLite 验证仓储语义，不替代 MySQL 8 集成环境。包含以下自动化覆盖：

- 模拟模型完成并核对耗时、Token 和 request ID 日志；
- 单板块失败、部分结果保留和单独重试；
- section 原子领取、MySQL `SKIP LOCKED`、租约过期与进程重启恢复；
- 模型失败后的30/60/120秒数据库退避；
- 设置 `BAZI_TEST_MYSQL_URL`（数据库名必须以 `_test` 结尾）后，可运行真实 MySQL
  `SKIP LOCKED` 集成测试；
- HTTP 202、状态/结果查询、取消和级联删除；
- Alembic 从空库升级并创建四张核心表；
- 普通排盘接口在没有数据库和 AI 配置时继续工作。
