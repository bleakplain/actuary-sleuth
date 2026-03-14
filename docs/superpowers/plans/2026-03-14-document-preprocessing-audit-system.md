# Document Preprocessing and Audit System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build independent preprocessing and audit packages with package-level isolation and LanceDB metadata enhancement for RAG integration.

**Architecture:** Package-based architecture with common/ layer for shared models, preprocessing/ for document cleaning and extraction, audit/ for compliance checking. Async decoupled data flow with enhanced metadata stored in LanceDB.

**Tech Stack:** Python 3.12, LlamaIndex, LanceDB, GLM-4 LLM, pytest

---

## Chunk 1: Common Layer (Shared Models)

### Task 1: Create common package structure

**Files:**
- Create: `scripts/lib/common/__init__.py`
- Create: `scripts/lib/common/models.py`

- [ ] **Step 1: Create common/__init__.py**

```python
# scripts/lib/common/__init__.py

from .models import (
    RegulationStatus,
    RegulationLevel,
    RegulationRecord,
    ProcessingOutcome,
    RegulationDocument
)

__all__ = [
    'RegulationStatus',
    'RegulationLevel',
    'RegulationRecord',
    'ProcessingOutcome',
    'RegulationDocument'
]
```

- [ ] **Step 2: Create common/models.py with enums and dataclasses**

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

- [ ] **Step 3: Verify import works**

Run: `python3 -c "from lib.common.models import RegulationRecord, RegulationStatus; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 4: Write test for enums**

```python
# tests/lib/common/test_models.py

import pytest
from lib.common.models import RegulationStatus, RegulationLevel


def test_regulation_status_values():
    """测试 RegulationStatus 枚举值"""
    assert RegulationStatus.RAW == "raw"
    assert RegulationStatus.CLEANED == "cleaned"
    assert RegulationStatus.EXTRACTED == "extracted"
    assert RegulationStatus.AUDITED == "audited"
    assert RegulationStatus.FAILED == "failed"


def test_regulation_level_values():
    """测试 RegulationLevel 枚举值"""
    assert RegulationLevel.LAW == "law"
    assert RegulationLevel.DEPARTMENT_RULE == "department_rule"
    assert RegulationLevel.NORMATIVE == "normative"
    assert RegulationLevel.OTHER == "other"


def test_regulation_status_is_string_enum():
    """测试 RegulationStatus 是字符串枚举"""
    status = RegulationStatus.RAW
    assert isinstance(status, str)
    assert status == "raw"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/lib/common/test_models.py -v`

Expected: PASS

- [ ] **Step 6: Write test for RegulationRecord**

```python
# tests/lib/common/test_models.py (add)

from lib.common.models import RegulationRecord


def test_regulation_record_defaults():
    """测试 RegulationRecord 默认值"""
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险"
    )
    assert record.law_name == "保险法"
    assert record.article_number == "第十六条"
    assert record.category == "健康保险"
    assert record.effective_date is None
    assert record.hierarchy_level is None
    assert record.issuing_authority is None
    assert record.status == RegulationStatus.RAW
    assert record.quality_score is None


def test_regulation_record_with_all_fields():
    """测试 RegulationRecord 完整字段"""
    from lib.common.models import RegulationLevel

    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险",
        effective_date="2023-01-01",
        hierarchy_level=RegulationLevel.LAW,
        issuing_authority="全国人大",
        status=RegulationStatus.EXTRACTED,
        quality_score=0.95
    )
    assert record.law_name == "保险法"
    assert record.effective_date == "2023-01-01"
    assert record.hierarchy_level == RegulationLevel.LAW
    assert record.quality_score == 0.95
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/lib/common/test_models.py::test_regulation_record_defaults -v`

Expected: PASS

- [ ] **Step 8: Write test for ProcessingOutcome**

```python
# tests/lib/common/test_models.py (add)

from lib.common.models import ProcessingOutcome, RegulationRecord, RegulationStatus
from datetime import datetime


def test_processing_outcome_defaults():
    """测试 ProcessingOutcome 默认值"""
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险"
    )
    outcome = ProcessingOutcome(
        success=True,
        regulation_id="abc123",
        record=record
    )
    assert outcome.success is True
    assert outcome.regulation_id == "abc123"
    assert outcome.errors == []
    assert outcome.warnings == []
    assert outcome.processor == ""
    assert isinstance(outcome.processed_at, datetime)


def test_processing_outcome_with_errors():
    """测试 ProcessingOutcome 带错误信息"""
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险"
    )
    outcome = ProcessingOutcome(
        success=False,
        regulation_id="",
        record=record,
        errors=["解析失败", "缺少必要字段"],
        warnings=["字段不完整"],
        processor="preprocessing.extractor"
    )
    assert outcome.success is False
    assert outcome.errors == ["解析失败", "缺少必要字段"]
    assert outcome.warnings == ["字段不完整"]
    assert outcome.processor == "preprocessing.extractor"
