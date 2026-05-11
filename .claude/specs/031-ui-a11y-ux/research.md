# UI Accessibility & UX Compliance - 技术调研报告

生成时间: 2026-05-09
源规格: .claude/specs/031-ui-a11y-ux/spec.md

## 执行摘要

调研覆盖 `scripts/web/` 下全部 25 个 TSX 组件、6 个页面、4 个 store、3 个常量文件、1 个 CSS 文件和入口文件。核心发现：**(1)** 当前 a11y 基线几乎为零——`lang="en"` 在中文 UI 上、无 ARIA live 区域、无 skip link、icon 按钮无 aria-label；**(2)** 暗色模式已有 `sidebarDarkTheme` 部分实现但缺运行时切换和全量 dark token；**(3)** 移动端已有 `isMobile` 分支和 `MobileTabBar` 但 tab bar 用 bare `<div>` 无键盘支持；**(4)** 无路由级 ErrorBoundary、无 lazy loading、所有 loading 用 `<Spin>` 无 skeleton。技术选型建议：antd 内置 focus trap（Modal/Drawer）+ `@react-aria/interactions` 补充自定义组件、antd `theme.darkAlgorithm` 做暗色、Vite 自动 code splitting + `React.lazy`、CSS `prefers-reduced-motion` 媒体查询。最大风险是 TracePanel 的 bare `<div>` 交互树——需大量重构才能达到 a11y 合规。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 aria-label | `CopyBtn.tsx:30`, `ChatPanel.tsx:155,213,358`, `MessageBubble.tsx:59` | 缺失 |
| FR-002 aria-live 聊天 | `ChatPanel.tsx:224-237` | 缺失 |
| FR-003 aria-live 进度 | `CompliancePage.tsx`, `EvalPage.tsx:833` | 缺失 |
| FR-004 skip link | `App.tsx`, `AppLayout.tsx` | 缺失 |
| FR-005 focus-visible | `index.css` | 缺失（依赖 antd 默认） |
| FR-006 focus trap | `usePromptModal.tsx:43-64`, antd Drawer/Modal | antd 内置，自定义弹窗缺失 |
| FR-007 route ErrorBoundary | `App.tsx:16`, `ErrorBoundary.tsx` | 仅全局，无路由级 |
| FR-008 错误描述含下一步 | `api/client.ts:27` ("请求失败") | 无具体建议 |
| FR-009 skeleton | 所有页面 | 全部用 `<Spin>`，无 `<Skeleton>` |
| FR-010 React.lazy | `App.tsx:7-12` | 静态 import，无 lazy |
| FR-011 暗色模式切换 | `theme.ts:76-90`, `App.tsx:17` | 侧边栏 dark 已有，全局切换缺失 |
| FR-012 WCAG AA 对比度 | `chartColors.ts`, `traceColors.ts`, `MessageBubble.tsx:80,87` | 硬编码颜色不适应暗色 |
| FR-013 color-scheme meta | `index.html:2` | `<html lang="en">`，无 `<meta name="theme-color">` |
| FR-014 移动端 tab bar | `AppLayout.tsx:46-95` | 已有 MobileTabBar 但用 bare `<div>` |
| FR-015 44px tap target | `AppLayout.tsx:69-90`, `ChatPanel.tsx:213-217` | 部分已有（44px），部分缺失 |
| FR-016 safe-area | `ChatPanel.tsx:239`, `AppLayout.tsx:62` | 部分已有（底部 padding），顶部缺失 |
| FR-017 语义 HTML | `AppLayout.tsx`, 所有页面 | 全部 `<div>`，无 `<nav>/<main>/<article>` |
| FR-018 表单 label | `ChatPanel.tsx:256-268`, `FeedbackButtons.tsx:90-104` | 部分有（antd Form.Item），部分缺失 |
| FR-019 错误聚焦 | 无 | 缺失 |
| FR-020 beforeunload | 无 | 缺失 |
| FR-021 破坏性操作确认 | `ChatPanel.tsx:144-160`, `EvalPage.tsx:748`, `CompliancePage.tsx:710` | 部分有 Popconfirm，不统一 |
| FR-022 prefers-reduced-motion | `index.css` | 缺失 |
| FR-023 禁止 transition: all | `ChatPanel.tsx:306,332`, `TracePanel.tsx:397` | 无 `transition: all`，但无 reduced-motion 适配 |
| FR-024 省略号字符 | `TracePanel.tsx:60` (`'\n...'`), `CompliancePage.tsx:210` (`'...'`) | 用三个点，非 U+2026 |
| FR-025 tabular-nums | `TracePanel.tsx:119,167,417,449` | 已有！其他数值列缺失 |
| FR-026 text-wrap: balance | 无 | 缺失 |
| FR-027 autocomplete off | `ChatPanel.tsx:256-268` | 缺失 |
| FR-028 发送后焦点保持 | `ChatPanel.tsx:83-88` | 缺失（焦点未显式保持） |
| FR-029 Intl.DateTimeFormat | `MessageBubble.tsx:14-19` | 已用 `toLocaleTimeString`（内部用 Intl），`TracePanel.tsx:40-49` 硬编码格式 |
| FR-030 select 暗色显式色 | 无 | 缺失 |

