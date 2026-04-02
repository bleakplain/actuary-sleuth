# 合规检查来源可信度增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增强合规检查历史中 `[来源X]` 引用的可信度，让用户能查看完整法规元数据和原文片段。

**Architecture:** 后端增强 Prompt 让 LLM 输出引用原文片段（`source_excerpt`），前端新增来源详情抽屉面板展示完整元数据。fusion.py 补充透传额外元数据字段。

**Tech Stack:** Python (FastAPI), React (Ant Design), TypeScript

---

### Task 1: fusion.py 透传额外元数据

**Files:**
- Modify: `scripts/lib/rag_engine/fusion.py:56-67`

- [ ] **Step 1: 在 fusion.py 的结果构建中添加 `doc_number`、`effective_date`、`issuing_authority` 字段**

在 `reciprocal_rank_fusion` 函数的结果构建部分（约第 59-67 行），在 `'hierarchy_path'` 后面添加三个字段：

```python
results.append({
    'law_name': chunk.metadata.get('law_name', '未知'),
    'article_number': chunk.metadata.get('article_number', '未知'),
    'category': chunk.metadata.get('category', ''),
    'content': chunk.text,
    'source_file': chunk.metadata.get('source_file', ''),
    'hierarchy_path': chunk.metadata.get('hierarchy_path', ''),
    'doc_number': chunk.metadata.get('doc_number', ''),
    'effective_date': chunk.metadata.get('effective_date', ''),
    'issuing_authority': chunk.metadata.get('issuing_authority', ''),
    'score': rrf_score,
})
```

- [ ] **Step 2: 运行现有测试确认无破坏**

Run: `pytest scripts/tests/ -v -x`
Expected: 所有测试通过

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/rag_engine/fusion.py
git commit -m "feat: pass through doc_number, effective_date, issuing_authority in fusion results"
```

---

### Task 2: 增强合规 Prompt 引用精度

**Files:**
- Modify: `scripts/api/routers/compliance.py:19-53` (product prompt)
- Modify: `scripts/api/routers/compliance.py:55-91` (document prompt)
- Modify: `scripts/api/routers/compliance.py:95-99` (`_build_context`)

- [ ] **Step 1: 修改 `_build_context` 注入更多元数据**

将 `_build_context` 函数改为：

```python
def _build_context(search_results: list) -> str:
    parts = []
    for i, r in enumerate(search_results):
        law_name = r.get('law_name', '')
        article = r.get('article_number', '')
        content = r.get('content', '')
        authority = r.get('issuing_authority', '')
        doc_number = r.get('doc_number', '')
        effective = r.get('effective_date', '')
        header = f"[来源{i+1}] 【{law_name}】{article}"
        if doc_number:
            header += f"（{doc_number}）"
        if authority:
            header += f"\n发布机关：{authority}"
        if effective:
            header += f"\n生效日期：{effective}"
        parts.append(f"{header}\n{content}")
    return "\n\n".join(parts)
