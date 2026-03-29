# RAG Web 平台 - 前端实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 React + TypeScript + Ant Design 构建法规知识平台前端，对接后端 API，提供法规问答、知识库管理、评估管理、合规检查四大模块。

**Architecture:** React SPA + Vite 构建，Ant Design 组件库，Zustand 状态管理，react-markdown 渲染回答，Recharts 评估图表。API 调用层封装在 `services/`，页面组件在 `pages/`，通用组件在 `components/`。

**Tech Stack:** React 18, TypeScript, Vite, Ant Design 5, Zustand, react-markdown, Recharts, axios

**Design Spec:** `docs/superpowers/specs/2026-03-29-rag-web-platform-design.md`

**Backend API:** `docs/superpowers/plans/2026-03-29-rag-web-backend.md`（Task 4-8 定义了全部 API 端点）

---

## 文件结构总览

```
scripts/web/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── public/
├── src/
│   ├── main.tsx                    # React 入口
│   ├── App.tsx                     # 路由配置 + 布局
│   ├── vite-env.d.ts
│   ├── api/                        # API 调用层
│   │   ├── client.ts               # axios 实例 + 拦截器
│   │   ├── ask.ts                  # 问答 API
│   │   ├── knowledge.ts            # 知识库 API
│   │   ├── eval.ts                 # 评估 API
│   │   └── compliance.ts           # 合规检查 API
│   ├── stores/                     # Zustand 状态管理
│   │   ├── askStore.ts             # 对话状态
│   │   └── appStore.ts             # 全局状态（侧边栏等）
│   ├── pages/                      # 页面组件
│   │   ├── AskPage.tsx             # 法规问答（主页面）
│   │   ├── KnowledgePage.tsx       # 知识库管理
│   │   ├── EvalDatasetPage.tsx     # 评估数据集管理
│   │   ├── EvalRunPage.tsx         # 评估运行与结果
│   │   └── CompliancePage.tsx      # 合规检查
│   ├── components/                 # 通用组件
│   │   ├── AppLayout.tsx           # 全局布局（侧边栏 + 顶栏 + 内容区）
│   │   ├── ChatPanel.tsx           # 对话面板（消息列表 + 输入框）
│   │   ├── MessageBubble.tsx       # 单条消息气泡（含引用渲染）
│   │   ├── SourcePanel.tsx         # 来源侧边面板
│   │   ├── CitationTag.tsx         # [来源X] 可点击标签
│   │   └── MetricsChart.tsx        # 评估指标图表
│   └── types/                      # TypeScript 类型定义
│       └── index.ts                # 全部接口类型
```

---

## Task 1: 项目初始化与通用布局

**Files:**
- Create: `scripts/web/` (Vite + React + TS 脚手架)
- Create: `scripts/web/src/main.tsx`
- Create: `scripts/web/src/App.tsx`
- Create: `scripts/web/src/components/AppLayout.tsx`
- Create: `scripts/web/src/types/index.ts`

- [ ] **Step 1: 创建 Vite 项目**

```bash
cd scripts && npm create vite@latest web -- --template react-ts
cd web && npm install
```

- [ ] **Step 2: 安装依赖**

```bash
cd scripts/web && npm install antd @ant-design/icons react-router-dom zustand axios react-markdown remark-gfm recharts
```

- [ ] **Step 3: 创建 TypeScript 类型定义 `scripts/web/src/types/index.ts`**

```typescript
// ── 问答 ────────────────────────────────────────────

export interface Citation {
  source_idx: number;
  law_name: string;
  article_number: string;
  content: string;
}

export interface Source {
  law_name: string;
  article_number: string;
  category: string;
  content: string;
  source_file: string;
  hierarchy_path: string;
}

export interface Message {
  id: number;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  sources: Source[];
  timestamp: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  message_count: number;
}

export interface ChatRequest {
  question: string;
  conversation_id?: string;
  mode: 'qa' | 'search';
}

// ── 知识库 ──────────────────────────────────────────

export interface Document {
  name: string;
  file_path: string;
  clause_count: number;
  file_size: number;
  indexed_at?: string;
  status: string;
}

export interface IndexStatus {
  vector_db: Record<string, unknown>;
  bm25: Record<string, unknown>;
  document_count: number;
}

export interface TaskStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: string;
  result?: Record<string, unknown>;
}

// ── 评估数据集 ──────────────────────────────────────

export interface EvalSample {
  id: string;
  question: string;
  ground_truth: string;
  evidence_docs: string[];
  evidence_keywords: string[];
  question_type: 'factual' | 'multi_hop' | 'negative' | 'colloquial';
  difficulty: 'easy' | 'medium' | 'hard';
  topic: string;
  created_at: string;
  updated_at: string;
}

export interface EvalSnapshot {
  id: string;
  name: string;
  description: string;
  sample_count: number;
  created_at: string;
}

// ── 评估运行 ────────────────────────────────────────

export interface EvalRun {
  id: string;
  mode: 'retrieval' | 'generation' | 'full';
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  total: number;
  started_at: string;
  finished_at?: string;
  config?: Record<string, unknown>;
}

export interface SampleResult {
  id: number;
  run_id: string;
  sample_id: string;
  retrieved_docs: Source[];
  generated_answer: string;
  retrieval_metrics: Record<string, number>;
  generation_metrics: Record<string, number>;
}

export interface MetricsDiff {
  baseline: number;
  compare: number;
  delta: number;
  pct_change: number;
}

// ── 合规检查 ────────────────────────────────────────

export interface ComplianceItem {
  param: string;
  value?: unknown;
  requirement: string;
  status: 'compliant' | 'non_compliant' | 'attention';
  source?: string;
  suggestion?: string;
}

export interface ComplianceResult {
  summary: {
    compliant: number;
    non_compliant: number;
    attention: number;
  };
  items: ComplianceItem[];
  sources?: Source[];
  citations?: Citation[];
  extracted_params?: Record<string, string>;
}

export interface ComplianceReport {
  id: string;
  product_name: string;
  category: string;
  mode: 'product' | 'document';
  result: ComplianceResult;
  created_at: string;
}
```

- [ ] **Step 4: 创建 axios 实例 `scripts/web/src/api/client.ts`**

```typescript
import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

const client = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
});

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg = err.response?.data?.detail || err.message || '请求失败';
    return Promise.reject(new Error(msg));
  },
);

export default client;
```

- [ ] **Step 5: 创建全局布局 `scripts/web/src/components/AppLayout.tsx`**

```tsx
import React, { useState } from 'react';
import { Layout, Menu } from 'antd';
import {
  MessageOutlined,
  DatabaseOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';

const { Sider, Content, Header } = Layout;

const menuItems = [
  { key: '/ask', icon: <MessageOutlined />, label: '法规问答' },
  { key: '/knowledge', icon: <DatabaseOutlined />, label: '知识库管理' },
  { key: '/eval/dataset', icon: <BarChartOutlined />, label: '评估数据集' },
  { key: '/eval/runs', icon: <BarChartOutlined />, label: '评估运行' },
  { key: '/compliance', icon: <SafetyCertificateOutlined />, label: '合规检查' },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);

  const selectedKey = menuItems.find(
    (item) => location.pathname.startsWith(item.key),
  )?.key || '/ask';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
        style={{ borderRight: '1px solid #f0f0f0' }}
      >
        <div style={{ height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', borderBottom: '1px solid #f0f0f0' }}>
          <span style={{ fontWeight: 600, fontSize: collapsed ? 14 : 16 }}>
            {collapsed ? 'AS' : '精算助手'}
          </span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderRight: 0 }}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center' }}>
          <span style={{ fontSize: 16, fontWeight: 500 }}>
            精算法规知识平台
          </span>
        </Header>
        <Content style={{ margin: 16, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
```

- [ ] **Step 6: 配置路由 `scripts/web/src/App.tsx`**

```tsx
import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import AppLayout from './components/AppLayout';
import AskPage from './pages/AskPage';
import KnowledgePage from './pages/KnowledgePage';
import EvalDatasetPage from './pages/EvalDatasetPage';
import EvalRunPage from './pages/EvalRunPage';
import CompliancePage from './pages/CompliancePage';

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<AskPage />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/eval/dataset" element={<EvalDatasetPage />} />
            <Route path="/eval/runs" element={<EvalRunPage />} />
            <Route path="/compliance" element={<CompliancePage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
```

- [ ] **Step 7: 创建占位页面使路由可编译**

创建 `scripts/web/src/pages/AskPage.tsx`:
```tsx
export default function AskPage() {
  return <div>法规问答</div>;
}
```

