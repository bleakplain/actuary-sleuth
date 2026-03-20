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
│       │   └── database.py    # 数据库操作
│       ├── reporting/         # 报告生成
│       │   ├── template.py    # 报告模板
│       │   ├── model.py       # 报告数据模型
│       │   ├── export/        # 文档导出
│       │   └── strategies/    # 整改策略
│       ├── config.py          # 配置管理
│       ├── exceptions.py      # 异常定义
│       ├── logger.py          # 日志工具
│       └── ...
├── data/                     # 数据目录
└── CLAUDE.md                 # 本文档
```

## 编码规范

### 命名约定

1. **函数名使用业务语义，而非技术实现**
   ```python
   # ✓ 好 - 业务语义
   save_audit_record()
   fetch_document_content()
   calculate_result()

   # ✗ 避免 - 技术实现别名
   save_audit_record as db_save
   fetch_document_content as fetch
   calculate_result as compute
   ```

2. **私有函数使用前缀 `_`**
   ```python
   def _managed_query(...):  # 内部使用
   def managed_query(...):   # 公开 API
   ```

3. **常量使用 UPPER_CASE**
   ```python
   MAX_VIOLATIONS = 100
   DEFAULT_TIMEOUT = 30
   ```

### 模块组织

1. **common/** - 通用数据模型和工具
   - `models.py` - Product, ProductCategory 等基础模型
   - `audit.py` - PreprocessedResult, CheckedResult 等审核流程模型
   - `product.py` - 产品类型映射
   - `database.py` - 数据库操作

2. **reporting/** - 报告生成相关
   - `template.py` - 报告模板生成
   - `export/` - 文档导出功能

3. 避免过度抽象，转换逻辑优先内联到使用处

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
```

## 核心流程

### 审核流程 (audit.py)

```
1. 预处理 (preprocess.py)
   ↓
2. 负面清单检查 (check.py)
   ↓
3. 定价分析 (scoring.py)
   ↓
4. 综合评估
   ↓
5. 保存到数据库
   ↓
6. 导出报告 (可选)
```

### 数据流

```
DocumentContent
    ↓ (preprocess)
PreprocessedResult (Product + Clauses + PricingParams)
    ↓ (check_violations)
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
```

## 配置

配置文件位于项目根目录的 `config.yaml`（如存在），或通过环境变量覆盖。

## 注意事项

1. **不要使用技术实现的别名**：如 `db_save`, `fetch_data` 等，使用业务语义名称
2. **转换逻辑优先内联**：不要为简单的数据转换创建单独的类或模块
3. **私有函数使用 `_` 前缀**：区分公开 API 和内部实现
4. **数据库操作使用 context manager**：确保连接正确关闭
