# 知识库重建 - Excel 检查清单转结构化 Markdown

## 概述

将 `references/1.产品开发检查清单2025年.xlsx` 转换为结构化 Markdown 知识库，替换现有 v3（飞书迁移的法规原文）。以法规为粒度拆分、保留元数据标签、通过智谱 GLM-OCR 处理内嵌费率表格图片，生成可重复构建的转换脚本。

## 目标

1. 将 Excel 13 个 sheet 按法规粒度拆分为独立 Markdown 文件
2. 提取元数据标签（险种大类/类型/分型/期限/主附险/填报项目）嵌入文件
3. 5 张内嵌表格图片通过智谱 GLM-OCR 转为 Markdown 表格
4. 生成可重复执行的转换脚本，Excel 更新后可一键重建
5. 替换现有 v3 知识库，创建 v4

## 目录结构

```
scripts/lib/rag_engine/data/kb/v4/
├── meta.json
└── references/
    ├── 00_保险法/
    │   └── 保险法.md
    ├── 01_负面清单检查/
    │   └── 负面清单.md
    ├── 02_条款费率管理办法/
    │   └── 条款费率管理办法.md
    ├── 03_信息披露/
    │   └── 信息披露规则.md
    ├── 04_健康保险产品开发/
    │   ├── 健康保险管理办法.md
    │   └── 健康保险产品管理办法.md
    ├── 05_普通型人身保险/
    │   └── 普通型人身保险精算规定.md
    ├── 06_分红型人身保险/
    │   ├── 分红险精算规定.md
    │   ├── 分红险精算规定_费率表.md
    │   └── 分红保险管理办法.md
    ├── 07_短期健康保险/
    │   └── 短期健康保险管理办法.md
    ├── 08_意外伤害保险/
    │   └── 意外伤害保险业务监管办法.md
    ├── 09_互联网保险产品/
    │   ├── 互联网保险业务监管办法.md
    │   └── 关于规范互联网保险销售行为的通知.md
    ├── 10_税优健康险/
    │   └── 个人税收优惠型健康保险.md
    ├── 11_万能型人身保险/
    │   └── 万能型人身保险精算规定.md
    └── 12_其他监管规定/
        ├── 其他监管规定.md
        └── 其他监管规定_身故保障比例表.md
```

命名规则：`{sheet序号}_{sheet简称}/`，目录名去掉"检查"二字，专注说明法规名称。同一 sheet 内多部法规按法规名称拆分为独立文件。

## Markdown 文件格式

### 集合级元数据（YAML frontmatter）

每个法规文件头部包含 YAML frontmatter：

```yaml
---
collection: 06_分红型人身保险
regulation: 分红险精算规定
source: 1.产品开发检查清单2025年.xlsx
source_sheet: "06.对照"分红险精算规定"检查"
tags:
  - 分红险
  - 人身保险
  - 精算规定
---
```

### 条款级元数据（blockquote 标签）

每个检查条款前嵌入元数据标签块：

```markdown
## 第X条 [条款标题]

> **元数据**: 险种大类=人身保险 | 类型=分红险 | 分型=两全 | 期限=10年以上 | 主附险=主险 | 填报项目=精算责任人

条款正文内容...

### 检查要点

- 要点1
- 要点2
```

元数据标签来自 Excel 的 B-G 列（险种大类/类型/分型/期限/主附险/填报项目）。当某列值为空或"全部"时不标注该字段。

## 表格图片处理

### 图片清单

Excel 中共 5 张嵌入图片，全部为费率/比例表格：

| Sheet | 图片 | 内容 |
|-------|------|------|
| 05 (分红险精算规定) | 图片1 | 费率表（两全险/终身寿险） |
| 05 (分红险精算规定) | 图片2 | 费率表（年金险） |
| 05 (分红险精算规定) | 图片3 | 费率表（两全险/终身寿险） |
| 05 (分红险精算规定) | 图片4 | 费率表（年金险） |
| 10 (其他监管规定) | 图片5 | 身故保险金给付比例表 |

### OCR 方案：智谱 GLM-OCR

使用智谱 AI 的 `/v4/layout_parsing` API（model: `glm-ocr`）：

