# RAG 法规知识平台 - 设计文档

## 概述

基于现有 `scripts/lib/rag_engine/` 构建 Web 平台，提供法规问答、知识库管理、评估管理、合规检查五大功能模块。面向专业精算人员，支持本地开发和服务器部署。

## 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │ 法规问答 │ │ 知识库   │ │ 评估管理 │ │ 合规检查   │ │
│  │ (Chat)   │ │ 管理     │ │ & 展示   │ │ 助手       │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘ │
└───────┼────────────┼────────────┼──────────────┼────────┘
        │            │            │              │
        ▼            ▼            ▼              ▼
┌─────────────────────────────────────────────────────────┐
│                  FastAPI Backend                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │ /api/ask │ │ /api/kb  │ │ /api/eval │ │ /api/     │ │
│  │          │ │          │ │          │ │ compliance │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘ │
└───────┼────────────┼────────────┼──────────────┼────────┘
        │            │            │              │
        ▼            ▼            ▼              ▼
┌─────────────────────────────────────────────────────────┐
│              现有 scripts/lib/ (复用)                     │
│  rag_engine/ │ llm/ │ common/ │ preprocessing/           │
└─────────────────────────────────────────────────────────┘
```

### 核心原则

- **后端**：FastAPI 作为 API 层，直接复用现有 `scripts/lib/rag_engine/`，不重写任何 RAG 逻辑
- **前端**：React SPA，对话界面参考开源组件（ChatGPT-Next-Web 风格），精算场景页面自行开发
- **通信**：REST API + SSE（流式问答）
- **部署**：前后端分离，可独立部署，也可 Nginx 反代统一入口

### 新增目录结构

```
scripts/
├── api/                    # FastAPI 应用（新增）
│   ├── app.py              # FastAPI 入口
│   ├── routers/            # 路由模块
│   │   ├── ask.py          # 法规问答 API
│   │   ├── knowledge.py    # 知识库管理 API
│   │   ├── eval.py         # 评估管理 API
│   │   └── compliance.py   # 合规检查 API
│   ├── schemas/            # Pydantic 请求/响应模型
│   └── middleware/         # 中间件（CORS、错误处理）
├── web/                    # React 前端（新增）
│   ├── src/
│   │   ├── pages/          # 页面组件
│   │   ├── components/     # 通用组件
│   │   └── services/       # API 调用层
│   └── package.json
└── lib/                    # 现有代码（不动）
```

## 模块一：法规问答 (Ask)

### 交互设计

对话式界面，类似 ChatGPT，针对精算场景增强：

- **引用溯源**：回答中每个 `[来源X]` 标注可点击，侧边面板展示对应法规原文
- **来源面板**：右侧可折叠面板，列出本次检索命中的所有法规条款，支持跳转到具体条文
- **流式输出**：SSE 流式返回生成内容
- **多轮对话**：支持上下文连续追问（可配置保留轮数）
- **搜索模式切换**：支持"智能问答"和"精确检索"两种模式

### API 设计

```
POST /api/ask/chat
  请求: { question: str, conversation_id?: str, mode: "qa"|"search" }
  响应: SSE stream (逐 token 返回，最终附带 citations 和 sources)

GET  /api/ask/conversations
  响应: [{ id: str, title: str, created_at: datetime, message_count: int }]

GET  /api/ask/conversations/{id}/messages
  响应: [{ role: str, content: str, citations: Citation[], sources: Source[], timestamp: datetime }]

