# Actuary Sleuth RAG Engine - 评估体系改进方案

生成时间: 2026-04-03
源文档: research.md

基于 research.md 的分析，本方案聚焦 RAG 评估体系的准确性提升、数据集扩展和代码质量修复。

---

## 一、问题修复方案 ✅

### ⚡ 评估准确性问题 (P0 - 必须修复)

#### 问题 1.1: [P0] `_is_relevant()` 纯字符匹配导致检索评估指标失真 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/evaluator.py:149-184`
- **函数**: `_is_relevant()`
- **严重程度**: P0
- **影响范围**: 所有检索评估指标（Precision/Recall/MRR/NDCG）的准确性

##### 当前代码
```python
# scripts/lib/rag_engine/evaluator.py:149-184
def _contains_keyword(content: str, keywords: List[str]) -> bool:
    return any(kw in content for kw in keywords if len(kw) >= 2)


def _is_relevant(
    result: Dict[str, Any],
    evidence_docs: List[str],
    evidence_keywords: List[str],
) -> bool:
    content = result.get('content', '')
    source_file = result.get('source_file', '')
    law_name = result.get('law_name', '')

    if evidence_keywords:
        long_keywords = [kw for kw in evidence_keywords if len(kw) >= 2]
        matched = sum(1 for kw in long_keywords if kw in content)
        required = min(2, len(long_keywords))
        if matched >= required:
            return True

    doc_set = set(evidence_docs)
    if source_file and source_file in doc_set and evidence_keywords:
        if _contains_keyword(content, evidence_keywords):
            return True

    if law_name and evidence_docs:
        for doc in evidence_docs:
            doc_stem = doc.replace('.md', '').replace('_', '')
            if doc_stem and len(doc_stem) >= 4 and doc_stem in law_name:
                if evidence_keywords:
                    if _contains_keyword(content, evidence_keywords):
                        return True
                elif source_file and source_file in doc_set:
                    return True

    return False
```

##### 修复方案
保留现有三层匹配作为快速路径，新增 embedding 语义相似度作为第四层判断。当关键词匹配结果为"不相关"时，使用 embedding 相似度做二次判定（阈值 > 0.65 则视为相关）。这样既不会降低现有的召回率，还能减少语义等价但字面不匹配导致的漏判。

##### 代码变更
```python
# scripts/lib/rag_engine/evaluator.py
import math
import re
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field

from .eval_dataset import EvalSample, QuestionType
from .tokenizer import tokenize_chinese

logger = logging.getLogger(__name__)

_RAGAS_METRICS = ('faithfulness', 'answer_relevancy', 'answer_correctness')

_ANSWER_SENTENCE_PATTERN = re.compile(r'[^。！？\n]+[。！？\n]?')

# 语义相关性判定的 embedding 相似度阈值
_SEMANTIC_RELEVANCE_THRESHOLD = 0.65

# 缓存 embedding 模型实例
_embed_model_cache: Optional[Any] = None


def _get_embed_model():
    """延迟加载 embedding 模型（仅首次语义判定时初始化）"""
    global _embed_model_cache
    if _embed_model_cache is not None:
        return _embed_model_cache
    try:
        from lib.llm import LLMClientFactory
        from lib.rag_engine.llamaindex_adapter import get_embedding_model
        from lib.config import get_embed_llm_config
        _embed_model_cache = get_embedding_model(get_embed_llm_config())
        return _embed_model_cache
    except Exception as e:
        logger.warning(f"Embedding 模型加载失败，将仅使用关键词匹配: {e}")
        return None


def _compute_embedding_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的 embedding 余弦相似度"""
    embed_model = _get_embed_model()
    if embed_model is None:
        return 0.0
    try:
        from llama_index.core import Settings
        from llama_index.core import QueryBundle
        emb_a = embed_model.get_query_embedding(text_a)
        emb_b = embed_model.get_query_embedding(text_b)
        dot = sum(a * b for a, b in zip(emb_a, emb_b))
        norm_a = math.sqrt(sum(a * a for a in emb_a))
        norm_b = math.sqrt(sum(b * b for b in emb_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
    except Exception as e:
        logger.debug(f"Embedding 相似度计算失败: {e}")
        return 0.0


def _contains_keyword(content: str, keywords: List[str]) -> bool:
    return any(kw in content for kw in keywords if len(kw) >= 2)


def _is_relevant(
    result: Dict[str, Any],
    evidence_docs: List[str],
    evidence_keywords: List[str],
) -> bool:
    """判断检索结果是否与评估样本相关

    三层快速匹配 + embedding 语义判定：
    1. 关键词匹配：content 中匹配足够数量关键词
    2. 文件名匹配：source_file + 关键词
    3. 法规名匹配：law_name 包含 evidence_doc stem + 关键词
    4. 语义匹配：embedding 相似度 > 阈值（仅当前三层均不匹配时启用）
    """
    content = result.get('content', '')
    source_file = result.get('source_file', '')
    law_name = result.get('law_name', '')

    # 第一层：关键词匹配
    if evidence_keywords:
        long_keywords = [kw for kw in evidence_keywords if len(kw) >= 2]
        matched = sum(1 for kw in long_keywords if kw in content)
        required = min(2, len(long_keywords))
        if matched >= required:
            return True

    # 第二层：文件名匹配
    doc_set = set(evidence_docs)
    if source_file and source_file in doc_set and evidence_keywords:
        if _contains_keyword(content, evidence_keywords):
            return True

    # 第三层：法规名匹配
    if law_name and evidence_docs:
        for doc in evidence_docs:
            doc_stem = doc.replace('.md', '').replace('_', '')
            if doc_stem and len(doc_stem) >= 4 and doc_stem in law_name:
                if evidence_keywords:
                    if _contains_keyword(content, evidence_keywords):
                        return True
                elif source_file and source_file in doc_set:
                    return True

    # 第四层：embedding 语义判定（仅当 evidence_keywords 不为空且前三层不匹配时）
    if evidence_keywords:
        query_text = ' '.join(evidence_keywords)
        similarity = _compute_embedding_similarity(query_text, content)
        if similarity >= _SEMANTIC_RELEVANCE_THRESHOLD:
            return True

    return False
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/evaluator.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. Embedding 语义判定（推荐） | 兼顾字面匹配和语义等价，不改变现有召回 | 增加一次 embedding 调用开销 | ✅ |
| B. 使用 RAGAS context_relevance | 更准确的语义判断 | 依赖 RAGAS 安装 + LLM 调用，成本高 | ❌ |
| C. 仅优化关键词匹配规则 | 零额外开销 | 无法解决同义表达问题 | ❌ |

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Embedding 模型加载失败 | 中 | 回退到纯关键词匹配，行为不变 | try/except + 日志警告 |
| 语义阈值不当导致误判 | 中 | 部分样本相关性判断不准 | 阈值可通过常量调整，后续可配置化 |
| 评估速度变慢 | 低 | 每个"不相关"结果多一次 embedding 计算 | 仅在前三层不匹配时才触发 |

##### 测试建议
```python
# scripts/tests/lib/rag_engine/test_evaluator.py — 新增测试

