# 文档预处理和审核系统设计

## 概述

设计独立的文档预处理和审核系统，通过包级别隔离实现模块解耦，与现有 RAG 引擎集成。

## 目标

1. **模块隔离**：预处理和审核通过独立的 package 隔离，而非文件名
2. **Prompt 管理**：每个模块有独立的 prompts.py
3. **异步解耦**：预处理和审核可独立运行
4. **RAG 集成**：通过增强 LanceDB 元数据与现有 RAG 集成
5. **业务语义命名**：使用领域特定的类名和枚举

## 架构

### 整体结构

```
scripts/lib/
├── common/                          # 公共可复用层
│   ├── __init__.py
│   └── models.py                    # 共享数据模型
├── preprocessing/                   # 预处理包
│   ├── __init__.py
│   ├── prompts.py                   # 预处理 Prompt 模板
│   ├── cleaner.py                   # 文档清洗
│   └── extractor.py                 # 结构化信息提取
└── audit/                           # 审核包
    ├── __init__.py
    ├── prompts.py                   # 审核 Prompt 模板
    └── auditor.py                   # 合规审核
```

### 数据流

```
原始文档 (Markdown)
    │
    ▼
┌─────────────────────┐
│  DocumentCleaner    │ → 清洗后内容
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ InformationExtractor│ → RegulationRecord (结构化信息)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  LanceDB Metadata   │ → 增强向量数据库元数据
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│    ComplianceAuditor│ → 审核报告
└─────────────────────┘
```

## Part 1: 公共可复用层

### models.py

```python
# scripts/lib/common/models.py

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class RegulationStatus(str, Enum):
    """法规处理状态"""
    RAW = "raw"                      # 原始文档
    CLEANED = "cleaned"              # 已清洗
    EXTRACTED = "extracted"          # 已提取结构化信息
    AUDITED = "audited"              # 已审核
    FAILED = "failed"                # 处理失败


class RegulationLevel(str, Enum):
    """法规层级"""
    LAW = "law"                                  # 法律
    DEPARTMENT_RULE = "department_rule"          # 部门规章
    NORMATIVE = "normative"                      # 规范性文件
    OTHER = "other"                              # 其他


@dataclass
class RegulationRecord:
    """法规基本信息记录"""
    law_name: str
    article_number: str
    category: str
    effective_date: Optional[str] = None
    hierarchy_level: Optional[RegulationLevel] = None
    issuing_authority: Optional[str] = None
    status: RegulationStatus = RegulationStatus.RAW
    quality_score: Optional[float] = None


@dataclass
class ProcessingOutcome:
    """处理结果"""
    success: bool
    regulation_id: str
    record: RegulationRecord
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    processed_at: datetime = field(default_factory=datetime.now)
    processor: str = ""  # 处理器标识，如 "preprocessing" 或 "audit"


@dataclass
class RegulationDocument:
    """法规文档"""
    content: str
    source_file: str
    record: RegulationRecord
```

## Part 2: preprocessing/ 包

### prompts.py

