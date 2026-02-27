---
name: actuary-sleuth
description: Use when reviewing insurance product clauses for compliance, checking against regulatory negative lists, calculating pricing reasonableness, or querying insurance regulations and laws. Use for精算师日常评审工作 including新产品条款审核、法规查询、负面清单检查、定价合理性计算和评审报告生成.
version: 3.0.0
author: OpenClaw
metadata:
  openclaw:
    emoji: "📊"
    requires:
      bins: ["python3", "node", "openclaw"]
      env: ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_TARGET_GROUP_ID"]
    primaryEnv: "FEISHU_APP_ID"
---

# Actuary Sleuth Skill

## Overview

Actuary Sleuth is an insurance product compliance audit system that helps actuaries review insurance clauses, check against negative lists, analyze pricing reasonableness, and query regulations efficiently.

面向精算师的专业产品评审辅助系统，帮助精算师更高效地评审保险产品条款。通过自动化检查和智能检索提升评审质量和效率，减少人工翻阅法规文件和负面清单的时间。

**🎯 核心特性：自动化审核 + Word 文档导出 + 飞书推送**
- 自动执行完整的合规性审核流程
- 自动生成专业 Word 审核报告
- 自动推送报告到飞书群组
- 用户无需额外操作，系统主动交付完整审核结果

## Tools

### audit_document

Audits an insurance product document for compliance issues.

**Script:** `scripts/audit.py`

**Usage:**
```bash
python3 scripts/audit.py --documentUrl <飞书文档URL>
```

**Parameters:**
- `--documentUrl` (string, required): 飞书文档URL

**Workflow:**
```
1. 从飞书获取文档内容
2. 文档预处理和结构化提取
3. 负面清单检查
4. 定价合理性分析（死亡率、利率、费用率）
5. 综合评分和合规评级
6. 生成 Word 审核报告
7. 推送报告到飞书群组
8. 保存审核记录
```

**Returns:**
```json
{
  "success": true,
  "audit_id": "AUD-20260215-001",
  "violations": [...],
  "pricing": {
    "mortality": {"value": 0.0005, "benchmark": 0.00048, "deviation": 4.2, "reasonable": true},
    "interest": {"value": 0.035, "benchmark": 0.035, "deviation": 0.0, "reasonable": true},
    "expense": {"value": 0.15, "benchmark": 0.12, "deviation": 25.0, "reasonable": false}
  },
  "score": 75,
  "grade": "合格",
  "summary": {"high": 2, "medium": 1, "low": 0},
  "docx_export": {
    "success": true,
    "file_path": "/tmp/审核报告.docx",
    "file_size": 12345,
    "title": "产品名称_审核报告_20260227-143000"
  },
  "feishu_push": {
    "success": true,
    "message_id": "oc_xxx",
    "group_id": "oc_xxx"
  }
}
```

### query_regulation

Queries insurance regulations and laws.

**Script:** `scripts/query.py`

**Usage:**
```bash
python3 scripts/query.py --query <查询内容> [--searchType <类型>]
```

**Parameters:**
- `--query` (string, required): 查询内容
- `--searchType` (string, optional): `exact`(精确)、`semantic`(语义)、`hybrid`(混合，默认)

**Returns:**
```json
{
  "success": true,
  "query": "保险法第十六条",
  "search_type": "hybrid",
  "results": [
    {
      "type": "exact",
      "content": "订立保险合同，保险人就保险标的或者被保险人的有关情况提出询问的，投保人应当如实告知...",
      "law_name": "保险法",
      "article_number": "第十六条",
      "category": "如实告知义务",
      "score": 1.0
    }
  ],
  "count": 1
}
```

### check_negative_list

Checks product clauses against the negative list.

**Script:** `scripts/check.py`

**Usage:**
```bash
python3 scripts/check.py --clauses <条款文本>
```

**Parameters:**
- `--clauses` (string, required): 条款文本，多行输入每行一个条款

**Returns:**
```json
{
  "success": true,
  "violations": [...],
  "count": 1,
  "summary": {"high": 1, "medium": 0, "low": 0}
}
```

### pricing_analysis

Analyzes pricing reasonableness for insurance products.

**Script:** `scripts/scoring.py`

**Usage:**
```bash
python3 scripts/scoring.py --input <JSON参数>
```

**Input Format:**
```json
{
  "pricing_params": {
    "mortality_rate": 0.0005,
    "interest_rate": 0.035,
    "expense_rate": 0.12
  },
  "product_type": "life"
}
```

**Returns:**
```json
{
  "success": true,
  "pricing": {
    "mortality": {"value": 0.0005, "benchmark": 0.0005, "reasonable": true},
    "interest": {"value": 0.035, "benchmark": 0.035, "reasonable": true},
    "expense": {"value": 0.12, "benchmark": 0.12, "reasonable": true}
  },
  "overall_score": 100,
  "is_reasonable": true
}
```

## Configuration

### scriptsPath
Path to Python scripts directory.
- **Default:** `./scripts`
- **Type:** string

### dataPath
Path to data directory containing SQLite and LanceDB databases.
- **Default:** `./data`
- **Type:** string

### pythonEnv
Python environment to use for script execution.
- **Default:** `python3`
- **Type:** string

### lancedbUri
URI for LanceDB vector database.
- **Default:** `./data/lancedb`
- **Type:** string

### ollamaHost
Host URL for Ollama LLM service.
- **Default:** `http://localhost:11434`
- **Type:** string

### ollamaModel
Model name for text generation.
- **Default:** `qwen2:7b`
- **Type:** string

### ollamaEmbedModel
Model name for text embeddings.
- **Default:** `nomic-embed-text`
- **Type:** string

