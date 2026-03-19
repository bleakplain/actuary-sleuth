# Audit & Reporting Module Deep Review

**Date:** 2026-03-19
**Purpose:** Comprehensive review of audit and reporting modules
**Constraint:** Do not change audit report basic structure and content

## Module Architecture Overview

```
                    ┌─────────────────────────────────────────────┐
                    │              Audit Module                      │
                    │  ┌─────────────────────────────────────────┐   │
                    │  │   ComplianceAuditor                  │   │
                    │  │   - audit(request) → List[AuditOutcome] │   │
                    │  │   - _audit(clause, regulations)        │   │
                    │  │   - _parse_audit_response()          │   │
                    │  │   - _create_audit_result()          │   │
                    │  │   - _search_regulations()          │   │
                    │  │   - _build_product_context()       │   │
                    │  │   - _build_regulations_reference() │   │
                    │  └─────────────────────────────────────────┘   │
                    └─────────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────────────┐
                    │           Reporting Module                     │
                    │  ┌─────────────────────────────────────────┐   │
                    │  │  ReportGenerationTemplate              │   │
                    │  │  - generate(violations, pricing,       │   │
                    │  │            product_info, score)       │   │
                    │  │  - _calculate_score()                │   │
                    │  │  - _calculate_grade()                │   │
                    │  │  - _summarize_violations()           │   │
                    │  │  - _generate_content()               │   │
                    │  │  - _generate_blocks()                │   │
                    │  └─────────────────────────────────────────┘   │
                    │                                                    │
                    │  ┌─────────────────────────────────────────┐   │
                    │  │  _DocxGenerator                         │   │
                    │  │  - generate(context, title)             │   │
                    │  │  - _generate_docx_js_code()           │   │
                    │  │  - _generate_conclusion_section()     │   │
                    │  │  - _generate_details_section()        │   │
                    │  │  - _generate_suggestions_section()    │   │
                    │  └─────────────────────────────────────────┘   │
                    │                                                    │
                    │  ┌─────────────────────────────────────────┐   │
                    │  │  DocxExporter                           │   │
                    │  │  - export(audit_result)               │   │
                    │  │  - save_report()                       │   │
                    │  └─────────────────────────────────────────┘   │
                    └─────────────────────────────────────────────┘
```

## Data Flow Gap Analysis

### Current State: Two Separate Data Models

| Module | Input Data Model | Output Data Model |
|--------|------------------|------------------|
| **Audit** | `AuditRequest` → `List[AuditOutcome]` | `AuditResult`, `AuditIssue` |
| **Reporting** | `violations`, `pricing_analysis`, `product_info`, `score` | Word document |

### Data Mapping Issues

#### 1. AuditOutput → ReportingInput Gap

**Audit Output Structure:**
```python
AuditResult:
  - overall_assessment: "通过/有条件通过/不通过"
  - assessment_reason: "评定依据说明"
  - issues: List[AuditIssue]
    - clause: str
    - severity: "high/medium/low"
    - dimension: "合规性/信息披露/条款清晰度/费率合理性"
    - regulation: str
    - description: str
    - suggestion: str
  - score: 0-100
  - summary: str
  - regulations_used: List[str]
```

**Reporting Input Structure:**
```python
ReportGenerationTemplate.generate():
  - violations: List[Dict[str, Any]]  # Required
    - clause_reference: str
    - clause_text: str
    - description: str
    - category: str
    - severity: str
    - remediation: str
    - regulation_citation: str (optional)
  - pricing_analysis: Dict[str, Any]
  - product_info: Dict[str, Any]
  - score: int (optional)
```

#### 2. Field Mapping Requirements

| Audit Field | Reporting Field | Mapping Complexity |
|-------------|-----------------|-------------------|
| `issues[].clause` | `violations[].clause_reference` | ⚠️ Different format |
| `issues[].description` | `violations[].description` | ✅ Direct |
| `issues[].severity` | `violations[].severity` | ✅ Direct |
| `issues[].dimension` | `violations[].category` | ⚠️ Semantic mapping |
| `issues[].regulation` | `violations[].regulation_citation` | ⚠️ Different naming |
| `issues[].suggestion` | `violations[].remediation` | ⚠️ Different naming |
| `result.overall_assessment` | ❌ Not used | ❌ Missing field |
| `result.assessment_reason` | ❌ Not used | ❌ Missing field |
| `result.regulations_used` | ❌ Not used | ❌ Missing field |

