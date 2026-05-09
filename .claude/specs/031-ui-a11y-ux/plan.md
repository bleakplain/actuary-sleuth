# Implementation Plan: UI Accessibility & UX Compliance

**Branch**: `031-ui-a11y-ux` | **Date**: 2026-05-09 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

将 actuary-sleuth 前端从 a11y 基线近零提升至 WCAG 2.1 AA 合规，涵盖：入口修正(lang/skip link/语义 HTML)、ARIA 属性补全、焦点管理、路由级 ErrorBoundary、Skeleton 加载、React.lazy 代码拆分、暗色模式、移动端可访问性增强、表单/破坏性操作保护、动画/排版打磨。零新增 npm 依赖，全部基于 antd v6 内置能力和 React 标准库。

## Technical Context

**Language/Version**: TypeScript 5.9 + React 19
**Primary Dependencies**: antd ^6.3.4, react ^19.2.4, react-router-dom ^7.13.2, zustand ^5.0.12, vite ^8.0.1 (全部已安装，零新增)
**Testing**: vitest + playwright (已有配置)
**Performance Goals**: 初始 chunk 仅含 AskPage + shared; Lighthouse a11y ≥ 90
**Constraints**: 不重写 antd 内部 a11y；不引入新 npm 依赖；暗色用 antd darkAlgorithm；skeleton 用 antd Skeleton

## Constitution Check

- [x] **Library-First**: 全部方案基于 antd 内置能力（`<Skeleton>`、`theme.darkAlgorithm`、Modal focus trap）和 React 标准库（`React.lazy`、`Suspense`）。零新增依赖。
- [x] **测试优先**: 每个 Phase 含 playwright e2e 验证步骤。新增 hooks/components 有 vitest 单元测试。
- [x] **简单优先**: ErrorBoundary 用 HOC 包裹（最简方案）；focus trap 依赖 antd 内置，仅自定义弹窗补自实现 hook。
- [x] **显式优于隐式**: aria-label 均显式声明；theme 切换用显式 `isDark` state 而非隐式 CSS 类。
- [x] **可追溯性**: 每个 Phase 标注对应 spec.md User Story 和 FR 编号。
- [x] **独立可测试**: 每个 US 的 Phase 有 Checkpoint，可独立验证。

## Project Structure

### Documentation

```text
.claude/specs/031-ui-a11y-ux/
├── spec.md
├── research.md
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code (新增/修改)

```text
scripts/web/src/
├── index.html                              # 修改: lang, meta
├── index.css                               # 修改: reduced-motion, focus-visible, typography
├── App.tsx                                 # 修改: lazy routes, ErrorBoundary, theme, SkipLink
├── main.tsx                                # 修改: 无
├── theme.ts                                # 修改: darkTheme + getTheme
├── components/
│   ├── SkipLink.tsx                        # 新增
│   ├── PageErrorBoundary.tsx               # 新增
│   ├── AppLayout.tsx                       # 修改: nav/main 语义化, tab bar a11y
│   ├── ChatPanel.tsx                       # 修改: aria-live, aria-label, autocomplete, focus
│   ├── MessageBubble.tsx                   # 修改: article, aria-label, 颜色 token
│   ├── CopyBtn.tsx                         # 修改: button 元素, aria-label
│   ├── CitationTag.tsx                     # 修改: role/tabIndex
│   ├── TracePanel.tsx                      # 修改: role/tabIndex/onKeyDown, 颜色
│   ├── MetricsChart.tsx                    # 修改: aria-hidden SVG, 颜色 token
│   ├── SourcePanel.tsx                     # 修改: role/tabIndex
│   ├── DocumentViewer.tsx                  # 修改: token 背景色
│   ├── FeedbackButtons.tsx                 # 修改: aria-pressed
│   └── ErrorBoundary.tsx                  # 修改: 加 role="alert"
├── hooks/
│   ├── useTheme.ts                         # 新增
│   ├── useUnsavedChanges.ts               # 新增
│   └── usePromptModal.tsx                 # 修改: autoFocus 条件化
├── constants/
│   ├── chartColors.ts                      # 修改: 函数版接受 token
│   └── traceColors.ts                      # 修改: 函数版接受 isDark
├── api/
│   └── client.ts                           # 修改: 错误描述含下一步
└── pages/
    ├── CompliancePage.tsx                  # 修改: aria-live, label, 确认文案, skeleton, 省略号
    ├── EvalPage.tsx                        # 修改: aria-live, label, 确认文案, skeleton, 省略号
    ├── FeedbackPage.tsx                    # 修改: skeleton
    └── KnowledgePage.tsx                   # 修改: skeleton, beforeunload, 省略号