def test_is_relevant_semantic_match(monkeypatch):
    """同义表达但字面不匹配时，embedding 语义判定应识别为相关"""
    # 模拟 embedding 相似度返回高值
    def mock_similarity(text_a, text_b):
        return 0.75
    monkeypatch.setattr(
        'lib.rag_engine.evaluator._compute_embedding_similarity',
        mock_similarity,
    )
    result = {
        'content': '观察期内发生保险事故不承担赔偿责任',
        'law_name': '健康保险管理办法',
        'source_file': 'other.md',
    }
    # "等待期" 和 "观察期" 同义，字面不匹配
    assert _is_relevant(result, ["05_健康保险产品开发.md"], ["等待期", "保险事故"]) is True


def test_is_relevant_semantic_below_threshold(monkeypatch):
    """embedding 相似度低于阈值时仍判为不相关"""
    def mock_similarity(text_a, text_b):
        return 0.4
    monkeypatch.setattr(
        'lib.rag_engine.evaluator._compute_embedding_similarity',
        mock_similarity,
    )
    result = {
        'content': '分红型保险的分红水平不确定',
        'law_name': '分红型人身保险',
        'source_file': '07_分红型人身保险.md',
    }
    assert _is_relevant(result, ["05_健康保险产品开发.md"], ["等待期"]) is False


def test_is_relevant_keyword_match_still_first(monkeypatch):
    """关键词匹配优先于 embedding 判定"""
    call_count = 0
    def mock_similarity(text_a, text_b):
        nonlocal call_count
        call_count += 1
        return 0.0
    monkeypatch.setattr(
        'lib.rag_engine.evaluator._compute_embedding_similarity',
        mock_similarity,
    )
    result = {
        'content': '等待期规定相关内容',
        'law_name': '未知',
        'source_file': 'other.md',
    }
    assert _is_relevant(result, ["05_健康保险产品开发.md"], ["等待期", "既往症"]) is True
    assert call_count == 0  # 关键词已匹配，不触发 embedding
```

##### 验收标准
- [ ] 关键词匹配的现有行为不变（所有现有测试通过）
- [ ] 同义表达（如"等待期"vs"观察期"）能被识别为相关
- [ ] Embedding 模型加载失败时优雅回退到纯关键词匹配
- [ ] 评估速度下降不超过 20%（仅"不相关"结果触发 embedding）

---

#### 问题 1.2: [P0] Recall 分母应为证据 Chunk 数而非文档数 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/evaluator.py:304`
- **函数**: `RetrievalEvaluator.evaluate()`
- **严重程度**: P0
- **影响范围**: Recall@K 指标可能被高估

##### 当前代码
```python
# evaluator.py:304
recall = min(sum(relevance) / len(sample.evidence_docs), 1.0) if sample.evidence_docs else 0.0
```

##### 修复方案
分母从 `len(sample.evidence_docs)` 改为 `len(sample.evidence_docs)`（当前数据集结构下证据以文档为单位），但增加文档内覆盖率检查。当检索结果来自 evidence_docs 中的文档时，检查该文档是否至少有一个 chunk 被检索到。

由于当前 `EvalSample` 的 `evidence_docs` 是文件名列表而非 Chunk ID 列表，在数据集结构升级前，将分母调整为"至少需要检索到的不同文档数"，即 `len(sample.evidence_docs)`，但要求检索到的相关文档必须覆盖至少一半的证据文档。

实际上，当前逻辑的分母 `len(sample.evidence_docs)` 已经是合理的（"有多少个证据文档被检索到了"），但上限 `min(..., 1.0)` 会掩盖多文档样本的覆盖不足问题。

**修正方案**：移除 `min(..., 1.0)` 上限，让 Recall 真实反映覆盖比例。

##### 代码变更
```python
# scripts/lib/rag_engine/evaluator.py:304
# 修改前:
recall = min(sum(relevance) / len(sample.evidence_docs), 1.0) if sample.evidence_docs else 0.0

# 修改后:
recall = sum(relevance) / len(sample.evidence_docs) if sample.evidence_docs else 0.0
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/evaluator.py:304` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 移除 min(..., 1.0) 上限（推荐） | Recall 真实反映覆盖比例，简单 | Recall 可能 > 1.0（不会，relevance 总和 ≤ evidence_docs 数） | ✅ |
| B. 升级为 Chunk 级证据标注 | 最精确 | 需要重构数据集，工作量大 | ⏳ 后续迭代 |
| C. 保持不变 | 零风险 | Recall 高估，掩盖问题 | ❌ |

> **注意**：实际上 `sum(relevance) ≤ len(results) ≤ top_k`，而 `len(evidence_docs)` 是证据文档数。对于 multi_hop 样本（2 个证据文档），检索到 1 个相关文档时 Recall = 0.5，这是合理的。`min(..., 1.0)` 上限在这种场景下不会触发（因为 sum(relevance) ≤ top_k = 5，而 evidence_docs 通常 ≥ 1）。但如果 top_k > len(evidence_docs)，理论上 sum(relevance) 可以 > len(evidence_docs)——不对，relevance 是每个 result 对 evidence_docs 的匹配，不是对每个 evidence_doc 的匹配。所以 `sum(relevance)` 的最大值是 `len(results)`（即 top_k），而分母是 `len(evidence_docs)`。当 top_k > evidence_docs 数量时，Recall 确实可能 > 1.0。移除 min 是正确的。

##### 测试建议
```python
# scripts/tests/lib/rag_engine/test_evaluator.py — 新增测试

def test_recall_no_cap_for_multi_doc_samples(mock_rag_engine):
    """多文档证据样本的 Recall 不应被 cap 在 1.0"""
    sample = EvalSample(
        id="multi_doc",
        question="万能险和分红险的区别",
        ground_truth="两者收益方式不同",
        evidence_docs=["12_万能型人身保险.md", "07_分红型人身保险.md"],
        evidence_keywords=["万能险", "分红险", "收益"],
        question_type=QuestionType.MULTI_HOP,
        difficulty="medium",
        topic="保险产品对比",
    )
    # 只检索到 1 个相关文档（另一个不相关）
    mock_rag_engine.search.return_value = [
        {'content': '万能险提供最低保证利率', 'law_name': '万能型人身保险', 'source_file': '12_万能型人身保险.md', 'score': 0.9},
        {'content': '分红险的分红水平不确定', 'law_name': '分红型人身保险', 'source_file': '07_分红型人身保险.md', 'score': 0.85},
    ]
    evaluator = RetrievalEvaluator(mock_rag_engine)
    result = evaluator.evaluate(sample, top_k=2)
    # 两个文档都相关 → recall = 2/2 = 1.0
    assert result['recall'] == pytest.approx(1.0)


def test_recall_reflects_partial_coverage(mock_rag_engine):
    """Recall 应真实反映部分覆盖"""
    sample = EvalSample(
        id="partial",
        question="互联网保险和信息披露的要求",
        ground_truth="需要满足多个条件",
        evidence_docs=["10_互联网保险产品.md", "04_信息披露规则.md", "01_保险法相关监管规定.md"],
        evidence_keywords=["互联网", "信息披露", "全流程"],
        question_type=QuestionType.MULTI_HOP,
        difficulty="hard",
        topic="综合监管",
    )
    # 3 个证据文档中只检索到 1 个相关
    mock_rag_engine.search.return_value = [
        {'content': '互联网保险全流程在线服务', 'law_name': '互联网保险产品', 'source_file': '10_互联网保险产品.md', 'score': 0.9},
        {'content': '不相关内容', 'law_name': '其他', 'source_file': 'other.md', 'score': 0.3},
    ]
    evaluator = RetrievalEvaluator(mock_rag_engine)
    result = evaluator.evaluate(sample, top_k=2)
    assert result['recall'] == pytest.approx(1.0 / 3.0)
```

