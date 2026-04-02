# 合规检查来源可信度增强设计

## 问题

合规检查历史中，`[来源X]` 引用存在两个可信度问题：

1. **前端展示不完整**：`source` 列只显示 LLM 生成的文本字符串，`result.sources`（完整元数据）和 `result.citations`（解析后的引用）已存储但前端未使用，用户无法看到法规原文、发文机关、生效日期、检索相关度等验证信息。
2. **LLM 引用精度不足**：Prompt 只要求 `[来源X]` 格式引用，未要求引用具体原文片段，用户无法快速判断引用是否支撑结论。

## 设计方案

### 一、后端：增强合规 Prompt 引用精度

**文件**：`scripts/api/routers/compliance.py`

1. **`_build_context` 增加元数据**：将 `issuing_authority`、`effective_date`、`doc_number` 注入 context，让 LLM 能引用更精确的信息。

2. **增强两个 Prompt**（`_COMPLIANCE_PROMPT_PRODUCT` 和 `_COMPLIANCE_PROMPT_DOCUMENT`）：
   - 新增 `source_excerpt` 字段，存储从来源中直接摘录的原文片段
   - 指令要求 LLM 在每个 item 中引用法规原文关键句作为事实依据

3. **输出结构新增字段**：
   ```json
   {
       "param": "等待期",
       "source": "[来源2]",
       "source_excerpt": "健康保险产品的等待期不得超过90天",
       "...": "..."
   }
   ```

### 二、前端：来源详情面板

**文件**：`scripts/web/src/pages/CompliancePage.tsx`

1. **法规来源列改为可点击 Tag**：解析 `[来源X]` 文本，渲染为蓝色可点击标签。

2. **新增 SourceDrawer 抽屉组件**（同文件内）：
   - 法规名称 + 条款编号
   - 完整法规原文内容
   - 元数据：发文机关、文号、生效日期、所属分类、来源文件
   - 检索相关度评分（RRF score）
   - 引用的原文片段高亮（`source_excerpt`）

3. **利用已有数据**：从 `result.sources` 数组中按 index 查找对应 Source 对象。

### 三、类型定义更新

**文件**：`scripts/web/src/types/index.ts`

- `ComplianceItem` 新增 `source_excerpt?: string` 字段
- `Source` 接口新增 `score?: number`、`doc_number?: string`、`effective_date?: string`、`issuing_authority?: string` 可选字段

### 四、不变的部分

- 数据库 schema 无需修改（`result_json` 已包含所有数据）
- 后端 API 返回结构不变（`ComplianceReportOut` 已有 `result` 字段）
- RAG 引擎、检索、归因模块不做改动