```

---

## Implementation Phases

### Phase 1: Infrastructure — US3 + US5 + US8 (partial) (P1)

入口修正、路由级 ErrorBoundary、React.lazy 代码拆分、语义 HTML 基础。

#### 需求回溯

→ spec.md US3 (Route-level ErrorBoundary), US5 (Code Splitting), US8 验收场景2+5 (main landmark + skip link)
→ FR-004, FR-007, FR-008, FR-010, FR-013 (partial), FR-017 (partial)

#### 实现步骤

1. **修正 `index.html`**
   - 文件: `scripts/web/index.html`
   - `lang="en"` → `lang="zh-CN"`
   - `<title>web</title>` → `<title>精算助手</title>`
   - 添加 `<meta name="theme-color" content="#ffffff">`
   - 添加 `<meta name="color-scheme" content="light dark">`

2. **创建 SkipLink 组件**
   - 文件: `scripts/web/src/components/SkipLink.tsx` (新增)
   - 渲染一个 visually-hidden 链接，Tab 时显示，链接到 `#main-content`
   ```tsx
   export default function SkipLink() {
     return (
       <a href="#main-content" className="skip-link">
         跳到主内容
       </a>
     );
   }
   ```

3. **创建 PageErrorBoundary 组件**
   - 文件: `scripts/web/src/components/PageErrorBoundary.tsx` (新增)
   - 函数式 ErrorBoundary（用 `useState` + `useEffect` 或类组件），含重试按钮和错误描述
   - 错误描述包含下一步建议（SC-010）
   ```tsx
   export default function PageErrorBoundary({ children }: { children: ReactNode }) {
     // 类组件模式（React ErrorBoundary 需要类组件）
     // getDerivedStateFromError → 局部错误状态
     // fallback: Result + "重试" + "刷新页面"
   }
   ```

4. **改进 `api/client.ts` 错误描述**
   - 文件: `scripts/web/api/client.ts`
   - 默认错误从 "请求失败" 改为 "请求失败，请检查网络后重试"
   - `ApiError` 新增 `suggestion` 字段

5. **React.lazy 路由拆分 + ErrorBoundary 包裹**
   - 文件: `scripts/web/src/App.tsx`
   - 所有页面改为 `React.lazy(() => import('./pages/XXXPage'))`
   - 用 `<Suspense fallback={<PageSkeleton />}>` 包裹（用 antd Skeleton）
   - 每个路由用 `withErrorBoundary(LazyPage)` 包裹
   - 添加 `<SkipLink />`
   - `<div id="root">` 后 SkipLink 为首个可聚焦元素

6. **AppLayout 语义化：`<nav>` + `<main>`**
   - 文件: `scripts/web/src/components/AppLayout.tsx`
   - Sider 外包 `<nav aria-label="主导航">`
   - Content 改为 `<main id="main-content">`
   - 移动端 MobileTabBar 外包 `<nav aria-label="主导航">`

**Checkpoint**: 验证 `lang="zh-CN"`、skip link 可 Tab 聚焦、lazy 加载正常、ErrorBoundary 隔离路由错误、`<nav>` + `<main>` landmark 存在

---

### Phase 2: ARIA & Accessibility Core — US1 + US2 (P1)

ARIA 属性补全（aria-label、aria-live）、焦点管理（focus-visible、focus trap、发送后焦点保持）。

#### 需求回溯

→ spec.md US1 (Screen reader), US2 (Keyboard-only)
→ FR-001, FR-002, FR-003, FR-005, FR-006, FR-028

#### 实现步骤

1. **icon 按钮添加 aria-label** (FR-001)
   - `CopyBtn.tsx`: 改为 `<button>` 元素，加 `aria-label="复制"` / `aria-label="已复制"`
   - `ChatPanel.tsx`: delete session 按钮 `aria-label="删除会话"`、menu 按钮 `aria-label="打开会话列表"`、close trace 按钮 `aria-label="关闭调试面板"`
   - `MessageBubble.tsx`: delete 按钮 `aria-label="删除消息"`

2. **ChatPanel aria-live 区域** (FR-002)
   - 文件: `scripts/web/src/components/ChatPanel.tsx`
   - 消息列表容器加 `aria-live="polite"` `aria-label="对话消息"`

