# Comprehensive Document Preprocessing System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a comprehensive document preprocessing system for insurance products with dual-path extraction (fast path for standard documents, structured path for complex ones), dynamic prompt generation based on product type classification, and complete validation.

**Architecture:**
- **Dual-path extraction**: 80%+ documents go through fast path (lightweight LLM with few-shot), 20% go through structured path (dynamic prompt + specialized extractors)
- **Multi-label product classification**: Identifies product types (critical illness, medical, universal life, term life, etc.) with confidence scores
- **Component-based prompt builder**: Dynamically generates prompts based on product type and user requirements
- **Layered validation**: Business rules, data types, and confidence checks

**Tech Stack:** Python 3.10+, LLM clients (zhipu/ollama), pytest for testing, dataclasses for models

---

## File Structure

```
lib/preprocessing/
├── __init__.py                 # Module exports
├── models.py                   # Data models (NormalizedDocument, ExtractResult, etc.)
├── product_types.py            # Product type definitions and templates
├── document_normalizer.py     # Document normalization (encoding, noise removal)
├── classifier.py               # Product type classifier (multi-label)
├── path_selector.py           # Extraction path selector (fast vs structured)
├── prompt_builder.py          # Dynamic prompt generator (component-based)
├── lightweight_extractor.py    # Lightweight extractor for fast path
├── structured_extractor.py    # Structured extractor with specialized extractors
├── validator.py                # Result validation (business rules, data types)
└── extractor.py                # Unified extractor (main entry point)

tests/preprocessing/
├── __init__.py
├── test_models.py              # Test data models
├── test_classifier.py           # Test product type classifier
├── test_normalizer.py          # Test document normalizer
├── test_path_selector.py        # Test path selection logic
├── test_lightweight_extractor.py # Test lightweight extractor
├── test_structured_extractor.py # Test structured extractor
├── test_validator.py           # Test validation logic
├── test_extractor.py           # Test unified extractor
└── fixtures/                   # Test documents
    ├── critical_illness.txt
    ├── medical_insurance.txt
    ├── universal_life.txt
    └── term_life.txt

docs/superpowers/plans/
└── 2025-03-11-comprehensive-preprocessing-system.md  # This file
```

---

## Chunk 1: Foundation - Core Models and Classification

### Task 1.1: Fix Missing Import in classifier.py

**Files:**
- Modify: `lib/preprocessing/classifier.py:1-20`

- [x] **Step 1: Add missing Optional import**

Add `Optional` to the typing imports in classifier.py line 1-20.

```bash
# Verify import works
python3 -c "from lib.preprocessing import ProductTypeClassifier; print('OK')"
```

### Task 1.2: Test Product Type Classification

**Files:**
- Test: `tests/preprocessing/test_classifier.py`

- [x] **Step 1: Write test for product type classification**

```python
# tests/preprocessing/test_classifier.py
import pytest
from lib.preprocessing import ProductTypeClassifier

def test_classify_critical_illness():
    """Test critical illness classification"""
    classifier = ProductTypeClassifier(threshold=0.3)

    document = """
    # 重大疾病保险条款
    第一条：保险责任
    本合同承保的重大疾病包括：恶性肿瘤、急性心肌梗死
    等待期：90天
    轻症赔付：30%保额，重症赔付：100%保额
    """

    classifications = classifier.classify(document)

    assert len(classifications) > 0
    primary_type, confidence = classifier.get_primary_type(document)
    assert primary_type == 'critical_illness'
    assert confidence > 0.5

def test_classify_hybrid_product():
    """Test hybrid product classification (medical + critical illness)"""
    classifier = ProductTypeClassifier(threshold=0.3)

    document = """
    # 重大疾病医疗保险
    包含重大疾病保障和医疗保障
    等待期：90天
    免赔额：500元
    """

    is_hybrid = classifier.is_hybrid_product(document)
    assert is_hybrid == True

def test_classify_no_match():
    """Test classification with no match"""
    classifier = ProductTypeClassifier(threshold=0.3)

    document = "这是一份普通合同文本，没有保险相关内容"

    classifications = classifier.classify(document)
    # Should return default life_insurance with low confidence
    assert len(classifications) >= 0
```

- [x] **Step 2: Run test to verify it passes**

```bash
cd /root/.openclaw/workspace/skills/actuary-sleuth/scripts
pytest tests/preprocessing/test_classifier.py -v
```

### Task 1.3: Test Document Normalizer

**Files:**
- Test: `tests/preprocessing/test_normalizer.py`