DELETE /api/ask/conversations/{id}
```

### 后端实现要点

- 复用 `RAGEngine.ask()` 方法，包装为 SSE 流式响应
- 对话历史存 SQLite
- `conversation_id` 关联对话上下文，传递给 RAGEngine

## 模块二：知识库管理

### 功能

- 查看已索引的法规文档列表（名称、条款数、索引时间、文件大小）
- 导入新法规文档（上传 markdown 文件或指定目录路径）
- 重建索引（全量/单文件）
- 索引状态监控（向量库大小、BM25 状态、最后更新时间）
- 法规文档预览（查看原始 markdown 内容）

### API 设计

```
GET    /api/kb/documents                # 文档列表
POST   /api/kb/documents/import         # 导入文档（上传文件或指定路径）
POST   /api/kb/documents/rebuild        # 重建索引
GET    /api/kb/documents/{name}/preview # 预览文档内容
GET    /api/kb/status                   # 索引状态（LanceDB + BM25）
DELETE /api/kb/documents/{name}         # 删除文档并更新索引
```

### 后端实现要点

- 复用 `RegulationDataImporter`、`VectorIndexManager`、`BM25Index`
- 导入/重建为耗时操作，返回 task_id，前端轮询 `/api/kb/tasks/{id}` 获取进度
- 文档元信息存储在 SQLite

## 模块三：测试数据集管理

### 现有实现

当前 30 个评测问题硬编码在 `eval_dataset.py` 的 `create_default_eval_dataset()` 中，持久化到 `data/eval_dataset.json`。数据结构：

```python
@dataclass(frozen=True)
class EvalSample:
    id: str                        # 唯一标识 (e.g., "f001")
    question: str                  # 问题文本
    ground_truth: str              # 期望答案
    evidence_docs: List[str]       # 相关文档文件名列表
    evidence_keywords: List[str]   # 检索关键词
    question_type: QuestionType    # FACTUAL / MULTI_HOP / NEGATIVE / COLLOQUIAL
    difficulty: str                # easy / medium / hard
    topic: str                     # 主题分类 (e.g., "健康保险")

class QuestionType(Enum):
    FACTUAL = "factual"
    MULTI_HOP = "multi_hop"
    NEGATIVE = "negative"
    COLLOQUIAL = "colloquial"
```

**现有局限**：
- 无版本管理，无法追踪数据集演进
- 无筛选能力（按类型/难度/主题）
- 无创建时间、作者等元数据
- 30 题覆盖面有限，需要扩展

### 功能

- 查看/编辑/新增/删除评测问题
- 批量导入（JSON 格式，兼容现有 `eval_dataset.json` 格式 `{"samples": [...], "total": N}`）
- 按类型筛选（FACTUAL / MULTI_HOP / NEGATIVE / COLLOQUIAL）
- 按难度、主题筛选
- 版本快照：保存当前数据集为命名版本，支持回滚对比
- 初始化时自动导入现有 `data/eval_dataset.json` 中的 30 题

### API 设计

```
GET    /api/eval/dataset                        # 问题列表（支持 ?type=&difficulty=&topic= 筛选）
POST   /api/eval/dataset/samples                # 新增问题
PUT    /api/eval/dataset/samples/{id}           # 编辑问题
DELETE /api/eval/dataset/samples/{id}           # 删除问题
POST   /api/eval/dataset/import                 # 批量导入（JSON，兼容现有格式）
POST   /api/eval/dataset/snapshots              # 创建版本快照
GET    /api/eval/dataset/snapshots              # 快照列表
POST   /api/eval/dataset/snapshots/{id}/restore # 回滚到指定快照
```

### 后端实现要点

- 复用 `EvalSample` 数据结构和 `QuestionType` 枚举，在 SQLite 中新增 `created_at`、`updated_at` 字段
- 首次启动时检测 SQLite 中无数据，自动从 `data/eval_dataset.json` 导入
- 快照为 `eval_samples` 表的完整时间点拷贝（`eval_snapshot_items` 关联表）
- 批量导入格式与现有 JSON 保持兼容，同时支持仅传入 samples 数组

## 模块四：评估结果展示

### 现有实现

`evaluator.py` 提供两类评估器：

**RetrievalEvaluator** — 检索质量评估：
- Precision@K、Recall@K、MRR、NDCG、Redundancy Rate
- 相关性判断：`_is_relevant()` 基于文档文件名 + 关键词匹配
- 按问题类型分组的分项指标（`by_type`）

**GenerationEvaluator** — 生成质量评估：
- RAGAS 模式（需安装）：Faithfulness、Answer Relevancy、Answer Correctness
- 轻量模式（默认）：Token overlap 计算的近似指标
- 同样支持按类型分组

**报告结构**（`RAGEvalReport`）：
```python
@dataclass
class RAGEvalReport:
    retrieval: RetrievalEvalReport
    generation: GenerationEvalReport
    total_samples: int
    failed_samples: List[Dict[str, Any]]
