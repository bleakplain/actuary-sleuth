"""从产品条款块提取法规审核需要的可验证事实。"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Protocol, Tuple

from lib.common.compliance_audit import ExtractedFact, FactKind
from lib.common.product_tags import ProductTags


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