创建 `scripts/web/src/pages/KnowledgePage.tsx`:
```tsx
export default function KnowledgePage() {
  return <div>知识库管理</div>;
}
```

创建 `scripts/web/src/pages/EvalDatasetPage.tsx`:
```tsx
export default function EvalDatasetPage() {
  return <div>评估数据集</div>;
}
```

创建 `scripts/web/src/pages/EvalRunPage.tsx`:
```tsx
export default function EvalRunPage() {
  return <div>评估运行</div>;
}
```

创建 `scripts/web/src/pages/CompliancePage.tsx`:
```tsx
export default function CompliancePage() {
  return <div>合规检查</div>;
}
```

- [ ] **Step 8: 验证项目可启动**

```bash
cd scripts/web && npm run dev &
sleep 3 && curl -s http://localhost:5173 | head -5
kill %1
```

Expected: HTML 输出（Vite dev server 启动成功）

- [ ] **Step 9: Commit**

```bash
git add scripts/web/
git commit -m "feat(web): scaffold React + TypeScript + Ant Design project with layout"
```

---

## Task 2: 法规问答页面

**Files:**
- Create: `scripts/web/src/api/ask.ts`
- Create: `scripts/web/src/stores/askStore.ts`
- Modify: `scripts/web/src/pages/AskPage.tsx`
- Create: `scripts/web/src/components/ChatPanel.tsx`
- Create: `scripts/web/src/components/MessageBubble.tsx`
- Create: `scripts/web/src/components/CitationTag.tsx`
- Create: `scripts/web/src/components/SourcePanel.tsx`

- [ ] **Step 1: 创建 API 层 `scripts/web/src/api/ask.ts`**

```typescript
import client from './client';
import type { ChatRequest, Conversation, Message } from '../types';

export async function fetchConversations(): Promise<Conversation[]> {
  const { data } = await client.get('/api/ask/conversations');
  return data;
}

export async function fetchMessages(conversationId: string): Promise<Message[]> {
  const { data } = await client.get(`/api/ask/conversations/${conversationId}/messages`);
  return data;
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await client.delete(`/api/ask/conversations/${conversationId}`);
}

export function chatSSE(req: ChatRequest): {
  controller: AbortController;
  onToken: (token: string) => void;
  onDone: (data: { conversation_id: string; citations: unknown[]; sources: unknown[] }) => void;
  onError: (err: string) => void;
} {
  const controller = new AbortController();
  let onToken: (token: string) => void = () => {};
  let onDone: (data: unknown) => void = () => {};
  let onError: (err: string) => void = () => {};

  const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

  fetch(`${API_BASE}/api/ask/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal: controller.signal,
  })
    .then(async (res) => {
      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data:')) {
            try {
              const event = JSON.parse(line.slice(5).trim());
              if (event.type === 'token') onToken(event.data);
              else if (event.type === 'done') onDone(event.data);
              else if (event.type === 'error') onError(event.data);
            } catch { /* skip malformed */ }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') onError(err.message);
    });

  return {
    controller,
    set onToken(fn: typeof onToken) { onToken = fn; },
    set onDone(fn: typeof onDone) { onDone = fn; },
    set onError(fn: typeof onError) { onError = fn; },
  };
}
```

注意：上面 `chatSSE` 的 setter 写法不符合 TypeScript 最佳实践。改用回调参数方式：

```typescript
export function chatSSE(
  req: ChatRequest,
  callbacks: {
    onToken: (token: string) => void;
    onDone: (data: { conversation_id: string; citations: unknown[]; sources: unknown[] }) => void;
    onError: (err: string) => void;
  },
): AbortController {
  const controller = new AbortController();
  const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

  fetch(`${API_BASE}/api/ask/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal: controller.signal,
  })
    .then(async (res) => {
      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data:')) {
            try {
              const event = JSON.parse(line.slice(5).trim());
              if (event.type === 'token') callbacks.onToken(event.data);
              else if (event.type === 'done') callbacks.onDone(event.data);
              else if (event.type === 'error') callbacks.onError(event.data);
            } catch { /* skip malformed */ }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') callbacks.onError(err.message);
    });

  return controller;
}
```

- [ ] **Step 2: 创建状态管理 `scripts/web/src/stores/askStore.ts`**

```typescript
import { create } from 'zustand';
import type { Conversation, Message, Source } from '../types';
import * as askApi from '../api/ask';

interface AskState {
  conversations: Conversation[];
  currentConversationId: string | null;
  messages: Message[];
  streaming: boolean;
  currentSources: Source[];

  loadConversations: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  sendMessage: (question: string, mode: 'qa' | 'search') => void;
  deleteConversation: (id: string) => Promise<void>;
}

export const useAskStore = create<AskState>((set, get) => ({
  conversations: [],
  currentConversationId: null,
  messages: [],
  streaming: false,
  currentSources: [],

  loadConversations: async () => {
    const conversations = await askApi.fetchConversations();
    set({ conversations });
  },

  selectConversation: async (id: string) => {
    set({ currentConversationId: id, currentSources: [] });
    const messages = await askApi.fetchMessages(id);
    set({ messages });
  },

  sendMessage: (question: string, mode: 'qa' | 'search') => {
    const { currentConversationId, messages } = get();

    // 添加用户消息到 UI
    const userMsg: Message = {
      id: Date.now(),
      conversation_id: currentConversationId || '',
      role: 'user',
      content: question,
      citations: [],
      sources: [],
      timestamp: new Date().toISOString(),
    };
    const assistantMsg: Message = {
      id: Date.now() + 1,
      conversation_id: currentConversationId || '',
      role: 'assistant',
      content: '',
      citations: [],
      sources: [],
      timestamp: new Date().toISOString(),
    };
    set({ messages: [...messages, userMsg, assistantMsg], streaming: true, currentSources: [] });

    if (mode === 'search') {
      // search 模式用普通 POST
      askApi.chatSSE(
        { question, conversation_id: currentConversationId || undefined, mode: 'search' },
        {
          onToken: () => {},
          onDone: () => {},
          onError: () => {},
        },
      );
      // search 模式返回的是 JSON，需要用不同处理方式
      // 这里改为直接用 axios
      import('./ask').then(async (mod) => {
        const client = (await import('./client')).default;
        try {
          const { data } = await client.post('/api/ask/chat', {
            question,
            conversation_id: currentConversationId || undefined,
            mode: 'search',
          });
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id
                ? { ...m, content: typeof data.content === 'string' ? data.content : JSON.stringify(data.sources, null, 2) }
                : m,
            ),
            currentSources: data.sources || [],
            streaming: false,
          }));
          get().loadConversations();
        } catch (err) {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: `错误: ${err}` } : m,
            ),
            streaming: false,
          }));
        }
      });
      return;
    }

    // QA 模式：SSE 流式
    let fullAnswer = '';
    askApi.chatSSE(
      { question, conversation_id: currentConversationId || undefined, mode: 'qa' },
      {
        onToken: (token) => {
          fullAnswer += token;
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: fullAnswer } : m,
            ),
          }));
        },
        onDone: (data) => {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id
                ? { ...m, citations: data.citations || [], sources: data.sources || [] }
                : m,
            ),
            currentConversationId: data.conversation_id || currentConversationId,
            currentSources: data.sources || [],
            streaming: false,
          }));
          get().loadConversations();
        },
        onError: (err) => {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: `错误: ${err}` } : m,
            ),
            streaming: false,
          }));
        },
      },
    );
  },

  deleteConversation: async (id: string) => {
    await askApi.deleteConversation(id);
    const { currentConversationId } = get();
    if (currentConversationId === id) {
      set({ currentConversationId: null, messages: [] });
    }
    get().loadConversations();
  },
}));
```

- [ ] **Step 3: 创建引用标签组件 `scripts/web/src/components/CitationTag.tsx`**

```tsx
import React from 'react';
import { Tag } from 'antd';
import type { Citation } from '../types';

interface Props {
  citation: Citation;
  onClick?: (citation: Citation) => void;
}

export default function CitationTag({ citation, onClick }: Props) {
  return (
    <Tag
      color="blue"
      style={{ cursor: onClick ? 'pointer' : 'default' }}
      onClick={() => onClick?.(citation)}
    >
      [{citation.law_name} {citation.article_number}]
    </Tag>
  );
}
```

- [ ] **Step 4: 创建消息气泡组件 `scripts/web/src/components/MessageBubble.tsx`**

```tsx
import React from 'react';
import { Typography } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import CitationTag from './CitationTag';
import type { Message, Citation, Source } from '../types';

const { Text } = Typography;

interface Props {
  message: Message;
  onCitationClick?: (citation: Citation) => void;
}

export default function MessageBubble({ message, onCitationClick }: Props) {
  if (message.role === 'user') {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <div style={{
          maxWidth: '70%', background: '#1677ff', color: '#fff',
          padding: '8px 16px', borderRadius: 12, borderBottomRightRadius: 4,
        }}>
          {message.content}
        </div>
      </div>
    );
  }

  // assistant 消息：渲染 markdown + 内联引用替换
  const content = message.content || '';
  const hasSources = message.sources && message.sources.length > 0;

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        maxWidth: '85%', background: '#f5f5f5', padding: '8px 16px',
        borderRadius: 12, borderBottomLeftRadius: 4,
      }}>
        {content ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        ) : (
          <Text type="secondary">思考中...</Text>
        )}
        {hasSources && (
          <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {message.sources.map((s: Source, i: number) => (
              <CitationTag
                key={i}
                citation={{ source_idx: i, law_name: s.law_name, article_number: s.article_number, content: s.content }}
                onClick={onCitationClick}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: 创建来源面板组件 `scripts/web/src/components/SourcePanel.tsx`**

```tsx
import React from 'react';
import { Drawer, Typography, Empty } from 'antd';
import type { Source } from '../types';

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  sources: Source[];
  selectedSource: Source | null;
  onSelect: (source: Source) => void;
  onClose: () => void;
}

export default function SourcePanel({ open, sources, selectedSource, onSelect, onClose }: Props) {
  return (
    <Drawer
      title="法规来源"
      placement="right"
      width={420}
      open={open}
      onClose={onClose}
    >
      {sources.length === 0 ? (
        <Empty description="暂无来源" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {sources.map((s, i) => (
            <div
              key={i}
              onClick={() => onSelect(s)}
              style={{
                padding: 12, border: '1px solid #f0f0f0', borderRadius: 8,
                cursor: 'pointer',
                background: selectedSource === s ? '#e6f4ff' : '#fff',
                borderLeft: selectedSource === s ? '3px solid #1677ff' : '3px solid transparent',
              }}
            >
              <Text strong>
                [{i + 1}] {s.law_name}
              </Text>
              {s.article_number && (
                <Text type="secondary" style={{ marginLeft: 8 }}>{s.article_number}</Text>
              )}
              <Paragraph
                ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
                style={{ marginTop: 4, marginBottom: 0, fontSize: 13 }}
              >
                {s.content}
              </Paragraph>
            </div>
          ))}
        </div>
      )}
    </Drawer>
  );
}
```

- [ ] **Step 6: 创建对话面板组件 `scripts/web/src/components/ChatPanel.tsx`**

```tsx
import React, { useRef, useEffect } from 'react';
import { Input, Button, Radio, Space, Popconfirm } from 'antd';
import { SendOutlined, DeleteOutlined } from '@ant-design/icons';
import MessageBubble from './MessageBubble';
import SourcePanel from './SourcePanel';
import { useAskStore } from '../stores/askStore';
import type { Citation, Source } from '../types';

const { TextArea } = Input;

export default function ChatPanel() {
  const [input, setInput] = React.useState('');
  const [mode, setMode] = React.useState<'qa' | 'search'>('qa');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const {
    messages, streaming, currentSources,
    currentConversationId, conversations,
    sendMessage, selectConversation, deleteConversation, loadConversations,
  } = useAskStore();

  const [sourcePanelOpen, setSourcePanelOpen] = React.useState(false);
  const [selectedSource, setSelectedSource] = React.useState<Source | null>(null);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    const q = input.trim();
    if (!q || streaming) return;
    setInput('');
    sendMessage(q, mode);
  };

  const handleCitationClick = (citation: Citation) => {
    const source = currentSources.find(
      (s, i) => i === citation.source_idx,
    );
    if (source) {
      setSelectedSource(source);
      setSourcePanelOpen(true);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      {/* 左侧：对话历史列表 */}
      <div style={{ width: 220, borderRight: '1px solid #f0f0f0', overflow: 'auto' }}>
        <div style={{ padding: '8px 12px', fontWeight: 600, fontSize: 14 }}>对话历史</div>
        {conversations.map((conv) => (
          <div
            key={conv.id}
            onClick={() => selectConversation(conv.id)}
            style={{
              padding: '8px 12px', cursor: 'pointer',
              background: currentConversationId === conv.id ? '#e6f4ff' : '#fff',
              borderBottom: '1px solid #f5f5f5',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, fontSize: 13 }}>
              {conv.title || conv.id}
            </span>
            <Popconfirm
              title="确定删除？"
              onConfirm={(e) => { e?.stopPropagation(); deleteConversation(conv.id); }}
              onCancel={(e) => e?.stopPropagation()}
            >
              <Button
                type="text"
                size="small"
                icon={<DeleteOutlined />}
                onClick={(e) => e.stopPropagation()}
                style={{ color: '#999' }}
              />
            </Popconfirm>
          </div>
        ))}
      </div>

      {/* 中间：对话区域 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* 消息列表 */}
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px' }}>
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', color: '#999', marginTop: 100 }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>法规问答</div>
              <div>输入问题，检索保险法规并获取带引用的回答</div>
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              onCitationClick={handleCitationClick}
            />
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* 输入区 */}
        <div style={{ borderTop: '1px solid #f0f0f0', padding: '12px 24px' }}>
          <Space style={{ marginBottom: 8 }}>
            <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)} size="small">
              <Radio.Button value="qa">智能问答</Radio.Button>
              <Radio.Button value="search">精确检索</Radio.Button>
            </Radio.Group>
          </Space>
          <div style={{ display: 'flex', gap: 8 }}>
            <TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); handleSend(); } }}
              placeholder="输入法规相关问题..."
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={streaming}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={streaming}
              disabled={!input.trim()}
            />
          </div>
        </div>
      </div>

      {/* 来源面板 */}
      <SourcePanel
        open={sourcePanelOpen}
        sources={currentSources}
        selectedSource={selectedSource}
        onSelect={setSelectedSource}
        onClose={() => setSourcePanelOpen(false)}
      />
    </div>
  );
}
```

- [ ] **Step 7: 更新 `scripts/web/src/pages/AskPage.tsx`**

```tsx
import React from 'react';
import ChatPanel from '../components/ChatPanel';