##### 验收标准
- [ ] 现有单文档样本的 Recall 不变
- [ ] 多文档样本的 Recall 真实反映覆盖比例
- [ ] Recall 值域 [0.0, +∞)，不再人为 cap

---

#### 问题 1.3: [P0] 评估数据集仅 30 条，远不足以支撑统计显著评估 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/eval_dataset.py`
- **严重程度**: P0
- **影响范围**: 所有评估结论的统计显著性

##### 修复方案
扩展评估数据集到 100+ 条（分阶段实施，本期目标 100 条，后续扩展到 200+）。采用 LLM 辅助生成 + 人工审核的方式。利用现有的 `eval_samples` 数据库表和 `convert_to_eval_sample` API 建立持续扩展机制。

**分阶段实施**：
1. **Phase 1**：扩展到 60 条（在现有 30 条基础上新增 30 条）
2. **Phase 2**：扩展到 100 条
3. **Phase 3**：扩展到 200 条（需要 LLM 辅助生成 + 人工审核 pipeline）

本方案仅覆盖 Phase 1。

##### 代码变更
在 `eval_dataset.py` 中新增扩展数据集，保持与现有数据集格式一致：

```python
# scripts/lib/rag_engine/eval_dataset.py — 在 create_default_eval_dataset() 中追加

def create_default_eval_dataset() -> List[EvalSample]:
    """创建默认评估数据集（60 条，覆盖四种题型）。"""
    samples = _create_base_eval_dataset()
    samples.extend(_create_extended_eval_dataset())
    return samples


def _create_base_eval_dataset() -> List[EvalSample]:
    """基础评估数据集（30 条）"""
    return [
        # ... 现有的 30 条样本保持不变 ...
    ]


def _create_extended_eval_dataset() -> List[EvalSample]:
    """扩展评估数据集（30 条，Phase 1）

    聚焦保险产品审核场景：产品条款、费率、免责、等待期、续保等产品设计维度。
    不涵盖保险公司运营管理（注册资本变更、精算师聘用、理赔流程等）。
    """
    return [
        # ---- FACTUAL 扩展 (8 条) ----
        EvalSample(
            id="f013",
            question="万能型保险的结算利率如何确定？",
            ground_truth="万能型保险的结算利率由保险公司根据实际投资情况确定，每月公布一次。结算利率不得低于最低保证利率。",
            evidence_docs=["12_万能型人身保险.md"],
            evidence_keywords=["万能型", "结算利率", "最低保证利率"],
            question_type=QuestionType.FACTUAL,
            difficulty="medium",
            topic="万能型保险",
        ),
        EvalSample(
            id="f014",
            question="意外伤害保险的保险期间有什么限制？",
            ground_truth="意外伤害保险的保险期间不得少于1年，不得多于5年。保险期间届满后，投保人可以续保，但需重新核保。",
            evidence_docs=["09_意外伤害保险.md"],
            evidence_keywords=["意外伤害保险", "保险期间", "1年", "5年"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="意外伤害保险",
        ),
        EvalSample(
            id="f015",
            question="年金保险的犹豫期是多少天？",
            ground_truth="人身保险产品的犹豫期不少于15天。年金保险作为人身保险的一种，同样适用此规定。",
            evidence_docs=["01_保险法相关监管规定.md", "13_其他险种产品.md"],
            evidence_keywords=["犹豫期", "15天", "人身保险"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="年金保险",
        ),
        EvalSample(
            id="f016",
            question="新型人身保险产品在条款中应如何进行信息披露？",
            ground_truth="新型人身保险产品应在条款中以显著方式提示投保人关注保险责任、责任免除、退保损失等关键信息。产品说明材料应在官方网站提供。",
            evidence_docs=["04_信息披露规则.md"],
            evidence_keywords=["信息披露", "显著方式", "保险责任", "责任免除"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="信息披露",
        ),
        EvalSample(
            id="f017",
            question="健康保险产品的免赔额有什么规定？",
            ground_truth="医疗费用型健康保险可以设置免赔额，但税优健康险产品不得设置免赔额。免赔额的设置应当在条款中明确说明。",
            evidence_docs=["05_健康保险产品开发.md", "11_税优健康险.md"],
            evidence_keywords=["免赔额", "健康保险", "税优健康险"],
            question_type=QuestionType.FACTUAL,
            difficulty="medium",
            topic="健康保险",
        ),
        EvalSample(
            id="f018",
            question="普通型年金保险的评估利率有什么优惠政策？",
            ground_truth="普通型年金保险可享受1.15倍的评估利率优惠。这是对年金保险产品在定价时的一种政策支持，旨在鼓励长期储蓄型保险产品的发展。",
            evidence_docs=["06_普通型人身保险.md"],
            evidence_keywords=["年金保险", "评估利率", "1.15倍", "普通型"],
            question_type=QuestionType.FACTUAL,
            difficulty="medium",
            topic="年金保险",
        ),
        EvalSample(
            id="f019",
            question="意外伤害保险的免责条款包括哪些情形？",
            ground_truth="意外伤害保险的免责条款通常包括：故意行为、违法犯罪、醉驾、战争、核辐射等情形。免责条款应在条款中以显著方式提示投保人。",
            evidence_docs=["09_意外伤害保险.md", "02_负面清单.md"],
            evidence_keywords=["意外伤害", "免责条款", "故意行为", "显著方式"],
            question_type=QuestionType.FACTUAL,
            difficulty="medium",
            topic="意外伤害保险",
        ),
        EvalSample(
            id="f020",
            question="保险条款中的免责条款应如何标注？",
            ground_truth="保险条款中不得使用含糊不清的免责条款。责任免除条款应当使用通俗易懂的语言，在保单中以显著方式提示投保人阅读，并在投保单上作出足以引起投保人注意的提示。",
            evidence_docs=["02_负面清单.md", "04_信息披露规则.md"],
            evidence_keywords=["免责条款", "含糊不清", "显著方式", "通俗易懂"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="条款规范",
        ),

        # ---- MULTI_HOP 扩展 (8 条) ----
        EvalSample(
            id="m009",
            question="意外险和健康险在免责条款方面有什么共同点和区别？",
            ground_truth="共同点：两者都需要以显著方式提示免责条款，不得含糊不清。区别：意外险重点关注故意行为、违法犯罪等特定情形，健康险重点关注既往症、等待期等医疗相关情形。",
            evidence_docs=["09_意外伤害保险.md", "05_健康保险产品开发.md", "02_负面清单.md"],
            evidence_keywords=["免责条款", "意外险", "健康险", "显著方式", "区别"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="hard",
            topic="保险产品对比",
        ),
        EvalSample(
            id="m010",
            question="一个产品如果同时是万能型和互联网销售的，需要满足哪些监管要求？",
            ground_truth="需要同时满足万能型保险要求（最低保证利率、账户价值透明、结算利率公布）和互联网保险要求（自营网络平台、网络安全等级保护、全流程在线服务、消费者权益保护）。两个维度的要求相互叠加。",
            evidence_docs=["12_万能型人身保险.md", "10_互联网保险产品.md"],
            evidence_keywords=["万能型", "互联网", "最低保证利率", "全流程在线", "叠加"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="hard",
            topic="综合监管",
        ),
        EvalSample(
            id="m011",
            question="负面清单对健康险和年金险的信息披露有什么不同要求？",
            ground_truth="健康险需明确说明等待期、免赔额、既往症处理等关键信息。年金险需明确说明年金领取方式、领取年龄、保证领取期限。两者都需遵循信息披露的真实性、准确性、完整性原则。",
            evidence_docs=["05_健康保险产品开发.md", "13_其他险种产品.md", "04_信息披露规则.md"],
            evidence_keywords=["负面清单", "健康险", "年金险", "信息披露", "等待期"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="hard",
            topic="综合监管",
        ),
        EvalSample(
            id="m012",
            question="保险公司如果同时经营普通型、分红型和万能型产品，佣金管理有什么统一规则？",
            ground_truth="所有类型产品的佣金均以定价时的附加费用率为上限。普通型年金保险可享受1.15倍评估利率优惠。佣金应当合理，不得通过高额佣金进行不正当竞争。不同类型产品分别适用各自的佣金管理规定。",
            evidence_docs=["06_普通型人身保险.md", "07_分红型人身保险.md", "12_万能型人身保险.md"],
            evidence_keywords=["佣金", "附加费用率", "普通型", "分红型", "万能型"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="hard",
            topic="佣金管理",
        ),
        EvalSample(
            id="m013",
            question="如果一份保险产品既涉及健康险又涉及税优政策，在产品设计上需要特别注意什么？",
            ground_truth="税优健康险不得因既往症拒保，医疗费用型不得设置免赔额。产品设计需同时满足健康险的产品开发规范和税优政策的特殊要求，如投保人范围（本人、配偶、子女、父母）等。",
            evidence_docs=["05_健康保险产品开发.md", "11_税优健康险.md"],
            evidence_keywords=["税优", "健康险", "既往症", "免赔额", "投保人范围"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="hard",
            topic="健康保险",
        ),
        EvalSample(
            id="m014",
            question="保险公司在条款设计上如何同时满足负面清单和保险法的要求？",
            ground_truth="条款设计需满足保险法的格式要求（通俗易懂、显著提示免责条款）和负面清单的禁止性规定（不得含糊不清、不得有误导性条款）。两者从不同角度约束条款设计，共同保障消费者权益。",
            evidence_docs=["01_保险法相关监管规定.md", "02_负面清单.md", "03_条款费率管理办法.md"],
            evidence_keywords=["条款设计", "负面清单", "保险法", "通俗易懂", "禁止"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="hard",
            topic="综合监管",
        ),
        EvalSample(
            id="m015",
            question="短期健康险转换为长期健康险时，续保条款需要注意什么？",
            ground_truth="短期健康险不得保证续保，到期后需重新核保。如转为长期健康险，需重新签订合同，适用长期险的条款和费率。注意不得在短期险条款中使用"自动续保"等误导性表述。",
            evidence_docs=["08_短期健康保险.md", "05_健康保险产品开发.md"],
            evidence_keywords=["短期健康险", "长期健康险", "保证续保", "重新核保", "转换"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="medium",
            topic="健康保险",
        ),
        EvalSample(
            id="m016",
            question="从消费者权益保护角度，互联网保险和传统保险在信息披露上有何不同？",
            ground_truth="互联网保险除了满足一般信息披露要求外，还需在网页显著位置展示产品条款、费率表、免责条款等，提供在线客服和投诉渠道。传统保险通过纸质材料或柜台方式披露。",
            evidence_docs=["10_互联网保险产品.md", "04_信息披露规则.md"],
            evidence_keywords=["消费者权益", "互联网保险", "信息披露", "显著位置", "在线"],
            question_type=QuestionType.MULTI_HOP,
            difficulty="medium",
            topic="互联网保险",
        ),

        # ---- NEGATIVE 扩展 (8 条) ----
        EvalSample(
            id="n007",
            question="税优健康险产品可以设置等待期吗？",
            ground_truth="税优健康险不得因被保险人既往病史拒保，医疗费用型税优健康险不得设置免赔额或等待期。",
            evidence_docs=["11_税优健康险.md"],
            evidence_keywords=["税优健康险", "等待期", "不得设置", "免赔额"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="税优健康险",
        ),
        EvalSample(
            id="n008",
            question="万能型保险可以承诺保底收益上不封顶吗？",
            ground_truth="万能型保险的最低保证利率由保险公司自主确定，但不得超过监管规定的准备金评估利率上限。结算利率根据实际投资情况确定，不承诺上不封顶。",
            evidence_docs=["12_万能型人身保险.md"],
            evidence_keywords=["万能型", "保证利率", "上限", "不得"],
            question_type=QuestionType.NEGATIVE,
            difficulty="medium",
            topic="万能型保险",
        ),
        EvalSample(
            id="n009",
            question="保险条款可以使用含糊不清的免责条款吗？",
            ground_truth="保险条款中不得使用含糊不清的免责条款。责任免除条款应当使用通俗易懂的语言，在保单中以显著方式提示投保人阅读。",
            evidence_docs=["02_负面清单.md", "04_信息披露规则.md"],
            evidence_keywords=["免责条款", "含糊不清", "通俗易懂", "显著方式"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="条款规范",
        ),
        EvalSample(
            id="n010",
            question="保险公司可以在条款中使用"最终解释权归本公司所有"的表述吗？",
            ground_truth="保险条款中不得包含"最终解释权归本公司所有"等排除或限制投保人权利的格式条款。此类条款属于不公平格式条款，不具有法律效力。",
            evidence_docs=["02_负面清单.md", "01_保险法相关监管规定.md"],
            evidence_keywords=["最终解释权", "格式条款", "不得", "排除权利"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="条款规范",
        ),
        EvalSample(
            id="n011",
            question="意外伤害保险的保费可以低于成本价销售吗？",
            ground_truth="意外伤害保险应当回归保障本源，科学合理定价，保费应当根据风险程度合理厘定，不得低于成本价销售。",
            evidence_docs=["09_意外伤害保险.md"],
            evidence_keywords=["意外伤害保险", "定价", "低于成本", "保障本源"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="意外伤害保险",
        ),
        EvalSample(
            id="n012",
            question="保险条款费率可以不经过审批就直接使用吗？",
            ground_truth="人身保险公司开发的保险条款和保险费率应当依法报经金融监督管理部门审批或者备案。审批和备案的具体要求按照相关规定执行。",
            evidence_docs=["03_条款费率管理办法.md"],
            evidence_keywords=["条款", "费率", "审批", "备案", "不得"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="条款费率管理",
        ),
        EvalSample(
            id="n013",
            question="分红险可以将不确定的分红宣传为确定收益吗？",
            ground_truth="分红险的分红水平不确定，根据公司实际经营状况确定。保险公司不得承诺保证分红金额，不得将不确定的分红宣传为确定收益。",
            evidence_docs=["07_分红型人身保险.md", "02_负面清单.md"],
            evidence_keywords=["分红", "不确定", "不得承诺", "确定收益"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="分红型保险",
        ),
        EvalSample(
            id="n014",
            question="短期健康险可以在条款中写"终身续保"吗？",
            ground_truth="短期健康保险严禁使用"终身续保"等易与长期健康保险混淆的表述。短期健康险的保险期间届满后需重新投保。",
            evidence_docs=["08_短期健康保险.md"],
            evidence_keywords=["短期健康险", "终身续保", "严禁", "混淆"],
            question_type=QuestionType.NEGATIVE,
            difficulty="easy",
            topic="短期健康保险",
        ),

        # ---- COLLOQUIAL 扩展 (6 条) ----
        EvalSample(
            id="c005",
            question="我买了两份医疗险，能重复报销吗？",
            ground_truth="医疗费用型保险适用补偿原则，不能重复报销。多份医疗险的报销总额不超过实际医疗费用。但定额给付型保险不受此限制。",
            evidence_docs=["05_健康保险产品开发.md", "01_保险法相关监管规定.md"],
            evidence_keywords=["医疗险", "重复报销", "补偿原则", "定额给付"],
            question_type=QuestionType.COLLOQUIAL,
            difficulty="medium",
            topic="医疗保险",
        ),
        EvalSample(
            id="c006",
            question="这个意外险能保多久？",
            ground_truth="意外伤害保险的保险期间不得少于1年，不得多于5年。具体保障期限以保险合同约定为准。",
            evidence_docs=["09_意外伤害保险.md"],
            evidence_keywords=["意外伤害保险", "保险期间", "1年", "5年"],
            question_type=QuestionType.COLLOQUIAL,
            difficulty="easy",
            topic="意外伤害保险",
        ),
        EvalSample(
            id="c007",
            question="分红险的收益是写进合同里的吗？",
            ground_truth="分红险的分红水平不确定，不写入合同保证金额。分红根据公司实际经营状况确定，分红方式包括现金分红和增额红利，需在条款中说明分红计算方法。",
            evidence_docs=["07_分红型人身保险.md"],
            evidence_keywords=["分红险", "分红", "不确定", "条款"],
            question_type=QuestionType.COLLOQUIAL,
            difficulty="medium",
            topic="分红型保险",
        ),
        EvalSample(
            id="c008",
            question="这个保险生病了能赔多少？",
            ground_truth="赔付金额取决于具体保险合同的约定，包括保额、免赔额、赔付比例和年度限额等。不同产品赔付标准不同，需查看具体条款。",
            evidence_docs=["05_健康保险产品开发.md"],
            evidence_keywords=["生病", "赔付", "保额", "免赔额", "赔付比例"],
            question_type=QuestionType.COLLOQUIAL,
            difficulty="easy",
            topic="健康保险",
        ),
        EvalSample(
            id="c009",
            question="这个万能险的利息比银行高吗？",
            ground_truth="万能险的收益体现在账户价值增长，与银行存款利率没有直接可比性。万能险提供最低保证利率，实际结算利率根据投资情况可能高于或低于银行利率。",
            evidence_docs=["12_万能型人身保险.md"],
            evidence_keywords=["万能险", "利息", "最低保证利率", "结算利率", "账户价值"],
            question_type=QuestionType.COLLOQUIAL,
            difficulty="medium",
            topic="万能型保险",
        ),
        EvalSample(
            id="c010",
            question="体检报告有异常还能买保险吗？",
            ground_truth="体检报告有异常是否影响投保取决于异常的具体情况和保险公司的核保规则。一般健康险可能因特定异常加费、除外承保或延期承保。税优健康险不得因既往症拒保。",
            evidence_docs=["05_健康保险产品开发.md", "11_税优健康险.md"],
            evidence_keywords=["体检", "异常", "核保", "加费", "既往症"],
            question_type=QuestionType.COLLOQUIAL,
            difficulty="medium",
            topic="核保管理",
        ),
    ]
```

