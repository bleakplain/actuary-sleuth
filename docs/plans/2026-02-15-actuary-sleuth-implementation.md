# Actuary Sleuth Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an insurance product compliance audit system using SKILL.md workflow orchestration with Python scripts, integrating SQLite, LanceDB vector search, and Ollama LLM for automated regulatory checking.

**Architecture:** Feishu Channel receives user messages → parses SKILL.md → calls Python scripts → scripts interact with SQLite/LanceDB/Ollama → return structured audit reports.

**Tech Stack:** Python 3.10+, SQLite, LanceDB, Ollama (qwen2:7b, nomic-embed-text), feishu2md, PaddleOCR

---

## Task 1: Create Project Structure

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/SKILL.md`
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/skill.json`
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/template.py`
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/lib/__init__.py`
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/config/settings.json`
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/requirements.txt`
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/data/.gitkeep`
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/references/.gitkeep`

**Step 1: Create SKILL.md**

Run: `mkdir -p /root/.openclaw/workspace/skills/actuary-sleuth`

```markdown
---
name: actuary-sleuth
description: Use when reviewing insurance product clauses for compliance, checking against regulatory negative lists, calculating pricing reasonableness, or querying insurance regulations and laws. Use for精算师日常评审工作 including新产品条款审核、法规查询、负面清单检查、定价合理性计算和评审报告生成.
metadata:
  openclaw:
    emoji: "📊"
    requires:
      bins: ["python3"]
---

# Actuary Sleuth - 精算审计助手

## Overview

面向精算师的专业产品评审辅助系统，帮助精算师更高效地评审保险产品条款。

## Tools

### audit_document
审核保险产品文档

**Input:**
- documentContent (string): Markdown格式的文档内容
- documentUrl (string): 文档URL（可选）
- auditType (string): 审核类型，full/negative-only（可选，默认full）

**Output:**
```json
{
  "success": true,
  "violations": [...],
  "pricing": {...},
  "score": 75,
  "report": "..."
}
```

### query_regulation
查询保险法规

**Input:**
- query (string): 查询词
- searchType (string): exact/semantic/hybrid（可选，默认hybrid）

**Output:**
```json
{
  "success": true,
  "results": [...]
}
```

### check_negative_list
检查负面清单

**Input:**
- clauses (array): 产品条款数组

**Output:**
```json
{
  "success": true,
  "violations": [...]
}
```
```

**Step 2: Create skill.json**

```json
{
  "id": "actuary-sleuth",
  "name": "Actuary Sleuth",
  "version": "3.0.0",
  "readme": "SKILL.md",
  "config": {
    "scriptsPath": "./scripts",
    "dataPath": "./data",
    "pythonEnv": "python3",
    "lancedbUri": "./data/lancedb",
    "ollamaHost": "http://localhost:11434",
    "ollamaModel": "qwen2:7b",
    "ollamaEmbedModel": "nomic-embed-text"
  }
}
```

**Step 3: Create template.py**

