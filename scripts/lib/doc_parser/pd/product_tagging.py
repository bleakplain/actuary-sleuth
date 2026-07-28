"""从产品名称和条款正文生成可解释的产品标签。"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ...common.product_tags import (
    ContractRole, CustomerScope, HealthTermClass, ProductDesignType, ProductLine,
    ProductSubtype, ProductTags, ProductTermClass, ProductTermForm, RenewalType,
    TagEvidence, TermOption,
)

_NAME_TYPES = (
    ("医疗意外", ProductLine.HEALTH, ProductSubtype.MEDICAL_ACCIDENT),
    ("失能收入损失", ProductLine.HEALTH, ProductSubtype.DISABILITY_INCOME),
    ("重大疾病", ProductLine.HEALTH, ProductSubtype.CRITICAL_ILLNESS),
    ("重疾", ProductLine.HEALTH, ProductSubtype.CRITICAL_ILLNESS),
    ("护理", ProductLine.HEALTH, ProductSubtype.NURSING),
    ("医疗", ProductLine.HEALTH, ProductSubtype.MEDICAL),
    ("疾病", ProductLine.HEALTH, ProductSubtype.DISEASE),
    ("两全", ProductLine.LIFE, ProductSubtype.ENDOWMENT),
    ("年金", ProductLine.LIFE, ProductSubtype.ANNUITY),
    ("终身寿险", ProductLine.LIFE, ProductSubtype.WHOLE_LIFE),
    ("定期寿险", ProductLine.LIFE, ProductSubtype.TERM_LIFE),
    ("意外伤害", ProductLine.ACCIDENT, ProductSubtype.ACCIDENT),
    ("意外", ProductLine.ACCIDENT, ProductSubtype.ACCIDENT),
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


def _evidence(field: str, value: str, source: str, text: str) -> TagEvidence:
    return TagEvidence(field, value, source, text[:120], 1.0)


def _classify_name(name: str) -> Tuple[ProductLine, ProductSubtype]:
    for keyword, line, subtype in _NAME_TYPES:
        if keyword in name:
            return line, subtype
    if "寿险" in name or "人寿保险" in name:
        return ProductLine.LIFE, ProductSubtype.OTHER_LIFE
    if "健康" in name:
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


def _term_facts(text: str) -> Tuple[Tuple[ProductTermForm, ...], Tuple[TermOption, ...]]:
    forms: List[ProductTermForm] = []
    options: List[TermOption] = []
    if "终身" in text:
        forms.append(ProductTermForm.WHOLE_LIFE)
        options.append(TermOption("whole_life"))
    for age in re.findall(r'(?:至|到)被保险人(?:年满)?\s*(\d{1,3})\s*周?岁', text):
        forms.append(ProductTermForm.TO_AGE)
        options.append(TermOption("to_age", float(age), "year"))
    duration_pattern = r'([零一二两三四五六七八九十百\d]+)\s*(年|个月|月|日)'
    for value, unit in re.findall(rf'保险期间[^。；\n]{{0,30}}?{duration_pattern}', text):
        number = _parse_duration_number(value)
        if number is None:
            continue
        normalized_unit = "month" if unit in ("个月", "月") else "year" if unit == "年" else "day"
        forms.append(ProductTermForm.FIXED_DURATION)
        options.append(TermOption("fixed_duration", number, normalized_unit))
        if normalized_unit == "year" and number > 1:
            forms.append(ProductTermForm.OVER_ONE_YEAR)
        else:
            forms.append(ProductTermForm.ONE_YEAR_OR_LESS)
    guarantee = re.search(rf'保证续保期间[^。；\n]{{0,20}}?{duration_pattern}', text)
    if guarantee:
        guarantee_number = _parse_duration_number(guarantee.group(1))
        if guarantee_number is not None and guarantee.group(2) == "年":
            forms.append(ProductTermForm.GUARANTEED_RENEWAL_PERIOD)
            options.append(TermOption("guaranteed_renewal_period", guarantee_number, "year"))
    unique_forms = tuple(dict.fromkeys(forms))
    if len({(item.kind, item.value, item.unit) for item in options}) > 1:
        unique_forms += (ProductTermForm.MULTIPLE_OPTIONS,)
    return tuple(dict.fromkeys(unique_forms)), tuple(dict.fromkeys(options))


def build_product_tags(
    product_name: Optional[str], document_content: str = "",
) -> ProductTags:
    """构建产品标签；无法从约定来源确认的值保持 unknown/None。"""
    name = product_name or ""
    line, subtype = _classify_name(name)
    evidence: List[TagEvidence] = []
    warnings: List[str] = []
    if product_name and subtype is not ProductSubtype.UNKNOWN:
        evidence.extend((_evidence("line", line.value, "product_name", name),
                         _evidence("primary_subtype", subtype.value, "product_name", name)))

    design = ProductDesignType.UNKNOWN
    for keyword, value in (("分红型", ProductDesignType.PARTICIPATING),
                           ("万能型", ProductDesignType.UNIVERSAL),
                           ("投资连结型", ProductDesignType.UNIT_LINKED),
                           ("普通型", ProductDesignType.ORDINARY)):
        if keyword in name:
            design = value
            evidence.append(_evidence("design_type", value.value, "product_name", keyword))
            break
    if line in (ProductLine.HEALTH, ProductLine.ACCIDENT):
        design = ProductDesignType.NOT_APPLICABLE

    customer = CustomerScope.UNKNOWN
    role = ContractRole.UNKNOWN
    if product_name:
        customer = CustomerScope.GROUP if "团体" in name else CustomerScope.INDIVIDUAL
        role = _classify_contract_role(name)
        evidence.extend((_evidence("customer_scope", customer.value, "product_name", name),
                         _evidence("contract_role", role.value, "product_name", name)))

    combined = f"{name}\n{document_content}"
    forms, options = _term_facts(combined)
    renewal = RenewalType.UNKNOWN
    if re.search(r"不保证续保|并非保证续保|不属于保证续保", document_content):
        renewal = RenewalType.NON_GUARANTEED
    elif re.search(r"(?:不接受|不提供|不得|不能|无法)续保|保险期间届满[^。；\n]{0,20}(?:合同终止|不再续保)", document_content):
        renewal = RenewalType.NONE
    elif re.search(r"保证续保期间|本合同(?:为|属于)?保证续保|为保证续保产品|提供保证续保", document_content):
        renewal = RenewalType.GUARANTEED

    term_class = ProductTermClass.UNKNOWN
    if ProductTermForm.WHOLE_LIFE in forms or ProductTermForm.TO_AGE in forms or ProductTermForm.OVER_ONE_YEAR in forms:
        term_class = ProductTermClass.LONG_TERM
    elif ProductTermForm.ONE_YEAR_OR_LESS in forms:
        term_class = ProductTermClass.LONG_TERM if renewal is RenewalType.GUARANTEED else ProductTermClass.SHORT_TERM
    elif "长期" in name:
        term_class = ProductTermClass.LONG_TERM
    elif "短期" in name:
        term_class = ProductTermClass.SHORT_TERM

    health_term = HealthTermClass.UNKNOWN
    if line is ProductLine.HEALTH and term_class is not ProductTermClass.UNKNOWN:
        health_term = HealthTermClass.LONG_HEALTH if term_class is ProductTermClass.LONG_TERM else HealthTermClass.SHORT_HEALTH

    internet = "互联网" in name if product_name else None
    adjustable = "费率可调" in name if product_name else None
    tax = True if re.search(r'税收优惠|个人所得税.*优惠|税优健康', document_content) else None
    customized = None
    if product_name:
        customized = "定制" in name and bool(re.search(r'适用地区|参保地|基本医疗保险统筹地区', document_content))

    components = tuple(key for key, words in _COVERAGE_KEYWORDS.items() if any(word in document_content for word in words))
    if term_class is not ProductTermClass.UNKNOWN:
        evidence.append(_evidence("term_class", term_class.value, "product_clause", combined))
    if health_term is not HealthTermClass.UNKNOWN:
        evidence.append(_evidence("health_term_class", health_term.value, "derived", term_class.value))
    if renewal is not RenewalType.UNKNOWN:
        evidence.append(_evidence("renewal_type", renewal.value, "product_clause", document_content))
    for field, tag_value, source in (
        ("is_internet_exclusive", internet, "product_name"),
        ("is_rate_adjustable", adjustable, "product_name"),
        ("is_tax_advantaged_health", tax, "product_clause"),
        ("is_city_customized_medical", customized, "product_name_and_clause"),
    ):
        if tag_value is not None:
            evidence.append(_evidence(field, str(tag_value).lower(), source, combined))
    for component in components:
        evidence.append(_evidence("coverage_components", component, "product_clause", document_content))
    if adjustable and not (line is ProductLine.HEALTH and subtype is ProductSubtype.MEDICAL):
        warnings.append("名称含“费率可调”，但产品名称识别结果不是健康险医疗保险")
    if "定制" in name and customized is False:
        warnings.append("名称含“定制”，但条款未识别到明确适用地区")
    if line is ProductLine.HEALTH and health_term is HealthTermClass.UNKNOWN:
        warnings.append("健康险未能确定长期/短期属性")
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
