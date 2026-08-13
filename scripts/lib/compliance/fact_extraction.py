"""从产品条款块提取法规审核需要的可验证事实。"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Optional, Protocol, Tuple

from lib.common.compliance_audit import (
    ExtractedFact,
    FactKind,
    FactTruth,
    ProductFact,
    ProductFactEvidence,
    ProofStrategy,
    RegulationTriggerSpec,
    TriggerFactName,
)
from lib.common.constants import CoverageFactKeys
from lib.common.product_tags import ProductTags, RenewalType


class FactSourceBlock(Protocol):
    @property
    def clause_id(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def text(self) -> str: ...

    @property
    def topics(self) -> Tuple[str, ...]: ...


_NUMBER_PATTERN = r"([零〇一二两三四五六七八九十百千\d]+)"
_DURATION_PATTERN = re.compile(rf"{_NUMBER_PATTERN}\s*(个?月|年|天|日)")
_NEGATION_PREFIXES = ("不", "不得", "不能", "并非", "未", "无", "禁止")
_DURATION_CONTEXT_LABELS = (
    "等待期",
    "犹豫期",
    "保险期间",
    "保障期间",
    "缴费期间",
    "首次费率调整",
    "首次调整费率",
    "首次调整保险费率",
    "后续费率调整",
    "再次调整费率",
    "相邻两次费率调整",
    "每次费率调整",
)
_STRONG_BOUNDARIES = "。；;\n"
_BOOLEAN_FACT_SIGNALS: Mapping[
    TriggerFactName,
    Tuple[Tuple[str, ...], Tuple[re.Pattern[str], ...]],
] = {
    TriggerFactName.HAS_WAITING_PERIOD: (
        ("coverage.waiting_period",),
        (re.compile(r"等待期"),),
    ),
    TriggerFactName.HAS_HESITATION_PERIOD: (
        ("application.hesitation",),
        (re.compile(r"犹豫期"),),
    ),
    TriggerFactName.HAS_POLICY_LOAN: (
        ("policy.loan",),
        (re.compile(
            r"保单贷款|保单借款|保险单贷款|合同借款|"
            r"申请(?:保单|保险单)?(?:贷款|借款)"
        ),),
    ),
    TriggerFactName.HAS_CASH_VALUE: (
        ("policy.cash_value",),
        (re.compile(r"现金价值"),),
    ),
    TriggerFactName.HAS_GRACE_PERIOD: (
        ("premium.grace_period",),
        (re.compile(r"宽限期"),),
    ),
    TriggerFactName.HAS_RENEWAL: (
        (),
        (re.compile(
            r"可以申请续保|可申请续保|接受续保|同意续保|办理续保|"
            r"保证续保期间|续保申请|续保条件|不保证续保|非保证续保"
        ),),
    ),
    TriggerFactName.IS_RATE_ADJUSTABLE: (
        ("premium.rate_adjustment",),
        (re.compile(
            r"费率可调|有权调整(?:保险)?费率|"
            r"重新厘定(?:保险费率|保险费|费率)|"
            r"根据[^。；;\n]{0,20}(?:赔付|理赔)经验[^。；;\n]{0,20}"
            r"(?:调整|厘定)(?:保险费率|保险费|费率)"
        ),),
    ),
    TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG: (
        (),
        (re.compile(r"院外购药|药店"),),
    ),
    TriggerFactName.HAS_DEATH_BENEFIT: (
        ("coverage.death",),
        (re.compile(r"身故保险金|死亡保险金|死亡给付|身故责任"),),
    ),
    TriggerFactName.MENTIONS_CRITICAL_ILLNESS_DEFINITION_TERM: (
        (),
        (re.compile(r"重大疾病"),),
    ),
}
_BOOLEAN_FACT_NEGATIONS: Mapping[
    TriggerFactName,
    Tuple[re.Pattern[str], ...],
] = {
    TriggerFactName.HAS_WAITING_PERIOD: (
        re.compile(
            r"(?:不设置|不设|未设置|没有|无|免设)等待期"
            r"(?=$|[，,。；;\n])"
        ),
    ),
    TriggerFactName.HAS_HESITATION_PERIOD: (
        re.compile(
            r"(?:不设置|不设|未设置|没有|无|免设)犹豫期"
            r"(?=$|[，,。；;\n])"
        ),
    ),
    TriggerFactName.HAS_POLICY_LOAN: (
        re.compile(
            r"(?:(?:不提供|不支持|不具有|没有|无)"
            r"(?:保单|保险单)(?:贷款|借款)|"
            r"不得申请(?:保单|保险单)(?:贷款|借款))"
            r"(?=$|[，,。；;\n])"
        ),
    ),
    TriggerFactName.HAS_CASH_VALUE: (
        re.compile(
            r"(?:(?:本合同|本产品|该合同|该产品)[^。；;\n]{0,12}"
            r"(?:不具有|没有|无)现金价值|"
            r"(?:不具有|没有)现金价值)"
            r"(?=$|[，,。；;\n])"
        ),
    ),
    TriggerFactName.HAS_GRACE_PERIOD: (
        re.compile(
            r"(?:不设置|不设|未设置|没有|无)宽限期"
            r"(?=$|[，,。；;\n])"
        ),
    ),
    TriggerFactName.HAS_RENEWAL: (
        re.compile(
            r"(?:(?:本产品|本合同)[^。；;\n]{0,12}"
            r"(?:不提供|不接受|不支持|不含|不可|不能|无法)续保|"
            r"保险期间届满[^。；;\n]{0,20}(?:合同终止|不再续保))"
            r"(?=$|[，,。；;\n])"
        ),
    ),
    TriggerFactName.IS_RATE_ADJUSTABLE: (
        re.compile(
            r"(?:本产品|本合同)(?:的)?(?:保险)?费率"
            r"(?:不可调(?:整)?|固定)"
            r"(?=$|[，,。；;\n])"
        ),
    ),
    TriggerFactName.HAS_DEATH_BENEFIT: (
        re.compile(
            r"(?:本产品|本合同)"
            r"(?:不包含|不提供|不承担)(?:任何)?"
            r"(?:身故|死亡)"
            r"(?:保险金(?:责任)?|保险责任|责任|给付)"
            r"(?=$|[，,。；;\n])"
        ),
    ),
}
_TAG_FACT_FIELDS: Mapping[TriggerFactName, str] = {
    TriggerFactName.HAS_WAITING_PERIOD: "has_waiting_period",
    TriggerFactName.HAS_HESITATION_PERIOD: "has_hesitation_period",
    TriggerFactName.HAS_CASH_VALUE: "has_cash_value",
    TriggerFactName.IS_RATE_ADJUSTABLE: "is_rate_adjustable",
    TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG: (
        "mentions_out_of_hospital_drug"
    ),
    TriggerFactName.MENTIONS_CRITICAL_ILLNESS_DEFINITION_TERM: (
        "mentions_critical_illness_definition_term"
    ),
    TriggerFactName.HAS_RENEWAL: "renewal_type",
    TriggerFactName.HAS_POLICY_LOAN: "policy_rights",
    TriggerFactName.HAS_DEATH_BENEFIT: "coverage_components",
}
_NUMERIC_FACT_KINDS: Mapping[
    TriggerFactName,
    Tuple[FactKind, str],
] = {
    TriggerFactName.WAITING_PERIOD_DAYS: (FactKind.WAITING_PERIOD, "day"),
    TriggerFactName.HESITATION_PERIOD_DAYS: (FactKind.HESITATION_PERIOD, "day"),
    TriggerFactName.FIRST_RATE_ADJUSTMENT_INTERVAL_YEARS: (
        FactKind.FIRST_RATE_ADJUSTMENT_INTERVAL,
        "year",
    ),
    TriggerFactName.SUBSEQUENT_RATE_ADJUSTMENT_INTERVAL_YEARS: (
        FactKind.SUBSEQUENT_RATE_ADJUSTMENT_INTERVAL,
        "year",
    ),
}
_CLOSED_SCAN_FACTS = frozenset({
    TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
    TriggerFactName.MENTIONS_CRITICAL_ILLNESS_DEFINITION_TERM,
})
_CLOSED_SCAN_COVERAGE_KEYS: Mapping[TriggerFactName, str] = {
    TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG: (
        CoverageFactKeys.OUT_OF_HOSPITAL_DRUG_TEXT
    ),
    TriggerFactName.MENTIONS_CRITICAL_ILLNESS_DEFINITION_TERM: (
        CoverageFactKeys.CRITICAL_ILLNESS_TERM_TEXT
    ),
}


def _parse_chinese_integer(raw: str) -> Optional[int]:
    if raw.isdigit():
        return int(raw)
    digits = {
        "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
        "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000}
    total = 0
    section = 0
    current = 0
    for char in raw:
        if char in digits:
            current = digits[char]
        elif char in units:
            section += (current or 1) * units[char]
            current = 0
        else:
            return None
    total += section + current
    return total


def _normalize_unit(raw: str) -> str:
    if raw in ("天", "日"):
        return "day"
    if raw in ("月", "个月"):
        return "month"
    return "year"


def _append_duration_fact(
    facts: List[ExtractedFact],
    kind: FactKind,
    block: FactSourceBlock,
    match: re.Match[str],
    confidence: float = 1.0,
) -> None:
    value = _parse_chinese_integer(match.group(1))
    if value is None:
        return
    content = f"{block.title}\n{block.text}"
    facts.append(ExtractedFact(
        kind=kind,
        value=str(value),
        unit=_normalize_unit(match.group(2)),
        clause_id=block.clause_id,
        evidence=_context_evidence(content, match.start(), match.end()),
        confidence=confidence,
    ))


def _context_evidence(
    content: str,
    start: int,
    end: int,
    window: int = 36,
) -> str:
    return content[max(0, start - window):min(len(content), end + window)].strip()


def _durations_near_label(
    content: str,
    labels: Tuple[str, ...],
) -> Tuple[re.Match[str], ...]:
    context_labels = tuple(dict.fromkeys((*_DURATION_CONTEXT_LABELS, *labels)))
    matches: List[re.Match[str]] = []
    for match in _DURATION_PATTERN.finditer(content):
        sentence_start = max(
            (content.rfind(marker, 0, match.start()) for marker in _STRONG_BOUNDARIES),
            default=-1,
        ) + 1
        nearest: Optional[Tuple[int, str]] = None
        for context_label in context_labels:
            index = content.rfind(context_label, sentence_start, match.start())
            if index >= 0 and (nearest is None or index > nearest[0]):
                nearest = (index, context_label)
        if (
            nearest is not None
            and nearest[1] in labels
            and match.start() - nearest[0] <= 120
        ):
            matches.append(match)
            continue
        if nearest is not None:
            continue
        sentence_end_candidates = tuple(
            index
            for marker in _STRONG_BOUNDARIES
            if (index := content.find(marker, match.end())) >= 0
        )
        sentence_end = min(sentence_end_candidates, default=len(content))
        following = tuple(
            (index, context_label)
            for context_label in context_labels
            if (
                index := content.find(
                    context_label,
                    match.end(),
                    sentence_end,
                )
            ) >= 0
        )
        next_label = min(following, default=None)
        if (
            next_label is not None
            and next_label[1] in labels
            and next_label[0] - match.end() <= 30
        ):
            matches.append(match)
    return tuple(matches)


def _is_negated(content: str, match_start: int) -> bool:
    prefix = content[max(0, match_start - 8):match_start]
    return any(marker in prefix for marker in _NEGATION_PREFIXES)


def _extract_block_facts(block: FactSourceBlock) -> Tuple[ExtractedFact, ...]:
    content = f"{block.title}\n{block.text}"
    facts: List[ExtractedFact] = []

    for waiting in _durations_near_label(content, ("等待期",)):
        _append_duration_fact(facts, FactKind.WAITING_PERIOD, block, waiting)

    for hesitation in _durations_near_label(content, ("犹豫期",)):
        _append_duration_fact(facts, FactKind.HESITATION_PERIOD, block, hesitation)

    renewal_matches = (
        *(
            ("none", match)
            for match in re.finditer(
                r"不提供续保|不得续保|不可续保|不含续保",
                content,
            )
        ),
        *(
            ("available", match)
            for match in re.finditer(
                r"可以申请续保|可申请续保|接受续保|同意续保|办理续保",
                content,
            )
        ),
    )
    if not renewal_matches:
        mention = re.search(r"续保", content)
        renewal_matches = (("mentioned", mention),) if mention else ()
    for renewal_value, renewal_match in renewal_matches:
        facts.append(ExtractedFact(
            kind=FactKind.RENEWAL_ARRANGEMENT,
            value=renewal_value,
            unit="",
            clause_id=block.clause_id,
            evidence=_context_evidence(
                content,
                renewal_match.start(),
                renewal_match.end(),
            ),
            confidence=1.0,
        ))
    non_guaranteed = re.search(r"不保证续保|非保证续保|不承诺续保", content)
    if non_guaranteed:
        facts.append(ExtractedFact(
            kind=FactKind.NON_GUARANTEED_RENEWAL,
            value="true",
            unit="",
            clause_id=block.clause_id,
            evidence=non_guaranteed.group(0),
            confidence=1.0,
        ))

    for prohibited in re.finditer(r"自动续保|承诺续保|无条件续保", content):
        if _is_negated(content, prohibited.start()):
            continue
        facts.append(ExtractedFact(
            kind=FactKind.PROHIBITED_RENEWAL_LANGUAGE,
            value=prohibited.group(0),
            unit="",
            clause_id=block.clause_id,
            evidence=content[max(0, prohibited.start() - 16):prohibited.end() + 16],
            confidence=1.0,
        ))

    for first_adjustment in _durations_near_label(
        content,
        ("首次费率调整", "首次调整费率", "首次调整保险费率"),
    ):
        _append_duration_fact(
            facts, FactKind.FIRST_RATE_ADJUSTMENT_INTERVAL, block, first_adjustment,
        )
    for subsequent_adjustment in _durations_near_label(
        content,
        ("后续费率调整", "再次调整费率", "相邻两次费率调整", "每次费率调整"),
    ):
        _append_duration_fact(
            facts, FactKind.SUBSEQUENT_RATE_ADJUSTMENT_INTERVAL,
            block, subsequent_adjustment,
        )
    return tuple(facts)


def extract_audit_facts(
    blocks: Iterable[FactSourceBlock],
    product_tags: ProductTags,
) -> Tuple[ExtractedFact, ...]:
    facts = [fact for block in blocks for fact in _extract_block_facts(block)]
    if product_tags.is_rate_adjustable is not None:
        evidence = next(
            (
                item.evidence for item in product_tags.evidence
                if item.field_name == "is_rate_adjustable"
            ),
            "",
        )
        facts.append(ExtractedFact(
            kind=FactKind.RATE_ADJUSTABLE,
            value=str(product_tags.is_rate_adjustable).lower(),
            unit="",
            clause_id="product-name",
            evidence=evidence,
            confidence=1.0,
        ))
    unique = {
        (item.kind, item.value, item.unit, item.clause_id, item.evidence): item
        for item in facts
    }
    return tuple(unique.values())


def _fact_evidence(
    block: FactSourceBlock,
    match: re.Match[str],
) -> ProductFactEvidence:
    content = f"{block.title}\n{block.text}"
    return ProductFactEvidence(
        clause_id=block.clause_id,
        quote=_context_evidence(content, match.start(), match.end()),
    )


def _signal_evidence(
    blocks: Tuple[FactSourceBlock, ...],
    fact_name: TriggerFactName,
) -> Tuple[ProductFactEvidence, ...]:
    topics, patterns = _BOOLEAN_FACT_SIGNALS[fact_name]
    evidence: list[ProductFactEvidence] = []
    for block in blocks:
        content = f"{block.title}\n{block.text}"
        negations = tuple(
            match
            for pattern in _BOOLEAN_FACT_NEGATIONS.get(fact_name, ())
            for match in pattern.finditer(content)
        )
        positive_matches = tuple(
            match
            for pattern in patterns
            for match in pattern.finditer(content)
            if not any(
                negation.start() <= match.start()
                and match.end() <= negation.end()
                for negation in negations
            )
            and not (
                match.start() <= len(block.title)
                and negations
            )
        )
        if positive_matches:
            evidence.extend(
                _fact_evidence(block, match) for match in positive_matches
            )
        elif not negations and set(topics).intersection(block.topics):
            quote = block.text.strip() or block.title.strip()
            if quote:
                evidence.append(ProductFactEvidence(
                    clause_id=block.clause_id,
                    quote=quote[:160],
                ))
    return tuple(dict.fromkeys(evidence))


def _explicit_negation_evidence(
    blocks: Tuple[FactSourceBlock, ...],
    fact_name: TriggerFactName,
) -> Tuple[ProductFactEvidence, ...]:
    return tuple(dict.fromkeys(
        _fact_evidence(block, match)
        for block in blocks
        for pattern in _BOOLEAN_FACT_NEGATIONS.get(fact_name, ())
        for match in pattern.finditer(f"{block.title}\n{block.text}")
    ))


def _tag_evidence(
    product_tags: ProductTags,
    field_name: str,
    blocks: Tuple[FactSourceBlock, ...],
) -> Tuple[ProductFactEvidence, ...]:
    items = []
    for evidence in product_tags.evidence:
        if evidence.field_name != field_name or not evidence.evidence.strip():
            continue
        quote = evidence.evidence.strip()
        if evidence.source in {"user_input", "file_name", "product_name"} or (
            evidence.source.endswith("_default")
        ):
            items.append(ProductFactEvidence("product-name", quote))
            continue
        normalized_quote = _normalized_phrase_text(quote)
        matched_blocks = tuple(
            block
            for block in blocks
            if normalized_quote
            and normalized_quote in _normalized_phrase_text(
                f"{block.title}\n{block.text}"
            )
        )
        if matched_blocks:
            items.extend(
                ProductFactEvidence(block.clause_id, quote)
                for block in matched_blocks
            )
        else:
            items.append(ProductFactEvidence("product-document", quote))
    return tuple(dict.fromkeys(items))


def _closed_scan_terms(
    specs: Iterable[RegulationTriggerSpec],
) -> Mapping[TriggerFactName, Tuple[str, ...]]:
    terms: Dict[TriggerFactName, list[str]] = defaultdict(list)
    for spec in specs:
        if (
            spec.proof_strategy is not ProofStrategy.CLOSED_PHRASE_SCAN
            or spec.fact_name not in _CLOSED_SCAN_FACTS
        ):
            continue
        terms[spec.fact_name].extend(spec.search_all_terms)
        terms[spec.fact_name].extend(spec.search_any_terms)
    return {
        fact_name: tuple(dict.fromkeys(values))
        for fact_name, values in terms.items()
        if values
    }


def _normalized_phrase_text(value: str) -> str:
    return _normalized_phrase_with_indexes(value)[0]


def _normalized_phrase_with_indexes(value: str) -> Tuple[str, Tuple[int, ...]]:
    characters: list[str] = []
    source_indexes: list[int] = []
    for source_index, source_character in enumerate(value):
        for character in unicodedata.normalize("NFKC", source_character):
            if character.isspace() or unicodedata.category(character) == "Cf":
                continue
            characters.append(character)
            source_indexes.append(source_index)
    return "".join(characters), tuple(source_indexes)


def _normalized_phrase_evidence(
    blocks: Tuple[FactSourceBlock, ...],
    terms: Tuple[str, ...],
) -> Tuple[ProductFactEvidence, ...]:
    evidence: list[ProductFactEvidence] = []
    for block in blocks:
        content = f"{block.title}\n{block.text}"
        normalized_content, source_indexes = _normalized_phrase_with_indexes(content)
        for term in terms:
            normalized_term = _normalized_phrase_text(term)
            if not normalized_term:
                continue
            start = normalized_content.find(normalized_term)
            if start < 0:
                continue
            end = start + len(normalized_term)
            source_start = source_indexes[start]
            source_end = source_indexes[end - 1] + 1
            evidence.append(ProductFactEvidence(
                block.clause_id,
                _context_evidence(content, source_start, source_end),
            ))
    return tuple(dict.fromkeys(evidence))


def _tag_boolean(
    product_tags: ProductTags,
    fact_name: TriggerFactName,
) -> Optional[bool]:
    if fact_name is TriggerFactName.HAS_RENEWAL:
        if product_tags.renewal_type is RenewalType.UNKNOWN:
            return None
        return product_tags.renewal_type is not RenewalType.NONE
    if fact_name is TriggerFactName.HAS_POLICY_LOAN:
        return True if "loan" in product_tags.policy_rights else None
    if fact_name is TriggerFactName.HAS_DEATH_BENEFIT:
        return True if "death" in product_tags.coverage_components else None
    field_name = _TAG_FACT_FIELDS.get(fact_name)
    return getattr(product_tags, field_name) if field_name else None


def _boolean_product_fact(
    fact_name: TriggerFactName,
    blocks: Tuple[FactSourceBlock, ...],
    product_tags: ProductTags,
    closed_terms: Tuple[str, ...],
    complete_document: bool,
) -> ProductFact:
    signal_evidence = _signal_evidence(blocks, fact_name)
    negation_evidence = _explicit_negation_evidence(blocks, fact_name)
    tag_value = _tag_boolean(product_tags, fact_name)
    tag_field = _TAG_FACT_FIELDS.get(fact_name)
    tag_evidence = (
        _tag_evidence(product_tags, tag_field, blocks)
        if tag_field is not None
        else ()
    )
    closed_evidence = (
        _normalized_phrase_evidence(blocks, closed_terms)
        if complete_document and closed_terms
        else ()
    )
    signal_evidence = tuple(dict.fromkeys((*signal_evidence, *closed_evidence)))
    if negation_evidence and (signal_evidence or tag_value is True):
        return ProductFact(
            name=fact_name,
            truth=FactTruth.UNKNOWN,
            method="conflict",
            confidence=0.0,
            evidence=tuple(dict.fromkeys((
                *signal_evidence,
                *negation_evidence,
                *tag_evidence,
            ))),
            reason="产品条款同时存在正向与明确否定证据，不能用于排除法规",
        )
    if signal_evidence and tag_value is False:
        return ProductFact(
            name=fact_name,
            truth=FactTruth.UNKNOWN,
            method="conflict",
            confidence=0.0,
            evidence=tuple(dict.fromkeys((*signal_evidence, *tag_evidence))),
            reason="产品标签与条款明示内容冲突，不能用于排除法规",
        )
    if signal_evidence or tag_value is True:
        return ProductFact(
            name=fact_name,
            truth=FactTruth.TRUE,
            value=True,
            method="deterministic_presence",
            evidence=tuple(dict.fromkeys((*signal_evidence, *tag_evidence))),
            reason="产品名称标签、受控主题或条款原文明示该事实",
            proof_strategy=ProofStrategy.EXPLICIT_PRESENCE,
        )
    if negation_evidence:
        return ProductFact(
            name=fact_name,
            truth=FactTruth.FALSE,
            value=False,
            method="explicit_negation",
            evidence=negation_evidence,
            reason=(
                "产品条款明确否定该事实，但开放世界功能仍可能"
                "以其他表述实际存在；该证据不用于排除法规"
            ),
            safe_for_exclusion=False,
            proof_strategy=ProofStrategy.EXPLICIT_NEGATION,
        )
    if complete_document and closed_terms:
        return ProductFact(
            name=fact_name,
            truth=FactTruth.FALSE,
            value=False,
            method="closed_phrase_scan",
            evidence=(),
            reason=(
                "完整产品条款封闭词组扫描零命中: "
                + "、".join(closed_terms)
            ),
            safe_for_exclusion=True,
            proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
            proof_terms=closed_terms,
            complete_document_proof=True,
        )
    if tag_value is False:
        return ProductFact(
            name=fact_name,
            truth=FactTruth.FALSE,
            value=False,
            method="controlled_product_tag",
            evidence=tag_evidence,
            reason="产品标签为 false，但缺少可用于排除法规的负向证明",
            safe_for_exclusion=False,
            proof_strategy=None,
        )
    return ProductFact(
        name=fact_name,
        truth=FactTruth.UNKNOWN,
        method="deterministic_scan",
        confidence=0.0,
        reason="现有确定性证据不能证明该事实为 true 或 false",
    )


def _numeric_product_fact(
    fact_name: TriggerFactName,
    extracted_facts: Tuple[ExtractedFact, ...],
) -> ProductFact:
    kind, canonical_unit = _NUMERIC_FACT_KINDS[fact_name]
    matching = tuple(
        fact for fact in extracted_facts
        if fact.kind is kind and fact.unit == canonical_unit
    )
    distinct_values = tuple(dict.fromkeys(fact.value for fact in matching))
    evidence = tuple(dict.fromkeys(
        ProductFactEvidence(fact.clause_id, fact.evidence)
        for fact in matching
        if fact.evidence
    ))
    if len(distinct_values) == 1:
        return ProductFact(
            name=fact_name,
            truth=FactTruth.TRUE,
            value=distinct_values[0],
            unit=canonical_unit,
            method="numeric_fact",
            confidence=min((fact.confidence for fact in matching), default=1.0),
            evidence=evidence,
            reason=(
                "从产品条款提取到唯一规范化数值；该数值可证明触发条件满足，"
                "但数值不满足不能在触发层直接排除法规"
            ),
            safe_for_exclusion=False,
            proof_strategy=ProofStrategy.NUMERIC_FACT,
        )
    if len(distinct_values) > 1:
        return ProductFact(
            name=fact_name,
            truth=FactTruth.UNKNOWN,
            unit=canonical_unit,
            method="numeric_fact_conflict",
            confidence=0.0,
            evidence=evidence,
            reason="同一事实存在多个数值，不能在触发层合并为单一值",
        )
    return ProductFact(
        name=fact_name,
        truth=FactTruth.UNKNOWN,
        unit=canonical_unit,
        method="numeric_fact",
        confidence=0.0,
        reason="未提取到具有规范单位的数值",
    )


def build_product_fact_ledger(
    blocks: Iterable[FactSourceBlock],
    product_tags: ProductTags,
    required_fact_names: Iterable[TriggerFactName],
    *,
    complete_document: bool = False,
    coverage_attested_facts: Tuple[str, ...] = (),
    trigger_specs: Iterable[RegulationTriggerSpec] = (),
    extracted_facts: Optional[Tuple[ExtractedFact, ...]] = None,
) -> Tuple[ProductFact, ...]:
    """一次构建候选法规共享的产品事实；未知事实绝不因零命中自动变为 false。"""
    materialized_blocks = tuple(blocks)
    names = tuple(dict.fromkeys(required_fact_names))
    specs = tuple(trigger_specs)
    closed_terms = _closed_scan_terms(specs)
    shared_audit_facts = (
        extracted_facts
        if extracted_facts is not None
        else extract_audit_facts(materialized_blocks, product_tags)
    )
    ledger: list[ProductFact] = []
    covered_facts = frozenset(coverage_attested_facts)
    for fact_name in names:
        if fact_name in _NUMERIC_FACT_KINDS:
            ledger.append(_numeric_product_fact(fact_name, shared_audit_facts))
            continue
        ledger.append(_boolean_product_fact(
            fact_name,
            materialized_blocks,
            product_tags,
            closed_terms.get(fact_name, ()),
            complete_document or (
                _CLOSED_SCAN_COVERAGE_KEYS.get(fact_name) in covered_facts
            ),
        ))
    return tuple(ledger)
