"""应用常量定义"""

from typing import Dict, List


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

    # 文档长度限制
    MAX_DOCUMENT_LENGTH = 12000
    MIN_DOCUMENT_LENGTH = 100


class LLMConstants:
    """LLM 调用配置"""

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 5.0
    RATE_LIMIT_DELAY_MULT = 3
    RETRY_MAX_DELAY = 60.0

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


class ComplianceConstants:
    """合规检查常量"""

    VALID_CATEGORIES: List[str] = ["健康险", "医疗险", "重疾险", "寿险", "意外险", "年金险", "财产险"]

    CATEGORY_REGULATION_REGISTRY: Dict[str, List[str]] = {
        "健康险": [
            "《健康保险管理办法》2019年第3号",
            "中国银保监会办公厅关于规范短期健康保险业务有关问题的通知（银保监办发〔2021〕7号）、关于短期健康险续保表述备案事项的通知（电子报备系统通知公告2021-4-22）",
            "关于健康保险产品等待期及既往症表述有关事项的通知（电子报备系统通知公告2022-7-27）",
        ],
        "医疗险": [
            "《健康保险管理办法》2019年第3号",
            "中国银保监会办公厅《关于长期医疗保险产品费率调整有关问题的通知》（银保监办发〔2020〕27号）",
        ],
        "重疾险": [
            "重大疾病保险的疾病定义使用规范（2020年修订版）",
            "中国银保监会办公厅关于使用重大疾病保险的疾病定义有关事项的通知（银保监办便函〔2020〕1452号）",
            "《健康保险管理办法》2019年第3号",
        ],
        "寿险": [
            "中国银保监会办公厅关于印发普通型人身保险精算规定的通知（银保监办发〔2020〕7号）",
            "《人身保险公司保险条款和保险费率管理办法（2015年修订）》（2015年第3号）",
        ],
        "意外险": [
            "中国银保监会办公厅关于 印发意外伤害保险业务监管办法的通知(银保监办发〔2021〕106号)",
            "关于发布《中国保险业意外伤害经验发生率表（2021）》的通知（中精协发〔2021〕14号）",
        ],
    }

    GENERAL_REGULATIONS: List[str] = [
        "中华人民共和国保险法（2015年修订版）",
        "《人身保险公司保险条款和保险费率管理办法（2015年修订）》（2015年第3号）",
        "中国银保监会办公厅关于印发普通型人身保险精算规定的通知（银保监办发〔2020〕7号）",
        "中国银保监会办公厅关于强化人身保险精算监管有关事项的通知（银保监办发〔2020〕6号）",
    ]

    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".docx"]