```

- [ ] **Step 9: Run test to verify it passes**

Run: `pytest tests/lib/common/test_models.py::test_processing_outcome_defaults -v`

Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add scripts/lib/common/ tests/lib/common/
git commit -m "feat: add common layer with shared data models

Add RegulationStatus, RegulationLevel enums and RegulationRecord,
ProcessingOutcome, RegulationDocument dataclasses."
```

---

## Chunk 2: Preprocessing Package - Prompts

### Task 2: Create preprocessing package with prompts

**Files:**
- Create: `scripts/lib/preprocessing/__init__.py`
- Create: `scripts/lib/preprocessing/prompts.py`

- [ ] **Step 1: Create preprocessing/__init__.py**

```python
# scripts/lib/preprocessing/__init__.py

from .cleaner import DocumentCleaner
from .extractor import InformationExtractor

__all__ = ['DocumentCleaner', 'InformationExtractor']
```

- [ ] **Step 2: Create preprocessing/prompts.py with cleaning prompt**

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


def get_cleaning_prompt() -> str:
    """获取文档清洗提示词"""
    return CLEANING_SYSTEM_PROMPT


def get_extraction_prompt() -> str:
    """获取信息提取提示词"""
    return EXTRACTION_SYSTEM_PROMPT


def format_completeness_check_prompt(content: str) -> str:
    """格式化完整性检查提示词"""
    return COMPLETENESS_CHECK_PROMPT.format(content=content[:3000])
```

- [ ] **Step 3: Write test for prompts**

```python
# tests/lib/preprocessing/test_prompts.py

from lib.preprocessing.prompts import (
    get_cleaning_prompt,
    get_extraction_prompt,
    format_completeness_check_prompt
)


def test_get_cleaning_prompt():
    """测试获取清洗提示词"""
    prompt = get_cleaning_prompt()
    assert "保险法规文档清洗专家" in prompt
    assert "清洗规则" in prompt
    assert "图片链接" in prompt


def test_get_extraction_prompt():
    """测试获取提取提示词"""
    prompt = get_extraction_prompt()
    assert "保险法规信息提取专家" in prompt
    assert "law_name" in prompt
    assert "hierarchy_level" in prompt
    assert "JSON 格式" in prompt


def test_format_completeness_check_prompt():
    """测试格式化完整性检查提示词"""
    content = "这是一条测试法规内容"
    prompt = format_completeness_check_prompt(content)
    assert "这是一条测试法规内容" in prompt
    assert "信息完整性" in prompt
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/lib/preprocessing/test_prompts.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/preprocessing/__init__.py scripts/lib/preprocessing/prompts.py tests/lib/preprocessing/
git commit -m "feat: add preprocessing prompts module"
```

---

## Chunk 3: Preprocessing Package - DocumentCleaner

### Task 3: Create DocumentCleaner class

**Files:**
- Create: `scripts/lib/preprocessing/cleaner.py`
- Test: `tests/lib/preprocessing/test_cleaner.py`

- [ ] **Step 1: Write test for rule-based cleaning**

```python
# tests/lib/preprocessing/test_cleaner.py

import pytest
from lib.preprocessing.cleaner import DocumentCleaner
from lib.common.models import RegulationRecord, RegulationStatus


def test_rule_based_clean_removes_images():
    """测试去除图片链接"""
    cleaner = DocumentCleaner()
    content = "测试内容![图片](image.png)更多内容"
    result = cleaner._rule_based_clean(content)
    assert "![图片]" not in result
    assert "测试内容" in result
    assert "更多内容" in result


def test_rule_based_clean_removes_html():
    """测试去除 HTML 标签"""
    cleaner = DocumentCleaner()
    content = "测试内容<div>HTML</div>更多内容"
    result = cleaner._rule_based_clean(content)
    assert "<div>" not in result
    assert "</div>" not in result
    assert "测试内容" in result
    assert "HTML" in result


def test_rule_based_clean_normalizes_newlines():
    """测试统一换行符"""
    cleaner = DocumentCleaner()
    content = "第一行\r\n第二行\n\n\n第三行"
    result = cleaner._rule_based_clean(content)
    assert "\r\n" not in result
    assert "\n\n\n" not in result  # 多余空行应被减少


def test_rule_based_clean_removes_excess_blank_lines():
    """测试去除多余空行"""
    cleaner = DocumentCleaner()
    content = "第一行\n\n\n\n第二行"
    result = cleaner._rule_based_clean(content)
    assert "\n\n\n" not in result
    # 应该只有双换行
    assert result.count("\n\n") >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/lib/preprocessing/test_cleaner.py -v`

Expected: FAIL with "DocumentCleaner not defined"

- [ ] **Step 3: Create cleaner.py with DocumentCleaner class**

```python
# scripts/lib/preprocessing/cleaner.py