```python
# scripts/lib/preprocessing/prompts.py

# 文档清洗提示词
CLEANING_SYSTEM_PROMPT = """你是一位保险法规文档清洗专家，负责将原始文档规范化为标准格式。

【任务】
清理和规范化法规文档内容，保持法条原意不变。

【清洗规则】
1. 条款编号规范化：
   - 统一使用中文数字：第十六条、第十七条
   - 去除多余空格和换行
   - 识别并列条款（如（一）（二）、1. 2.）

2. 文本清理：
   - 去除图片链接（如 ![]()、<img>）
   - 去除HTML标签
   - 统一换行符（使用 \\n\\n 分隔条款）
   - 去除重复内容

3. 结构保持：
   - 保持法条的层级结构（章、节、条）
   - 保持法条的完整语义
   - 标记无法识别的内容

【输出格式】
仅返回清洗后的纯文本内容，不添加任何解释或注释。"""

# 结构化信息提取提示词
EXTRACTION_SYSTEM_PROMPT = """你是一位保险法规信息提取专家，负责从法规文档中提取结构化信息。

【任务】
从法规文档中提取关键信息，输出为 JSON 格式。

【提取字段】
- law_name: 法规/文件全称
- effective_date: 生效日期（YYYY-MM-DD 格式，无法确定时返回 null）
- hierarchy_level: 法规层级（law/department_rule/normative/other）
- issuing_authority: 发布机关（如"中国银保监会"）
- category: 法规分类（如"健康保险"、"产品管理"、"信息披露"等）

【层级判断规则】
- law: 包含"法"字且由全国人大及其常委会制定（如《中华人民共和国保险法》）
- department_rule: 部门规章，包含"办法"、"规定"、"细则"等
- normative: 规范性文件，包含"通知"、"指引"、"意见"、"批复"等
- other: 其他情况

【输出格式】
严格按照以下 JSON 格式输出，不添加任何其他内容：
```json
{
  "law_name": "法规全称",
  "effective_date": "YYYY-MM-DD 或 null",
  "hierarchy_level": "law|department_rule|normative|other",
  "issuing_authority": "发布机关",
  "category": "分类"
}
```

如果无法确定某个字段值，返回 null。"""

# 完整性检查提示词
COMPLETENESS_CHECK_PROMPT = """请检查以下法规文档的信息完整性。

【文档内容】
{content}

【检查要点】
1. 法规名称是否完整
2. 是否包含明确的生效日期
3. 发布机关是否明确
4. 法规层级是否清晰
5. 条款内容是否完整（无截断、无缺失）

请返回检查结果：
```json
{{
  "is_complete": true|false,
  "issues": ["问题1", "问题2"],
  "quality_score": 0.0-1.0
}}
```
"""
```

### cleaner.py

```python
# scripts/lib/preprocessing/cleaner.py

from typing import Dict, List, Optional
import re
import logging
from lib.common.models import RegulationDocument, RegulationRecord, RegulationStatus, ProcessingOutcome
from lib.llm_client import BaseLLMClient, LLMClientFactory

logger = logging.getLogger(__name__)


class DocumentCleaner:
    """文档清洗器 - 负责清洗和规范化法规文档"""

    def __init__(self, llm_client: BaseLLMClient = None):
        """
        Args:
            llm_client: LLM 客户端，默认使用 QA 模型
        """
        self.llm_client = llm_client or LLMClientFactory.get_qa_llm()

    def clean(
        self,
        content: str,
        source_file: str,
        record: RegulationRecord
    ) -> ProcessingOutcome:
        """
        清洗文档内容

        Args:
            content: 原始文档内容
            source_file: 来源文件路径
            record: 法规记录

        Returns:
            ProcessingOutcome: 清洗结果，包含清洗后的内容
        """
        try:
            # 规则清洗（快速）
            rule_cleaned = self._rule_based_clean(content)

            # LLM 验证和补充
            llm_cleaned = self._llm_assisted_clean(rule_cleaned)

            # 更新记录状态
            record.status = RegulationStatus.CLEANED

            return ProcessingOutcome(
                success=True,
                regulation_id=self._generate_regulation_id(record),
                record=record,
                errors=[],
                warnings=[],
                processor="preprocessing.cleaner"
            )

        except Exception as e:
            logger.error(f"文档清洗失败: {e}")
            record.status = RegulationStatus.FAILED
            return ProcessingOutcome(
                success=False,
                regulation_id="",
                record=record,
                errors=[str(e)],
                warnings=[],
                processor="preprocessing.cleaner"
            )

    def _rule_based_clean(self, content: str) -> str:
        """基于规则的快速清洗"""
        # 去除图片链接
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
        content = re.sub(r'<img[^>]*>', '', content)

        # 去除 HTML 标签
        content = re.sub(r'<[^>]+>', '', content)

        # 统一换行符
        content = re.sub(r'\r\n', '\n', content)

        # 去除多余空行
        content = re.sub(r'\n{3,}', '\n\n', content)

        return content.strip()

    def _llm_assisted_clean(self, content: str) -> str:
        """使用 LLM 辅助清洗"""
        from .prompts import CLEANING_SYSTEM_PROMPT

        messages = [
            {'role': 'system', 'content': CLEANING_SYSTEM_PROMPT},
            {'role': 'user', 'content': content}
        ]

        try:
            cleaned = self.llm_client.chat(messages)
            return cleaned.strip()
        except Exception as e:
            logger.warning(f"LLM 清洗失败，使用规则清洗结果: {e}")
            return content

    def _generate_regulation_id(self, record: RegulationRecord) -> str:
        """生成法规唯一标识"""
        import hashlib
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
```

