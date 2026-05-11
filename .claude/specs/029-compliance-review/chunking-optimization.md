# 保险产品合规审查分块优化方案

## 一、背景与问题

### 1.1 当前架构

```
保险产品文档 → 按章节拆分 → 每章节 + 全量法规 → LLM 检查 → 合并结果
```

每次 LLM 调用包含：
- 章节文本：可能 10K-50K tokens
- 全量法规：险种专属 + 通用法规，可能 50K+ tokens
- 总计：60K-100K+ tokens/次

### 1.2 性能瓶颈

| 指标 | 当前值 | 问题 |
|------|--------|------|
| 单次调用 token | 60K-100K+ | 远超模型舒适区 |
| 超时重试 | 多次 | 累计耗时从分钟级到小时级 |
| 重疾险测试 | 8977s | 首次调用需预热 + 多次超时重试 |
| 意外险测试 | 224.9s | 文档较短，重试次数少 |

**本地推理 vs 远端推理对比**：

| 维度 | Ollama + qwen3:8B（本地） | 智谱 glm-z1-air（远端） |
|------|--------------------------|------------------------|
| 推理速度 | ~10-15 tok/s（CPU/有限GPU） | ~50-100 tok/s（云端GPU集群） |
| 100K token 调用 | 6000-10000s（极易超时） | 1000-2000s（可控） |
| 超时配置 | timeout=120s → 大概率超时 | timeout=120s → 通常够用 |
| 并发能力 | 受本机资源限制，1-2 并发 | 服务端并发，4-8 并发 |
| 成本 | 免费 | 按量计费 |
| 数据安全 | 产品文档不出本机 | 产品文档需上传云端 |

**结论**：使用远端推理（zhipu/glm）可大幅缓解超时问题，但分块优化仍有必要——即使远端推理速度快，100K+ token 的单次调用成本高、延迟大，分块后可并行加速。分块优化对本地和远端推理都有价值。

### 1.3 核心约束

**法规必须全量注入**：合规审查需要确保每条适用法规都被检查到，不能像 RAG 那样按需检索。

---

## 二、优化目标

1. **单次 LLM 调用 token 控制在 10K-15K 以内**，避免超时
2. **保持全量法规覆盖**，确保审查完整性
3. **支持并行处理**，利用多核/多并发加速
4. **保持审查准确性**，不因分块降低检查质量

---

## 三、技术方案

### 3.1 核心思路：交叉检查矩阵

将"大文档 + 大法规"的单次调用，拆分为"文档分块 × 法规分批"的矩阵检查：

