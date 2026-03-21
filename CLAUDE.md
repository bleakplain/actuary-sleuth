# Actuary Sleuth - AI 精算审核助手

## 项目概述

Actuary Sleuth 是一个基于 AI 的保险产品精算审核助手，能够自动解析保险产品文档、检测负面清单违规、分析定价合理性，并生成结构化的审核报告。

## 技术栈

- **Python 3.10+**
- **Ollama** - 本地 LLM 推理
- **SQLite** - 数据存储
- **飞书 API** - 文档推送

## 项目结构

```
actuary-sleuth/
├── scripts/
│   ├── audit.py              # 主审核流程
│   ├── preprocess.py         # 文档预处理
│   ├── check.py              # 负面清单检查
│   ├── scoring.py            # 定价分析
│   ├── report.py             # 报告生成
│   ├── query.py              # 法规查询
│   └── lib/
│       ├── common/            # 公共模块
│       │   ├── models.py      # 数据模型
│       │   ├── audit.py       # 审核流程模型
│       │   ├── product.py     # 产品类型映射
│       │   ├── database.py    # 数据库操作
│       │   └── exceptions.py  # 通用异常
│       ├── reporting/         # 报告生成
│       │   ├── template.py    # 报告模板
│       │   ├── model.py       # 报告数据模型
│       │   ├── export/        # 文档导出
│       │   └── strategies/    # 整改策略
│       ├── preprocessing/     # 预处理模块
│       │   └── document_fetcher.py  # 文档获取
│       ├── config.py          # 配置管理
│       ├── audit.py           # 审核流程编排
│       ├── logger.py          # 日志工具
│       └── ...
├── data/                     # 数据目录
└── CLAUDE.md                 # 本文档
```
## 项目目标
- 我们优先保证：正确性 > 可维护性 > 性能

## 代码与风格
- 只改与任务相关的文件，避免大范围重排
- 新增代码必须有对应测试（或解释为什么没有）

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

5. **常量使用 UPPER_CASE**
   ```python
   MAX_VIOLATIONS = 100
   DEFAULT_TIMEOUT = 30
   ```

### 面向对象设计原则

1. **隐藏内部实现细节，简化用户使用**
   ```python
   # ✓ 好 - 使用对象方法
   class PreprocessResult:
       def get_clauses(self) -> List[Dict]:
           return self._clauses

       def get_product_info(self) -> ProductInfo:
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
   # lib/common/exceptions.py - 通用异常
   class ActuarySleuthException(Exception):
       """项目基类异常"""

   class DatabaseError(ActuarySleuthException):
       """数据库异常"""

   class RecordNotFoundError(ActuarySleuthException):
       """记录未找到异常"""

   # lib/preprocessing/exceptions.py - 预处理模块异常
   class DocumentFetchError(ActuarySleuthException):
       """文档获取失败异常"""
   ```

### 模块组织

1. **common/** - 通用数据模型和工具
   - `models.py` - Product, ProductCategory 等基础模型
   - `audit.py` - PreprocessedResult, CheckedResult 等审核流程模型
   - `product.py` - 产品类型映射
   - `database.py` - 数据库操作
   - `exceptions.py` - 通用异常类

2. **preprocessing/** - 预处理模块
   - `document_fetcher.py` - 文档获取
   - `extractor.py` - 内容提取

3. **reporting/** - 报告生成相关
   - `template.py` - 报告模板生成
   - `export/` - 文档导出功能

4. 避免过度抽象，转换逻辑优先内联到使用处

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

### 数据模型设计

1. **数据类使用 frozen dataclass 确保不可变性**
   ```python
   @dataclass(frozen=True)
   class PreprocessedResult:
       audit_id: str
       document_url: str
       product: Product
       clauses: List[Dict[str, Any]]
   ```

2. **模型元数据包含必要的上下文信息**
   ```python
   # ✓ 好 - 元数据包含 document_url
   product_info = {
       'name': 'xxx',
       'type': 'health',
       'document_url': document_url,  # 保留来源信息
   }
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

## 核心流程

### 审核流程 (lib/audit.py)

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

## 开发指南

### 添加新的检查规则

1. 在数据库 `negative_list` 表中添加规则
2. 规则支持关键词匹配和正则表达式

### 添加新的产品类型

1. 在 `common/models.py` 的 `ProductCategory` 枚举中添加
2. 在 `common/product.py` 的 `CATEGORY_TO_SCORING` 中添加映射

### 修改报告模板

报告模板使用模板方法模式，主要修改点：
- `reporting/template.py` 的 `ReportGenerationTemplate` 类
- 可以添加新的生成方法如 `_generate_xxx_section`

## 测试

```bash
# 运行单个脚本
python3 scripts/audit.py --documentUrl <feishu_url>

# 运行测试
pytest scripts/tests/

# 测试必须通过才能提交代码
```

## 配置

配置文件位于项目根目录的 `config.yaml`（如存在），或通过环境变量覆盖。

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
