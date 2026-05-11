# Feature Specification: UI 设计走查与改进

**Feature Branch**: `033-ui-design-audit`
**Created**: 2026-05-11
**Status**: Draft
**Input**: 使用 frontend-design 走查 UI 设计，识别潜在问题及改进

## 审计范围

对精算助手 Web 前端全部 7 个页面、28 个组件进行设计走查，覆盖：
- 视觉一致性与品牌感
- 排版层级与信息密度
- 色彩系统与对比度
- 间距节奏与空间布局
- 交互反馈与动效
- 移动端适配质量

---

## 审计发现

### P1 — 视觉一致性问题

#### US-1.1 — 页面标题区缺乏统一结构 (Priority: P1)

各页面标题实现不统一：
- CompliancePage: `<Title level={4} className="mb-16">合规检查助手</Title>`
- EvalPage: `<Title level={4} className="mb-16">评测管理</Title>`
- KnowledgePage: `<Title level={4} className="mb-16">知识库管理</Title>`
- FeedbackPage: `<Typography.Title level={4} className="mb-16">问题反馈</Typography.Title>`
- ObservabilityPage: 无标题（建议标题 `可观测性`，图标 ExperimentOutlined）

**问题**: 部分用 `<Title>`、部分用 `<Typography.Title>`，ObservabilityPage 完全没有页面标题。标题与内容之间仅有 `mb-16`(16px)，与 Ant Design 默认间距不协调。页面标题缺乏图标、描述副标题等辅助信息。ChatPanel (AskPage) 是全屏聊天界面，不需要 PageHeader。

**Why this priority**: 标题区是每个页面的第一视觉焦点，不一致会立即降低产品专业感。

**Independent Test**: 逐页检查标题元素、字号、间距是否一致。

**Acceptance Scenarios**:
1. **Given** 打开任意页面, **When** 查看页面顶部, **Then** 标题使用统一的组件、字号(level=4)、图标、描述
2. **Given** ObservabilityPage, **When** 页面加载, **Then** 显示页面标题

---

#### US-1.2 — 色彩系统碎片化 (Priority: P1)

主色 `#1677ff` 定义在 `theme.ts` 中，但多处使用硬编码色值：
- `chartColors.ts`: `#1e40af`（蓝色系但不是主色）、`#059669`、`#d97706`、`#dc2626`
- `sidebarDarkTheme`: `#001529`、`#000c17` 硬编码
- MessageBubble 用户消息气泡: `#ffffff` 文字硬编码
- TracePanel: 大量 CSS 变量但混用 `var(--ant-*)` 与 `token.*`

**问题**: 图表颜色 `#1e40af` vs 主色 `#1677ff` 不是同一个蓝。侧边栏硬编码颜色无法跟随主题变化。用户消息气泡白色文字在浅色主色下可能对比度不足。

**Why this priority**: 色彩不一致会让产品看起来像拼凑的，降低信任感。

**Independent Test**: 搜索代码中所有 `#` 开头的色值，验证是否都引用自 theme 或 constants。

**Acceptance Scenarios**:
1. **Given** 切换深色模式, **When** 查看侧边栏, **Then** 侧边栏颜色正确跟随深色主题
2. **Given** 查看图表, **When** 对比图表蓝色与按钮蓝色, **Then** 两者视觉一致

---

### P2 — 信息架构与布局

#### US-2.1 — 空状态设计缺乏引导 (Priority: P2)

各页面空状态实现方式不同：
- ChatPanel: `<div className="empty-state">` + 自定义文案 + emoji 文字
- CompliancePage: Ant Design `<Empty>` 组件
- EvalPage: `<Text type="secondary">` 混用
- TracePanel: 自定义 empty-state + `&#x1f50d;` emoji

**问题**: 空状态是关键的用户引导时刻，当前缺乏统一的行动召唤(CTA)。ChatPanel 空状态已有操作引导（输入问题），但知识库、评测、反馈页面仅显示"暂无数据"而无引导操作。

**Why this priority**: 空状态直接影响用户首次体验和功能发现。

**Independent Test**: 清空各页面数据，检查空状态展示。

**Acceptance Scenarios**:
1. **Given** 首次打开知识库页面, **When** 无文档, **Then** 显示引导文案和"导入文档"按钮
2. **Given** 首次打开评测页面, **When** 无样本, **Then** 显示引导文案和"新增"按钮

---

#### US-2.2 — 卡片与面板边框/阴影不统一 (Priority: P2)

- 多数使用 `1px solid ${token.colorBorderSecondary}` 做分隔
- CompliancePage 解析面板: `borderRadius: 6`
- EvalPage SampleDrawer: 无边框，靠分割线区分
- ChatPanel 源面板: `borderRadius: token.borderRadiusLG` + 左侧彩色边框
- KnowledgePage 文档卡片: Ant Design Card 默认无边框

**问题**: 面板之间缺乏统一的视觉层级区分。哪些用 Card、哪些用 div + border，没有明确规则。

**Why this priority**: 视觉层级帮助用户快速理解页面结构。

**Independent Test**: 列出所有带边框/border-radius 的容器，验证是否遵循统一规则。

**Acceptance Scenarios**:
1. **Given** 任意包含面板的页面, **When** 查看面板边框, **Then** 主面板用 Card(有阴影)、内嵌面板用 border + borderRadius 6

---

### P3 — 交互与动效

#### US-3.1 — 缺乏加载与状态过渡动效 (Priority: P3)

当前只有：
- CSS `transition: background 0.15s` 用于 hover
- TracePanel divider `transition: background 0.2s`
- 全局 `prefers-reduced-motion` 支持