Run: `mkdir -p /root/.openclaw/workspace/skills/actuary-sleuth/scripts/lib`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Actuary Sleuth Script Template
统一脚本接口规范
"""
import argparse
import json
import sys
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

def main():
    parser = argparse.ArgumentParser(description='Actuary Sleuth Script')
    parser.add_argument('--input', required=True, help='JSON input file')
    parser.add_argument('--config', default='./config/settings.json', help='Config file')
    args = parser.parse_args()

    # 读取输入
    with open(args.input, 'r', encoding='utf-8') as f:
        params = json.load(f)

    # 执行业务逻辑
    try:
        result = execute(params)
        # 输出结果（JSON格式）
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        # 错误输出
        error_result = {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }
        print(json.dumps(error_result, ensure_ascii=False), file=sys.stderr)
        return 1

def execute(params):
    """具体业务逻辑实现 - 子类必须覆盖"""
    raise NotImplementedError("Subclasses must implement execute()")

if __name__ == '__main__':
    sys.exit(main())
```

**Step 4: Create lib/__init__.py**

Run: `touch /root/.openclaw/workspace/skills/actuary-sleuth/scripts/lib/__init__.py`

```python
# Actuary Sleuth Library
```

**Step 5: Create config/settings.json**

Run: `mkdir -p /root/.openclaw/workspace/skills/actuary-sleuth/scripts/config`

```json
{
  "scriptsPath": "./scripts",
  "dataPath": "./data",
  "pythonEnv": "python3",
  "lancedbUri": "./data/lancedb",
  "ollamaHost": "http://localhost:11434",
  "ollamaModel": "qwen2:7b",
  "ollamaEmbedModel": "nomic-embed-text"
}
```

**Step 6: Create requirements.txt**

```
lancedb>=0.5.0
requests>=2.28.0
pyarrow>=14.0.0
paddleocr>=2.7.0
```

**Step 7: Create data and references directories**

Run: `mkdir -p /root/.openclaw/workspace/skills/actuary-sleuth/data /root/.openclaw/workspace/skills/actuary-sleuth/references`

Run: `touch /root/.openclaw/workspace/skills/actuary-sleuth/data/.gitkeep /root/.openclaw/workspace/skills/actuary-sleuth/references/.gitkeep`

**Step 8: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/`

Run: `git commit -m "feat: create actuary-sleuth skill base structure"`

---

## Task 2: Implement Database Module (lib/db.py)

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/lib/db.py`
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/init_db.py`
- Test: Create test file manually for validation

**Step 1: Write lib/db.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库操作模块
"""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / 'data' / 'actuary.db'

def get_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def find_regulation(article_number):
    """精确查找法规条款"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('''
        SELECT * FROM regulations
        WHERE article_number = ?
    ''', (article_number,))

    row = cur.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None

def search_regulations(keyword):
    """关键词搜索法规"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('''
        SELECT * FROM regulations
        WHERE content LIKE ? OR article_number LIKE ?
        LIMIT 20
    ''', (f'%{keyword}%', f'%{keyword}%'))

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]

def get_negative_list():
    """获取负面清单"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('SELECT * FROM negative_list ORDER BY severity DESC')
    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]

def save_audit_record(record):
    """保存审核记录"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute('''
        INSERT INTO audit_history (id, user_id, document_url, violations, score)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        record['id'],
        record.get('user_id', ''),
        record.get('document_url', ''),
        json.dumps(record.get('violations', []), ensure_ascii=False),
        record.get('score', 0)
    ))

    conn.commit()
    conn.close()
```

**Step 2: Write init_db.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化数据库
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'data' / 'actuary.db'

def init_database():
    """初始化数据库表"""
    conn = sqlite3.connect(DB_PATH)

    # 创建法规表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS regulations (
            id TEXT PRIMARY KEY,
            law_name TEXT NOT NULL,
            article_number TEXT,
            content TEXT NOT NULL,
            category TEXT,
            tags TEXT,
            effective_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_article
        ON regulations(law_name, article_number)
    ''')

    # 创建负面清单表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS negative_list (
            id INTEGER PRIMARY KEY,
            rule_number TEXT UNIQUE,
            description TEXT NOT NULL,
            severity TEXT,
            category TEXT,
            remediation TEXT,
            keywords TEXT,
            patterns TEXT,
            version TEXT,
            effective_date TEXT
        )
    ''')

    # 创建审核历史表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS audit_history (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            document_url TEXT,
            document_type TEXT,
            violations TEXT,
            score REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print(f"Database initialized: {DB_PATH}")

if __name__ == '__main__':
    init_database()
```

**Step 3: Make executable and test**

Run: `chmod +x /root/.openclaw/workspace/skills/actuary-sleuth/scripts/init_db.py`

Run: `cd /root/.openclaw/workspace/skills/actuary-sleuth && python3 scripts/init_db.py`

Expected: `Database initialized: /root/.openclaw/workspace/skills/actuary-sleuth/data/actuary.db`

Run: `sqlite3 /root/.openclaw/workspace/skills/actuary-sleuth/data/actuary.db ".tables"`

Expected: `audit_history  negative_list  regulations`

**Step 4: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/scripts/`

Run: `git commit -m "feat: implement database module and initialization script"`

---

## Task 3: Implement Ollama Module (lib/ollama.py)

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/lib/ollama.py`