同步更新测试中的断言：

```python
# scripts/tests/lib/rag_engine/test_evaluator.py — 更新测试

class TestEvalDataset:
    def test_load_default_dataset(self):
        dataset = create_default_eval_dataset()
        assert len(dataset) == 60  # 30 基础 + 30 扩展

    def test_question_type_distribution(self):
        dataset = create_default_eval_dataset()
        type_counts = {}
        for s in dataset:
            t = s.question_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        assert type_counts['factual'] >= 18
        assert type_counts['multi_hop'] >= 12
        assert type_counts['negative'] >= 12
        assert type_counts['colloquial'] >= 8
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/eval_dataset.py` |
| 修改 | `scripts/tests/lib/rag_engine/test_evaluator.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 人工编写扩展 30 条（推荐） | 质量可控，与现有格式一致 | 工作量较大 | ✅ |
| B. LLM 自动生成 + 人工筛选 | 效率高，覆盖面广 | 需要 LLM 调用 + 人工审核流程 | ⏳ Phase 2-3 |
| C. 从线上 badcase 导入 | 最贴近真实场景 | 当前 badcase 数量可能不足 | ⏳ 持续进行 |

##### 验收标准
- [ ] 默认数据集从 30 条扩展到 60 条
- [ ] 四种题型比例合理：factual ≥ 18, multi_hop ≥ 12, negative ≥ 12, colloquial ≥ 8
- [ ] 每条样本的 evidence_docs 和 evidence_keywords 与 KB 实际文档对应
- [ ] 所有新增样本的序列化/反序列化 roundtrip 正常

---

### ⚠️ 质量问题 (P1)

#### 问题 2.1: [P1] 轻量级 faithfulness 对语义改写不敏感 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/evaluator.py:612-637`
- **函数**: `GenerationEvaluator._compute_faithfulness()`
- **严重程度**: P1
- **影响范围**: RAGAS 不可用时的生成评估准确性