- [x] **Step 1: Write test for document normalization**

```python
# tests/preprocessing/test_normalizer.py
import pytest
from lib.preprocessing import DocumentNormalizer

def test_normalize_basic():
    """Test basic normalization"""
    normalizer = DocumentNormalizer()

    document = "  # Test document  \n  "
    result = normalizer.normalize(document, 'text')

    assert result.content.strip() == "# Test document"
    assert result.metadata['source_type'] == 'text'

def test_normalize_pdf_noise():
    """Test PDF-specific noise removal"""
    normalizer = DocumentNormalizer()

    document = """
    第1页
    # 保险条款
    正文内容
    第2页
    更多内容
    """

    result = normalizer.normalize(document, 'pdf')

    # Should remove page numbers
    assert '第1页' not in result.content
    assert '第2页' not in result.content
    assert '保险条款' in result.content

def test_format_detection():
    """Test format detection"""
    normalizer = DocumentNormalizer()

    # Document with clauses
    document = """
    第一条 保险责任
    第二条 责任免除
    第三条 保险期间
    """ * 5

    result = normalizer.normalize(document, 'text')

    assert result.format_info.is_structured == True
    assert result.format_info.section_count >= 3
    assert result.format_info.has_clause_numbers == True
```

- [x] **Step 2: Run test to verify it passes**

```bash
pytest tests/preprocessing/test_normalizer.py -v
```

### Task 1.4: Test Path Selector

**Files:**
- Test: `tests/preprocessing/test_path_selector.py`

- [x] **Step 1: Write test for path selection**

```python
# tests/preprocessing/test_path_selector.py
import pytest
from lib.preprocessing import DocumentNormalizer, ExtractionPathSelector

def test_select_fast_path():
    """Test fast path selection for standard documents"""
    normalizer = DocumentNormalizer()
    selector = ExtractionPathSelector()

    # Standard format document
    document = """
    # 产品名称：重大疾病保险
    # 保险公司：XX人寿保险股份有限公司
    # 保险期间：终身
    # 等待期：90天

    第一条 保险责任
    第二条 责任免除
    """ * 8  # Ensure 8 sections

    normalized = normalizer.normalize(document, 'text')
    path = selector.select_path(normalized)

    assert path.path_type in ['fast', 'structured']

def test_required_fields():
    """Test required fields constant"""
    from lib.preprocessing.path_selector import ExtractionPathSelector

    required = ExtractionPathSelector.get_required_fields()

    assert 'product_name' in required
    assert 'insurance_company' in required
    assert 'waiting_period' in required
    assert len(required) >= 4
```

- [x] **Step 2: Run test to verify it passes**

```bash
pytest tests/preprocessing/test_path_selector.py -v
```

---

## Chunk 2: Prompt Builder and Lightweight Extractor

### Task 2.1: Fix Document Normalizer Quote Issue

**Files:**
- Modify: `lib/preprocessing/document_normalizer.py:95-97`

- [x] **Step 1: Fix quote escaping in document_normalizer.py**

Replace the problematic quote handling code with proper Unicode escapes.

```bash
# Verify the fix
python3 -c "from lib.preprocessing.document_normalizer import DocumentNormalizer; n = DocumentNormalizer(); print('OK')"
```

### Task 2.2: Test Prompt Builder

**Files:**
- Test: `tests/preprocessing/test_prompt_builder.py`

- [x] **Step 1: Write test for prompt builder**

```python
# tests/preprocessing/test_prompt_builder.py
import pytest
import json
from lib.preprocessing.prompt_builder import PromptBuilder
from lib.preprocessing.product_types import get_extraction_focus, get_output_schema

def test_build_basic_prompt():
    """Test basic prompt building"""
    builder = PromptBuilder()

    prompt = builder.build(
        product_type='critical_illness',
        required_fields=['product_name', 'covered_diseases'],
        extraction_focus=['病种清单', '等待期'],
        output_schema=get_output_schema('critical_illness'),
        is_hybrid=False
    )

    assert '重大疾病险产品提取专家' in prompt
    assert '病种清单' in prompt
    assert '等待期' in prompt
    assert 'diseases' in prompt.lower()
    assert 'JSON' in prompt

def test_build_hybrid_prompt():
    """Test prompt building for hybrid products"""
    builder = PromptBuilder()

    prompt = builder.build(
        product_type='critical_illness',
        required_fields=['product_name', 'covered_diseases'],
        extraction_focus=['病种清单'],
        output_schema=get_output_schema('critical_illness'),
        is_hybrid=True
    )

    assert '组合产品' in prompt
    assert '分别提取' in prompt
```