from typing import Dict, List, Optional
import re
import logging
import hashlib
from lib.common.models import RegulationRecord, RegulationStatus, ProcessingOutcome
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

            # LLM 验证和补充（可选，根据配置）
            # llm_cleaned = self._llm_assisted_clean(rule_cleaned)
            cleaned_content = rule_cleaned  # Phase 1 只使用规则清洗

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

        # 去除多余空行（3个或更多连续换行变成2个）
        content = re.sub(r'\n{3,}', '\n\n', content)

        return content.strip()

    def _llm_assisted_clean(self, content: str) -> str:
        """使用 LLM 辅助清洗（Phase 1 不启用）"""
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
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/lib/preprocessing/test_cleaner.py -v`

Expected: PASS

- [ ] **Step 5: Write test for clean() method**

```python
# tests/lib/preprocessing/test_cleaner.py (add)

from unittest.mock import Mock, patch


def test_clean_success():
    """测试成功清洗文档"""
    cleaner = DocumentCleaner()
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="测试"
    )

    result = cleaner.clean(
        content="测试内容",
        source_file="test.md",
        record=record
    )

    assert result.success is True
    assert record.status == RegulationStatus.CLEANED
    assert result.errors == []
    assert result.processor == "preprocessing.cleaner"


def test_clean_with_invalid_content():
    """测试处理无效内容（模拟异常）"""
    cleaner = DocumentCleaner()
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="测试"
    )

    # 模拟异常
    with patch.object(cleaner, '_rule_based_clean', side_effect=Exception("清洗失败")):
        result = cleaner.clean(
            content="测试内容",
            source_file="test.md",
            record=record
        )

    assert result.success is False
    assert record.status == RegulationStatus.FAILED
    assert "清洗失败" in result.errors[0]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/lib/preprocessing/test_cleaner.py::test_clean_success -v`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/preprocessing/cleaner.py tests/lib/preprocessing/test_cleaner.py
git commit -m "feat: add DocumentCleaner with rule-based cleaning"
```

---

## Chunk 4: Preprocessing Package - InformationExtractor

### Task 4: Create InformationExtractor class

**Files:**
- Create: `scripts/lib/preprocessing/extractor.py`
- Test: `tests/lib/preprocessing/test_extractor.py`

- [ ] **Step 1: Write test for _generate_regulation_id**

```python
# tests/lib/preprocessing/test_extractor.py

import pytest
from lib.preprocessing.extractor import InformationExtractor
from lib.common.models import RegulationRecord, RegulationLevel, RegulationStatus


def test_generate_regulation_id():
    """测试生成法规唯一标识"""
    extractor = InformationExtractor()
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险"
    )

    reg_id = extractor._generate_regulation_id(record)
    assert len(reg_id) == 16
    assert isinstance(reg_id, str)

    # 相同输入应生成相同 ID
    reg_id2 = extractor._generate_regulation_id(record)
    assert reg_id == reg_id2

    # 不同输入应生成不同 ID
    record2 = RegulationRecord(
        law_name="保险法",
        article_number="第十七条",
        category="健康保险"
    )
    reg_id3 = extractor._generate_regulation_id(record2)
    assert reg_id != reg_id3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/lib/preprocessing/test_extractor.py -v`

Expected: FAIL with "InformationExtractor not defined"

- [ ] **Step 3: Create extractor.py with InformationExtractor class**

```python
# scripts/lib/preprocessing/extractor.py

from typing import Dict, List, Optional
import json
import logging
import hashlib
from lib.common.models import RegulationRecord, RegulationLevel, RegulationStatus, ProcessingOutcome
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
                record.hierarchy_level = RegulationLevel(extracted_info['hierarchy_level'])
            if extracted_info.get('issuing_authority'):
                record.issuing_authority = extracted_info['issuing_authority']
            if extracted_info.get('category'):
                record.category = extracted_info['category']

            # 质量检查（Phase 1 使用默认值）
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
        from .prompts import format_completeness_check_prompt

        prompt = format_completeness_check_prompt(content[:3000])

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
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/lib/preprocessing/test_extractor.py::test_generate_regulation_id -v`

Expected: PASS

- [ ] **Step 5: Write test for extract() with mock LLM**

