"""从产品名称和条款正文生成可解释的产品标签。"""
from __future__ import annotations

import re
from typing import Dict, List, Match, Optional, Tuple, Union

from ...common.product_tags import (
    ContractRole, CustomerScope, HealthTermClass, ProductDesignType, ProductLine,
    ProductSubtype, ProductTags, ProductTermClass, ProductTermForm, RenewalType,
    TagEvidence, TermOption,
)

_NAME_TYPES = (
    ("意外伤害医疗保险", ProductLine.HEALTH, ProductSubtype.MEDICAL_ACCIDENT),
    ("意外医疗保险", ProductLine.HEALTH, ProductSubtype.MEDICAL_ACCIDENT),
    ("医疗意外保险", ProductLine.HEALTH, ProductSubtype.MEDICAL_ACCIDENT),
    ("失能收入损失保险", ProductLine.HEALTH, ProductSubtype.DISABILITY_INCOME),
    ("重大疾病保险", ProductLine.HEALTH, ProductSubtype.CRITICAL_ILLNESS),
    ("重疾保险", ProductLine.HEALTH, ProductSubtype.CRITICAL_ILLNESS),
    ("护理保险", ProductLine.HEALTH, ProductSubtype.NURSING),
    ("医疗保险", ProductLine.HEALTH, ProductSubtype.MEDICAL),
    ("疾病保险", ProductLine.HEALTH, ProductSubtype.DISEASE),
    ("终身寿险", ProductLine.LIFE, ProductSubtype.WHOLE_LIFE),
    ("定期寿险", ProductLine.LIFE, ProductSubtype.TERM_LIFE),
    ("两全保险", ProductLine.LIFE, ProductSubtype.ENDOWMENT),
    ("年金保险", ProductLine.LIFE, ProductSubtype.ANNUITY),
    ("意外伤害保险", ProductLine.ACCIDENT, ProductSubtype.ACCIDENT),
    ("意外保险", ProductLine.ACCIDENT, ProductSubtype.ACCIDENT),
)

_COVERAGE_KEYWORDS = {
    "critical_illness": ("重大疾病保险金", "重疾保险金"),
    "disease": ("疾病保险金",),
    "medical": ("医疗保险金", "医疗费用保险金"),
    "accidental_medical": ("意外医疗保险金", "意外伤害医疗保险金"),
    "disability_income": ("失能收入损失保险金",),
    "nursing": ("护理保险金", "长期护理保险金"),
    "death": ("身故保险金",),
    "survival": ("生存保险金", "满期保险金"),
}

_SUBTYPE_COMPONENT = {
    ProductSubtype.CRITICAL_ILLNESS: "critical_illness",
    ProductSubtype.DISEASE: "disease",
    ProductSubtype.MEDICAL: "medical",
    ProductSubtype.DISABILITY_INCOME: "disability_income",
    ProductSubtype.NURSING: "nursing",
    ProductSubtype.MEDICAL_ACCIDENT: "accidental_medical",
}


def _evidence_excerpt(
    text: str,
    match: Optional[Union[str, Match[str]]] = None,
) -> str:
    normalized = text.strip()
    if match is None:
        return normalized[:120]
    resolved = (
        re.search(re.escape(match), text)
        if isinstance(match, str)
        else match
    )
    if resolved is None:
        return normalized[:120]
    start = max(0, resolved.start() - 50)
    end = min(len(text), resolved.end() + 70)
    excerpt = text[start:end].strip()
    return excerpt[:120]


def _evidence(
    field: str,
    value: str,
    source: str,
    text: str,
    match: Optional[Union[str, Match[str]]] = None,
) -> TagEvidence:
    return TagEvidence(
        field,
        value,
        source,
        _evidence_excerpt(text, match),
        1.0,
    )


def _classify_name(name: str) -> Tuple[ProductLine, ProductSubtype]:
    matches = []
    for order, (keyword, line, subtype) in enumerate(_NAME_TYPES):
        for match in re.finditer(re.escape(keyword), name):
            matches.append((
                match.end(),
                len(keyword),
                -order,
                line,
                subtype,
            ))
    if matches:
        _, _, _, line, subtype = max(matches, key=lambda item: item[:3])
        return line, subtype
    if "人寿保险" in name:
        return ProductLine.LIFE, ProductSubtype.OTHER_LIFE
    if "健康保险" in name:
        return ProductLine.HEALTH, ProductSubtype.OTHER_HEALTH
    return ProductLine.UNKNOWN, ProductSubtype.UNKNOWN


