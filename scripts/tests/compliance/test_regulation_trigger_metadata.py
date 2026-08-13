import pytest

from lib.common.compliance_audit import (
    ProofStrategy,
    TriggerFactName,
    TriggerOperator,
)
from lib.compliance.regulation_trigger_metadata import (
    RegulationTriggerMetadataError,
    parse_regulation_trigger_metadata,
)
from lib.compliance.regulation_units import aggregate_regulation_units


def _metadata(**overrides: object) -> dict[str, object]:
    metadata: dict[str, object] = {
        "触发事实": "has_policy_loan",
        "触发运算符": "equals",
        "触发期望值": "true",
        "目标条款主题": "policy.loan,policy.cash_value",
        "所需事实": "has_cash_value",
        "证明策略": "explicit_presence",
        "检索必含词组": "保单贷款",
        "检索任一词组": "贷款比例,现金价值",
        "触发条件说明": "产品提供保单贷款时触发",
    }
    metadata.update(overrides)
    return metadata


def _candidate(chunk_id: str, metadata: dict[str, object]) -> dict[str, object]:
    return {
        "id": chunk_id,
        "law_name": "测试法规",
        "article_number": "第十条",
        "source_file": "测试法规.md",
        "content": "法规正文",
        "applicability_status": "applicable",
        "metadata": {
            "section_path": "第十条",
            "chunk_index": int(chunk_id.rsplit("-", 1)[1]),
            **metadata,
        },
    }


def test_unconfigured_v5_metadata_has_no_trigger_spec():
    assert parse_regulation_trigger_metadata({"适用标签": "health"}) == ()


def test_valid_metadata_is_parsed_to_controlled_values():
    specs = parse_regulation_trigger_metadata(_metadata())

    assert len(specs) == 1
    spec = specs[0]
    assert spec.fact_name is TriggerFactName.HAS_POLICY_LOAN
    assert spec.operator is TriggerOperator.EQUALS
    assert spec.expected_value is True
    assert spec.target_topics == ("policy.loan", "policy.cash_value")
    assert spec.required_facts == (TriggerFactName.HAS_CASH_VALUE,)
    assert spec.proof_strategy is ProofStrategy.EXPLICIT_PRESENCE
    assert spec.search_all_terms == ("保单贷款",)
    assert spec.search_any_terms == ("贷款比例", "现金价值")
    assert spec.exclusion_approved is False


def test_explicit_actuary_approval_is_preserved():
    spec = parse_regulation_trigger_metadata(_metadata(
        触发排除验收状态="已验收",
    ))[0]

    assert spec.exclusion_approved is True


def test_contains_any_is_rejected_until_a_string_fact_is_registered():
    with pytest.raises(RegulationTriggerMetadataError, match="布尔产品事实"):
        parse_regulation_trigger_metadata(_metadata(
            触发事实="mentions_out_of_hospital_drug",
            触发运算符="contains_any",
            触发期望值="院外购药、药店、院外购药",
            目标条款主题="coverage.medical",
            所需事实="",
        ))


def test_exists_accepts_an_explicit_boolean_expectation():
    spec = parse_regulation_trigger_metadata(_metadata(
        触发事实="has_cash_value",
        触发运算符="exists",
        触发期望值="false",
        目标条款主题="policy.cash_value",
        所需事实="",
        证明策略="explicit_negation",
    ))[0]

    assert spec.expected_value is False


def test_numeric_expected_value_requires_a_number():
    with pytest.raises(RegulationTriggerMetadataError, match="必须是数值"):
        parse_regulation_trigger_metadata(_metadata(
            触发事实="waiting_period_days",
            触发运算符="less_than_or_equal",
            触发期望值="一百八十天",
            目标条款主题="coverage.waiting_period",
            所需事实="",
            证明策略="numeric_fact",
        ))


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"触发运算符": ""}, "触发运算符必须是非空字符串"),
        ({"触发运算符": "python_eval"}, "触发运算符非法"),
        ({"触发事实": "has_unknown_feature"}, "触发事实未注册"),
        ({"证明策略": "model_guess"}, "证明策略非法"),
        ({"目标条款主题": "policy.unknown"}, "引用未注册主题"),
        (
            {
                "证明策略": "closed_phrase_scan",
                "检索必含词组": "",
                "检索任一词组": "",
            },
            "closed_phrase_scan 必须配置",
        ),
        (
            {
                "证明策略": "closed_phrase_scan",
                "检索任一词组": "保单贷款",
            },
            "开放世界产品功能事实",
        ),
        ({"触发排除验收状态": "自动通过"}, "必须是 pending 或 approved"),
        ({"触发期望值": 1}, "equals 期望值必须是 true 或 false"),
        ({"触发期望值": 0}, "equals 期望值必须是 true 或 false"),
        ({"触发期望值": 2}, "equals 期望值必须是 true 或 false"),
    ],
)
def test_invalid_or_partial_metadata_is_rejected(
    overrides: dict[str, object],
    error: str,
):
    with pytest.raises(RegulationTriggerMetadataError, match=error):
        parse_regulation_trigger_metadata(_metadata(**overrides))