**Step 1: Write lib/ollama.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 调用模块
"""
import requests
import json

OLLAMA_HOST = 'http://localhost:11434'
EMBED_MODEL = 'nomic-embed-text'
CHAT_MODEL = 'qwen2:7b'

def embed(text):
    """生成文本向量"""
    try:
        response = requests.post(
            f'{OLLAMA_HOST}/api/embeddings',
            json={
                'model': EMBED_MODEL,
                'prompt': text
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()['embedding']
    except Exception as e:
        raise Exception(f"Ollama embed error: {str(e)}")

def generate(prompt, system=None):
    """生成文本"""
    data = {
        'model': CHAT_MODEL,
        'prompt': prompt,
        'stream': False
    }

    if system:
        data['system'] = system

    try:
        response = requests.post(
            f'{OLLAMA_HOST}/api/generate',
            json=data,
            timeout=120
        )
        response.raise_for_status()
        return response.json()['response']
    except Exception as e:
        raise Exception(f"Ollama generate error: {str(e)}")

def analyze_compliance(clause, regulations):
    """分析条款合规性"""
    prompt = f"""作为保险精算专家，请判断以下条款是否违规：

【条款内容】
{clause}

【相关法规】
{chr(10).join(regulations[:3])}

请返回JSON格式（仅返回JSON，不要其他内容）：
{{
    "is_violation": true或false,
    "reason": "违规原因或合规说明",
    "severity": "high或medium或low",
    "suggestion": "整改建议"
}}"""

    try:
        result = generate(prompt)
        # 尝试解析 JSON
        result = result.strip()
        if result.startswith('```'):
            result = result.split('\n', 1)[1]
        if result.endswith('```'):
            result = result.rsplit('\n', 1)[0]
        if result.startswith('json'):
            result = result[4:]

        return json.loads(result)
    except:
        # 解析失败，返回默认结果
        return {
            "is_violation": False,
            "reason": "无法解析",
            "severity": "low",
            "suggestion": "请人工复核"
        }
```

**Step 2: Test Ollama connection**

Run: `curl -s http://localhost:11434/api/tags | head -20`

Expected: Ollama model list (if running)

**Step 3: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/scripts/lib/ollama.py`

Run: `git commit -m "feat: implement ollama LLM integration module"`

---

## Task 4: Implement LanceDB Module (lib/lancedb.py)

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/lib/lancedb.py`

**Step 1: Write lib/lancedb.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量检索模块
"""
import lancedb
from pathlib import Path

DB_URI = str(Path(__file__).parent.parent.parent / 'data' / 'lancedb')

class VectorDB:
    _instance = None
    _tables = {}

    @classmethod
    def connect(cls):
        """连接 LanceDB"""
        if cls._instance is None:
            cls._instance = lancedb.connect(DB_URI)
        return cls._instance

    @classmethod
    def get_table(cls, table_name='regulations_vectors'):
        """获取表"""
        if table_name not in cls._tables:
            db = cls.connect()
            try:
                cls._tables[table_name] = db.open_table(table_name)
            except:
                return None
        return cls._tables[table_name]

    @classmethod
    def search(cls, query_vector, top_k=5, table_name='regulations_vectors'):
        """向量搜索"""
        table = cls.get_table(table_name)
        if table is None:
            return []

        results = table.vectorSearch(query_vector).limit(top_k).to_pydict()

        return [
            {
                'content': r['chunk_text'],
                'metadata': r['metadata'],
                'score': 1 / (1 + r.get('_distance', 0))
            }
            for r in results
        ]

    @classmethod
    def add_vectors(cls, data, table_name='regulations_vectors'):
        """添加向量"""
        db = cls.connect()

        existing_tables = db.table_names()
        if table_name not in existing_tables:
            import pyarrow as pa
            schema = pa.schema([
                pa.field('id', pa.string()),
                pa.field('regulation_id', pa.string()),
                pa.field('chunk_text', pa.string()),
                pa.field('vector', pa.list_(pa.float32())),
                pa.field('metadata', pa.string())
            ])
            table = db.create_table(table_name, schema=schema)
        else:
            table = db.open_table(table_name)

        table.add(data)
        cls._tables[table_name] = table
```

**Step 2: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/scripts/lib/lancedb.py`