缺少：
- 页面切换动画（React Router 无过渡）
- 表格加载骨架屏不统一（部分用 `<Skeleton>`、部分用 `<Empty>`）
- Drawer/Modal 开关无过渡
- 按钮点击无反馈动画

**Why this priority**: 过渡动效提升感知性能和专业感，但优先级低于功能和一致性。

**Independent Test**: 在页面间导航、打开/关闭 Drawer，观察是否有过渡效果。

**Acceptance Scenarios**:
1. **Given** 点击侧边栏切换页面, **When** 页面切换, **Then** 有淡入过渡
2. **Given** 打开 Drawer, **When** 面板出现, **Then** 有 slide 过渡（Ant Design 默认已支持）

---

#### US-3.2 — 移动端触摸目标尺寸不一致 (Priority: P3)

移动端已有部分 44px 最小触摸区域：
- 聊天按钮: `minWidth: 44, height: 44`
- 菜单按钮: `minWidth: 44, minHeight: 44`
- 删除按钮: `minWidth: 44, minHeight: 44`

但缺失：
- CompliancePage 文档审查面板的展开/收起区域
- EvalPage 表格中的操作按钮（`size="small"` 约 24px）
- KnowledgePage 分块表格行
- TraceList 中的行

**Why this priority**: 小触摸目标是移动端易用性的核心问题。

**Independent Test**: 在移动设备或 DevTools 模拟器中尝试点击小按钮。

**Acceptance Scenarios**:
1. **Given** 移动端, **When** 尝试点击表格行内操作按钮, **Then** 触摸区域 >= 44px

---

### P4 — 排版与细节

#### US-4.1 — 字体栈缺乏中文优化 (Priority: P4)

```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
```

**问题**: 缺少中文字体声明。虽然系统字体在 macOS/Windows 上可以 fallback 到中文，但 Linux 服务器端渲染可能出问题。此外，monospace 字体仅用于 TracePanel，其他代码展示（EvalPage JSON 输入）未使用等宽字体。

**Why this priority**: 对当前用户群影响较小，但属于完整性问题。

**Acceptance Scenarios**:
1. **Given** font-family 声明, **When** 检查 CSS, **Then** 包含中文字体 fallback（如 "PingFang SC", "Microsoft YaHei"）

---

#### US-4.2 — 数字展示未统一等宽对齐 (Priority: P4)

TracePanel 已使用 `fontVariantNumeric: 'tabular-nums'`，但其他数据密集区域未使用：
- EvalPage 评测指标表格
- FeedbackPage 统计卡片
- CompliancePage 检查结果表格
- CacheMetrics 统计数值

**Why this priority**: 等宽数字提升数据可读性，但仅在数据密集场景有显著效果。

**Acceptance Scenarios**:
1. **Given** 包含数值的表格, **When** 数值变化, **Then** 数字不导致列宽跳动

---

## 总体评估

### 做得好的方面
- 响应式设计：每个组件都考虑了 `isMobile` 分支
- 深色模式：通过 Ant Design token 系统实现，覆盖度高
- 无障碍基础：skip-link、aria-live、focus-visible、reduced-motion 已到位
- Token 化设计：大量使用 `theme.useToken()` 而非硬编码颜色
- 侧边栏深色主题：独立的 ConfigProvider 实现，与主内容区解耦

### 需要改进的方面
- **缺乏设计系统约束**: 没有统一的间距、圆角、阴影 scale
- **页面标题区**: 不统一，部分页面缺少
- **空状态引导**: 功能性强但引导性弱
- **图表色彩**: 与主色系脱节
- **monospace/数字排版**: 部分区域未应用

---

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 提供统一的页面标题组件，包含图标、标题、可选描述
- **FR-002**: 系统 MUST 确保所有硬编码色值替换为 theme token 或常量引用（sidebarDarkTheme 的 `#001529` 除外——这是 Ant Design 经典深色侧边栏色，刻意保留）
- **FR-003**: 系统 MUST 为每个页面的空状态提供操作引导（CTA 按钮）
- **FR-004**: 系统 SHOULD 统一面板边框/圆角规则（Card vs bordered div）
- **FR-005**: 系统 SHOULD 通过全局 CSS 统一应用 tabular-nums（在 body 级声明，无需逐组件处理）
- **FR-006**: 系统 MAY 添加页面切换过渡动效
- **FR-007**: 系统 MUST 确保移动端所有可交互元素 >= 44px 触摸区域

### Key Entities

- **PageHeader**: 统一的页面标题组件（图标 + 标题 + 描述 + 操作区）
- **EmptyGuide**: 统一的空状态引导组件（图标 + 文案 + CTA）
- **Design Tokens**: 统一导出的间距、圆角、阴影常量

## Success Criteria

- **SC-001**: 所有页面标题使用同一组件渲染，字号/间距一致
- **SC-002**: 代码中无游离硬编码色值（除常量文件外）
- **SC-003**: 所有页面空状态包含可操作的 CTA
- **SC-004**: TypeScript 编译无错误
- **SC-005**: 深色模式下无视觉异常

## Assumptions

- 保持 Ant Design 作为基础组件库，不引入新 UI 框架
- 图表库 recharts 保持不变，仅调整色彩配置
- 改进以增量方式落地，不重写现有页面结构
- 移动端优先考虑功能可用性，不追求像素级完美

## Edge Cases

- 深色模式下硬编码颜色是否正确显示？
- 空状态在数据刚加载完时是否有闪烁？
- 页面标题组件在移动端是否需要简化？