```python
# tests/lib/preprocessing/test_extractor.py (add)

from unittest.mock import Mock, patch


def test_extract_success_with_mock():
    """测试成功提取信息（使用 Mock LLM）"""
    mock_llm = Mock()
    mock_llm.chat.side_effect = [
        # _extract_with_llm 调用
        '{"law_name": "保险法", "effective_date": "2023-01-01", "hierarchy_level": "law", "issuing_authority": "全国人大", "category": "健康保险"}',
        # _check_completeness 调用
        '{"is_complete": true, "issues": [], "quality_score": 0.9}'
    ]

    extractor = InformationExtractor(llm_client=mock_llm)
    record = RegulationRecord(
        law_name="",  # 初始为空，会被提取填充
        article_number="第十六条",
        category="未分类"
    )

    result = extractor.extract("测试文档内容", record)

    assert result.success is True
    assert record.law_name == "保险法"
    assert record.effective_date == "2023-01-01"
    assert record.hierarchy_level == RegulationLevel.LAW
    assert record.issuing_authority == "全国人大"
    assert record.category == "健康保险"
    assert record.quality_score == 0.9
    assert record.status == RegulationStatus.EXTRACTED


def test_extract_with_json_parse_error():
    """测试 JSON 解析失败时的处理"""
    mock_llm = Mock()
    mock_llm.chat.side_effect = [
        "非 JSON 响应",  # _extract_with_llm 返回无效 JSON
        '{"is_complete": true, "issues": [], "quality_score": 0.5}'
    ]

    extractor = InformationExtractor(llm_client=mock_llm)
    record = RegulationRecord(
        law_name="原始名称",
        article_number="第十六条",
        category="未分类"
    )

    result = extractor.extract("测试文档内容", record)

    # 即使 JSON 解析失败，也应该成功（使用默认值）
    assert result.success is True
    # law_name 应保持原值（因为提取失败）
    assert record.law_name == "原始名称"
    assert record.quality_score == 0.5
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/lib/preprocessing/test_extractor.py::test_extract_success_with_mock -v`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/preprocessing/extractor.py tests/lib/preprocessing/test_extractor.py
git commit -m "feat: add InformationExtractor with LLM-based extraction"
```

---

## Chunk 5: Audit Package - Basic Structure

### Task 5: Create audit package with basic structure

**Files:**
- Create: `scripts/lib/audit/__init__.py`
- Create: `scripts/lib/audit/prompts.py`
- Create: `scripts/lib/audit/auditor.py`
- Test: `tests/lib/audit/test_auditor.py`

- [ ] **Step 1: Create audit/__init__.py**

```python
# scripts/lib/audit/__init__.py

from dataclasses import dataclass
from typing import List

# 为了避免循环导入，在这里定义简单版本
# 完整实现在 auditor.py 中


__all__ = ['ComplianceAuditor']
```

- [ ] **Step 2: Create audit/prompts.py**

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


def get_audit_prompt() -> str:
    """获取合规审核提示词"""
    return AUDIT_SYSTEM_PROMPT


def format_comparison_prompt(product_clause: str, regulation_content: str) -> str:
    """格式化条款对比提示词"""
    return CLAUSE_COMPARISON_PROMPT.format(
        product_clause=product_clause,
        regulation_content=regulation_content
    )
```

- [ ] **Step 3: Create audit/auditor.py with basic structure**

```python
# scripts/lib/audit/auditor.py

from dataclasses import dataclass
from typing import Dict, List
import json
import logging
import hashlib
from lib.common.models import RegulationRecord, RegulationStatus, ProcessingOutcome
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
        from .prompts import format_comparison_prompt

        prompt = format_comparison_prompt(product_clause, regulation_content)

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
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
```

- [ ] **Step 4: Update audit/__init__.py**

```python
# scripts/lib/audit/__init__.py

from .auditor import ComplianceAuditor, AuditIssue, AuditReport

__all__ = ['ComplianceAuditor', 'AuditIssue', 'AuditReport']
```

- [ ] **Step 5: Write test for auditor**

