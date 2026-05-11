# Implementation Plan: UI 设计走查与改进

**Branch**: `033-ui-design-audit` | **Date**: 2026-05-11 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

统一前端 5 个页面的标题组件、色彩常量、空状态引导。新建 2 个轻量组件（PageHeader、EmptyGuide），修改 12 个现有文件，不引入新依赖。

## Technical Context

**Language/Version**: TypeScript + React 18 + Vite
**Primary Dependencies**: Ant Design 5.x（已有）、recharts（已有）
**Testing**: `npx tsc --noEmit` 类型检查 + 目视验证
**Performance Goals**: 无新增运行时开销（仅 CSS/组件层级改动）
**Constraints**: 不引入新依赖；TracePanel 保持 CSS 变量方案不改；sidebarDarkTheme 保持硬编码

## Constitution Check

- [x] **Library-First**: 复用 Ant Design `<Title>`、`<Empty>`、`<Statistic>` 组件，不造轮子
- [x] **测试优先**: 纯展示组件无单元测试必要，用 TypeScript 类型检查 + 目视验证
- [x] **简单优先**: PageHeader/EmptyGuide 都是 < 30 行的薄封装；tabular-nums 用 body 级 CSS 一行解决
- [x] **显式优于隐式**: 组件 props 显式声明，无魔法行为
- [x] **可追溯性**: 每个 Phase 标注对应 User Story
- [x] **独立可测试**: 每个 Phase 可独立交付和验证

## Project Structure

### Source Code Changes

```
scripts/web/src/
├── components/
│   ├── PageHeader.tsx          # 新增
│   └── EmptyGuide.tsx          # 新增
├── constants/
│   └── chartColors.ts          # 修改：色值对齐主色
├── components/
│   ├── MessageBubble.tsx       # 修改：#ffffff → token
│   └── observability/
│       └── CacheTrendChart.tsx # 修改：硬编码 stroke → 常量
├── pages/
│   ├── CompliancePage.tsx      # 修改：PageHeader + EmptyGuide
│   ├── EvalPage.tsx            # 修改：PageHeader + EmptyGuide
│   ├── KnowledgePage.tsx       # 修改：PageHeader + EmptyGuide
│   ├── FeedbackPage.tsx        # 修改：PageHeader
│   └── ObservabilityPage.tsx   # 修改：添加 PageHeader
└── index.css                   # 修改：font-family + tabular-nums + 触摸目标
```

## Implementation Phases

### Phase 1: 基础组件 — US-1.1 + US-2.1 (P1)

#### 需求回溯

→ spec.md US-1.1: 页面标题区缺乏统一结构
→ spec.md US-2.1: 空状态设计缺乏引导
→ spec.md FR-001: 统一页面标题组件
→ spec.md FR-003: 空状态提供操作引导

#### 实现步骤

**步骤 1: 新建 PageHeader 组件**

文件: `scripts/web/src/components/PageHeader.tsx`

```typescript
import { Typography } from 'antd';
import { Grid } from 'antd';

const { Title, Text } = Typography;
const { useBreakpoint } = Grid;

interface PageHeaderProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  extra?: React.ReactNode;
}

export default function PageHeader({ icon, title, description, extra }: PageHeaderProps) {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  return (
    <div className="flex-between" style={{ marginBottom: 16 }}>
      <div>
        <Title level={4} style={{ margin: 0 }}>
          {icon}<span style={{ marginLeft: icon ? 8 : 0 }}>{title}</span>
        </Title>
        {!isMobile && description && (
          <Text type="secondary" style={{ fontSize: 13, marginTop: 2, display: 'block' }}>
            {description}
          </Text>
        )}
      </div>
      {extra}
    </div>
  );
}
```

**步骤 2: 新建 EmptyGuide 组件**

文件: `scripts/web/src/components/EmptyGuide.tsx`

