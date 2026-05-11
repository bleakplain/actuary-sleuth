# Feature Specification: UI Accessibility & UX Compliance

**Feature Branch**: `031-ui-a11y-ux`
**Created**: 2026-05-09
**Status**: Draft
**Input**: Web Interface Guidelines 审查报告 — 12 类问题，43 项发现

## User Scenarios & Testing

### User Story 1 - Screen reader users can navigate and use the app (Priority: P1)

As a visually impaired user using a screen reader, I need proper ARIA labels, live regions, and semantic HTML so I can ask insurance regulation questions, review audit results, and navigate between pages.

**Why this priority**: Accessibility is a legal compliance requirement and foundational — without it, a class of users cannot use the product at all.

**Independent Test**: Enable VoiceOver/NVDA, navigate all 6 pages, complete a question-ask-verify flow, review an audit result.

**Acceptance Scenarios**:

1. **Given** the app is loaded, **When** a screen reader navigates the sidebar, **Then** each menu item announces its label (法规问答, 知识库管理, etc.) and current selection state
2. **Given** a chat session is active, **When** a new assistant message appears, **Then** the screen reader announces the new message via `aria-live="polite"` region
3. **Given** the compliance page is open, **When** audit progress updates, **Then** the screen reader announces progress changes
4. **Given** any icon-only button (copy, delete, close trace), **When** focused, **Then** screen reader announces its purpose via `aria-label`
5. **Given** the app loads, **When** user presses Tab, **Then** focus moves to a "跳到主内容" skip link first

---

### User Story 2 - Keyboard-only users can operate all features (Priority: P1)

As a keyboard-only user, I need visible focus indicators, keyboard shortcuts, and proper focus management so I can use the entire app without a mouse.

**Why this priority**: Keyboard accessibility is core WCAG 2.1 AA requirement; many power users also prefer keyboard navigation.

**Independent Test**: Unplug mouse, complete full workflow: navigate to a page, ask a question, view source, open trace panel, copy text, close panel.

**Acceptance Scenarios**:

1. **Given** any interactive element, **When** focused via Tab, **Then** a visible focus ring is displayed (`focus-visible`)
2. **Given** the chat input is focused, **When** user types a question and presses Enter, **Then** the message is sent and focus remains in the input
3. **Given** a modal/drawer is opened, **When** user presses Tab, **Then** focus is trapped within the modal; pressing Escape closes it
4. **Given** a modal/drawer is closed, **When** focus returns, **Then** focus moves back to the trigger element
5. **Given** the prompt modal is open, **When** user presses Escape, **Then** the modal closes and focus returns to the trigger

---

### User Story 3 - Route-level error boundaries prevent full-app crashes (Priority: P1)

As a user, when a page encounters an error, I should see an error state for that page only — not a blank screen or full-app crash — with a clear retry action.

**Why this priority**: Current single ErrorBoundary means one page crash kills the entire SPA. This is a reliability/user-trust issue.

**Independent Test**: Force an error in EvalPage, verify other pages still work.

**Acceptance Scenarios**:

1. **Given** any page throws a render error, **When** the error boundary catches it, **Then** only that page shows an error state with "重试" and "刷新页面" buttons
2. **Given** a page shows an error state, **When** user clicks "重试", **Then** the page re-renders without a full page reload
3. **Given** a page shows an error state, **When** user navigates to another page, **Then** the other page renders normally
4. **Given** an API call fails, **When** the error is displayed, **Then** the error message includes a specific next step (not just "请求失败")

---

### User Story 4 - Skeleton loading replaces spinners (Priority: P2)

As a user on a slow network, I should see skeleton placeholders that match the layout of incoming content, not spinning indicators, so I know what to expect and the layout doesn't jump.

**Why this priority**: Skeletons reduce perceived load time and layout shift (CLS), directly improving UX metrics.

**Independent Test**: Throttle network, load each page, verify skeleton appears before content.

**Acceptance Scenarios**:

1. **Given** the ask page is loading messages, **Then** skeleton message bubbles appear matching the chat layout
2. **Given** the knowledge page is loading documents, **Then** skeleton table rows appear
3. **Given** the eval page is loading metrics, **Then** skeleton cards with statistic placeholders appear
4. **Given** the compliance page is loading, **Then** skeleton panels matching the review layout appear

---

### User Story 5 - Route-level code splitting with React.lazy (Priority: P2)

As a user, I should see the ask page load quickly without downloading code for pages I haven't visited yet.

**Why this priority**: Current eager imports bundle all pages upfront. Lazy loading reduces initial bundle size and TTI.

**Independent Test**: Check network tab — only AskPage chunk loads on initial visit; other chunks load on navigation.

**Acceptance Scenarios**:

