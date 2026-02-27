# Actuary Sleuth

保险产品合规性审核智能系统 - 基于规则引擎和向量检索的自动化审核工具

## 项目概述

Actuary Sleuth 是一个专业的保险产品合规性审核系统，通过自动化工具分析保险产品条款，检测潜在的合规风险，并提供详细的审核报告。系统整合了负面清单检查、定价合理性分析和智能报告生成功能。

### 主要功能

- **负面清单检查**: 基于监管规则自动检测产品条款中的违规内容
- **定价合理性分析**: 分析定价参数（死亡率、利率、费用率）是否符合监管标准
- **文档预处理**: 自动解析保险产品文档，提取结构化信息
- **智能报告生成**: 生成详细的合规性审核报告，包含违规详情和改进建议
- **向量检索**: 基于 LanceDB 的语义搜索，快速查找相关法规条款
- **审核历史**: 保存审核记录，支持历史查询
- **Word 文档导出**: 支持将审核报告导出为 Word (.docx) 格式文档
- **飞书推送**: 自动推送生成的报告到指定飞书群组

## 系统架构

```
actuary-sleuth/
├── scripts/              # 核心脚本
│   ├── init_db.py        # 数据库初始化
│   ├── import_regs.py    # 法规导入
│   ├── preprocess.py     # 文档预处理
│   ├── check.py          # 负面清单检查
│   ├── scoring.py        # 定价分析
│   ├── query.py          # 法规查询
│   ├── audit.py          # 综合审核（主流程）
│   └── lib/              # 核心库
│       ├── config.py              # 配置管理
│       ├── database.py            # 数据库操作
│       ├── exceptions.py          # 异常定义
│       ├── id_generator.py        # ID 生成器
│       ├── logger.py              # 日志记录
│       ├── ollama.py              # LLM 接口
│       ├── reporting/             # 报告生成模块
│       │   ├── model.py           # 数据模型
│       │   ├── template/          # 模板方法模式
│       │   │   └── report_template.py
│       │   ├── export/            # 文档导出
│       │   │   ├── docx_exporter.py    # Word 导出器
│       │   │   ├── docx_generator.py   # Word 生成器（内部）
│       │   │   ├── feishu_pusher.py    # 飞书推送器（内部）
│       │   │   ├── constants.py        # Docx 常量
│       │   │   ├── result.py           # 结果类
│       │   │   └── validation.py       # 输入验证
│       │   └── strategies/        # 整改策略模式
│       │       └── remediation/
│       └── vector_store.py        # 向量检索
├── data/                 # 数据目录
│   ├── actuary.db        # SQLite 数据库
│   └── lancedb/          # 向量数据库
├── references/           # 法规文档
├── tests/                # 测试目录
│   ├── unit/             # 单元测试
│   └── integration/      # 集成测试
└── skill.json            # 技能配置
```

## 安装说明

### 环境要求

- Python 3.8+
- SQLite3
- Node.js (用于 Word 文档生成)
- Ollama (可选，用于向量检索)

### 安装步骤

1. **克隆项目**
```bash
cd /root/.openclaw/workspace/skills/actuary-sleuth
```

2. **安装 Python 依赖**
```bash
pip install lancedb pyarrow requests pytest
```

3. **安装 Node.js 依赖**（Word 文档生成）
```bash
npm install -g docx
# 或使用全局 node_modules
sudo npm install -g docx
```

4. **安装 OpenClaw**（飞书推送）
```bash
# 确保 openclaw 已安装
which openclaw
# 默认路径: /usr/bin/openclaw
```

5. **初始化数据库**
```bash
cd scripts
python init_db.py
```

6. **导入法规数据**（可选）
```bash
# 导入所有法规（不含向量）
python import_regs.py --refs-dir ../references --no-vectors

# 导入单个法规（含向量，需要 Ollama）
python import_regs.py --refs-dir ../references --file insurance_law.md
```

7. **配置 Ollama**（可选，用于向量检索）
```bash
# 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 拉取嵌入模型
ollama pull nomic-embed-text

# 启动服务
ollama serve
```

## 使用指南

### 1. 数据库初始化

```bash
python scripts/init_db.py
```