3. **进度 aria-live** (FR-003)
   - `CompliancePage.tsx`: 解析/检查进度加 `aria-live="polite"`
   - `EvalPage.tsx`: 评测运行进度加 `aria-live="polite"`

4. **CopyBtn 改为 button + tabIndex**
   - 文件: `scripts/web/src/components/CopyBtn.tsx`
   - 从 `<CopyOutlined onClick>` 改为 `<button onClick aria-label>`
   - 样式：无边框、无背景、cursor pointer

5. **CitationTag 可点击加 role/tabIndex** (FR-001 补充)
   - 文件: `scripts/web/src/components/CitationTag.tsx`
   - 有 onClick 时加 `role="button"`, `tabIndex={0}`, `onKeyDown` (Enter/Space 触发 onClick)

6. **focus-visible CSS 补充** (FR-005)
   - 文件: `scripts/web/src/index.css`
   - 添加自定义交互元素 focus-visible 样式：
   ```css
   :where([role="button"], [role="tab"], [role="treeitem"]):focus-visible {
     outline: 2px solid var(--ant-color-primary);
     outline-offset: 2px;
     border-radius: 2px;
   }
   ```

7. **ChatPanel 发送后焦点保持** (FR-028)
   - 文件: `scripts/web/src/components/ChatPanel.tsx`
   - `handleSend` 后显式 `inputRef.current?.focus()`

8. **ChatPanel 输入框 autocomplete off** (FR-027)
   - 文件: `scripts/web/src/components/ChatPanel.tsx`
   - TextArea 加 `autoComplete="off"`