##### 当前代码
```python
# evaluator.py:612-637
@staticmethod
def _compute_faithfulness(contexts: List[str], answer: str) -> float:
    if not contexts or not answer:
        return 0.0

    context_text = ' '.join(contexts)
    context_bigrams = _token_bigrams(context_text)
    answer_bigrams = _token_bigrams(answer)

    sentences = _ANSWER_SENTENCE_PATTERN.findall(answer)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
    if not sentences:
        return _bigram_overlap(answer_bigrams, context_bigrams)

    supported_count = 0
    for sentence in sentences:
        sentence_bigrams = _token_bigrams(sentence)
        if not sentence_bigrams:
            continue
        covered = sentence_bigrams & context_bigrams
        if len(covered) / len(sentence_bigrams) >= 0.3:
            supported_count += 1

    sentence_coverage = supported_count / len(sentences)
    bigram_overlap = _bigram_overlap(answer_bigrams, context_bigrams)
    return 0.6 * sentence_coverage + 0.4 * bigram_overlap
```

##### 修复方案
提升阈值、增加 token 级覆盖检查作为补充、调整权重使句级覆盖更重要。

##### 代码变更
```python
# scripts/lib/rag_engine/evaluator.py — 替换 _compute_faithfulness 方法

# 提升句级覆盖阈值：0.3 → 0.4
_SENTENCE_COVERAGE_THRESHOLD = 0.4

@staticmethod
def _compute_faithfulness(contexts: List[str], answer: str) -> float:
    """轻量级忠实度计算（RAGAS 不可用时的 fallback）

    组合两个信号：
    1. 句级 bigram 覆盖率：每个句子是否被 context 支撑（阈值 0.4）
    2. 整体 token 覆盖率：answer 的 token 在 context 中出现的比例

    权重：0.7 * 句级 + 0.3 * 整体（提升句级权重以更严格检测幻觉）
    """
    if not contexts or not answer:
        return 0.0

    context_text = ' '.join(contexts)
    context_bigrams = _token_bigrams(context_text)
    answer_bigrams = _token_bigrams(answer)

    sentences = _ANSWER_SENTENCE_PATTERN.findall(answer)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
    if not sentences:
        return _bigram_overlap(answer_bigrams, context_bigrams)

    supported_count = 0
    for sentence in sentences:
        sentence_bigrams = _token_bigrams(sentence)
        if not sentence_bigrams:
            continue
        covered = sentence_bigrams & context_bigrams
        if len(covered) / len(sentence_bigrams) >= _SENTENCE_COVERAGE_THRESHOLD:
            supported_count += 1

    sentence_coverage = supported_count / len(sentences)
    bigram_overlap = _bigram_overlap(answer_bigrams, context_bigrams)
    return 0.7 * sentence_coverage + 0.3 * bigram_overlap
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/evaluator.py:612-637` |
| 修改 | `scripts/tests/lib/rag_engine/test_evaluator.py`（调整阈值相关的断言） |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 提升阈值 + 调整权重（推荐） | 减少漏检幻觉，不改变实现方式 | 可能增加 false positive | ✅ |
| B. 引入 token 级 Jaccard | 更细粒度 | 与 bigram overlap 高度冗余 | ❌ |
| C. 弃用轻量级指标，强制 RAGAS | 最准确 | 不安装 RAGAS 时无法评估 | ❌ |