初始化 SQLite 数据库，创建以下表：
- `regulations`: 法规条款表
- `negative_list`: 负面清单规则表
- `audit_history`: 审核历史记录表

### 2. 导入法规数据

```bash
# 导入所有法规（不需要 Ollama）
python scripts/import_regs.py --refs-dir ../references --no-vectors

# 导入单个文件
python scripts/import_regs.py --refs-dir ../references --file sample.md

# 含向量导入（需要 Ollama 服务）
python scripts/import_regs.py --refs-dir ../references
```

### 3. 法规查询

```bash
# 关键词搜索
python scripts/query.py --query "保险法第十六条"

# 混合搜索（关键词 + 向量）
python scripts/query.py --query "等待期规定" --search-type hybrid
```

### 4. 文档预处理

```bash
# 创建输入文件
cat > input.json << EOF
{
  "documentContent": "产品名称：XXX保险\n第一条：...",
  "documentUrl": "https://example.com/policy.pdf",
  "documentType": "insurance_policy"
}
EOF

# 执行预处理
python scripts/preprocess.py --input input.json
```

输出示例：
```json
{
  "success": true,
  "preprocess_id": "PRE-20240215-123456",
  "product_info": {
    "product_name": "XXX保险",
    "insurance_company": "XXX保险公司",
    "product_type": "寿险"
  },
  "clauses": ["第一条：...", "第二条：..."],
  "pricing_params": {
    "interest_rate": 0.035,
    "expense_rate": 0.12
  }
}
```

### 5. 负面清单检查

```bash
# 创建输入文件
cat > input.json << EOF
{
  "clauses": [
    "保险公司不承担任何责任",
    "本产品收益率为 10%"
  ]
}
EOF

# 执行检查
python scripts/check.py --input input.json
```

输出示例：
```json
{
  "success": true,
  "violations": [
    {
      "clause_index": 0,
      "rule": "NL-001",
      "description": "免责条款不明确",
      "severity": "high",
      "remediation": "明确列出免责情形"
    }
  ],
  "summary": {
    "high": 1,
    "medium": 0,
    "low": 0
  }
}
```

### 6. 定价合理性分析

```bash
# 创建输入文件
cat > input.json << EOF
{
  "pricing_params": {
    "mortality_rate": 0.0005,
    "interest_rate": 0.035,
    "expense_rate": 0.12
  },
  "product_type": "life"
}
EOF

# 执行分析
python scripts/scoring.py --input input.json
```

输出示例：
```json
{
  "success": true,
  "pricing": {
    "mortality": {
      "value": 0.0005,
      "benchmark": 0.0005,
      "reasonable": true
    },
    "interest": {
      "value": 0.035,
      "benchmark": 0.035,
      "reasonable": true
    }
  },
  "overall_score": 100,
  "is_reasonable": true
}
```

### 7. 综合审核（完整流程）

```bash
# 执行完整审核（需要飞书文档 URL）
python scripts/audit.py --documentUrl "https://example.feishu.cn/docx/xxx"
```

审核流程：
1. 从飞书获取文档内容
2. 文档预处理
3. 负面清单检查
4. 定价合理性分析
5. 生成审核报告
6. 导出 Word 文档
7. 推送到飞书群组
8. 保存审核记录

## Word 文档导出

### 功能特性

- **基于 docx-js**: 使用 JavaScript 生成标准 Word 文档，完美支持中文
- **专业格式**: 包含标题、表格、样式等完整格式
- **可配置**: 支持自定义输出目录、验证选项、超时设置
- **飞书推送**: 自动将生成的文档推送到指定群组

### 使用示例

```python
from lib.reporting.export import DocxExporter, export_docx
from lib.reporting.model import EvaluationContext

# 方式一：使用便捷函数
result = export_docx(
    context=context,
    title="审核报告",
    validate=False,
    auto_push=True
)

# 方式二：使用 DocxExporter 类
exporter = DocxExporter(
    output_dir="./reports",
    validate=False,
    auto_push=True
)
result = exporter.export(context, "审核报告")

# 仅生成文档（不推送）
result = exporter.generate_only(context, "审核报告")

# 仅推送已有文档
result = exporter.push_only("/path/to/docx.docx", "标题", "消息")
```

