# Actuary Sleuth - AI 精算审核助手

## Build And Test
- **Install**: `pip install -r requirements.txt`
- **Dev**: `python3 scripts/audit.py --documentUrl <feishu_url>`
- **Test**: `pytest scripts/tests/`
- **Type Check**: `mypy scripts/lib/`

## Architecture Boundaries
- **Entry points**: `scripts/audit.py`, `scripts/preprocess.py`, `scripts/check.py`, `scripts/scoring.py`, `scripts/report.py`
- **Domain logic**: `scripts/lib/audit/`, `scripts/lib/preprocessing`, `scripts/lib/reporting`
- **Data models**: `scripts/lib/common/models.py`, `scripts/lib/common/audit.py`
- **Utilities**: `scripts/lib/common/` - shared across modules
- **Do not put** persistence logic in domain modules, use `scripts/lib/common/database.py`
- **Do not put** LLM client logic in domain modules, use `scripts/lib/llm/`

## NEVER
- **Modify** `scripts/.env`, `scripts/config/settings.json` lockfiles, or CI secrets without explicit approval
- **Remove** feature flags or constants without searching all call sites
- **Commit** without running tests (`pytest scripts/tests/`)
- **Add** `from lib.exceptions import *` wildcard imports in library code
- **Add** sys.path manipulation in library files (only in entry points if absolutely necessary)
- **Create** new service packages, reuse existing `scripts/lib/` structure

## ALWAYS
- **Show diff** before committing (`git diff HEAD`)
- **Update** documentation for user-facing changes
- **Run tests** before pushing (`pytest scripts/tests/`)
- **Follow** the existing code style and patterns
- **Use** type annotations for public APIs
- **Use** frozen dataclass for data models
- **Archive** exceptions to corresponding modules

## Compact Instructions

Preserve:
1. **Architecture decisions** - NEVER summarize technical decisions
2. **Modified files** - List files changed and key changes
3. **Current verification status** - Pass/fail commands, test results
4. **Open risks, TODOs, rollback notes** - Track known issues

---

## 项目概述

Actuary Sleuth 是一个基于 AI 的保险产品精算审核助手，能够自动解析保险产品文档、检测负面清单违规、分析定价合理性，并生成结构化的审核报告。

## 技术栈

- **Python 3.10+**
- **Ollama** - 本地 LLM 推理
- **SQLite** - 数据存储
- **飞书 API** - 文档推送
- **pytest** - 测试框架
- **mypy** - 类型检查

## 项目结构

```
actuary-sleuth/
├── scripts/
│   ├── audit.py              # 主审核流程入口
│   ├── preprocess.py         # 文档预处理入口
│   ├── check.py              # 负面清单检查入口
│   ├── scoring.py            # 定价分析入口
│   ├── report.py             # 报告生成入口
│   ├── query.py              # 法规查询入口
│   ├── init_db.py            # 数据库初始化
│   ├── lib/                  # 核心库
│   │   ├── common/           # 公共模块
│   │   │   ├── models.py              # 核心数据模型
│   │   │   ├── audit.py               # 审核流程模型
│   │   │   ├── result.py              # 统一结果类
│   │   │   ├── product.py             # 产品信息处理
│   │   │   ├── database.py            # 数据库操作
│   │   │   ├── exceptions.py          # 通用异常
│   │   │   ├── constants.py           # 所有常量
│   │   │   ├── logger.py              # 日志工具
│   │   │   └── ...
│   │   ├── audit/             # 审核模块
│   │   ├── preprocessing/     # 预处理模块
│   │   ├── reporting/         # 报告生成
│   │   ├── rag_engine/        # RAG向量引擎
│   │   ├── llm/               # LLM客户端抽象
│   │   ├── config.py          # 全局配置管理
│   │   └── exceptions.py      # 基础异常定义
│   └── tests/                # 测试套件
├── data/                     # 数据目录
├── config/                   # 配置文件
├── CHANGELOG.md              # 变更日志
├── CLAUDE.md                 # 本文档
└── plan.md                   # 改进方案文档
```

---

## 编码规范

### 命名约定

**函数名使用业务语义，面向业务而非技术实现**
```python
# ✓ 好 - 业务语义
save_audit_record()
fetch_feishu_document()
calculate_result()
execute_preprocess()
check_negative_list()

# ✗ 避免 - 技术实现别名
save_audit_record as db_save
fetch_document_content as fetch
```

**方法名使用动名词组合，见名知意**
```python
# ✓ 好
fetch_feishu_document()
execute_preprocess()
check_violations()

# ✗ 避免
fetch_from_feishu()
preprocess_execute()
```

**类名使用名词，表示实体或概念**
```python
# ✓ 好
class AuditService: ...
class DocumentFetcher: ...
class Product: ...

# ✗ 避免
class Auditing: ...
class Fetch: ...
```

**私有函数使用前缀 `_`**
```python
def _managed_query(...):  # 内部使用
def managed_query(...):   # 公开 API
```