9. **MessageBubble 改为 `<article>`**
   - 文件: `scripts/web/src/components/MessageBubble.tsx`
   - 外层 `<div>` 改为 `<article>`，加 `aria-label={`${msg.role === 'user' ? '用户消息' : '助手消息'}`} ${formatMsgTime(msg.timestamp)}`}`

**Checkpoint**: VoiceOver 可朗读所有 icon 按钮目的、新消息通过 aria-live 通知、Tab 可聚焦到所有交互元素、发送后焦点在输入框

---

### Phase 3: Keyboard & Focus — US2 补充 + US8 (P1→P2)

焦点陷阱、bare `<div>` 交互元素改造、TracePanel 最小可用 a11y。

#### 需求回溯

→ spec.md US2 验收场景3-4, US8 验收场景1
→ FR-006, FR-017 (TracePanel 交互)

#### 实现步骤

1. **MobileTabBar 加 role/tabIndex/onKeyDown** (FR-005, FR-014 增强)
   - 文件: `scripts/web/src/components/AppLayout.tsx`
   - 每个 tab 项加 `role="tab"`, `tabIndex={active ? 0 : -1}`, `aria-selected={active}`, `onKeyDown` (左右箭头切换)

2. **ChatPanel session list 加 role/tabIndex**
   - 文件: `scripts/web/src/components/ChatPanel.tsx`
   - session 项加 `role="button"`, `tabIndex={0}`, `onKeyDown` (Enter 触发 onClick)

3. **SourcePanel source item 加 role/tabIndex**
   - 文件: `scripts/web/src/components/SourcePanel.tsx`
   - source 项加 `role="button"`, `tabIndex={0}`, `aria-selected`

4. **MessageBubble search result card 加 role/tabIndex**
   - 文件: `scripts/web/src/components/MessageBubble.tsx`
   - 搜索结果卡片加 `role="button"`, `tabIndex={0}`, `onKeyDown`

5. **TracePanel 交互元素加 a11y**
   - 文件: `scripts/web/src/components/TracePanel.tsx`
   - SpanRow: `role="treeitem"`, `tabIndex={0}`, `aria-expanded`, `onKeyDown` (Enter 切换展开)
   - CollapsibleText toggle: `role="button"`, `aria-expanded`, `tabIndex={0}`, `onKeyDown`
   - RetrievalResults expand/collapse: `role="button"`, `tabIndex={0}`, `onKeyDown`

6. **ChatPanel drag handle 加 role**
   - 文件: `scripts/web/src/components/ChatPanel.tsx`
   - drag handle 加 `role="separator"`, `aria-orientation="vertical"`, `aria-label="调整面板宽度"`

**Checkpoint**: 所有 bare `<div>` 交互元素可通过 Tab 聚焦、Enter/Space 可激活、TracePanel span 树可通过键盘导航

---

### Phase 4: Mobile Enhancement — US7 (P2)

移动端可访问性增强（已有布局，增强 a11y）。

#### 需求回溯

→ spec.md US7 (Full mobile responsive)
→ FR-014, FR-015, FR-016

#### 实现步骤

1. **MobileTabBar 44px tap target 确认** (FR-015)
   - 已有 `minWidth: 44, minHeight: 44` 在部分按钮；补全 ChatPanel 其他 icon 按钮

2. **safe-area-inset-top 补充** (FR-016)
   - AppLayout mobile Header 加 `paddingTop: 'env(safe-area-inset-top, 0px)'`

**Checkpoint**: 375px 宽度下 Tab 可聚焦所有交互元素、44px 最小触达区域、安全区域无遮挡

---

### Phase 5: Skeleton Loading — US4 (P2)

替换 `<Spin>` 为 `<Skeleton>`。

#### 需求回溯

→ spec.md US4 (Skeleton loading)
→ FR-009

#### 实现步骤

1. **替换页面级 Spin 为 Skeleton**
   - `ChatPanel.tsx`: 消息加载用 `<Skeleton avatar paragraph={{ rows: 2 }} active />`
   - `KnowledgePage.tsx`: 表格加载用 `<Skeleton.Table active />`
   - `EvalPage.tsx`: 评测列表 + 指标卡片用 `<Skeleton.Table />` + `<Skeleton active />`
   - `CompliancePage.tsx`: 解析结果用 `<Skeleton active paragraph={{ rows: 6 }} />`
   - `FeedbackPage.tsx`: 反馈列表用 `<Skeleton.Table active />`

2. **DocumentViewer loading 改为 Skeleton**
   - `DocumentViewer.tsx`: `<Spin tip="加载文档..." />` 改为 `<Skeleton active paragraph={{ rows: 10 }} />`

**Checkpoint**: 慢速网络下各页面显示骨架屏而非 spinner、无布局跳动

---

### Phase 6: Form & Destructive Action — US9 + US12 (P2)

表单 label 补全、beforeunload、破坏性操作确认文案统一。

#### 需求回溯

→ spec.md US9 (Form controls), US12 (Destructive action protection)
→ FR-018, FR-019, FR-020, FR-021

#### 实现步骤

1. **创建 useUnsavedChanges hook** (FR-020)
   - 文件: `scripts/web/src/hooks/useUnsavedChanges.ts` (新增)
   - `isDirty=true` 时添加 `beforeunload` 监听
   - `isDirty=false` 时移除
   ```ts
   export function useUnsavedChanges(isDirty: boolean): void {
     useEffect(() => {
       if (!isDirty) return;
       const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
       window.addEventListener('beforeunload', handler);
       return () => window.removeEventListener('beforeunload', handler);
     }, [isDirty]);
   }
   ```

2. **KnowledgePage 编辑状态加 beforeunload**
   - 文件: `scripts/web/src/pages/KnowledgePage.tsx`
   - `useUnsavedChanges(editing)` — 编辑中离开时警告

3. **CompliancePage 输入状态加 beforeunload**
   - 文件: `scripts/web/src/pages/CompliancePage.tsx`
   - `useUnsavedChanges(!!richTextContent.trim() || !!uploadedFile)`

4. **FeedbackButtons 加 aria-pressed** (FR-018 补充)
   - 文件: `scripts/web/src/components/FeedbackButtons.tsx`
   - up/down 按钮加 `aria-pressed={feedback === 'up'/'down'}`

5. **CompliancePage 表单加 label** (FR-018)
   - 文件: `scripts/web/src/pages/CompliancePage.tsx`
   - productName Input 加 `aria-label="产品名称"`

6. **CompliancePage text input spellCheck={false}** (US9 验收场景4)
   - 文件: `scripts/web/src/pages/CompliancePage.tsx`
   - 条款文档 TextArea 加 `spellCheck={false}`

7. **破坏性操作 Popconfirm 文案统一加可逆说明** (FR-021)
   - `ChatPanel.tsx:144-160`: "确定删除此会话？此操作不可恢复。"
   - `EvalPage.tsx:748`: "确定删除此评测样本？此操作不可恢复。"
   - `KnowledgePage.tsx` 版本删除: "确定删除此版本？此操作不可恢复。"
   - `CompliancePage.tsx:710`: "确定删除该检查记录？此操作不可恢复。"

**Checkpoint**: 表单有 label/aria-label、编辑中离开有 beforeunload 警告、删除操作确认文案含可逆说明

---

### Phase 7: Animation & Typography — US10 + US11 (P3)

CSS reduced-motion、省略号替换、tabular-nums、text-wrap: balance、Intl.DateTimeFormat。

#### 需求回溯

→ spec.md US10 (Animation), US11 (Typography)
→ FR-022, FR-023, FR-024, FR-025, FR-026, FR-029

#### 实现步骤

1. **index.css 添加 prefers-reduced-motion** (FR-022)
   ```css
   @media (prefers-reduced-motion: reduce) {
     *, *::before, *::after {
       animation-duration: 0.01ms !important;
       animation-iteration-count: 1 !important;
       transition-duration: 0.01ms !important;
     }
   }
   ```

2. **index.css 添加 typography 规则** (FR-025, FR-026)
   ```css
   .markdown-body h1, .markdown-body h2, .markdown-body h3, .markdown-body h4 {
     text-wrap: balance;
   }
   .tabular-nums {
     font-variant-numeric: tabular-nums;
   }
   ```

3. **省略号替换** (FR-024)
   - `TracePanel.tsx:60`: `'\n...'` → `'\n…'`
   - `CompliancePage.tsx:210`: `'...'` → `'…'`
   - `EvalPage.tsx`: 搜索 `+ '...'` → `+ '…'`
   - `KnowledgePage.tsx`: 搜索 `.slice(0, 80)...` → `.slice(0, 80)…`
   - 全局搜索所有 `'...'` 和 `+ '...'` 和 `...` 文本，替换为 `'…'`

4. **MetricsChart 数值列加 tabular-nums** (FR-025)
   - 文件: `scripts/web/src/components/MetricsChart.tsx`
   - Statistic value 加 `className="tabular-nums"`

5. **TracePanel formatTimestamp 改用 Intl** (FR-029)
   - 文件: `scripts/web/src/components/TracePanel.tsx`
   - `formatTimestamp` 改用 `Intl.DateTimeFormat('zh-CN', ...)` 替代手动拼接

6. **SkipLink 样式** (FR-004 补充)
   - 文件: `scripts/web/src/index.css`
   ```css
   .skip-link {
     position: absolute;
     top: -40px;
     left: 0;
     padding: 8px 16px;
     background: var(--ant-color-primary);
     color: #fff;
     z-index: 9999;
     transition: top 0.2s;
   }
   .skip-link:focus {
     top: 0;
   }
   ```

**Checkpoint**: reduced-motion 下无动画、省略号字符正确、数值列等宽、标题 balance、日期用 Intl

---

### Phase 8: Dark Mode — US6 (P2)

暗色模式全量支持。

#### 需求回溯

→ spec.md US6 (Dark mode)
→ FR-011, FR-012, FR-013, FR-030

#### 实现步骤

1. **创建 useTheme hook**
   - 文件: `scripts/web/src/hooks/useTheme.ts` (新增)
   ```ts
   export function useTheme() {
     const [isDark, setIsDark] = useState(() => {
       const stored = localStorage.getItem('theme');
       if (stored) return stored === 'dark';
       return window.matchMedia('(prefers-color-scheme: dark)').matches;
     });

     useEffect(() => {
       const mq = window.matchMedia('(prefers-color-scheme: dark)');
       const handler = (e: MediaQueryListEvent) => {
         if (!localStorage.getItem('theme')) setIsDark(e.matches);
       };
       mq.addEventListener('change', handler);
       return () => mq.removeEventListener('change', handler);
     }, []);

     const toggleTheme = useCallback(() => {
       setIsDark(prev => {
         const next = !prev;
         localStorage.setItem('theme', next ? 'dark' : 'light');
         return next;
       });
     }, []);

     useEffect(() => {
       document.documentElement.style.colorScheme = isDark ? 'dark' : 'light';
       const meta = document.querySelector('meta[name="theme-color"]');
       if (meta) meta.setAttribute('content', isDark ? '#0f172a' : '#ffffff');
     }, [isDark]);

     return { isDark, toggleTheme };
   }
   ```

2. **扩展 theme.ts：darkTheme 全量配置**
   - 文件: `scripts/web/src/theme.ts`
   - 新增 `darkTheme: ThemeConfig`，基于 `theme.darkAlgorithm`
   - 新增 `getTheme(isDark: boolean): ThemeConfig` 工厂函数
   - 保留 `sidebarDarkTheme` 用于侧边栏独立配置

3. **App.tsx 接入 useTheme**
   - 文件: `scripts/web/src/App.tsx`
   - 用 `useTheme()` 获取 `isDark` 和 `toggleTheme`
   - `ConfigProvider theme={getTheme(isDark)}`
   - 将 `toggleTheme` 通过 context 或 props 传递到 AppLayout 供 Header 按钮使用

4. **chartColors.ts 改为函数版**
   - 文件: `scripts/web/src/constants/chartColors.ts`
   - 导出 `getChartColors(isDark: boolean)` 返回颜色对象
   - 保留 `CHART_COLORS` 作为默认导出（向后兼容）

5. **traceColors.ts 改为函数版**
   - 文件: `scripts/web/src/constants/traceColors.ts`
   - 导出 `getTraceCategoryColors(isDark: boolean)` — 暗色时反转背景色为深色

6. **MetricsChart 用函数版 chartColors**
   - 文件: `scripts/web/src/components/MetricsChart.tsx`
   - 用 `theme.useToken()` + `getChartColors()` 替代硬编码 `CHART_COLORS`
   - SVG chart 加 `aria-hidden="true"` (装饰性图表)

7. **TracePanel 用函数版 traceColors**
   - 文件: `scripts/web/src/components/TracePanel.tsx`
   - `getCategoryStyle` 改为接受 `isDark` 参数
   - score heat `rgba(30, 64, 175, ...)` 改为 `token.colorPrimary` + opacity

8. **MessageBubble 硬编码颜色改 token**
   - 文件: `scripts/web/src/components/MessageBubble.tsx`
   - `color: '#ffffff'` → `token.colorBgContainer`（或 `token.colorPrimaryTextActive`）
   - `color: 'rgba(255,255,255,0.7)'` → 用 token 计算半透明文字色

9. **DocumentViewer 加 token 背景色/文字色**
   - 文件: `scripts/web/src/components/DocumentViewer.tsx`
   - PDF/DOCX 容器加 `background: token.colorBgContainer`, `color: token.colorText`

10. **CitationTag `color="blue"` 改为语义色**
    - 文件: `scripts/web/src/components/CitationTag.tsx`
    - `color="blue"` 改为 `color="primary"` 或用 token 色

11. **Select 暗色显式色** (FR-030)
    - 文件: `scripts/web/src/index.css`
    ```css
    [data-theme="dark"] .ant-select-selector,
    html[dark] .ant-select-selector {
      background-color: var(--ant-color-bg-container);
      color: var(--ant-color-text);
    }
    ```
    - 注：antd v6 darkAlgorithm 应自动处理，此为 Windows 兼容兜底

**Checkpoint**: 暗色切换正常、刷新后保持、跟随 OS、所有页面无颜色异常、chart 颜色适配

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | — | — |

无违反。TracePanel a11y 采用渐进式方案（role/tabIndex/onKeyDown 最小可用，非完整 tree ARIA），符合简单优先原则。

---

## Appendix

### 执行顺序建议

```
Phase 1 (基础设施)
  ↓