### 配置选项

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `output_dir` | str | `/tmp` | 输出目录 |
| `validate` | bool | `False` | 是否验证生成的文档 |
| `auto_push` | bool | `True` | 是否自动推送到飞书 |
| `execution_timeout` | int | `30` | 文档生成超时（秒） |
| `validation_timeout` | int | `30` | 验证超时（秒） |

### 飞书推送配置

在 `config/settings.json` 中配置：

```json
{
  "feishu": {
    "app_id": "your_app_id",
    "app_secret": "your_app_secret",
    "target_group_id": "oc_xxxxxxxxxxxxxxx"
  },
  "openclaw": {
    "bin": "/usr/bin/openclaw"
  }
}
```

### 报告内容结构

生成的 Word 文档包含以下部分：

1. **文档标题** - 居中显示的报告标题
2. **产品信息** - 产品名称、类型、保险公司、版本号等
3. **审核评分** - 综合评分、合规评级、违规统计
4. **定价分析** - 各项定价参数的合理性分析
5. **违规详情** - 按严重程度分组的违规列表
   - 高危违规
   - 中危违规
   - 低危违规
6. **审核依据** - 相关法规条款列表
7. **报告生成时间** - 页脚显示生成时间

### 内部实现

报告导出模块采用三层架构：

```
DocxExporter (公共接口)
    ├── export() - 完整导出流程
    ├── generate_only() - 仅生成文档
    └── push_only() - 仅推送文档

_DocxGenerator (内部实现)
    ├── generate() - 生成 Word 文档
    ├── _generate_docx_js_code() - 生成 JavaScript 代码
    ├── _execute_docx_generation() - 执行 Node.js 生成
    └── _validate_docx() - 验证生成的文档

_FeishuPusher (内部实现)
    ├── push() - 推送文档到飞书
    ├── push_text() - 推送文本消息
    └── _execute_openclaw_command() - 执行 OpenClaw 命令
```

### 辅助模块

- **constants.py**: Docx 相关常量（单位、页面、样式等）
- **result.py**: 统一的结果封装类
- **validation.py**: 输入验证工具

## 报告生成模块

### 架构设计

报告生成采用 **模板方法模式** 和 **策略模式**：

```
ReportGenerationTemplate (模板编排)
    ├── generate() - 模板方法，定义报告生成流程
    ├── _calculate_score() - 计算综合评分
    ├── _calculate_grade() - 确定合规评级
    ├── _summarize_violations() - 统计违规摘要
    ├── _generate_content() - 生成文本内容
    └── _generate_blocks() - 生成飞书块格式

RemediationStrategies (策略模式)
    ├── WaitingPeriodRemediationStrategy - 等待期整改策略
    └── ExemptionClauseRemediationStrategy - 免责条款整改策略

EvaluationContext (数据载体)
    ├── violations - 违规记录列表
    ├── pricing_analysis - 定价分析结果
    ├── product - 产品信息 (_InsuranceProduct)
    ├── score, grade - 计算结果
    ├── summary - 违规摘要
    └── regulation_basis - 审核依据
```

### 使用示例

```python
from lib.reporting.template import ReportGenerationTemplate
from lib.reporting.model import EvaluationContext

template = ReportGenerationTemplate()
result = template.generate(
    violations=violations,
    pricing_analysis=pricing_analysis,
    product_info=product_info
)

# 结果包含：
# - score: 综合评分 (0-100)
# - grade: 合规评级 (优秀/良好/合格/不合格)
# - summary: 违规摘要
# - content: 文本格式报告
# - blocks: 飞书块格式报告
# - metadata: 元数据
```

### 评分规则

| 评分区间 | 评级 | 说明 |
|----------|------|------|
| 90-100 | 优秀 | 产品优秀，建议快速通过 |
| 75-89 | 良好 | 产品良好，可正常上会 |
| 60-74 | 合格 | 产品合格，建议完成修改后上会 |
| 0-59 | 不合格 | 产品不合格，不建议提交审核 |

### 扣分规则

| 违规严重程度 | 扣分值 |
|--------------|--------|
| high (严重) | 10 分/项 |
| medium (中等) | 5 分/项 |
| low (轻微) | 2 分/项 |
| 定价问题 | 根据偏差程度 |