export default function AskPage() {
  return (
    <div style={{ height: 'calc(100vh - 64px - 32px)' }}>
      <ChatPanel />
    </div>
  );
}
```

- [ ] **Step 8: 验证编译通过**

```bash
cd scripts/web && npx tsc --noEmit
```

Expected: 无错误

- [ ] **Step 9: Commit**

```bash
git add scripts/web/src/
git commit -m "feat(web): add ask page with chat panel, SSE streaming, and source drawer"
```

---

## Task 3: 知识库管理页面

**Files:**
- Create: `scripts/web/src/api/knowledge.ts`
- Modify: `scripts/web/src/pages/KnowledgePage.tsx`

- [ ] **Step 1: 创建 API 层 `scripts/web/src/api/knowledge.ts`**

```typescript
import client from './client';
import type { Document, IndexStatus, TaskStatus } from '../types';

export async function fetchDocuments(): Promise<Document[]> {
  const { data } = await client.get('/api/kb/documents');
  return data;
}

export async function importDocuments(filePattern: string, filePath?: string): Promise<{ task_id: string }> {
  const { data } = await client.post('/api/kb/documents/import', {
    file_path: filePath || undefined,
    file_pattern: filePattern,
  });
  return data;
}

export async function rebuildIndex(filePattern: string, force: boolean): Promise<{ task_id: string }> {
  const { data } = await client.post('/api/kb/documents/rebuild', {
    file_pattern: filePattern,
    force,
  });
  return data;
}

export async function fetchTaskStatus(taskId: string): Promise<TaskStatus> {
  const { data } = await client.get(`/api/kb/tasks/${taskId}`);
  return data;
}

export async function fetchDocumentPreview(name: string): Promise<{ name: string; content: string; total_chars: number }> {
  const { data } = await client.get(`/api/kb/documents/${encodeURIComponent(name)}/preview`);
  return data;
}

export async function fetchIndexStatus(): Promise<IndexStatus> {
  const { data } = await client.get('/api/kb/status');
  return data;
}
```

- [ ] **Step 2: 实现 `scripts/web/src/pages/KnowledgePage.tsx`**

```tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Button, Space, Tag, Modal, Input, Descriptions,
  Typography, message, Progress, Statistic, Row, Col, Popconfirm,
} from 'antd';
import {
  DatabaseOutlined, ReloadOutlined, ImportOutlined,
  EyeOutlined, SyncOutlined,
} from '@ant-design/icons';
import * as kbApi from '../api/knowledge';
import type { Document, IndexStatus } from '../types';

