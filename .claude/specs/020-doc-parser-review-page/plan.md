# Implementation Plan: 产品文档解析结果审核页面

**Branch**: `020-doc-parser-review-page` | **Date**: 2026-04-22 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

实现产品文档解析结果的审核页面，支持用户查看解析后的结构化数据（条款、费率表、责任等）并对照原文进行验证。核心挑战是 doc_parser 当前未存储位置信息，需分阶段实现：阶段一采用文本匹配定位，阶段二扩展位置字段支持精确定位。

## Technical Context

**Language/Version**: Python 3.x + TypeScript (React)
**Primary Dependencies**: FastAPI, Ant Design, React, pdfplumber, python-docx
**Storage**: SQLite (复用现有数据库)
**Testing**: pytest + Vitest
**Performance Goals**: 原文定位响应 < 1s
**Constraints**: 复用知识库审核页面布局和交互模式

## Constitution Check

- [x] **Library-First**: 复用 KnowledgePage.tsx 的分块验证 Modal、EvalPage.tsx 的审核抽屉模式
- [x] **测试优先**: 每个 Phase 包含单元测试和集成测试
- [x] **简单优先**: 阶段一采用文本匹配定位，避免大改解析器
- [x] **显式优于隐式**: 数据模型明确字段，无魔法行为
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md User Story
- [x] **独立可测试**: User Story 1-2 可独立交付，User Story 3-4 为增量功能

## Project Structure

### Documentation

```text
.claude/specs/020-doc-parser-review-page/
├── spec.md          # 需求规格
├── research.md      # 技术调研
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/
├── api/
│   ├── routers/
│   │   └── product_doc.py      # 新增：产品文档 API
│   └── database.py             # 修改：添加解析结果存储
├── lib/
│   ├── doc_parser/
│   │   ├── models.py           # 修改：添加位置字段（阶段二）
│   │   └── pd/
│   │       ├── docx_parser.py  # 修改：提取位置信息（阶段二）
│   │       └── pdf_parser.py   # 修改：提取位置信息（阶段二）
│   └── common/
│       └── models.py           # 新增：审核状态模型
└── web/src/
    ├── pages/
    │   └── ProductDocPage.tsx  # 新增：产品文档审核页面
    └── api/
        └── productDoc.ts       # 新增：产品文档 API 封装
```

## Implementation Phases

---

### Phase 1: 数据存储与 API (P1)

#### 需求回溯

→ 对应 spec.md FR-001, FR-004: 展示解析结果、与审核流程集成

#### 实现步骤

**步骤 1.1: 定义解析结果存储模型**

- 文件: `scripts/lib/common/models.py`
- 说明: 新增 `ParsedDocument` 数据模型用于持久化

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

@dataclass(frozen=True)
class ParsedDocument:
    """产品文档解析结果"""
    id: str                           # 文档唯一标识
    file_name: str                    # 原始文件名
    file_path: Optional[str]          # 文件路径（如有）
    file_type: str                    # .docx / .pdf
    clauses: List[Dict[str, Any]]     # 条款列表
    premium_tables: List[Dict[str, Any]]  # 费率表列表
    notices: List[Dict[str, Any]]     # 须知
    health_disclosures: List[Dict[str, Any]]  # 健康告知
    exclusions: List[Dict[str, Any]]  # 责任免除
    rider_clauses: List[Dict[str, Any]]  # 附加险条款
    raw_content: Optional[str]        # 原文内容（用于对照）
    parse_time: datetime
    warnings: List[str]
    review_status: str = "pending"    # pending, approved, rejected
    reviewer: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None