### 1.2 可复用组件

- **`ErrorBoundary`** (`components/ErrorBoundary.tsx`): 类组件，已有重试/刷新按钮。可重构为函数式 + hook 版本，复用到路由级。
- **`appTheme` / `sidebarDarkTheme`** (`theme.ts`): 已有完整 light token 和部分 dark token。`sidebarDarkTheme` 证明 `theme.darkAlgorithm` 可用，可扩展为全量 dark theme。
- **`useBreakpoint()`** (`AppLayout.tsx:17` via `Grid.useBreakpoint`): 已有 `isMobile` 判断逻辑。所有页面可复用。
- **`DARK_MENU_TOKENS`** (`theme.ts:4-9`): 侧边栏 dark token 可合并到全局 dark theme。
- **Ant Design `<Skeleton>`**: 已在 antd 依赖中，无需新增包，可直接替换 `<Spin>`。
- **Ant Design Modal/Drawer focus trap**: antd 6 的 Modal/Drawer 已内置焦点陷阱和 Escape 关闭。自定义弹窗需额外处理。

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `components/SkipLink.tsx` | 新增 | skip-to-content 链接 |
| `components/PageErrorBoundary.tsx` | 新增 | 路由级错误边界（函数式） |
| `components/Skeleton/` | 新增 | ChatSkeleton, TableSkeleton, CardSkeleton |
| `components/AccessibleButton.tsx` | 新增 | 包装 icon-only 按钮，自动加 aria-label |
| `hooks/useTheme.ts` | 新增 | 暗色模式切换 hook（localStorage + prefers-color-scheme） |
| `hooks/useFocusTrap.ts` | 新增 | 焦点陷阱 hook（用于非 antd 弹窗） |
| `hooks/useUnsavedChanges.ts` | 新增 | beforeunload 警告 hook |
| `theme.ts` | 修改 | 新增 `darkTheme` 全量配置、`getTheme(isDark)` 工厂函数 |
| `App.tsx` | 修改 | React.lazy 路由、路由级 ErrorBoundary、skip link、theme provider |
| `AppLayout.tsx` | 修改 | `<nav>` + `<main>` 语义化、移动端 tab bar 可访问性 |
| `index.html` | 修改 | `lang="zh-CN"`、`<meta name="theme-color">`、`<meta name="color-scheme">` |
| `index.css` | 修改 | `prefers-reduced-motion`、`:focus-visible`、`text-wrap: balance`、`tabular-nums` |
| `ChatPanel.tsx` | 修改 | aria-live 区域、icon 按钮 aria-label、autocomplete off、发送后焦点保持 |
| `MessageBubble.tsx` | 修改 | `<article>` 语义化、aria-label、删除按钮 aria-label、硬编码颜色→token |
| `CopyBtn.tsx` | 修改 | 改为 `<button>`、加 aria-label、tabIndex |
| `TracePanel.tsx` | 修改 | 交互元素加 role/tabIndex/onKeyDown、硬编码颜色→CSS 变量 |
| `MetricsChart.tsx` | 修改 | chart 颜色改用 token、SVG 加 aria-hidden |
| `CitationTag.tsx` | 修改 | 可点击时加 role="button"、tabIndex |
| `chartColors.ts` | 修改 | 导出函数版，接受 token 参数 |
| `traceColors.ts` | 修改 | 导出函数版，接受 token 参数 |
| `DocumentViewer.tsx` | 修改 | 容器加 token 背景色/文字色 |
| `CompliancePage.tsx` | 修改 | 进度 aria-live、表单 label、破坏性操作确认统一 |
| `EvalPage.tsx` | 修改 | 同上 + skeleton 替换 |
| `FeedbackPage.tsx` | 修改 | thumbs 按钮 aria-pressed |
| `KnowledgePage.tsx` | 修改 | skeleton 替换、beforeunload |
| `usePromptModal.tsx` | 修改 | 移除 autoFocus（或改条件 autoFocus） |