1. **Given** the app is first loaded, **When** the user visits the ask page, **Then** only the ask page chunk and shared chunk are downloaded
2. **Given** the user navigates to eval page for the first time, **When** the chunk loads, **Then** a skeleton/spinner appears briefly during chunk download
3. **Given** a previously visited page is revisited, **Then** the cached chunk loads instantly with no spinner

---

### User Story 6 - Dark mode support (Priority: P2)

As a user who prefers dark interfaces (or works in low-light environments), I can toggle between light and dark themes, with all components rendering correctly in both modes.

**Why this priority**: Dark mode is widely expected in modern tools; improves comfort for a significant user segment.

**Independent Test**: Toggle dark mode, verify all 6 pages render correctly with proper contrast and background colors.

**Acceptance Scenarios**:

1. **Given** the app is in light mode, **When** user toggles dark mode, **Then** all surfaces, text, borders, and interactive elements switch to dark theme colors with WCAG AA contrast
2. **Given** dark mode is active, **When** user refreshes the page, **Then** dark mode persists (stored in localStorage)
3. **Given** the OS is in dark mode, **When** the app loads for the first time, **Then** the app defaults to dark mode (respects `prefers-color-scheme`)
4. **Given** dark mode is active, **Then** `<html>` has `color-scheme: dark` and `<meta name="theme-color">` matches the dark background
5. **Given** dark mode is active, **Then** native `<select>` elements have explicit `background-color` and `color` set (Windows compatibility)

---

### User Story 7 - Full mobile responsive design (Priority: P2)

As a mobile user, I can use all features on a phone-sized screen with appropriate layouts: collapsible sidebar, stacked panels, touch-friendly tap targets, and safe-area awareness.

**Why this priority**: Insurance professionals often review documents on tablets/phones in the field.

**Independent Test**: Open app on 375px-wide viewport, complete core workflows on each page.

**Acceptance Scenarios**:

1. **Given** viewport is below `md` breakpoint (768px), **Then** sidebar is hidden and replaced by a bottom tab bar with safe-area padding
2. **Given** mobile viewport, **When** user taps a tab bar item, **Then** the corresponding page loads with touch-friendly (44px minimum) tap targets
3. **Given** mobile viewport on chat page, **Then** input area has safe-area-inset-bottom padding so it's not obscured by the home indicator
4. **Given** mobile viewport on compliance page, **Then** the two-panel review layout stacks vertically with tabs
5. **Given** mobile viewport on eval page, **Then** tables scroll horizontally and detail panels open in drawers
6. **Given** any interactive element on mobile, **Then** tap targets are at least 44x44px

---

### User Story 8 - Semantic HTML and landmark structure (Priority: P2)

As an assistive technology user, the page has proper semantic structure: `<nav>` for sidebar, `<main>` for content, `<article>` for messages, `<section>` for content groups, with heading hierarchy.

**Why this priority**: Semantic HTML is the foundation of accessibility — ARIA is a supplement, not a replacement.

**Independent Test**: Use a landmark navigator (screen reader) to jump between nav, main, and sections.

**Acceptance Scenarios**:

1. **Given** any page, **Then** the sidebar is wrapped in `<nav>` with `aria-label="主导航"`
2. **Given** any page, **Then** the main content area is wrapped in `<main>` with `id="main-content"`
3. **Given** chat messages, **Then** each message is an `<article>` with `aria-label` describing role and timestamp
4. **Given** any page, **Then** headings follow h1→h4 hierarchy without skipping levels
5. **Given** the app loads, **Then** a skip link "跳到主内容" is the first focusable element, linking to `#main-content`

---

### User Story 9 - Proper form controls with labels and validation (Priority: P2)

As a user filling in forms (feedback, eval sample edit, compliance input), all inputs have associated labels, appropriate `type`/`inputmode`, `autocomplete` hints, and inline validation with error focus management.

**Why this priority**: Forms are the primary interaction point; unlabeled inputs and missing validation create frustration and errors.

**Independent Test**: Tab through all form inputs, submit with invalid data, verify error handling.

**Acceptance Scenarios**:

1. **Given** any form input, **Then** it has an associated `<label>` or `aria-label`
2. **Given** the chat input, **Then** it has `autocomplete="off"` to prevent browser suggestion interference
3. **Given** a form with validation errors, **When** user submits, **Then** focus moves to the first error field
4. **Given** the compliance text input, **Then** it has `spellCheck={false}` for document content
5. **Given** any form with unsaved changes, **When** user navigates away, **Then** a `beforeunload` warning is shown
6. **Given** a date/time displayed anywhere in the UI, **Then** it uses `Intl.DateTimeFormat` with `zh-CN` locale (no hardcoded date patterns)

---

### User Story 10 - Animation and transition polish (Priority: P3)

As a user, transitions feel smooth and intentional: sidebar collapse animates, messages fade in, status changes transition. Users who prefer reduced motion see instant changes instead.