def _classify_contract_role(name: str) -> ContractRole:
    """仅把产品名称中位于“保险”之前的“附加”视为附加险标识。"""
    insurance_index = name.find("保险")
    if insurance_index < 0:
        return ContractRole.UNKNOWN
    rider_index = name.find("附加")
    if 0 <= rider_index < insurance_index:
        return ContractRole.RIDER
    return ContractRole.MAIN


def _parse_duration_number(value: str) -> Optional[float]:
    """解析条款中常见的阿拉伯数字或中文整数期限。"""
    if value.isdigit():
        return float(value)
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100}
    total = 0
    current = 0
    for char in value:
        if char in digits:
            current = digits[char]
        elif char in units:
            total += (current or 1) * units[char]
            current = 0
        else:
            return None
    return float(total + current)


_DURATION_PATTERN = re.compile(
    r'([零一二两三四五六七八九十百\d]+)\s*(年|个月|月|天|日)'
)
_OTHER_PERIOD_LABEL = re.compile(
    r'等待期|犹豫期|宽限期|保证续保期间|缴费期间|交费期间'
)
_INSURANCE_PERIOD_DEFINITION = re.compile(
    r'保险期间\s*(?:'
    r'为|是|分为|分别为|可(?:供)?选择|可选|不超过|不得超过|'
    r'至|到|自|由|'
    r'[:：]\s*(?=[零一二两三四五六七八九十百\d]|终身)'
    r')'
)
_GUARANTEED_RENEWAL_DEFINITIONS = (
    re.compile(
        r'每\s*'
        r'(?P<value>[零一二两三四五六七八九十百\d]+)\s*'
        r'(?P<unit>年|个月|月|天|日)\s*'
        r'为\s*(?:一|1)?\s*个保证续保期间'
    ),
    re.compile(
        r'保证续保期间\s*'
        r'(?:为|是|[:：])\s*'
        r'(?P<value>[零一二两三四五六七八九十百\d]+)\s*'
        r'(?P<unit>年|个月|月|天|日)'
    ),
)


def _period_segments(
    text: str,
    label: str,
    *,
    require_definition: bool = False,
) -> Tuple[str, ...]:
    segments: List[str] = []
    for label_match in re.finditer(label, text):
        if require_definition:
            definition = _INSURANCE_PERIOD_DEFINITION.match(
                text,
                label_match.start(),
            )
            if definition is None:
                continue
        end = len(text)
        delimiter = re.search(r'[。；;\n]', text[label_match.end():])
        if delimiter:
            end = label_match.end() + delimiter.start()
        other_label = _OTHER_PERIOD_LABEL.search(
            text,
            label_match.end(),
            end,
        )
        if other_label:
            end = other_label.start()
        segments.append(text[label_match.end():end])
    return tuple(segments)


def _normalized_duration_unit(unit: str) -> str:
    if unit in ("个月", "月"):
        return "month"
    if unit in ("天", "日"):
        return "day"
    return "year"


def _is_long_duration(number: float, unit: str) -> bool:
    return (
        (unit == "year" and number > 1)
        or (unit == "month" and number > 12)
        or (unit == "day" and number > 365)
    )


def _guaranteed_renewal_options(text: str) -> Tuple[TermOption, ...]:
    """只从保证续保期限定义句提取期限，排除届满申请、宽限等窗口。"""
    options: List[TermOption] = []
    for pattern in _GUARANTEED_RENEWAL_DEFINITIONS:
        for match in pattern.finditer(text):
            number = _parse_duration_number(match.group("value"))
            if number is None:
                continue
            options.append(TermOption(
                "guaranteed_renewal_period",
                number,
                _normalized_duration_unit(match.group("unit")),
            ))
    return tuple(dict.fromkeys(options))