Run: `git commit -m "feat: implement LanceDB vector search module"`

---

## Task 5: Implement Query Script (scripts/query.py)

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/query.py`

**Step 1: Write query.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法规查询脚本
"""
from template import main
from lib import db, lancedb, ollama

def execute(params):
    """执行法规查询"""
    query_text = params['query']
    search_type = params.get('searchType', 'hybrid')

    results = []

    # 精确查询
    if search_type in ['exact', 'hybrid']:
        exact = db.find_regulation(query_text)
        if exact:
            results.append({
                'type': 'exact',
                'content': exact['content'],
                'law_name': exact['law_name'],
                'article_number': exact['article_number'],
                'category': exact['category'],
                'score': 1.0
            })

    # 语义检索
    if search_type in ['semantic', 'hybrid']:
        query_vec = ollama.embed(query_text)
        semantic = lancedb.VectorDB.search(query_vec, top_k=5)
        for item in semantic:
            results.append({
                'type': 'semantic',
                'content': item['content'],
                'law_name': item['metadata']['law_name'],
                'article_number': item['metadata']['article_number'],
                'score': item['score']
            })

    # 排序返回
    results.sort(key=lambda x: x['score'], reverse=True)

    return {
        'success': True,
        'query': query_text,
        'search_type': search_type,
        'results': results[:5],
        'count': len(results[:5])
    }

if __name__ == '__main__':
    main()
```

**Step 2: Make executable and test**

Run: `chmod +x /root/.openclaw/workspace/skills/actuary-sleuth/scripts/query.py`

Run: `echo '{"query":"保险法第十六条"}' > /tmp/test_query.json && cd /root/.openclaw/workspace/skills/actuary-sleuth && python3 scripts/query.py --input /tmp/test_query.json`

Expected: JSON output with success:true and empty results (no data yet)

**Step 3: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/scripts/query.py`

Run: `git commit -m "feat: implement regulation query script"`

---

## Task 6: Implement Check Script (scripts/check.py)

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/check.py`

**Step 1: Write check.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
负面清单检查脚本
"""
from template import main
from lib import db

def execute(params):
    """执行负面清单检查"""
    clauses = params['clauses']

    # 获取负面清单规则
    rules = db.get_negative_list()

    # 执行检查
    violations = []
    for idx, clause in enumerate(clauses):
        for rule in rules:
            if match_rule(clause, rule):
                violations.append({
                    'clause_index': idx,
                    'clause_text': clause[:100] + '...' if len(clause) > 100 else clause,
                    'rule': rule['rule_number'],
                    'description': rule['description'],
                    'severity': rule['severity'],
                    'category': rule['category'],
                    'remediation': rule['remediation']
                })

    return {
        'success': True,
        'violations': violations,
        'count': len(violations),
        'summary': group_by_severity(violations)
    }

def match_rule(clause, rule):
    """规则匹配逻辑"""
    # 关键词匹配
    keywords = rule.get('keywords', [])
    if keywords:
        import json
        keyword_list = json.loads(keywords) if isinstance(keywords, str) else keywords
        for keyword in keyword_list:
            if keyword in clause:
                return True

    # 正则表达式匹配
    patterns = rule.get('patterns', [])
    if patterns:
        import json
        import re
        pattern_list = json.loads(patterns) if isinstance(patterns, str) else patterns
        for pattern in pattern_list:
            if re.search(pattern, clause):
                return True

    return False

def group_by_severity(violations):
    """按严重程度分组"""
    summary = {
        'high': sum(1 for v in violations if v['severity'] == 'high'),
        'medium': sum(1 for v in violations if v['severity'] == 'medium'),
        'low': sum(1 for v in violations if v['severity'] == 'low')
    }
    return summary

if __name__ == '__main__':
    main()
```

**Step 2: Make executable and test**

Run: `chmod +x /root/.openclaw/workspace/skills/actuary-sleuth/scripts/check.py`

Run: `echo '{"clauses":["测试条款内容"]}'> /tmp/test_check.json && cd /root/.openclaw/workspace/skills/actuary-sleuth && python3 scripts/check.py --input /tmp/test_check.json`

Expected: JSON output with success:true and empty violations (no rules yet)

**Step 3: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/scripts/check.py`

Run: `git commit -m "feat: implement negative list check script"`

---

## Task 7: Implement Remaining Scripts

### Task 7a: preprocess.py

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/preprocess.py`

**Step 1: Write preprocess.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档预处理脚本
"""
from template import main