```

**现有局限**：
- 无逐题详情持久化（只有聚合指标）
- 无评估运行历史记录
- 对比功能仅限命令行，输出文本表格
- 无法查看单个问题的检索结果和生成回答

### 功能

- 触发评估运行，支持三种模式（与现有 `evaluate_rag.py` 一致）：
  - `retrieval`：仅检索评估（快速，无 LLM 调用）
  - `generation`：仅生成评估（需 LLM）
  - `full`：完整评估（默认）
- 指标仪表盘：Precision@K、Recall@K、MRR、NDCG、Redundancy Rate、Faithfulness、Answer Relevancy、Answer Correctness
- 按问题类型分组指标（FACTUAL / MULTI_HOP / NEGATIVE / COLLOQUIAL）
- 逐题详情：每个问题的检索结果列表、生成回答、与 ground_truth 对比、各项评分
- 失败样本高亮：Recall < 0.5 的样本重点标注
- 版本对比：选择两个评估报告，展示指标变化（绝对值 + 百分比变化）
- 导出评估报告（JSON / Markdown），JSON 格式与现有 `evaluate_rag.py --export` 兼容

### API 设计

```
POST /api/eval/runs                              # 触发评估
  请求: { mode: "retrieval"|"generation"|"full", top_k?: int, chunking?: str }
  响应: { run_id: str, status: "pending" }

GET  /api/eval/runs/{id}/status                  # 运行状态
  响应: { status: "running"|"completed"|"failed", progress: int, total: int }

GET  /api/eval/runs/{id}/report                  # 评估报告（聚合指标）
GET  /api/eval/runs/{id}/details                 # 逐题详情
GET  /api/eval/runs                              # 历史评估列表
POST /api/eval/runs/compare                      # 版本对比（传入两个 run_id）
  请求: { baseline_id: str, compare_id: str }
  响应: { metrics_diff: {...}, improved: [...], regressed: [...] }

GET  /api/eval/runs/{id}/export?format=json|md   # 导出报告
```

### 后端实现要点

- 复用 `RetrievalEvaluator` 和 `GenerationEvaluator`，不修改评估逻辑
- 每次评估运行记录：`eval_runs`（模式、配置、时间戳、状态）
- 新增 `eval_sample_results` 表存储逐题详情：检索结果列表、生成回答、各项指标
- 评估运行为异步任务（asyncio），前端轮询 status
- 导出 JSON 格式与现有 `{"timestamp": ..., "report": {...}}` 保持兼容
- 对比逻辑复用 `evaluate_rag.py` 中的 `_print_comparison()` 计算逻辑

## 模块五：合规检查助手

### 两种检查模式

**模式 A - 产品参数检查**：
- 用户输入结构化产品参数（险种类型、等待期、免赔额、保险期间、缴费方式等）
- 系统根据险种自动检索相关法规要求
- 逐项对比参数是否合规，输出合规/不合规/需关注三级判定
- 生成合规报告，列出每项检查的法规依据

**模式 B - 条款文档审查**：
- 用户上传保险条款文档（markdown/文本）
- 系统提取条款中的关键参数
- 自动检索对应法规要求并比对
- 标注不合规条款，给出修改建议

### 输出格式

```
合规检查报告
├── 基本信息：产品名称、险种、检查时间
├── 检查结果摘要：合规 N 项 / 不合规 M 项 / 需关注 K 项
├── 逐项检查详情
│   ├── [合规] 等待期：90天 → 法规要求≤180天 [来源X]
│   ├── [不合规] 免赔额：5000元 → 法规要求≤2000元 [来源X]
│   └── [需关注] 保险期间：1年 → 无明确法规限制
└── 法规依据汇总
```

### API 设计

```
POST /api/compliance/check/product    # 产品参数检查
  请求: { product_name: str, category: str, params: dict }
  响应: ComplianceReport

