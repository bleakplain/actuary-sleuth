"""保险产品与条款主题的受控标签模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class ProductLine(str, Enum):
    LIFE = "life"
    HEALTH = "health"
    ACCIDENT = "accident"
    UNKNOWN = "unknown"


class ProductSubtype(str, Enum):
    TERM_LIFE = "term_life"
    WHOLE_LIFE = "whole_life"
    ENDOWMENT = "endowment"
    ANNUITY = "annuity"
    DISEASE = "disease"
    CRITICAL_ILLNESS = "critical_illness"
    MEDICAL = "medical"
    DISABILITY_INCOME = "disability_income"
    NURSING = "nursing"
    MEDICAL_ACCIDENT = "medical_accident"
    ACCIDENT = "accident"
    OTHER_LIFE = "other_life"
    OTHER_HEALTH = "other_health"
    OTHER_ACCIDENT = "other_accident"
    UNKNOWN = "unknown"


class ProductDesignType(str, Enum):
    ORDINARY = "ordinary"
    PARTICIPATING = "participating"
    UNIVERSAL = "universal"
    UNIT_LINKED = "unit_linked"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class ProductTermClass(str, Enum):
    LONG_TERM = "long_term"
    SHORT_TERM = "short_term"
    UNKNOWN = "unknown"


class ProductTermForm(str, Enum):
    ONE_YEAR_OR_LESS = "one_year_or_less"
    OVER_ONE_YEAR = "over_one_year"
    FIXED_DURATION = "fixed_duration"
    TO_AGE = "to_age"
    WHOLE_LIFE = "whole_life"
    GUARANTEED_RENEWAL_PERIOD = "guaranteed_renewal_period"
    MULTIPLE_OPTIONS = "multiple_options"


class HealthTermClass(str, Enum):
    LONG_HEALTH = "long_health"
    SHORT_HEALTH = "short_health"
    UNKNOWN = "unknown"


class CustomerScope(str, Enum):
    INDIVIDUAL = "individual"
    GROUP = "group"
    UNKNOWN = "unknown"


class ContractRole(str, Enum):
    MAIN = "main"
    RIDER = "rider"
    UNKNOWN = "unknown"


class PremiumPattern(str, Enum):
    SINGLE = "single"
    INSTALLMENT = "installment"
    FLEXIBLE = "flexible"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class RenewalType(str, Enum):
    NONE = "none"
    NON_GUARANTEED = "non_guaranteed"
    GUARANTEED = "guaranteed"
    UNKNOWN = "unknown"


class MedicalBenefitBasis(str, Enum):
    EXPENSE_REIMBURSEMENT = "expense_reimbursement"
    FIXED_BENEFIT = "fixed_benefit"
    DAILY_ALLOWANCE = "daily_allowance"
    MIXED = "mixed"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class DiseasePaymentPattern(str, Enum):
    SINGLE = "single"
    MULTIPLE = "multiple"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


PRODUCT_TAG_LABELS: Dict[str, Dict[str, str]] = {
    "line": {"life": "人寿保险", "health": "健康保险", "accident": "意外伤害保险", "unknown": "未知"},
    "primary_subtype": {
        "term_life": "定期寿险", "whole_life": "终身寿险", "endowment": "两全保险",
        "annuity": "年金保险", "disease": "疾病保险", "critical_illness": "重大疾病保险",
        "medical": "医疗保险", "disability_income": "失能收入损失保险", "nursing": "护理保险",
        "medical_accident": "医疗意外保险", "accident": "意外伤害保险",
        "other_life": "其他人寿保险", "other_health": "其他健康保险",
        "other_accident": "其他意外伤害保险", "unknown": "未知",
    },
    "design_type": {
        "ordinary": "普通型", "participating": "分红型", "universal": "万能型",
        "unit_linked": "投资连结型", "not_applicable": "不适用", "unknown": "未知",
    },
    "term_class": {"long_term": "长期", "short_term": "短期", "unknown": "未知"},
    "health_term_class": {"long_health": "长期健康保险", "short_health": "短期健康保险", "unknown": "未知"},
    "customer_scope": {"individual": "个人", "group": "团体", "unknown": "未知"},
    "contract_role": {"main": "主险", "rider": "附加险", "unknown": "未知"},
    "renewal_type": {"none": "无续保", "non_guaranteed": "不保证续保", "guaranteed": "保证续保", "unknown": "未知"},
}


class ClauseTopic(str, Enum):
    CONTRACT_NAME = "contract.name"
    CONTRACT_DEFINITION = "contract.definition"
    CONTRACT_PARTY = "contract.party"
    CONTRACT_FORMATION = "contract.formation"
    CONTRACT_EFFECTIVE = "contract.effective"
    CONTRACT_CHANGE = "contract.change"
    CONTRACT_TERMINATION = "contract.termination"
    CONTRACT_REINSTATEMENT = "contract.reinstatement"
    CONTRACT_DISPUTE = "contract.dispute"
    CONTRACT_LIMITATION = "contract.limitation"
    APPLICATION_ELIGIBILITY = "application.eligibility"
    APPLICATION_AGE = "application.age"
    APPLICATION_DISCLOSURE = "application.disclosure"
    APPLICATION_UNDERWRITING = "application.underwriting"
    APPLICATION_HESITATION = "application.hesitation"
    COVERAGE_RESPONSIBILITY = "coverage.responsibility"
    COVERAGE_EXCLUSION = "coverage.exclusion"
    COVERAGE_PERIOD = "coverage.period"
    COVERAGE_AMOUNT = "coverage.amount"
    COVERAGE_WAITING_PERIOD = "coverage.waiting_period"
    COVERAGE_PREEXISTING = "coverage.preexisting"
    COVERAGE_DEATH = "coverage.death"
    COVERAGE_SURVIVAL = "coverage.survival"
    COVERAGE_DISABILITY = "coverage.disability"
    COVERAGE_DISEASE = "coverage.disease"
    COVERAGE_MEDICAL = "coverage.medical"
    COVERAGE_NURSING = "coverage.nursing"
    COVERAGE_DEDUCTIBLE = "coverage.deductible"
    COVERAGE_PAYMENT_RATIO = "coverage.payment_ratio"
    COVERAGE_PAYMENT_LIMIT = "coverage.payment_limit"
    PREMIUM_AMOUNT = "premium.amount"
    PREMIUM_PAYMENT = "premium.payment"
    PREMIUM_GRACE_PERIOD = "premium.grace_period"
    PREMIUM_AUTO_ADVANCE = "premium.auto_advance"
    PREMIUM_RATE = "premium.rate"
    PREMIUM_RATE_ADJUSTMENT = "premium.rate_adjustment"
    RENEWAL_GENERAL = "renewal.general"
    RENEWAL_GUARANTEED = "renewal.guaranteed"
    RENEWAL_NON_GUARANTEED = "renewal.non_guaranteed"
    RENEWAL_REAPPLICATION = "renewal.reapplication"
    RENEWAL_TERMINATION = "renewal.termination"
    CLAIM_NOTIFICATION = "claim.notification"
    CLAIM_APPLICATION = "claim.application"
    CLAIM_MATERIAL = "claim.material"
    CLAIM_ASSESSMENT = "claim.assessment"
    CLAIM_PAYMENT = "claim.payment"
    CLAIM_MEDICAL_INSTITUTION = "claim.medical_institution"
    CLAIM_COMPENSATION_ORDER = "claim.compensation_order"
    POLICY_CASH_VALUE = "policy.cash_value"
    POLICY_LOAN = "policy.loan"
    POLICY_REDUCTION = "policy.reduction"
    POLICY_ASSIGNMENT = "policy.assignment"
    POLICY_BENEFICIARY = "policy.beneficiary"
    POLICY_DIVIDEND = "policy.dividend"
    POLICY_ACCOUNT_VALUE = "policy.account_value"
    DISCLOSURE_READING_GUIDE = "disclosure.reading_guide"
    DISCLOSURE_PROMINENT_NOTICE = "disclosure.prominent_notice"
    DISCLOSURE_EXEMPTION_NOTICE = "disclosure.exemption_notice"
    DISCLOSURE_RISK_NOTICE = "disclosure.risk_notice"


@dataclass(frozen=True)
class TagEvidence:
    """记录标签的取值依据，避免自动推断成为不可解释的事实。"""
    field_name: str
    value: str
    source: str
    evidence: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "field_name": self.field_name,
            "value": self.value,
            "source": self.source,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }
        return result


@dataclass(frozen=True)
class TermOption:
    kind: str
    value: Optional[float] = None
    unit: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "value": self.value, "unit": self.unit}


@dataclass(frozen=True)
class ProductTags:
    line: ProductLine = ProductLine.UNKNOWN
    primary_subtype: ProductSubtype = ProductSubtype.UNKNOWN
    design_type: ProductDesignType = ProductDesignType.UNKNOWN
    term_class: ProductTermClass = ProductTermClass.UNKNOWN
    term_forms: Tuple[ProductTermForm, ...] = ()
    term_options: Tuple[TermOption, ...] = ()
    health_term_class: HealthTermClass = HealthTermClass.UNKNOWN
    customer_scope: CustomerScope = CustomerScope.UNKNOWN
    contract_role: ContractRole = ContractRole.UNKNOWN
    premium_pattern: PremiumPattern = PremiumPattern.UNKNOWN
    renewal_type: RenewalType = RenewalType.UNKNOWN
    is_internet_exclusive: Optional[bool] = None
    is_rate_adjustable: Optional[bool] = None
    is_tax_advantaged_health: Optional[bool] = None
    is_city_customized_medical: Optional[bool] = None
    coverage_components: Tuple[str, ...] = ()
    medical_benefit_basis: MedicalBenefitBasis = MedicalBenefitBasis.UNKNOWN
    disease_payment_pattern: DiseasePaymentPattern = DiseasePaymentPattern.UNKNOWN
    has_cash_value: Optional[bool] = None
    policy_rights: Tuple[str, ...] = ()
    insured_age_min: Optional[float] = None
    insured_age_max: Optional[float] = None
    insured_populations: Tuple[str, ...] = ()
    has_waiting_period: Optional[bool] = None
    has_hesitation_period: Optional[bool] = None
    deductible_types: Tuple[str, ...] = ()
    health_management_service: str = "unknown"
    evidence: Tuple[TagEvidence, ...] = ()
    warnings: Tuple[str, ...] = ()

    @property
    def multiple_health_coverages(self) -> bool:
        health_components = {
            "disease", "critical_illness", "medical", "accidental_medical",
            "disability_income", "nursing",
        }
        return len(health_components.intersection(self.coverage_components)) > 1

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "line": self.line.value,
            "primary_subtype": self.primary_subtype.value,
            "design_type": self.design_type.value,
            "term_class": self.term_class.value,
            "term_forms": [item.value for item in self.term_forms],
            "term_options": [item.to_dict() for item in self.term_options],
            "health_term_class": self.health_term_class.value,
            "customer_scope": self.customer_scope.value,
            "contract_role": self.contract_role.value,
            "premium_pattern": self.premium_pattern.value,
            "renewal_type": self.renewal_type.value,
            "is_internet_exclusive": self.is_internet_exclusive,
            "is_rate_adjustable": self.is_rate_adjustable,
            "is_tax_advantaged_health": self.is_tax_advantaged_health,
            "is_city_customized_medical": self.is_city_customized_medical,
            "coverage_components": list(self.coverage_components),
            "multiple_health_coverages": self.multiple_health_coverages,
            "medical_benefit_basis": self.medical_benefit_basis.value,
            "disease_payment_pattern": self.disease_payment_pattern.value,
            "has_cash_value": self.has_cash_value,
            "policy_rights": list(self.policy_rights),
            "insured_age": {"minimum": self.insured_age_min, "maximum": self.insured_age_max, "unit": "year"},
            "insured_populations": list(self.insured_populations),
            "has_waiting_period": self.has_waiting_period,
            "has_hesitation_period": self.has_hesitation_period,
            "deductible_types": list(self.deductible_types),
            "health_management_service": self.health_management_service,
            "evidence": [item.to_dict() for item in self.evidence],
            "warnings": list(self.warnings),
        }
        result["display_labels"] = {
            field_name: labels.get(str(result[field_name]), str(result[field_name]))
            for field_name, labels in PRODUCT_TAG_LABELS.items()
        }
        return result