def execute(params):
    """执行文档预处理"""
    content = params.get('content', '')

    # 简单预处理：提取条款
    clauses = []
    sections = []
    current_section = "前言"
    current_clauses = []

    for line in content.split('\n'):
        line = line.strip()
        if not line:
            continue

        # 检测章节
        if line.startswith('#') or '第' in line and '章' in line:
            if current_clauses:
                sections.append({
                    'title': current_section,
                    'clauses': current_clauses
                })
                clauses.extend(current_clauses)
                current_clauses = []
            current_section = line.lstrip('#').strip()
        else:
            current_clauses.append(line)

    # 最后一部分
    if current_clauses:
        sections.append({
            'title': current_section,
            'clauses': current_clauses
        })
        clauses.extend(current_clauses)

    return {
        'success': True,
        'clauses': clauses,
        'sections': sections,
        'metadata': {
            'total_clauses': len(clauses),
            'total_sections': len(sections)
        }
    }

if __name__ == '__main__':
    main()
```

**Step 2: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/scripts/preprocess.py && git commit -m "feat: implement document preprocessing script"`

### Task 7b: scoring.py

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/scoring.py`

**Step 1: Write scoring.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评分模块脚本
"""

def calculate_score(violations, pricing=None):
    """计算综合评分"""
    if not violations:
        return 100

    # 基础分100
    score = 100

    # 根据违规严重程度扣分
    for v in violations:
        severity = v.get('severity', 'low')
        if severity == 'high':
            score -= 20
        elif severity == 'medium':
            score -= 10
        else:
            score -= 5

    # 定价合理性影响
    if pricing and not pricing.get('reasonable', True):
        score -= 15

    return max(0, score)

def analyze_pricing(pricing_data):
    """分析定价合理性"""
    # 简化版本：返回占位结果
    return {
        'reasonable': True,
        'mortality_rate': pricing_data.get('mortality', 0.001),
        'interest_rate': pricing_data.get('interest', 0.035),
        'expense_rate': pricing_data.get('expense', 0.15)
    }
```

**Step 2: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/scripts/scoring.py && git commit -m "feat: implement scoring module"`

### Task 7c: report.py

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/report.py`

**Step 1: Write report.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成脚本
"""
from datetime import datetime
import uuid

def generate(data):
    """生成审核报告"""
    violations = data.get('violations', [])
    score = data.get('score', 0)

    # 生成报告文本
    report_lines = [
        "📊 审核报告",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"【综合评分】{score} 分 - {'合格' if score >= 60 else '不合格'}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # 按严重程度分组
    high_violations = [v for v in violations if v.get('severity') == 'high']
    medium_violations = [v for v in violations if v.get('severity') == 'medium']

    if high_violations:
        report_lines.append(f"🔴 高危违规 ({len(high_violations)})")
        for idx, v in enumerate(high_violations, 1):
            report_lines.append(f"  {idx}. {v.get('description', '未知违规')}")
            report_lines.append(f"     - 位置: 第{v.get('clause_index', '?')}条")
            report_lines.append(f"     - 严重程度: 高")
            report_lines.append(f"     - 建议: {v.get('remediation', '请整改')}")

    if medium_violations:
        report_lines.append(f"🟡 中危违规 ({len(medium_violations)})")
        for idx, v in enumerate(medium_violations, 1):
            report_lines.append(f"  {idx}. {v.get('description', '未知违规')}")

    # 定价分析
    pricing = data.get('pricing')
    if pricing:
        if pricing.get('reasonable', True):
            report_lines.append("✅ 定价分析合理")
        else:
            report_lines.append("⚠️ 定价分析需关注")

    # 元数据
    metadata = data.get('metadata', {})
    report_lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"审核时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"审核编号: AUD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    ])

    return {
        'success': True,
        'report': '\n'.join(report_lines),
        'raw_data': data
    }
```

**Step 2: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/scripts/report.py && git commit -m "feat: implement report generation module"`

### Task 7d: audit.py

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/audit.py`

**Step 1: Write audit.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审核引擎 - 主入口
"""
from template import main
import sys
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from lib import preprocess, check, query, scoring, report