const { Title, Text, Paragraph } = Typography;

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<{ name: string; content: string; total_chars: number } | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<string>('');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [docs, status] = await Promise.all([
        kbApi.fetchDocuments(),
        kbApi.fetchIndexStatus(),
      ]);
      setDocuments(docs);
      setIndexStatus(status);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 轮询任务状态
  useEffect(() => {
    if (!taskId || taskStatus === 'completed' || taskStatus === 'failed') return;
    const timer = setInterval(async () => {
      try {
        const task = await kbApi.fetchTaskStatus(taskId);
        setTaskStatus(task.status);
        if (task.status === 'completed' || task.status === 'failed') {
          clearInterval(timer);
          if (task.status === 'completed') {
            message.success('操作完成');
            loadData();
          } else {
            message.error(`操作失败: ${task.progress}`);
          }
        }
      } catch { clearInterval(timer); }
    }, 2000);
    return () => clearInterval(timer);
  }, [taskId, taskStatus, loadData]);

  const handleImport = async () => {
    try {
      const { task_id } = await kbApi.importDocuments('*.md');
      setTaskId(task_id);
      setTaskStatus('pending');
      message.info('开始导入...');
    } catch (err) {
      message.error(`导入失败: ${err}`);
    }
  };

  const handleRebuild = async () => {
    try {
      const { task_id } = await kbApi.rebuildIndex('*.md', true);
      setTaskId(task_id);
      setTaskStatus('pending');
      message.info('开始重建索引...');
    } catch (err) {
      message.error(`重建失败: ${err}`);
    }
  };

  const handlePreview = async (name: string) => {
    try {
      const doc = await kbApi.fetchDocumentPreview(name);
      setPreviewDoc(doc);
    } catch (err) {
      message.error(`预览失败: ${err}`);
    }
  };

  const columns = [
    { title: '文档名称', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '条款数', dataIndex: 'clause_count', key: 'clause_count', width: 100,
      sorter: (a: Document, b: Document) => a.clause_count - b.clause_count,
    },
    {
      title: '文件大小', dataIndex: 'file_size', key: 'file_size', width: 120,
      render: (size: number) => size > 1024 ? `${(size / 1024).toFixed(1)} KB` : `${size} B`,
      sorter: (a: Document, b: Document) => a.file_size - b.file_size,
    },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: unknown, record: Document) => (
        <Button type="link" icon={<EyeOutlined />} onClick={() => handlePreview(record.name)}>
          预览
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>知识库管理</Title>

      {/* 状态概览 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card><Statistic title="文档数量" value={documents.length} prefix={<DatabaseOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="向量库文档" value={indexStatus?.document_count || 0} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="BM25 状态" value={indexStatus?.bm25?.loaded ? '已加载' : '未加载'} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="向量库状态" value={(indexStatus?.vector_db as Record<string, string>)?.status || '未知'} /></Card>
        </Col>
      </Row>

      {/* 操作栏 */}
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<ImportOutlined />} onClick={handleImport}
          loading={taskStatus === 'running' || taskStatus === 'pending'}>
          导入文档
        </Button>
        <Popconfirm title="确定重建索引？此操作会重新处理所有文档。" onConfirm={handleRebuild}>
          <Button icon={<SyncOutlined />} loading={taskStatus === 'running' || taskStatus === 'pending'}>
            重建索引
          </Button>
        </Popconfirm>
        <Button icon={<ReloadOutlined />} onClick={loadData}>刷新</Button>
      </Space>

      {/* 任务进度 */}
      {(taskStatus === 'pending' || taskStatus === 'running') && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Progress percent={taskStatus === 'pending' ? 0 : 50} status="active" />
          <Text type="secondary">{taskStatus === 'pending' ? '等待中...' : '处理中...'}</Text>
        </Card>
      )}

      {/* 文档列表 */}
      <Card>
        <Table
          dataSource={documents}
          columns={columns}
          rowKey="name"
          loading={loading}
          pagination={{ pageSize: 20 }}
          size="middle"
        />
      </Card>

      {/* 预览弹窗 */}
      <Modal
        title={previewDoc?.name || '文档预览'}
        open={!!previewDoc}
        onCancel={() => setPreviewDoc(null)}
        footer={null}
        width={700}
      >
        {previewDoc && (
          <>
            <Text type="secondary">总字符数: {previewDoc.total_chars}</Text>
            <Paragraph style={{ marginTop: 12, maxHeight: 500, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
              {previewDoc.content}
            </Paragraph>
          </>
        )}
      </Modal>
    </div>
  );
}
```

- [ ] **Step 3: 验证编译通过**

```bash
cd scripts/web && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add scripts/web/src/api/knowledge.ts scripts/web/src/pages/KnowledgePage.tsx
git commit -m "feat(web): add knowledge base management page with document list and import"
```

---

## Task 4: 评估数据集管理页面

**Files:**
- Create: `scripts/web/src/api/eval.ts`
- Modify: `scripts/web/src/pages/EvalDatasetPage.tsx`

- [ ] **Step 1: 创建 API 层 `scripts/web/src/api/eval.ts`**

```typescript
import client from './client';
import type {
  EvalSample, EvalSnapshot, EvalRun, SampleResult,
  ComplianceReport,
} from '../types';

// ── 数据集 ──────────────────────────────────────────

export async function fetchEvalSamples(params?: {
  question_type?: string;
  difficulty?: string;
  topic?: string;
}): Promise<EvalSample[]> {
  const { data } = await client.get('/api/eval/dataset', { params });
  return data;
}

export async function createEvalSample(sample: Partial<EvalSample>): Promise<EvalSample> {
  const { data } = await client.post('/api/eval/dataset/samples', sample);
  return data;
}

export async function updateEvalSample(id: string, sample: Partial<EvalSample>): Promise<EvalSample> {
  const { data } = await client.put(`/api/eval/dataset/samples/${id}`, { ...sample, id });
  return data;
}

export async function deleteEvalSample(id: string): Promise<void> {
  await client.delete(`/api/eval/dataset/samples/${id}`);
}

export async function importEvalSamples(samples: Partial<EvalSample>[]): Promise<{ imported: number; total: number }> {
  const { data } = await client.post('/api/eval/dataset/import', { samples });
  return data;
}

export async function fetchSnapshots(): Promise<EvalSnapshot[]> {
  const { data } = await client.get('/api/eval/dataset/snapshots');
  return data;
}

export async function createSnapshot(name: string, description: string): Promise<{ snapshot_id: string }> {
  const { data } = await client.post('/api/eval/dataset/snapshots', { name, description });
  return data;
}

export async function restoreSnapshot(snapshotId: string): Promise<{ restored: number }> {
  const { data } = await client.post(`/api/eval/dataset/snapshots/${snapshotId}/restore`);
  return data;
}

// ── 评估运行 ────────────────────────────────────────

export async function createEvalRun(config: {
  mode: 'retrieval' | 'generation' | 'full';
  top_k?: number;
  chunking?: string;
}): Promise<{ run_id: string }> {
  const { data } = await client.post('/api/eval/runs', config);
  return data;
}

export async function fetchEvalRunStatus(runId: string): Promise<EvalRun> {
  const { data } = await client.get(`/api/eval/runs/${runId}/status`);
  return data;
}

export async function fetchEvalRunReport(runId: string): Promise<Record<string, unknown>> {
  const { data } = await client.get(`/api/eval/runs/${runId}/report`);
  return data;
}

export async function fetchEvalRunDetails(runId: string): Promise<{
  run_id: string; mode: string; status: string; total_samples: number; details: SampleResult[];
}> {
  const { data } = await client.get(`/api/eval/runs/${runId}/details`);
  return data;
}

export async function fetchEvalRuns(): Promise<EvalRun[]> {
  const { data } = await client.get('/api/eval/runs');
  return data;
}

export async function compareEvalRuns(baselineId: string, compareId: string): Promise<{
  metrics_diff: Record<string, { baseline: number; compare: number; delta: number; pct_change: number }>;
  improved: string[];
  regressed: string[];
}> {
  const { data } = await client.post('/api/eval/runs/compare', { baseline_id: baselineId, compare_id: compareId });
  return data;
}