```

**步骤 1.2: 添加数据库表和操作函数**

- 文件: `scripts/api/database.py`
- 说明: 添加 `parsed_documents` 表和相关操作

```python
# 在 init_db() 中添加表创建
CREATE_TABLE_PARSED_DOCS = """
CREATE TABLE IF NOT EXISTS parsed_documents (
    id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_path TEXT,
    file_type TEXT NOT NULL,
    clauses TEXT,           -- JSON
    premium_tables TEXT,    -- JSON
    notices TEXT,           -- JSON
    health_disclosures TEXT,-- JSON
    exclusions TEXT,        -- JSON
    rider_clauses TEXT,     -- JSON
    raw_content TEXT,
    parse_time TEXT,
    warnings TEXT,          -- JSON
    review_status TEXT DEFAULT 'pending',
    reviewer TEXT,
    reviewed_at TEXT,
    review_comment TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

def save_parsed_document(doc: ParsedDocument) -> str:
    """保存解析结果"""
    with get_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO parsed_documents
            (id, file_name, file_path, file_type, clauses, premium_tables,
             notices, health_disclosures, exclusions, rider_clauses,
             raw_content, parse_time, warnings, review_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            doc.id, doc.file_name, doc.file_path, doc.file_type,
            json.dumps(doc.clauses, ensure_ascii=False),
            json.dumps(doc.premium_tables, ensure_ascii=False),
            json.dumps(doc.notices, ensure_ascii=False),
            json.dumps(doc.health_disclosures, ensure_ascii=False),
            json.dumps(doc.exclusions, ensure_ascii=False),
            json.dumps(doc.rider_clauses, ensure_ascii=False),
            doc.raw_content,
            doc.parse_time.isoformat(),
            json.dumps(doc.warnings, ensure_ascii=False),
            doc.review_status,
        ))
        return doc.id

def get_parsed_document(doc_id: str) -> Optional[ParsedDocument]:
    """获取解析结果"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM parsed_documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if not row:
            return None
        return ParsedDocument(
            id=row['id'],
            file_name=row['file_name'],
            file_path=row['file_path'],
            file_type=row['file_type'],
            clauses=json.loads(row['clauses'] or '[]'),
            premium_tables=json.loads(row['premium_tables'] or '[]'),
            notices=json.loads(row['notices'] or '[]'),
            health_disclosures=json.loads(row['health_disclosures'] or '[]'),
            exclusions=json.loads(row['exclusions'] or '[]'),
            rider_clauses=json.loads(row['rider_clauses'] or '[]'),
            raw_content=row['raw_content'],
            parse_time=datetime.fromisoformat(row['parse_time']),
            warnings=json.loads(row['warnings'] or '[]'),
            review_status=row['review_status'],
            reviewer=row['reviewer'],
            reviewed_at=datetime.fromisoformat(row['reviewed_at']) if row['reviewed_at'] else None,
            review_comment=row['review_comment'],
        )