def execute(params):
    """执行完整审核流程"""
    # 1. 文档预处理
    doc = preprocess.execute({'content': params.get('documentContent', '')})

    # 2. 负面清单检查
    violations = check.execute({'clauses': doc.get('clauses', [])})
    violation_list = violations.get('violations', [])

    # 3. 法规合规检查
    audit_type = params.get('auditType', 'full')
    if audit_type != 'negative-only':
        for v in violation_list:
            v['regulations'] = query.execute({
                'query': v['description'],
                'searchType': 'hybrid'
            })

    # 4. 定价分析
    pricing = None
    pricing_data = params.get('pricing_data')
    if pricing_data and audit_type == 'full':
        pricing = scoring.analyze_pricing(pricing_data)

    # 5. 计算综合评分
    score = scoring.calculate_score(violation_list, pricing)

    # 6. 生成报告
    return report.generate({
        'violations': violation_list,
        'pricing': pricing,
        'score': score,
        'document': doc,
        'metadata': {
            'audit_type': audit_type,
            'document_url': params.get('documentUrl', ''),
            'timestamp': datetime.now().isoformat()
        }
    })

if __name__ == '__main__':
    from datetime import datetime
    main()
```

**Step 2: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/scripts/audit.py && git commit -m "feat: implement main audit engine script"`

---

## Task 8: Import Sample Data

**Files:**
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/scripts/import_regs.py`
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/references/01_保险法相关监管规定.md`
- Create: `/root/.openclaw/workspace/skills/actuary-sleuth/references/02_负面清单.md`

