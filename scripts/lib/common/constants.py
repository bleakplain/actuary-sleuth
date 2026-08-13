"""应用常量定义"""

from typing import Dict, List, Tuple


class CoverageFactKeys:
    """可由完整正文零命中证明为假的稳定事实键。"""

    RENEWAL_TEXT = "renewal_text"
    TAX_ADVANTAGED_TEXT = "tax_advantaged_text"
    OUT_OF_HOSPITAL_DRUG_TEXT = "out_of_hospital_drug_text"
    CRITICAL_ILLNESS_TERM_TEXT = "critical_illness_term_text"
    INCREASING_SUM_ASSURED_TEXT = "increasing_sum_assured_text"
    ALL: Tuple[str, ...] = (
        RENEWAL_TEXT,
        TAX_ADVANTAGED_TEXT,
        OUT_OF_HOSPITAL_DRUG_TEXT,
        CRITICAL_ILLNESS_TERM_TEXT,
        INCREASING_SUM_ASSURED_TEXT,
    )


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

    EVALUATION_DATASET_VERSION = "compliance-audit-v1"
    REGULATION_TRIGGER_SCHEMA_VERSION = "1.0.0"
    REGULATION_TRIGGER_EXCLUSION_MODE = "shadow"
    EVALUATION_DATASET_STATUS = "pending"
    CUTOVER_GATE_STATUS = "blocked"
    APPROVED_REGULATION_TRIGGER_SOURCE_SHA256 = ""
    APPROVED_REGULATION_TRIGGER_CATALOG_SHA256 = ""
    AUDIT_TOTAL_DEADLINE_SECONDS = 300.0
    AUDIT_FACT_RESOLUTION_MAX_SECONDS = 45.0
    AUDIT_REPORT_PERSISTENCE_RESERVE_SECONDS = 5.0
    AUDIT_MAX_CONCURRENCY = 5
    MAX_PRODUCT_DOCUMENT_BYTES = 25 * 1024 * 1024
    MAX_RICH_TEXT_CHARACTERS = 5_000_000
    VALID_CATEGORIES: List[str] = ["健康险", "医疗险", "重疾险", "寿险", "意外险", "年金险", "财产险", "分红险"]

    # ProductCategory 枚举值 → 合规检查险种类别（子类别归入大类）
    SUBCATEGORY_MAPPING: Dict[str, str] = {
        "寿险": "寿险",
        "健康险": "健康险",
        "重疾险": "重疾险",
        "医疗险": "医疗险",
        "意外险": "意外险",
        "年金险": "年金险",
        "分红险": "分红险",
        "车险": "财产险",
        "财产险": "财产险",
        "养老险": "年金险",
        "教育险": "年金险",
        "旅游险": "意外险",
    }
    CATEGORY_PARENT_MAPPING: Dict[str, str] = {
        "医疗险": "健康险",
        "重疾险": "健康险",
        "年金险": "寿险",
        "分红险": "寿险",
    }

    CATEGORY_REGULATION_REGISTRY: Dict[str, List[str]] = {
        "健康险": [
            "《健康保险管理办法》2019年第3号",
            "中国银保监会办公厅关于规范短期健康保险业务有关问题的通知（银保监办发〔2021〕7号）、关于短期健康险续保表述备案事项的通知（电子报备系统通知公告2021-4-22）",
            "关于健康保险产品等待期及既往症表述有关事项的通知（电子报备系统通知公告2022-7-27）",
            "关于报备提供健康管理服务产品注意事项的通知（电子报备系统通知公告2021-3-23）",
        ],
        "医疗险": [
            "《健康保险管理办法》2019年第3号",
            "中国银保监会办公厅《关于长期医疗保险产品费率调整有关问题的通知》（银保监办发〔2020〕27号）",
            "关于报备提供健康管理服务产品注意事项的通知（电子报备系统通知公告2021-3-23）",
            "关于对适用个人所得税优惠政策的商业健康保险产品有关事项的说明（电子报备系统通知公告2023-7-18）",
            "国家金融监督管理总局关于适用商业健康保险个人所得税优惠政策产品有关事项的通知（金规〔2023〕2号）",
        ],
        "重疾险": [
            "重大疾病保险的疾病定义使用规范（2020年修订版）",
            "《健康保险管理办法》2019年第3号",
            "关于新版重疾定义适用问题的通知（电子报备系统通知公告2020-11-13）",
        ],
        "寿险": [
            "中国银保监会办公厅关于印发普通型人身保险精算规定的通知（银保监办发〔2020〕7号）",
            "《人身保险公司保险条款和保险费率管理办法（2015年修订）》（2015年第3号）",
            "中国保监会《关于普通型人身保险费率政策改革有关事项的通知》（保监发〔2013〕62号）",
        ],
        "意外险": [
            "中国银保监会办公厅关于 印发意外伤害保险业务监管办法的通知(银保监办发〔2021〕106号)",
        ],
        "年金险": [
            "中国银保监会办公厅关于印发普通型人身保险精算规定的通知（银保监办发〔2020〕7号）",
            "《人身保险公司保险条款和保险费率管理办法（2015年修订）》（2015年第3号）",
            "中国保监会《关于推进分红型人身保险费率政策改革有关事项的通知》附分红险精算规定（保监发〔2015〕93号）",
        ],
        "分红险": [
            "中国保监会《关于推进分红型人身保险费率政策改革有关事项的通知》附分红险精算规定（保监发〔2015〕93号）",
        ],
    }

    GENERAL_REGULATIONS: List[str] = [
        "中华人民共和国保险法（2015年修订版）",
        "最高人民法院《关于适用〈中华人民共和国保险法〉若干问题的解释（三）》",
        "《人身保险公司保险条款和保险费率管理办法（2015年修订）》（2015年第3号）",
        "中国银保监会办公厅关于印发普通型人身保险精算规定的通知（银保监办发〔2020〕7号）",
        "人身保险产品信息披露管理办法（2022年第8号）、关于印发一年期以上人身保险产品信息披露规则的通知（银保监规〔2022〕24号）、《一年期以上人身保险产品信息披露规则》相关执行标准（电子报备系统通知公告2023-1-13）、《一年期以上人身保险产品信息披露规则》相关执行标准的补充通知（电子报备系统通知公告2023-2-20）",
        "中国保监会《关于规范人身保险公司产品开发设计行为的通知》（保监人身险〔2017〕134号）",
        "中国保监会《关于进一步完善人身保险精算制度有关事项的通知》（保监发〔2016〕76号）",
        "中国银保监会办公厅关于进一步规范保险机构互联网人身保险业务有关事项的通知（银保监办发〔2021〕108号）",
    ]

    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".doc", ".docx"]