```typescript
import { Empty, Button } from 'antd';

interface EmptyGuideProps {
  icon?: React.ReactNode;
  title?: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}

export default function EmptyGuide({ description, actionLabel, onAction }: EmptyGuideProps) {
  return (
    <div className="empty-state">
      <Empty description={description}>
        {actionLabel && onAction && (
          <Button type="primary" onClick={onAction}>{actionLabel}</Button>
        )}
      </Empty>
    </div>
  );
}
```

---

### Phase 2: 色彩统一 — US-1.2 (P1)

#### 需求回溯

→ spec.md US-1.2: 色彩系统碎片化
→ spec.md FR-002: 硬编码色值替换为 token 或常量

#### 实现步骤

**步骤 1: 对齐 chartColors.ts 色值**

文件: `scripts/web/src/constants/chartColors.ts`

将 `#1e40af` → `#1677ff`，`#3b82f6` → `#4096ff`，palette 首色同步修改：

```typescript
export const CHART_COLORS = {
  primary: '#1677ff',
  primaryLight: '#4096ff',
  success: '#059669',
  warning: '#d97706',
  error: '#dc2626',
  retrieval: '#1677ff',
  generation: '#059669',
  palette: ['#1677ff', '#059669', '#d97706', '#dc2626', '#722ed1', '#0891b2'],
};
```

**步骤 2: MessageBubble 白色文字改用 token**

文件: `scripts/web/src/components/MessageBubble.tsx:83`

```typescript
// 旧: color: '#ffffff',
// 新: color: token.colorWhite,
```

**步骤 3: CacheTrendChart stroke 改用常量**

文件: `scripts/web/src/components/observability/CacheTrendChart.tsx:64`

```typescript
// 旧: stroke="#1890ff"
// 新: stroke={CHART_COLORS.primary}
```

需在文件顶部添加 import:
```typescript
import { CHART_COLORS } from '../../constants/chartColors';
```

---

### Phase 3: 全局 CSS 改进 — US-4.1 + US-4.2 + US-3.2 (P4/P3)

#### 需求回溯

→ spec.md US-4.1: 字体栈缺乏中文优化
→ spec.md US-4.2: 数字展示未统一等宽对齐
→ spec.md FR-005: 全局 tabular-nums
→ spec.md FR-007: 移动端触摸目标 >= 44px

#### 实现步骤

**步骤 1: index.css body 规则修改**

文件: `scripts/web/src/index.css`

```css
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  font-variant-numeric: tabular-nums;
  background: var(--ant-color-bg-layout);
  transition: background 0.3s;
}
```

**步骤 2: 移动端触摸目标 CSS**

在 `index.css` 末尾添加：

```css
@media (max-width: 767px) {
  .ant-table-cell .ant-btn-sm {
    min-height: 44px;
    min-width: 44px;
  }
}
```

---

### Phase 4: 页面接入 PageHeader — US-1.1 (P1)

#### 需求回溯

→ spec.md US-1.1: 页面标题区缺乏统一结构

#### 实现步骤

每个页面替换标题，统一 import。以下为 5 个页面的具体改动：

**CompliancePage.tsx:648**
```typescript
// 旧: <Title level={4} className="mb-16">合规检查助手</Title>
// 新: <PageHeader icon={<SafetyCertificateOutlined />} title="合规检查助手" description="检查保险条款文档的合规性" />
```

**EvalPage.tsx:1174**
```typescript
// 旧: <Title level={4} className="mb-16">评测管理</Title>
// 新: <PageHeader icon={<BarChartOutlined />} title="评测管理" description="RAG 检索与生成质量评测" />
```

**KnowledgePage.tsx:367**
```typescript
// 旧: <Title level={4} className="mb-16">知识库管理</Title>
// 新: <PageHeader icon={<DatabaseOutlined />} title="知识库管理" description="管理法规知识库的文档与版本" />
```

**FeedbackPage.tsx:190**
```typescript
// 旧: <Typography.Title level={4} className="mb-16">问题反馈</Typography.Title>
// 新: <PageHeader icon={<DislikeOutlined />} title="问题反馈" description="跟踪和修复 RAG 系统的问题" />
// 注意: DislikeOutlined 需确认在 FeedbackPage 的 import 中已引入
```