Phase 2 (ARIA 核心) ← 可与 Phase 3 部分并行
  ↓
Phase 3 (键盘/焦点) ← 依赖 Phase 2 的 aria 属性
  ↓
Phase 4 (移动端增强) ← 可与 Phase 5 并行
  ↓
Phase 5 (Skeleton) ← 独立
  ↓
Phase 6 (表单/破坏性) ← 独立
  ↓
Phase 7 (动画/排版) ← 独立
  ↓
Phase 8 (暗色模式) ← 依赖 Phase 2 的 token 改造基础
```

### 验收标准总结

| User Story | 验收标准 | 验证方式 |
|-----------|---------|---------|
| US1 (Screen reader) | aria-label, aria-live, skip link | VoiceOver 手动测试 + Lighthouse |
| US2 (Keyboard) | focus-visible, focus trap, 焦点保持 | 键盘手动测试 |
| US3 (ErrorBoundary) | 路由隔离, 重试按钮 | 渲染错误注入测试 |
| US4 (Skeleton) | 骨架屏替代 spinner | 慢速网络视觉验证 |
| US5 (Code Splitting) | 初始 chunk 仅首页 | DevTools Network 面板 |
| US6 (Dark mode) | 全量暗色适配, WCAG AA | 暗色切换视觉验证 |
| US7 (Mobile) | 44px tap target, safe-area | 375px viewport 测试 |
| US8 (Semantic HTML) | nav/main/article/skip | HTML 验证器 |
| US9 (Form) | label, autocomplete, beforeunload | 表单交互测试 |
| US10 (Animation) | reduced-motion | 系统设置 reduced-motion 验证 |
| US11 (Typography) | 省略号, tabular-nums, balance | 视觉检查 |
| US12 (Destructive) | 确认含可逆说明 | 删除操作手动测试 |
