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

## ALWAYS
- **Show diff** before committing (`git diff HEAD`)
- **Update** documentation for user-facing changes
- **Run tests** before pushing (`pytest scripts/tests/`)
- **Follow** the existing code style and patterns
- **Use** type annotations for public APIs

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

## 项目结构（最新）

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
│   ├── template.py           # 旧版模板（保留兼容）
│   ├── lib/                  # 核心库
│   │   ├── common/           # 公共模块（12个模块）
│   │   │   ├── models.py              # 核心数据模型（Product, ProductCategory等）
│   │   │   ├── audit.py               # 审核流程模型（PreprocessedResult等）
│   │   │   ├── result.py              # 统一结果类（ProcessResult）
│   │   │   ├── product.py             # 产品信息处理
│   │   │   ├── product_type.py        # 产品类型映射
│   │   │   ├── database.py            # 数据库操作
│   │   │   ├── date_utils.py          # 时间工具
│   │   │   ├── exceptions.py          # 通用异常
│   │   │   ├── constants.py           # 所有常量（含PreprocessingConstants）
│   │   │   ├── cache.py               # 缓存管理器
│   │   │   ├── logging_config.py       # 日志配置
│   │   │   ├── id_generator.py        # ID生成
│   │   │   └── logger.py              # 日志工具
│   │   ├── audit/             # 审核模块（3个模块）
│   │   │   ├── auditor.py             # 合规审核器
│   │   │   ├── prompts.py             # 审核提示词
│   │   │   └── evaluation.py          # 评分逻辑
│   │   ├── preprocessing/     # 预处理模块（16个模块）
│   │   │   ├── document_fetcher.py    # 飞书文档获取
│   │   │   ├── document_extractor.py  # 提取器入口
│   │   │   ├── fast_extractor.py      # 规则提取
│   │   │   ├── dynamic_extractor.py   # LLM提取
│   │   │   ├── classifier.py          # 产品分类
│   │   │   ├── normalizer.py          # 文档规范化
│   │   │   ├── validator.py           # 结果验证
│   │   │   ├── extractor_selector.py   # 提取器选择
│   │   │   ├── prompt_builder.py      # 提示词构建
│   │   │   ├── models.py              # 预处理数据模型
│   │   │   ├── exceptions.py          # 预处理异常
│   │   │   └── utils/                 # 预处理工具
│   │   ├── reporting/         # 报告生成（17个模块）
│   │   │   ├── template.py            # 报告模板
│   │   │   ├── model.py               # EvaluationContext
│   │   │   ├── export/                # 导出功能
│   │   │   │   ├── docx_exporter.py   # DOCX导出
│   │   │   │   ├── docx_generator.py  # DOCX生成
│   │   │   │   ├── feishu_pusher.py    # 飞书推送
│   │   │   │   ├── validation.py        # 导出验证
│   │   │   │   ├── constants.py         # 导出常量
│   │   │   │   └── result.py            # 导出结果
│   │   │   └── strategies/            # 整改策略
│   │   │       └── remediation/       # 整改策略实现
│   │   ├── rag_engine/        # RAG向量引擎（10个模块）
│   │   │   ├── rag_engine.py          # RAG引擎主类
│   │   │   ├── retrieval.py           # 混合检索
│   │   │   ├── fusion.py              # 结果融合
│   │   │   ├── index_manager.py       # 索引管理
│   │   │   ├── doc_parser.py          # 法规解析
│   │   │   ├── data_importer.py       # 数据导入
│   │   │   ├── tokenizer.py           # 中文分词
│   │   │   ├── llamaindex_adapter.py  # LlamaIndex适配
│   │   │   ├── config.py              # RAG配置
│   │   │   └── vector_store.py        # 向量存储
│   │   ├── llm/               # LLM客户端抽象（7个模块）
│   │   │   ├── factory.py             # 客户端工厂
│   │   │   ├── base.py                # 基础接口
│   │   │   ├── models.py              # 模型定义
│   │   │   ├── ollama.py              # Ollama实现
│   │   │   ├── zhipu.py               # 智谱实现
│   │   │   └── metrics.py             # API指标
│   │   ├── middleware/        # 中间件（2个模块）
│   │   │   └── base.py                # 中间件基类
│   │   ├── config.py          # 全局配置管理（线程安全单例）
│   │   ├── exceptions.py      # 基础异常定义
│   │   ├── evaluation.py      # 评分逻辑（已移至audit/）
│   │   ├── id_generator.py    # ID生成（已移至common/）
│   │   ├── logger.py          # 日志工具（已移至common/）
│   │   ├── ollama.py          # Ollama客户端（已删除，使用llm/ollama.py）
│   │   ├── vector_store.py    # 向量存储（已移至rag_engine/）
│   │   └── constants.py       # 预处理常量（已合并至common/constants.py）
│   └── tests/                # 测试套件
│       ├── lib/               # 模块测试
│       └── integration/       # 集成测试
├── data/                     # 数据目录
├── config/                   # 配置文件
├── CHANGELOG.md              # 变更日志
├── CLAUDE.md                 # 本文档
├── plan.md                   # 改进方案文档
└── research.md               # 问题研究报告
```

## 项目目标

- **优先级**: 正确性 > 可维护性 > 性能

---

## 编码规范

### 命名约定

1. **函数名使用业务语义，面向业务而非技术实现**
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
   calculate_result as compute
   ```