def test_numbered_trigger_columns_compile_to_and_specs():
    specs = parse_regulation_trigger_metadata({
        "触发事实1": "has_renewal",
        "触发运算符1": "equals",
        "触发期望值1": True,
        "目标条款主题1": "renewal.non_guaranteed",
        "证明策略1": "semantic_fact",
        "触发事实2": "is_rate_adjustable",
        "触发运算符2": "equals",
        "触发期望值2": True,
        "目标条款主题2": "premium.rate_adjustment",
        "证明策略2": "semantic_fact",
    })

    assert [spec.fact_name for spec in specs] == [
        TriggerFactName.HAS_RENEWAL,
        TriggerFactName.IS_RATE_ADJUSTABLE,
    ]


def test_unnumbered_first_trigger_can_be_followed_by_numbered_second():
    specs = parse_regulation_trigger_metadata({
        "触发事实": "has_renewal",
        "触发运算符": "equals",
        "触发期望值": True,
        "证明策略": "semantic_fact",
        "触发事实2": "is_rate_adjustable",
        "触发运算符2": "equals",
        "触发期望值2": True,
        "证明策略2": "semantic_fact",
    })

    assert len(specs) == 2


def test_numbered_trigger_columns_must_be_contiguous():
    with pytest.raises(RegulationTriggerMetadataError, match="连续编号"):
        parse_regulation_trigger_metadata({
            "触发事实2": "has_renewal",
            "触发运算符2": "equals",
            "触发期望值2": True,
            "证明策略2": "semantic_fact",
        })


def test_aggregation_preserves_trigger_spec_on_unit_and_chunks():
    result = aggregate_regulation_units(
        [
            _candidate("chunk-1", _metadata()),
            _candidate("chunk-2", _metadata()),
        ],
        kb_version="v5",
    )

    assert not result.errors
    assert len(result.units) == 1
    unit = result.units[0]
    assert unit.trigger_specs[0].fact_name is TriggerFactName.HAS_POLICY_LOAN
    assert all(chunk.trigger_specs == unit.trigger_specs for chunk in unit.chunks)


def test_aggregation_keeps_unconfigured_v5_unit_unchanged():
    result = aggregate_regulation_units(
        [_candidate("chunk-1", {"适用标签": "health"})],
        kb_version="v5",
    )

    assert not result.errors
    assert result.units[0].trigger_specs == ()


def test_invalid_trigger_metadata_keeps_unit_without_trigger_filtering():
    result = aggregate_regulation_units(
        [
            _candidate("chunk-1", _metadata()),
            _candidate("chunk-2", _metadata(触发运算符="python_eval")),
        ],
        kb_version="v5",
    )

    assert len(result.units) == 1
    assert result.units[0].trigger_specs == ()
    assert all(chunk.trigger_specs == () for chunk in result.units[0].chunks)
    assert result.rejected_chunk_ids == ()
    assert "法规触发规格非法" in result.errors[0]
    assert "保守保留" in result.units[0].applicability_reasons[-1]


def test_inconsistent_trigger_specs_keep_unit_without_trigger_filtering():
    result = aggregate_regulation_units(
        [
            _candidate("chunk-1", _metadata()),
            _candidate("chunk-2", _metadata(触发事实="has_cash_value")),
        ],
        kb_version="v5",
    )

    assert len(result.units) == 1
    assert result.units[0].chunk_ids == ("chunk-1", "chunk-2")
    assert result.units[0].trigger_specs == ()
    assert result.rejected_chunk_ids == ()
    assert "触发规格不一致" in result.errors[0]
