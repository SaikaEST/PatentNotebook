# 专利审查助手项目中期答辩复习总结

## 1. 项目一句话定位
本项目是一个面向企业专利团队的“审查历程分析工作台”，把分散的审查文件（OA、答复、修改等）沉淀为可检索、可追溯、可生成报告的知识底座，并提供问答与报告产出能力。

核心要求有两点：
- 全部 AI 输出必须可追溯（带 citation：`source_id/chunk_id/page/quote`）。
- 数据接入支持插件化抓取，同时始终保留手工上传兜底能力。

---

## 2. 系统总体架构（答辩建议先讲这张“逻辑图”）

### 2.1 技术栈
- 后端：FastAPI + SQLAlchemy + Celery
- 存储：PostgreSQL（pgvector）+ MinIO + Redis
- 前端：Next.js 14（React 18）
- 部署：Docker Compose 一键拉起（`docker-compose.yml`）

### 2.2 组件职责
- `api`：同步接口层，负责鉴权、业务编排、返回任务状态。
- `worker`：异步任务层，负责文档解析、向量化、产物生成、导出。
- `postgres`：业务数据与向量数据（`DocumentChunk.embedding`）。
- `minio`：原始文件、解析文本、产物文件、导出文件对象存储。
- `redis`：Celery Broker/Backend（任务队列与状态）。
- `frontend`：Sources / Chat / Studio 三面板交互。

---

## 3. 代码目录速览（“各部分作用”）

- `backend/app/main.py`
  - 应用入口：注册 CORS、健康检查、所有路由、开发环境初始化数据库。
- `backend/app/api/routes/*`
  - 业务接口层：`auth/cases/sources/chat/artifacts/exports/alerts`。
- `backend/app/models/entities.py`
  - 领域模型核心：租户、案件、文档、切片、问答、产物、审计等。
- `backend/app/tasks/*`
  - 异步任务核心：采集与处理、产物生成、导出。
- `backend/app/services/*`
  - 基础服务：解析、分类、向量化、检索、引用、对象存储。
- `backend/app/pipelines/adapters/*`
  - 外部来源适配器（CNIPR/CNIPA/EPO/USPTO/DMS），实现插件化接入。
- `frontend/components/*`
  - 三个核心交互面板：来源管理、问答、报告工坊。
- `docs/openapi.yaml`
  - API 合同快照（演示与联调依据）。

---

## 4. 后端关键链路与关键代码

## 4.1 API 启动与路由装配
文件：`backend/app/main.py`
- `FastAPI(title=settings.app_name)` 创建应用。
- `on_startup()` 在 `env=dev` 时调用 `init_db()`，自动创建表与 `vector` 扩展。
- 统一挂载业务路由：
  - `/auth` 登录
  - `/cases` 案件管理与采集启动
  - `/sources` 来源上传/勾选
  - `/chat` 引用式问答
  - `/studio` 产物生成与下载
  - `/exports` 导出
  - `/alerts` 订阅

## 4.2 鉴权与多租户入口
文件：`backend/app/api/routes/auth.py`、`backend/app/api/deps.py`
- 登录策略（MVP 友好）：
  - 若用户不存在，自动创建 `default tenant + default workspace + org_admin user`。
  - 返回 JWT（`create_access_token`）。
- 请求鉴权：
  - `get_current_user()` 从 `Authorization: Bearer` 解 token，按邮箱查用户。

这部分在中期可强调：
- 已具备企业化结构（Tenant/Workspace）；
- 但鉴权仍是本地简化版，OIDC/SAML 是占位实现（`auth_providers.py`）。

## 4.3 采集与处理主链路（项目最关键）
入口文件：`backend/app/api/routes/cases.py`
- `POST /cases/{case_id}/ingest` 调用 `ingest_case.delay(...)` 进入异步。
- 若案件缺少 `JurisdictionCase`，接口会返回 `missing=true` 和补救建议。

核心任务：`backend/app/tasks/ingest.py`
- `ingest_case`：
  1. 按辖区解析 provider 顺序（`resolve_provider_order`）。
  2. 调 adapter 拉文档元信息 + 文件字节。
  3. 写入 MinIO，创建 `SourceDocument`。
  4. 触发 `process_source.delay(source_id)`。
- `process_source`：
  1. 从 MinIO 读文件。
  2. `parse_document_bytes` 解析 PDF/HTML/XML/TXT。
  3. `chunk_pages` 分块（默认 1500 字符）。
  4. `embed_text` 生成向量并写 `DocumentChunk.embedding`。
  5. 落解析全文到 MinIO（`parsed/{source_id}.txt`）。

可直接用于汇报的“工程价值”：
- 同时支持“官方接口抓取 + 内网 DMS + 人工上传”三通道。
- 处理链路全异步，适合大文档与批量案件。
- 每一步都有 `missing_reason/followup_suggestions`，避免黑盒失败。

## 4.4 检索问答与引用闭环
文件：`backend/app/api/routes/chat.py`、`backend/app/services/retrieval.py`、`backend/app/services/citations.py`
- `/chat` 必须传 `source_ids`，否则返回缺失提示。
- `retrieve_chunks`：
  - 先按向量余弦距离取 TopK；
  - 若无向量结果，回退到按 `chunk_index` 顺序取片段。
- `build_citations`：
  - 对每个 chunk 生成结构化引用 `source_id/chunk_id/page/quote`。

这部分是答辩亮点：
- “回答内容 + 证据定位”绑定输出，不是纯生成式黑盒。

