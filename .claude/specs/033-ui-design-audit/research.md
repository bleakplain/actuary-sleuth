# 033-ui-design-audit - 技术调研报告

生成时间: 2026-05-11
源规格: .claude/specs/033-ui-design-audit/spec.md

## 执行摘要

对前端 28 个组件、7 个页面的 UI 代码进行代码级分析，确认 spec.md 中的 7 类问题全部可在不引入新依赖的前提下修复。核心改动集中在 2 个新组件（PageHeader、EmptyGuide）和 12 个现有文件的增量修改。最大的风险是 TracePanel 中大量 CSS 变量引用（`var(--ant-*)`）与 theme token 混用——TracePanel 是纯函数子组件，刻意不使用 `useToken()` 以避免 props 透传，这个设计决策应保留，仅统一色彩常量即可。

---

## 一、现有代码分析

### 1.1 需求 → 模块映射

| 需求 | 对应文件 | 行号 | 现状 |
|------|---------|------|------|
| FR-001 页面标题统一 | CompliancePage:648, EvalPage:1174, KnowledgePage:367, FeedbackPage:190, ObservabilityPage:全文 | — | 4 页用 `<Title level={4}>`（两种写法），1 页无标题 |
| FR-002 硬编码色值 | theme.ts:33-39, chartColors.ts:2-9, traceColors.ts:2-7, MessageBubble.tsx:83, CacheTrendChart.tsx:64 | — | 5 个文件含硬编码色值 |
| FR-003 空状态引导 | EvalPage:1534/1588, CompliancePage:244/249, TracePanel:518/526, TraceList:252, ChatPanel:231, KnowledgePage:548 | — | 6 处空状态，仅 ChatPanel 有操作引导 |
| FR-004 面板边框统一 | CompliancePage:281(br:6), MessageBubble:85(br:12), TracePanel:79(br:6), 各处 br:4 | — | borderRadius 混用 2/4/6/8/12/16 |
| FR-005 tabular-nums | MetricsChart:70, TraceList:138/169, TracePanel:121/168/423/455 | — | 仅 Trace 组件族和 MetricsChart 使用 |
| FR-007 移动端触摸 | 各页表格行 onRow 区域, EvalPage 操作按钮 size="small" | — | 表格行已修 tabIndex，按钮尺寸未处理 |

### 1.2 可复用组件

- **`<Title>` / `<Typography.Title>`**: Ant Design 的标题组件，已有 `level={4}` 约定，可直接封装为 PageHeader
- **`<Empty>`**: Ant Design 的空状态组件，支持 `description` 属性和子元素（可放 CTA 按钮）
- **`className="empty-state"`**: 已在 `index.css:100` 定义样式，可扩展为 EmptyGuide 组件
- **`CHART_COLORS` (chartColors.ts)**: 已集中管理图表色值，仅需调整色值本身
- **`TRACE_CATEGORY_COLORS` (traceColors.ts)**: 已集中管理 Trace 色值，结构良好

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `components/PageHeader.tsx` | 新增 | 统一页面标题组件 |
| `components/EmptyGuide.tsx` | 新增 | 统一空状态引导组件 |
| `constants/chartColors.ts` | 修改 | 色值对齐主色 `#1677ff` |
| `constants/traceColors.ts` | 保持不变 | 深色模式背景色仅调试面板使用，影响有限，暂不处理 |
| `index.css` | 修改 | font-family 添加中文 fallback，body 添加 tabular-nums |
| `MessageBubble.tsx` | 修改 | `#ffffff` → token 引用 |
| `CacheTrendChart.tsx` | 修改 | `#1890ff` → CHART_COLORS 常量 |
| `CompliancePage.tsx` | 修改 | 替换标题为 PageHeader，Empty 替换为 EmptyGuide |
| `EvalPage.tsx` | 修改 | 同上 |
| `KnowledgePage.tsx` | 修改 | 同上 |
| `FeedbackPage.tsx` | 修改 | 同上 |
| `ObservabilityPage.tsx` | 修改 | 添加 PageHeader |
| `MetricsChart.tsx` | 修改 | Statistic 补充 tabular-nums |
| `FeedbackPage.tsx` | 修改 | Statistic 补充 tabular-nums |

---

## 二、技术选型研究