def _term_facts(
    text: str,
    *,
    product_name: bool = False,
) -> Tuple[Tuple[ProductTermForm, ...], Tuple[TermOption, ...]]:
    forms: List[ProductTermForm] = []
    options: List[TermOption] = []
    if product_name and "终身" in text:
        forms.append(ProductTermForm.WHOLE_LIFE)
        options.append(TermOption("whole_life"))
    definition_segments = _period_segments(
        text,
        r'保险期间',
        require_definition=True,
    )
    for segment in definition_segments:
        if "终身" in segment:
            forms.append(ProductTermForm.WHOLE_LIFE)
            options.append(TermOption("whole_life"))
        age_segment_pattern = (
            r'(?:至|到)被保险人(?:年满)?\s*'
            r'([^。；，,\n]{0,40})'
        )
        for age_segment in re.findall(age_segment_pattern, segment):
            if "岁" not in age_segment:
                continue
            for age in re.findall(
                r'[零一二两三四五六七八九十百\d]{1,4}',
                age_segment,
            ):
                age_number = _parse_duration_number(age)
                if age_number is None:
                    continue
                forms.append(ProductTermForm.TO_AGE)
                options.append(TermOption("to_age", age_number, "year"))
        for value, unit in _DURATION_PATTERN.findall(segment):
            number = _parse_duration_number(value)
            if number is None:
                continue
            normalized_unit = _normalized_duration_unit(unit)
            forms.append(ProductTermForm.FIXED_DURATION)
            options.append(TermOption(
                "fixed_duration",
                number,
                normalized_unit,
            ))
            forms.append(
                ProductTermForm.OVER_ONE_YEAR
                if _is_long_duration(number, normalized_unit)
                else ProductTermForm.ONE_YEAR_OR_LESS
            )
    guarantee_options = _guaranteed_renewal_options(text)
    if guarantee_options:
        forms.append(ProductTermForm.GUARANTEED_RENEWAL_PERIOD)
        options.extend(guarantee_options)
    unique_options = tuple(dict.fromkeys(options))
    unique_forms = list(dict.fromkeys(forms))
    insurance_period_options = tuple(
        option for option in unique_options
        if option.kind != "guaranteed_renewal_period"
    )
    if len(insurance_period_options) > 1:
        unique_forms.append(ProductTermForm.MULTIPLE_OPTIONS)
    return tuple(dict.fromkeys(unique_forms)), unique_options


