from lib.common.product_tags import (
    ContractRole,
    CustomerScope,
    ProductLine,
    ProductSubtype,
    ProductTags,
    ProductTermClass,
)
from lib.rag_engine.layered_retrieval import layer_regulation_candidates


def _product(**overrides) -> ProductTags:
    values = {
        "line": ProductLine.HEALTH,
        "primary_subtype": ProductSubtype.MEDICAL,
        "term_class": ProductTermClass.SHORT_TERM,
        "customer_scope": CustomerScope.INDIVIDUAL,
        "contract_role": ContractRole.MAIN,
    }
    values.update(overrides)
    return ProductTags(**values)


def _candidate(
    article: str,
    tags: str = "",
    topics: str = "",
    score: float = 0.1,
    chunk_id: str = "",
    content: str = "",
    risk_triggers: str = "",
    fact_trigger: str = "",
) -> dict:
    candidate = {
        "law_name": "测试法规",
        "article_number": article,
        "content": content or article,
        "score": score,
        "metadata": {
            "适用标签": tags,
            "条款主题": topics,
            "风险触发标签": risk_triggers,
            "触发事实": fact_trigger,
        },
    }
    if chunk_id:
        candidate["id"] = chunk_id
    return candidate


def test_exact_topic_precedes_general_and_untagged():
    candidates = [
        _candidate("无主题", "health,short_term"),
        _candidate("通用续保", "health,short_term", "renewal.general"),
        _candidate("不保证续保", "health,short_term", "renewal.non_guaranteed"),
    ]

    result = layer_regulation_candidates(
        candidates, _product(), ("renewal.non_guaranteed",), top_k=3,
    )

    assert [item["article_number"] for item in result.chunks] == [
        "不保证续保", "通用续保", "无主题",
    ]


def test_applicable_precedes_indeterminate():
    candidates = [
        _candidate("期限未知候选", "health,long_term"),
        _candidate("明确适用", "health"),
    ]
    product = _product(term_class=ProductTermClass.UNKNOWN)

    result = layer_regulation_candidates(candidates, product, top_k=2)

    assert [item["article_number"] for item in result.chunks] == ["明确适用", "期限未知候选"]
    assert result.chunks[1]["applicability_status"] == "indeterminate"


def test_not_applicable_is_never_restored_by_fallback():
    candidates = [
        _candidate("寿险规则", "life"),
        _candidate("健康险规则", "health"),
    ]

    result = layer_regulation_candidates(
        candidates, _product(), ("unmapped.topic",), top_k=10,
    )

    assert [item["article_number"] for item in result.chunks] == ["健康险规则"]
    assert result.excluded_count == 1


def test_duplicate_law_and_article_is_kept_once():
    candidates = [
        _candidate("第1条", "health", score=0.2, chunk_id="chunk-1"),
        _candidate("第1条", "health", score=0.1, chunk_id="chunk-1"),
    ]

    result = layer_regulation_candidates(candidates, _product(), top_k=8)

    assert len(result.chunks) == 1
    assert result.candidate_count == 1


def test_distinct_chunks_from_same_article_are_preserved():
    candidates = [
        _candidate("第1条", "health", chunk_id="chunk-1", content="第一段"),
        _candidate("第1条", "health", chunk_id="chunk-2", content="第二段"),
    ]

    result = layer_regulation_candidates(candidates, _product(), top_k=8)

    assert [item["id"] for item in result.chunks] == ["chunk-1", "chunk-2"]
    assert result.candidate_count == 2


def test_topic_mismatch_alone_is_not_safety_fallback():
    candidate = _candidate(
        "其他主题", "health,short_term", "claim.payment", chunk_id="chunk-1",
    )

    result = layer_regulation_candidates(
        [candidate], _product(), ("renewal.non_guaranteed",), top_k=1,
    )

    assert result.chunks[0]["fallback_layer"] == "topic_mismatch_fallback"
    assert result.fallback_used is False


def test_rrf_score_orders_candidates_within_same_layer():
    candidates = [
        _candidate("低分", "health", score=0.01, chunk_id="low"),
        _candidate("高分", "health", score=0.20, chunk_id="high"),
    ]

    result = layer_regulation_candidates(candidates, _product(), top_k=2)

    assert [item["id"] for item in result.chunks] == ["high", "low"]


def test_unknown_regulation_tag_is_safe_fallback():
    candidate = _candidate("未来标签", "health,future_tag")

    result = layer_regulation_candidates([candidate], _product(), top_k=1)

    assert result.chunks[0]["applicability_status"] == "indeterminate"
    assert result.fallback_used is True


def test_risk_trigger_bypass_candidate_is_not_excluded():
    candidate = _candidate(
        "费率可调规则",
        "health,medical,long_term",
        risk_triggers="rate_adjustable",
    )

    result = layer_regulation_candidates(
        [candidate],
        _product(is_rate_adjustable=True),
        top_k=None,
    )

    assert result.excluded_count == 0
    assert result.chunks[0]["applicability_status"] == "applicable"
    assert "risk_trigger" in result.chunks[0]["matched_dimensions"]


def test_unknown_risk_trigger_keeps_candidate_as_safety_fallback():
    candidate = _candidate(
        "费率可调规则",
        "health,medical,long_term",
        risk_triggers="rate_adjustable",
    )

    result = layer_regulation_candidates(
        [candidate],
        _product(is_rate_adjustable=None),
        top_k=None,
    )

    assert result.excluded_count == 0
    assert result.chunks[0]["applicability_status"] == "indeterminate"
    assert result.fallback_used is True


def test_fact_trigger_keeps_candidate_before_trigger_evaluation_layer():
    candidate = _candidate(
        "续保责任规则",
        "health",
        fact_trigger="has_renewal",
    )

    result = layer_regulation_candidates(
        [candidate],
        _product(line=ProductLine.LIFE),
        top_k=None,
    )

    assert result.excluded_count == 0
    assert result.chunks[0]["applicability_status"] == "indeterminate"
    assert "fact_trigger" in result.chunks[0]["indeterminate_dimensions"]


def test_incomplete_fact_trigger_configuration_is_not_filtered_early():
    candidate = _candidate("缺少触发事实的规则", "health")
    candidate["metadata"].update({
        "触发运算符": "exists",
        "证明策略": "explicit_negation",
    })

    result = layer_regulation_candidates(
        [candidate],
        _product(line=ProductLine.LIFE),
        top_k=None,
    )

    assert result.excluded_count == 0
    assert result.chunks[0]["applicability_status"] == "indeterminate"
    assert "fact_trigger" in result.chunks[0]["indeterminate_dimensions"]