2. **方法名使用动名词组合，见名知意**
   ```python
   # ✓ 好
   fetch_feishu_document()
   execute_preprocess()
   check_violations()
   analyze_pricing()

   # ✗ 避免
   fetch_from_feishu()  # 技术实现导向
   preprocess_execute() # 动词后置
   ```

3. **类名使用名词，表示实体或概念**
   ```python
   # ✓ 好
   class AuditService: ...
   class DocumentFetcher: ...
   class Product: ...

   # ✗ 避免
   class Auditing: ...  # 动名词混淆
   class Fetch: ...     # 过于简略
   ```

4. **私有函数使用前缀 `_`**
   ```python
   def _managed_query(...):  # 内部使用
   def managed_query(...):   # 公开 API
   ```

5. **常量使用 UPPER_CASE 或类常量**
   ```python
   # 模块级常量
   MAX_VIOLATIONS = 100
   DEFAULT_TIMEOUT = 30

   # 类常量（推荐）
   class AuditConstants:
       DEFAULT_TIMEOUT = 30
       MAX_VIOLATIONS = 100
   ```

### 面向对象设计原则

1. **隐藏内部实现细节，简化用户使用**
   ```python
   # ✓ 好 - 使用对象方法
   class PreprocessedResult:
       def get_clauses(self) -> List[Dict]:
           return self._clauses

       def get_product_info(self) -> Product:
           return self._product_info

   # 使用时
   result.get_clauses()
   result.get_product_info()

   # ✗ 避免 - 暴露内部结构
   result['clauses']
   result.get('clauses', [])
   ```

2. **布尔值检查使用属性而非方法调用**
   ```python
   # ✓ 好
   if result.success:
       ...

   # ✗ 避免
   if result.get('success'):
       ...
   if result.is_success():
       ...
   ```

3. **类设计满足单一职责原则**
   ```python
   # ✓ 好 - 每个类职责清晰
   class DocumentFetcher:
       """只负责文档获取"""

   class AuditOrchestrator:
       """只负责流程编排"""

   # ✗ 避免 - 职责混杂
   class AuditManager:
       """既负责流程又负责获取文档又负责存储"""
   ```

### API 设计原则

1. **把复杂留给自己，把简单留给用户**
   ```python
   # ✓ 好 - 用户只需提供 URL
   def execute_audit(document_url: str) -> AuditResult:
       document_content = fetch_feishu_document(document_url)
       ...

   # ✗ 避免 - 把复杂性转嫁给用户
   def execute_audit(document_url: str, document_content: str) -> AuditResult:
       """用户需要自己获取文档内容"""
   ```