##### 测试建议
```python
# 调整现有测试以反映新阈值
def test_lightweight_faithfulness_high():
    contexts = ['保险合同是投保人与保险人约定保险权利义务关系的协议']
    answer = '保险合同是投保人与保险人约定权利义务关系的协议'
    score = GenerationEvaluator._compute_faithfulness(contexts, answer)
    assert score > 0.8

def test_lightweight_faithfulness_strict():
    """含幻觉句子的答案应获得较低的忠实度"""
    contexts = ['保险合同是投保人与保险人约定保险权利义务关系的协议']
    # 第一句有支撑，第二句是幻觉
    answer = '保险合同是投保人与保险人约定的协议。万能保险的结算利率根据账户价值确定。'
    score = GenerationEvaluator._compute_faithfulness(contexts, answer)
    assert score < 0.6  # 更严格，只有 50% 的句子有支撑
```

##### 验收标准
- [ ] 句级覆盖阈值从 0.3 提升到 0.4
- [ ] 权重调整为 0.7 * 句级 + 0.3 * 整体
- [ ] 现有测试通过（调整断言范围）
- [ ] 包含幻觉的答案 faithfulness 显著降低

---

### ⚠️ 代码质量问题 (P2-P3)

#### 问题 3.1: [P3] BadcaseClassifier 中存在不可达代码 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/badcase_classifier.py:71-77`
- **严重程度**: P3
- **影响范围**: 代码可维护性

##### 当前代码
```python
# badcase_classifier.py:37-43 — 第一次检查
if unverified_claims:
    claims_preview = "；".join(unverified_claims[:3])
    return {
        "type": "hallucination",
        "reason": f"回答包含 {len(unverified_claims)} 条未引用的事实性陈述: {claims_preview}",
        "fix_direction": "加强 Prompt 忠实度约束，要求 LLM 严格引用来源",
    }

# ... 中间有 gap 答案检查 ...

# badcase_classifier.py:71-77 — 第二次检查（不可达）
if unverified_claims:
    claims_preview = "；".join(unverified_claims[:3])
    return {
        "type": "hallucination",
        "reason": f"回答包含 {len(unverified_claims)} 条未引用的事实性陈述: {claims_preview}",
        "fix_direction": "加强 Prompt 忠实度约束，要求 LLM 严格引用来源",
    }
```

##### 修复方案
删除第 71-77 行的不可达代码。

##### 代码变更
```python
# scripts/lib/rag_engine/badcase_classifier.py — 删除第 71-77 行

# 删除前（完整函数）：
def classify_badcase(query, retrieved_docs, answer, unverified_claims):
    combined_content = " ".join(d.get("content", "") for d in retrieved_docs)
    if not combined_content.strip():
        return {"type": "knowledge_gap", "reason": "检索结果为空", ...}

    if unverified_claims:                              # 第 37 行
        return {"type": "hallucination", ...}          # 第 38-43 行

    _gap_phrases = [...]
    is_gap_answer = any(phrase in answer for phrase in _gap_phrases)
    if is_gap_answer:
        if overlap > 2:
            return {"type": "retrieval_failure", ...}
        else:
            return {"type": "knowledge_gap", ...}

    if unverified_claims:                              # 第 71 行 ← 删除
        return {"type": "hallucination", ...}          # 第 72-77 行 ← 删除

    # bigram overlap 检查...

    return {"type": "retrieval_failure", ...}

# 删除后：直接从 is_gap_answer 检查跳到 bigram overlap 检查
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/badcase_classifier.py`（删除第 71-77 行） |