```
┌─────────────────────────────────────────────────────────────────┐
│                        文档分块层                                │
│                                                                  │
│  输入：doc_parser 输出的 AuditDocument，已包含结构化条款列表      │
│  - clauses: List[Clause]        → 每个条款天然是一个 chunk       │
│  - exclusions: List[DocumentSection] → 按章节分块               │
│  - notices: List[DocumentSection]    → 按章节分块               │
│                                                                  │
│  分块策略：                                                      │
│  1. 每个 Clause 作为一个独立 chunk（条款粒度）                   │
│  2. 相邻小条款合并：token < min_chunk_tokens 时合并到下一 chunk  │
│  3. DocumentSection 按段落或 token 预算分块                      │
│  4. chunk token 范围：min 200 ~ max 3000 tokens                 │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                        法规分块层                                │
│                                                                  │
│  法规来源：RAG 引擎按 law_name 精确匹配加载                      │
│  - 险种专属法规：get_category_regulations(category)              │
│  - 通用法规：get_general_regulations()                          │
│                                                                  │
│  分批策略：                                                      │
│  1. 按 law_name 分组（保持法规完整性）                           │
│  2. 每个 law_name 内按 article_number 顺序分批                   │
│  3. 单个 batch token 上限：6000-8000 tokens                      │
│  4. 同一法规的条款尽量放在同一 batch                             │
│                                                                  │
│  示例：                                                          │
│  Batch 1: 健康保险管理办法 全部条款                              │
│  Batch 2: 人身保险产品禁忌条款 全部条款                          │
│  Batch 3: 保险法 第1-30条                                       │
│  Batch 4: 保险法 第31-60条                                      │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                      交叉检查矩阵                                │
│                                                                  │
│              法规Batch1    法规Batch2    法规Batch3    ...       │
│ 文档Chunk1      ✓             ✓             ✓                   │
│ 文档Chunk2      ✓             ✓             ✓                   │
│ 文档Chunk3      ✓             ✓             ✓                   │
│ ...                                                              │
│                                                                  │
│  每个 ✓ = 一次 LLM 调用                                          │
│  Token 估算：~2000 (文档chunk) + ~7000 (法规batch) = ~9000 tokens │
│  本地推理可在 15-30 秒内完成，远端推理 3-5 秒                    │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                        结果合并层                                │
│                                                                  │
│  1. 按文档条款聚合：某条款违反了哪些法规                          │
│  2. 去重：同一违规项可能被多个法规batch报告                       │
│  3. 冲突消解：不同检查结果矛盾时的处理策略                        │
│  4. 生成最终合规审查报告                                          │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Token 预算模型

| 组件 | Token 量 | 说明 |
|------|----------|------|
| 文档 chunk | 200-3000 | 单个条款或段落（小条款合并、大条款独立） |
| 法规 batch | 6000-8000 | 一个或多个法规的全部条款 |
| Prompt 模板 | 300-500 | 检查指令 + JSON 格式说明 |
| LLM 输出 | 1000-2000 | 检查结果 JSON |
| **单次调用总计** | **8000-14000** | 可控范围内 |

**设计原则**：
- 文档 chunk 较小（条款粒度），保证语义完整
- 小 chunk 合并策略：token < 200 的条款与相邻条款合并，避免单次调用信息不足
- 法规 batch 较大，保持法规完整性，避免同一法规被拆散
- 总 token 控制在模型舒适区内

### 3.3 调用次数估算

假设典型场景：
- 文档：50 条款 → 30-40 chunks（小条款合并后）
- 法规：险种专属(3部) + 通用(5部) = 8 batches

**调用次数**：35 chunks × 8 batches = 280 次 LLM 调用

**耗时估算**（本地推理）：
- 串行：280 次 × 20s = 5600s ≈ 93 分钟
- 并行（4 worker）：5600s / 4 = 1400s ≈ 23 分钟

**耗时估算**（远端推理）：
- 串行：280 次 × 4s = 1120s ≈ 19 分钟
- 并行（4 worker）：1120s / 4 = 280s ≈ 5 分钟

### 3.4 智能跳过优化

暂缓实现。先完成分块优化一版，基于实际效果决定是否需要智能跳过。

---

## 四、详细设计

### 4.1 模块架构

```
scripts/lib/compliance/
├── checker.py          # 主检查器（改造）
├── chunker.py          # 新增：文档/法规分块器
├── merger.py           # 新增：结果合并器
├── prompts.py          # 改造：适配分块检查的 prompt
└── __init__.py         # 导出更新
```

注：暂不创建 `smart_skip.py`，待一版效果评估后再决定。

### 4.2 数据结构

```python
@dataclass(frozen=True)
class CheckConfig:
    """检查配置"""
    max_chunk_tokens: int = 3000             # 文档 chunk 上限
    min_chunk_tokens: int = 200              # 文档 chunk 下限（小条款合并）
    max_regulation_batch_tokens: int = 8000  # 法规 batch 上限
    max_output_tokens: int = 2048            # LLM 输出上限
    max_negative_list_doc_chars: int = 100000  # 负面清单文档截断字符数
    parallel_workers: int = 4                # 并行 worker 数


@dataclass
class DocumentChunk:
    """文档分块"""
    chunk_id: str                          # 唯一标识，如 "clause-1.1"
    section_type: str                      # clause/exclusion/notice
    section_title: str                     # 保险条款/责任免除
    clause_number: str                     # 条款编号（仅 clause 类型）
    text: str                              # 文本内容
    token_count: int                       # token 估算