---

## 二、技术选型研究

### 2.1 暗色模式方案

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| A: antd `ConfigProvider` + `algorithm` 动态切换 | 零新增依赖；antd 组件自动适配；现有 `sidebarDarkTheme` 已验证 | 自定义 inline style 需手动改用 token；CSS 变量需额外处理 | antd 占 UI 90%+ 的项目 | ✅ |
| B: CSS 变量 + `[data-theme="dark"]` 选择器 | 不依赖 JS 运行时；可渐进增强 | antd 组件不支持 CSS 变量主题（v6 用 CSS-in-JS）；双套维护成本高 | 非 antd 项目 | ❌ |
| C: next-themes 类库 | 社区成熟、SSR 支持 | 引入新依赖；本非 Next.js 项目；antd 集成需额外适配 | Next.js 项目 | ❌ |

**选择方案 A**。实现路径：
1. `theme.ts` 新增 `darkTheme: ThemeConfig`，复用 `theme.darkAlgorithm` + dark token
2. 新增 `useTheme()` hook：读取 `localStorage('theme')` 或 `matchMedia('(prefers-color-scheme: dark)')`，提供 `toggleTheme()` 和 `isDark` 状态
3. `App.tsx` 用 `<ConfigProvider theme={isDark ? darkTheme : appTheme}>`
4. 所有硬编码颜色改用 `token.*` 或 CSS 变量
5. `<html>` 动态设置 `color-scheme` 和 `<meta name="theme-color">`

### 2.2 焦点陷阱方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: antd Modal/Drawer 内置 | 零成本；已覆盖 90% 弹窗 | 自定义弹窗（如 resize drawer）不适用 | ✅ 主要 |
| B: focus-trap-react | 社区标准；功能完整 | 新增依赖 (~5KB)；与 antd 可能冲突 | ❌ |
| C: 自实现 useFocusTrap hook | 零依赖；完全控制 | 实现复杂（需处理 Shadow DOM、iframe 等） | ✅ 补充 |

**选择 A+C**：antd 弹窗用内置方案，自定义弹窗（如 ChatPanel 的 resize trace panel）用自实现 hook。

### 2.3 路由级 ErrorBoundary 方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 包裹每个 `<Route element>` | 简单直接；React 标准模式 | 每个路由需手动包裹 | ✅ |
| B: 自定义 `<Route errorElement>` (RRD v6.4+) | 声明式；与 loader 集成 | 需迁移到 data router API；改动大 | ❌ |

**选择 A**：在 `App.tsx` 中创建 `withErrorBoundary(PageComponent)` HOC 包裹每个路由元素。

### 2.4 代码拆分方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: `React.lazy` + `Suspense` | React 标准方式；Vite 自动 chunk | 需处理 loading fallback | ✅ |
| B: `@loadable/component` | SSR 支持；更丰富 API | 新增依赖；非 SSR 项目无收益 | ❌ |

**选择 A**。Vite + `React.lazy` 自动按路由生成 chunk，零配置。

### 2.5 Skeleton 方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: antd `<Skeleton>` 组件 | 零新增依赖；样式统一 | 需逐页面替换 | ✅ |
| B: 自绘 SVG skeleton | 更精确匹配布局 | 工作量大；维护成本高 | ❌ |