##### 验收标准
- [ ] 删除后所有现有测试通过
- [ ] 函数行为不变（死代码不影响输出）

---

#### 问题 3.2: [P2] `compute_retrieval_relevance()` 和 `_compute_context_relevance()` 逻辑重复 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/quality_detector.py:14-37` 和 `scripts/lib/rag_engine/evaluator.py:244-259`
- **严重程度**: P2
- **影响范围**: 代码维护性

##### 修复方案
将 bigram overlap 计算逻辑提取到 evaluator.py（已有 `_token_bigrams` 和 `_bigram_overlap`），quality_detector.py 复用 evaluator 的实现。

##### 代码变更
```python
# scripts/lib/rag_engine/quality_detector.py — 修改 compute_retrieval_relevance

from .evaluator import _token_bigrams


def compute_retrieval_relevance(query: str, sources: List[Dict[str, Any]]) -> float:
    """计算 query 与检索结果的 bigram 重叠度"""
    if not query or not sources:
        return 0.0

    query_bigrams = _token_bigrams(query)
    if not query_bigrams:
        return 0.0

    context_bigrams: set = set()
    for s in sources:
        content = s.get("content", "")
        if content:
            context_bigrams |= _token_bigrams(content)

    if not context_bigrams:
        return 0.0

    matched = query_bigrams & context_bigrams
    return len(matched) / len(query_bigrams)
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/quality_detector.py` |
| 不变 | `scripts/lib/rag_engine/evaluator.py`（作为公共函数被引用） |

##### 验收标准
- [ ] quality_detector.py 不再重复定义 `_token_bigrams`
- [ ] 所有现有测试通过

---

## 二、测试覆盖改进方案

### 当前测试覆盖分析

| 模块 | 覆盖率估算 | 备注 |
|------|-----------|------|
| `eval_dataset.py` | 90% | 序列化/反序列化完整 |
| `evaluator.py` (RetrievalEvaluator) | 85% | mock RAG engine，覆盖各分支 |
| `evaluator.py` (GenerationEvaluator lightweight) | 80% | faithfulness/correctness 测试充分 |
| `evaluator.py` (GenerationEvaluator RAGAS) | 30% | 需要 API key |
| `quality_detector.py` | **0%** | 无独立测试文件 |
| `badcase_classifier.py` | 70% | 有测试文件但缺少边界 case |
| `attribution.py` | 20% | 仅在 qa_prompt 测试中部分覆盖 |

### 测试缺口清单

| 优先级 | 模块 | 缺失测试 |
|--------|------|----------|
| P1 | `quality_detector.py` | 完全无测试 |
| P2 | `attribution.py` | `_detect_unverified_claims` 边界条件 |
| P2 | `badcase_classifier.py` | 空输入、超长输入 |
| P2 | `evaluator.py` | `run_retrieval_evaluation()` 未测试 |

### 新增测试计划

#### 2.1 QualityDetector 测试（P1）

```python
# scripts/tests/lib/rag_engine/test_quality_detector.py

import pytest
from lib.rag_engine.quality_detector import (
    detect_quality,
    compute_retrieval_relevance,
    compute_info_completeness,
)


class TestComputeRetrievalRelevance:
    def test_empty_inputs(self):
        assert compute_retrieval_relevance("", []) == 0.0
        assert compute_retrieval_relevance("query", []) == 0.0
        assert compute_retrieval_relevance("", [{"content": "test"}]) == 0.0

    def test_high_relevance(self):
        sources = [{"content": "健康保险等待期不得超过90天"}]
        score = compute_retrieval_relevance("健康保险等待期规定", sources)
        assert score > 0.5

    def test_low_relevance(self):
        sources = [{"content": "分红型保险的分红水平不确定"}]
        score = compute_retrieval_relevance("意外伤害保险免责条款", sources)
        assert score < 0.3

    def test_multiple_sources(self):
        sources = [
            {"content": "不相关内容"},
            {"content": "健康保险等待期规定"},
        ]
        score = compute_retrieval_relevance("健康保险等待期", sources)
        assert score > 0.0


class TestComputeInfoCompleteness:
    def test_no_numbers_in_query(self):
        assert compute_info_completeness("等待期有什么规定", "不超过90天") == 1.0

    def test_answer_contains_query_numbers(self):
        score = compute_info_completeness("等待期不超过多少天", "等待期不超过90天")
        assert score > 0.0

    def test_answer_missing_query_numbers(self):
        score = compute_info_completeness("佣金比例上限是多少", "佣金应当合理")
        assert score == 0.0

    def test_empty_inputs(self):
        assert compute_info_completeness("", "90天") == 0.0
        assert compute_info_completeness("等待期", "") == 0.0


class TestDetectQuality:
    def test_high_quality(self):
        result = detect_quality(
            query="健康保险等待期",
            answer="等待期不得超过90天",
            sources=[{"content": "健康保险等待期不得超过90天"}],
            faithfulness_score=0.9,
        )
        assert result["overall"] > 0.7
        assert result["faithfulness"] == 0.9

    def test_low_faithfulness(self):
        result = detect_quality(
            query="等待期",
            answer="万能保险结算利率根据账户价值确定",
            sources=[{"content": "健康保险等待期不得超过90天"}],
            faithfulness_score=0.2,
        )
        assert result["overall"] < 0.5

    def test_no_sources(self):
        result = detect_quality("等待期", "不确定", [])
        assert result["retrieval_relevance"] == 0.0

    def test_none_faithfulness_defaults_to_zero(self):
        result = detect_quality("query", "answer", [{"content": "query answer"}])
        assert result["faithfulness"] == 0.0
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 新增 | `scripts/tests/lib/rag_engine/test_quality_detector.py` |

#### 2.2 `run_retrieval_evaluation()` 测试（P2）

```python
# scripts/tests/lib/rag_engine/test_evaluator.py — 新增到 TestRetrievalEvaluator 类

def test_run_retrieval_evaluation_with_failures(mock_rag_engine):
    """run_retrieval_evaluation 应正确识别失败样本"""
    from lib.rag_engine.eval_dataset import create_default_eval_dataset
    from lib.rag_engine.evaluator import run_retrieval_evaluation

    # 所有检索结果都不相关
    mock_rag_engine.search.return_value = [
        {'content': '不相关内容', 'law_name': '其他', 'source_file': 'other.md', 'score': 0.5},
    ]
    samples = create_default_eval_dataset()[:5]
    report, failed = run_retrieval_evaluation(mock_rag_engine, samples, top_k=1)

    assert report.precision_at_k == 0.0
    assert len(failed) == 5
    for f in failed:
        assert f['failure_reason'] in ('检索无结果', '结果不相关', '排序错误（相关文档排名靠后）')