@dataclass
class RegulationBatch:
    """法规批次"""
    batch_id: str                          # 唯一标识，如 "reg-health-管理办法"
    law_names: List[str]                   # 包含的法规名称列表
    articles: List[Dict]                   # 法规条款列表
    text: str                              # 拼接后的文本
    token_count: int                       # token 估算


@dataclass
class ChunkCheckResult:
    """分块检查结果"""
    chunk_id: str
    batch_id: str
    items: List[Dict[str, Any]]            # 检查项列表
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


@dataclass
class MergedResult:
    """合并后的最终结果"""
    summary: Dict[str, int]                # compliant/non_compliant/attention
    items: List[Dict[str, Any]]            # 所有检查项（去重后）
    by_clause: Dict[str, List[Dict]]       # 按条款聚合的结果
    check_matrix: Dict[str, List[str]]     # chunk_id -> batch_ids 映射
    total_llm_calls: int                   # 总 LLM 调用次数
    total_tokens: int                      # 总 token 消耗
    elapsed_seconds: float                 # 总耗时
```

### 4.3 分块器设计（chunker.py）

```python
from lib.doc_parser import AuditDocument, Clause, DocumentSection


class DocumentChunker:
    """文档分块器

    输入：doc_parser 输出的 AuditDocument（已结构化）
    输出：List[DocumentChunk] 供检查器使用
    """

    def __init__(self, config: CheckConfig):
        self._config = config

    def chunk_document(self, audit_doc: AuditDocument) -> List[DocumentChunk]:
        """将 AuditDocument 分块

        分块策略：
        1. clauses: 每个 Clause 天然是一个 chunk，小条款自动合并
        2. exclusions/notices: 按段落或 token 预算分块
        3. 忽略：tables, health_disclosures, rider_clauses
        """
        chunks = []

        # 1. 条款分块（条款粒度 + 小条款合并）
        clause_chunks = self._chunk_clauses(audit_doc.clauses)
        chunks.extend(clause_chunks)

        # 2. 责任免除分块
        for i, section in enumerate(audit_doc.exclusions):
            if not section.content or len(section.content) < self._config.min_section_length:
                continue
            sub_chunks = self._chunk_section(section, "exclusion", "责任免除", i)
            chunks.extend(sub_chunks)

        # 3. 投保须知分块
        for i, section in enumerate(audit_doc.notices):
            if not section.content or len(section.content) < self._config.min_section_length:
                continue
            sub_chunks = self._chunk_section(section, "notice", "投保须知", i)
            chunks.extend(sub_chunks)

        return chunks

    def _chunk_clauses(self, clauses: List[Clause]) -> List[DocumentChunk]:
        """条款分块：每个条款独立 chunk，小条款合并

        合并规则：
        - token_count < min_chunk_tokens 的条款与下一个条款合并
        - 合并后 token_count 不超过 max_chunk_tokens
        - 保留条款编号列表用于结果溯源
        """
        chunks = []
        pending_clauses: List[Clause] = []
        pending_tokens = 0

        for clause in clauses:
            if not clause.text or len(clause.text) < self._config.min_section_length:
                continue

            clause_text = f"【条款 {clause.number}】{clause.title}\n{clause.text}"
            clause_tokens = estimate_tokens(clause_text)

            # 如果当前条款足够大，先 flush pending
            if pending_clauses and clause_tokens >= self._config.min_chunk_tokens:
                chunks.append(self._build_clause_chunk(pending_clauses))
                pending_clauses = []
                pending_tokens = 0

            # 加入 pending
            pending_clauses.append(clause)
            pending_tokens += clause_tokens

            # 如果 pending 超过上限，flush
            if pending_tokens >= self._config.max_chunk_tokens:
                chunks.append(self._build_clause_chunk(pending_clauses))
                pending_clauses = []
                pending_tokens = 0

        # flush 剩余
        if pending_clauses:
            chunks.append(self._build_clause_chunk(pending_clauses))

        return chunks

    def _build_clause_chunk(self, clauses: List[Clause]) -> DocumentChunk:
        """构建条款 chunk"""
        numbers = [c.number for c in clauses]
        texts = [f"【条款 {c.number}】{c.title}\n{c.text}" for c in clauses]
        text = "\n\n".join(texts)

        return DocumentChunk(
            chunk_id=f"clause-{'_'.join(numbers)}",
            section_type="clause",
            section_title="保险条款",
            clause_number=numbers[0] if len(numbers) == 1 else f"{numbers[0]}-{numbers[-1]}",
            text=text,
            token_count=estimate_tokens(text),
        )

    def _chunk_section(
        self,
        section: DocumentSection,
        section_type: str,
        section_title: str,
        index: int,
    ) -> List[DocumentChunk]:
        """将 DocumentSection 分块"""
        text = section.content
        tokens = estimate_tokens(text)

        # 如果不超过上限，直接返回
        if tokens <= self._config.max_chunk_tokens:
            return [DocumentChunk(
                chunk_id=f"{section_type}-{index}",
                section_type=section_type,
                section_title=section_title,
                clause_number="",
                text=f"### {section.title}\n{text}",
                token_count=tokens,
            )]

        # 超过上限，按段落分块
        paragraphs = text.split("\n\n")
        chunks = []
        current_text = ""
        current_tokens = 0
        sub_index = 0

        for para in paragraphs:
            para_tokens = estimate_tokens(para)
            if current_tokens + para_tokens > self._config.max_chunk_tokens:
                if current_text:
                    chunks.append(DocumentChunk(
                        chunk_id=f"{section_type}-{index}-{sub_index}",
                        section_type=section_type,
                        section_title=section_title,
                        clause_number="",
                        text=f"### {section.title}\n{current_text}",
                        token_count=current_tokens,
                    ))
                    sub_index += 1
                current_text = para
                current_tokens = para_tokens
            else:
                current_text += "\n\n" + para if current_text else para
                current_tokens += para_tokens

        if current_text:
            chunks.append(DocumentChunk(
                chunk_id=f"{section_type}-{index}-{sub_index}",
                section_type=section_type,
                section_title=section_title,
                clause_number="",
                text=f"### {section.title}\n{current_text}",
                token_count=current_tokens,
            ))

        return chunks