export async function exportEvalReport(runId: string, format: 'json' | 'md' = 'json'): Promise<Blob> {
  const { data } = await client.get(`/api/eval/runs/${runId}/export`, {
    params: { format },
    responseType: 'blob',
  });
  return data;
}
```

- [ ] **Step 2: 实现 `scripts/web/src/pages/EvalDatasetPage.tsx`**

```tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Button, Space, Tag, Modal, Form, Input, Select,
  Typography, message, Row, Col, Popconfirm, Descriptions,
} from 'antd';
import {
  PlusOutlined, ImportOutlined, SaveOutlined, RollbackOutlined,
} from '@ant-design/icons';
import * as evalApi from '../api/eval';
import type { EvalSample, EvalSnapshot } from '../types';

const { Title, Text } = Typography;

const QUESTION_TYPE_OPTIONS = [
  { value: 'factual', label: 'FACTUAL（事实类）' },
  { value: 'multi_hop', label: 'MULTI_HOP（多跳推理）' },
  { value: 'negative', label: 'NEGATIVE（否定类）' },
  { value: 'colloquial', label: 'COLLOQUIAL（口语类）' },
];

const DIFFICULTY_OPTIONS = [
  { value: 'easy', label: 'easy' },
  { value: 'medium', label: 'medium' },
  { value: 'hard', label: 'hard' },
];

const TYPE_COLORS: Record<string, string> = {
  factual: 'blue', multi_hop: 'purple', negative: 'red', colloquial: 'green',
};