def test_run_retrieval_evaluation_all_pass(mock_rag_engine):
    """所有样本检索成功时 failed 列表为空"""
    from lib.rag_engine.eval_dataset import create_default_eval_dataset
    from lib.rag_engine.evaluator import run_retrieval_evaluation

    mock_rag_engine.search.return_value = [
        {'content': '等待期规定相关内容', 'law_name': '健康保险产品开发', 'source_file': '05_健康保险产品开发.md', 'score': 0.9},
    ]
    samples = create_default_eval_dataset()[:5]
    report, failed = run_retrieval_evaluation(mock_rag_engine, samples, top_k=1)

    assert len(failed) == 0
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/tests/lib/rag_engine/test_evaluator.py` |

---

## 三、技术债务清理方案

### 技术债务清单

| ID | 债务描述 | 位置 | 优先级 | 处理方式 |
|----|----------|------|--------|----------|
| TD-1 | 评估数据集仅 30 条 | `eval_dataset.py` | P0 | 本方案扩展到 60 条 |
| TD-2 | `_is_relevant()` 纯字符匹配 | `evaluator.py:149-184` | P0 | 本方案增加 embedding 语义判定 |
| TD-3 | Recall 分母有 cap | `evaluator.py:304` | P0 | 本方案移除 cap |
| TD-4 | 轻量级 faithfulness 阈值过低 | `evaluator.py:612-637` | P1 | 本方案提升阈值 |
| TD-5 | BadcaseClassifier 死代码 | `badcase_classifier.py:71-77` | P3 | 本方案删除 |
| TD-6 | bigram 重叠逻辑重复 | `quality_detector.py` vs `evaluator.py` | P2 | 本方案复用 |
| TD-7 | QualityDetector 无测试 | `test_quality_detector.py` | P1 | 本方案新增 |
| TD-8 | `run_retrieval_evaluation()` 未测试 | `test_evaluator.py` | P2 | 本方案新增 |
| TD-9 | 证据标注缺少 Chunk 级精度 | `eval_dataset.py` | P0 | 后续迭代 |
| TD-10 | Badcase → 测试集自动沉淀 | `feedback.py:convert_to_eval_sample` | P1 | 已有 API，需优化 |

### 清理路线图

```
Phase 1 (本期):
├── TD-1: 扩展数据集到 60 条
├── TD-2: 增强 _is_relevant() 语义判定
├── TD-3: 移除 Recall cap
├── TD-4: 提升轻量级 faithfulness 阈值
├── TD-5: 删除死代码
├── TD-6: 合并重复逻辑
├── TD-7: 新增 QualityDetector 测试
└── TD-8: 新增 run_retrieval_evaluation 测试

Phase 2 (后续):
├── TD-9: 升级证据标注为 Chunk 级别
├── TD-10: 优化 badcase 沉淀流程
└── 数据集扩展到 200+ 条
```

---

## 四、架构和代码质量改进

### 4.1 已有基础设施说明

在分析过程中发现系统已具备以下评估基础设施，**不需要重新构建**：

| 基础设施 | 状态 | 位置 |
|----------|------|------|
| 评估数据集 DB 表 | ✅ 已有 | `eval_samples` 表 |
| 评估运行记录 | ✅ 已有 | `eval_runs` 表 |
| 评估快照 | ✅ 已有 | `eval_snapshots` 表 |
| A/B 对比 API | ✅ 已有 | `POST /api/eval/runs/compare` |
| Badcase → 测试集转换 | ✅ 已有 | `POST /api/feedback/badcases/{id}/convert` |
| 评估报告导出 | ✅ 已有 | `GET /api/eval/runs/{id}/export` |
| CLI 评估脚本 | ✅ 已有 | `evaluate_rag.py`（含 `--compare`） |

**结论**：A/B 对比和 badcase 沉淀的**基础设施已完备**，当前短板主要在数据层（数据集太小）和算法层（相关性判断不准），本方案聚焦这两层。

### 4.2 不在本方案范围内（后续迭代）

| 项目 | 原因 | 建议 |
|------|------|------|
| Chunk 级证据标注 | 需要重构 EvalSample 数据结构和 KB 构建流程 | Phase 2 实施 |
| RAGAS 作为默认评估模式 | 需要确认部署环境 RAGAS 可用性 | 先在 CI 中验证 |
| 线上质量监控 | 需要 TruLens 等工具集成 | 独立任务 |
| LLM 自动生成测试集 | 需要 prompt 工程 + 人工审核流程 | Phase 2-3 |

---

## 附录

### 执行顺序建议

```
1. TD-5: 删除死代码（5 分钟，零风险，热身）
2. TD-6: 合并重复 bigram 逻辑（10 分钟）
3. TD-3: 移除 Recall cap（5 分钟）
4. TD-4: 提升 faithfulness 阈值（10 分钟）
5. TD-7: 新增 QualityDetector 测试（30 分钟）
6. TD-8: 新增 run_retrieval_evaluation 测试（15 分钟）
7. TD-2: 增强 _is_relevant() 语义判定（1 小时，核心改动）
8. TD-1: 扩展数据集到 60 条（2 小时，需要仔细编写和验证）
9. 运行全量测试确认无回归
```

### 变更摘要

| 文件 | 变更类型 | 变更内容 |
|------|----------|----------|
| `scripts/lib/rag_engine/evaluator.py` | 修改 | 增加 embedding 语义判定、移除 Recall cap、提升 faithfulness 阈值 |
| `scripts/lib/rag_engine/eval_dataset.py` | 修改 | 扩展默认数据集从 30 条到 60 条 |
| `scripts/lib/rag_engine/badcase_classifier.py` | 修改 | 删除不可达死代码（第 71-77 行） |
| `scripts/lib/rag_engine/quality_detector.py` | 修改 | 复用 evaluator 的 `_token_bigrams` |
| `scripts/tests/lib/rag_engine/test_evaluator.py` | 修改 | 更新数据集断言、新增语义判定测试、新增 run_retrieval_evaluation 测试 |
| `scripts/tests/lib/rag_engine/test_quality_detector.py` | **新增** | QualityDetector 完整测试 |

### 验收标准总结

#### 功能验收标准
- [ ] `_is_relevant()` 能识别语义等价但不字面匹配的相关内容
- [ ] `_is_relevant()` 在 embedding 模型不可用时优雅回退
- [ ] Recall 不再被 cap 在 1.0，真实反映多文档覆盖比例
- [ ] 轻量级 faithfulness 阈值提升到 0.4，权重调整为 0.7/0.3
- [ ] 默认评估数据集从 30 条扩展到 60 条
- [ ] BadcaseClassifier 死代码已删除
- [ ] QualityDetector 的 bigram 逻辑不再重复实现

#### 质量验收标准
- [ ] 所有现有测试通过
- [ ] 新增 test_quality_detector.py 覆盖 detect_quality 三个核心函数
- [ ] 新增 run_retrieval_evaluation 测试覆盖成功/失败两种场景
- [ ] `pytest scripts/tests/lib/rag_engine/` 全部通过

#### 部署验收标准
- [ ] 向后兼容：现有 API 接口不变
- [ ] 数据兼容：现有 eval_samples 表数据无需迁移
- [ ] 性能：检索评估速度下降不超过 20%