class RegulationBatcher:
    """法规分批器

    输入：RAG 引擎检索的法规列表
    输出：List[RegulationBatch] 供检查器使用

    分批策略：
    1. 按 law_name 分组，保持法规完整性
    2. 单个法规 token 数超过上限时，按 article_number 分批
    """

    def __init__(self, config: CheckConfig):
        self._config = config

    def batch_regulations(
        self,
        regulations: List[Dict],
    ) -> List[RegulationBatch]:
        """将法规条款分批"""
        # 1. 按 law_name 分组
        by_law: Dict[str, List[Dict]] = {}
        for reg in regulations:
            law_name = reg.get("law_name", "未知法规")
            if law_name not in by_law:
                by_law[law_name] = []
            by_law[law_name].append(reg)

        batches = []

        # 2. 为每个法规生成 batch
        for law_name, articles in by_law.items():
            sorted_articles = sorted(
                articles,
                key=lambda x: x.get("article_number", "")
            )

            text_parts = []
            for art in sorted_articles:
                article_num = art.get("article_number", "")
                content = art.get("content", "")
                text_parts.append(f"【{law_name}】{article_num}\n{content}")

            full_text = "\n\n".join(text_parts)
            tokens = estimate_tokens(full_text)

            if tokens <= self._config.max_regulation_batch_tokens:
                batches.append(RegulationBatch(
                    batch_id=f"reg-{law_name}",
                    law_names=[law_name],
                    articles=sorted_articles,
                    text=full_text,
                    token_count=tokens,
                ))
            else:
                sub_batches = self._split_large_law(law_name, sorted_articles)
                batches.extend(sub_batches)

        return batches

    def _split_large_law(
        self,
        law_name: str,
        articles: List[Dict],
    ) -> List[RegulationBatch]:
        """将单个大法规分批"""
        batches = []
        current_articles = []
        current_text = ""
        current_tokens = 0
        sub_index = 0

        for art in articles:
            article_num = art.get("article_number", "")
            content = art.get("content", "")
            art_text = f"【{law_name}】{article_num}\n{content}"
            art_tokens = estimate_tokens(art_text)

            if current_tokens + art_tokens > self._config.max_regulation_batch_tokens:
                if current_articles:
                    batches.append(RegulationBatch(
                        batch_id=f"reg-{law_name}-{sub_index}",
                        law_names=[law_name],
                        articles=current_articles,
                        text=current_text,
                        token_count=current_tokens,
                    ))
                    sub_index += 1
                current_articles = [art]
                current_text = art_text
                current_tokens = art_tokens
            else:
                current_articles.append(art)
                current_text += "\n\n" + art_text if current_text else art_text
                current_tokens += art_tokens

        if current_articles:
            batches.append(RegulationBatch(
                batch_id=f"reg-{law_name}-{sub_index}",
                law_names=[law_name],
                articles=current_articles,
                text=current_text,
                token_count=current_tokens,
            ))

        return batches
