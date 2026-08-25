"""operator_schema 加载与校验的单元测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.benchmark_mutation.operator_schema import (
    MutationOperator,
    MutationOperatorError,
    MutationTier,
    load_operators,
    parse_operator,
)

def _valid_operator_raw(**overrides):
    raw = {
        "operator_id": "OP-T01",
        "rule_ref": "产品责任设计#原序号=22",
        "tier": "insertion",
        "host_tags": ["participating"],
        "target_topics": ["policy.account_value"],
        "payload": {"insert_text": "本合同设立保单账户。"},
        "expected_decision": "violated",
        "description": "测试算子",
    }
    raw.update(overrides)
    return raw

class TestParseOperator:
    def test_valid_insertion_operator(self):
        op = parse_operator(_valid_operator_raw())
        assert op.tier is MutationTier.INSERTION
        assert op.host_tags == ("participating",)

    def test_rejects_non_violated_expectation(self):
        with pytest.raises(MutationOperatorError, match="violated"):
            parse_operator(_valid_operator_raw(expected_decision="satisfied"))

    def test_rejects_unknown_host_tag(self):
        with pytest.raises(MutationOperatorError, match="未知标签"):
            parse_operator(_valid_operator_raw(host_tags=["finance_tech"]))

    def test_rejects_empty_target_topics(self):
        with pytest.raises(MutationOperatorError, match="target_topics"):
            parse_operator(_valid_operator_raw(target_topics=[]))

    @pytest.mark.parametrize(
        "tier,payload",
        [
            (MutationTier.INSERTION, {}),
            (MutationTier.NUMERIC, {"from_value": "10年"}),
            (MutationTier.DELETION, {}),
            (MutationTier.REWRITE, {"anchor_text": "既往症"}),
        ],
    )
    def test_rejects_payload_missing_tier_fields(self, tier, payload):
        with pytest.raises(MutationOperatorError, match="payload"):
            parse_operator(_valid_operator_raw(tier=tier.value, payload=payload))

    def test_rejects_unknown_tier(self):
        with pytest.raises(MutationOperatorError):
            parse_operator(_valid_operator_raw(tier="transform"))

class TestLoadOperators:
    def test_default_library_loads_with_thirty_or_more(self):
        operators = load_operators()
        assert len(operators) >= 30
        assert len({op.operator_id for op in operators}) == len(operators)

    def test_rejects_duplicate_operator_ids(self, tmp_path: Path):
        raw = {"operators": [_valid_operator_raw(), _valid_operator_raw()]}
        path = tmp_path / "operators.json"
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(MutationOperatorError, match="重复"):
            load_operators(path)

    def test_rejects_empty_library(self, tmp_path: Path):
        path = tmp_path / "operators.json"
        path.write_text(json.dumps({"operators": []}), encoding="utf-8")
        with pytest.raises(MutationOperatorError, match="非空"):
            load_operators(path)

class TestRuleRefVerification:
    def _write_kb(self, tmp_path: Path, ordinal: str) -> None:
        rule_file = tmp_path / "01_负面清单检查" / "产品责任设计.md"
        rule_file.parent.mkdir(parents=True)
        rule_file.write_text(f"## 第1条检核规则\n> {ordinal}", encoding="utf-8")

    def _single_operator_library(self, tmp_path: Path) -> Path:
        path = tmp_path / "operators.json"
        path.write_text(
            json.dumps({"operators": [_valid_operator_raw()]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_verifies_rule_ref_against_kb(self, tmp_path: Path):
        self._write_kb(tmp_path, "原序号=22")
        operators = load_operators(self._single_operator_library(tmp_path), refs_dir=tmp_path)
        assert operators

    def test_rejects_missing_ordinal(self, tmp_path: Path):
        self._write_kb(tmp_path, "原序号=99")
        with pytest.raises(MutationOperatorError, match="未找到"):
            load_operators(self._single_operator_library(tmp_path), refs_dir=tmp_path)

class TestTierCoverage:
    def test_library_covers_all_four_tiers(self):
        operators = load_operators()
        tiers = {op.tier for op in operators}
        assert tiers == {MutationTier.INSERTION, MutationTier.NUMERIC, MutationTier.DELETION, MutationTier.REWRITE}

    def test_operator_is_frozen(self):
        op = parse_operator(_valid_operator_raw())
        with pytest.raises(AttributeError):
            op.operator_id = "OP-T02"