POST /api/compliance/check/document   # 条款文档审查
  请求: { document_content: str, product_name?: str }
  响应: ComplianceReport

GET  /api/compliance/reports          # 合规报告历史
GET  /api/compliance/reports/{id}     # 合规报告详情
```

### 检查策略：LLM 驱动

所有合规检查通过 RAG 检索 + LLM 判断完成：
- 根据险种 category 检索相关法规条款
- LLM 提取法规中的参数要求（数值类 + 模糊条款类）
- LLM 对比产品参数/条款文档进行判定
- 输出合规/不合规/需关注三级判定，附带法规依据和原文引用

### 后端实现要点

- 合规检查核心逻辑：复用 `RAGEngine.ask()` 检索法规，用专用合规检查 prompt 驱动 LLM
- LLM 输出结构化合规检查结果（JSON），包含每项检查的判定、依据、法规来源
- 条款文档审查：先 LLM 提取文档中的关键参数，再复用合规检查逻辑
- 合规报告存储在 SQLite，支持历史查询和对比

## 技术选型

### 后端

| 组件 | 选型 | 理由 |
|------|------|------|
| Web 框架 | FastAPI | 异步、自动 OpenAPI 文档、类型安全 |
| 数据库 | SQLite | 本地部署友好、零配置 |
| 流式输出 | SSE (Server-Sent Events) | 比 WebSocket 简单，单向推送够用 |
| 异步任务 | asyncio + 轮询 | 耗时操作返回 task_id，前端轮询状态，避免引入 Celery 等重依赖 |
| ORM | SQLAlchemy Core | 轻量，不引入 Full ORM 复杂性 |

### 前端

| 组件 | 选型 | 理由 |
|------|------|------|
| 框架 | React 18 + TypeScript | 生态成熟、类型安全 |
| 构建 | Vite | 快速开发体验 |
| UI 库 | Ant Design | 中文友好、组件丰富 |
| 对话界面 | 自建（参考 ChatGPT-Next-Web） | 精算场景需要深度定制 |
| Markdown | react-markdown + remark-gfm | 渲染回答内容 |
| 图表 | Recharts | 评估指标可视化 |
| 状态管理 | Zustand | 轻量，比 Redux 简洁 |

### 数据库 Schema

```
conversations        - 对话记录 (id, title, created_at)
messages             - 消息 (id, conversation_id, role, content, citations_json, sources_json, timestamp)
documents            - 法规文档元信息 (name, file_path, clause_count, file_size, indexed_at, status)
eval_samples         - 评测问题 (id, question, ground_truth, evidence_docs_json, evidence_keywords_json, question_type, difficulty, topic, created_at, updated_at)
eval_snapshots       - 数据集版本快照 (id, name, description, sample_count, created_at)
eval_snapshot_items  - 快照中的问题条目 (snapshot_id, eval_sample_id)
eval_runs            - 评估运行记录 (id, mode, status, progress, total, started_at, finished_at, config_json)
eval_sample_results  - 逐题评估详情 (run_id, sample_id, retrieved_docs_json, generated_answer, retrieval_metrics_json, generation_metrics_json)
compliance_reports   - 合规报告 (id, product_name, category, mode, result_json, created_at)
```

## 设计约束

1. 不修改现有 `scripts/lib/` 中的核心逻辑，仅在 `scripts/api/` 中做薄封装
2. 前端所有页面使用中文
3. SQLite 数据库文件放在 `scripts/data/` 目录下
4. 评估报告格式与现有 `evaluate_rag.py` 输出保持兼容
5. 一期不做用户认证，本地部署场景通过端口隔离即可；后续部署到服务器时再添加
6. SSE 仅用于问答流式输出，其他耗时操作（导入、评估）统一用轮询