**选择 A**。

### 2.6 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| antd | ^6.3.4 | 内置 `<Skeleton>`、`theme.darkAlgorithm`、Modal focus trap | ✅ 已安装 |
| react | ^19.2.4 | `React.lazy`、`Suspense`、`useId` | ✅ 已安装 |
| react-router-dom | ^7.13.2 | 路由（不升级到 data router） | ✅ 已安装 |
| zustand | ^5.0.12 | theme store | ✅ 已安装 |
| vite | ^8.0.1 | 自动 code splitting | ✅ 已安装 |

**无需新增任何 npm 依赖。**

---

## 三、数据流分析

### 3.1 现有数据流

```
用户交互 → Page Component → API Call → Store (zustand) → Re-render
                 ↓
            Error (message.error toast)
```

暗色模式（无）:
```
无 → 硬编码 light theme
```

移动端:
```
Grid.useBreakpoint() → isMobile → 条件渲染（部分组件有，大部分无）
```

### 3.2 新增/变更的数据流

暗色模式:
```
App 初始化 → useTheme()
  → 读取 localStorage('theme') || matchMedia('(prefers-color-scheme: dark)')
  → isDark state
  → ConfigProvider theme={isDark ? darkTheme : lightTheme}
  → <html color-scheme> + <meta theme-color> 更新
  → 用户点击 toggle → isDark 切换 → localStorage 持久化
  → matchMedia change 事件监听 → 自动跟随 OS
```

路由级错误边界:
```
App.tsx → React.lazy(Page) → Suspense fallback={PageSkeleton}
  → Route element={withErrorBoundary(LazyPage)}
  → 渲染错误 → PageErrorBoundary 捕获 → 显示页面级错误 + 重试
  → 其他路由不受影响
```

beforeunload:
```
useUnsavedChanges(isDirty)
  → isDirty=true → window.addEventListener('beforeunload', handler)
  → isDirty=false → removeEventListener
  → 用户离开 → 浏览器弹确认框
```

### 3.3 关键数据结构

```typescript
// theme store (新增，可选：也可直接用 React context)
interface ThemeState {
  isDark: boolean;
  toggleTheme: () => void;
}

// 路由级 ErrorBoundary props
interface PageErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;  // 可自定义错误 UI
}

// useUnsavedChanges hook
function useUnsavedChanges(isDirty: boolean): void;
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [ ] **antd v6 `theme.darkAlgorithm` 全量覆盖** — 验证所有使用的 antd 组件（Table, Tree, Collapse, Descriptions, Drawer, Modal, Select, Input, Switch, Tag, Statistic, Progress）在 `darkAlgorithm` 下渲染正确。特别关注：Table header 背景、Tree 选中色、Select 下拉面板、Statistic 文字色。
- [ ] **antd v6 `ConfigProvider` 动态切换 algorithm 无闪烁** — 验证 `theme` prop 变化时不会导致全量重渲染或闪烁。antd v6 用 CSS-in-JS（@ant-design/cssinjs），运行时切换应通过 `<StyleProvider>` + cache 控制。
- [ ] **Vite code splitting 对 recharts/mammoth/react-pdf 的影响** — 这些大库当前被多个页面引用。验证 lazy loading 后是否正确生成独立 chunk，且共享依赖（react, antd）提取到 vendor chunk。
- [ ] **antd Modal focus trap 与自定义拖拽 resize drawer 的共存** — ChatPanel 的 trace panel 和 EvalPage 的 SampleDrawer 使用自定义 `onMouseDown` resize。验证 antd Drawer 的 focus trap 是否与 resize 交互冲突。
- [ ] **`prefers-color-scheme` 动态变化** — 验证 `matchMedia('(prefers-color-scheme: dark)')` 的 `change` 事件在 macOS/Windows 切换深浅色时正确触发，且 `ConfigProvider` 响应及时。
- [ ] **`lang="zh-CN"` 对 antd 组件的影响** — 当前 `zhCN` locale + `lang="en"`。改为 `lang="zh-CN"` 后验证 antd 内置 ARIA 属性（如 Table 的排序/筛选按钮 aria-label）是否跟随语言切换。

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| TracePanel 全量重构 a11y 工作量超预期 | 高 | 高 | 分阶段：先加 role/tabIndex/onKeyDown（最小可用），后续迭代加 `role="tree"/"treeitem"` |
| 暗色模式下自定义 inline style 遗漏导致颜色异常 | 中 | 中 | 用 codemod/grep 扫描所有 `#`、`rgb`、`rgba` 硬编码颜色，逐一替换为 token 或 CSS 变量 |
| React.lazy 导致首次访问某页面时白屏闪烁 | 低 | 中 | Suspense fallback 用对应页面的 Skeleton，而非通用 spinner |
| `beforeunload` 在 SPA 路由切换时不触发（仅页面离开时触发） | 中 | 低 | 补充路由守卫：用 react-router 的 `useBlocker`（v7 支持）或自定义 Prompt 组件 |
| antd v6 CSS-in-JS 性能问题（大量动态 token 计算） | 低 | 中 | Vite 生产构建已做 SSR 样式提取；运行时切换仅发生一次，性能影响可接受 |
| `focus-visible` 与 antd 默认 focus 样式冲突 | 低 | 低 | 在 `index.css` 中用 `:where()` 降低选择器优先级，不覆盖 antd 默认 |