- **请求**: `{"model": "glm-ocr", "file": "<base64>"}`
- **输出**: Markdown 格式的表格
- **成本**: 0.2元/百万 tokens
- **后处理**: OCR 结果直接嵌入对应 Markdown 文件的适当位置

### 处理流程

1. openpyxl 提取图片为 PIL Image 对象
2. 转为 base64 编码
3. 调用 `ZhipuClient.ocr_table()` 方法
4. 后处理 OCR 返回的 Markdown，清洗格式
5. 嵌入到对应法规文件的表格占位位置

## ZhipuClient 扩展

在 `scripts/lib/llm/zhipu.py` 的 `ZhipuClient` 中新增 `ocr_table()` 方法：

```python
def _do_ocr_table(self, image_base64: str) -> str:
    """调用 GLM-OCR 识别表格为 Markdown"""
    url = f"{self.base_url}/layout_parsing"
    data = {
        "model": "glm-ocr",
        "file": image_base64
    }
    session = self._get_session()
    response = session.post(url, json=data, timeout=self.timeout)
    response.raise_for_status()
    result = response.json()
    return result.get("content", "")

@_track_timing("zhipu")
@_with_circuit_breaker("zhipu")
@_retry_with_backoff(
    max_retries=LLMConstants.MAX_RETRIES,
    base_delay=LLMConstants.RETRY_BASE_DELAY,
    rate_limit_delay_mult=LLMConstants.RATE_LIMIT_DELAY_MULT
)
def ocr_table(self, image_base64: str) -> str:
    return self._do_ocr_table(image_base64)
```

复用现有的 session 管理、重试、熔断机制。

## 转换脚本

### 文件位置

`scripts/lib/rag_engine/excel_to_kb.py`

### 职责

1. 读取 Excel 文件（openpyxl）
2. 解析 sheet 结构，识别法规边界（A 列非数字行为法规分隔标记）
3. 提取元数据列（B-G 列）和条款内容
4. 处理嵌入图片（调用 GLM-OCR）
5. 生成 Markdown 文件到指定输出目录
6. 生成 `meta.json` 版本信息

### 核心逻辑

```
读取 Excel → 遍历 Sheet → 检测法规边界 → 提取元数据+条款 →
遇到图片 → OCR 转 Markdown → 生成 YAML frontmatter →
写入 MD 文件 → 生成 meta.json
```

### 法规边界检测

A 列（序号列）值为空或非纯数字时，标记为新法规的开始。同一 sheet 内可有多个法规。

### 调用方式

```bash
# 完整重建
python -m lib.rag_engine.excel_to_kb \
  --input references/1.产品开发检查清单2025年.xlsx \
  --output scripts/lib/rag_engine/data/kb/v4

# 跳过 OCR（已有缓存时）
python -m lib.rag_engine.excel_to_kb \
  --input references/1.产品开发检查清单2025年.xlsx \
  --output scripts/lib/rag_engine/data/kb/v4 \
  --skip-ocr
```

## 与 RAG 引擎的集成

### 版本管理

- 在现有 `VersionManager` 体系下创建 v4
- `meta.json` 包含版本 ID、创建时间、文件数、描述
- `references/` 目录存放生成的 Markdown 文件

### 分块策略

现有 RAG 引擎按 `##` 标题分块，新格式天然兼容：
- 每个 `## 第X条` 成为独立 chunk
- frontmatter 中的 collection/regulation 标签提供集合级上下文
- blockquote 中的元数据标签提供条款级上下文

### chunker 适配

无需修改 chunker 逻辑。新文件格式中：
- YAML frontmatter（`---` 包裹）被 chunker 的 frontmatter 解析逻辑正确处理
- `##` 标题作为分块边界保持不变
- blockquote 元数据作为 chunk 内容的一部分被保留

## 实施顺序

1. **ZhipuClient.ocr_table()** — 在 zhipu.py 中添加 OCR 方法
2. **转换脚本** — 编写 excel_to_kb.py，处理 Excel→Markdown 的完整逻辑
3. **生成知识库** — 运行脚本生成 v4 目录及文件
4. **验证** — 检查生成文件的格式正确性、OCR 表格质量
5. **集成** — 通过 VersionManager 注册 v4，验证 RAG 查询效果
