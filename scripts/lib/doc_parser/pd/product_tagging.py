"""从产品名称和条款正文生成可解释的产品标签。"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Match, Optional, Tuple, Union

from ...common.constants import CoverageFactKeys
from ...common.product_tags import (
    ContractRole, CustomerScope, DiseasePaymentPattern, HealthTermClass,
    MedicalBenefitBasis, ProductDesignType, ProductLine, ProductSubtype,
    ProductTags, ProductTermClass, ProductTermForm, RenewalType, TagEvidence,
    TermOption,
)
from .critical_illness_definitions import find_critical_illness_term

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

_COVERAGE_PATTERNS = {
    "critical_illness": (
        re.compile(r"重大疾病保险金"),
        re.compile(r"重疾保险金"),
    ),
    "disease": (
        re.compile(r"(?<!重大)(?<!重症)(?<!中症)(?<!轻症)疾病保险金"),
    ),
    "medical": (
        re.compile(r"医疗费用保险金"),
        re.compile(r"(?<!意外)(?<!伤害)医疗保险金"),
    ),
    "accidental_medical": (
        re.compile(r"意外医疗保险金"),
        re.compile(r"意外伤害医疗保险金"),
    ),
    "disability_income": (re.compile(r"失能收入损失保险金"),),
    "nursing": (
        re.compile(r"长期护理保险金"),
        re.compile(r"护理保险金"),
    ),
    "death": (re.compile(r"身故保险金"),),
    "survival": (
        re.compile(r"生存保险金"),
        re.compile(r"满期保险金"),
    ),
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
        r'(?:每\s*)?'
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

_MEDICAL_EXPENSE_PATTERNS = (
    re.compile(
        r'(?:实际发生|支出)[^。；\n]{0,80}'
        r'(?:医疗|药品|治疗|手术|基因检测)[^。；\n]{0,30}费用'
    ),
    re.compile(
        r'(?:医疗|药品|治疗|手术|基因检测)[^。；\n]{0,30}费用'
        r'[^。；\n]{0,100}(?:赔付比例|给付比例|剩余部分)'
    ),
    re.compile(r'费用补偿型(?:商业)?医疗保险'),
)
_MEDICAL_DAILY_ALLOWANCE_PATTERNS = (
    re.compile(r'(?:住院|护理|重症监护)[^。；\n]{0,12}(?:日额|津贴)保险金'),
    re.compile(
        r'(?:每日|每天|按日)[^。；\n]{0,30}'
        r'(?:给付|支付)[^。；\n]{0,30}(?:津贴|保险金)'
    ),
)
_MEDICAL_FIXED_BENEFIT_PATTERNS = (
    re.compile(
        r'本公司按[^。；\n]{0,60}(?:基本保险金额|约定金额)'
        r'给付\s*(?:医\s*疗意外|并发症)'
    ),
    re.compile(
        r'(?:医疗意外身故|手术|并发症|住院)[^。；\n]{0,20}保险金'
        r'[^。；\n]{0,160}(?:按|依照)[^。；\n]{0,40}'
        r'(?:基本保险金额|约定金额)[^。；\n]{0,20}(?:给付|支付)'
    ),
    re.compile(
        r'(?:医疗|手术|并发症|住院)[^。；\n]{0,40}'
        r'(?:定额给付|固定金额给付)'
    ),
)
_DISEASE_MULTIPLE_PAYMENT_PATTERNS = (
    re.compile(r'多次给付'),
    re.compile(
        r'第[二三四五六七八九十\d]+次'
        r'(?:重大疾病|中症疾病|轻症疾病|疾病)?保险金'
    ),
    re.compile(
        r'(?:累计|最多|最高)[^。；\n]{0,30}给付'
        r'[^。；\n]{0,20}[二两三四五六七八九十\d]+\s*次'
    ),
    re.compile(r'(?:每组|不同组)[^。；\n]{0,80}(?:疾病)?保险金[^。；\n]{0,40}给付'),
)
_DISEASE_SINGLE_PAYMENT_PATTERNS = (
    re.compile(
        r'(?:给付|支付)[^。；\n]{0,20}'
        r'(?:重大疾病|疾病)保险金[^。；\n]{0,80}'
        r'(?:保险责任|本合同|合同效力)[^。；\n]{0,20}终止'
    ),
    re.compile(
        r'(?:重大疾病|疾病)保险金[^。；\n]{0,80}'
        r'(?:仅|只|最多)?\s*(?:给付|支付)\s*(?:一|1)\s*次'
    ),
)

_CANCER_SPECIFIC_NAME_PATTERN = re.compile(
    r"(?:恶性肿瘤|癌症|防癌)[^保险\n]{0,30}(?:医疗|疾病)?保险"
)
_SPECIFIC_DISEASE_NAME_PATTERN = re.compile(
    r"特定疾病保险|白血病(?:疾病)?保险|"
    r"(?:特定)?心脑血管(?:疾病)?保险"
)
_OUT_OF_HOSPITAL_DRUG_MENTION_PATTERN = re.compile(r"院外购药|药店")
_INCREASING_SUM_ASSURED_NAME_PATTERN = re.compile(
    r"增额(?:(?!保险|\n).){0,20}终身寿险"
)
_INCREASING_SUM_ASSURED_CLAUSE_PATTERN = re.compile(
    r"(?:有效保险金额|基本保险金额|保险金额)[^。；\n]{0,50}"
    r"(?:逐年|每年|按年)[^。；\n]{0,30}(?:递增|增加|增长)"
)
_RELIABLE_PRODUCT_NAME_SOURCES = frozenset({
    "user_input",
    "document_content",
    "file_name",
    "product_name",
})


def _has_attested_coverage(
    fact_key: str,
    complete_document: bool,
    coverage_attested_facts: Tuple[str, ...],
) -> bool:
    """全文证明兼容旧调用；局部证明只授权对应的负向事实。"""
    return complete_document or fact_key in coverage_attested_facts


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


def _first_match(
    patterns: Tuple[re.Pattern[str], ...],
    text: str,
) -> Optional[Match[str]]:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match
    return None


def _medical_benefit_basis(
    subtype: ProductSubtype,
    components: Tuple[str, ...],
    document_content: str,
) -> Tuple[MedicalBenefitBasis, Optional[Match[str]]]:
    medical_components = {"medical", "accidental_medical"}
    if (
        subtype in (ProductSubtype.UNKNOWN, ProductSubtype.OTHER_HEALTH)
        and not medical_components.intersection(components)
    ):
        return MedicalBenefitBasis.UNKNOWN, None
    if (
        subtype not in (ProductSubtype.MEDICAL, ProductSubtype.MEDICAL_ACCIDENT)
        and not medical_components.intersection(components)
    ):
        return MedicalBenefitBasis.NOT_APPLICABLE, None
    expense_match = _first_match(_MEDICAL_EXPENSE_PATTERNS, document_content)
    daily_match = _first_match(
        _MEDICAL_DAILY_ALLOWANCE_PATTERNS,
        document_content,
    )
    fixed_match = _first_match(
        _MEDICAL_FIXED_BENEFIT_PATTERNS,
        document_content,
    )
    positive_matches = tuple(
        match
        for match in (expense_match, daily_match, fixed_match)
        if match is not None
    )
    if len(positive_matches) > 1:
        return MedicalBenefitBasis.MIXED, positive_matches[0]
    if expense_match:
        return MedicalBenefitBasis.EXPENSE_REIMBURSEMENT, expense_match
    if daily_match:
        return MedicalBenefitBasis.DAILY_ALLOWANCE, daily_match
    if fixed_match:
        return MedicalBenefitBasis.FIXED_BENEFIT, fixed_match
    return MedicalBenefitBasis.UNKNOWN, None


def _disease_payment_pattern(
    subtype: ProductSubtype,
    components: Tuple[str, ...],
    document_content: str,
) -> Tuple[DiseasePaymentPattern, Optional[Match[str]]]:
    disease_components = {"disease", "critical_illness"}
    if (
        subtype in (ProductSubtype.UNKNOWN, ProductSubtype.OTHER_HEALTH)
        and not disease_components.intersection(components)
    ):
        return DiseasePaymentPattern.UNKNOWN, None
    if (
        subtype not in (
            ProductSubtype.DISEASE,
            ProductSubtype.CRITICAL_ILLNESS,
        )
        and not disease_components.intersection(components)
    ):
        return DiseasePaymentPattern.NOT_APPLICABLE, None
    multiple_match = _first_match(
        _DISEASE_MULTIPLE_PAYMENT_PATTERNS,
        document_content,
    )
    if multiple_match:
        return DiseasePaymentPattern.MULTIPLE, multiple_match
    single_match = _first_match(
        _DISEASE_SINGLE_PAYMENT_PATTERNS,
        document_content,
    )
    if single_match:
        return DiseasePaymentPattern.SINGLE, single_match
    return DiseasePaymentPattern.UNKNOWN, None


def build_product_tags(
    product_name: Optional[str],
    document_content: str = "",
    *,
    product_name_source: str = "product_name",
    complete_document: bool = False,
    coverage_attested_facts: Tuple[str, ...] = (),
) -> ProductTags:
    """构建产品标签；负向推断只使用对应事实的正文覆盖证明。"""
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
    renewal_from_absence = False
    normalized_document_content = re.sub(
        r"\s+", "", unicodedata.normalize("NFKC", document_content)
    )
    if (
        renewal is RenewalType.UNKNOWN
        and _has_attested_coverage(
            CoverageFactKeys.RENEWAL_TEXT,
            complete_document,
            coverage_attested_facts,
        )
        and line is not ProductLine.UNKNOWN
        and document_content.strip()
        and "续保" not in normalized_document_content
    ):
        renewal = RenewalType.NONE
        renewal_from_absence = True

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
            elif renewal in (RenewalType.NON_GUARANTEED, RenewalType.NONE):
                health_term = HealthTermClass.SHORT_HEALTH
        elif term_class is ProductTermClass.SHORT_TERM:
            health_term = HealthTermClass.SHORT_HEALTH
    elif line is not ProductLine.UNKNOWN:
        health_term = HealthTermClass.NOT_APPLICABLE
    # 对健康险，长期/短期本身就是监管分类：一年期保证续保产品也属于长期。
    # 物理保险期间仍完整保留在 term_forms/term_options，不能让两套单选标签冲突。
    if health_term is HealthTermClass.LONG_HEALTH:
        term_class = ProductTermClass.LONG_TERM
    elif health_term is HealthTermClass.SHORT_HEALTH:
        term_class = ProductTermClass.SHORT_TERM
    elif (
        line is ProductLine.HEALTH
        and ProductTermForm.ONE_YEAR_OR_LESS in forms
        and renewal is RenewalType.UNKNOWN
    ):
        # 一年期是物理期限事实，不足以单独确定健康险监管期限。续保
        # 约定未能确定时保守保留两侧法规，避免错误排除长期健康险规则。
        term_class = ProductTermClass.UNKNOWN

    internet = "互联网" in name if product_name else None
    adjustable = "费率可调" in name if product_name else None
    tax_match = re.search(
        r'税收优惠|个人所得税[^。；\n]*优惠|税优健康',
        document_content,
    )
    tax: Optional[bool] = None
    if tax_match:
        tax = True
    elif _has_attested_coverage(
        CoverageFactKeys.TAX_ADVANTAGED_TEXT,
        complete_document,
        coverage_attested_facts,
    ) and document_content.strip():
        tax = False
    customized = None
    customized_match = None
    if product_name:
        customized_match = re.search(r'城市定制(?:型)?', name)
        customized = customized_match is not None

    cancer_specific_match = (
        _CANCER_SPECIFIC_NAME_PATTERN.search(name)
        if product_name
        else None
    )
    specific_disease_match = (
        _SPECIFIC_DISEASE_NAME_PATTERN.search(name)
        if product_name
        else None
    )
    cancer_specific: Optional[bool] = None
    specific_disease: Optional[bool] = None
    reliable_classified_name = bool(
        product_name
        and product_name_source in _RELIABLE_PRODUCT_NAME_SOURCES
        and line is not ProductLine.UNKNOWN
        and subtype is not ProductSubtype.UNKNOWN
    )
    if cancer_specific_match:
        cancer_specific = True
        if subtype in (ProductSubtype.DISEASE, ProductSubtype.CRITICAL_ILLNESS):
            specific_disease = True
    elif specific_disease_match:
        specific_disease = True
    if specific_disease is None and reliable_classified_name and subtype not in (
        ProductSubtype.DISEASE,
        ProductSubtype.CRITICAL_ILLNESS,
    ):
        specific_disease = False
    if cancer_specific is None and reliable_classified_name:
        cancer_specific = False

    increasing_name_match = (
        _INCREASING_SUM_ASSURED_NAME_PATTERN.search(name)
        if product_name
        else None
    )
    increasing_clause_match = _INCREASING_SUM_ASSURED_CLAUSE_PATTERN.search(
        document_content,
    )
    increasing_sum_assured: Optional[bool] = None
    if increasing_name_match or increasing_clause_match:
        increasing_sum_assured = True
    elif _has_attested_coverage(
        CoverageFactKeys.INCREASING_SUM_ASSURED_TEXT,
        complete_document,
        coverage_attested_facts,
    ) and document_content.strip():
        increasing_sum_assured = False

    out_of_hospital_drug_match = _OUT_OF_HOSPITAL_DRUG_MENTION_PATTERN.search(
        document_content,
    )
    out_of_hospital_drug: Optional[bool] = None
    if out_of_hospital_drug_match:
        out_of_hospital_drug = True
    elif _has_attested_coverage(
        CoverageFactKeys.OUT_OF_HOSPITAL_DRUG_TEXT,
        complete_document,
        coverage_attested_facts,
    ) and document_content.strip():
        out_of_hospital_drug = False

    reliable_product_name = bool(
        product_name and product_name_source in _RELIABLE_PRODUCT_NAME_SOURCES
    )
    critical_illness_name_match = (
        re.search(r"重大疾病", name) if reliable_product_name else None
    )
    critical_illness_term_match = find_critical_illness_term(document_content)
    critical_illness_term: Optional[bool] = None
    if critical_illness_name_match or critical_illness_term_match:
        critical_illness_term = True
    elif (
        reliable_product_name
        and _has_attested_coverage(
            CoverageFactKeys.CRITICAL_ILLNESS_TERM_TEXT,
            complete_document,
            coverage_attested_facts,
        )
        and document_content.strip()
    ):
        critical_illness_term = False

    component_matches: Dict[str, Optional[Match[str]]] = {}
    for key, patterns in _COVERAGE_PATTERNS.items():
        component_match = None
        for pattern in patterns:
            component_match = pattern.search(document_content)
            if component_match:
                break
        component_matches[key] = component_match
    content_components = tuple(
        key for key, match in component_matches.items() if match is not None
    )
    primary_component = _SUBTYPE_COMPONENT.get(subtype)
    component_values = [primary_component] if primary_component else []
    component_values.extend(
        key for key in content_components if key != primary_component
    )
    components = tuple(component_values)
    medical_benefit, medical_benefit_match = _medical_benefit_basis(
        subtype,
        components,
        document_content,
    )
    disease_payment, disease_payment_match = _disease_payment_pattern(
        subtype,
        components,
        document_content,
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
        health_term_reason = (
            f"line={line.value}"
            if health_term is HealthTermClass.NOT_APPLICABLE
            else f"term_class={term_class.value}; renewal_type={renewal.value}"
        )
        evidence.append(_evidence(
            "health_term_class", health_term.value, "derived",
            health_term_reason,
        ))
    if renewal is not RenewalType.UNKNOWN:
        if renewal_from_absence:
            evidence.append(TagEvidence(
                "renewal_type",
                renewal.value,
                "document_coverage_attestation",
                "续保事实相关正文已覆盖，未出现续保约定",
                1.0,
            ))
        else:
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
    ):
        if tag_value is not None:
            evidence.append(_evidence(
                field,
                str(tag_value).lower(),
                source,
                source_text,
                evidence_match,
            ))
    if tax is True:
        evidence.append(_evidence(
            "is_tax_advantaged_health",
            "true",
            "product_clause",
            document_content,
            tax_match,
        ))
    elif tax is False:
        evidence.append(TagEvidence(
            "is_tax_advantaged_health",
            "false",
            "document_coverage_attestation",
            "税优事实相关正文已覆盖，未出现税收优惠表述",
            1.0,
        ))
    if customized is not None:
        evidence.append(_evidence(
            "is_city_customized_medical",
            str(customized).lower(),
            product_name_source,
            name,
            customized_match,
        ))
    for field, fact_value, match in (
        (
            "is_specific_disease_product",
            specific_disease,
            specific_disease_match or cancer_specific_match,
        ),
        (
            "is_cancer_specific_product",
            cancer_specific,
            cancer_specific_match,
        ),
    ):
        if fact_value is True:
            evidence.append(_evidence(
                field,
                "true",
                product_name_source,
                name,
                match,
            ))
        elif fact_value is False:
            evidence.append(TagEvidence(
                field,
                "false",
                product_name_source,
                (
                    f"产品名称已可靠识别为 line={line.value}, "
                    f"subtype={subtype.value}，未识别为对应专项产品"
                ),
                1.0,
            ))
        elif field == "is_specific_disease_product" and reliable_classified_name:
            evidence.append(TagEvidence(
                field,
                "unknown",
                product_name_source,
                (
                    f"产品名称已可靠识别为 line={line.value}, "
                    f"subtype={subtype.value}，但未明确限定专项疾病，保守保持未知"
                ),
                1.0,
            ))
    if out_of_hospital_drug is True:
        evidence.append(_evidence(
            "mentions_out_of_hospital_drug",
            "true",
            "product_clause",
            document_content,
            out_of_hospital_drug_match,
        ))
    elif out_of_hospital_drug is False:
        evidence.append(TagEvidence(
            "mentions_out_of_hospital_drug",
            "false",
            "document_coverage_attestation",
            "院外购药事实相关正文已覆盖，未出现“院外购药”或“药店”表述",
            1.0,
        ))
    if critical_illness_name_match:
        evidence.append(_evidence(
            "mentions_critical_illness_definition_term",
            "true",
            product_name_source,
            name,
            critical_illness_name_match,
        ))
    elif critical_illness_term is True and critical_illness_term_match:
        evidence.append(_evidence(
            "mentions_critical_illness_definition_term",
            "true",
            "product_clause",
            document_content,
            critical_illness_term_match.matched_term,
        ))
    elif critical_illness_term is False:
        evidence.append(TagEvidence(
            "mentions_critical_illness_definition_term",
            "false",
            "document_coverage_attestation",
            "可靠产品名称和重疾术语相关正文均未出现“重大疾病”或2020版规范列明疾病名称",
            1.0,
        ))
    if increasing_sum_assured is True:
        evidence.append(_evidence(
            "is_increasing_sum_assured_product",
            "true",
            product_name_source if increasing_name_match else "product_clause",
            name if increasing_name_match else document_content,
            increasing_name_match or increasing_clause_match,
        ))
    elif increasing_sum_assured is False:
        evidence.append(TagEvidence(
            "is_increasing_sum_assured_product",
            "false",
            "document_coverage_attestation",
            "保额递增事实相关正文已覆盖，未识别到保额逐年递增设计",
            1.0,
        ))
    for component in components:
        if component == primary_component:
            evidence.append(_evidence(
                "coverage_components",
                component,
                product_name_source,
                name,
            ))
        else:
            evidence.append(_evidence(
                "coverage_components",
                component,
                "product_clause",
                document_content,
                component_matches[component],
            ))
    for benefit_field, benefit_value, benefit_match in (
        ("medical_benefit_basis", medical_benefit, medical_benefit_match),
        ("disease_payment_pattern", disease_payment, disease_payment_match),
    ):
        if benefit_value.value == "unknown":
            continue
        if benefit_value.value == "not_applicable":
            evidence.append(_evidence(
                benefit_field,
                benefit_value.value,
                "derived",
                (
                    f"primary_subtype={subtype.value}; "
                    f"coverage_components={','.join(components)}"
                ),
            ))
        else:
            evidence.append(_evidence(
                benefit_field,
                benefit_value.value,
                "product_clause",
                document_content,
                benefit_match,
            ))
    if adjustable and not (line is ProductLine.HEALTH and subtype is ProductSubtype.MEDICAL):
        warnings.append("名称含“费率可调”，但产品名称识别结果不是健康险医疗保险")
    if "定制" in name and customized is False:
        warnings.append("产品名称含“定制”，但未识别到“城市定制型”身份")
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
    health_components = set(content_components).intersection(
        _SUBTYPE_COMPONENT.values(),
    )
    if expected_component and health_components and expected_component not in health_components:
        warnings.append("产品名称确定的主要险种与条款中识别到的健康责任不一致")

    return ProductTags(
        line=line, primary_subtype=subtype, design_type=design,
        term_class=term_class, term_forms=forms, term_options=options,
        health_term_class=health_term, customer_scope=customer, contract_role=role,
        renewal_type=renewal, is_internet_exclusive=internet,
        is_rate_adjustable=adjustable, is_tax_advantaged_health=tax,
        is_city_customized_medical=customized,
        is_specific_disease_product=specific_disease,
        mentions_out_of_hospital_drug=out_of_hospital_drug,
        is_cancer_specific_product=cancer_specific,
        mentions_critical_illness_definition_term=critical_illness_term,
        is_increasing_sum_assured_product=increasing_sum_assured,
        coverage_components=components,
        medical_benefit_basis=medical_benefit,
        disease_payment_pattern=disease_payment,
        evidence=tuple(evidence), warnings=tuple(warnings),
    )