### extractor.py

```python
# scripts/lib/preprocessing/extractor.py

from typing import Dict, List, Optional
import json
import logging
from lib.common.models import RegulationRecord, RegulationStatus, ProcessingOutcome
from lib.llm_client import BaseLLMClient, LLMClientFactory

logger = logging.getLogger(__name__)


class InformationExtractor:
    """结构化信息提取器"""

    def __init__(self, llm_client: BaseLLMClient = None):
        """
        Args:
            llm_client: LLM 客户端，默认使用 QA 模型
        """
        self.llm_client = llm_client or LLMClientFactory.get_qa_llm()

    def extract(
        self,
        content: str,
        record: RegulationRecord
    ) -> ProcessingOutcome:
        """
        从文档内容提取结构化信息

        Args:
            content: 清洗后的文档内容
            record: 法规记录（会更新提取到的信息）

        Returns:
            ProcessingOutcome: 提取结果
        """
        try:
            extracted_info = self._extract_with_llm(content)

            # 更新记录
            if extracted_info.get('law_name'):
                record.law_name = extracted_info['law_name']
            if extracted_info.get('effective_date'):
                record.effective_date = extracted_info['effective_date']
            if extracted_info.get('hierarchy_level'):
                from lib.common.models import RegulationLevel
                record.hierarchy_level = RegulationLevel(extracted_info['hierarchy_level'])
            if extracted_info.get('issuing_authority'):
                record.issuing_authority = extracted_info['issuing_authority']
            if extracted_info.get('category'):
                record.category = extracted_info['category']

            # 质量检查
            quality_result = self._check_completeness(content, record)
            record.quality_score = quality_result.get('quality_score', 0.5)
            record.status = RegulationStatus.EXTRACTED

            return ProcessingOutcome(
                success=True,
                regulation_id=self._generate_regulation_id(record),
                record=record,
                errors=[],
                warnings=quality_result.get('issues', []),
                processor="preprocessing.extractor"
            )

        except Exception as e:
            logger.error(f"信息提取失败: {e}")
            record.status = RegulationStatus.FAILED
            return ProcessingOutcome(
                success=False,
                regulation_id="",
                record=record,
                errors=[str(e)],
                warnings=[],
                processor="preprocessing.extractor"
            )

    def _extract_with_llm(self, content: str) -> Dict[str, Optional[str]]:
        """使用 LLM 提取结构化信息"""
        from .prompts import EXTRACTION_SYSTEM_PROMPT

        messages = [
            {'role': 'system', 'content': EXTRACTION_SYSTEM_PROMPT},
            {'role': 'user', 'content': content[:5000]}  # 限制长度
        ]

        try:
            response = self.llm_client.chat(messages)
            # 解析 JSON
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"LLM 提取失败: {e}")
            return {}

    def _check_completeness(self, content: str, record: RegulationRecord) -> Dict:
        """检查文档完整性"""
        from .prompts import COMPLETENESS_CHECK_PROMPT

        prompt = COMPLETENESS_CHECK_PROMPT.format(content=content[:3000])

        messages = [
            {'role': 'user', 'content': prompt}
        ]

        try:
            response = self.llm_client.chat(messages)
            return json.loads(response)
        except Exception as e:
            logger.warning(f"完整性检查失败: {e}")
            return {'is_complete': True, 'issues': [], 'quality_score': 0.5}

    def _generate_regulation_id(self, record: RegulationRecord) -> str:
        """生成法规唯一标识"""
        import hashlib
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
```