## 配置说明

### config/settings.json 配置

```json
{
  "version": "3.0.0",
  "data_paths": {
    "sqlite_db": "../../data/actuary.db",
    "lancedb_uri": "../../data/lancedb",
    "negative_list": "data/negative_list.json",
    "industry_standards": "data/industry_standards.json",
    "audit_logs": "data/audit_logs.json"
  },
  "regulation_search": {
    "data_dir": "../../references",
    "default_top_k": 5
  },
  "ollama": {
    "host": "http://localhost:11434",
    "chat_model": "qwen2:7b",
    "embed_model": "nomic-embed-text",
    "timeout": 120
  },
  "report": {
    "default_format": "docx",
    "output_dir": "./reports",
    "export_feishu": true
  },
  "feishu": {
    "app_id": "your_app_id",
    "app_secret": "your_app_secret",
    "target_group_id": "oc_xxxxxxxxxxxxxxx"
  },
  "openclaw": {
    "bin": "/usr/bin/openclaw"
  },
  "audit": {
    "scoring_weights": {
      "high": 10,
      "medium": 5,
      "low": 2
    },
    "thresholds": {
      "excellent": 90,
      "good": 75,
      "pass": 60
    }
  }
}
```

### 飞书推送配置

在 `config/settings.json` 中配置：

```json
{
  "feishu": {
    "app_id": "your_app_id",
    "app_secret": "your_app_secret",
    "target_group_id": "oc_xxxxxxxxxxxxxxx"
  }
}
```

或通过环境变量：
```bash
export FEISHU_APP_ID="your_app_id"
export FEISHU_APP_SECRET="your_app_secret"
export FEISHU_TARGET_GROUP_ID="oc_xxxxxxxxxxxxxxx"
```

### 数据库路径

- SQLite: `/root/.openclaw/workspace/skills/actuary-sleuth/data/actuary.db`
- LanceDB: `/root/.openclaw/workspace/skills/actuary-sleuth/data/lancedb`

### 法规文档目录

`/root/.openclaw/workspace/skills/actuary-sleuth/references/`

## API 文档

### 核心模块

#### lib/config.py

配置管理模块：

- `get_config()`: 获取全局配置单例
- `Config`: 配置类
  - `feishu`: 飞书配置 (FeishuConfig)
  - `report`: 报告配置 (ReportConfig)
  - `audit`: 审核配置 (AuditConfig)
  - `ollama`: Ollama 配置 (OllamaConfig)
  - `data_paths`: 数据路径配置 (DatabaseConfig)
  - `regulation_search`: 法规搜索配置 (RegulationSearchConfig)
  - `openclaw`: OpenClaw 配置 (OpenClawConfig)

#### lib/database.py

数据库操作模块：

- `get_connection()`: 获取数据库连接
- `find_regulation(article_number)`: 精确查找法规
- `search_regulations(keyword)`: 关键词搜索
- `get_negative_list()`: 获取负面清单
- `save_audit_record(record)`: 保存审核记录

#### lib/exceptions.py

异常定义模块：

- `ActuarySleuthException`: 基础异常类
- `FeishuAPIException`: 飞书 API 异常
- `ExportException`: 文档导出异常
- `MissingConfigurationException`: 缺少配置异常
- `InvalidParameterException`: 无效参数异常
- `ValidationException`: 验证失败异常

#### lib/ollama.py

Ollama LLM 接口模块：

- `OllamaClient`: Ollama 客户端类
  - `generate(prompt)`: 文本生成
  - `embed(text)`: 生成嵌入向量
  - `health_check()`: 健康检查

#### lib/vector_store.py

LanceDB 向量检索模块：

- `VectorDB`: 向量数据库管理类
  - `connect()`: 连接数据库
  - `search(query_vector, top_k)`: 向量搜索
  - `add_vectors(data)`: 添加向量数据

#### lib/reporting/model.py

数据模型：

- `_InsuranceProduct`: 保险产品信息（内部类）
- `EvaluationContext`: 评估上下文
  - `product`: 产品信息
  - `violations`: 违规列表
  - `pricing_analysis`: 定价分析
  - `score`, `grade`: 评分结果
  - `summary`: 违规摘要
  - `regulation_basis`: 审核依据