```

- [ ] **Step 2: 修改 `_COMPLIANCE_PROMPT_PRODUCT` 添加 `source_excerpt` 字段和引用指令**

将 `_COMPLIANCE_PROMPT_PRODUCT` 替换为：

```python
_COMPLIANCE_PROMPT_PRODUCT = """你是一位保险法规合规专家。请根据以下产品参数和相关法规条款，逐项检查该产品是否符合法规要求。

## 产品信息
- 产品名称：{product_name}
- 险种类型：{category}
- 产品参数：{params_json}

## 相关法规条款
{context}

## 输出要求
请以 JSON 格式输出检查结果，严格遵循以下结构：
{{
    "summary": {{
        "compliant": <合规项数>,
        "non_compliant": <不合规项数>,
        "attention": <需关注项数>
    }},
    "items": [
        {{
            "param": "<参数名称>",
            "value": "<产品实际值>",
            "requirement": "<法规要求，引用法规原文关键句>",
            "status": "<compliant|non_compliant|attention>",
            "source": "<法规来源，格式：[来源X]>",
            "source_excerpt": "<从来源法规中直接摘录的原文片段，作为该判断的事实依据>",
            "suggestion": "<修改建议，仅不合规时填写>"
        }}
    ]
}}

注意：
1. 每个参数都要检查，未找到明确法规要求的标注为 attention
2. source 必须使用 [来源X] 格式引用法规条款
3. source_excerpt 必须是从对应来源中直接摘录的原文，不得自行编造或改写
4. requirement 应结合法规原文表述，使合规判断有据可查
5. 仅输出 JSON，不要附加其他文字
"""
```

- [ ] **Step 3: 修改 `_COMPLIANCE_PROMPT_DOCUMENT` 同样添加 `source_excerpt`**

将 `_COMPLIANCE_PROMPT_DOCUMENT` 替换为：

```python
_COMPLIANCE_PROMPT_DOCUMENT = """你是一位保险法规合规专家。请审查以下保险条款文档，检查是否符合相关法规要求。

## 条款文档内容
{document_content}

## 相关法规条款
{context}

## 输出要求
请以 JSON 格式输出检查结果，严格遵循以下结构：
{{
    "summary": {{
        "compliant": <合规项数>,
        "non_compliant": <不合规项数>,
        "attention": <需关注项数>
    }},
    "items": [
        {{
            "param": "<检查项名称>",
            "value": "<条款中的实际内容>",
            "requirement": "<法规要求，引用法规原文关键句>",
            "status": "<compliant|non_compliant|attention>",
            "source": "<法规来源，格式：[来源X]>",
            "source_excerpt": "<从来源法规中直接摘录的原文片段，作为该判断的事实依据>",
            "suggestion": "<修改建议>"
        }}
    ],
    "extracted_params": {{
        "<参数名>": "<提取值>"
    }}
}}

注意：
1. 先提取条款中的关键参数，再逐项检查合规性
2. 检查项包括但不限于：等待期、免赔额、保险期间、缴费方式、免责条款等
3. source 必须使用 [来源X] 格式引用法规条款
4. source_excerpt 必须是从对应来源中直接摘录的原文，不得自行编造或改写
5. requirement 应结合法规原文表述，使合规判断有据可查
6. 仅输出 JSON，不要附加其他文字
"""
```

- [ ] **Step 4: Commit**

```bash
git add scripts/api/routers/compliance.py
git commit -m "feat: enhance compliance prompt with source_excerpt and richer metadata context"
```

---

### Task 3: 更新前端类型定义

**Files:**
- Modify: `scripts/web/src/types/index.ts:8-15` (Source interface)
- Modify: `scripts/web/src/types/index.ts:111-118` (ComplianceItem interface)

- [ ] **Step 1: 扩展 Source 接口添加可选元数据字段**

在 `Source` interface 中添加：

```typescript
export interface Source {
  law_name: string;
  article_number: string;
  category: string;
  content: string;
  source_file: string;
  hierarchy_path: string;
  doc_number?: string;
  effective_date?: string;
  issuing_authority?: string;
  score?: number;
}
```

- [ ] **Step 2: 在 ComplianceItem 中添加 source_excerpt 字段**

```typescript
export interface ComplianceItem {
  param: string;
  value?: string | number;
  requirement: string;
  status: 'compliant' | 'non_compliant' | 'attention';
  source?: string;
  source_excerpt?: string;
  suggestion?: string;
}
```

- [ ] **Step 3: Commit**

```bash
git add scripts/web/src/types/index.ts
git commit -m "feat: add source metadata and source_excerpt to type definitions"
```

---

### Task 4: 前端 — 来源详情抽屉组件

**Files:**
- Modify: `scripts/web/src/pages/CompliancePage.tsx`

- [ ] **Step 1: 添加 imports 和 SourceDrawer 组件**

在 `CompliancePage.tsx` 文件顶部，在现有 imports 后添加 `Drawer` 到 antd imports：

```typescript
import {
  Card, Form, Input, Button, Table, Tag, Typography,
  message, Tabs, Space, Descriptions, Popconfirm, Drawer,
} from 'antd';
```

添加 `BookOutlined` 到 icons imports：

```typescript
import {
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  HistoryOutlined, DeleteOutlined, BookOutlined,
} from '@ant-design/icons';
```

在 `CompliancePage` 函数之前（`STATUS_CONFIG` 之后），添加 `SourceDrawer` 组件：

```tsx
function SourceDrawer({
  visible,
  source,
  excerpt,
  onClose,
}: {
  visible: boolean;
  source: Source | undefined;
  excerpt?: string;
  onClose: () => void;
}) {
  if (!source) return null;

  return (
    <Drawer
      title={<Space><BookOutlined />法规来源详情</Space>}
      placement="right"
      width={560}
      open={visible}
      onClose={onClose}
    >
      <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="法规名称">{source.law_name}</Descriptions.Item>
        <Descriptions.Item label="条款编号">{source.article_number}</Descriptions.Item>
        {source.doc_number && (
          <Descriptions.Item label="文号">{source.doc_number}</Descriptions.Item>
        )}
        {source.issuing_authority && (
          <Descriptions.Item label="发布机关">{source.issuing_authority}</Descriptions.Item>
        )}
        {source.effective_date && (
          <Descriptions.Item label="生效日期">{source.effective_date}</Descriptions.Item>
        )}
        <Descriptions.Item label="分类">{source.category}</Descriptions.Item>
        {source.hierarchy_path && (
          <Descriptions.Item label="层级路径">{source.hierarchy_path}</Descriptions.Item>
        )}
        {source.score != null && (
          <Descriptions.Item label="检索相关度">
            <Tag color={source.score > 0.02 ? 'green' : source.score > 0.01 ? 'orange' : 'red'}>
              {source.score.toFixed(4)}
            </Tag>
          </Descriptions.Item>
        )}
      </Descriptions>

      {excerpt && (
        <div style={{ marginBottom: 16 }}>
          <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
            引用原文片段
          </Typography.Text>
          <div
            style={{
              background: '#e6f7ff',
              border: '1px solid #91d5ff',
              borderRadius: 4,
              padding: '8px 12px',
              color: '#0050b3',
              fontSize: 13,
            }}
          >
            {excerpt}
          </div>
        </div>
      )}

      <div>
        <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
          法规原文
        </Typography.Text>
        <div
          style={{
            background: '#fafafa',
            border: '1px solid #d9d9d9',
            borderRadius: 4,
            padding: '12px',
            maxHeight: 300,
            overflow: 'auto',
            whiteSpace: 'pre-wrap',
            fontSize: 13,
          }}
        >
          {source.content}
        </div>
      </div>
    </Drawer>
  );
}
```

- [ ] **Step 2: 在 CompliancePage 组件中添加 drawer 状态和 handler**

在 `CompliancePage` 函数体内，在 `const [historyLoading, setHistoryLoading] = useState(false);` 后添加：

```typescript
const [sourceDrawerVisible, setSourceDrawerVisible] = useState(false);
const [selectedSource, setSelectedSource] = useState<Source | undefined>();
const [selectedExcerpt, setSelectedExcerpt] = useState<string | undefined>();
```

在 `handleSelectReport` 函数之后添加：

```typescript
const handleSourceClick = (sourceIdx: number, excerpt?: string) => {
  const sources = result?.sources;
  if (sources && sourceIdx < sources.length) {
    setSelectedSource(sources[sourceIdx]);
    setSelectedExcerpt(excerpt);
    setSourceDrawerVisible(true);
  }
};
```

在 `itemColumns` 定义之后、`handleDeleteReport` 之前，添加 Source 类型的 import（如果 types 里没有 import）。确认 `CompliancePage.tsx` 顶部的 import 包含 `Source`：

```typescript
import type { ComplianceReport, ComplianceItem, Source } from '../types';
```

- [ ] **Step 3: 修改法规来源列为可点击的 Tag**

将 `itemColumns` 中的 `source` 列替换为：

```typescript
{
  title: '法规来源',
  dataIndex: 'source',
  key: 'source',
  width: 150,
  render: (text: string, record: ComplianceItem) => {
    if (!text) return '-';
    // 解析 [来源X] 标签
    const matches = text.match(/\[来源(\d+)\]/g);
    if (!matches) return text;
    return (
      <Space size={4} wrap>
        {matches.map((tag) => {
          const idx = parseInt(tag.replace(/\[来源(\d+)\]/, '$1'), 10) - 1;
          return (
            <Tag
              key={tag}
              color="blue"
              style={{ cursor: 'pointer' }}
              onClick={() => handleSourceClick(idx, record.source_excerpt)}
            >
              {tag}
            </Tag>
          );
        })}
      </Space>
    );
  },
},
```

- [ ] **Step 4: 在 JSX 末尾渲染 SourceDrawer**

在 `CompliancePage` return 的 JSX 最后（`</div>` 闭合之前），添加：

```tsx
<SourceDrawer
  visible={sourceDrawerVisible}
  source={selectedSource}
  excerpt={selectedExcerpt}
  onClose={() => setSourceDrawerVisible(false)}