**Why this priority**: Polish and comfort; reduced-motion support is an accessibility requirement.

**Independent Test**: Enable `prefers-reduced-motion`, verify animations are suppressed; disable it, verify smooth transitions.

**Acceptance Scenarios**:

1. **Given** `prefers-reduced-motion: reduce`, **Then** all CSS transitions/animations are disabled or replaced with instant state changes
2. **Given** normal motion preference, **When** sidebar collapses/expands, **Then** width animates smoothly (transform/opacity only)
3. **Given** normal motion preference, **When** a new message appears, **Then** it fades in briefly
4. **Given** any animation, **Then** only `transform` and `opacity` are animated (compositor-friendly); never `transition: all`

---

### User Story 11 - Typography and content handling polish (Priority: P3)

As a user, text is readable and handles edge cases: long content truncates with ellipsis, loading states end with `…`, numeric values use tabular-nums, headings use `text-wrap: balance`, and non-breaking spaces are used for value+unit pairs.

**Why this priority**: Typography polish improves readability and professionalism; content overflow bugs look broken.

**Independent Test**: Test with very long regulation names, many digits in metrics, deeply nested headings.

**Acceptance Scenarios**:

1. **Given** a regulation name exceeds container width, **Then** it truncates with `…` (ellipsis character, not three dots). Applies to: TracePanel.tsx, EvalPage.tsx, CompliancePage.tsx, KnowledgePage.tsx 截断逻辑
2. **Given** a loading state text, **Then** it ends with `…` (e.g., "加载中…", "保存中…")
3. **Given** metric values in tables/charts, **Then** they use `font-variant-numeric: tabular-nums` for alignment
4. **Given** headings with multiple words, **Then** `text-wrap: balance` is applied to prevent widows
5. **Given** a value+unit pair like "10 MB", **Then** a non-breaking space separates them

---

### User Story 12 - Destructive action protection (Priority: P2)

As a user, destructive actions (delete session, delete eval sample, delete version, delete compliance report) always require confirmation, and I can undo within a brief window or the confirmation clearly states irreversibility.

**Why this priority**: Data loss prevention — current code has some Popconfirms but inconsistent coverage.

**Independent Test**: Attempt each delete action, verify confirmation appears.

**Acceptance Scenarios**:

1. **Given** any delete action (session, eval sample, version, report), **When** user clicks delete, **Then** a confirmation modal/popconfirm appears stating what will be deleted
2. **Given** a delete confirmation, **Then** it states whether the action is reversible or irreversible
3. **Given** a delete confirmation, **When** user clicks cancel, **Then** nothing is deleted

---

### Edge Cases

- What happens when `aria-live` region is updated while screen reader is still reading a previous message?
- What happens when focus is in a drawer that gets closed by an external event (e.g., route change)?
- What if dark mode toggle happens while a modal is open?
- What if `prefers-color-scheme` changes while the app is running (OS theme switch)?
- What if a route-level ErrorBoundary catches an error in a lazy-loaded chunk?
- What if a form's `beforeunload` warning fires during a programmatic navigation?

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 为所有 icon-only 按钮添加 `aria-label`（copy, delete, close, menu, debug 等操作按钮）
- **FR-002**: 系统 MUST 在聊天消息列表区域添加 `aria-live="polite"` 实时区域
- **FR-003**: 系统 MUST 在审核/评测进度更新时通过 `aria-live` 通知屏幕阅读器
- **FR-004**: 系统 MUST 为页面添加 skip link（"跳到主内容"），作为首个可聚焦元素
- **FR-005**: 系统 MUST 确保所有交互元素有可见的 focus 指示器（`:focus-visible`）
- **FR-006**: 系统 MUST 在模态框/抽屉打开时实现焦点陷阱，关闭时焦点返回触发元素
- **FR-007**: 系统 MUST 为每个路由页面添加独立的 ErrorBoundary
- **FR-008**: 系统 MUST 在错误状态中提供 "重试" 和具体错误描述（含下一步操作建议）
- **FR-009**: 系统 MUST 用 skeleton 加载态替代所有 spinner 加载态
- **FR-010**: 系统 MUST 使用 `React.lazy` + `Suspense` 实现路由级代码拆分
- **FR-011**: 系统 MUST 支持暗色模式切换，尊重 `prefers-color-scheme` 系统偏好
- **FR-012**: 系统 MUST 在暗色模式下保证所有文本/交互元素的 WCAG AA 对比度
- **FR-013**: 系统 MUST 在 `<html>` 设置 `color-scheme` 并在 `<meta name="theme-color">` 匹配背景色
- **FR-014**: 系统 MUST 在移动端使用底部 tab bar + 抽屉式侧边栏替代固定侧边栏
- **FR-015**: 系统 MUST 确保移动端所有交互元素最小 44x44px 可触达区域
- **FR-016**: 系统 MUST 在移动端使用 `env(safe-area-inset-*)` 处理刘海/底部指示器
- **FR-017**: 系统 MUST 使用语义化 HTML：`<nav>` 侧边栏、`<main>` 主内容、`<article>` 消息、`<section>` 内容分组
- **FR-018**: 系统 MUST 为所有表单输入添加 `<label>` 或 `aria-label`
- **FR-019**: 系统 MUST 在表单提交失败时聚焦到第一个错误字段
- **FR-020**: 系统 MUST 在含未保存更改的表单页面离开时显示 `beforeunload` 警告
- **FR-021**: 系统 MUST 为所有破坏性操作添加确认对话框，说明是否可逆
- **FR-022**: 系统 MUST 支持 `prefers-reduced-motion` 减少动画偏好
- **FR-023**: 系统 MUST 在新增 CSS transition 时明确列出属性，禁止 `transition: all`（当前代码无此问题，作为规范约束防止回归）
- **FR-024**: 系统 MUST 使用省略号字符 `…`（U+2026）而非三个点 `...`，涉及文件：TracePanel.tsx, EvalPage.tsx, CompliancePage.tsx, KnowledgePage.tsx
- **FR-025**: 系统 MUST 为数值列使用 `font-variant-numeric: tabular-nums`
- **FR-026**: 系统 MUST 为标题使用 `text-wrap: balance` 防止孤行
- **FR-027**: 系统 MUST 在聊天输入框设置 `autocomplete="off"`
- **FR-028**: 系统 MUST 确保消息发送后焦点保持在输入框
- **FR-029**: 系统 MUST 使用 `Intl.DateTimeFormat` 格式化日期时间（替代硬编码格式）
- **FR-030**: 系统 MUST 在暗色模式下为 `<select>` 元素设置显式 `background-color` 和 `color`