### 2.1 页面标题组件方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 新建 `PageHeader.tsx` 组件 | 类型安全、可扩展（icon/desc/actions）、IDE 提示好 | 多一个文件 | ✅ |
| B. 在 index.css 定义 `.page-header` class | 零依赖、轻量 | 无法约束 props、icon/描述需要各自处理 | ❌ |
| C. 直接用 Ant Design `<PageHeader>` 组件 | 官方组件 | 已废弃（Ant Design 5.x 移除），功能过重 | ❌ |

**选择 A**: 新建轻量组件，接受 `icon`、`title`、`description`、`extra`(操作区) props。

### 2.2 色彩常量统一方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 调整 `chartColors.ts` 色值对齐主色 | 改动最小、集中管理 | 图表色彩仍硬编码，深色模式需额外处理 | ✅ |
| B. 图表组件通过 props 传入 token 色 | 完全响应主题 | 需改 recharts 每个组件的 stroke/fill，侵入大 | ❌ |

**选择 A**: `chartColors.ts` 的 `primary` 从 `#1e40af` 改为 `#1677ff`，其余色值保持功能色（success/warning/error 对齐 Ant Design 语义色）。traceColors.ts 已是常量文件，保持结构不变。

### 2.3 空状态引导方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 新建 `EmptyGuide.tsx` 组件 | 可复用、类型安全 | 多一个文件 | ✅ |
| B. 扩展现有 `<Empty>` + children | 无新文件 | 每处都要手写 CTA、不统一 | ❌ |

**选择 A**: 组件签名 `(icon, title, description, actionLabel, onAction)`，内部渲染 Ant Design `<Empty>` + CTA Button。

### 2.4 TracePanel CSS 变量 vs Token 方案

TracePanel 刻意使用 `var(--ant-*)` 而非 `theme.useToken()`（文件头注释已说明原因：纯子组件避免 props 透传）。**保持此设计决策不变**，仅需确保 CSS 变量与 token 值一致（Ant Design 5.x 已自动将 token 映射为 CSS 变量，所以 `var(--ant-color-*)` 是正确的做法）。

---

## 三、数据流分析

### 3.1 现有数据流

```
App.tsx (ConfigProvider + theme)
  → AppLayout.tsx (layout shell + nav)
    → Page (Compliance/Eval/Knowledge/Feedback/Observability/Ask)
      → 组件树 (各组件独立调用 theme.useToken())
```

主题色 `#1677ff` 流向：
- `theme.ts` → `ConfigProvider` → 全局 token → `theme.useToken()` 各组件
- `chartColors.ts` → MetricsChart 等图表组件（**不经过 token 系统，断裂点**）
- `traceColors.ts` → TracePanel（**不经过 token 系统，但已映射为 CSS 变量**）

### 3.2 新增/变更的数据流

```
theme.ts colorPrimary → chartColors.ts (对齐色值)
                       → PageHeader (新组件，复用 token)
                       → EmptyGuide (新组件，复用 token)
```

无新增数据流，仅统一现有色彩常量。

### 3.3 关键数据结构

无需新增数据模型。PageHeader 和 EmptyGuide 均为纯展示组件。

```typescript
// PageHeader props
interface PageHeaderProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  extra?: React.ReactNode;
}

// EmptyGuide props
interface EmptyGuideProps {
  icon?: React.ReactNode;
  title?: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [x] Ant Design 5.x `theme.useToken()` 返回的 `token.colorPrimary` 是否为 `#1677ff` → **是**，已在 theme.ts 中配置
- [x] `var(--ant-color-primary)` CSS 变量是否自动注入 → **是**，Ant Design 5.x ConfigProvider 自动生成
- [x] `traceColors.ts` 硬编码色值在深色模式下是否正常 → **部分异常**：`bg: '#f8fafc'` 等浅色背景在深色模式下刺眼，但 TracePanel 主要用于桌面端调试面板，影响有限
- [ ] `sidebarDarkTheme` 中 `#001529` 改用 `theme.darkAlgorithm` 自动生成后，侧边栏视觉是否保持一致

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 图表色值调整后雷达图/柱状图在深色模式下对比度不足 | 中 | 低 | recharts 的 `<CartesianGrid>` 和轴已在用默认色，调色值后目视验证 |
| traceColors 浅色 bg 在深色模式下刺眼 | 低 | 低 | 仅桌面端调试面板使用，可后续单独处理 |
| PageHeader 组件接入各页面时移动端间距异常 | 低 | 中 | 组件内处理 isMobile 分支，参照现有 mb-16 |

