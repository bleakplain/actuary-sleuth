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
- **飞书文档导出**: 支持将审核报告导出为飞书在线文档

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
│   ├── report.py         # 报告生成
│   ├── audit.py          # 综合审核（主流程）
│   └── lib/              # 核心库
│       ├── config.py          # 配置管理
│       ├── database.py        # 数据库操作
│       ├── exceptions.py      # 异常定义
│       ├── id_generator.py    # ID 生成器
│       ├── logger.py          # 日志记录
│       ├── ollama.py          # LLM 接口
│       ├── reporting/         # 报告生成模块
│       │   ├── model.py       # 数据模型
│       │   ├── template/      # 模板方法模式
│       │   │   └── report_template.py
│       │   ├── export/        # 飞书导出
│       │   │   └── feishu.py
│       │   └── strategies/    # 整改策略模式
│       │       └── remediation/
│       └── vector_store.py    # 向量检索
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
- Ollama (可选，用于向量检索)

### 安装步骤

1. **克隆项目**
```bash
cd /root/.openclaw/workspace/skills/actuary-sleuth
```

2. **安装依赖**
```bash
pip install lancedb pyarrow requests pytest
```

3. **初始化数据库**
```bash
cd scripts
python init_db.py
```

4. **导入法规数据**（可选）
```bash
# 导入所有法规（不含向量）
python import_regs.py --refs-dir ../references --no-vectors

# 导入单个法规（含向量，需要 Ollama）
python import_regs.py --refs-dir ../references --file insurance_law.md
```

5. **配置 Ollama**（可选，用于向量检索）
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

### 7. 报告生成

```bash
# 创建输入文件
cat > input.json << EOF
{
  "violations": [...],
  "pricing_analysis": {...},
  "product_info": {
    "product_name": "XXX保险",
    "insurance_company": "XXX公司"
  }
}
EOF

# 生成报告
python scripts/report.py --input input.json

# 导出为飞书文档
python scripts/report.py --input input.json --export-feishu
```

### 8. 综合审核（完整流程）

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
6. 导出飞书文档
7. 保存审核记录

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
    ├── product - 产品信息
    ├── score, grade - 计算结果
    ├── high_violations, medium_violations, low_violations - 分组违规
    └── regulation_basis - 审核依据

FeishuExporter (飞书导出)
    ├── export() - 导出为飞书文档
    ├── _create_document() - 创建飞书文档
    └── _write_document_content() - 写入文档内容
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
| high (严重) | 20 分/项 |
| medium (中等) | 10 分/项 |
| low (轻微) | 5 分/项 |
| 定价问题 | 10 分/项 |

## 配置说明

### skill.json 配置

```json
{
  "id": "actuary-sleuth",
  "name": "Actuary Sleuth",
  "version": "3.0.0",
  "config": {
    "scriptsPath": "./scripts",
    "dataPath": "./data",
    "lancedbUri": "./data/lancedb",
    "ollamaHost": "http://localhost:11434",
    "ollamaModel": "qwen2:7b",
    "ollamaEmbedModel": "nomic-embed-text"
  }
}
```

### 飞书导出配置

在 `scripts/config/config.yaml` 中配置：

```yaml
feishu:
  enabled: true
  app_id: "your_app_id"
  app_secret: "your_app_secret"
```

或通过环境变量：
```bash
export FEISHU_APP_ID="your_app_id"
export FEISHU_APP_SECRET="your_app_secret"
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
  - `feishu`: 飞书配置
  - `report`: 报告配置
  - `audit`: 审核配置

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

#### lib/reporting/

报告生成模块：

- `model.py`: 数据模型
  - `EvaluationContext`: 评估上下文
- `template/report_template.py`: 报告生成模板
  - `ReportGenerationTemplate`: 报告生成模板类
- `export/feishu.py`: 飞书导出
  - `FeishuExporter`: 飞书文档导出器
- `strategies/remediation/`: 整改策略
  - `RemediationStrategies`: 策略管理器

### 脚本接口

所有脚本遵循统一接口规范：

```bash
# 通用格式
python script_name.py --input input.json [--optional-args]

# 报告生成
python report.py --input input.json --export-feishu --output result.json

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

# 运行特定测试文件
python -m pytest ../tests/unit/test_reporting_generator.py -v
```

### 测试覆盖

当前测试覆盖：
- 总测试数：96 个
- 通过率：100%
- 单元测试：69 个
- 集成测试：27 个

## 技术特点

1. **模块化设计**: 每个脚本独立运行，易于集成和扩展
2. **设计模式**: 模板方法模式、策略模式
3. **统一接口**: 所有脚本使用相同的输入输出格式
4. **异常处理**: 完善的异常体系和错误报告
5. **向量检索**: 基于 LanceDB 的高性能语义搜索
6. **本地化部署**: 支持 Ollama 本地 LLM，无需云端 API
7. **类型安全**: 完善的类型提示和数据模型
8. **测试覆盖**: 全面的单元测试和集成测试

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

## 版本历史

### v3.0.0 (当前版本)
- 重构报告生成模块，使用模板方法模式和策略模式
- 引入 `EvaluationContext` 数据模型
- 改进异常体系，使用特定异常类型
- 添加完整的测试覆盖
- 优化代码结构和可维护性

### v2.0.0
- 添加向量检索功能
- 支持飞书文档导出
- 添加配置管理系统

### v1.0.0
- 初始版本
- 基础审核功能

## 许可证

本项目遵循相关开源许可证。

## 联系方式

如有问题或建议，请通过项目仓库提交 Issue。