### Key Entities

- **ThemeConfig**: 暗色模式主题配置，扩展当前 `appTheme`/`sidebarDarkTheme`
- **ErrorBoundary**: 路由级错误边界组件，替代当前全局单一 ErrorBoundary
- **Skeleton**: 各页面骨架屏组件（ChatSkeleton, TableSkeleton, CardSkeleton）
- **FocusTrap**: 可复用焦点陷阱 hook/utility，用于 Modal/Drawer
- **SkipLink**: 跳转到主内容的链接组件

## Success Criteria

- **SC-001**: Lighthouse Accessibility 评分 ≥ 90
- **SC-002**: 所有 6 个页面可通过纯键盘完成核心操作
- **SC-003**: VoiceOver 可完整朗读所有页面内容和交互状态
- **SC-004**: 单页面渲染错误不影响其他页面
- **SC-005**: 初始加载仅包含首页 chunk + 共享 chunk（其他页面按需加载）
- **SC-006**: 暗色模式下所有页面渲染正确，无颜色异常
- **SC-007**: 375px 宽度下所有核心流程可完成
- **SC-008**: `prefers-reduced-motion: reduce` 下无动画/过渡效果
- **SC-009**: 所有破坏性操作均有确认步骤，零意外删除
- **SC-010**: API 失败时错误消息含具体下一步建议（非通用"请求失败"）
- **SC-011**: 表单验证失败时焦点移到第一个错误字段

## Assumptions

- Ant Design 组件的 a11y 支持作为基础（不重写 antd 内部 a11y），仅补充自定义组件的缺失
- 暗色模式通过 antd `theme.darkAlgorithm` + CSS 变量实现，不引入额外 CSS-in-JS 库
- 移动端断点沿用 antd Grid 的 `md` (768px)
- 日期格式化用 `Intl.DateTimeFormat` 但语言固定中文（`zh-CN`），不做完整 i18n 框架
- 代码拆分以页面路由为粒度，不拆分页面内部大组件（如 MetricsChart）
- `beforeunload` 仅在用户确实编辑了内容（dirty state）时触发
- Skeleton 组件用 antd `Skeleton` 组件为基础，不做自定义 skeleton 绘制

## Already Partially Implemented

以下需求在现有代码中已有布局/骨架实现，plan 中应标注为"增强"而非"新建":

- **US7 验收场景1** (bottom tab bar) — `AppLayout.tsx:46-95` 已有 MobileTabBar 布局，需增强 a11y（role/tabIndex/onKeyDown/aria-selected）
- **US2 验收场景5** (Escape 关闭 modal) — antd Modal/Drawer 内置 Escape 关闭，无需新建，仅需确认自定义弹窗也支持
- **FR-005** (focus-visible) — antd 组件自带 focus-visible 样式，仅需补充自定义交互元素（如 MobileTabBar、TracePanel span rows）
- **FR-025** (tabular-nums) — TracePanel 已在 score/duration 列使用，仅需补充 MetricsChart 和其他数值列