/>
```

- [ ] **Step 5: 验证前端编译通过**

Run: `cd scripts/web && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 6: Commit**

```bash
git add scripts/web/src/pages/CompliancePage.tsx scripts/web/src/types/index.ts
git commit -m "feat: add source detail drawer with metadata and excerpt display"
```

---

### Task 5: 端到端验证

- [ ] **Step 1: 启动后端和前端**

Run: `python3 scripts/run_api.py` (in one terminal)
Run: `cd scripts/web && npm run dev` (in another terminal)

- [ ] **Step 2: 在浏览器中执行合规检查**

1. 打开 http://localhost:3000/compliance
2. 切换到「条款文档审查」tab
3. 粘贴一段包含等待期条款的健康险产品条款
4. 点击「开始审查」
5. 检查结果中等待期行的「法规来源」列应显示蓝色 `[来源X]` 标签
6. 点击蓝色标签，应弹出抽屉，显示法规名称、发文机关、生效日期、原文片段等

- [ ] **Step 3: 检查历史记录**

1. 切换到「检查历史」tab
2. 点击刚才的检查记录
3. 确认历史记录中的来源标签同样可以点击查看详情

- [ ] **Step 4: 最终 commit**

如有调整则提交：
```bash
git add -A
git commit -m "feat: enhance compliance source trustability with metadata and excerpt display"
```