export default function EvalDatasetPage() {
  const [samples, setSamples] = useState<EvalSample[]>([]);
  const [snapshots, setSnapshots] = useState<EvalSnapshot[]>([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<{ question_type?: string; difficulty?: string; topic?: string }>({});
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingSample, setEditingSample] = useState<Partial<EvalSample> | null>(null);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [snapshotModalOpen, setSnapshotModalOpen] = useState(false);
  const [snapshotName, setSnapshotName] = useState('');
  const [form] = Form.useForm();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [s, snap] = await Promise.all([
        evalApi.fetchEvalSamples(filters),
        evalApi.fetchSnapshots(),
      ]);
      setSamples(s);
      setSnapshots(snap);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreate = () => {
    setEditingSample(null);
    form.resetFields();
    setEditModalOpen(true);
  };

  const handleEdit = (record: EvalSample) => {
    setEditingSample(record);
    form.setFieldsValue(record);
    setEditModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      if (editingSample) {
        await evalApi.updateEvalSample(editingSample.id, values);
        message.success('更新成功');
      } else {
        await evalApi.createEvalSample(values);
        message.success('创建成功');
      }
      setEditModalOpen(false);
      loadData();
    } catch (err) {
      message.error(`保存失败: ${err}`);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await evalApi.deleteEvalSample(id);
      message.success('删除成功');
      loadData();
    } catch (err) {
      message.error(`删除失败: ${err}`);
    }
  };

  const handleImport = async () => {
    try {
      const data = JSON.parse(importText);
      const items = Array.isArray(data) ? data : (data.samples || []);
      const result = await evalApi.importEvalSamples(items);
      message.success(`导入 ${result.imported} 条，跳过 ${result.skipped} 条`);
      setImportModalOpen(false);
      setImportText('');
      loadData();
    } catch (err) {
      message.error(`导入失败: ${err}`);
    }
  };

  const handleCreateSnapshot = async () => {
    if (!snapshotName.trim()) {
      message.warning('请输入快照名称');
      return;
    }
    try {
      await evalApi.createSnapshot(snapshotName, '');
      message.success('快照创建成功');
      setSnapshotModalOpen(false);
      setSnapshotName('');
      loadData();
    } catch (err) {
      message.error(`创建失败: ${err}`);
    }
  };

  const handleRestore = async (snapId: string) => {
    try {
      const result = await evalApi.restoreSnapshot(snapId);
      message.success(`已恢复 ${result.restored} 条数据`);
      loadData();
    } catch (err) {
      message.error(`恢复失败: ${err}`);
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80 },
    { title: '问题', dataIndex: 'question', key: 'question', ellipsis: true },
    {
      title: '类型', dataIndex: 'question_type', key: 'question_type', width: 140,
      render: (t: string) => <Tag color={TYPE_COLORS[t] || 'default'}>{t}</Tag>,
    },
    { title: '难度', dataIndex: 'difficulty', key: 'difficulty', width: 80 },
    { title: '主题', dataIndex: 'topic', key: 'topic', width: 100 },
    {
      title: '操作', key: 'action', width: 150,
      render: (_: unknown, record: EvalSample) => (
        <Space>
          <Button type="link" size="small" onClick={() => handleEdit(record)}>编辑</Button>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>评估数据集管理</Title>

      {/* 筛选栏 */}
      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="问题类型" allowClear style={{ width: 160 }}
          value={filters.question_type}
          onChange={(v) => setFilters({ ...filters, question_type: v })}
          options={QUESTION_TYPE_OPTIONS}
        />
        <Select
          placeholder="难度" allowClear style={{ width: 100 }}
          value={filters.difficulty}
          onChange={(v) => setFilters({ ...filters, difficulty: v })}
          options={DIFFICULTY_OPTIONS}
        />
        <Input
          placeholder="主题筛选" style={{ width: 120 }}
          value={filters.topic}
          onChange={(e) => setFilters({ ...filters, topic: e.target.value || undefined })}
          onPressEnter={loadData}
        />
      </Space>

      {/* 操作栏 */}
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新增</Button>
        <Button icon={<ImportOutlined />} onClick={() => setImportModalOpen(true)}>批量导入</Button>
        <Button icon={<SaveOutlined />} onClick={() => setSnapshotModalOpen(true)}>创建快照</Button>
      </Space>

      <Row gutter={16}>
        <Col span={16}>
          <Card>
            <Table
              dataSource={samples}
              columns={columns}
              rowKey="id"
              loading={loading}
              pagination={{ pageSize: 20 }}
              size="middle"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="快照历史" size="small">
            {snapshots.length === 0 ? (
              <Text type="secondary">暂无快照</Text>
            ) : (
              snapshots.map((snap) => (
                <div key={snap.id} style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <Text strong>{snap.name}</Text>
                    <Text type="secondary" style={{ marginLeft: 8 }}>{snap.sample_count} 条</Text>
                    <br />
                    <Text type="secondary" style={{ fontSize: 12 }}>{snap.created_at}</Text>
                  </div>
                  <Popconfirm title={`确定恢复到 ${snap.name}？当前数据将被覆盖。`} onConfirm={() => handleRestore(snap.id)}>
                    <Button type="link" size="small" icon={<RollbackOutlined />}>恢复</Button>
                  </Popconfirm>
                </div>
              ))
            )}
          </Card>
        </Col>
      </Row>

      {/* 编辑弹窗 */}
      <Modal
        title={editingSample ? '编辑评测问题' : '新增评测问题'}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={handleSave}
        width={600}
      >
        <Form form={form} layout="vertical">
          {!editingSample && (
            <Form.Item name="id" label="ID" rules={[{ required: true }]}>
              <Input placeholder="如 f031" />
            </Form.Item>
          )}
          <Form.Item name="question" label="问题" rules={[{ required: true }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="ground_truth" label="标准答案">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="question_type" label="问题类型" rules={[{ required: true }]}>
            <Select options={QUESTION_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="difficulty" label="难度">
            <Select options={DIFFICULTY_OPTIONS} />
          </Form.Item>
          <Form.Item name="topic" label="主题">
            <Input placeholder="如 健康保险" />
          </Form.Item>
          <Form.Item name="evidence_docs" label="证据文档（JSON 数组）">
            <Input.TextArea rows={2} placeholder='["01_保险法相关监管规定.md"]' />
          </Form.Item>
          <Form.Item name="evidence_keywords" label="证据关键词（JSON 数组）">
            <Input.TextArea rows={2} placeholder='["等待期", "180天"]' />
          </Form.Item>
        </Form>
      </Modal>

      {/* 批量导入弹窗 */}
      <Modal
        title="批量导入"
        open={importModalOpen}
        onCancel={() => setImportModalOpen(false)}
        onOk={handleImport}
        width={600}
      >
        <Text type="secondary">粘贴 JSON 数组或 {"{\"samples\": [...]"}  格式</Text>
        <Input.TextArea
          rows={12}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          placeholder='[{"id": "f031", "question": "...", ...}]'
          style={{ marginTop: 8, fontFamily: 'monospace' }}
        />
      </Modal>

      {/* 创建快照弹窗 */}
      <Modal
        title="创建快照"
        open={snapshotModalOpen}
        onCancel={() => setSnapshotModalOpen(false)}
        onOk={handleCreateSnapshot}
      >
        <Input
          placeholder="快照名称，如 v1.0"
          value={snapshotName}
          onChange={(e) => setSnapshotName(e.target.value)}
          onPressEnter={handleCreateSnapshot}
        />
      </Modal>
    </div>
  );
}
```

- [ ] **Step 3: 验证编译通过**

```bash
cd scripts/web && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add scripts/web/src/api/eval.ts scripts/web/src/pages/EvalDatasetPage.tsx
git commit -m "feat(web): add eval dataset management page with CRUD, import, and snapshots"
```

---

## Task 5: 评估运行与结果页面

**Files:**
- Create: `scripts/web/src/components/MetricsChart.tsx`
- Modify: `scripts/web/src/pages/EvalRunPage.tsx`

- [ ] **Step 1: 创建指标图表组件 `scripts/web/src/components/MetricsChart.tsx`**

```tsx
import React from 'react';
import { Card, Row, Col, Statistic, Table, Tag } from 'antd';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts';

interface MetricItem {
  name: string;
  value: number;
  fullMark: number;
}

interface Props {
  metrics: Record<string, number | Record<string, number>>;
  title?: string;
}

export function formatMetric(value: number | undefined): string {
  if (value === undefined || value === null) return '-';
  return (value * 100).toFixed(1) + '%';
}

function extractMetricItems(metrics: Record<string, number | Record<string, number>>): MetricItem[] {
  const items: MetricItem[] = [];
  for (const [key, val] of Object.entries(metrics)) {
    if (typeof val === 'number') {
      items.push({ name: key, value: val, fullMark: 1 });
    }
  }
  return items;
}

export default function MetricsChart({ metrics, title = '评估指标' }: Props) {
  const items = extractMetricItems(metrics);
  const stats = items.filter((i) => i.value !== undefined);

  // 按类型分组指标
  const retrievalMetrics = items.filter((i) =>
    ['precision_at_k', 'recall_at_k', 'mrr', 'ndcg'].includes(i.name),
  );
  const generationMetrics = items.filter((i) =>
    ['faithfulness', 'answer_relevancy', 'answer_correctness'].includes(i.name),
  );

  return (
    <Card title={title} size="small">
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {stats.slice(0, 6).map((item) => (
          <Col span={4} key={item.name}>
            <Statistic
              title={item.name}
              value={(item.value * 100).toFixed(1)}
              suffix="%"
              valueStyle={{ fontSize: 16 }}
            />
          </Col>
        ))}
      </Row>

      {retrievalMetrics.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h4 style={{ marginBottom: 8 }}>检索指标</h4>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={retrievalMetrics.map((i) => ({ name: i.name, value: Number((i.value * 100).toFixed(1)) }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis domain={[0, 100]} />
              <Tooltip formatter={(v: number) => `${v}%`} />
              <Bar dataKey="value" fill="#1677ff" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {generationMetrics.length > 0 && (
        <div>
          <h4 style={{ marginBottom: 8 }}>生成指标</h4>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={generationMetrics.map((i) => ({ name: i.name, value: Number((i.value * 100).toFixed(1)) }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis domain={[0, 100]} />
              <Tooltip formatter={(v: number) => `${v}%`} />
              <Bar dataKey="value" fill="#52c41a" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
```

- [ ] **Step 2: 实现 `scripts/web/src/pages/EvalRunPage.tsx`**

```tsx
import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Button, Space, Select, Tag, Modal, Typography,
  message, Progress, Row, Col, Descriptions, Spin,
} from 'antd';
import {
  PlayCircleOutlined, DownloadOutlined, SwapOutlined,
} from '@ant-design/icons';
import * as evalApi from '../api/eval';
import MetricsChart, { formatMetric } from '../components/MetricsChart';
import type { EvalRun, SampleResult } from '../types';

const { Title, Text } = Typography;

export default function EvalRunPage() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedRun, setSelectedRun] = useState<EvalRun | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [details, setDetails] = useState<SampleResult[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [compareModalOpen, setCompareModalOpen] = useState(false);
  const [compareIds, setCompareIds] = useState<{ baseline: string; compare: string }>({ baseline: '', compare: '' });
  const [compareResult, setCompareResult] = useState<Record<string, unknown> | null>(null);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await evalApi.fetchEvalRuns();
      setRuns(data);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  // 轮询进行中的 run
  useEffect(() => {
    const runningRuns = runs.filter((r) => r.status === 'running' || r.status === 'pending');
    if (runningRuns.length === 0) return;
    const timer = setInterval(async () => {
      await loadRuns();
    }, 3000);
    return () => clearInterval(timer);
  }, [runs, loadRuns]);

  const handleStartRun = async (mode: 'retrieval' | 'generation' | 'full') => {
    try {
      const { run_id } = await evalApi.createEvalRun({ mode, top_k: 5 });
      message.success(`评估任务已创建: ${run_id}`);
      loadRuns();
    } catch (err) {
      message.error(`启动失败: ${err}`);
    }
  };

  const handleSelectRun = async (run: EvalRun) => {
    setSelectedRun(run);
    if (run.status === 'completed') {
      try {
        const [rpt, det] = await Promise.all([
          evalApi.fetchEvalRunReport(run.id),
          evalApi.fetchEvalRunDetails(run.id),
        ]);
        setReport(rpt);
        setDetails(det.details);
      } catch (err) {
        message.error(`加载报告失败: ${err}`);
      }
    } else {
      setReport(null);
      setDetails([]);
    }
  };

  const handleExport = async (runId: string, format: 'json' | 'md') => {
    try {
      const blob = await evalApi.exportEvalReport(runId, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `eval_report_${runId}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      message.error(`导出失败: ${err}`);
    }
  };

  const handleCompare = async () => {
    if (!compareIds.baseline || !compareIds.compare) {
      message.warning('请选择两个评估运行');
      return;
    }
    try {
      const result = await evalApi.compareEvalRuns(compareIds.baseline, compareIds.compare);
      setCompareResult(result);
    } catch (err) {
      message.error(`对比失败: ${err}`);
    }
  };

  const STATUS_MAP: Record<string, { color: string; label: string }> = {
    pending: { color: 'default', label: '等待中' },
    running: { color: 'processing', label: '运行中' },
    completed: { color: 'success', label: '已完成' },
    failed: { color: 'error', label: '失败' },
  };

  const runColumns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 140, ellipsis: true },
    {
      title: '模式', dataIndex: 'mode', key: 'mode', width: 100,
      render: (m: string) => <Tag>{m}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => {
        const info = STATUS_MAP[s] || { color: 'default', label: s };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    {
      title: '进度', key: 'progress', width: 150,
      render: (_: unknown, r: EvalRun) => {
        if (r.status === 'completed') return <Text>100%</Text>;
        if (r.total > 0) return <Progress percent={Math.round((r.progress / r.total) * 100)} size="small" />;
        return <Text type="secondary">-</Text>;
      },
    },
    { title: '启动时间', dataIndex: 'started_at', key: 'started_at', width: 180, ellipsis: true },
    { title: '完成时间', dataIndex: 'finished_at', key: 'finished_at', width: 180 },
  ];

  const detailColumns = [
    { title: '样本ID', dataIndex: 'sample_id', key: 'sample_id', width: 80 },
    {
      title: '问题', dataIndex: 'question', key: 'question', ellipsis: true,
      render: (_: unknown, r: SampleResult) => {
        // question 不在 result 中，需要从样本获取，这里先显示 ID
        return r.sample_id;
      },
    },
    {
      title: 'Precision', dataIndex: 'precision', key: 'precision', width: 90,
      render: (_: unknown, r: SampleResult) => formatMetric(r.retrieval_metrics.precision),
    },
    {
      title: 'Recall', dataIndex: 'recall', key: 'recall', width: 90,
      render: (_: unknown, r: SampleResult) => formatMetric(r.retrieval_metrics.recall),
    },
    {
      title: 'MRR', dataIndex: 'mrr', key: 'mrr', width: 90,
      render: (_: unknown, r: SampleResult) => formatMetric(r.retrieval_metrics.mrr),
    },
    {
      title: 'NDCG', dataIndex: 'ndcg', key: 'ndcg', width: 90,
      render: (_: unknown, r: SampleResult) => formatMetric(r.retrieval_metrics.ndcg),
    },
    {
      title: 'Faithfulness', dataIndex: 'faithfulness', key: 'faithfulness', width: 110,
      render: (_: unknown, r: SampleResult) => formatMetric(r.generation_metrics.faithfulness),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>评估运行与结果</Title>

      {/* 启动评估 */}
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<PlayCircleOutlined />} onClick={() => handleStartRun('retrieval')}>检索评估</Button>
        <Button icon={<PlayCircleOutlined />} onClick={() => handleStartRun('generation')}>生成评估</Button>
        <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => handleStartRun('full')}>完整评估</Button>
        <Button icon={<SwapOutlined />} onClick={() => setCompareModalOpen(true)}>版本对比</Button>
      </Space>

      <Row gutter={16}>
        {/* 左侧：运行列表 */}
        <Col span={10}>
          <Card title="评估历史" size="small">
            <Table
              dataSource={runs}
              columns={runColumns}
              rowKey="id"
              loading={loading}
              size="small"
              pagination={{ pageSize: 15 }}
              onRow={(record) => ({
                onClick: () => handleSelectRun(record),
                style: {
                  cursor: 'pointer',
                  background: selectedRun?.id === record.id ? '#e6f4ff' : undefined,
                },
              })}
            />
          </Card>
        </Col>

        {/* 右侧：报告详情 */}
        <Col span={14}>
          {selectedRun ? (
            <>
              <Descriptions title={`评估报告 - ${selectedRun.id}`} size="small" style={{ marginBottom: 16 }}>
                <Descriptions.Item label="模式">{selectedRun.mode}</Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={STATUS_MAP[selectedRun.status]?.color}>{STATUS_MAP[selectedRun.status]?.label}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="启动时间">{selectedRun.started_at}</Descriptions.Item>
                {selectedRun.status === 'completed' && (
                  <Descriptions.Item label="操作">
                    <Space>
                      <Button size="small" icon={<DownloadOutlined />}
                        onClick={() => handleExport(selectedRun.id, 'json')}>JSON</Button>
                      <Button size="small" icon={<DownloadOutlined />}
                        onClick={() => handleExport(selectedRun.id, 'md')}>Markdown</Button>
                    </Space>
                  </Descriptions.Item>
                )}
              </Descriptions>

              {report && (
                <>
                  <MetricsChart metrics={report as Record<string, number>} title="聚合指标" />
                  <Card title="逐题详情" size="small" style={{ marginTop: 16 }}>
                    <Spin spinning={detailLoading}>
                      <Table
                        dataSource={details}
                        columns={detailColumns}
                        rowKey="id"
                        size="small"
                        pagination={{ pageSize: 20 }}
                        expandable={{
                          expandedRowRender: (record) => (
                            <div>
                              <Text strong>生成回答：</Text>
                              <div style={{ marginTop: 4, padding: 8, background: '#f5f5f5', borderRadius: 4 }}>
                                {record.generated_answer || '-'}
                              </div>
                              {record.retrieved_docs.length > 0 && (
                                <>
                                  <Text strong style={{ marginTop: 8, display: 'block' }}>检索结果：</Text>
                                  {record.retrieved_docs.map((doc, i) => (
                                    <div key={i} style={{ padding: 4, fontSize: 13 }}>
                                      [{i + 1}] {doc.law_name} {doc.article_number}
                                    </div>
                                  ))}
                                </>
                              )}
                            </div>
                          ),
                        }}
                      />
                    </Spin>
                  </Card>
                </>
              )}
            </>
          ) : (
            <Card style={{ textAlign: 'center', padding: 40 }}>
              <Text type="secondary">选择一个评估运行查看详情</Text>
            </Card>
          )}
        </Col>
      </Row>

      {/* 版本对比弹窗 */}
      <Modal
        title="版本对比"
        open={compareModalOpen}
        onCancel={() => { setCompareModalOpen(false); setCompareResult(null); }}
        width={700}
        footer={null}
      >
        <Space style={{ marginBottom: 16 }}>
          <Select
            placeholder="基准版本" style={{ width: 200 }}
            value={compareIds.baseline || undefined}
            onChange={(v) => setCompareIds({ ...compareIds, baseline: v })}
            options={runs.filter((r) => r.status === 'completed').map((r) => ({
              value: r.id, label: `${r.id} (${r.mode}, ${r.started_at?.slice(0, 10)})`,
            }))}
          />
          <span>vs</span>
          <Select
            placeholder="对比版本" style={{ width: 200 }}
            value={compareIds.compare || undefined}
            onChange={(v) => setCompareIds({ ...compareIds, compare: v })}
            options={runs.filter((r) => r.status === 'completed').map((r) => ({
              value: r.id, label: `${r.id} (${r.mode}, ${r.started_at?.slice(0, 10)})`,
            }))}
          />
          <Button type="primary" onClick={handleCompare}>对比</Button>
        </Space>

        {compareResult && (
          <Table
            dataSource={Object.entries(compareResult.metrics_diff || {}).map(([key, val]) => ({
              key,
              metric: key,
              ...(val as Record<string, number>),
              trend: (val as Record<string, number>).delta > 0 ? '↑' : (val as Record<string, number>).delta < 0 ? '↓' : '→',
            }))}
            columns={[
              { title: '指标', dataIndex: 'metric', key: 'metric' },
              { title: '基准', dataIndex: 'baseline', key: 'baseline', render: (v: number) => (v * 100).toFixed(2) + '%' },
              { title: '对比', dataIndex: 'compare', key: 'compare', render: (v: number) => (v * 100).toFixed(2) + '%' },
              { title: '变化', dataIndex: 'pct_change', key: 'pct_change',
                render: (v: number) => <span style={{ color: v > 0 ? '#52c41a' : v < 0 ? '#ff4d4f' : '#999' }}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span> },
              { title: '趋势', dataIndex: 'trend', key: 'trend', width: 60,
                render: (v: string) => <span style={{ color: v === '↑' ? '#52c41a' : v === '↓' ? '#ff4d4f' : '#999', fontWeight: 600 }}>{v}</span> },
            ]}
            size="small"
            pagination={false}
          />
        )}
      </Modal>
    </div>
  );
}
```

- [ ] **Step 3: 验证编译通过**

```bash
cd scripts/web && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add scripts/web/src/components/MetricsChart.tsx scripts/web/src/pages/EvalRunPage.tsx
git commit -m "feat(web): add eval run page with metrics charts, details, and comparison"
```

---

## Task 6: 合规检查页面

**Files:**
- Create: `scripts/web/src/api/compliance.ts`
- Modify: `scripts/web/src/pages/CompliancePage.tsx`

- [ ] **Step 1: 创建 API 层 `scripts/web/src/api/compliance.ts`**

```typescript
import client from './client';
import type { ComplianceReport } from '../types';

export async function checkProduct(params: {
  product_name: string;
  category: string;
  params: Record<string, unknown>;
}): Promise<ComplianceReport> {
  const { data } = await client.post('/api/compliance/check/product', params);
  return data;
}

export async function checkDocument(params: {
  document_content: string;
  product_name?: string;
}): Promise<ComplianceReport> {
  const { data } = await client.post('/api/compliance/check/document', params);
  return data;
}

export async function fetchComplianceReports(): Promise<ComplianceReport[]> {
  const { data } = await client.get('/api/compliance/reports');
  return data;
}

export async function fetchComplianceReport(id: string): Promise<ComplianceReport> {
  const { data } = await client.get(`/api/compliance/reports/${id}`);
  return data;
}
```

- [ ] **Step 2: 实现 `scripts/web/src/pages/CompliancePage.tsx`**

```tsx
import React, { useState, useEffect } from 'react';
import {
  Card, Form, Input, Button, Table, Tag, Typography,
  message, Tabs, Space, Descriptions, Spin, List,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  HistoryOutlined,
} from '@ant-design/icons';
import * as complianceApi from '../api/compliance';
import type { ComplianceReport, ComplianceItem } from '../types';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

const STATUS_CONFIG: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  compliant: { color: 'success', icon: <CheckCircleOutlined />, label: '合规' },
  non_compliant: { color: 'error', icon: <CloseCircleOutlined />, label: '不合规' },
  attention: { color: 'warning', icon: <ExclamationCircleOutlined />, label: '需关注' },
};

export default function CompliancePage() {
  const [activeTab, setActiveTab] = useState('product');
  const [productForm] = Form.useForm();
  const [docForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [currentReport, setCurrentReport] = useState<ComplianceReport | null>(null);
  const [history, setHistory] = useState<ComplianceReport[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    loadHistory();
  }, []);

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const data = await complianceApi.fetchComplianceReports();
      setHistory(data);
    } catch { /* ignore */ }
    finally {
      setHistoryLoading(false);
    }
  };

  const handleProductCheck = async () => {
    try {
      const values = await productForm.validateFields();
      setLoading(true);
      const report = await complianceApi.checkProduct({
        product_name: values.product_name,
        category: values.category,
        params: parseParams(values.params_text),
      });
      setCurrentReport(report);
      message.success('检查完成');
      loadHistory();
    } catch (err) {
      message.error(`检查失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDocumentCheck = async () => {
    try {
      const values = await docForm.validateFields();
      setLoading(true);
      const report = await complianceApi.checkDocument({
        document_content: values.document_content,
        product_name: values.product_name || undefined,
      });
      setCurrentReport(report);
      message.success('检查完成');
      loadHistory();
    } catch (err) {
      message.error(`检查失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  const parseParams = (text: string): Record<string, unknown> => {
    const params: Record<string, unknown> = {};
    text.split('\n').forEach((line) => {
      const [key, ...vals] = line.split(':');
      if (key && vals.length > 0) {
        params[key.trim()] = vals.join(':').trim();
      }
    });
    return params;
  };

  const itemColumns = [
    {
      title: '检查项', dataIndex: 'param', key: 'param', width: 120,
    },
    {
      title: '产品值', dataIndex: 'value', key: 'value', width: 120,
    },
    {
      title: '法规要求', dataIndex: 'requirement', key: 'requirement', ellipsis: true,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => {
        const cfg = STATUS_CONFIG[s] || STATUS_CONFIG.attention;
        return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>;
      },
    },
    {
      title: '法规来源', dataIndex: 'source', key: 'source', width: 150, ellipsis: true,
    },
    {
      title: '建议', dataIndex: 'suggestion', key: 'suggestion', ellipsis: true,
    },
  ];

  const result = currentReport?.result;
  const summary = result?.summary;

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>合规检查助手</Title>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'product',
            label: '产品参数检查',
            children: (
              <Card title="输入产品参数" size="small" style={{ marginBottom: 16 }}>
                <Form form={productForm} layout="vertical">
                  <Form.Item name="product_name" label="产品名称" rules={[{ required: true }]}>
                    <Input placeholder="如：XX健康保险" />
                  </Form.Item>
                  <Form.Item name="category" label="险种类型" rules={[{ required: true }]}>
                    <Input placeholder="如：健康险、寿险、财产险" />
                  </Form.Item>
                  <Form.Item name="params_text" label="产品参数" rules={[{ required: true }]}
                    extra="每行一个参数，格式：参数名: 值，如：等待期: 90天">
                    <TextArea rows={6} placeholder={`等待期: 90天\n免赔额: 0元\n保险期间: 1年\n缴费方式: 年缴`} />
                  </Form.Item>
                  <Button type="primary" onClick={handleProductCheck} loading={loading}>
                    开始检查
                  </Button>
                </Form>
              </Card>
            ),
          },
          {
            key: 'document',
            label: '条款文档审查',
            children: (
              <Card title="上传条款文档" size="small" style={{ marginBottom: 16 }}>
                <Form form={docForm} layout="vertical">
                  <Form.Item name="product_name" label="产品名称（可选）">
                    <Input placeholder="如：XX健康保险" />
                  </Form.Item>
                  <Form.Item name="document_content" label="条款内容" rules={[{ required: true }]}>
                    <TextArea rows={10} placeholder="粘贴保险条款文档内容..." />
                  </Form.Item>
                  <Button type="primary" onClick={handleDocumentCheck} loading={loading}>
                    开始审查
                  </Button>
                </Form>
              </Card>
            ),
          },
          {
            key: 'history',
            label: <span><HistoryOutlined /> 检查历史</span>,
            children: (
              <Table
                dataSource={history}
                loading={historyLoading}
                rowKey="id"
                size="small"
                pagination={{ pageSize: 10 }}
                onRow={(record) => ({
                  onClick: () => setCurrentReport(record),
                  style: { cursor: 'pointer' },
                })}
                columns={[
                  { title: '产品名称', dataIndex: 'product_name', key: 'product_name' },
                  { title: '险种', dataIndex: 'category', key: 'category' },
                  {
                    title: '模式', dataIndex: 'mode', key: 'mode', width: 100,
                    render: (m: string) => m === 'product' ? '参数检查' : '文档审查',
                  },
                  { title: '检查时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
                ]}
              />
            ),
          },
        ]}
      />

      {/* 检查结果 */}
      {result && summary && (
        <Card title={`检查报告 - ${currentReport?.product_name || ''}`} style={{ marginTop: 16 }}>
          <Descriptions size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="模式">
              {currentReport?.mode === 'product' ? '产品参数检查' : '条款文档审查'}
            </Descriptions.Item>
            <Descriptions.Item label="检查时间">{currentReport?.created_at}</Descriptions.Item>
          </Descriptions>

          <Space size="large" style={{ marginBottom: 16 }}>
            <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: 14, padding: '4px 12px' }}>
              合规 {summary.compliant} 项
            </Tag>
            <Tag color="error" icon={<CloseCircleOutlined />} style={{ fontSize: 14, padding: '4px 12px' }}>
              不合规 {summary.non_compliant} 项
            </Tag>
            <Tag color="warning" icon={<ExclamationCircleOutlined />} style={{ fontSize: 14, padding: '4px 12px' }}>
              需关注 {summary.attention} 项
            </Tag>
          </Space>

          <Table
            dataSource={result.items || []}
            columns={itemColumns}
            rowKey={(r) => r.param}
            size="middle"
            pagination={false}
            rowClassName={(record) => {
              if (record.status === 'non_compliant') return 'ant-table-row-error';
              return '';
            }}
          />
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 3: 验证编译通过**

```bash
cd scripts/web && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add scripts/web/src/api/compliance.ts scripts/web/src/pages/CompliancePage.tsx
git commit -m "feat(web): add compliance check page with product and document modes"
```

---

## Task 7: 全局样式与构建优化

**Files:**
- Modify: `scripts/web/src/index.css` (全局样式)
- Modify: `scripts/web/src/main.tsx`
- Modify: `scripts/web/vite.config.ts` (API 代理)

- [ ] **Step 1: 配置 Vite 代理 `scripts/web/vite.config.ts`**

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
```

- [ ] **Step 2: 全局样式 `scripts/web/src/index.css`**

```css
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

/* 不合规行高亮 */
.ant-table-row-error {
  background: #fff2f0 !important;
}

/* 消息气泡内 markdown 样式 */
.ant-typography p {
  margin-bottom: 4px;
}

/* 滚动条美化 */
::-webkit-scrollbar {
  width: 6px;
}
::-webkit-scrollbar-thumb {
  background: #d9d9d9;
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: #bfbfbf;
}
```

- [ ] **Step 3: 更新 `scripts/web/src/main.tsx`**

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 4: 验证构建**

```bash
cd scripts/web && npm run build
```

Expected: 构建成功，`dist/` 目录生成

- [ ] **Step 5: Commit**

```bash
git add scripts/web/
git commit -m "feat(web): add global styles, vite proxy config, and build optimization"
```

---

## Task 8: 集成验证

**Files:** 无新文件

- [ ] **Step 1: 启动后端 + 前端，验证端到端**

```bash
# 终端 1：启动后端
cd scripts && python run_api.py &

# 终端 2：启动前端
cd scripts/web && npm run dev &
```

打开 http://localhost:3000 验证：
- [ ] 侧边栏导航正常切换
- [ ] 知识库页面显示文档列表
- [ ] 评估数据集页面显示 30 条默认数据
- [ ] 合规检查页面表单可填写

- [ ] **Step 2: TypeScript 类型检查**

```bash
cd scripts/web && npx tsc --noEmit
```

- [ ] **Step 3: 构建产物检查**

```bash
cd scripts/web && npm run build && ls dist/
```

Expected: `index.html`, `assets/` 目录存在

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(web): complete frontend implementation - all 4 modules verified"
```

---

## Self-Review Checklist

| # | 检查项 | Task |
|---|--------|------|
| 1 | 项目脚手架 + 布局 + 路由 + 类型定义 | Task 1 |
| 2 | 法规问答：对话面板 + SSE 流式 + 引用标签 + 来源抽屉 | Task 2 |
| 3 | 知识库：文档列表 + 导入/重建 + 预览 + 索引状态 | Task 3 |
| 4 | 评估数据集：CRUD + 筛选 + 批量导入 + 快照回滚 | Task 4 |
| 5 | 评估运行：启动 + 状态轮询 + 指标图表 + 逐题详情 + 对比 + 导出 | Task 5 |
| 6 | 合规检查：产品参数 + 条款文档 + 报告历史 + 结果展示 | Task 6 |
| 7 | Vite 代理 + 全局样式 + 构建优化 | Task 7 |
| 8 | 端到端集成验证 | Task 8 |
| 9 | 全部中文 UI | 全部 Task |
| 10 | TypeScript 类型安全 | Task 1 (types/index.ts) |