#### lib/reporting/export/

Word 文档导出模块：

- `docx_exporter.py`: Word 导出器（公共接口）
  - `DocxExporter`: 导出器类
  - `export_docx()`: 便捷函数
- `docx_generator.py`: Word 生成器（内部实现）
  - `_DocxGenerator`: 文档生成类
- `feishu_pusher.py`: 飞书推送器（内部实现）
  - `_FeishuPusher`: 推送器类
- `constants.py`: Docx 常量
  - `DocxConstants`: 常量集合
- `result.py`: 结果类
  - `ExportResult`: 通用导出结果
  - `GenerationResult`: 文档生成结果
  - `PushResult`: 推送结果
- `validation.py`: 输入验证

### 脚本接口

所有脚本遵循统一接口规范：

```bash
# 通用格式
python script_name.py --input input.json [--optional-args]

# 综合审核
python audit.py --documentUrl "https://..."
```

输入格式：JSON
输出格式：JSON（stdout）或错误（stderr）

## 测试

### 运行测试

```bash
# 进入脚本目录
cd scripts

# 运行所有测试
python -m pytest ../tests -v

# 运行单元测试
python -m pytest ../tests/unit -v

# 运行集成测试
python -m pytest ../tests/integration -v

# 查看测试覆盖率
python -m pytest ../tests --cov=lib --cov-report=html
```

### 测试覆盖

当前测试覆盖：
- 总测试数：96 个
- 通过率：100%
- 单元测试：69 个
- 集成测试：27 个

## 技术特点

1. **模块化设计**: 每个脚本独立运行，易于集成和扩展
2. **设计模式**: 模板方法模式、策略模式、外观模式
3. **统一接口**: 所有脚本使用相同的输入输出格式
4. **异常处理**: 完善的异常体系和错误报告
5. **向量检索**: 基于 LanceDB 的高性能语义搜索
6. **本地化部署**: 支持 Ollama 本地 LLM，无需云端 API
7. **类型安全**: 完善的类型提示和数据模型
8. **测试覆盖**: 全面的单元测试和集成测试
9. **Word 文档**: 基于 docx-js 生成标准 Word 文档，完美支持中文
10. **飞书集成**: 通过 OpenClaw 无缝集成飞书推送

## 开发说明

### 添加新脚本

1. 使用 `template.py` 作为模板
2. 实现 `execute(params)` 函数
3. 遵循统一的输入输出格式

### 添加负面清单规则

通过数据库添加规则：

```python
from scripts.lib import database

rule = {
    'id': 'NL-XXX',
    'rule_number': '规则编号',
    'description': '违规描述',
    'severity': 'high',
    'category': '分类',
    'remediation': '整改建议',
    'keywords': ['关键词1', '关键词2'],
    'patterns': ['正则表达式1']
}

database.add_negative_list_rule(rule)
```

### 添加整改策略

1. 在 `lib/reporting/strategies/remediation/` 下创建新策略文件
2. 继承 `RemediationStrategy` 基类
3. 实现 `can_handle()` 和 `get_remediation()` 方法
4. 在 `RemediationStrategies` 中注册新策略

```python
from lib.reporting.strategies import RemediationStrategy

class CustomRemediationStrategy(RemediationStrategy):
    def can_handle(self, violation: Dict) -> bool:
        # 判断是否可以处理该违规
        return 'custom_category' in violation.get('category', '')

    def get_remediation(self, violation: Dict) -> str:
        # 返回整改建议
        return "具体的整改建议"
```

### 自定义 Word 文档样式

修改 `lib/reporting/export/constants.py` 中的常量：

```python
class DocxUnits:
    FONT_SIZE_NORMAL = 24    # 正文字号
    FONT_SIZE_HEADING1 = 32  # 一级标题字号
    FONT_SIZE_HEADING2 = 28  # 二级标题字号

class DocxStyle:
    DEFAULT_FONT = "Arial"   # 默认字体
    COLOR_GRAY = "999999"    # 灰色
```

## 更新日志

详细的版本更新记录请查看 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

本项目遵循相关开源许可证。

## 联系方式

如有问题或建议，请通过项目仓库提交 Issue。
