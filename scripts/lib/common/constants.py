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
    SCORE_BASE = 100
    DEFAULT_EXCELLENT_THRESHOLD = 90
    DEFAULT_GOOD_THRESHOLD = 75
    DEFAULT_PASS_THRESHOLD = 60
    DEFAULT_GRADE = "不合格"

    SEVERITY_PENALTY_CRITICAL = 40
    SEVERITY_PENALTY_HIGH = 20
    SEVERITY_PENALTY_MEDIUM = 10
    SEVERITY_PENALTY_LOW = 5
    PRICING_ISSUE_PENALTY = 10


class ViolationConstants:
    """违规常量"""
    SEVERITY_HIGH = "high"
    SEVERITY_MEDIUM = "medium"
    SEVERITY_LOW = "low"

    DIMENSION_COMPLIANCE = "合规性"
    DIMENSION_DISCLOSURE = "信息披露"
    DIMENSION_CLARITY = "条款清晰度"
    DIMENSION_PRICING = "费率合理性"


class PreprocessingConstants:
    """文档预处理常量"""

    # 分块配置
    DEFAULT_CHUNK_SIZE = 6000
    DEFAULT_OVERLAP = 1500
    DEFAULT_CHUNK_THRESHOLD = 10000
    DEFAULT_MAX_CONCURRENT = 1

    # 模型并发数推荐
    MODEL_CONCURRENT_MAP = {
        'glm-4-flash': 5,
        'glm-4-air': 3,
        'glm-4-plus': 2,
    }

    # LLM 调用限流配置
    LLM_TARGET_QPS = 1.0
    LLM_MAX_RETRIES = 2
    LLM_RETRY_BASE_DELAY = 2.0
    LLM_RETRY_MAX_DELAY = 60.0

    # 文档长度限制
    MAX_DOCUMENT_LENGTH = 12000
    MIN_DOCUMENT_LENGTH = 100

    # LLM 配置
    LLM_MAX_TOKENS = 16384
    LLM_DEFAULT_CONFIDENCE = 0.75

    # 分块策略配置
    TABLE_DENSITY_THRESHOLD = 0.5
    DENSITY_CALCULATION_MULTIPLIER = 1000

    # 质量评估权重
    QUALITY_WEIGHTS = {
        'completeness': 0.40,
        'accuracy': 0.35,
        'consistency': 0.15,
        'reasonableness': 0.10,
    }

    # 去重参数
    DEDUP_PREFIX_LENGTH = 200
    DEDUP_SUFFIX_LENGTH = 100

    # 分块策略阈值
    SECTION_MIN_COUNT = 5
