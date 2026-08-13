"""用一次受控 LLM 请求补充产品级未决事实。

这一层只补充产品事实，不判断法规合规性。模型输出即使是 ``false`` 也不能
直接用于排除法规，因为语义判断不构成封闭扫描或明确互斥分类的安全反证。
任何协议、证据或调用失败都保留原 ``unknown``，避免把系统失败误写成产品事实。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    FactTruth,
    ProofStrategy,
    ProductFact,
    ProductFactEvidence,
    TriggerFactName,
)
from lib.llm.base import BaseLLMClient

logger = logging.getLogger(__name__)
_MIN_RESOLUTION_CONFIDENCE = 0.8
_MIN_EVIDENCE_CHARACTERS = 6
_FACT_DEFINITIONS_PATH = Path(__file__).parent / "data" / "product_fact_definitions.json"
_MISSING_CLIENT_ERROR = "未提供事实补充模型客户端，所有未决事实保持 unknown"

CandidateClauseIdsByFact = Mapping[TriggerFactName, Iterable[str]]
FactResolutionClientFactory = Callable[[], BaseLLMClient]


@dataclass(frozen=True)
class _SemanticFactDefinition:
    description: str
    evidence_any_terms: Tuple[str, ...]


@lru_cache(maxsize=1)
def _load_semantic_fact_definitions(
) -> Mapping[TriggerFactName, _SemanticFactDefinition]:
    try:
        raw = json.loads(_FACT_DEFINITIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取产品事实定义: {exc}") from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != "1.0.0":
        raise ValueError("产品事实定义缺少受支持的 schema_version")
    definitions = raw.get("semantic_boolean_facts")
    if not isinstance(definitions, Mapping):
        raise ValueError("产品事实定义必须包含 semantic_boolean_facts")
    parsed: Dict[TriggerFactName, _SemanticFactDefinition] = {}
    for raw_name, definition in definitions.items():
        try:
            fact_name = TriggerFactName(raw_name)
        except ValueError as exc:
            raise ValueError(f"产品事实定义引用未注册事实: {raw_name}") from exc
        if not isinstance(definition, Mapping):
            raise ValueError(f"产品事实定义必须是 object: {raw_name}")
        description = definition.get("description")
        evidence_terms = definition.get("evidence_any_terms")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"产品事实定义不能为空: {raw_name}")
        if (
            not isinstance(evidence_terms, list)
            or not evidence_terms
            or any(not isinstance(term, str) or not term.strip() for term in evidence_terms)
        ):
            raise ValueError(f"产品事实 evidence_any_terms 无效: {raw_name}")
        parsed[fact_name] = _SemanticFactDefinition(
            description=description.strip(),
            evidence_any_terms=tuple(dict.fromkeys(
                term.strip() for term in evidence_terms
            )),
        )
    return parsed


class _EvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class _FactOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_name: TriggerFactName
    truth: FactTruth
    confidence: float = Field(ge=0.0, le=1.0, strict=True)
    evidence: Tuple[_EvidenceOutput, ...] = ()


@dataclass(frozen=True)
class FactResolutionResult:
    """一次产品级事实补充的安全合并结果和校验轨迹。"""

    facts: Tuple[ProductFact, ...]
    requested_fact_names: Tuple[TriggerFactName, ...]
    resolved_fact_names: Tuple[TriggerFactName, ...]
    validation_errors: Tuple[str, ...]
    attempted: bool


def _unknown_fact_names(facts: Iterable[ProductFact]) -> Tuple[TriggerFactName, ...]:
    definitions = _load_semantic_fact_definitions()
    return tuple(dict.fromkeys(
        fact.name
        for fact in facts
        if fact.truth is FactTruth.UNKNOWN
        and not fact.unit
        and fact.name in definitions
    ))


def _unique_clauses(
    clauses: Iterable[AuditClauseSnapshot],
) -> Tuple[AuditClauseSnapshot, ...]:
    by_id: Dict[str, AuditClauseSnapshot] = {}
    for clause in clauses:
        by_id.setdefault(clause.clause_id, clause)
    return tuple(by_id.values())


def _clause_refs(
    clauses: Iterable[AuditClauseSnapshot],
) -> Dict[str, AuditClauseSnapshot]:
    return {
        f"P{index:03d}": clause
        for index, clause in enumerate(_unique_clauses(clauses), start=1)
    }


def _allowed_evidence_refs_by_fact(
    required_names: Iterable[TriggerFactName],
    clause_refs: Mapping[str, AuditClauseSnapshot],
    candidate_clause_ids_by_fact: Optional[CandidateClauseIdsByFact],
) -> Tuple[
    Dict[TriggerFactName, Tuple[str, ...]],
    Tuple[str, ...],
]:
    all_evidence_refs = tuple(clause_refs)
    evidence_ref_by_clause_id = {
        clause.clause_id: evidence_ref
        for evidence_ref, clause in clause_refs.items()
    }
    allowed: Dict[TriggerFactName, Tuple[str, ...]] = {}
    errors: List[str] = []
    for fact_name in required_names:
        if candidate_clause_ids_by_fact is None:
            allowed[fact_name] = all_evidence_refs
            continue
        clause_ids = tuple(dict.fromkeys(
            clause_id.strip()
            for clause_id in candidate_clause_ids_by_fact.get(fact_name, ())
            if isinstance(clause_id, str) and clause_id.strip()
        ))
        missing = tuple(
            clause_id
            for clause_id in clause_ids
            if clause_id not in evidence_ref_by_clause_id
        )
        if missing:
            errors.append(
                f"产品事实 {fact_name.value} 的候选条款 ID 不存在: "
                + ", ".join(missing)
            )
            allowed[fact_name] = ()
            continue
        allowed[fact_name] = tuple(
            evidence_ref_by_clause_id[clause_id]
            for clause_id in clause_ids
        )
        if not allowed[fact_name]:
            errors.append(
                f"产品事实 {fact_name.value} 没有候选产品条款，保持 unknown"
            )
    return allowed, tuple(errors)


def build_fact_resolution_messages(
    facts: Iterable[ProductFact],
    clauses: Iterable[AuditClauseSnapshot],
    candidate_clause_ids_by_fact: Optional[CandidateClauseIdsByFact] = None,
) -> List[Dict[str, str]]:
    """构建一个产品级批量请求；相同事实不会因多条法规重复出现。"""
    required_names = _unknown_fact_names(facts)
    if not required_names:
        raise ValueError("事实补充请求至少需要一个 unknown 产品事实")
    clause_refs = _clause_refs(clauses)
    if not clause_refs:
        raise ValueError("事实补充请求至少需要一个候选产品条款")
    allowed_by_fact, candidate_errors = _allowed_evidence_refs_by_fact(
        required_names,
        clause_refs,
        candidate_clause_ids_by_fact,
    )
    if candidate_errors:
        raise ValueError("；".join(candidate_errors))
    used_evidence_ids = frozenset(
        evidence_id
        for fact_name in required_names
        for evidence_id in allowed_by_fact[fact_name]
    )
    definitions = _load_semantic_fact_definitions()
    payload = {
        "required_fact_names": [name.value for name in required_names],
        "fact_tasks": [
            {
                "fact_name": name.value,
                "definition": definitions[name].description,
                "allowed_evidence_ids": allowed_by_fact[name],
            }
            for name in required_names
        ],
        "product_clauses": [
            {
                "evidence_id": evidence_id,
                "clause_id": clause.clause_id,
                "number": clause.number,
                "title": clause.title,
                "text": clause.text,
                "topics": clause.topics,
            }
            for evidence_id, clause in clause_refs.items()
            if evidence_id in used_evidence_ids
        ],
    }
    system = (
        "你只负责依据每个 fact_task 的受控 definition，从给定产品条款中识别产品事实，"
        "不判断任何法规是否合规。"
        "不得使用外部知识，不得把一个事实任务的结论当成另一个任务的证据。"
    )
    instruction = """输出一个 JSON 对象，不得输出 Markdown：
{"results": [{
  "fact_name": "<required_fact_names 中的值>",
  "truth": "true|false|unknown",
  "confidence": 0.95,
  "evidence": [{"evidence_id": "<P001等>", "quote": "<对应条款逐字摘录>"}]
}]}