### Critical Gap: overall_assessment Not Used

**Problem:** The reporting template calculates its own `opinion` and `grade` based on score and violation counts, **ignoring** `overall_assessment` from the audit result.

**Impact:** Inconsistent determination between audit and reporting layers.

**Current Reporting Logic (`_generate_conclusion_text`):**
```python
if high_count > 0:
    opinion = "不推荐上会"
elif score >= 90:
    opinion = "推荐通过"
elif score >= 75:
    opinion = "条件推荐"
elif score >= 60:
    opinion = "需补充材料"
else:
    opinion = "不予推荐"
```

**Audit Output:**
```python
overall_assessment: "通过/有条件通过/不通过"
```

**Issue:** Two different determination systems can produce conflicting results.

## Issues Found

### P0 - Critical Issues

#### 1. Data Model Incompatibility
**Problem:** Audit output (`AuditResult`) cannot be directly used as reporting input (`violations` list).

**Impact:** Requires adapter/converter layer between audit and reporting.

**Required Fields Missing for Reporting:**
- `clause_reference` (audit has `clause` but different format)
- `category` (audit has `dimension`, needs semantic mapping)
- `remediation` (audit has `suggestion`, needs renaming)

**Missing Audit Fields in Reporting:**
- `overall_assessment` - Critical audit determination ignored
- `assessment_reason` - Audit justification ignored
- `regulations_used` - Legal citations not used

---

### P1 - High Priority Issues

#### 2. Duplicate Business Logic
**Problem:** Both audit and reporting calculate conclusions independently.

**Audit Module:**
```python
overall_assessment: "通过/有条件通过/不通过"
assessment_reason: "产品条款完全符合相关监管要求，无重大合规风险"
```

**Reporting Module:**
```python
opinion = "推荐通过/条件推荐/需补充材料/不予推荐/不推荐上会"
explanation = "产品符合所有监管要求，未发现违规问题"
```

**Impact:** Two different conclusion systems create confusion.

---

#### 3. Severity Value Inconsistency
**Audit:** `"high"`, `"medium"`, `"low"` (English)
**Reporting:** `"high"`, `"medium"`, `"low"` (same, but inconsistent handling)

**Issue:** Reporting uses violation counts to determine outcomes, audit uses structured assessment.

---

### P2 - Medium Priority Issues

#### 4. Regulation Citation Not Propagated
**Audit:** `regulations_used: List[str]` - Full regulation references
**Reporting:** Uses hardcoded regulation map in `_get_regulation_basis()`

**Impact:** Dynamic regulations from audit not used in report.

---

#### 5. Missing Product Context Link
**Audit:** `AuditRequest` has full `Product`, `Coverage`, `Premium`
**Reporting:** Uses simplified `_InsuranceProduct` with limited fields

**Missing in Reporting:**
- `waiting_period`
- `age_min`, `age_max`
- `coverage.scope`, `coverage.deductible`
- `premium.payment_method`, `premium.payment_period`

---

### P3 - Low Priority Issues

#### 6. Code Duplication
Both `_DocxGenerator` and `ReportGenerationTemplate` have:
- `_generate_conclusion_text()` - duplicated logic
- `_get_regulation_basis()` - duplicated method
- `_get_score_description()` - duplicated method

---

#### 7. Magic Numbers in Reporting
```python
SEVERITY_PENALTY = {'high': 20, 'medium': 10, 'low': 5}
GRADE_THRESHOLDS = [(90, '优秀'), (75, '良好'), (60, '合格')]
HIGH_VIOLATIONS_LIMIT = 20
MEDIUM_VIOLATIONS_LIMIT = 10
```

These should be documented constants.

---