```

### 4.4 主检查器改造（checker.py）

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from lib.doc_parser import AuditDocument


class ComplianceChecker:
    """合规检查器（分块版）"""

    def __init__(
        self,
        llm: Optional[BaseLLMClient] = None,
        config: Optional[CheckConfig] = None,
    ):
        self._llm = llm or get_audit_llm()
        self._config = config or CheckConfig()
        self._chunker = DocumentChunker(self._config)
        self._batcher = RegulationBatcher(self._config)
        self._merger = ResultMerger()
        self._regulations_cache: Optional[List[Dict]] = None
        self._cached_category: Optional[str] = None

    def check_document(
        self,
        audit_doc: AuditDocument,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """检查 AuditDocument 的合规性

        Args:
            audit_doc: doc_parser 输出的 AuditDocument
            category: 险种类型

        Returns:
            检查结果字典
        """
        start_time = time.time()

        # 1. 加载全量法规
        regulations = self._load_all_regulations(category)

        # 2. 文档分块
        doc_chunks = self._chunker.chunk_document(audit_doc)

        # 3. 法规分批
        reg_batches = self._batcher.batch_regulations(regulations)

        logger.info(
            f"分块完成: {len(doc_chunks)} chunks × {len(reg_batches)} batches"
        )

        # 4. 构建检查矩阵（全量检查）
        check_pairs = []
        for chunk in doc_chunks:
            for batch in reg_batches:
                check_pairs.append((chunk, batch))

        # 5. 执行检查（并行）
        results = self._execute_checks(check_pairs)

        # 6. 合并结果
        merged = self._merger.merge(results)
        merged.elapsed_seconds = time.time() - start_time

        logger.info(
            f"检查完成: {len(results)} 次调用, "
            f"{merged.summary['non_compliant']} 个违规项, "
            f"耗时 {merged.elapsed_seconds:.1f}s"
        )

        return merged.to_dict()

    def _execute_checks(
        self,
        check_pairs: List[Tuple[DocumentChunk, RegulationBatch]],
    ) -> List[ChunkCheckResult]:
        """执行检查矩阵"""
        results = []

        with ThreadPoolExecutor(max_workers=self._config.parallel_workers) as executor:
            futures = {
                executor.submit(self._check_chunk_batch, chunk, batch): (chunk, batch)
                for chunk, batch in check_pairs
            }

            for future in as_completed(futures):
                results.append(future.result())

        return results

    def _check_chunk_batch(
        self,
        chunk: DocumentChunk,
        batch: RegulationBatch,
    ) -> ChunkCheckResult:
        """检查单个 (chunk, batch) 组合"""
        start = time.time()

        try:
            prompt = self._build_chunk_prompt(chunk, batch)
            response = self._llm.chat([{"role": "user", "content": prompt}])
            items = self._parse_response(response)

            return ChunkCheckResult(
                chunk_id=chunk.chunk_id,
                batch_id=batch.batch_id,
                items=items,
                elapsed_seconds=time.time() - start,
            )

        except Exception as e:
            logger.error(
                f"Check failed: chunk={chunk.chunk_id}, "
                f"batch={batch.batch_id}, error={e}"
            )
            return ChunkCheckResult(
                chunk_id=chunk.chunk_id,
                batch_id=batch.batch_id,
                items=[],
                error=str(e),
                elapsed_seconds=time.time() - start,
            )
```