约束：
1. required_fact_names 中每个事实必须且只能回答一次，不得省略、重复或新增事实。
2. 每个事实任务必须严格使用其 definition，独立判断、独立给出 evidence；
   不得按日常语言印象改写定义，也不得跨任务引用模型自己的结论。
3. evidence_id 只能使用该任务 allowed_evidence_ids 中的短 ID。
4. quote 必须是对应产品条款 text 中连续、逐字一致的原文。
5. true 或 false 必须有至少一条直接证据；证据不足或存在冲突时输出 unknown。
6. 不得因为没有找到关键词就输出 false；unknown 可以使用空 evidence。
7. 除 fact_name、truth、confidence、evidence 外不得输出其他字段。

事实补充包：
""" + json.dumps(payload, ensure_ascii=False)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": instruction},
    ]


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    first_newline = text.find("\n")
    if first_newline < 0:
        return text
    text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _parse_result_items(raw: str) -> Tuple[Tuple[object, ...], Tuple[str, ...]]:
    try:
        parsed = json.loads(_strip_code_fence(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        return (), (f"事实补充响应不是有效 JSON: {exc}",)
    if not isinstance(parsed, dict):
        return (), ("事实补充响应顶层必须是 object",)
    unexpected = tuple(key for key in parsed if key != "results")
    results = parsed.get("results")
    errors = tuple(f"事实补充响应包含未允许字段: {key}" for key in unexpected)
    if not isinstance(results, list):
        return (), (*errors, "事实补充响应必须包含 results 数组")
    return tuple(results), errors


def _group_outputs(
    items: Iterable[object],
    required_names: Tuple[TriggerFactName, ...],
) -> Tuple[Dict[str, List[object]], Tuple[str, ...]]:
    grouped: Dict[str, List[object]] = {}
    errors: List[str] = []
    required_values = frozenset(name.value for name in required_names)
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            errors.append(f"results[{index}] 必须是 object")
            continue
        raw_name = item.get("fact_name")
        if not isinstance(raw_name, str) or not raw_name:
            errors.append(f"results[{index}] 缺少有效 fact_name")
            continue
        if raw_name not in required_values:
            errors.append(f"返回未请求的产品事实: {raw_name}")
            continue
        grouped.setdefault(raw_name, []).append(item)
    return grouped, tuple(errors)


def _validated_fact(
    original: ProductFact,
    raw_output: object,
    clause_refs: Mapping[str, AuditClauseSnapshot],
    allowed_evidence_ids: Iterable[str],
) -> ProductFact:
    output = _FactOutput.model_validate(raw_output)
    if output.fact_name is not original.name:
        raise ValueError("fact_name 与待补充事实不一致")
    seen_ids = set()
    evidence: List[ProductFactEvidence] = []
    definition = _load_semantic_fact_definitions()[original.name]
    allowed_ids = frozenset(allowed_evidence_ids)
    for item in output.evidence:
        evidence_id = item.evidence_id.strip()
        quote = item.quote.strip()
        if evidence_id in seen_ids:
            raise ValueError(f"事实证据 ID 重复: {evidence_id}")
        seen_ids.add(evidence_id)
        clause = clause_refs.get(evidence_id)
        if clause is None:
            raise ValueError(f"事实证据 ID 无效: {evidence_id}")
        if evidence_id not in allowed_ids:
            raise ValueError(
                f"事实证据 ID 不属于该事实的候选条款: {evidence_id}"
            )
        if not quote or quote not in clause.text:
            raise ValueError(f"事实证据不是对应条款逐字子串: {evidence_id}")
        normalized_quote = re.sub(r"[\W_]+", "", quote, flags=re.UNICODE)
        if len(normalized_quote) < _MIN_EVIDENCE_CHARACTERS:
            raise ValueError(f"事实证据摘录过短: {evidence_id}")
        if not any(term in quote for term in definition.evidence_any_terms):
            raise ValueError(
                f"事实证据未包含受控业务词: {evidence_id}"
            )
        evidence.append(ProductFactEvidence(clause.clause_id, quote))
    if output.truth is FactTruth.UNKNOWN:
        return original
    if output.confidence < _MIN_RESOLUTION_CONFIDENCE:
        raise ValueError(
            f"模型置信度 {output.confidence:.3f} 低于 {_MIN_RESOLUTION_CONFIDENCE:.1f}"
        )
    if not evidence:
        raise ValueError("true/false 事实缺少产品条款证据")
    return replace(
        original,
        truth=output.truth,
        value=output.truth is FactTruth.TRUE,
        method="semantic_fact",
        confidence=output.confidence,
        evidence=tuple(evidence),
        reason=(
            "语义模型依据候选产品条款逐字证据补充该事实；"
            "语义 false 不构成排除法规的安全反证"
        ),
        safe_for_exclusion=False,
        proof_strategy=ProofStrategy.SEMANTIC_FACT,
    )


def resolve_unknown_product_facts(
    facts: Iterable[ProductFact],
    clauses: Iterable[AuditClauseSnapshot],
    llm: Optional[BaseLLMClient] = None,
    *,
    candidate_clause_ids_by_fact: Optional[CandidateClauseIdsByFact] = None,
    timeout_seconds: Optional[float] = None,
) -> FactResolutionResult:
    """一次补充全部 unknown 事实；任何失败都保留对应原事实。"""
    original_facts = tuple(facts)
    try:
        required_names = _unknown_fact_names(original_facts)
    except ValueError as exc:
        return FactResolutionResult(
            original_facts,
            (),
            (),
            (f"产品事实定义无效，所有未决事实保持 unknown: {exc}",),
            False,
        )
    if not required_names:
        return FactResolutionResult(original_facts, (), (), (), False)
    clause_refs = _clause_refs(clauses)
    if not clause_refs:
        return FactResolutionResult(
            original_facts,
            required_names,
            (),
            ("没有候选产品条款，所有未决事实保持 unknown",),
            False,
        )
    allowed_by_fact, candidate_errors = _allowed_evidence_refs_by_fact(
        required_names,
        clause_refs,
        candidate_clause_ids_by_fact,
    )
    request_names = tuple(
        fact_name for fact_name in required_names if allowed_by_fact[fact_name]
    )
    if not request_names:
        return FactResolutionResult(
            original_facts,
            (),
            (),
            candidate_errors,
            False,
        )
    request_facts = tuple(
        fact for fact in original_facts if fact.name in request_names
    )
    request_candidates = {
        fact_name: tuple(
            clause_refs[evidence_id].clause_id
            for evidence_id in allowed_by_fact[fact_name]
        )
        for fact_name in request_names
    }
    if timeout_seconds is not None and timeout_seconds <= 0:
        return FactResolutionResult(
            original_facts,
            request_names,
            (),
            (*candidate_errors, "事实补充时间预算已耗尽，所有未决事实保持 unknown"),
            False,
        )
    if llm is None:
        return FactResolutionResult(
            original_facts,
            request_names,
            (),
            (*candidate_errors, _MISSING_CLIENT_ERROR),
            False,
        )

    try:
        chat_kwargs: Dict[str, object] = {
            "temperature": 0.0,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        if timeout_seconds is not None:
            chat_kwargs["timeout"] = timeout_seconds
            chat_kwargs["_retry_deadline"] = (
                time.monotonic() + timeout_seconds
            )
        raw = llm.chat(
            build_fact_resolution_messages(
                request_facts,
                clause_refs.values(),
                request_candidates,
            ),
            **chat_kwargs,
        )
    except Exception as exc:
        logger.warning("产品未决事实批量补充失败: %s", exc)
        return FactResolutionResult(
            original_facts,
            request_names,
            (),
            (*candidate_errors, f"事实补充模型调用失败: {type(exc).__name__}"),
            True,
        )

    items, parse_errors = _parse_result_items(raw)
    grouped, grouping_errors = _group_outputs(items, request_names)
    errors = [*candidate_errors, *parse_errors, *grouping_errors]
    replacements: Dict[TriggerFactName, ProductFact] = {}
    originals = {fact.name: fact for fact in original_facts}
    for fact_name in request_names:
        raw_items = grouped.get(fact_name.value, [])
        if not raw_items:
            errors.append(f"未回答产品事实: {fact_name.value}")
            continue
        if len(raw_items) != 1:
            errors.append(
                f"产品事实重复回答 {len(raw_items)} 次: {fact_name.value}"
            )
            continue
        try:
            validated = _validated_fact(
                originals[fact_name],
                raw_items[0],
                clause_refs,
                allowed_by_fact[fact_name],
            )
        except (ValidationError, ValueError) as exc:
            errors.append(f"产品事实 {fact_name.value} 校验失败: {exc}")
            continue
        if validated.truth is not FactTruth.UNKNOWN:
            replacements[fact_name] = validated

    merged = tuple(
        replacements.get(fact.name, fact)
        if fact.truth is FactTruth.UNKNOWN
        else fact
        for fact in original_facts
    )
    return FactResolutionResult(
        facts=merged,
        requested_fact_names=request_names,
        resolved_fact_names=tuple(
            name for name in request_names if name in replacements
        ),
        validation_errors=tuple(errors),
        attempted=True,
    )


def _create_audit_llm_client() -> BaseLLMClient:
    from lib.config import get_audit_llm_config
    from lib.llm.factory import LLMClientFactory

    return LLMClientFactory.create_client(get_audit_llm_config())


def resolve_unknown_product_facts_with_audit_llm(
    facts: Iterable[ProductFact],
    clauses: Iterable[AuditClauseSnapshot],
    *,
    candidate_clause_ids_by_fact: Optional[CandidateClauseIdsByFact] = None,
    timeout_seconds: Optional[float] = None,
    client_factory: FactResolutionClientFactory = _create_audit_llm_client,
) -> FactResolutionResult:
    """使用审核模型补充事实，并在初始化或调用失败时安全保留 unknown。"""
    original_facts = tuple(facts)
    clause_snapshots = tuple(clauses)
    preflight = resolve_unknown_product_facts(
        original_facts,
        clause_snapshots,
        candidate_clause_ids_by_fact=candidate_clause_ids_by_fact,
        timeout_seconds=timeout_seconds,
    )
    if (
        not preflight.requested_fact_names
        or not clause_snapshots
        or timeout_seconds is not None and timeout_seconds <= 0
    ):
        return preflight
    preflight_errors = tuple(
        error for error in preflight.validation_errors
        if error != _MISSING_CLIENT_ERROR
    )
    try:
        client = client_factory()
    except Exception as exc:
        logger.warning("产品事实补充客户端初始化失败: %s", exc)
        return replace(
            preflight,
            validation_errors=(
                *preflight_errors,
                f"事实补充模型客户端初始化失败: {type(exc).__name__}",
            ),
            attempted=True,
        )
    try:
        return resolve_unknown_product_facts(
            original_facts,
            clause_snapshots,
            client,
            candidate_clause_ids_by_fact=candidate_clause_ids_by_fact,
            timeout_seconds=timeout_seconds,
        )
    finally:
        try:
            client.close()
        except Exception as exc:
            logger.warning("产品事实补充客户端关闭失败: %s", exc)