### __init__.py

```python
# scripts/lib/preprocessing/__init__.py

from .cleaner import DocumentCleaner
from .extractor import InformationExtractor

__all__ = ['DocumentCleaner', 'InformationExtractor']
```

## Part 3: audit/ 包

### prompts.py

```python
# scripts/lib/audit/prompts.py

# 合规审核提示词
AUDIT_SYSTEM_PROMPT = """你是一位保险产品合规审核专家，负责根据监管规定审核保险产品条款。

【审核标准】
1. 条款合规性：是否符合相关法律法规
2. 信息披露：是否充分披露产品信息
3. 条款清晰度：条款表述是否清晰易懂
4. 费率合理性：费率制定是否符合规定

【审核输出】
对每个条款进行审核，输出：
- 合规问题（如有）
- 风险等级（high/medium/low）
- 改进建议

严格按照以下 JSON 格式输出：
```json
{{
  "overall_assessment": "通过/有条件通过/不通过",
  "issues": [
    {{
      "clause": "条款内容摘要",
      "severity": "high/medium/low",
      "regulation": "违反的法规名称和条款号",
      "description": "问题描述",
      "suggestion": "改进建议"
    }}
  ],
  "score": 0-100,
  "summary": "审核总结"
}}
```
"""

# 条款对比提示词
CLAUSE_COMPARISON_PROMPT = """请对比以下产品条款与监管规定的差异。

【产品条款】
{product_clause}

【监管规定】
{regulation_content}

【对比维度】
1. 内容一致性
2. 覆盖完整性
3. 表述准确性

请返回对比结果：
```json
{{
  "is_compliant": true|false,
  "differences": ["差异1", "差异2"],
  "missing_points": ["缺失点1", "缺失点2"],
  "risk_level": "high/medium/low"
}}
```
"""
```

### auditor.py

