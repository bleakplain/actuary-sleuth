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

## 系统架构

```
actuary-sleuth/
├── scripts/           # 核心脚本
│   ├── init_db.py     # 数据库初始化
│   ├── import_regs.py # 法规导入
│   ├── preprocess.py  # 文档预处理
│   ├── check.py       # 负面清单检查
│   ├── scoring.py     # 定价分析
│   ├── report.py      # 报告生成
│   ├── audit.py       # 综合审核（主流程）
│   └── lib/           # 核心库
│       ├── db.py          # 数据库操作
│       ├── ollama.py      # LLM 接口
│       └── vector_store.py # 向量检索
├── data/              # 数据目录
│   ├── actuary.db     # SQLite 数据库
│   └── lancedb/       # 向量数据库
├── references/        # 法规文档
└── skill.json         # 技能配置
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
pip install lancedb pyarrow requests
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

### 3. 文档预处理

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

### 4. 负面清单检查

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

### 5. 定价合理性分析

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

### 6. 报告生成

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
```

### 7. 综合审核（完整流程）

```bash
# 创建输入文件
cat > input.json << EOF
{
  "documentContent": "# 保险产品\n\n第一条：...",
  "documentUrl": "https://example.com/policy.pdf",
  "auditType": "full"
}
EOF

# 执行完整审核
python scripts/audit.py --input input.json
```

审核流程：
1. 文档预处理
2. 负面清单检查
3. 定价合理性分析
4. 生成审核报告
5. 保存审核记录

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

### 数据库路径

- SQLite: `/root/.openclaw/workspace/skills/actuary-sleuth/data/actuary.db`
- LanceDB: `/root/.openclaw/workspace/skills/actuary-sleuth/data/lancedb`

### 法规文档目录

`/root/.openclaw/workspace/skills/actuary-sleuth/references/`

## API 文档

### 核心模块

#### lib/db.py

数据库操作模块，提供以下函数：

- `get_connection()`: 获取数据库连接
- `find_regulation(article_number)`: 精确查找法规
- `search_regulations(keyword)`: 关键词搜索
- `get_negative_list()`: 获取负面清单
- `save_audit_record(record)`: 保存审核记录

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

### 脚本接口

所有脚本遵循统一接口规范：

```bash
python script_name.py --input input.json [--config config.json]
```

输入格式：JSON
输出格式：JSON（stdout）或错误（stderr）

## 技术特点

1. **模块化设计**: 每个脚本独立运行，易于集成和扩展
2. **统一接口**: 所有脚本使用相同的输入输出格式
3. **错误处理**: 完善的异常处理和错误报告
4. **向量检索**: 基于 LanceDB 的高性能语义搜索
5. **本地化部署**: 支持 Ollama 本地 LLM，无需云端 API

## 开发说明

### 添加新脚本

1. 使用 `template.py` 作为模板
2. 实现 `execute(params)` 函数
3. 遵循统一的输入输出格式

### 添加负面清单规则

通过数据库添加规则：

```python
from scripts.lib import db

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

db.add_negative_list_rule(rule)
```

## 许可证

本项目遵循相关开源许可证。

## 联系方式

如有问题或建议，请通过项目仓库提交 Issue。