---

## 五、实现复杂度评估

### 5.1 按需求分组

| 分组 | 涉及 FR | 涉及文件数 | 复杂度 | 说明 |
|------|---------|-----------|--------|------|
| **G1: 入口修正** | FR-004, FR-013 | 3 | 低 | index.html lang/meta、App.tsx skip link、AppLayout nav/main |
| **G2: ARIA 属性补全** | FR-001, FR-002, FR-003, FR-018 | 8 | 中 | icon 按钮 aria-label、aria-live 区域、表单 label |
| **G3: 语义 HTML** | FR-017 | 2 | 低 | AppLayout `<nav>/<main>`、MessageBubble `<article>` |
| **G4: 焦点管理** | FR-005, FR-006, FR-028 | 4 | 中 | focus-visible CSS、focus trap hook、发送后焦点保持 |
| **G5: ErrorBoundary** | FR-007, FR-008 | 2 | 低 | 新建 PageErrorBoundary、包裹路由 |
| **G6: Skeleton** | FR-009 | 4 | 中 | 逐页面替换 Spin→Skeleton |
| **G7: Code Splitting** | FR-010 | 2 | 低 | React.lazy + Suspense |
| **G8: 暗色模式** | FR-011, FR-012, FR-013, FR-030 | 10+ | 高 | theme 工厂、useTheme hook、所有硬编码颜色替换、CSS 变量、meta 动态更新 |
| **G9: 移动端** | FR-014, FR-015, FR-016 | 3 | 中 | MobileTabBar 可访问性、44px tap target、safe-area |
| **G10: 表单/破坏性操作** | FR-019, FR-020, FR-021 | 5 | 中 | 错误聚焦、beforeunload hook、统一确认对话框 |
| **G11: 动画/排版** | FR-022, FR-023, FR-024, FR-025, FR-026, FR-027, FR-029 | 5 | 低 | CSS 规则、省略号替换、Intl 格式化 |

### 5.2 推荐实施顺序

1. **G1 → G3 → G5 → G7** (入口修正 + 语义 HTML + ErrorBoundary + Code Splitting) — 基础设施，其他改动依赖于此
2. **G2 → G4 → G9** (ARIA + 焦点 + 移动端) — a11y 核心
3. **G6 → G11** (Skeleton + 动画/排版) — UX 打磨
4. **G8** (暗色模式) — 独立且工作量大，放最后
5. **G10** (表单/破坏性操作) — 贯穿性改动，可与 G2 并行

---

## 六、关键代码位置索引

### 硬编码颜色（需改为 token/CSS 变量）