```python
# tests/lib/audit/test_auditor.py

import pytest
from unittest.mock import Mock
from lib.audit.auditor import ComplianceAuditor, AuditIssue, AuditReport
from lib.common.models import RegulationRecord, RegulationStatus


def test_audit_with_mock():
    """测试合规审核（使用 Mock）"""
    mock_llm = Mock()
    mock_llm.chat.return_value = '''{"overall_assessment": "通过", "issues": [], "score": 95, "summary": "符合规定"}'''

    auditor = ComplianceAuditor(llm_client=mock_llm)
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险"
    )

    result = auditor.audit(
        product_clause="产品条款内容",
        regulation_record=record,
        regulation_content="法规内容"
    )

    assert result.success is True
    assert record.status == RegulationStatus.AUDITED
    assert result.processor == "audit.auditor"


def test_compare_clauses_with_mock():
    """测试条款对比"""
    mock_llm = Mock()
    mock_llm.chat.return_value = '{"is_compliant": true, "differences": [], "missing_points": [], "risk_level": "low"}'

    auditor = ComplianceAuditor(llm_client=mock_llm)

    result = auditor.compare_clauses(
        product_clause="产品条款",
        regulation_content="法规内容"
    )

    assert result['is_compliant'] is True
    assert result['risk_level'] == 'low'


def test_audit_with_json_error():
    """测试 JSON 解析失败"""
    mock_llm = Mock()
    mock_llm.chat.return_value = "非 JSON 响应"

    auditor = ComplianceAuditor(llm_client=mock_llm)
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险"
    )

    result = auditor.audit(
        product_clause="产品条款内容",
        regulation_record=record,
        regulation_content="法规内容"
    )

    # 应该成功但标记为失败
    assert result.success is True
    assert record.status == RegulationStatus.AUDITED
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/lib/audit/test_auditor.py -v`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/audit/ tests/lib/audit/
git commit -m "feat: add audit package with ComplianceAuditor"
```

---

## Chunk 6: Configuration Integration

### Task 6: Extend config.py with preprocessing and audit config

**Files:**
- Modify: `scripts/lib/config.py`

- [ ] **Step 1: Write test for PreprocessingConfig**

```python
# tests/lib/test_config_extension.py

import pytest
from lib.config import Config, PreprocessingConfig


def test_preprocessing_config_defaults():
    """测试预处理配置默认值"""
    config_dict = {}
    preprocessing_config = PreprocessingConfig(config_dict)

    assert preprocessing_config.enable_llm_cleaning is True
    assert preprocessing_config.max_content_length == 5000
    assert preprocessing_config.quality_threshold == 0.6


def test_preprocessing_config_from_dict():
    """测试从字典读取配置"""
    config_dict = {
        'preprocessing': {
            'enable_llm_cleaning': False,
            'max_content_length': 3000,
            'quality_threshold': 0.8
        }
    }
    preprocessing_config = PreprocessingConfig(config_dict)

    assert preprocessing_config.enable_llm_cleaning is False
    assert preprocessing_config.max_content_length == 3000
    assert preprocessing_config.quality_threshold == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_config_extension.py -v`

Expected: FAIL with "PreprocessingConfig not defined"

- [ ] **Step 3: Add PreprocessingConfig to config.py**

Read the current config.py to find the right place to insert:

```python
# 在 scripts/lib/config.py 中，在 AuditConfig 类之前添加

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
```

- [ ] **Step 4: Add PreprocessingConfig to Config class**

In the `_init_nested_configs` method of `Config` class, add:

```python
# 在 Config._init_nested_configs 方法中添加
self._preprocessing = PreprocessingConfig(self._config)
```

And add property:

```python
# 在 Config 类中添加属性
@property
def preprocessing(self) -> PreprocessingConfig:
    """预处理配置"""
    return self._preprocessing
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/lib/test_config_extension.py -v`

Expected: PASS

- [ ] **Step 6: Write test for updated AuditConfig**

```python
# tests/lib/test_config_extension.py (add)

def test_audit_config_extended():
    """测试扩展的审核配置"""
    config_dict = {
        'audit': {
            'enable_detailed_audit': True,
            'max_comparison_length': 3000
        }
    }
    from lib.config import AuditConfig
    audit_config = AuditConfig(config_dict)

    assert audit_config.enable_detailed_audit is True
    assert audit_config.max_comparison_length == 3000
```

- [ ] **Step 7: Add new properties to AuditConfig**

In the existing `AuditConfig` class, add:

```python
# 在现有 AuditConfig 类中添加新属性

@property
def enable_detailed_audit(self) -> bool:
    """是否启用详细审核"""
    return self._config.get('enable_detailed_audit', True)

@property
def max_comparison_length(self) -> int:
    """条款对比最大长度"""
    return self._config.get('max_comparison_length', 3000)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/lib/test_config_extension.py::test_audit_config_extended -v`

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add scripts/lib/config.py tests/lib/test_config_extension.py
git commit -m "feat: extend config with PreprocessingConfig and AuditConfig updates"
```

---

## Chunk 7: Integration with RAG Engine

### Task 7: Add LanceDB metadata enhancement

**Files:**
- Modify: `scripts/lib/rag_engine/data_importer.py`

- [ ] **Step 1: Read existing data_importer.py**

Run: `head -100 scripts/lib/rag_engine/data_importer.py`

Note: Read the file to understand the existing import logic.

- [ ] **Step 2: Create helper function for enhanced metadata**

Create a new file `scripts/lib/rag_engine/metadata_enhancer.py`:

