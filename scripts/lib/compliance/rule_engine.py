"""确定性合规规则引擎 — 处理可量化的硬性检查。

从法规中提取的结构化规则，由 Python 代码确定性执行，
避免将数值比较、文本模式匹配等任务交给 LLM。
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ProductMetadata:
    """产品元数据，用于规则的精确匹配。

    与知识库 Excel 列一一对应：险种大类、险种类型、险种分型、保险期限、主附险。
    所有字段可选——缺失时该维度不做过滤。
    """
    category: Optional[str] = None         # 险种大类：健康险、寿险、意外险等
    sub_category: Optional[str] = None     # 险种类型：医疗险、重疾险、年金险等
    product_form: Optional[str] = None     # 险种分型：个人、团体等
    insurance_term: Optional[str] = None   # 保险期限：短期、长期、一年期
    policy_type: Optional[str] = None      # 主附险：主险、附加险


@dataclass(frozen=True)
class ComplianceRule:
    rule_id: str
    regulation_source: str
    article_number: str
    target_field: str
    check_type: str        # "numeric_comparison" | "text_pattern" | "required_text" | "prohibited_clause" | "numeric_range" | "field_presence"
    operator: str          # ">=" | "<=" | "==" | "not_match" | "must_contain" | "must_not_contain" | "in_range" | "must_exist"
    threshold: Any         # 对 in_range: 元组 (min, max)
    applicable_categories: List[str]
    severity: str          # "high" | "medium" | "low"
    description: str
    negation_context: Optional[List[str]] = None
    target_section: str = ""
    # 精确适用条件 — 与知识库元数据维度对齐
    applicable_sub_categories: List[str] = field(default_factory=list)
    applicable_insurance_terms: List[str] = field(default_factory=list)  # ["短期", "一年期", "长期"]
    applicable_policy_types: List[str] = field(default_factory=list)     # ["主险", "附加险"]
    applicable_product_forms: List[str] = field(default_factory=list)    # ["个人", "团体"]


@dataclass(frozen=True)
class RuleViolation:
    rule_id: str
    clause_number: str
    clause_content: str
    check_type: str
    status: str
    suggestion: str
    conclusion: str
    source_ref: str = ""
    chunk_id: Optional[str] = None
    confidence: str = "high"
    review_required: bool = False


# ---------------------------------------------------------------------------
# 规则定义 — 按法规来源分组
# ---------------------------------------------------------------------------

RULES: List[ComplianceRule] = [

    # === 《健康保险管理办法》2019年第3号 ===
    ComplianceRule(
        rule_id="health_wait_period_max_180",
        regulation_source="《健康保险管理办法》2019年第3号",
        article_number="第二十七条",
        target_field="等待期",
        check_type="numeric_comparison",
        operator="<=",
        threshold=180,
        applicable_categories=["健康险", "医疗险", "重疾险"],
        severity="high",
        description="健康保险等待期不得超过180天",
    ),
    ComplianceRule(
        rule_id="health_hesitation_min_15",
        regulation_source="《健康保险管理办法》2019年第3号",
        article_number="第十五条",
        target_field="犹豫期",
        check_type="numeric_comparison",
        operator=">=",
        threshold=15,
        applicable_categories=["健康险", "医疗险", "重疾险"],
        applicable_insurance_terms=["长期"],
        severity="high",
        description="长期健康保险产品的犹豫期不得少于15天",
    ),
    ComplianceRule(
        rule_id="health_must_have_preexisting",
        regulation_source="《关于健康保险产品等待期及既往症表述有关事项的通知》电子报备系统通知公告2022-7-27",
        article_number="第二项",
        target_field="既往症",
        check_type="field_presence",
        operator="must_exist",
        threshold=None,
        applicable_categories=["健康险", "医疗险"],
        severity="high",
        description="健康保险应当对既往症进行定义和说明",
    ),

    # === 银保监办发〔2021〕7号 — 短期健康保险 ===
    ComplianceRule(
        rule_id="short_health_no_guarantee_renew",
        regulation_source="银保监办发〔2021〕7号",
        article_number="第三条",
        target_field="续保",
        check_type="text_pattern",
        operator="not_match",
        threshold=r"保证续保|自动续保|承诺续保",
        applicable_categories=["健康险", "医疗险"],
        severity="high",
        description="短期健康险不得包含保证续保表述",
        applicable_insurance_terms=["短期", "一年期"],
    ),
    ComplianceRule(
        rule_id="short_health_must_state_1year",
        regulation_source="银保监办发〔2021〕7号",
        article_number="第三条",
        target_field="保险期间",
        check_type="required_text",
        operator="must_contain",
        threshold=r"保险期间.{0,4}[为是].{0,2}1\s*年|保险期间.{0,4}1\s*年|保险期限.{0,4}[为是].{0,2}1\s*年",
        applicable_categories=["健康险", "医疗险"],
        severity="high",
        description="短期健康险应当明确表述保险期间为1年",
        applicable_insurance_terms=["短期", "一年期"],
    ),
    ComplianceRule(
        rule_id="short_health_must_nonrenew_disclosure",
        regulation_source="银保监办发〔2021〕7号",
        article_number="第三条",
        target_field="续保",
        check_type="required_text",
        operator="must_contain",
        threshold=r"不保证续保|非保证续保|不承诺续保|本产品不保证续保",
        applicable_categories=["健康险", "医疗险"],
        severity="high",
        description="短期健康险应当明确声明不保证续保",
        applicable_insurance_terms=["短期", "一年期"],
    ),

    # === 《保险法》（2015年修订）===
    # 第二十六条原文：
    #   人寿保险以外的其他保险...诉讼时效期间为二年...
    #   人寿保险...诉讼时效期间为五年...
    ComplianceRule(
        rule_id="insurance_law_limitation_5y_life",
        regulation_source="《保险法》2015年修订",
        article_number="第二十六条",
        target_field="诉讼时效",
        check_type="numeric_comparison",
        operator=">=",
        threshold=5,
        applicable_categories=["寿险", "年金险"],
        severity="high",
        description="人寿保险的诉讼时效不得少于5年",
    ),
    ComplianceRule(
        rule_id="insurance_law_limitation_2y_nonlife",
        regulation_source="《保险法》2015年修订",
        article_number="第二十六条",
        target_field="诉讼时效",
        check_type="numeric_comparison",
        operator=">=",
        threshold=2,
        applicable_categories=["健康险", "医疗险", "意外险"],
        severity="high",
        description="非人寿保险的诉讼时效不得少于2年",
    ),

    # === 保监人身险〔2017〕134号 — 产品开发设计 ===
    ComplianceRule(
        rule_id="design_first_survival_payment_after_5y",
        regulation_source="《关于规范人身保险公司产品开发设计行为的通知》保监人身险〔2017〕134号",
        article_number="第一项",
        target_field="首次生存保险金给付",
        check_type="numeric_comparison",
        operator=">=",
        threshold=5,
        applicable_categories=["寿险", "年金险"],
        applicable_insurance_terms=["长期"],
        severity="high",
        description="两全保险、年金保险的首次生存保险金给付应在保单生效满5年之后",
    ),
    ComplianceRule(
        rule_id="design_no_death_main_health",
        regulation_source="《关于规范人身保险公司产品开发设计行为的通知》保监人身险〔2017〕134号",
        article_number="第一条",
        target_field="身故保险金",
        check_type="prohibited_clause",
        operator="must_not_contain",
        threshold=r"以死亡为给付保险金条件|死亡给付.*主险|身故.*主要.*责任",
        applicable_categories=["健康险", "医疗险"],
        severity="high",
        description="健康保险不得以死亡为给付保险金条件",
    ),

    # === 银保监办发〔2020〕27号 — 长期医疗保险费率调整 ===
    ComplianceRule(
        rule_id="long_medical_rate_adjust_first_interval_3y",
        regulation_source="《关于长期医疗保险产品费率调整有关问题的通知》银保监办发〔2020〕27号",
        article_number="第二项",
        target_field="首次费率调整",
        check_type="numeric_comparison",
        operator=">=",
        threshold=3,
        applicable_categories=["医疗险"],
        severity="high",
        description="长期医疗保险产品首次费率调整时间应当不早于产品上市销售之日起满3年",
        applicable_insurance_terms=["长期"],
    ),
    ComplianceRule(
        rule_id="long_medical_rate_adjust_subsequent_interval_1y",
        regulation_source="《关于长期医疗保险产品费率调整有关问题的通知》银保监办发〔2020〕27号",
        article_number="第二项",
        target_field="费率调整间隔",
        check_type="numeric_comparison",
        operator=">=",
        threshold=1,
        applicable_categories=["医疗险"],
        severity="high",
        description="长期医疗保险产品每次费率调整的时间间隔不得短于1年",
        applicable_insurance_terms=["长期"],
    ),

    # === 《重大疾病保险的疾病定义规范》（2020年修订版）===
    ComplianceRule(
        rule_id="ci_mild_pay_ratio_max_30",
        regulation_source="《重大疾病保险的疾病定义使用规范（2020年修订版）》",
        article_number="第二项",
        target_field="轻症",
        check_type="numeric_comparison",
        operator="<=",
        threshold=30,
        applicable_categories=["重疾险"],
        severity="high",
        description="轻度疾病累计保险金额不应高于相应重度疾病累计保险金额的30%",
    ),

    # === 普通型人身保险精算规定 ===
    ComplianceRule(
        rule_id="life_must_have_cash_value",
        regulation_source="《普通型人身保险精算规定》银保监办发〔2020〕7号",
        article_number="第二章",
        target_field="现金价值",
        check_type="field_presence",
        operator="must_exist",
        threshold=None,
        applicable_categories=["寿险", "年金险"],
        severity="high",
        description="人寿保险应当包含现金价值表",
    ),
    ComplianceRule(
        rule_id="life_hesitation_min_15",
        regulation_source="《人身保险公司保险条款和保险费率管理办法》2015年第3号",
        article_number="第二十条",
        target_field="犹豫期",
        check_type="numeric_comparison",
        operator=">=",
        threshold=15,
        applicable_categories=[],
        severity="high",
        description="犹豫期不得少于15天",
    ),

    # === 分红保险精算规定 ===
    ComplianceRule(
        rule_id="dividend_must_state_undetermined",
        regulation_source="《关于推进分红型人身保险费率政策改革有关事项的通知》保监发〔2015〕93号",
        article_number="第二项",
        target_field="红利",
        check_type="required_text",
        operator="must_contain",
        threshold=r"红利.*不确定|分红.*不确定|红利是不确定的|红利非保证|红利水平是不保证的|红利.*不保证|分红.*不保证",
        applicable_categories=["分红险"],
        severity="high",
        description="分红保险应当用醒目字体标明保单的红利水平是不保证的，在某些年度红利可能为零",
    ),
    ComplianceRule(
        rule_id="dividend_no_guarantee_rate",
        regulation_source="《分红保险精算规定》保监发〔2015〕93号",
        article_number="第四条",
        target_field="红利",
        check_type="prohibited_clause",
        operator="must_not_contain",
        threshold=r"保证红利|保底红利|最低红利|红利保证|保证分红率|保证收益率",
        applicable_categories=["分红险"],
        severity="high",
        description="分红保险不得对红利做出保证性承诺",
    ),

    # === 意外伤害保险 ===
    ComplianceRule(
        rule_id="accident_no_death_main_for_health",
        regulation_source="《关于规范人身保险公司产品开发设计行为的通知》保监人身险〔2017〕134号",
        article_number="第一条",
        target_field="身故保险金",
        check_type="prohibited_clause",
        operator="must_not_contain",
        threshold=r"以死亡为给付保险金条件|死亡给付.*主险|身故.*主要.*责任",
        applicable_categories=["意外险"],
        severity="medium",
        description="意外伤害保险不得以死亡为给付保险金条件作为主险责任",
    ),

    # === 互联网保险 ===
    # 原规则 internet_annuity_no_guarantee_rate 声称"互联网年金保险不得包含保证利率表述"，
    # 但项目内《关于进一步规范保险机构互联网人身保险业务有关事项的通知》文件中
    # 没有此条款。该规则已删除。如需恢复，需先在法规库中找到准确出处。

    # === 宽限期（通用）===
    ComplianceRule(
        rule_id="grace_period_min_60",
        regulation_source="《保险法》2015年修订",
        article_number="第三十六条",
        target_field="宽限期",
        check_type="numeric_comparison",
        operator=">=",
        threshold=60,
        applicable_categories=["寿险", "年金险", "重疾险"],
        severity="medium",
        description="分期支付保险费的，宽限期不得少于60天",
    ),

    # === 《健康保险管理办法》 — 长期健康保险续保 ===
    ComplianceRule(
        rule_id="health_long_term_renewal_clause",
        regulation_source="《健康保险管理办法》2019年第3号",
        article_number="第二十条",
        target_field="续保",
        check_type="field_presence",
        operator="must_exist",
        threshold=None,
        applicable_categories=["健康险", "医疗险"],
        severity="medium",
        description="长期健康保险应当包含明确的续保条款",
    ),

    # === 税优健康险 ===
    # 原规则 tax_health_deductible_limit 误把"免赔额≤2万"挂在金规〔2023〕2号下。
    # 实际该法规要求"至少包含免赔额为0的方案"，方向相反。该规则已删除。
    # 如需对税优健康险免赔额做检查，应改写为 required_text 检查"包含免赔额为0的方案"。
]


# ---------------------------------------------------------------------------
# 规则索引 — 按 category 预分组，避免全量遍历
# ---------------------------------------------------------------------------

_RULE_INDEX: dict[str, List[ComplianceRule]] = {}
_UNIVERSAL_RULES: List[ComplianceRule] = []  # applicable_categories=[] 的通用规则


def _build_rule_index() -> None:
    global _RULE_INDEX, _UNIVERSAL_RULES
    _RULE_INDEX = {}
    _UNIVERSAL_RULES = []
    for rule in RULES:
        if not rule.applicable_categories:
            _UNIVERSAL_RULES.append(rule)
        else:
            for cat in rule.applicable_categories:
                _RULE_INDEX.setdefault(cat, []).append(rule)


_build_rule_index()


def _get_applicable_rules(meta: ProductMetadata) -> List[ComplianceRule]:
    """按 category 索引快速获取适用规则，再做条件精筛。"""
    candidates = list(_UNIVERSAL_RULES)
    if meta.category and meta.category in _RULE_INDEX:
        candidates.extend(_RULE_INDEX[meta.category])
    return [r for r in candidates if _is_rule_applicable(r, meta)]

_FIELD_SYNONYMS: dict[str, list[str]] = {
    "等待期": ["观察期", "观察期限", "免责期", "等待期限"],
    "犹豫期": ["犹豫期限", "冷静期", "冷静期限", "撤回期"],
    "保险期间": ["保险期限", "保障期间", "保障期限"],
    "续保": ["保证续保", "自动续保", "承诺续保", "连续投保"],
    "既往症": ["既往疾病", "既往病史", "既有疾病", "原有疾病"],
    "免赔额": ["起付线", "起付金额", "自付额"],
    "身故保险金": ["身故给付", "身故赔偿金", "死亡保险金", "死亡给付"],
    "现金价值": ["退保价值", "解约价值", "退保金"],
    "保险费": ["保费", "应交保费", "期交保费"],
    "保单年度": ["保险年度", "合同年度"],
    "解除合同": ["退保", "终止合同", "解除保险合同"],
    "费率调整": ["保费调整", "费率变化", "费率浮动"],
    "红利": ["分红", "红利分配", "红利金额"],
    "诉讼时效": ["起诉期限", "诉讼期间", "权利时效"],
    "满期给付": ["满期保险金", "满期返还", "满期金"],
    "轻症": ["轻度疾病", "轻症疾病", "轻度重疾"],
    "中症": ["中度疾病", "中症疾病", "中度重疾"],
    "基本保险金额": ["基本保额", "保险金额", "保额"],
    "宽限期": ["宽限期限", "缴费宽限期"],
}


# ---------------------------------------------------------------------------
# 数值提取
# ---------------------------------------------------------------------------

_NUMERIC_PATTERNS = [
    re.compile(r'(\d+(?:\.\d+)?)\s*%'),        # 百分比
    re.compile(r'(\d+(?:\.\d+)?)\s*万'),        # 万元
    re.compile(r'(\d+)\s*[天日]'),               # 天/日
    re.compile(r'(\d+)\s*个?\s*月'),             # 月
    re.compile(r'(\d+)\s*年'),                    # 年
]


def _extract_numeric_value(text: str, field_hint: str) -> Optional[float]:
    lowered = text.lower()
    hint_pos = lowered.find(field_hint)
    if hint_pos < 0:
        for syn in _FIELD_SYNONYMS.get(field_hint, []):
            hint_pos = lowered.find(syn)
            if hint_pos >= 0:
                break
    if hint_pos < 0:
        return None
    context_radius = 30
    start = max(0, hint_pos - context_radius)
    end = min(len(text), hint_pos + context_radius + len(field_hint))
    context = text[start:end]
    for pattern in _NUMERIC_PATTERNS:
        m = pattern.search(context)
        if m:
            return float(m.group(1))
    return None


# ---------------------------------------------------------------------------
# 条款提取
# ---------------------------------------------------------------------------

_CLAUSE_RE = re.compile(
    r'【(?:附加险)?条款\s+(\d+(?:\.\d+)*)】([^\n]*)\n([\s\S]*?)(?=【|$)'
)


# ---------------------------------------------------------------------------
# 默认否定前缀
# ---------------------------------------------------------------------------

_DEFAULT_NEGATION_PREFIXES = ["不", "非", "未", "无", "不得", "不可以", "不能"]


# ---------------------------------------------------------------------------
# 检查逻辑
# ---------------------------------------------------------------------------


def _check_single_rule(
    rule: ComplianceRule,
    clause_text: str,
    clause_number: str,
) -> Optional[RuleViolation]:
    if rule.check_type == "numeric_comparison":
        return _check_numeric_comparison(rule, clause_text, clause_number)
    elif rule.check_type == "text_pattern":
        return _check_text_pattern(rule, clause_text, clause_number)
    elif rule.check_type == "numeric_range":
        return _check_numeric_range(rule, clause_text, clause_number)
    return None


def _check_numeric_comparison(
    rule: ComplianceRule,
    clause_text: str,
    clause_number: str,
) -> Optional[RuleViolation]:
    value = _extract_numeric_value(clause_text, rule.target_field)
    if value is None:
        return None
    threshold = float(rule.threshold)
    violated = False
    if rule.operator == ">=" and value < threshold:
        violated = True
    elif rule.operator == "<=" and value > threshold:
        violated = True
    elif rule.operator == "==" and value != threshold:
        violated = True
    if not violated:
        return None
    return RuleViolation(
        rule_id=rule.rule_id,
        clause_number=clause_number,
        clause_content=clause_text[:200],
        check_type="rule_engine",
        status="non_compliant",
        suggestion=f"根据{rule.regulation_source}{rule.article_number}，{rule.description}",
        conclusion=f"{rule.target_field}为{value}，{rule.description}",
    )


def _check_text_pattern(
    rule: ComplianceRule,
    clause_text: str,
    clause_number: str,
) -> Optional[RuleViolation]:
    pattern = re.compile(rule.threshold)
    match = pattern.search(clause_text)
    if rule.operator == "not_match" and match:
        negation_prefixes = rule.negation_context or _DEFAULT_NEGATION_PREFIXES
        before = clause_text[:match.start()]
        is_negated = any(before.rstrip().endswith(neg) for neg in negation_prefixes)
        if is_negated:
            return None
        return RuleViolation(
            rule_id=rule.rule_id,
            clause_number=clause_number,
            clause_content=match.group(0),
            check_type="rule_engine",
            status="non_compliant",
            suggestion=f"根据{rule.regulation_source}，{rule.description}",
            conclusion=f"条款包含禁止表述「{match.group(0)}」",
        )
    return None


def _check_required_text_document(
    rule: ComplianceRule,
    clauses: List[Tuple[str, str, str]],
) -> Optional[RuleViolation]:
    """文档级检查：任意一条条款包含所需文本即合规。"""
    if rule.operator == "must_contain":
        pattern = re.compile(rule.threshold)
        for clause_num, clause_title, clause_text in clauses:
            full_text = f"{clause_title}\n{clause_text}".strip()
            if pattern.search(full_text):
                return None
        return RuleViolation(
            rule_id=rule.rule_id,
            clause_number="全文档",
            clause_content=f"缺少必要内容",
            check_type="rule_engine",
            status="non_compliant",
            suggestion=f"根据{rule.regulation_source}{rule.article_number}，{rule.description}",
            conclusion=f"文档缺少必要内容，{rule.description}",
        )
    return None


def _check_prohibited_clause_document(
    rule: ComplianceRule,
    clauses: List[Tuple[str, str, str]],
) -> Optional[RuleViolation]:
    """文档级检查：任意一条条款包含禁止内容即违规。"""
    if rule.operator == "must_not_contain":
        pattern = re.compile(rule.threshold)
        for clause_num, clause_title, clause_text in clauses:
            full_text = f"{clause_title}\n{clause_text}".strip()
            match = pattern.search(full_text)
            if match:
                return RuleViolation(
                    rule_id=rule.rule_id,
                    clause_number=clause_num,
                    clause_content=match.group(0),
                    check_type="rule_engine",
                    status="non_compliant",
                    suggestion=f"根据{rule.regulation_source}{rule.article_number}，{rule.description}",
                    conclusion=f"条款包含禁止内容「{match.group(0)}」",
                )
    return None


def _check_numeric_range(
    rule: ComplianceRule,
    clause_text: str,
    clause_number: str,
) -> Optional[RuleViolation]:
    if rule.operator == "in_range":
        value = _extract_numeric_value(clause_text, rule.target_field)
        if value is None:
            return None
        lo, hi = rule.threshold
        if value < lo or value > hi:
            return RuleViolation(
                rule_id=rule.rule_id,
                clause_number=clause_number,
                clause_content=clause_text[:200],
                check_type="rule_engine",
                status="non_compliant",
                suggestion=f"根据{rule.regulation_source}{rule.article_number}，{rule.description}",
                conclusion=f"{rule.target_field}为{value}，不在允许范围[{lo}, {hi}]内",
            )
    return None


def _check_field_presence(
    rule: ComplianceRule,
    clauses: List[Tuple[str, str, str]],
) -> Optional[RuleViolation]:
    """文档级检查：验证字段是否出现在任何条款中。"""
    search_terms = [rule.target_field] + _FIELD_SYNONYMS.get(rule.target_field, [])
    for clause_num, clause_title, clause_text in clauses:
        full_text = f"{clause_title}\n{clause_text}".strip()
        if any(term in full_text for term in search_terms):
            return None
    return RuleViolation(
        rule_id=rule.rule_id,
        clause_number="全文档",
        clause_content=f"缺少「{rule.target_field}」相关条款",
        check_type="rule_engine",
        status="non_compliant",
        suggestion=f"根据{rule.regulation_source}{rule.article_number}，{rule.description}",
        conclusion=f"文档缺少「{rule.target_field}」相关条款，{rule.description}",
    )


def _is_rule_applicable(rule: ComplianceRule, meta: ProductMetadata) -> bool:
    """检查规则是否适用于给定产品元数据。"""
    # 险种大类匹配
    if rule.applicable_categories:
        if not meta.category or meta.category not in rule.applicable_categories:
            return False
    # 险种类型匹配
    if rule.applicable_sub_categories:
        if not meta.sub_category or meta.sub_category not in rule.applicable_sub_categories:
            return False
    # 保险期限匹配
    if rule.applicable_insurance_terms:
        if not meta.insurance_term or meta.insurance_term not in rule.applicable_insurance_terms:
            return False
    # 主附险匹配
    if rule.applicable_policy_types:
        if not meta.policy_type or meta.policy_type not in rule.applicable_policy_types:
            return False
    # 险种分型匹配
    if rule.applicable_product_forms:
        if not meta.product_form or meta.product_form not in rule.applicable_product_forms:
            return False
    return True


def check_rules(
    document_content: str,
    category: Optional[str],
    metadata: Optional[ProductMetadata] = None,
) -> List[RuleViolation]:
    if metadata is None:
        metadata = ProductMetadata(category=category)
    elif metadata.category is None:
        metadata = ProductMetadata(
            category=category,
            sub_category=metadata.sub_category,
            product_form=metadata.product_form,
            insurance_term=metadata.insurance_term,
            policy_type=metadata.policy_type,
        )
    violations: List[RuleViolation] = []
    clauses = _CLAUSE_RE.findall(document_content)
    rules = _get_applicable_rules(metadata)
    for rule in rules:
        if rule.check_type == "field_presence":
            v = _check_field_presence(rule, clauses)
            if v:
                violations.append(v)
        elif rule.check_type == "required_text":
            v = _check_required_text_document(rule, clauses)
            if v:
                violations.append(v)
        elif rule.check_type == "prohibited_clause":
            v = _check_prohibited_clause_document(rule, clauses)
            if v:
                violations.append(v)
        else:
            for clause_num, clause_title, clause_text in clauses:
                full_text = f"{clause_title}\n{clause_text}".strip()
                v = _check_single_rule(rule, full_text, clause_num)
                if v:
                    violations.append(v)
    return violations