2. **异常类具体化，避免过于宽泛**
   ```python
   # ✓ 好 - 具体异常
   class DocumentFetchError(ActuarySleuthException):
       """文档获取失败异常"""
       pass

   class DatabaseError(ActuarySleuthException):
       """数据库操作异常"""
       pass

   # ✗ 避免 - 过于宽泛
   raise Exception("Failed")
   raise RuntimeError("Error")
   ```

3. **异常类归档到对应模块**
   ```python
   # lib/exceptions.py - 基础异常定义
   class ActuarySleuthException(Exception):
       """项目基类异常"""

   class DatabaseError(ActuarySleuthException):
       """数据库异常"""

   class DatabaseException(ActuarySleuthException):
       """数据库操作异常（带操作详情）"""

   # lib/common/exceptions.py - 重新导出常用异常
   from lib.exceptions import ActuarySleuthException, DatabaseError, ...

   # lib/preprocessing/exceptions.py - 预处理模块异常
   class DocumentFetchError(ActuarySleuthException):
       """文档获取失败异常"""
   ```

### 模块组织

1. **lib/common/** - 通用数据模型和工具
   - `models.py` - Product, ProductCategory, AuditRequest 等基础模型
   - `audit.py` - PreprocessedResult, CheckedResult, AnalyzedResult, EvaluationResult
   - `product.py` - 产品信息处理
   - `database.py` - 数据库操作（get_connection等）
   - `exceptions.py` - 通用异常重新导出
   - `constants.py` - 所有常量（DocumentValidation, AuditConstants, PreprocessingConstants等）

2. **lib/audit/** - 审核模块
   - `auditor.py` - 合规审核器
   - `prompts.py` - 审核提示词
   - `evaluation.py` - 评分和综合评估逻辑

3. **lib/preprocessing/** - 预处理模块
   - `document_fetcher.py` - 文档获取
   - `document_extractor.py` - 提取器入口
   - `fast_extractor.py` - 规则提取
   - `dynamic_extractor.py` - LLM提取
   - 其他预处理子模块...

4. **lib/reporting/** - 报告生成
   - `template.py` - 报告模板
   - `model.py` - EvaluationContext
   - `export/` - 导出功能

5. **避免过度抽象** - 转换逻辑优先内联到使用处

### 导入规范

```python
# 标准库
import sys
from pathlib import Path

# 第三方库
import ollama

# 项目内部 - 按层级排序
from lib.common import database as db
from lib.common.models import Product
from lib.common.audit import PreprocessedResult
from lib.preprocessing.document_fetcher import fetch_feishu_document
```

**禁止**:
- `from lib.exceptions import *` - 通配符导入（仅在特定场景使用）
- `from module import name1, name2, name3, name4, name5` - 超过3个导入时分行

### 数据模型设计

1. **数据类使用 frozen dataclass 确保不可变性**
   ```python
   @dataclass(frozen=True)
   class PreprocessedResult:
       audit_id: str
       document_url: str
       timestamp: datetime
       product: Product
       clauses: List[Dict[str, Any]]
       pricing_params: Dict[str, Any]
   ```

2. **模型元数据包含必要的上下文信息**
   ```python
   # ✓ 好 - 元数据包含 document_url
   product = Product(
       name="xxx",
       company="xxx",
       category=ProductCategory.HEALTH,
       document_url=document_url,  # 保留来源信息
   )
   ```

3. **避免不必要的类型转换**
   ```python
   # ✓ 好 - 直接使用原始数据
   result = PreprocessedResult(
       product=Product.from_dict(product_info),
       ...
   )

   # ✗ 避免 - 中间转换
   product_dict = result.get('product_info')
   product = Product.from_dict(product_dict)
   ```

---

## 核心流程

### 审核流程 (scripts/audit.py)

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
- 可以添加新的生成方法如 `_generate_xxx_section`

### 添加新的 LLM 客户端

1. 在 `lib/llm/` 创建新的客户端文件（如 `deepseek.py`）
2. 实现基础接口 `lib/llm/base.py`
3. 在 `lib/llm/factory.py` 注册客户端
4. 在 `scripts/config/settings.json` 配置模型参数

---

## 测试

```bash
# 运行单个脚本
python3 scripts/audit.py --documentUrl <feishu_url>

# 运行测试
pytest scripts/tests/

# 运行测试并显示覆盖率
pytest scripts/tests/ --cov=lib --cov-report=html

# 类型检查
mypy scripts/lib/

# 测试必须通过才能提交代码
```

---

## 配置

配置文件位于 `scripts/config/settings.json`，或通过环境变量覆盖。

**配置结构**:
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
5. **数据模型**：不可变性、包含元数据、避免不必要转换、避免深层嵌套
6. **模块组织**：不新增 service 包、复用现有 lib/ 结构、通用模块归档到 lib/common
7. **测试要求**：测试未通过不允许提交代码
8. **代码注释**：代码自注释，不写冗余注释，移除向后兼容代码，不体现演进过程
9. **时间处理**：不通过日志获取 timestamp，使用 `lib/common/date_utils` 工具类
10. **数据转换**：避免不必要的类型转换，优先使用原始数据结构
11. **职责下沉**：计算逻辑下沉到数据对象（如 `result.get_summary()`），不在调用处计算
12. **参数精简**：避免冗余参数，优先使用数据中已有的元数据
13. **函数命名**：模块前缀 + 功能动词（如 `execute_check`），变量名准确反映数据含义
14. **代码紧凑**：移除不必要空行，代码结构紧凑
15. **对象传递**：logger 等对象优先传递，避免重复获取
16. **异常统一**：使用 lib/exceptions.py 定义基础异常，lib/common/exceptions.py 重新导出
17. **常量集中**：所有常量归档到 lib/common/constants.py，按类别组织
18. **配置管理**：使用 lib/config.py 的线程安全单例，不要创建新的配置管理器

---

## 最近变更

### 2025-03-21 - 代码结构重组
**Commit**: `2844889 refactor: reorganize code structure and improve module organization`

**文件移动**:
- `lib/logger.py` → `lib/common/logger.py`
- `lib/id_generator.py` → `lib/common/id_generator.py`
- `lib/evaluation.py` → `lib/audit/evaluation.py`
- `lib/vector_store.py` → `lib/rag_engine/vector_store.py`

**文件删除**:
- `lib/ollama.py` (重复，已使用 `lib/llm/ollama.py`)
- `lib/constants.py` (已合并到 `lib/common/constants.py`)

**代码质量修复**:
- 修复 lib/__init__.py 中的双重函数调用
- 移除 lib/common/constants.py 中的 sys.path 操作
- 简化 lib/common/exceptions.py 异常导入链
- 添加 DatabaseError 类到 lib/exceptions.py

**导入更新**:
- 所有引用移动文件的代码已更新
- 入口点（audit.py, preprocess.py等）导入已更新

**测试**: 159 passed, 1 skipped, 50.90% coverage

### 2025-03-21 - 质量改进
**Commit**: `9493276 feat: implement comprehensive code quality and security improvements`

**新增文件**:
- `lib/common/cache.py` - 缓存管理器
- `lib/common/constants.py` - 常量定义
- `lib/common/logging_config.py` - 日志配置
- `lib/middleware/base.py` - 中间件基类
- `mypy.ini` - 类型检查配置
- `.pre-commit-config.yaml` - Pre-commit钩子

**测试**: 159 passed, 1 skipped, 48.56% coverage

---

## 待办事项 (TODO)

- [ ] 提升测试覆盖率到 70%
- [ ] 添加更多集成测试
- [ ] 完善异常处理的单元测试
- [ ] 考虑引入 API 版本控制（如果对外提供API）