def list_parsed_documents(
    review_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[ParsedDocument]:
    """列出解析结果"""
    with get_connection() as conn:
        query = "SELECT * FROM parsed_documents"
        params = []
        if review_status:
            query += " WHERE review_status = ?"
            params.append(review_status)
        query += " ORDER BY parse_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return [_row_to_parsed_doc(row) for row in rows]
```

**步骤 1.3: 创建产品文档 API 路由**

- 文件: `scripts/api/routers/product_doc.py` (新增)
- 说明: 提供解析结果查询和审核接口

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

from ..database import save_parsed_document, get_parsed_document, list_parsed_documents
from lib.doc_parser import parse_product_document

router = APIRouter(prefix="/api/product-docs", tags=["product-docs"])

class ParseRequest(BaseModel):
    file_path: str

class ReviewRequest(BaseModel):
    reviewer: str
    comment: Optional[str] = None
    status: str = "approved"  # approved 或 rejected

@router.post("/parse")
async def parse_document(request: ParseRequest):
    """解析产品文档并存储结果"""
    try:
        audit_doc = parse_product_document(request.file_path)
        doc_id = str(uuid.uuid4())
        # 转换为存储格式
        parsed_doc = ParsedDocument(
            id=doc_id,
            file_name=audit_doc.file_name,
            file_path=request.file_path,
            file_type=audit_doc.file_type,
            clauses=[{"number": c.number, "title": c.title, "text": c.text} for c in audit_doc.clauses],
            premium_tables=[{"raw_text": t.raw_text, "data": t.data} for t in audit_doc.premium_tables],
            notices=[{"title": s.title, "content": s.content} for s in audit_doc.notices],
            health_disclosures=[{"title": s.title, "content": s.content} for s in audit_doc.health_disclosures],
            exclusions=[{"title": s.title, "content": s.content} for s in audit_doc.exclusions],
            rider_clauses=[{"number": c.number, "title": c.title, "text": c.text} for c in audit_doc.rider_clauses],
            raw_content=None,  # 阶段一暂不存储原文
            parse_time=audit_doc.parse_time,
            warnings=audit_doc.warnings,
        )
        save_parsed_document(parsed_doc)
        return {"id": doc_id, "status": "parsed"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """获取解析结果"""
    doc = get_parsed_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc

@router.get("")
async def list_documents(
    review_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """列出解析结果"""
    docs = list_parsed_documents(review_status, limit, offset)
    return docs

@router.patch("/{doc_id}/review")
async def review_document(doc_id: str, request: ReviewRequest):
    """提交审核结果"""
    doc = get_parsed_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # 更新审核状态
    update_parsed_document_review(doc_id, request.status, request.reviewer, request.comment)
    return {"id": doc_id, "status": request.status}
```

**步骤 1.4: 注册路由**

- 文件: `scripts/api/main.py`
- 说明: 添加 product_doc 路由

```python
from .routers import product_doc
app.include_router(product_doc.router)
```

**步骤 1.5: 单元测试**

- 文件: `scripts/tests/api/test_product_doc.py` (新增)

```python
import pytest
from api.database import init_db, save_parsed_document, get_parsed_document
from lib.common.models import ParsedDocument
from datetime import datetime

@pytest.fixture
def setup_db():
    init_db()

def test_save_and_get_parsed_document(setup_db):
    doc = ParsedDocument(
        id="test-1",
        file_name="test.pdf",
        file_path="/tmp/test.pdf",
        file_type=".pdf",
        clauses=[{"number": "1.1", "title": "测试条款", "text": "内容"}],
        premium_tables=[],
        notices=[],
        health_disclosures=[],
        exclusions=[],
        rider_clauses=[],
        raw_content=None,
        parse_time=datetime.now(),
        warnings=[],
    )
    save_parsed_document(doc)
    result = get_parsed_document("test-1")
    assert result is not None
    assert result.file_name == "test.pdf"
    assert len(result.clauses) == 1
```

---

### Phase 2: 前端审核页面 (P1)

#### 需求回溯

→ 对应 spec.md User Story 1, User Story 2: 查看解析结果、对照原文验证

#### 实现步骤

**步骤 2.1: 创建 API 封装**

- 文件: `scripts/web/src/api/productDoc.ts` (新增)

```typescript
import client from './client';

export interface ParsedDocument {
  id: string;
  file_name: string;
  file_path: string | null;
  file_type: string;
  clauses: Array<{ number: string; title: string; text: string }>;
  premium_tables: Array<{ raw_text: string; data: string[][] }>;
  notices: Array<{ title: string; content: string }>;
  health_disclosures: Array<{ title: string; content: string }>;
  exclusions: Array<{ title: string; content: string }>;
  rider_clauses: Array<{ number: string; title: string; text: string }>;
  raw_content: string | null;
  parse_time: string;
  warnings: string[];
  review_status: string;
  reviewer: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
}

export async function fetchParsedDocuments(params?: {
  review_status?: string;
}): Promise<ParsedDocument[]> {
  const { data } = await client.get('/api/product-docs', { params });
  return data;
}

export async function fetchParsedDocument(docId: string): Promise<ParsedDocument> {
  const { data } = await client.get(`/api/product-docs/${docId}`);
  return data;
}

export async function reviewDocument(docId: string, request: {
  reviewer: string;
  comment?: string;
  status: 'approved' | 'rejected';
}): Promise<{ id: string; status: string }> {
  const { data } = await client.patch(`/api/product-docs/${docId}/review`, request);
  return data;
}
```

**步骤 2.2: 创建审核页面**

- 文件: `scripts/web/src/pages/ProductDocPage.tsx` (新增)
- 说明: 复用 KnowledgePage.tsx 的分块验证 Modal 布局

```tsx
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Card, Table, Button, Space, Modal, Typography, message, Tag, Descriptions,
  Row, Col, Tabs, theme, Grid, Input, Drawer, Form
} from 'antd';
import { FileTextOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import * as api from '../api/productDoc';
import type { ParsedDocument } from '../api/productDoc';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const { Text, Title } = Typography;

export default function ProductDocPage() {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  const [documents, setDocuments] = useState<ParsedDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<ParsedDocument | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedItem, setSelectedItem] = useState<{ type: string; index: number } | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // 加载文档列表
  const loadDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const docs = await api.fetchParsedDocuments();
      setDocuments(docs);
    } catch (err: any) {
      message.error(`加载失败: ${err?.message || err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  // 打开详情 Modal
  const handleViewDetail = (doc: ParsedDocument) => {
    setSelectedDoc(doc);
    setDetailOpen(true);
    setSelectedItem(null);
  };

  // 获取所有解析项（用于表格展示）
  const parseItems = useMemo(() => {
    if (!selectedDoc) return [];
    const items: Array<{ type: string; index: number; label: string; content: string }> = [];

    selectedDoc.clauses.forEach((c, i) => {
      items.push({ type: 'clause', index: i, label: `条款 ${c.number}`, content: c.text });
    });
    selectedDoc.premium_tables.forEach((_, i) => {
      items.push({ type: 'premium_table', index: i, label: `费率表 ${i + 1}`, content: '[表格]' });
    });
    selectedDoc.notices.forEach((n, i) => {
      items.push({ type: 'notice', index: i, label: `须知: ${n.title}`, content: n.content });
    });
    selectedDoc.health_disclosures.forEach((h, i) => {
      items.push({ type: 'health_disclosure', index: i, label: `健康告知 ${i + 1}`, content: h.content });
    });
    selectedDoc.exclusions.forEach((e, i) => {
      items.push({ type: 'exclusion', index: i, label: `责任免除 ${i + 1}`, content: e.content });
    });
    selectedDoc.rider_clauses.forEach((r, i) => {
      items.push({ type: 'rider_clause', index: i, label: `附加险条款 ${r.number}`, content: r.text });
    });

    return items;
  }, [selectedDoc]);

  // 文本定位（阶段一：简单文本匹配）
  const locateText = useCallback((text: string) => {
    if (!selectedDoc?.raw_content) return;
    // 复用 KnowledgePage 的定位算法
    const lines = selectedDoc.raw_content.split('\n');
    const flatContent = selectedDoc.raw_content.replace(/\s+/g, '');
    const snippet = text.replace(/\s+/g, '').slice(0, 80);
    const pos = flatContent.indexOf(snippet);
    if (pos < 0) return;

    let charCount = 0, startLine = -1;
    for (let i = 0; i < lines.length; i++) {
      const lineLen = lines[i].replace(/\s+/g, '').length;
      if (charCount + lineLen > pos) { startLine = i; break; }
      charCount += lineLen;
    }
    if (startLine < 0) return;

    // 滚动到对应位置
    requestAnimationFrame(() => {
      const blocks = contentRef.current?.querySelectorAll('p, li, h1, h2, h3, h4, h5, h6, blockquote, pre, tr');
      if (!blocks) return;
      for (const block of blocks) {
        const blockText = block.textContent?.replace(/\s+/g, '') || '';
        if (snippet.includes(blockText.slice(0, Math.min(blockText.length, 60)))) {
          block.classList.add('kb-highlight');
          block.scrollIntoView({ behavior: 'smooth', block: 'center' });
          break;
        }
      }
    });
  }, [selectedDoc]);

  // 表格列定义
  const columns = [
    { title: '文件名', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
    { title: '类型', dataIndex: 'file_type', key: 'file_type', width: 80 },
    { title: '条款数', key: 'clause_count', width: 80, render: (_: unknown, r: ParsedDocument) => r.clauses.length },
    { title: '状态', dataIndex: 'review_status', key: 'review_status', width: 100, render: (v: string) => (
      <Tag color={v === 'approved' ? 'green' : 'default'}>{v === 'approved' ? '已通过' : '待审核'}</Tag>
    )},
    { title: '操作', key: 'action', width: 100, render: (_: unknown, r: ParsedDocument) => (
      <Button type="link" size="small" onClick={() => handleViewDetail(r)}>查看</Button>
    )},
  ];

  return (
    <Card title="产品文档解析审核">
      <Table
        dataSource={documents}
        rowKey="id"
        columns={columns}
        loading={loading}
        pagination={{ pageSize: 20 }}
      />

      <Modal
        title={selectedDoc?.file_name}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={isMobile ? '100%' : '90vw'}
        style={{ top: 20 }}
      >
        {selectedDoc && (
          <div style={{ display: 'flex', height: 'calc(100vh - 200px)' }}>
            {/* 左侧：解析结果列表 */}
            <div style={{ width: '45%', borderRight: `1px solid ${token.colorBorderSecondary}`, overflow: 'auto' }}>
              <Table
                dataSource={parseItems}
                rowKey={(_, i) => String(i)}
                size="small"
                pagination={false}
                onRow={(record) => ({
                  onClick: () => {
                    setSelectedItem({ type: record.type, index: record.index });
                    if (selectedDoc.raw_content) {
                      locateText(record.content);
                    }
                  },
                  style: { cursor: 'pointer' },
                })}
                columns={[
                  { title: '类型', dataIndex: 'label', key: 'label', ellipsis: true },
                  { title: '内容摘要', dataIndex: 'content', key: 'content', ellipsis: true, render: (v: string) => v.slice(0, 50) + '...' },
                ]}
              />
            </div>

            {/* 右侧：详情展示 */}
            <div style={{ width: '55%', padding: 16, overflow: 'auto' }}>
              {selectedItem ? (
                <Descriptions bordered column={1} size="small">
                  <Descriptions.Item label="类型">{parseItems.find(p => p.type === selectedItem.type && p.index === selectedItem.index)?.label}</Descriptions.Item>
                  <Descriptions.Item label="内容">
                    <div className="markdown-body">
                      {selectedItem.type === 'premium_table' ? (
                        <pre>{selectedDoc.premium_tables[selectedItem.index]?.raw_text}</pre>
                      ) : (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {parseItems.find(p => p.type === selectedItem.type && p.index === selectedItem.index)?.content || ''}
                        </ReactMarkdown>
                      )}
                    </div>
                  </Descriptions.Item>
                </Descriptions>
              ) : (
                <div style={{ color: token.colorTextSecondary }}>点击左侧项查看详情</div>
              )}
            </div>
          </div>
        )}
      </Modal>
    </Card>
  );
}
```

**步骤 2.3: 添加路由**

- 文件: `scripts/web/src/App.tsx`

```tsx
import ProductDocPage from './pages/ProductDocPage';

// 在路由配置中添加
<Route path="/product-docs" element={<ProductDocPage />} />
```

**步骤 2.4: 添加导航入口**

- 文件: `scripts/web/src/components/AppLayout.tsx`

```tsx
import { FileTextOutlined } from '@ant-design/icons';

// 在菜单项中添加
{
  key: '/product-docs',
  icon: <FileTextOutlined />,
  label: '产品文档审核',
}
```

---

### Phase 3: 审核状态管理 (P2)

#### 需求回溯

→ 对应 spec.md User Story 3: 审核状态标记

#### 实现步骤

**步骤 3.1: 添加审核 Drawer**

- 文件: `scripts/web/src/pages/ProductDocPage.tsx` (修改)
- 说明: 在详情 Modal 底部添加审核操作

```tsx
// 在 Modal 内添加审核表单
const [reviewDrawerOpen, setReviewDrawerOpen] = useState(false);
const [reviewForm] = Form.useForm();

const handleSubmitReview = async (values: { reviewer: string; comment?: string; status: 'approved' | 'rejected' }) => {
  if (!selectedDoc) return;
  try {
    await api.reviewDocument(selectedDoc.id, values);
    message.success('审核已提交');
    setReviewDrawerOpen(false);
    loadDocuments();
  } catch (err: any) {
    message.error(`提交失败: ${err?.message || err}`);
  }
};

// 在 Modal footer 或详情区域添加
<Button type="primary" onClick={() => setReviewDrawerOpen(true)}>
  提交审核
</Button>

// 审核 Drawer
<Drawer
  title="提交审核"
  open={reviewDrawerOpen}
  onClose={() => setReviewDrawerOpen(false)}
  width={400}
>
  <Form form={reviewForm} layout="vertical" onFinish={handleSubmitReview}>
    <Form.Item name="reviewer" label="审核人" rules={[{ required: true }]}>
      <Input />
    </Form.Item>
    <Form.Item name="status" label="审核结果" rules={[{ required: true }]} initialValue="approved">
      <Select options={[
        { value: 'approved', label: '通过' },
        { value: 'rejected', label: '不通过' },
      ]} />
    </Form.Item>
    <Form.Item name="comment" label="备注">
      <Input.TextArea rows={3} />
    </Form.Item>
    <Form.Item>
      <Button type="primary" htmlType="submit">提交</Button>
    </Form.Item>
  </Form>
</Drawer>
```

---

### Phase 4: 原文对照定位增强 (P2)

#### 需求回溯

→ 对应 spec.md User Story 2: 对照原文验证

#### 实现步骤

**步骤 4.1: 扩展数据模型添加位置字段**

- 文件: `scripts/lib/doc_parser/models.py` (修改)

```python
from typing import Optional, Tuple

@dataclass(frozen=True)
class Clause:
    number: str
    title: str
    text: str
    section_type: str = "clause"
    # 新增位置字段
    page_number: Optional[int] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    table_index: Optional[int] = None

@dataclass(frozen=True)
class PremiumTable:
    raw_text: str
    data: List[List[str]]
    remark: str = ""
    section_type: str = "premium_table"
    # 新增位置字段
    page_number: Optional[int] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    table_index: Optional[int] = None
```

**步骤 4.2: 修改 PDF 解析器提取位置**

- 文件: `scripts/lib/doc_parser/pd/pdf_parser.py` (修改)

```python
def _extract_clauses_from_tables(self, tables, page_index: int, warnings: List[str]) -> List[Clause]:
    clauses = []
    for table in tables:
        rows = table.extract()
        if not rows:
            continue
        for row in rows:
            if not row or not row[0]:
                continue
            first_cell = str(row[0] or '').strip()
            if self.detector.is_clause_table(first_cell):
                number = first_cell
                content = str(row[1] or '').strip() if len(row) > 1 else ''
                title, text = separate_title_and_text(content)
                # 添加位置信息
                bbox = table.bbox if hasattr(table, 'bbox') else None
                clauses.append(Clause(
                    number=number,
                    title=title,
                    text=text,
                    page_number=page_index + 1,
                    bbox=bbox,
                ))
    return clauses
```

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | - | - |

## Appendix

### 执行顺序建议

```
Phase 1 (数据存储与 API)
    ↓
Phase 2 (前端审核页面) ← 可并行开发
    ↓
Phase 3 (审核状态管理)
    ↓
Phase 4 (原文对照定位增强) ← 可选，后续迭代
```

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 查看解析结果 | 所有解析字段正确展示 | `test_product_doc.py` |
| US2 对照原文验证 | 点击条款后原文定位响应 < 1s | 手动测试 |
| US3 审核状态标记 | 状态正确保存和展示 | `test_product_doc.py` |
| US4 开发调试视图 | 阶段二实现 | - |