## 4.5 产物生成与下载
文件：`backend/app/api/routes/artifacts.py`、`backend/app/tasks/artifacts.py`、`backend/app/services/artifact_builder.py`
- `POST /studio/artifacts`：创建 `Artifact(status=queued)` 并异步生成。
- `generate_artifact`：
  - 按传入 source_ids 或案件下全部来源做检索。
  - 生成 Markdown 产物并写 MinIO（`artifacts/{artifact_id}.md`）。
  - 更新状态为 `ready`。
- `/studio/artifacts/{id}/download-url`：
  - 返回 MinIO 预签名下载地址（带过期时间）。

当前状态说明（中期要诚实交代）：
- `timeline/claim_diff/risk_report` 模板已搭好，深层抽取逻辑仍是占位。

---

## 5. 前端三大模块作用与关键实现

## 5.1 页面骨架
文件：`frontend/app/page.tsx`
- 三栏布局：`SourcesPanel` + `ChatPanel` + `StudioPanel`。
- 形成“先上传/勾选来源 -> 再问答 -> 再生成报告”的顺序操作链。

## 5.2 SourcesPanel（来源文档面板）
文件：`frontend/components/SourcesPanel.tsx`
- 输入 token、辖区案件 ID、文档类型并上传文件。
- 列表展示来源文档并支持 `included` 勾选切换（用于后续问答/产物范围）。
- 将勾选结果写入本地 `INCLUDED_SOURCE_IDS_STORAGE_KEY`。

## 5.3 ChatPanel（引用式问答面板）
文件：`frontend/components/ChatPanel.tsx`
- 从本地或 API 同步已勾选 source_ids。
- 调 `/chat` 获取答案与 citations，并渲染证据标签。
- `missing_reason` 会在消息中直接展示，便于用户补资料。

## 5.4 StudioPanel（报告工坊面板）
文件：`frontend/components/StudioPanel.tsx`
- 选择产物类型（`quick_outline/timeline/claim_diff/risk_report`）。
- 创建任务、轮询状态、拿预签名链接下载产物。
- 任务列表持久化到本地（`ARTIFACT_TASKS_STORAGE_KEY`）。

---

## 6. 数据模型设计要点（中期高频提问点）
文件：`backend/app/models/entities.py`

### 6.1 组织与权限
- `Tenant -> Workspace -> Project -> PatentCase` 支撑多租户分层。
- `User.roles_json` + API 侧依赖注入构成权限入口。

### 6.2 专利案件域
- `PatentCase`：案件主实体
- `JurisdictionCase`：CN/EU/US 等辖区维度
- `SourceDocument`：原始文档对象
- `DocumentChunk`：切片与向量（RAG 基础）
- `Artifact`：异步生成产物状态机

### 6.3 可扩展分析域（已建模，待强化算法）
- `Event`、`OfficeActionIssue`、`ClaimDiff`、`RiskSignal` 等已预留。
- 说明架构已支持“从文件处理”走向“审查知识图谱化”。

---

## 7. 异步与扩展机制（为什么这样设计）

- Celery 队列拆分：`ingest/nlp/export/default`（`tasks/celery_app.py`）
- Provider 注册中心：`ADAPTERS` + `resolve_provider_order(...)`
- Adapter 协议统一：`list_documents` / `fetch_document`

设计收益：
- 解耦外部源接入与业务主流程；
- 后续新增来源只需加 Adapter，不改核心接口。

---

## 8. 现阶段完成度与边界

### 8.1 已完成（可演示）
- 全链路可跑通：登录 -> 建案 -> 上传/抓取 -> 解析分块 -> 问答 -> 生成并下载 Markdown 产物。
- 引用闭环已落地：问答与产物都可以回溯到来源片段。
- 插件化采集框架已成形，DMS 兜底可用。

### 8.2 仍在完善（答辩需主动说明）
- OIDC/SAML、细粒度 RBAC 仍是企业化预留。
- EPO/USPTO adapter 当前为占位实现。
- 高级 NLP（事件抽取、claim diff 自动比对、风险评分）仍需算法补全。
- 测试覆盖目前偏基础（健康检查 + 少量 helper 测试）。

---

## 9. 中期汇报建议话术（可直接复述）

1. 先讲目标：解决专利审查资料碎片化，建设“可追溯分析工作台”。
2. 再讲架构：FastAPI + Celery + pgvector + MinIO，前后端分离，异步处理。
3. 展示主链路：`/cases/{id}/ingest -> ingest_case -> process_source -> /chat -> /studio/artifacts`。
4. 强调亮点：引用强约束、缺失提示机制、插件化接入、可扩展数据模型。
5. 诚实说明边界：高级 NLP 与企业 SSO 仍在迭代，下一阶段重点补算法与测试。

---

## 10. 可附在 PPT 的“关键代码清单”

- 应用入口与路由：`backend/app/main.py`
- 鉴权与 token：`backend/app/core/security.py`
- 登录与默认租户创建：`backend/app/api/routes/auth.py`
- 采集任务主流程：`backend/app/tasks/ingest.py`
- Provider 路由策略：`backend/app/pipelines/adapters/registry.py`
- 文档解析与分块：`backend/app/services/document_parser.py`
- 向量检索：`backend/app/services/retrieval.py`
- 引用构建：`backend/app/services/citations.py`
- 产物生成：`backend/app/tasks/artifacts.py`
- 前端三面板：`frontend/components/SourcesPanel.tsx`、`frontend/components/ChatPanel.tsx`、`frontend/components/StudioPanel.tsx`

> 这份项目目前可定义为：**“已完成可用骨架 + 关键链路打通 + 企业化扩展位预留”**，适合中期答辩展示工程化能力与后续研究空间。