### openclawBin
OpenClaw binary path for Feishu integration.
- **Default:** `/usr/bin/openclaw`
- **Type:** string

### feishuTargetGroupId
Feishu group ID for report pushing.
- **Required:** Yes
- **Type:** string
- **Environment Variable:** `FEISHU_TARGET_GROUP_ID`

## Requirements

### Network
- **feishu**: Access to Feishu API for document operations
- **ollama**: (Optional) For semantic search and embeddings

### File Permissions
- **read**: Read access to document files and reference materials
- **write**: Write access to data directory for database operations

### Dependencies
- **python3**: Python 3.8 or higher
- **sqlite3**: SQLite database (usually bundled with Python)
- **lancedb**: Vector database for semantic search
- **ollama**: (Optional) Local LLM service for embeddings
- **node**: Node.js for Word document generation
- **docx**: npm package for Word document generation (global install required)
- **openclaw**: For Feishu integration

### Installation

```bash
# Python dependencies
pip install lancedb pyarrow requests

# Node.js dependencies (global)
npm install -g docx

# Initialize database
python3 scripts/init_db.py

# Import regulations
python3 scripts/import_regs.py --refs-dir ../references --no-vectors
```

## When to Use

**Use when:**
- 审核新产品保险条款（需要检查负面清单、法规合规性）
- 查询保险监管法规（保险法、条款费率管理办法等）
- 检查产品是否违反负面清单（22个违规点）
- 计算定价合理性（死亡率、利率、费用率对比行业标准）
- 生成 Word 审核报告并推送飞书

**💡 默认行为：完整审核流程**
- 提供产品文档后，系统自动执行完整审核流程
- 生成 Word 审核报告并推送到飞书群组
- 用户无需额外说明，系统默认执行完整交付流程

**NOT for:**
- 最终合规决策（应以监管部门官方解释为准）
- 复杂法律问题（需咨询专业法律意见）
- 监管政策解读（参考仅作辅助）

## Quick Reference

| 场景 | 输入 | 输出 | 优先级 |
|------|------|------|--------|
| 产品文档审核 | 飞书文档URL | 结构化产品数据 + 违规检查结果 + **Word报告** + **飞书推送** | P0 |
| 负面清单检查 | 产品条款 | 22个违规点检查结果 + 整改建议 | P0 |
| 法规快速查询 | 条款编号/关键词 | 完整条款内容 + 标准引用格式 | P0 |
| 定价合理性计算 | 定价参数 | 偏差分析 + 合理性判断 | P0 |
| Word报告生成 | 审核结果 | Word文档(.docx) + 飞书群组推送 | P0 |
| 智能检索 | 自然语言描述 | 相关法规条款 | P1 |

## Core Workflow

### 完整评审流程

```
1. 接收产品文档（飞书URL）
   ↓
2. 自动解析文档（提取结构、识别类型）
   ↓
3. 负面清单检查（22个违规点规则匹配）
   ↓
4. 定价合理性分析（对比行业标准）
   ↓
5. 法规匹配（相关条款引用）
   ↓
6. 计算综合评分和合规评级
   ↓
7. 生成 Word 审核报告
   ↓
8. 📄 推送 Word 报告到飞书群组
   ↓
9. ✅ 用户在飞书中收到审核结果
```

### 快速查询流程

```
1. 输入查询（条款编号/关键词/自然语言）
   ↓
2. 检索知识库（倒排索引/向量检索）
   ↓
3. 返回结果（完整条款 + 标准引用）
```

## Knowledge Base (references/)

本技能内置完整的精算审计法规知识库（16份法规文档）：

### 基础法规 (P0)
- `01_保险法相关监管规定.md` - 保险法核心条款
- `02_负面清单.md` - 22个违规点详细说明
- `03_条款费率管理办法.md` - 费用率监管规定
- `04_信息披露规则.md` - 信息披露要求

### 产品开发规范 (P0)
- `05_健康保险产品开发.md` - 健康险开发规范
- `06_普通型人身保险.md` - 普通型产品规定
- `07_分红型人身保险.md` - 分红型产品规定
- `08_短期健康保险.md` - 短期健康险规定
- `09_意外伤害保险.md` - 意外险规定
- `10_互联网保险产品.md` - 互联网产品规范
- `11_税优健康险.md` - 税优健康险规定
- `12_万能型人身保险.md` - 万能险规定
- `13_其他险种产品.md` - 其他险种规定
- `14_综合监管规定.md` - 综合监管要求

### 参考手册
- `产品开发相关法律法规手册2025.12.md` - 完整法规手册

## Scoring System

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

## Negative List Rules

22个违规点涵盖：
- 条款表述（冗长、不统一、不集中）
- 免责条款（位置不显著、表述不清）
- 保险责任（模糊表述、范围不明）
- 理赔条件（设置不合理障碍）
- 定价合理性（死亡率、利率、费用率异常）

## Common Mistakes

| 错误 | 后果 | 正确做法 |
|------|------|----------|
| 直接使用自动化结果作为最终决策 | 合规风险 | 自动化结果仅供参考，需人工复核 |
| 忽略法规版本 | 使用过时规定 | 定期检查references/目录更新情况 |
| 过度依赖评分系统 | 误判风险 | 评分仅作参考，需结合专业判断 |
| 未记录审计过程 | 无法追溯 | 保存完整审计日志 |

## Limitations

1. 本技能仅作为评审辅助工具
2. 实际决策应以监管部门官方解释为准
3. 复杂问题应咨询专业法律和精算意见
4. 监管规定可能更新，请定期检查最新版本
5. 评分和建议仅供参考，最终判断需专业人员

## Related Documentation

- README.md: 项目说明和详细文档
- CHANGELOG.md: 版本更新记录
- references/: 法规文档知识库