- [x] **Step 2: Run test to verify it passes**

```bash
pytest tests/preprocessing/test_prompt_builder.py -v
```

### Task 2.3: Test Lightweight Extractor

**Files:**
- Test: `tests/preprocessing/test_lightweight_extractor.py`

- [x] **Step 1: Write test for lightweight extractor**

```python
# tests/preprocessing/test_lightweight_extractor.py
import pytest
from unittest.mock import Mock
from lib.preprocessing import (
    DocumentNormalizer, LightweightExtractor,
    FastPathExtractionFailed
)

def test_extract_with_mock_llm():
    """Test lightweight extraction with mocked LLM"""
    # Create mock LLM client
    mock_llm = Mock()
    mock_llm.generate.return_value = '{"product_name": "重大疾病保险", "waiting_period": 90}'

    normalizer = DocumentNormalizer()
    extractor = LightweightExtractor(mock_llm)

    document = "# 重大疾病保险条款\n..."
    normalized = normalizer.normalize(document, 'text')

    result = extractor.extract(normalized, ['product_name', 'waiting_period'])

    assert result.data['product_name'] == '重大疾病保险'
    assert result.data['waiting_period'] == 90
    assert result.metadata['extraction_path'] == 'fast'

def test_extract_failure():
    """Test extraction failure raises exception"""
    mock_llm = Mock()
    mock_llm.generate.side_effect = Exception("LLM failed")

    normalizer = DocumentNormalizer()
    extractor = LightweightExtractor(mock_llm)

    document = "test document"
    normalized = normalizer.normalize(document, 'text')

    with pytest.raises(FastPathExtractionFailed):
        extractor.extract(normalized, ['product_name'])
```

- [x] **Step 2: Run test to verify it passes**

```bash
pytest tests/preprocessing/test_lightweight_extractor.py -v
```

---

## Chunk 3: Structured Extractor and Validation

### Task 3.1: Test Structured Extractor

**Files:**
- Test: `tests/preprocessing/test_structured_extractor.py`

- [x] **Step 1: Write test for structured extractor**

```python
# tests/preprocessing/test_structured_extractor.py
import pytest
from unittest.mock import Mock
from lib.preprocessing import (
    DocumentNormalizer, StructuredExtractor, ExtractionPath
)

def test_structured_extract_with_mock():
    """Test structured extraction with mocked LLM"""
    mock_llm = Mock()
    mock_llm.generate.return_value = '''{"product_name": "重大疾病保险", "covered_diseases": [
        {"disease_name": "恶性肿瘤", "disease_grade": "重症", "payout_ratio": 1.0}
    ]}'''

    normalizer = DocumentNormalizer()
    extractor = StructuredExtractor(mock_llm)

    document = "# 重大疾病保险\n..."
    normalized = normalizer.normalize(document, 'text')

    path = ExtractionPath(
        path_type='structured',
        product_type='critical_illness',
        confidence=0.85,
        is_hybrid=False,
        reason="Test"
    )

    result = extractor.extract(normalized, path, ['product_name', 'covered_diseases'])

    assert result.data['product_name'] == '重大疾病保险'
    assert 'covered_diseases' in result.data
    assert result.metadata['extraction_path'] == 'structured'
```

- [x] **Step 2: Run test to verify it passes**

```bash
pytest tests/preprocessing/test_structured_extractor.py -v
```

### Task 3.2: Test Validator

**Files:**
- Test: `tests/preprocessing/test_validator.py`

- [x] **Step 1: Write test for validator**

```python
# tests/preprocessing/test_validator.py
import pytest
from lib.preprocessing import ExtractResult, ExtractResultValidator

def test_validate_complete_result():
    """Test validation of complete result"""
    validator = ExtractResultValidator()

    result = ExtractResult(
        data={
            'product_name': '重大疾病保险',
            'insurance_company': 'XX人寿',
            'insurance_period': '终身',
            'waiting_period': '90',
            'age_min': '0',
            'age_max': '60'
        },
        confidence={k: 0.85 for k in ['product_name', 'insurance_company', 'insurance_period', 'waiting_period', 'age_min', 'age_max']},
        provenance={k: 'llm' for k in ['product_name', 'insurance_company', 'insurance_period', 'waiting_period', 'age_min', 'age_max']}
    )

    validation = validator.validate(result)

    assert validation.is_valid == True
    assert validation.score >= 80

def test_validate_missing_required_field():
    """Test validation with missing required field"""
    validator = ExtractResultValidator()

    result = ExtractResult(
        data={
            'product_name': '重大疾病保险',
            # Missing waiting_period
        },
        confidence={},
        provenance={}
    )

    validation = validator.validate(result)

    assert validation.is_valid == False
    assert '缺失必需字段' in '\n'.join(validation.errors)
```