### 4.5 结果合并器（merger.py）

```python
class ResultMerger:
    """结果合并器"""

    def merge(self, results: List[ChunkCheckResult]) -> MergedResult:
        """合并所有分块检查结果"""
        all_items = []
        by_clause: Dict[str, List[Dict]] = {}
        check_matrix: Dict[str, List[str]] = {}

        for result in results:
            if result.chunk_id not in check_matrix:
                check_matrix[result.chunk_id] = []
            check_matrix[result.chunk_id].append(result.batch_id)

            for item in result.items:
                item["source_chunk"] = result.chunk_id
                item["source_batch"] = result.batch_id
                all_items.append(item)

                clause_num = item.get("clause_number", "")
                if clause_num:
                    if clause_num not in by_clause:
                        by_clause[clause_num] = []
                    by_clause[clause_num].append(item)

        deduped_items = self._deduplicate(all_items)
        summary = self._compute_summary(deduped_items)

        return MergedResult(
            summary=summary,
            items=deduped_items,
            by_clause=by_clause,
            check_matrix=check_matrix,
            total_llm_calls=len(results),
            total_tokens=0,
        )

    def _deduplicate(self, items: List[Dict]) -> List[Dict]:
        """去重：同一违规项可能被多个 batch 报告"""
        seen = set()
        unique = []

        for item in items:
            key = (
                item.get("clause_number", ""),
                item.get("param", ""),
                item.get("status", ""),
            )
            if key not in seen:
                seen.add(key)
                unique.append(item)

        return unique

    def _compute_summary(self, items: List[Dict]) -> Dict[str, int]:
        """计算汇总统计"""
        summary = {"compliant": 0, "non_compliant": 0, "attention": 0}
        for item in items:
            status = item.get("status", "")
            if status in summary:
                summary[status] += 1
        return summary
```

### 4.6 Prompt 模板（prompts.py）

```python
COMPLIANCE_PROMPT_CHUNK = """你是一位保险法规合规专家。请审查以下保险条款是否违反给定法规条款。

## 待审条款内容
{document_chunk}

## 待对照法规条款
{regulation_batch}

## 输出要求
请以 JSON 格式输出检查结果：
{{
    "items": [
        {{
            "clause_number": "<条款编号，从待审条款中提取>",
            "param": "<检查项名称>",
            "value": "<条款中的实际内容>",
            "requirement": "<法规要求，引用法规原文>",
            "status": "<compliant|non_compliant|attention>",
            "source": "<法规来源，格式：【法规名】条款号>",
            "source_excerpt": "<法规原文片段>",
            "suggestion": "<修改建议，仅在 non_compliant 或 attention 时提供>"
        }}
    ],
    "summary": {{
        "compliant": <合规项数>,
        "non_compliant": <不合规项数>,
        "attention": <需关注项数>
    }}
}}

## 注意事项
1. 仅检查待审条款是否违反待对照法规条款
2. 如果条款完全符合法规要求或法规不适用，items 可以为空数组
3. source 必须使用【法规名】条款号 格式引用
4. 仅输出 JSON，不要附加其他文字
"""
```

---

## 五、负面清单检查

负面清单检查逻辑与条款审查不同，保持独立：

```python
def check_negative_list(self, document_content: str) -> Tuple[List[Dict], str]:
    """执行负面清单检查（保持原有逻辑）

    负面清单检查特点：
    - 全文扫描，不分块
    - 检查是否包含禁止表述
    - 单次 LLM 调用

    优化策略：
    - 截断文档到 max_context_tokens
    - 保持负面清单全量注入
    """
    # ... 保持现有实现 ...
```

---

## 六、配置与兼容性

