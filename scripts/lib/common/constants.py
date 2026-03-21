"""应用常量定义"""


class DocumentValidation:
    """文档验证常量"""
    MAX_CLAUSES_COUNT = 500
    MAX_CLAUSE_LENGTH = 10000
    MIN_CLAUSE_LENGTH = 10
    MAX_TOTAL_TEXT_LENGTH = 500000


class AuditConstants:
    """审核常量"""
    DEFAULT_TOP_K = 3
    MAX_CLAUSE_LENGTH_FOR_AUDIT = 5000
    DEFAULT_TIMEOUT = 30


class ScoringConstants:
    """评分常量"""
    DEFAULT_EXCELLENT_THRESHOLD = 90
    DEFAULT_GOOD_THRESHOLD = 75
    DEFAULT_PASS_THRESHOLD = 60
    DEFAULT_GRADE = "不合格"


class ViolationConstants:
    """违规常量"""
    SEVERITY_HIGH = "high"
    SEVERITY_MEDIUM = "medium"
    SEVERITY_LOW = "low"

    DIMENSION_COMPLIANCE = "合规性"
    DIMENSION_DISCLOSURE = "信息披露"
    DIMENSION_CLARITY = "条款清晰度"
    DIMENSION_PRICING = "费率合理性"