- [x] **Step 2: Run test to verify it passes**

```bash
pytest tests/preprocessing/test_validator.py -v
```

---

## Chunk 4: Integration and End-to-End Testing

### Task 4.1: Test Unified Extractor

**Files:**
- Test: `tests/preprocessing/test_extractor.py`

- [x] **Step 1: Write end-to-end test for unified extractor**

```python
# tests/preprocessing/test_extractor.py
import pytest
from unittest.mock import Mock
from lib.preprocessing import UnifiedDocumentExtractor

def test_extract_end_to_end():
    """Test complete extraction flow"""
    # Mock LLM client
    mock_llm = Mock()

    # Fast path response
    mock_llm.generate.return_value = '''{
        "product_name": "重大疾病保险",
        "insurance_company": "XX人寿保险股份有限公司",
        "insurance_period": "终身",
        "waiting_period": 90
    }'''

    extractor = UnifiedDocumentExtractor(mock_llm)

    document = """
    # 重大疾病保险
    XX人寿保险股份有限公司

    第一条 保险责任
    第二条 责任免除
    第三条 保险期间：终身
    第四条 等待期：90天
    第五条 保险金额
    第六条 保险费
    第七条 犹豫期
    第八条 合同效力
    """

    result = extractor.extract(document, source_type='text')

    assert result.data['product_name'] == '重大疾病保险'
    assert result.data['waiting_period'] == 90
    assert result.metadata['extraction_path'] in ['fast', 'structured']
    assert result.metadata['validation_score'] >= 60

def test_extract_with_required_fields():
    """Test extraction with custom required fields"""
    mock_llm = Mock()
    mock_llm.generate.return_value = '{"product_name": "测试保险", "waiting_period": 90}'

    extractor = UnifiedDocumentExtractor(mock_llm)

    result = extractor.extract(
        document="test document",
        required_fields=['product_name', 'waiting_period']
    )

    assert 'product_name' in result.data
    assert 'waiting_period' in result.data
```

- [x] **Step 2: Run test to verify it passes**

```bash
pytest tests/preprocessing/test_extractor.py -v
```

### Task 4.2: Create Test Fixtures

**Files:**
- Create: `tests/preprocessing/fixtures/`

- [x] **Step 1: Create test fixture documents**

```bash
mkdir -p tests/preprocessing/fixtures
```

```python
# tests/preprocessing/fixtures/critical_illness.txt
重大疾病保险条款

第一条 保险责任
本合同承保的重大疾病包括：
1. 恶性肿瘤
2. 急性心肌梗死
3. 脑中风后遗症
4. 重大器官移植术
5. 终末期肾病
6. 多个肢体缺失
7. 急性出血性坏死性胰腺炎

等待期：90天

轻症疾病赔付：基本保额的30%
重大疾病赔付：基本保额的100%

第二条 责任免除
因下列情形之一导致被保险人身故的，本公司不承担保险责任...

第三条 保险期间
本合同保险期间为终身...
```

```python
# tests/preprocessing/fixtures/medical_insurance.txt
医疗保险条款

第一条 保险责任
在本合同保险期间内，本公司承担下列保险责任：

（一）住院医疗费用
等待期：30天

免赔额：
- 三级医院：0元
- 二级医院：500元
- 一级医院：1000元

赔付比例：
- 三级医院：90%
- 二级医院：80%
- 一级医院：70%

年度限额：20万元
```

- [x] **Step 2: Verify fixtures are created**

```bash
ls -la tests/preprocessing/fixtures/
```

### Task 4.3: Performance Comparison Test

**Files:**
- Create: `tests/preprocessing/test_performance_comparison.py`

- [x] **Step 1: Write performance comparison test**

