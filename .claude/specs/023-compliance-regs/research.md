# 合规审查法规检索策略改造 - 技术调研报告

生成时间: 2026-04-23 14:30:00
源规格: .claude/specs/023-compliance-regs/spec.md

## 执行摘要

调研发现当前合规检查的法规检索仅依赖 RAG 语义检索，可能遗漏关键法规。现有知识库通过 YAML frontmatter 的 `collection` 字段标记法规分类（如 `健康险_健康保险管理办法`），但检索时未利用此分类。负面清单表已存在但未集成到合规检查流程。建议实现险种法规库映射表、强制包含通用法规、独立负面清单检查模块，改动范围中等，核心在 compliance.py 检索逻辑。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 险种专属法规库 | `lib/rag_engine/rag_engine.py:348-381` | 仅支持语义检索，无险种分类过滤 |
| FR-002 通用法规强制包含 | `api/routers/compliance.py:312-317` | 无，仅 RAG 检索结果 |
| FR-003 负面清单检查 | `lib/common/database.py:95-104` | 表已存在，get_negative_list() 可用，但未集成 |
| FR-004 LLM 险种识别 | `api/routers/compliance.py:275-278` | 已有参数提取 LLM，可扩展 |
| FR-005 用户修正险种 | `api/schemas/compliance.py` | 无，需新增请求字段 |
| FR-007 来源类型标注 | `lib/doc_parser/models.py:55-74` | metadata 已有 category 字段 |

### 1.2 可复用组件

- **`ProductCategory` 枚举** (`lib/common/product_types.py:12-23`): 已定义健康险、寿险、意外险等险种分类
- **`classify_product()` 函数** (`lib/common/product_types.py:103-132`): 基于关键词匹配识别险种
- **`DocumentMeta.from_frontmatter()`** (`lib/doc_parser/models.py:38-53`): 解析 YAML frontmatter 的险种类型字段
- **`get_negative_list()`** (`lib/common/database.py:95-104`): 获取负面清单数据
- **`RAGEngine.search(filters=...)`** (`lib/rag_engine/rag_engine.py:348-381`): 支持 metadata 过滤检索

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `api/routers/compliance.py` | 修改 | 改造检索逻辑，加载险种法规库 |
| `api/schemas/compliance.py` | 修改 | 添加 category、category_confirmed 字段 |
| `lib/common/regulation_registry.py` | 新增 | 险种法规映射表配置 |
| `api/routers/compliance.py` | 新增函数 | `_load_general_regulations()` 通用法规加载 |
| `api/routers/compliance.py` | 新增函数 | `_check_negative_list()` 负面清单检查 |

---

## 二、技术选型研究

### 2.1 险种法规库存储方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| YAML 配置文件 | 易维护、可版本追踪 | 需加载解析 | 法规映射表固定 | ✅ 推荐 |
| SQLite 表 | 查询快、动态更新 | 需建表维护 | 频繁更新法规库 | ❌ 不必要 |
| 知识库 metadata 过滤 | 复用现有结构 | 需知识库重新标记 | 法规已按险种分类 | ✅ 备选 |

**推荐方案**: YAML 配置文件 + 知识库 metadata 过滤

YAML 配置定义法规名称列表，检索时用 `filters={"law_name": xxx}` 过滤。这样既保持配置灵活性，又复用现有 metadata 过滤机制。

### 2.2 险种识别方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| 关键词匹配 (classify_product) | 快速、无 LLM 成本 | 覆盖不全 | 产品名称明确 | ✅ 备选 |
| LLM 提取 | 灵活、识别复杂表述 | 有成本、需用户确认 | 自动识别 | ✅ 推荐 |
| 用户手动选择 | 准确 | 用户负担 | 兜底方案 | ✅ 必须 |

**推荐方案**: LLM 提取 + 用户确认 + 关键词匹配兜底

### 2.3 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| yaml | 内置 | 法规映射配置 | ✅ 无问题 |
| SQLite | 现有 | 负面清单查询 | ✅ 已存在 |

---

## 三、数据流分析

### 3.1 现有数据流

```
用户上传文档 → parse_file → ParsedDocument
→ check_document → RAG检索(语义) → LLM分析 → ComplianceReport
```

**问题**: RAG 检索仅基于 query 语义，可能遗漏通用法规。

### 3.2 新增/变更的数据流

```
用户上传文档 → parse_file → ParsedDocument
→ LLM识别险种 → 用户确认险种
→ check_document(category=用户确认险种)
    ├─ 加载险种专属法规库 (filters={"category": category})
    ├─ 加载通用法规库 (保险法、条款管理办法等)
    ├─ RAG 补充检索 (语义相关条款)
    ├─ 负面清单检查 (独立检查项)
    → 合并法规上下文 → LLM分析 → ComplianceReport
```