def build_product_tags(
    product_name: Optional[str],
    document_content: str = "",
    *,
    product_name_source: str = "product_name",
    complete_document: bool = False,
) -> ProductTags:
    """构建产品标签；无法从约定来源确认的值保持 unknown/None。"""
    name = product_name or ""
    line, subtype = _classify_name(name)
    evidence: List[TagEvidence] = []
    warnings: List[str] = []
    if product_name and subtype is not ProductSubtype.UNKNOWN:
        evidence.extend((
            _evidence("line", line.value, product_name_source, name),
            _evidence("primary_subtype", subtype.value, product_name_source, name),
        ))

    design = ProductDesignType.UNKNOWN
    for keyword, value in (("分红型", ProductDesignType.PARTICIPATING),
                           ("万能型", ProductDesignType.UNIVERSAL),
                           ("投资连结型", ProductDesignType.UNIT_LINKED),
                           ("普通型", ProductDesignType.ORDINARY)):
        if keyword in name:
            design = value
            evidence.append(_evidence(
                "design_type",
                value.value,
                product_name_source,
                name,
                keyword,
            ))
            break
    if design is ProductDesignType.UNKNOWN and line is not ProductLine.UNKNOWN:
        # 分红、万能、投连等特殊设计必须在正式名称中明示；没有特殊设计
        # 标识的已识别保险产品按普通型处理，与法规侧 ordinary 标签一致。
        design = ProductDesignType.ORDINARY
        evidence.append(TagEvidence(
            "design_type",
            design.value,
            f"{product_name_source}_default",
            name,
            0.95,
        ))

    customer = CustomerScope.UNKNOWN
    role = ContractRole.UNKNOWN
    if product_name:
        customer = CustomerScope.GROUP if "团体" in name else CustomerScope.INDIVIDUAL
        role = _classify_contract_role(name)
        evidence.extend((
            _evidence("customer_scope", customer.value, product_name_source, name),
            _evidence("contract_role", role.value, product_name_source, name),
        ))

    combined = f"{name}\n{document_content}"
    forms, options = _term_facts(document_content)
    term_from_clause = bool(forms)
    if not forms:
        name_forms, name_options = _term_facts(name, product_name=True)
        forms, options = name_forms, name_options
    renewal = RenewalType.UNKNOWN
    renewal_match = re.search(
        r"不保证续保|并非保证续保|不属于保证续保",
        document_content,
    )
    if renewal_match:
        renewal = RenewalType.NON_GUARANTEED
    else:
        renewal_match = re.search(
            r"(?:不接受|不提供|不得|不能|无法)续保|"
            r"保险期间届满[^。；\n]{0,20}(?:合同终止|不再续保)",
            document_content,
        )
    if renewal_match and renewal is RenewalType.UNKNOWN:
        renewal = RenewalType.NONE
    elif renewal_match is None:
        renewal_match = re.search(
            r"保证续保期间|本合同(?:为|属于)?保证续保|"
            r"为保证续保产品|提供保证续保",
            document_content,
        )
    if renewal_match and renewal is RenewalType.UNKNOWN:
        renewal = RenewalType.GUARANTEED

    term_class = ProductTermClass.UNKNOWN
    if ProductTermForm.WHOLE_LIFE in forms or ProductTermForm.TO_AGE in forms or ProductTermForm.OVER_ONE_YEAR in forms:
        term_class = ProductTermClass.LONG_TERM
    elif ProductTermForm.ONE_YEAR_OR_LESS in forms:
        term_class = ProductTermClass.SHORT_TERM
    elif "长期" in name or "终身" in name:
        term_class = ProductTermClass.LONG_TERM
    elif "短期" in name:
        term_class = ProductTermClass.SHORT_TERM

    physical_term_class = term_class
    health_term = HealthTermClass.UNKNOWN
    if line is ProductLine.HEALTH:
        if term_class is ProductTermClass.LONG_TERM:
            health_term = HealthTermClass.LONG_HEALTH
        elif ProductTermForm.ONE_YEAR_OR_LESS in forms:
            if renewal is RenewalType.GUARANTEED:
                health_term = HealthTermClass.LONG_HEALTH
            elif renewal in (RenewalType.NON_GUARANTEED, RenewalType.NONE) or complete_document:
                health_term = HealthTermClass.SHORT_HEALTH
        elif term_class is ProductTermClass.SHORT_TERM:
            health_term = HealthTermClass.SHORT_HEALTH
    # 对健康险，长期/短期本身就是监管分类：一年期保证续保产品也属于长期。
    # 物理保险期间仍完整保留在 term_forms/term_options，不能让两套单选标签冲突。
    if health_term is HealthTermClass.LONG_HEALTH:
        term_class = ProductTermClass.LONG_TERM
    elif health_term is HealthTermClass.SHORT_HEALTH:
        term_class = ProductTermClass.SHORT_TERM

    internet = "互联网" in name if product_name else None
    adjustable = "费率可调" in name if product_name else None
    tax_match = re.search(
        r'税收优惠|个人所得税[^。；\n]*优惠|税优健康',
        document_content,
    )
    tax = True if tax_match else None
    customized = None
    if product_name:
        customized = "定制" in name and bool(re.search(r'适用地区|参保地|基本医疗保险统筹地区', document_content))

    component_matches: Dict[str, Optional[Match[str]]] = {}
    for key, words in _COVERAGE_KEYWORDS.items():
        component_match = None
        for word in words:
            component_match = re.search(re.escape(word), document_content)
            if component_match:
                break
        component_matches[key] = component_match
    components = tuple(
        key for key, match in component_matches.items() if match is not None
    )
    if term_class is not ProductTermClass.UNKNOWN:
        if (
            line is ProductLine.HEALTH
            and health_term is not HealthTermClass.UNKNOWN
            and term_class is not physical_term_class
        ):
            evidence.append(_evidence(
                "term_class",
                term_class.value,
                "health_regulatory_classification",
                (
                    f"health_term_class={health_term.value}; "
                    f"renewal_type={renewal.value}; "
                    f"term_forms={','.join(form.value for form in forms)}"
                ),
            ))
        else:
            term_source = (
                "product_clause" if term_from_clause else product_name_source
            )
            term_text = document_content if term_from_clause else name
            term_match = re.search(
                r'保险期间|终身|(?:至|到)被保险人',
                term_text,
            )
            evidence.append(_evidence(
                "term_class",
                term_class.value,
                term_source,
                term_text,
                term_match,
            ))
    if health_term is not HealthTermClass.UNKNOWN:
        evidence.append(_evidence(
            "health_term_class", health_term.value, "derived",
            f"term_class={term_class.value}; renewal_type={renewal.value}",
        ))
    if renewal is not RenewalType.UNKNOWN:
        evidence.append(_evidence(
            "renewal_type",
            renewal.value,
            "product_clause",
            document_content,
            renewal_match,
        ))
    for field, tag_value, source, source_text, evidence_match in (
        (
            "is_internet_exclusive",
            internet,
            product_name_source,
            name,
            "互联网",
        ),
        (
            "is_rate_adjustable",
            adjustable,
            product_name_source,
            name,
            "费率可调",
        ),
        (
            "is_tax_advantaged_health",
            tax,
            "product_clause",
            document_content,
            tax_match,
        ),
        (
            "is_city_customized_medical",
            customized,
            f"{product_name_source}_and_clause",
            combined,
            re.search(
                r'适用地区|参保地|基本医疗保险统筹地区',
                combined,
            ),
        ),
    ):
        if tag_value is not None:
            evidence.append(_evidence(
                field,
                str(tag_value).lower(),
                source,
                source_text,
                evidence_match,
            ))
    for component in components:
        evidence.append(_evidence(
            "coverage_components",
            component,
            "product_clause",
            document_content,
            component_matches[component],
        ))
    if adjustable and not (line is ProductLine.HEALTH and subtype is ProductSubtype.MEDICAL):
        warnings.append("名称含“费率可调”，但产品名称识别结果不是健康险医疗保险")
    if "定制" in name and customized is False:
        warnings.append("名称含“定制”，但条款未识别到明确适用地区")
    if line is ProductLine.HEALTH and health_term is HealthTermClass.UNKNOWN:
        warnings.append("健康险未能确定长期/短期属性")
    comparison_term = (
        ProductTermClass.LONG_TERM
        if health_term is HealthTermClass.LONG_HEALTH
        else ProductTermClass.SHORT_TERM
        if health_term is HealthTermClass.SHORT_HEALTH
        else term_class
    )
    if "长期" in name:
        evidence.append(_evidence(
            "term_class_name_claim", ProductTermClass.LONG_TERM.value,
            product_name_source, name,
        ))
    elif "短期" in name:
        evidence.append(_evidence(
            "term_class_name_claim", ProductTermClass.SHORT_TERM.value,
            product_name_source, name,
        ))
    if "长期" in name and comparison_term is ProductTermClass.SHORT_TERM:
        warnings.append("产品名称标示长期，但条款期限事实计算结果为短期，请人工复核")
    if "短期" in name and comparison_term is ProductTermClass.LONG_TERM:
        warnings.append("产品名称标示短期，但条款期限事实计算结果为长期，请人工复核")
    expected_component = _SUBTYPE_COMPONENT.get(subtype)
    health_components = set(components).intersection(_SUBTYPE_COMPONENT.values())
    if expected_component and health_components and expected_component not in health_components:
        warnings.append("产品名称确定的主要险种与条款中识别到的健康责任不一致")

    return ProductTags(
        line=line, primary_subtype=subtype, design_type=design,
        term_class=term_class, term_forms=forms, term_options=options,
        health_term_class=health_term, customer_scope=customer, contract_role=role,
        renewal_type=renewal, is_internet_exclusive=internet,
        is_rate_adjustable=adjustable, is_tax_advantaged_health=tax,
        is_city_customized_medical=customized, coverage_components=components,
        evidence=tuple(evidence), warnings=tuple(warnings),
    )