### 面向对象设计

**隐藏内部实现细节，简化用户使用**
```python
# ✓ 好 - 使用对象方法
result.get_clauses()
result.get_product_info()

# ✗ 避免 - 暴露内部结构
result['clauses']
result.get('clauses', [])
```

**布尔值检查使用属性**
```python
# ✓ 好
if result.success:
    ...

# ✗ 避免
if result.is_success():
    ...
```

**类设计满足单一职责**
```python
# ✓ 好
class DocumentFetcher:
    """只负责文档获取"""

# ✗ 避免
class AuditManager:
    """既负责流程又负责获取文档又负责存储"""
```

### API 设计

**把复杂留给自己，把简单留给用户**
```python
# ✓ 好 - 用户只需提供 URL
def execute_audit(document_url: str) -> AuditResult:
    document_content = fetch_feishu_document(document_url)
    ...

# ✗ 避免 - 把复杂性转嫁给用户
def execute_audit(document_url: str, document_content: str) -> AuditResult:
    """用户需要自己获取文档内容"""
```

**异常类具体化，归档到对应模块**
```python
# lib/exceptions.py - 基础异常定义
class ActuarySleuthException(Exception):
    """项目基类异常"""

# lib/common/exceptions.py - 重新导出常用异常
from lib.exceptions import ActuarySleuthException, DatabaseError

# lib/preprocessing/exceptions.py - 预处理模块异常
class DocumentFetchError(ActuarySleuthException):
    """文档获取失败异常"""
```

### 模块组织

1. **lib/common/** - 通用数据模型和工具
2. **lib/audit/** - 审核模块
3. **lib/preprocessing/** - 预处理模块
4. **lib/reporting/** - 报告生成
5. 避免过度抽象，转换逻辑优先内联到使用处

### 数据模型设计

**使用 frozen dataclass 确保不可变性**
```python
@dataclass(frozen=True)
class PreprocessedResult:
    audit_id: str
    document_url: str
    timestamp: datetime
    product: Product
    clauses: List[Dict[str, Any]]
```

**模型元数据包含必要的上下文信息**
```python
# ✓ 好 - 元数据包含 document_url
product = Product(
    name="xxx",
    company="xxx",
    category=ProductCategory.HEALTH,
    document_url=document_url,
)
```

---

## 核心流程

### 审核流程

```
1. 文档获取 (fetch_feishu_document)
   ↓
2. 预处理 (execute_preprocess)
   ↓
3. 负面清单检查 (check_negative_list)
   ↓
4. 定价分析 (analyze_pricing)
   ↓
5. 综合评估 (calculate_result)
   ↓
6. 保存到数据库
   ↓
7. 导出报告 (可选)
```

### 数据流

```
DocumentContent
    ↓ (execute_preprocess)
PreprocessedResult (Product + Clauses + PricingParams)
    ↓ (check_negative_list)
CheckedResult (+ Violations)
    ↓ (analyze_pricing)
AnalyzedResult (+ PricingAnalysis)
    ↓ (calculate_result)
EvaluationResult (+ Score + Grade)
```

---

## 开发指南

### 添加新的检查规则
1. 在数据库 `negative_list` 表中添加规则
2. 规则支持关键词匹配和正则表达式

### 添加新的产品类型
1. 在 `lib/common/models.py` 的 `ProductCategory` 枚举中添加
2. 在 `lib/common/product_type.py` 中添加映射

### 修改报告模板
报告模板使用模板方法模式，主要修改点：
- `lib/reporting/template.py` 的 `ReportGenerationTemplate` 类

### 添加新的 LLM 客户端
1. 在 `lib/llm/` 创建新的客户端文件
2. 实现基础接口 `lib/llm/base.py`
3. 在 `lib/llm/factory.py` 注册客户端
4. 在 `scripts/config/settings.json` 配置模型参数

---

## 配置

配置文件位于 `scripts/config/settings.json`，或通过环境变量覆盖。

```json
{
  "llm": {
    "default_provider": "ollama",
    "models": {...}
  },
  "feishu": {...},
  "report": {...}
}
```

---

## 约束总结

1. **命名规范**：函数名使用业务语义、动名词组合、见名知意
2. **面向对象**：隐藏实现细节、单一职责、使用对象方法
3. **API 设计**：复杂留给自己、简单留给用户
4. **异常处理**：具体异常类、归档到对应模块
5. **数据模型**：不可变性、包含元数据、避免不必要转换
6. **模块组织**：不新增 service 包、复用现有 lib/ 结构
7. **测试要求**：测试未通过不允许提交代码
8. **代码注释**：代码自注释，不写冗余注释
9. **时间处理**：使用 `lib/common/date_utils` 工具类
10. **数据转换**：避免不必要的类型转换
11. **职责下沉**：计算逻辑下沉到数据对象
12. **参数精简**：避免冗余参数
13. **常量集中**：所有常量归档到 `lib/common/constants.py`
14. **配置管理**：使用线程安全单例 `lib/config.py`