```python
# scripts/lib/audit/auditor.py

from typing import Dict, List, Optional
import json
import logging
from lib.common.models import RegulationRecord, ProcessingOutcome
from lib.llm_client import BaseLLMClient, LLMClientFactory

logger = logging.getLogger(__name__)


@dataclass
class AuditIssue:
    """单个审核问题"""
    clause: str
    severity: str  # high/medium/low
    regulation: str
    description: str
    suggestion: str


@dataclass
class AuditReport:
    """审核报告"""
    overall_assessment: str  # 通过/有条件通过/不通过
    issues: List[AuditIssue]
    score: int  # 0-100
    summary: str


class ComplianceAuditor:
    """合规审核器"""

    def __init__(self, llm_client: BaseLLMClient = None):
        """
        Args:
            llm_client: LLM 客户端，默认使用 Audit 模型（更高质量）
        """
        self.llm_client = llm_client or LLMClientFactory.get_audit_llm()

    def audit(
        self,
        product_clause: str,
        regulation_record: RegulationRecord,
        regulation_content: str
    ) -> ProcessingOutcome:
        """
        审核产品条款是否符合监管规定

        Args:
            product_clause: 产品条款内容
            regulation_record: 相关法规记录
            regulation_content: 法规内容

        Returns:
            ProcessingOutcome: 审核结果
        """
        try:
            # 使用 LLM 进行合规审核
            audit_result = self._llm_audit(product_clause, regulation_content)

            # 更新记录状态
            regulation_record.status = RegulationStatus.AUDITED

            return ProcessingOutcome(
                success=True,
                regulation_id=self._generate_regulation_id(regulation_record),
                record=regulation_record,
                errors=[],
                warnings=[],
                processor="audit.auditor"
            )

        except Exception as e:
            logger.error(f"合规审核失败: {e}")
            regulation_record.status = RegulationStatus.FAILED
            return ProcessingOutcome(
                success=False,
                regulation_id="",
                record=regulation_record,
                errors=[str(e)],
                warnings=[],
                processor="audit.auditor"
            )

    def _llm_audit(self, product_clause: str, regulation_content: str) -> AuditReport:
        """使用 LLM 进行合规审核"""
        from .prompts import AUDIT_SYSTEM_PROMPT

        prompt = f"""请审核以下产品条款：

【产品条款】
{product_clause}

【相关监管规定】
{regulation_content}
"""

        messages = [
            {'role': 'system', 'content': AUDIT_SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt}
        ]

        try:
            response = self.llm_client.chat(messages)
            result = json.loads(response)

            issues = [
                AuditIssue(**issue) for issue in result.get('issues', [])
            ]

            return AuditReport(
                overall_assessment=result.get('overall_assessment', '不通过'),
                issues=issues,
                score=result.get('score', 0),
                summary=result.get('summary', '')
            )
        except Exception as e:
            logger.error(f"LLM 审核失败: {e}")
            return AuditReport(
                overall_assessment='不通过',
                issues=[],
                score=0,
                summary=f'审核失败: {str(e)}'
            )

    def compare_clauses(
        self,
        product_clause: str,
        regulation_content: str
    ) -> Dict:
        """对比产品条款与监管规定"""
        from .prompts import CLAUSE_COMPARISON_PROMPT

        prompt = CLAUSE_COMPARISON_PROMPT.format(
            product_clause=product_clause,
            regulation_content=regulation_content
        )

        messages = [
            {'role': 'user', 'content': prompt}
        ]

        try:
            response = self.llm_client.chat(messages)
            return json.loads(response)
        except Exception as e:
            logger.error(f"条款对比失败: {e}")
            return {
                'is_compliant': False,
                'differences': [str(e)],
                'missing_points': [],
                'risk_level': 'high'
            }

    def _generate_regulation_id(self, record: RegulationRecord) -> str:
        """生成法规唯一标识"""
        import hashlib
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
```

### __init__.py

```python
# scripts/lib/audit/__init__.py

from .auditor import ComplianceAuditor, AuditIssue, AuditReport

__all__ = ['ComplianceAuditor', 'AuditIssue', 'AuditReport']
```

## Part 4: RAG 集成

### LanceDB 元数据增强

在文档导入时，将预处理提取的结构化信息作为元数据存储到 LanceDB：

```python
# 在 rag_engine/data_importer.py 中增强

from lib.preprocessing import DocumentCleaner, InformationExtractor
from lib.common.models import RegulationRecord, RegulationLevel, RegulationStatus

def import_with_enhanced_metadata(file_path: str) -> None:
    """导入文档并增强元数据"""
    # 1. 读取原始内容
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 2. 创建初始记录
    record = RegulationRecord(
        law_name="",
        article_number="",
        category="未分类",
        status=RegulationStatus.RAW
    )

    # 3. 清洗文档
    cleaner = DocumentCleaner()
    clean_result = cleaner.clean(content, file_path, record)

    if not clean_result.success:
        logger.error(f"文档清洗失败: {clean_result.errors}")
        return

    # 4. 提取结构化信息
    extractor = InformationExtractor()
    extract_result = extractor.extract(content, record)

    if not extract_result.success:
        logger.warning(f"信息提取失败: {extract_result.errors}")

    # 5. 构建增强元数据
    enhanced_metadata = {
        'law_name': record.law_name,
        'article_number': record.article_number,
        'category': record.category,
        'effective_date': record.effective_date,
        'hierarchy_level': record.hierarchy_level.value if record.hierarchy_level else None,
        'issuing_authority': record.issuing_authority,
        'status': record.status.value,
        'quality_score': record.quality_score
    }

    # 6. 导入到 LanceDB（使用现有导入逻辑）
    # ... 调用现有的 data_importer 逻辑，传入增强元数据
```