### 6.1 配置示例

```python
# 默认配置（保守模式）
config = CheckConfig(
    max_chunk_tokens=3000,
    min_chunk_tokens=200,
    max_regulation_batch_tokens=8000,
    parallel_workers=4,
)

# 高性能配置（远端推理 + 高并发）
config = CheckConfig(
    max_chunk_tokens=4000,
    min_chunk_tokens=200,
    max_regulation_batch_tokens=10000,
    parallel_workers=8,
)
```

### 6.2 向后兼容

- 保持 `check_document()` 方法签名不变
- 内部自动检测文档大小，小文档走原有流程，大文档走分块流程
- 提供 `use_chunking: bool` 参数允许显式控制

```python
def check_document(
    self,
    audit_doc: AuditDocument,
    category: Optional[str] = None,
    use_chunking: Optional[bool] = None,
) -> Dict[str, Any]:
    # 自动检测是否需要分块
    if use_chunking is None:
        doc_tokens = self._estimate_doc_tokens(audit_doc)
        use_chunking = doc_tokens > 10000

    if use_chunking:
        return self._check_document_chunked(audit_doc, category)
    else:
        return self._check_document_legacy(audit_doc, category)
```

---

## 七、测试策略

### 7.1 单元测试

```python
class TestDocumentChunker:
    """文档分块器测试"""

    def test_clause_as_single_chunk(self):
        """每个条款是一个独立 chunk"""
        pass

    def test_small_clauses_merged(self):
        """小条款合并到同一 chunk"""
        pass

    def test_chunk_respects_token_limit(self):
        """分块 token 数不超限"""
        pass


class TestRegulationBatcher:
    """法规分批器测试"""

    def test_batch_by_law_name(self):
        """按法规名称分组"""
        pass

    def test_large_law_split(self):
        """大法规分批正确"""
        pass


class TestResultMerger:
    """结果合并器测试"""

    def test_deduplicate_items(self):
        """去重正确"""
        pass

    def test_aggregate_by_clause(self):
        """按条款聚合正确"""
        pass
```

### 7.2 集成测试

使用真实保险产品文档验证：
- 重疾险（大文档）
- 意外险（中文档）
- 医疗险（小文档）

对比分块前后的：
- 审查耗时
- 审查结果一致性
- LLM 调用次数

---

## 八、实施计划

### Phase 1：核心分块（1-2 天）

1. 实现 `DocumentChunker` 和 `RegulationBatcher`
2. 改造 `check_document()` 支持分块流程
3. 单元测试

### Phase 2：并行执行（1 天）

1. 实现 `ThreadPoolExecutor` 并行执行
2. 结果合并器
3. 集成测试

### Phase 3：生产验证（1 天）

1. 真实产品文档测试
2. 性能对比
3. 结果准确性验证

---

## 九、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 分块导致上下文丢失 | 条款含义理解不准确 | 条款粒度分块，保持语义完整 |
| 小 chunk 信息不足 | 检查结果不完整 | min_chunk_tokens 下限 + 相邻条款合并 |
| 并行导致内存溢出 | 程序崩溃 | 限制 parallel_workers |
| 结果合并不完整 | 审查报告缺失 | 完善去重逻辑 + 测试覆盖 |

---

## 十、预期效果

| 指标 | 当前 | 优化后（本地） | 优化后（远端） |
|------|------|---------------|---------------|
| 单次 LLM 调用 token | 60K-100K+ | 10K-15K | 10K-15K |
| 重疾险审查耗时 | 8977s | 预计 20-40 分钟 | 预计 5-10 分钟 |
| 意外险审查耗时 | 224.9s | 预计 5-10 分钟 | 预计 2-3 分钟 |
| 超时风险 | 高 | 低 | 极低 |
| 并行支持 | 无 | 支持 | 支持 |

---

## 十一、待确认事项

1. **并行 worker 数？** 建议：本地 4，远端 8
2. **负面清单是否保持独立？** 建议保持独立
3. **是否需要进度显示？** 大文档检查耗时长，建议增加进度回调