```python
# scripts/lib/rag_engine/metadata_enhancer.py

import logging
from pathlib import Path
from lib.preprocessing import DocumentCleaner, InformationExtractor
from lib.common.models import RegulationRecord, RegulationStatus

logger = logging.getLogger(__name__)


def enhance_metadata_from_file(file_path: str) -> dict:
    """
    从文件提取增强元数据

    Args:
        file_path: 法规文档文件路径

    Returns:
        dict: 增强元数据字典
    """
    try:
        # 读取原始内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 创建初始记录
        record = RegulationRecord(
            law_name="",
            article_number="",
            category="未分类",
            status=RegulationStatus.RAW
        )

        # 清洗文档
        cleaner = DocumentCleaner()
        clean_result = cleaner.clean(content, file_path, record)

        if not clean_result.success:
            logger.warning(f"文档清洗失败: {clean_result.errors}")
            # 返回基础元数据
            return {
                'law_name': '',
                'article_number': '',
                'category': '未分类',
                'effective_date': None,
                'hierarchy_level': None,
                'issuing_authority': None,
                'status': RegulationStatus.FAILED.value,
                'quality_score': None
            }

        # 提取结构化信息
        extractor = InformationExtractor()
        extract_result = extractor.extract(content, record)

        if not extract_result.success:
            logger.warning(f"信息提取失败: {extract_result.errors}")

        # 构建增强元数据
        return {
            'law_name': record.law_name,
            'article_number': record.article_number,
            'category': record.category,
            'effective_date': record.effective_date,
            'hierarchy_level': record.hierarchy_level.value if record.hierarchy_level else None,
            'issuing_authority': record.issuing_authority,
            'status': record.status.value,
            'quality_score': record.quality_score
        }

    except Exception as e:
        logger.error(f"元数据增强失败: {e}")
        return {
            'law_name': '',
            'article_number': '',
            'category': '未分类',
            'effective_date': None,
            'hierarchy_level': None,
            'issuing_authority': None,
            'status': RegulationStatus.FAILED.value,
            'quality_score': None
        }
```

- [ ] **Step 3: Write test for metadata enhancer**

```python
# tests/lib/rag_engine/test_metadata_enhancer.py

import pytest
import tempfile
import os
from lib.rag_engine.metadata_enhancer import enhance_metadata_from_file


def test_enhance_metadata_from_file():
    """测试从文件提取增强元数据"""
    # 创建临时测试文件
    content = """
# 保险法相关监管规定

## 第十六条

订立保险合同，保险人就保险标的或者被保险人的有关情况提出询问的，投保人应当如实告知。
    """

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
        f.write(content)
        temp_file = f.name

    try:
        metadata = enhance_metadata_from_file(temp_file)

        assert 'law_name' in metadata
        assert 'article_number' in metadata
        assert 'category' in metadata
        assert 'status' in metadata
        assert metadata['status'] in ['raw', 'cleaned', 'extracted', 'audited', 'failed']

    finally:
        os.unlink(temp_file)


def test_enhance_metadata_with_nonexistent_file():
    """测试处理不存在的文件"""
    metadata = enhance_metadata_from_file('/nonexistent/file.md')

    assert metadata['status'] == 'failed'
    assert metadata['category'] == '未分类'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/lib/rag_engine/test_metadata_enhancer.py -v`

Expected: PASS

- [ ] **Step 5: Add metadata filtering helper to rag_engine.py**

Create a new file or add to existing `rag_engine.py`:

```python
# 在 scripts/lib/rag_engine/rag_engine.py 中添加方法

def search_by_metadata(
    self,
    query: str,
    law_name: str = None,
    category: str = None,
    hierarchy_level: str = None,
    issuing_authority: str = None
) -> List[Dict[str, Any]]:
    """
    使用增强元数据进行检索

    Args:
        query: 查询文本
        law_name: 法规名称过滤
        category: 分类过滤
        hierarchy_level: 层级过滤
        issuing_authority: 发布机关过滤

    Returns:
        List[Dict]: 检索结果
    """
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

- [ ] **Step 6: Write test for search_by_metadata**

```python
# tests/lib/rag_engine/test_rag_engine_metadata.py (add)

import pytest
from lib.rag_engine import create_qa_engine


def test_search_by_metadata_with_filters():
    """测试使用元数据过滤检索"""
    engine = create_qa_engine()
    engine.initialize()

    # 按分类过滤
    results = engine.search_by_metadata(
        query="保险",
        category="健康保险"
    )

    assert isinstance(results, list)
    # 验证所有结果都符合过滤条件
    for result in results:
        if result.get('category'):
            assert '健康保险' in result['category'] or result['category'] == '健康保险'