---

## 五、改动清单与行号定位

### FR-001 页面标题统一（新建组件 + 5 页面替换）

**新建** `components/PageHeader.tsx`:
- 接收 icon, title, description, extra
- 渲染 `<Title level={4}>` + 可选描述
- 移动端隐藏描述

**替换位置**:
- `CompliancePage.tsx:648` `<Title level={4}>合规检查助手</Title>` → `<PageHeader icon={<SafetyCertificateOutlined />} title="合规检查助手" />`
- `EvalPage.tsx:1174` → `<PageHeader icon={<BarChartOutlined />} title="评测管理" />`
- `KnowledgePage.tsx:367` → `<PageHeader icon={<DatabaseOutlined />} title="知识库管理" />`
- `FeedbackPage.tsx:190` → `<PageHeader icon={<DislikeOutlined />} title="问题反馈" />`
- `ObservabilityPage.tsx` → 添加 `<PageHeader icon={<ExperimentOutlined />} title="可观测性" />`

### FR-002 色彩统一（3 常量文件 + 2 组件）

- `chartColors.ts:2` `primary: '#1e40af'` → `'#1677ff'`
- `chartColors.ts:3` `primaryLight: '#3b82f6'` → `'#4096ff'`（Ant Design primary-4）
- `chartColors.ts:7` `retrieval: '#1e40af'` → `'#1677ff'`
- `chartColors.ts:9` palette 首色 `'#1e40af'` → `'#1677ff'`
- `CacheTrendChart.tsx:64` `stroke="#1890ff"` → `stroke={CHART_COLORS.primary}`
- `MessageBubble.tsx:83` `color: '#ffffff'` → `color: token.colorTextLightSolid`（Ant Design 5.x token）
- sidebarDarkTheme `#001529` 保持不变（设计决策 #3）

### FR-003 空状态引导（新建组件 + 6 处替换）

**新建** `components/EmptyGuide.tsx`

**替换位置**:
- `EvalPage:1534` → `<EmptyGuide description="选择左侧的配置查看详情" actionLabel="新增" onAction={startNewConfig} />`
- `EvalPage:1588` → `<EmptyGuide description="暂无评测记录" actionLabel="开始评测" onAction={() => startEvaluation('full')} />`
- `CompliancePage:244/249` → `<EmptyGuide description="未解析到任何内容" />`
- `TracePanel:526` → `<EmptyGuide description="暂无 Trace 数据" />`（保留 emoji icon）
- `TraceList:252` → `<EmptyGuide description="暂无 Trace 数据" />`
- `KnowledgePage` 无文档时 → 添加引导按钮

### FR-005 tabular-nums（CSS 全局化）

在 `index.css` body 添加 `font-variant-numeric: tabular-nums;`，让所有数字默认等宽。移除各组件中零散的 `fontVariantNumeric: 'tabular-nums'` 声明（非必需，可保留不冲突）。

### FR-007 移动端触摸目标

EvalPage 表格操作按钮 `size="small"` 在移动端需增大。涉及行号：EvalPage:747/749（数据集审核/删除）、1267/1279（快照恢复/删除）、334/393（SampleDrawer 添加引用）。方案：通过 CSS `@media (max-width: 767px)` 在 `.ant-table-cell .ant-btn-sm` 上设 `min-height: 44px; min-width: 44px;`。同页 FeedbackPage:139/162/167/171 的操作按钮、KnowledgePage:358 查看按钮同理。

---

## 六、设计决策记录

1. **TracePanel 保持 CSS 变量方案** — 文件头注释已说明原因（避免 props 透传），这是合理的架构决策，不改。
2. **chartColors.ts 保持静态常量** — recharts 组件不接入 React context，传 token 需要 hook，增加复杂度。保持静态常量，仅对齐色值。
3. **sidebarDarkTheme 保留硬编码** — 侧边栏用独立 `<ConfigProvider theme={sidebarDarkTheme}>`，与主主题解耦。`#001529` 是 Ant Design 经典深色侧边栏色，刻意为之，不改。
4. **全局 tabular-nums 优先于逐组件** — `index.css` body 级声明让所有数字等宽，是最简单的方案，且不影响非数字文本。
