# RAG 引擎优化计划

生成时间: 2026-03-26
版本: 2.1
状态: 待实施

---

## 一、问题陈述

### 1.1 当前方案的问题

基于 `research.md` 和微信文章《面试官：如何提升 RAG 检索质量？》的分析，当前 RAG 引擎存在以下问题：

| 问题 | 描述 | 严重性 | 影响 |
|------|------|--------|------|
| **融合算法非标准** | 使用加权平均而非 RRF | P1 | 融合效果不理想 |
| **缺少 Reranking** | 未实现 Cross-Encoder 重排序 | P0 | **最高 ROI 的优化缺失** |
| **配置循环依赖** | RAGConfig 初始化依赖全局配置 | P2 | 影响可测试性 |
| **BM25 算法简化** | IDF 固定为 1.0，无真实文档频率 | P2 | 关键词检索质量受限 |
| **资源清理不完整** | `cleanup()` 方法未完整实现 | P2 | 潜在内存泄漏 |
| **静默失败** | 初始化失败时记录日志但返回 None | P1 | 难以诊断问题 |
| **中文分词简单** | 使用正则表达式 | P3 | 分词质量有限 |
| **缺少缓存机制** | 频繁的相同查询无缓存 | P3 | 性能浪费 |

### 1.2 技术瓶颈

```
当前检索流程的瓶颈点:

[用户查询]
    ↓
[查询处理 - 无优化] ← 瓶颈1: 缺少 Query Rewriting/HyDE
    ↓
[向量检索 - Bi-Encoder] ← 瓶颈2: 独立编码，无查询-文档交互
    ↓
[关键词检索 - 简化BM25] ← 瓶颈3: IDF固定，无真实文档频率
    ↓
[结果融合 - 加权平均] ← 瓶颈4: 非标准融合算法
    ↓
[返回 Top-K] ← 瓶颈5: 缺少 Cross-Encoder Reranking
```

---

## 二、优化目标

### 2.1 核心目标

| 指标 | 当前 | 目标 | 提升 |
|------|------|------|------|
| **检索准确率** | ~75% | 90%+ | +15% |
| **排序质量 (NDCG@10)** | ~0.65 | 0.80+ | +23% |
| **召回率** | ~80% | 95%+ | +15% |
| **查询响应时间** | < 1s | < 1.5s | +50% (可接受) |
| **首次查询延迟** | ~500ms | < 800ms | +60% |

### 2.2 设计原则

1. **渐进式增强**: 先实现高 ROI 的优化，再考虑复杂特性
2. **向后兼容**: 新功能通过配置开关控制，不破坏现有行为
3. **可观测性**: 每个阶段都有监控和指标
4. **测试驱动**: 先写测试，再实现功能

---

## 三、技术方案

### 3.1 整体架构优化

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         优化后的 RAG 检索流程                                  │
└─────────────────────────────────────────────────────────────────────────────┘

[用户查询]
    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 阶段0: 查询优化 (可选)                                                       │
│ - Query Rewriting: 查询改写                                                 │
│ - HyDE: 生成假想答案进行检索                                                 │
│ - Multi-Query: 多角度查询扩展                                                │
└─────────────────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 阶段1: 粗召回 (Hybrid Search + RRF)                                         │
│ - 向量检索 (top-20)                                                         │
│ - 关键词检索 (top-20, 改进BM25)                                              │
│ - RRF 融合 (替代加权平均)                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 阶段2: 精排序 (Reranking) ← 最高 ROI                                        │
│ - Cross-Encoder 重排序                                                      │
│ - 从 top-20 精排到 top-5                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
    ↓
[最终结果]
```

### 3.2 核心组件

#### 3.2.1 RRF 融合算法

**文件**: `scripts/lib/rag_engine/fusion.py`

**职责**: 替代当前加权平均，实现标准 RRF 算法

**实现内容**:
```python
def rrf_fuse(
    vector_nodes: List,
    keyword_nodes: List,
    k: int = 60
) -> List[Dict[str, Any]]:
    """
    使用 RRF（Reciprocal Rank Fusion）融合结果

    RRF 公式：score(d) = Σ (k / (k + rank_i(d)))

    优势：
    - 无需归一化（BM25 和余弦相似度量纲不同）
    - 对排名更敏感，更符合人类感知
    - Elasticsearch 8.x 和主流向量数据库原生支持
    """