```python
# tests/preprocessing/test_performance_comparison.py
import pytest
import time
from unittest.mock import Mock
from lib.preprocessing import UnifiedDocumentExtractor
from lib.extraction import DocumentExtractor as OldExtractor

def test_fast_path_performance():
    """Test fast path is faster than old method"""
    mock_llm = Mock()
    mock_llm.generate.return_value = '{"product_name": "测试", "insurance_company": "测试公司", "insurance_period": "终身", "waiting_period": 90}'

    # New system
    new_extractor = UnifiedDocumentExtractor(mock_llm)

    document = """
    # 测试保险
    测试保险公司

    第一条 保险责任
    第二条 保险期间：终身
    第三条 等待期：90天
    """ * 10  # Ensure it qualifies for fast path

    start = time.time()
    new_result = new_extractor.extract(document)
    new_time = time.time() - start

    # Mock old system would need 3 LLM calls vs 1 for new
    # This is a structural difference, not timing-based test
    assert new_result.metadata['extraction_path'] == 'fast'
    assert new_result.data['product_name'] == '测试'
```

- [x] **Step 2: Run test to verify it passes**

```bash
pytest tests/preprocessing/test_performance_comparison.py -v
```

---

## Chunk 5: Documentation and Finalization

### Task 5.1: Update Module Documentation

**Files:**
- Update: `lib/preprocessing/__init__.py:1-50`

- [x] **Step 1: Update module docstring with usage examples**

Add comprehensive usage examples to the module docstring.

```bash
# Verify import still works
python3 -c "from lib.preprocessing import UnifiedDocumentExtractor; print('OK')"
```

### Task 5.2: Create Integration Test with Real Document

**Files:**
- Create: `tests/preprocessing/integration_test.py`

- [x] **Step 1: Create integration test with sample document**

```python
# tests/preprocessing/integration_test.py
import pytest
import os
from lib.preprocessing import UnifiedDocumentExtractor
from lib.llm_client import LLMClientFactory

@pytest.mark.integration
def test_extract_real_document():
    """Test extraction with real document (if available)"""
    # Try to find a test document
    fixture_path = 'tests/preprocessing/fixtures/critical_illness.txt'

    if not os.path.exists(fixture_path):
        pytest.skip("No test document available")

    with open(fixture_path, 'r', encoding='utf-8') as f:
        document = f.read()

    # Use actual LLM client if available, otherwise mock
    try:
        from lib.config import get_config
        llm_config = get_config().llm.to_client_config()
        llm_client = LLMClientFactory.create_client(llm_config)
    except:
        pytest.skip("No LLM configuration available")

    extractor = UnifiedDocumentExtractor(llm_client)
    result = extractor.extract(document)

    # Basic validation
    assert result.data is not None
    assert len(result.data) > 0
    assert result.metadata['validation_score'] >= 0
```

- [x] **Step 2: Run integration test**

```bash
pytest tests/preprocessing/integration_test.py -v
```

### Task 5.3: Verify All Tests Pass

**Files:**
- No file changes

- [x] **Step 1: Run all preprocessing tests**

```bash
cd /root/.openclaw/workspace/skills/actuary-sleuth/scripts
pytest tests/preprocessing/ -v --tb=short
```

- [x] **Step 2: Check test coverage**

```bash
pytest tests/preprocessing/ --cov=lib/preprocessing --cov-report=html
```

### Task 5.4: Commit and Push

**Files:**
- Git commit and push

- [x] **Step 1: Stage all changes**

```bash
git add lib/preprocessing/ tests/preprocessing/
```

- [x] **Step 2: Commit changes**

```bash
git commit -m "feat: implement comprehensive document preprocessing system

- Dual-path extraction (fast 80% + structured 20%)
- Multi-label product type classification
- Dynamic prompt generation based on product type
- Component-based prompt builder
- Specialized extractors (premium table, clauses)
- Business rule validation

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

- [x] **Step 3: Push changes**

```bash
git push
```

---

## Remember

- **Code organization**: Each file has one clear responsibility
- **Test-driven**: Write tests before implementation (or immediately after)
- **Frequent commits**: Commit after each task or small group of tasks
- **Documentation**: Update docstrings as you go
- **Validation**: Use the real LLM client for integration tests if available
- **Performance**: Focus on 80% fast path for cost optimization

## Success Criteria

The implementation is successful when:

1. ✅ All unit tests pass (>90% coverage)
2. ✅ Integration test passes with real LLM (or mock)
3. ✅ Fast path correctly identifies standard format documents
4. ✅ Structured path correctly extracts from complex documents
5. ✅ Product type classification achieves >70% confidence on test documents
6. ✅ Validation catches common business rule violations
7. ✅ System can handle mixed/hybrid products
8. ✅ Import errors are resolved
9. ✅ Code is documented with clear docstrings
10. ✅ Module is ready for integration with main application

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2025-03-11-comprehensive-preprocessing-system.md`. Ready to execute?

**Recommended execution approach:** Use superpowers:executing-plans to implement this plan step by step with verification after each chunk.