**ObservabilityPage.tsx** — 在 `<Tabs>` 前添加：
```typescript
<PageHeader icon={<ExperimentOutlined />} title="可观测性" description="Trace 链路追踪与缓存监控" />
```

每个页面需添加 import:
```typescript
import PageHeader from '../components/PageHeader';
```

移除不再需要的 `const { Title } = Typography;` 或 `const { Text, Title } = Typography;`（仅当 Title 仅用于页面标题时）。

---

### Phase 5: 空状态接入 EmptyGuide — US-2.1 (P2)

#### 需求回溯

→ spec.md US-2.1: 空状态设计缺乏引导
→ spec.md FR-003: 空状态提供操作引导

#### 实现步骤

**EvalPage** — 配置详情空状态（搜索 `选择左侧的配置查看详情`）
```typescript
// 旧: <Text type="secondary">选择左侧的配置查看详情，或新建配置</Text>
// 新: <EmptyGuide description="选择左侧的配置查看详情" actionLabel="新增配置" onAction={startNewConfig} />
```

**EvalPage** — 评测记录空状态（搜索 `暂无评测记录`）
```typescript
// 旧: <div className="empty-state" style={{ fontSize: token.fontSizeSM }}>暂无评测记录</div>
// 新: <EmptyGuide description="暂无评测记录" />
```

**CompliancePage** — 解析结果为空（搜索 `未解析到任何内容`）
```typescript
// 旧: <Empty description="未解析到任何内容" />
// 新: <EmptyGuide description="未解析到任何内容" />
```

**CompliancePage** — 请输入文档（搜索 `请输入文档内容`）
```typescript
// 旧: <Empty description="请输入文档内容或点击左侧上传文件" />
// 新: <EmptyGuide description="请输入文档内容或上传文件" />
```

**TraceList** — 暂无 Trace（搜索 `暂无 Trace 数据`）
```typescript
// 旧: <div className="empty-state" style={{ fontSize: 12 }}>暂无 Trace 数据</div>
// 新: <EmptyGuide description="暂无 Trace 数据" />
```

每个页面需添加 import:
```typescript
import EmptyGuide from '../components/EmptyGuide';
```

---

### Phase 6: 验证 — 全部 User Stories

#### 验证步骤

1. **类型检查**: `npx tsc --noEmit` 无错误
2. **目视验证**: 逐页检查标题、空状态、色彩一致性
3. **深色模式**: 切换深色模式检查无视觉异常
4. **移动端**: DevTools 模拟器检查触摸目标尺寸

## Complexity Tracking

无违反。所有方案均为最简实现。

### 本期不实现的需求

- **US-2.2 面板边框统一 (P2)**: 各页面 borderRadius 数量多（2/4/6/8/12/16），影响有限，留后续统一。当前 borderRadius 已通过 token.borderRadius (6) 约束新增代码。
- **FR-006 页面切换过渡动效 (MAY)**: React Router 无内置过渡，需引入 `motion` 或 `framer-motion`，违反"不引入新依赖"约束。后续可考虑。

## Appendix

### 执行顺序

```
Phase 1 (组件) → Phase 2 (色彩) → Phase 3 (CSS) → Phase 4 (标题接入) → Phase 5 (空状态接入) → Phase 6 (验证)
```

Phase 2/3 可并行。Phase 4/5 依赖 Phase 1。

### 验收标准总结

| User Story | 验收标准 | 验证方式 |
|-----------|---------|---------|
| US-1.1 标题统一 | 5 页标题使用同一组件、字号一致 | 目视 + 代码检查 |
| US-1.2 色彩统一 | 无游离硬编码色值（除常量文件 + sidebarDarkTheme） | grep 检查 |
| US-2.1 空状态引导 | 空状态含 CTA 按钮 | 目视 |
| US-4.1 字体 | font-family 含中文 fallback | CSS 检查 |
| US-4.2 数字对齐 | 全局 tabular-nums | CSS 检查 |
| US-3.2 触摸目标 | 移动端按钮 >= 44px | DevTools 测量 |