```

**验收标准**:
- RRF 融合结果质量优于加权平均 (通过人工评估)
- 单元测试覆盖 > 90%

**测试**:
```python
# tests/lib/rag_engine/test_rrf_fusion.py
def test_rrf_vs_weighted_average():
    """对比 RRF 和加权平均的效果"""
    vector_results = create_mock_vector_results(10)
    keyword_results = create_mock_keyword_results(10)

    rrf_results = rrf_fuse(vector_results, keyword_results)
    weighted_results = fuse_results(vector_results, keyword_results, 0.5)

    # 评估两种方法的质量差异
    assert evaluate_ranking_quality(rrf_results) >= evaluate_ranking_quality(weighted_results)
```

#### 3.2.2 Cross-Encoder Reranker

**文件**: `scripts/lib/rag_engine/reranker.py` (新建)

**职责**: 实现两阶段检索的精排阶段

**实现内容**:
```python
class CrossEncoderReranker:
    """使用 Cross-Encoder 进行重排序

    这是 RAG 优化的"性价比之王"：
    - Bi-Encoder (向量检索): 查询和文档独立编码，速度快但精度一般
    - Cross-Encoder (Reranker): 查询和文档拼接编码，精度高但速度慢

    两阶段架构：
    1. 粗召回: Bi-Encoder 召回 top-20
    2. 精排序: Cross-Encoder 精排到 top-5
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name)

    def rerank(
        self,
        query: str,
        candidates: List[NodeWithScore],
        top_k: int = 5
    ) -> List[NodeWithScore]:
        """对候选结果进行重排序"""
```

**验收标准**:
- 集成 bge-reranker-v2-m3 模型（本地部署或智谱 API）
- Reranking 后 NDCG@10 提升 > 15%
- 单次 Reranking 延迟 < 300ms
- 支持批量推理优化性能

**测试**:
```python
# tests/lib/rag_engine/test_reranker.py
def test_cross_encoder_reranker():
    reranker = CrossEncoderReranker()
    candidates = create_mock_candidates(20)
    query = "健康保险等待期有什么规定？"

    reranked = reranker.rerank(query, candidates, top_k=5)

    assert len(reranked) == 5
    assert reranked[0].score >= reranked[-1].score
    # 验证相关性更靠前
    assert all(r.score > 0.5 for r in reranked)
```

#### 3.2.3 改进的 BM25 算法

**文件**: `scripts/lib/rag_engine/fusion.py`

**职责**: 实现完整的 BM25 算法，包含真实 IDF 计算

**实现内容**:
```python
class BM25Scorer:
    """改进的 BM25 算法

    当前问题：IDF 固定为 1.0
    改进方案：计算真实的逆文档频率
    """

    def __init__(self, corpus: List[str]):
        """预计算文档频率"""
        self.doc_freq = self._compute_doc_frequency(corpus)
        self.idf = self._compute_idf()
        self.avg_doc_len = sum(len(doc.split()) for doc in corpus) / len(corpus)

    def compute_score(self, query: str, document: str) -> float:
        """计算 BM25 分数"""
        k1 = 1.5
        b = 0.75

        query_tokens = tokenize(query)
        doc_tokens = tokenize(document)

        score = 0.0
        for token in query_tokens:
            if token in doc_tokens:
                tf = doc_tokens.count(token)
                idf = self.idf.get(token, 0)
                doc_len = len(doc_tokens)
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / self.avg_doc_len))

        return score
```

**验收标准**:
- 支持文档频率预计算和缓存
- BM25 分数与标准实现一致
- 关键词检索准确率提升 > 10%

---

## 四、实施计划

### 4.1 第一阶段: 快速胜利 (1-2 周)

**目标**: 实现 RRF 融合和改进的 BM25，低风险高收益

#### 任务 1.1: 实现 RRF 融合算法

**文件**: `scripts/lib/rag_engine/fusion.py`

**修改内容**:
1. 新增 `rrf_fuse()` 函数（默认使用，替换加权平均）

**验收标准**:
- RRF 实现符合公式
- 单元测试覆盖

**测试**:
```python
def test_rrf_fusion():
    vector_results = create_mock_results(10)
    keyword_results = create_mock_results(10)

    rrf_results = rrf_fuse(vector_results, keyword_results)
    assert len(rrf_results) <= 20
    assert rrf_results[0]['score'] >= rrf_results[-1]['score']
```

#### 任务 1.2: 改进 BM25 算法

**文件**: `scripts/lib/rag_engine/fusion.py`

**修改内容**:
1. 创建 `BM25Scorer` 类
2. 实现文档频率预计算
3. 实现真实 IDF 计算

**验收标准**:
- 支持文档频率缓存
- BM25 分数正确
- 性能可接受

### 4.2 第二阶段: 核心优化 (2-3 周)

**目标**: 实现 Cross-Encoder Reranking（最高 ROI）

#### 任务 2.1: 实现 Cross-Encoder Reranker

**文件**: `scripts/lib/rag_engine/reranker.py` (新建)

**修改内容**:
1. 创建 `CrossEncoderReranker` 类
2. 集成 sentence-transformers
3. 实现批量推理优化

**验收标准**:
- 集成 bge-reranker-v2-m3
- Reranking 延迟 < 300ms
- NDCG@10 提升 > 15%

**测试**:
```python
def test_reranker_performance():
    reranker = CrossEncoderReranker()
    candidates = create_mock_candidates(20)

    start = time.time()
    results = reranker.rerank("测试查询", candidates, top_k=5)
    duration = time.time() - start

    assert duration < 0.3  # 延迟 < 300ms
    assert len(results) == 5
```

#### 任务 2.2: 集成到检索流程

**文件**: `scripts/lib/rag_engine/retriever.py`, `rag_engine.py`

**修改内容**:
1. 在 `hybrid_search()` 后添加 rerank 选项
2. 在 `RAGEngine.ask()` 中集成

**验收标准**:
- 端到端流程正常
- 错误处理完善

#### 任务 2.3: 性能优化

**修改内容**:
1. 实现 Reranker 模型懒加载
2. 支持批量推理
3. 添加缓存机制

**验收标准**:
- 首次 Reranking < 500ms (模型加载)
- 后续 Reranking < 300ms
- 内存占用合理

### 4.3 第三阶段: 查询优化 (2 周)

**目标**: 实现 Query Rewriting

#### 任务 3.1: 实现 Query Rewriting

**文件**: `scripts/lib/rag_engine/query_optimizer.py` (新建)

**修改内容**:
1. 创建 `QueryRewriter` 类
2. 实现 LLM 查询改写
3. 添加配置开关

**验收标准**:
- 查询改写延迟 < 500ms
- 改写后查询质量提升

### 4.4 第四阶段: 质量提升 (1-2 周)

**目标**: 修复现有问题，提升代码质量

#### 任务 4.1: 修复配置循环依赖

**文件**: `scripts/lib/rag_engine/config.py`

**修改内容**:
1. 重构 `RAGConfig.__post_init__()`
2. 移除对全局配置的依赖
3. 改用依赖注入

**验收标准**:
- 消除循环依赖
- 可独立测试

#### 任务 4.2: 完善资源清理

**文件**: `scripts/lib/rag_engine/rag_engine.py`

**修改内容**:
1. 实现 `cleanup()` 方法
2. 添加上下文管理器支持
3. 测试资源释放

**验收标准**:
- 资源正确释放
- 无内存泄漏

#### 任务 4.3: 改进错误处理

**文件**: `scripts/lib/rag_engine/rag_engine.py`

**修改内容**:
1. 将静默失败改为抛出异常
2. 添加特定异常类
3. 改进错误消息

**验收标准**:
- 错误可诊断
- 测试覆盖错误场景

---

## 五、技术选型

### 5.1 核心技术栈

| 需求 | 推荐方案 | 备选方案 | 原因 |
|------|----------|----------|------|
| **Reranker 模型** | bge-reranker-v2-m3 | Cohere Rerank API | 开源，中文支持好 |
| **Sentence Transformers** | sentence-transformers | - | Cross-Encoder 实现 |
| **中文分词** | jieba | pkuseg | 成熟稳定 |
| **缓存** | functools.lru_cache | Redis | 简单高效 |

### 5.2 外部依赖

```python
# requirements.txt 新增
sentence-transformers>=2.2.0    # Cross-Encoder Reranker
jieba>=0.42.1                   # 中文分词（改进 BM25）
flagembedding>=1.2.0            # bge-reranker 模型（可选）
```

### 5.3 配置新增

```python
# scripts/lib/rag_engine/config.py 新增
@dataclass
class RAGConfig:
    # 现有配置...
    fusion_strategy: str = "rrf"  # 默认使用 RRF

    # Reranking 配置
    enable_reranking: bool = True
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_top_k: int = 5
    rerank_recall_k: int = 20  # 精召回数量

    # 查询优化配置
    enable_query_rewriting: bool = False

    # BM25 配置
    use_improved_bm25: bool = True
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
```

---

## 六、风险控制

### 6.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Reranker 模型加载慢 | 高 | 中 | 懒加载，预热机制 |
| Reranking 延迟高 | 中 | 高 | 批量推理，模型量化 |
| RRF 效果不如预期 | 低 | 低 | A/B 测试，保留回退 |
| 内存占用增加 | 中 | 中 | 监控，设置限制 |

### 6.2 兼容性风险

| 风险 | 缓解措施 |
|------|----------|
| 破坏现有检索结果 | 配置开关，逐步迁移 |
| API 变更 | 保持向后兼容 |
| 性能下降 | 设置超时，降级机制 |

### 6.3 测试策略

**单元测试**:
- RRF 融合算法
- Reranker 各功能
- BM25 分数计算

**集成测试**:
- 端到端检索流程
- 配置切换测试
- 性能基准测试

**回归测试**:
- 确保现有功能正常
- 对比新旧方案质量

---

## 七、成功指标

### 7.1 定量指标

| 指标 | 基线 | 目标 | 测量方法 |
|------|------|------|----------|
| **NDCG@10** | 0.65 | 0.80+ | 测试集评估 |
| **召回率@10** | 80% | 95%+ | 测试集评估 |
| **检索准确率** | 75% | 90%+ | 人工评估 100 个查询 |
| **Reranking 延迟** | - | < 300ms | 性能监控 |
| **端到端延迟** | < 1s | < 1.5s | 性能监控 |

### 7.2 定性指标

- 用户满意度提升
- 检索结果相关性提升
- 代码可维护性提升

---

## 八、时间表

### 8.1 里程碑

| 里程碑 | 目标 | 时间 | 状态 |
|--------|------|------|------|
| **M1: RRF + 改进 BM25** | 快速胜利 | 第 2 周 | 待开始 |
| **M2: Reranking 实现** | 核心 ROI | 第 5 周 | 待开始 |
| **M3: 查询优化** | Query Rewriting | 第 7 周 | 待开始 |
| **M4: 质量提升** | 修复现有问题 | 第 9 周 | 待开始 |

### 8.2 详细排期

**第 1-2 周**: 第一阶段
- 任务 1.1: RRF 融合算法 (3 天)
- 任务 1.2: 改进 BM25 (3 天)
- 任务 1.3: 配置和测试 (2 天)

**第 3-5 周**: 第二阶段
- 任务 2.1: Cross-Encoder Reranker (5 天)
- 任务 2.2: 集成到检索流程 (3 天)
- 任务 2.3: 性能优化 (2 天)

**第 6-7 周**: 第三阶段
- 任务 3.1: Query Rewriting (3 天)
- 任务 3.2: 测试和调优 (3 天)

**第 8-9 周**: 第四阶段
- 任务 4.1: 修复配置依赖 (2 天)
- 任务 4.2: 完善资源清理 (2 天)
- 任务 4.3: 改进错误处理 (2 天)

**第 10 周**: 测试和上线
- 全面测试 (3 天)
- 文档编写 (2 天)

---

## 九、资源需求

### 9.1 人力资源

| 角色 | 人数 | 时间 | 职责 |
|------|------|------|------|
| 后端开发 | 1 | 全程 | 核心功能实现 |
| 测试工程师 | 1 | 第 2、5、9 周 | 测试用例编写 |

### 9.2 技术资源

- 开发环境: GPU 或 CPU (Reranker 推理)
- 测试环境: 模拟 Reranker
- 生产环境: 现有基础设施

### 9.3 外部服务

| 服务 | 用量 | 成本 |
|------|------|------|
| Reranker 模型 | 本地推理 | 免费 |
| LLM API (Query Rewriting) | ~200 次/天 | 现有预算 |

---

## 十、后续优化方向

### 10.1 短期 (3 个月)

1. **Parent-Child 索引**: 小 chunk 检索，大 chunk 返回
2. **查询结果缓存**: LRU 缓存频繁查询
3. **A/B 测试框架**: 自动对比优化效果

### 10.2 中期 (6 个月)

1. **Multi-Query**: 多角度查询扩展
2. **Contextual Compression**: 上下文压缩
3. **自适应融合**: 根据查询类型动态调整融合策略

### 10.3 长期 (1 年)

1. **Graph RAG**: 知识图谱增强检索
2. **Agentic RAG**: 自适应检索策略
3. **端到端优化**: 联合优化检索和生成

---

## 附录

### A. 相关文件

- `scripts/lib/rag_engine/research.md` - 深度研究报告
- `scripts/lib/rag_engine/optimization_analysis.md` - 优化分析报告
- 微信文章: https://mp.weixin.qq.cn/s/91fwfAhI8UEjGsOZ5Ztm9A

### B. 测试计划

- `tests/lib/rag_engine/test_rrf_fusion.py` - RRF 融合测试
- `tests/lib/rag_engine/test_reranker.py` - Reranker 测试
- `tests/lib/rag_engine/test_improved_bm25.py` - BM25 测试
- `tests/integration/test_rag_optimization.py` - 端到端测试

### C. 参考文档

- [RRF 论文](https://plg.uwaterloo.ca/~gvcormac/cormacksigir08-rrf.pdf)
- [BGE Reranker](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- [HyDE 论文](https://arxiv.org/abs/2212.14096)