### 元数据过滤

使用增强元数据进行精确检索：

```python
# 在 rag_engine/rag_engine.py 中利用增强元数据

def search_by_metadata(
    self,
    query: str,
    law_name: str = None,
    category: str = None,
    hierarchy_level: str = None,
    issuing_authority: str = None
) -> List[Dict]:
    """使用增强元数据进行检索"""
    filters = {}
    if law_name:
        filters['law_name'] = law_name
    if category:
        filters['category'] = category
    if hierarchy_level:
        filters['hierarchy_level'] = hierarchy_level
    if issuing_authority:
        filters['issuing_authority'] = issuing_authority

    return self.search(query, filters=filters)
```

## 分阶段实施

### Phase 1: 核心功能（当前实现）

1. 创建 common/models.py - 共享数据模型
2. 创建 preprocessing/ 包 - 文档清洗和结构化信息提取
3. 创建 audit/ 包 - 基础合规审核框架
4. LanceDB 元数据增强集成

### Phase 2: 扩展功能（未来）

1. 完整的 ComplianceAuditor 实现
2. 审核报告生成
3. 批量处理支持
4. 审核日志和追溯

## 配置管理

扩展现有 config.py 添加预处理和审核配置：

```python
# scripts/lib/config.py 新增

class PreprocessingConfig:
    """预处理配置"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('preprocessing', {})

    @property
    def enable_llm_cleaning(self) -> bool:
        """是否启用 LLM 辅助清洗"""
        return self._config.get('enable_llm_cleaning', True)

    @property
    def max_content_length(self) -> int:
        """LLM 处理的最大内容长度"""
        return self._config.get('max_content_length', 5000)

    @property
    def quality_threshold(self) -> float:
        """质量分数阈值"""
        return self._config.get('quality_threshold', 0.6)


class AuditConfig:
    """审核配置（更新现有类）"""

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('audit', {})

    # ... 现有属性 ...

    @property
    def enable_detailed_audit(self) -> bool:
        """是否启用详细审核"""
        return self._config.get('enable_detailed_audit', True)

    @property
    def max_comparison_length(self) -> int:
        """条款对比最大长度"""
        return self._config.get('max_comparison_length', 3000)
```

## 错误处理

| 场景 | 处理方式 | 日志级别 |
|------|----------|----------|
| 文档清洗失败 | 标记 FAILED，返回错误 | ERROR |
| 信息提取失败 | 标记 FAILED，返回错误 | ERROR |
| LLM JSON 解析失败 | 使用默认值，记录警告 | WARNING |
| 质量检查失败 | 使用默认质量分，记录警告 | WARNING |
| 审核失败 | 标记 FAILED，返回错误 | ERROR |

## 测试计划

### 单元测试

1. **common/models.py**
   - 测试枚举值
   - 测试 dataclass 验证

2. **preprocessing/cleaner.py**
   - 测试规则清洗
   - Mock LLM 响应

3. **preprocessing/extractor.py**
   - 测试信息提取
   - 测试完整性检查

4. **audit/auditor.py**
   - 测试合规审核
   - 测试条款对比

### 集成测试

1. 完整预处理流程
2. LanceDB 元数据增强
3. 元数据过滤检索
4. 审核流程集成

## 命名约定总结

| 旧名称 | 新名称 | 说明 |
|--------|--------|------|
| DocumentMetadata | RegulationRecord | 法规记录 |
| DocumentStatus | RegulationStatus | 法规处理状态 |
| ProcessResult | ProcessingOutcome | 处理结果 |
| BaseDocument | RegulationDocument | 法规文档 |
| HierarchyLevel | RegulationLevel | 法规层级 |

避免使用 "info" 和 "metadata" 等通用名称，使用业务语义明确的命名。