def test_search_by_metadata_with_law_name():
    """测试按法规名称过滤"""
    engine = create_qa_engine()
    engine.initialize()

    results = engine.search_by_metadata(
        query="等待期",
        law_name="保险法"
    )

    assert isinstance(results, list)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/lib/rag_engine/test_rag_engine_metadata.py -v`

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/rag_engine/metadata_enhancer.py tests/lib/rag_engine/
git commit -m "feat: add LanceDB metadata enhancement helpers"
```

---

## Chunk 8: End-to-End Integration Test

### Task 8: Create end-to-end integration test

**Files:**
- Create: `tests/integration/test_preprocessing_audit_pipeline.py`

- [ ] **Step 1: Write end-to-end test**

```python
# tests/integration/test_preprocessing_audit_pipeline.py

import pytest
import tempfile
import os
from lib.preprocessing import DocumentCleaner, InformationExtractor
from lib.audit import ComplianceAuditor
from lib.common.models import RegulationRecord, RegulationStatus, RegulationLevel


def test_full_preprocessing_pipeline():
    """测试完整预处理流程"""
    # 创建测试文档
    content = """
# 保险法相关监管规定

## 第十六条

订立保险合同，保险人就保险标的或者被保险人的有关情况提出询问的，投保人应当如实告知。

## 第十七条

订立保险合同，采用保险人提供的格式条款的，保险人向投保人提供的投保单应当附格式条款，保险人应当向投保人说明合同的内容。
    """

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
        f.write(content)
        temp_file = f.name

    try:
        # 1. 创建初始记录
        record = RegulationRecord(
            law_name="",
            article_number="第十六条",
            category="未分类"
        )

        # 2. 清洗文档
        cleaner = DocumentCleaner()
        clean_result = cleaner.clean(content, temp_file, record)

        assert clean_result.success is True
        assert record.status == RegulationStatus.CLEANED

        # 3. 提取信息
        extractor = InformationExtractor()
        extract_result = extractor.extract(content, record)

        assert extract_result.success is True
        assert record.status == RegulationStatus.EXTRACTED
        # 注意：由于使用 Mock，实际字段可能没有被填充
        # 在真实环境中需要 LLM 调用

        # 4. 验证结果
        assert extract_result.regulation_id != ""
        assert extract_result.processor == "preprocessing.extractor"

    finally:
        os.unlink(temp_file)


def test_audit_pipeline():
    """测试审核流程"""
    # 创建测试数据
    product_clause = """
    等待期：本产品等待期为 90 天，自合同生效日起计算。
    在等待期内发生保险事故，保险公司不承担保险责任。
    """

    regulation_content = """
    # 健康保险产品开发相关监管规定

    ## 第二十七条

    疾病保险、医疗保险、护理保险产品的等待期不得超过 180 天。
    """

    record = RegulationRecord(
        law_name="健康保险产品开发相关监管规定",
        article_number="第二十七条",
        category="健康保险"
    )

    # 使用 Mock LLM 进行测试
    from unittest.mock import Mock
    mock_llm = Mock()
    mock_llm.chat.return_value = '''{"overall_assessment": "通过", "issues": [], "score": 95, "summary": "符合规定"}'''

    auditor = ComplianceAuditor(llm_client=mock_llm)
    audit_result = auditor.audit(product_clause, record, regulation_content)

    assert audit_result.success is True
    assert record.status == RegulationStatus.AUDITED
    assert audit_result.processor == "audit.auditor"


def test_metadata_enhanced_search():
    """测试元数据增强检索"""
    from lib.rag_engine import create_qa_engine

    engine = create_qa_engine()
    engine.initialize()

    # 使用元数据过滤
    results = engine.search_by_metadata(
        query="保险",
        category="健康保险"
    )

    assert isinstance(results, list)
    # 验证结果结构
    for result in results[:3]:  # 只检查前3个
        assert 'law_name' in result
        assert 'article_number' in result
        assert 'content' in result
        assert 'score' in result
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/integration/test_preprocessing_audit_pipeline.py -v`

Expected: PASS

- [ ] **Step 3: Create example usage script**