| 文件 | 行 | 当前值 | 应改为 |
|------|-----|--------|--------|
| `MessageBubble.tsx` | 80 | `color: '#ffffff'` | `token.colorBgContainer` 或计算对比色 |
| `MessageBubble.tsx` | 87 | `color: 'rgba(255,255,255,0.7)'` | `token.colorTextSecondary` + opacity |
| `chartColors.ts` | 1-10 | 全部 hex | 导出函数，接受 token |
| `traceColors.ts` | 1-8 | 全部 hex（含浅色背景） | 导出函数，暗色时反转 |
| `TracePanel.tsx` | 120 | `rgba(30, 64, 175, ...)` | 用 token.colorPrimary + opacity |
| `DocumentViewer.tsx` | 76,93 | 无背景/文字色 | 加 `token.colorBgContainer`, `token.colorText` |

### bare `<div>` 交互元素（需加 role/tabIndex/onKeyDown）

| 文件 | 行 | 元素 | 应加 |
|------|-----|------|------|
| `AppLayout.tsx` | 69-90 | MobileTabBar item | `role="tab"`, `tabIndex={0}`, `aria-selected`, `onKeyDown` |
| `ChatPanel.tsx` | 117-161 | Session list item | `role="button"`, `tabIndex={0}`, `onKeyDown` |
| `ChatPanel.tsx` | 299-335 | Drag handle | `role="separator"`, `aria-orientation`, `aria-valuenow` |
| `CitationTag.tsx` | 15-19 | Clickable Tag | `role="button"`, `tabIndex={0}` |
| `CopyBtn.tsx` | 30-34 | Icon span | 改为 `<button>`, 加 `aria-label` |
| `MessageBubble.tsx` | 117-147 | Search result card | `role="button"`, `tabIndex={0}` |
| `SourcePanel.tsx` | 34-59 | Source item | `role="button"`, `tabIndex={0}`, `aria-selected` |
| `TracePanel.tsx` | 64-67 | CollapsibleText toggle | `role="button"`, `aria-expanded` |
| `TracePanel.tsx` | 133-143 | Expand/collapse link | `role="button"`, `tabIndex={0}` |
| `TracePanel.tsx` | 389-402 | SpanRow | `role="treeitem"`, `aria-expanded`, `aria-level` |

### 三个点 → 省略号字符

| 文件 | 行 | 当前 | 应改为 |
|------|-----|------|--------|
| `TracePanel.tsx` | 60 | `'\n...'` | `'\n…'` |
| `CompliancePage.tsx` | 210 | `'...'` | `'…'` |
| `EvalPage.tsx` | 341,401 | `+ '...'` | `+ '…'` |
| `KnowledgePage.tsx` | 632,719 | `.slice(0, 80)...` | `.slice(0, 80)…` |

### Silent catch 块（需加用户反馈或保留陈旧数据标注）

| 文件 | 行 | 当前处理 |
|------|-----|---------|
| `CompliancePage.tsx` | 446-449 | `catch { /* 静默失败 */ }` |
| `CompliancePage.tsx` | 399-401 | `catch { /* 降级为空列表 */ }` |
| `EvalPage.tsx` | 159-163 | `catch { /* KB docs optional */ }` |
| `EvalPage.tsx` | 203-208 | `catch { setDocChunks([]) }` |
| `EvalPage.tsx` | 825 | `.catch(() => {})` |
| `EvalPage.tsx` | 1075 | `catch { /* skip */ }` |
| `observabilityStore.ts` | 37-39 | `catch { /* 保留陈旧数据 */ }` |
| `feedbackStore.ts` | 60-63 | `catch { DEV console.error }` |

---

## 七、参考实现

- [Ant Design v6 Dark Theme](https://ant.design/docs/react/customize-theme#dark-mode) — 官方暗色模式配置方式
- [Ant Design v6 Accessibility](https://ant.design/docs/react/accessible) — antd 内置 a11y 支持清单
- [React Aria](https://react-spectrum.adobe.com/react-aria/) — 可参考交互 hook 设计（不引入依赖，仅参考 API）
- [Vite Code Splitting](https://vitejs.dev/guide/build.html#chunking-strategy) — Vite 自动 chunk 策略
- [WCAG 2.1 AA Checklist](https://www.wuhcag.com/wcag-checklist/) — 验收对照清单
- [Web Interface Guidelines](https://github.com/vercel-labs/web-interface-guidelines) — 本次审查的规则来源