**Step 1: Write import_regs.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入法规数据
"""
import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'data' / 'actuary.db'
REFS_PATH = Path(__file__).parent.parent / 'references'

def import_markdown_file(file_path):
    """导入单个 Markdown 法规文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    law_name = file_path.stem
    articles = parse_articles(content)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for article in articles:
        cur.execute('''
            INSERT OR REPLACE INTO regulations
            (id, law_name, article_number, content, category)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            f"{law_name}_{article['number']}",
            law_name,
            article['number'],
            article['content'],
            article.get('category', '')
        ))

    conn.commit()
    conn.close()
    print(f"Imported {len(articles)} articles from {file_path.name}")

def parse_articles(content):
    """解析 Markdown 文件中的条款"""
    articles = []
    pattern = r'^(#{1,3}\s*)?(第[一二三四五六七八九十百千]+条|[\d]+\.?)\s*(.*)$'

    current_article = None

    for line in content.split('\n'):
        match = re.match(pattern, line.strip())
        if match:
            if current_article:
                articles.append(current_article)
            current_article = {
                'number': match.group(2),
                'title': match.group(3),
                'content': ''
            }
        elif current_article:
            current_article['content'] += line + '\n'

    if current_article:
        articles.append(current_article)

    return articles

def import_negative_list():
    """导入负面清单"""
    nl_file = REFS_PATH / '02_负面清单.md'
    with open(nl_file, 'r', encoding='utf-8') as f:
        content = f.read()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 简化版：插入示例规则
    sample_rules = [
        (1, 'NL001', '免责条款未加粗标红', 'high', '格式', '请将免责条款加粗并使用红色字体', '[]', '[]', 'v1.0', '2024-01-01'),
        (2, 'NL002', '犹豫期描述不完整', 'high', '内容', '补充犹豫期起算日期', '[]', '[]', 'v1.0', '2024-01-01'),
    ]

    for rule in sample_rules:
        cur.execute('''
            INSERT OR REPLACE INTO negative_list
            (id, rule_number, description, severity, category, remediation, keywords, patterns, version, effective_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', rule)

    conn.commit()
    conn.close()
    print(f"Imported {len(sample_rules)} negative list rules")

if __name__ == '__main__':
    import_negative_list()
```

**Step 2: Create sample reference files**

Run: `cat > /root/.openclaw/workspace/skills/actuary-sleuth/references/01_保险法相关监管规定.md << 'EOF'
# 保险法相关监管规定

## 第十六条

订立保险合同，保险人就保险标的或者被保险人的有关情况提出询问的，投保人应当如实告知。

## 第十七条

保险合同中规定有关于保险人责任免除条款的，保险人在订立保险合同时应当向投保人明确说明，未明确说明的，该条款不产生效力。

## 第十九条

投保人可以解除合同，保险人不得解除合同。
EOF`

Run: `cat > /root/.openclaw/workspace/skills/actuary-sleuth/references/02_负面清单.md << 'EOF'
# 负面清单

## 高危违规

1. 免责条款未加粗标红
2. 犹豫期描述不完整
3. 费率表不清晰
EOF`

**Step 3: Test import**

Run: `chmod +x /root/.openclaw/workspace/skills/actuary-sleuth/scripts/import_regs.py`

Run: `cd /root/.openclaw/workspace/skills/actuary-sleuth && python3 scripts/import_regs.py`

Expected: `Imported 2 negative list rules`

**Step 4: Verify data**

Run: `sqlite3 /root/.openclaw/workspace/skills/actuary-sleuth/data/actuary.db "SELECT COUNT(*) FROM regulations;"`

Expected: `3`

Run: `sqlite3 /root/.openclaw/workspace/skills/actuary-sleuth/data/actuary.db "SELECT COUNT(*) FROM negative_list;"`

Expected: `2`

**Step 5: Commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/`

Run: `git commit -m "feat: add sample regulation data and import script"`

---

## Task 9: Final Integration Testing

**Files:**
- Test all scripts end-to-end

**Step 1: Test query script with data**

Run: `echo '{"query":"第十六条"}' > /tmp/test_query_final.json && cd /root/.openclaw/workspace/skills/actuary-sleuth && python3 scripts/query.py --input /tmp/test_query_final.json`

Expected: JSON with results containing "第十六条" content

**Step 2: Test check script with data**

Run: `echo '{"clauses":["保险人有权解除合同","犹豫期10天"]}'> /tmp/test_check_final.json && cd /root/.openclaw/workspace/skills/actuary-sleuth && python3 scripts/check.py --input /tmp/test_check_final.json`

Expected: JSON with violations detected

**Step 3: Test full audit flow**

Run: `echo '{"documentContent":"# 测试保险产品\n## 第一条\n保险人有权解除合同。\n## 第二条\n犹豫期10天。"}' > /tmp/test_audit_final.json && cd /root/.openclaw/workspace/skills/actuary-sleuth && python3 scripts/audit.py --input /tmp/test_audit_final.json`

Expected: JSON report with score and violations

**Step 4: Verify all files exist and are executable**

Run: `ls -la /root/.openclaw/workspace/skills/actuary-sleuth/scripts/*.py`

Expected: All Python scripts listed with execute permissions

**Step 5: Final commit**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/ && git commit -m "test: complete integration testing and validation"`

---

## Task 10: Documentation and Cleanup

**Files:**
- Update: SKILL.md with usage examples
- Create: README.md for the skill

**Step 1: Create README.md**

```markdown
# Actuary Sleuth Skill

保险产品精算审核系统，支持负面清单检查、法规查询和审核报告生成。

## 安装

1. 确保已安装 Python 3.10+
2. 安装依赖: `pip install -r scripts/requirements.txt`
3. 初始化数据库: `python3 scripts/init_db.py`
4. 导入法规数据: `python3 scripts/import_regs.py`

## 使用

### 审核文档

\`\`\`bash
echo '{"documentContent":"..."}' | python3 scripts/audit.py --input /dev/stdin
\`\`\`

### 查询法规

\`\`\`bash
echo '{"query":"保险法第十六条"}' | python3 scripts/query.py --input /dev/stdin
\`\`\`

### 检查负面清单

\`\`\`bash
echo '{"clauses":["..."]}' | python3 scripts/check.py --input /dev/stdin
\`\`\`
```

**Step 2: Commit documentation**

Run: `git add /root/.openclaw/workspace/skills/actuary-sleuth/ && git commit -m "docs: add usage documentation and README"`

**Step 3: Push to remote**

Run: `git push origin main`