#### 8. Inconsistent Field Naming
| Audit | Reporting | Issue |
|-------|-----------|-------|
| `suggestion` | `remediation` | Same concept, different names |
| `dimension` | `category` | Semantic mapping needed |
| `clause` | `clause_reference` | Format difference |
| `regulation` | `regulation_citation` | Naming difference |

---

## Recommendations

### Option A: Create Adapter Layer (Recommended)

Create `AuditToReportAdapter` to convert audit output to reporting input:

```python
@dataclass
class AuditToReportAdapter:
    """Convert audit output to reporting input format"""

    def convert_outcomes_to_report_input(
        self,
        outcomes: List[AuditOutcome],
        request: AuditRequest
    ) -> Tuple[List[Dict], Dict, Dict, int]:
        """
        Convert audit outcomes to reporting format

        Returns:
            (violations, pricing_analysis, product_info, score)
        """
        violations = []
        for outcome in outcomes:
            if outcome.result and outcome.result.issues:
                for issue in outcome.result.issues:
                    violations.append({
                        'clause_reference': issue.clause,
                        'clause_text': issue.clause,  # Same as reference
                        'description': issue.description,
                        'category': self._map_dimension_to_category(issue.dimension),
                        'severity': issue.severity,
                        'remediation': issue.suggestion,
                        'regulation_citation': issue.regulation
                    })

        product_info = {
            'product_name': request.product.name,
            'product_type': self._get_product_type_name(request.product.category),
            'insurance_company': request.product.company,
        }

        # Calculate score from first successful outcome
        score = next(
            (outcome.result.score for outcome in outcomes
             if outcome.result and outcome.result.score is not None),
            100
        )

        return violations, {}, product_info, score

    def _map_dimension_to_category(self, dimension: str) -> str:
        """Map audit dimension to reporting category"""
        mapping = {
            '合规性': '产品条款表述',
            '信息披露': '产品责任设计',
            '条款清晰度': '产品条款表述',
            '费率合理性': '产品费率厘定及精算假设',
        }
        return mapping.get(dimension, '产品条款表述')
```

**Pros:**
- Keeps audit module unchanged
- Keeps reporting module unchanged
- Single conversion point

**Cons:**
- Requires new code
- Adds runtime overhead

---

### Option B: Unify Data Model (Breaking Change)

Create shared data model used by both audit and reporting.

**Pros:**
- Single source of truth
- No conversion overhead
- Consistent field naming

**Cons:**
- Breaking change to both modules
- Requires extensive refactoring
- May affect existing users

---

### Option C: Modify Reporting to Use Audit Output (Minimal Change)

Update `ReportGenerationTemplate` to accept `AuditResult` directly.

**Pros:**
- Eliminates data conversion
- Uses audit's rich structured output
- Maintains audit's conclusions

**Cons:**
- Requires updating reporting module
- Changes report generation logic

---

## Recommended Action Plan

### Phase 1: Create Adapter (Immediate)

1. Create `AuditToReportAdapter` class
2. Add conversion method `audit_to_report_input()`
3. Update `report.py` to use adapter

### Phase 2: Unify Conclusions (Medium Priority)

1. Standardize on `overall_assessment` from audit
2. Update reporting to use audit's conclusion
3. Deprecate reporting's own calculation

### Phase 3: Field Naming Consistency (Low Priority)

1. Align field names across modules
2. Use audit field names as source of truth
3. Update reporting to use audit names

## Test Status

**Current Tests:**
- Audit module: 66 tests passing
- Reporting module: No direct tests found
- Integration: No audit→reporting integration tests

**Needed:**
- Audit→reporting adapter tests
- End-to-end audit to report generation tests
- Data model consistency tests

## Summary

| Priority | Issue | Impact | Effort |
|----------|-------|--------|--------|
| P0 | Data model incompatibility | Blocking | Medium |
| P0 | overall_assessment not used | High | Low |
| P1 | Duplicate business logic | High | Medium |
| P2 | Regulation citation not propagated | Medium | Low |
| P3 | Code duplication | Low | Medium |
| P3 | Inconsistent field naming | Low | High |

**Recommended Approach:** Create adapter layer (Option A) to bridge audit and reporting without breaking existing functionality.