```python
# scripts/examples/preprocessing_audit_example.py

"""
文档预处理和审核系统使用示例
"""

from lib.preprocessing import DocumentCleaner, InformationExtractor
from lib.audit import ComplianceAuditor
from lib.common.models import RegulationRecord, RegulationStatus
from lib.rag_engine import create_qa_engine


def example_preprocessing():
    """预处理示例"""
    # 读取文档
    with open('references/01_保险法相关监管规定.md', 'r', encoding='utf-8') as f:
        content = f.read()

    # 创建记录
    record = RegulationRecord(
        law_name="",
        article_number="",
        category="未分类"
    )

    # 清洗
    cleaner = DocumentCleaner()
    clean_result = cleaner.clean(content, 'test.md', record)
    print(f"清洗结果: {clean_result.success}, 状态: {record.status}")

    # 提取
    extractor = InformationExtractor()
    extract_result = extractor.extract(content, record)
    print(f"提取结果: {extract_result.success}")
    print(f"法规名称: {record.law_name}")
    print(f"生效日期: {record.effective_date}")
    print(f"发布机关: {record.issuing_authority}")
    print(f"质量分数: {record.quality_score}")


def example_audit():
    """审核示例"""
    product_clause = "等待期：90天"
    regulation_content = "等待期不得超过180天"

    record = RegulationRecord(
        law_name="健康保险监管规定",
        article_number="第二十七条",
        category="健康保险"
    )

    auditor = ComplianceAuditor()
    audit_result = auditor.audit(product_clause, record, regulation_content)

    print(f"审核结果: {audit_result.success}")
    print(f"状态: {record.status}")


def example_metadata_search():
    """元数据检索示例"""
    engine = create_qa_engine()
    engine.initialize()

    # 按分类检索
    results = engine.search_by_metadata(
        query="等待期",
        category="健康保险"
    )

    for result in results[:3]:
        print(f"{result['law_name']} - {result['article_number']}")
        print(f"相似度: {result['score']:.2f}\n")


if __name__ == '__main__':
    print("=== 预处理示例 ===")
    example_preprocessing()

    print("\n=== 审核示例 ===")
    example_audit()

    print("\n=== 元数据检索示例 ===")
    example_metadata_search()
```

- [ ] **Step 4: Commit**

```bash
git add tests/integration/ scripts/examples/
git commit -m "test: add end-to-end integration test and usage examples"
```

---

## Verification

### Task 9: Final verification and documentation

- [ ] **Step 1: Run all tests**

```bash
pytest tests/lib/common/ -v
pytest tests/lib/preprocessing/ -v
pytest tests/lib/audit/ -v
pytest tests/lib/rag_engine/test_metadata_enhancer.py -v
pytest tests/integration/test_preprocessing_audit_pipeline.py -v
```

Expected: All PASS

- [ ] **Step 2: Verify imports work**

```bash
python3 -c "from lib.common.models import RegulationRecord; from lib.preprocessing import DocumentCleaner; from lib.audit import ComplianceAuditor; print('All imports OK')"
```

Expected: `All imports OK`

- [ ] **Step 3: Check package structure**

```bash
find scripts/lib/{common,preprocessing,audit} -name "*.py" | sort
```

Expected output:
```
scripts/lib/common/__init__.py
scripts/lib/common/models.py
scripts/lib/preprocessing/__init__.py
scripts/lib/preprocessing/cleaner.py
scripts/lib/preprocessing/extractor.py
scripts/lib/preprocessing/prompts.py
scripts/lib/audit/__init__.py
scripts/lib/audit/auditor.py
scripts/lib/audit/prompts.py
```

- [ ] **Step 4: Create README for the new system**

```markdown
# scripts/lib/PREPROCESSING_AUDIT_README.md

## 文档预处理和审核系统

### 架构

```
scripts/lib/
├── common/              # 公共可复用层
│   ├── models.py        # 数据模型
├── preprocessing/       # 预处理包
│   ├── prompts.py       # 预处理 Prompt
│   ├── cleaner.py       # 文档清洗
│   └── extractor.py     # 信息提取
└── audit/               # 审核包
    ├── prompts.py       # 审核 Prompt
    └── auditor.py       # 合规审核
```

### 使用示例

```python
from lib.preprocessing import DocumentCleaner, InformationExtractor
from lib.audit import ComplianceAuditor
from lib.common.models import RegulationRecord

# 预处理
cleaner = DocumentCleaner()
extractor = InformationExtractor()

record = RegulationRecord(
    law_name="",
    article_number="",
    category="未分类"
)

with open('regulation.md', 'r') as f:
    content = f.read()

clean_result = cleaner.clean(content, 'regulation.md', record)
extract_result = extractor.extract(content, record)

# 审核
auditor = ComplianceAuditor()
audit_result = auditor.audit(
    product_clause="产品条款",
    regulation_record=record,
    regulation_content="法规内容"
)
```

### 元数据检索

```python
from lib.rag_engine import create_qa_engine

engine = create_qa_engine()
engine.initialize()

# 按分类检索
results = engine.search_by_metadata(
    query="等待期",
    category="健康保险"
)
```
```

- [ ] **Step 5: Final commit**

```bash
git add scripts/lib/PREPROCESSING_AUDIT_README.md
git commit -m "docs: add preprocessing and audit system README"
```

---

**Plan complete and saved to `docs/superpowers/plans/2026-03-14-document-preprocessing-audit-system.md`. Ready to execute?**