### 3.3 关键数据结构

```python
# 险种法规映射配置 (新增)
REGULATION_REGISTRY = {
    "健康险": [
        "健康保险管理办法",
        "关于规范短期健康保险发展的通知",
        "健康保险精算规定",
    ],
    "寿险": [
        "人身保险精算规定",
        "人寿保险产品指引",
    ],
    # ...
}

GENERAL_REGULATIONS = [
    "中华人民共和国保险法",
    "保险条款管理办法",
    "保险费率管理办法",
    "人身保险公司精算报告管理办法",
]

# 合规检查请求扩展 (修改)
class DocumentCheckRequest(BaseModel):
    document_content: str
    product_name: Optional[str]
    parse_id: Optional[str]
    category: Optional[str]          # 新增: 险种类型
    category_confirmed: bool = False # 新增: 用户已确认

# 合规检查结果扩展 (修改)
class ComplianceResult:
    items: List[ComplianceItem]
    regulation_sources: Dict[str, List[str]]  # 新增: {"险种专属": [...], "通用": [...], "负面清单": [...]}
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [ ] 知识库 metadata 的 `category` 字段是否已按险种分类 — 验证方式: 检查现有法规 frontmatter
- [ ] 通用法规是否都在知识库中 — 验证方式: 搜索保险法、条款管理办法文件
- [ ] LLM 险种识别准确率是否达标 (≥90%) — 验证方式: 测试样本评估

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 知识库未按险种分类 | 中 | 高 | 提供法规名称列表配置，用 law_name 过滤 |
| 用户不确认险种导致检查不完整 | 中 | 中 | 默认加载通用法规库兜底 |
| 负面清单检查项过多影响用户体验 | 低 | 低 | 按严重程度分级展示 |
| 多险种组合产品法规库过大 | 低 | 中 | 合并法规库时去重 |

---

## 五、参考实现

### 5.1 现有 metadata 过滤机制

```python
# lib/rag_engine/rag_engine.py:478-509
def search_by_metadata(
    self,
    query: str,
    law_name: Optional[str] = None,
    category: Optional[str] = None,
    ...
) -> List[Dict]:
    filters = {}
    if law_name:
        filters['law_name'] = law_name
    if category:
        filters['category'] = category
    return self.search(query, filters=filters)
```

### 5.2 负面清单查询

```python
# lib/common/database.py:95-104
def get_negative_list():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute('SELECT * FROM negative_list ORDER BY severity DESC')
        rows = cur.fetchall()
        return [dict(row) for row in rows]
```

### 5.3 DocumentMeta metadata 输出

```python
# lib/doc_parser/models.py:55-74
def to_chunk_metadata(self, article_number, source_file) -> Dict:
    metadata = {
        'law_name': self.law_name,
        'article_number': article_number,
        'category': self.category,  # 从 collection 提取，如 "健康险"
        'hierarchy_path': f"{self.category} > {self.law_name} > {article_number}",
        ...
    }
    return metadata
```

---

## 六、法规分类现状验证

### 6.1 知识库 frontmatter 结构

法规 Markdown 文件的 YAML frontmatter 示例:

```yaml
---
collection: 健康险_健康保险管理办法
regulation: 健康保险管理办法
发文机关: [国家卫生健康委员会, 国家金融监督管理总局]
文号: [〔2023〕1号]
险种类型: 健康险
---
```

**关键发现**:
- `collection` 格式为 `<险种>_<法规名称>`，可提取险种分类
- `category` 字段由 `DocumentMeta.from_frontmatter()` 从 collection 提取
- 已有 metadata 字段: `law_name`, `category`, `article_number`, `hierarchy_path`

### 6.2 检索利用现状

当前合规检查 (`api/routers/compliance.py:312-317`) 检索逻辑:

```python
query = f"保险合规要求 {extracted[:200]}"
search_results = engine.search(query, top_k=10)
```

**问题**: 未使用 `filters` 参数，未利用 metadata 分类信息。

---

## 七、改造要点总结

1. **险种识别流程**: LLM 提取 → 用户确认 → 失败时关键词匹配兜底
2. **法规加载策略**: 险种专属库 + 通用法规库 + RAG 补充 + 负面清单检查
3. **检索改进**: 使用 `search(filters={"category": category})` 过滤险种专属法规
4. **负面清单集成**: 独立检查项，在 LLM 检查前执行，结果合并到 items
5. **配置管理**: YAML 配置法规映射表，便于版本追踪和维护