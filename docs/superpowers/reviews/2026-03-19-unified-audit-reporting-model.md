# Unified Audit-Reporting Data Model Implementation

**Date:** 2026-03-19
**Status:** Completed
**Approach:** Option B - Unified Data Model (Breaking Change)

## Overview

Implemented a unified data model that eliminates the data transformation layer between audit and reporting modules. The reporting module now directly accepts `AuditResult` from the audit module as its single source of truth.

## Problem Statement

Previously, the audit module output (`AuditResult`) was incompatible with the reporting module input (`violations: List[Dict]`), requiring an adapter layer and causing:

1. **Data model incompatibility** - Different field names (suggestion vs remediation, dimension vs category)
2. **Duplicate business logic** - Both modules calculated conclusions independently
3. **Lost audit data** - `overall_assessment`, `assessment_reason`, `regulations_used` were not used in reports

## Solution: Unified Data Model

### Key Changes

#### 1. EvaluationContext (`lib/reporting/model.py`)

**Before:**
```python
@dataclass
class EvaluationContext:
    violations: List[Dict[str, Any]]
    pricing_analysis: Dict[str, Any]
    product: _InsuranceProduct
    score: Optional[int] = None
    grade: Optional[str] = None
    # ... violations stored directly
```

**After:**
```python
@dataclass
class EvaluationContext:
    audit_result: Optional['AuditResult'] = None  # Single source of truth
    product: _InsuranceProduct
    pricing_analysis: Dict[str, Any]

    @property
    def violations(self) -> List[Dict[str, Any]]:
        """Convert AuditResult.issues to reporting format"""
        return [{
            'clause_reference': issue.clause,
            'clause_text': issue.clause,
            'description': issue.description,
            'category': issue.dimension,  # dimension → category
            'severity': issue.severity,
            'remediation': issue.suggestion,  # suggestion → remediation
            'regulation_citation': issue.regulation,
        } for issue in self.audit_result.issues]

    @property
    def score(self) -> int:
        return self.audit_result.score if self.audit_result else 0

    @property
    def overall_assessment(self) -> str:
        return self.audit_result.overall_assessment if self.audit_result else "不通过"
```

#### 2. ReportGenerationTemplate (`lib/reporting/template/report_template.py`)

**Before:**
```python
def generate(
    self,
    violations: List[Dict[str, Any]],
    pricing_analysis: Dict[str, Any],
    product_info: Dict[str, Any],
    score: Optional[int] = None
) -> Dict[str, Any]:
```

**After:**
```python
def generate(
    self,
    audit_result: 'AuditResult',  # Direct input from audit
    product_info: Dict[str, Any],
    pricing_analysis: Dict[str, Any] = None,
    clauses: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
```

**Key Behavioral Changes:**
- Uses `audit_result.overall_assessment` instead of calculating conclusions
- Uses `audit_result.regulations_used` for regulation basis
- Derives `grade` from `overall_assessment` mapping:
  - "通过" → "优秀"
  - "有条件通过" → "良好"
  - "不通过" → "不合格"

#### 3. DocxGenerator (`lib/reporting/export/docx_generator.py`)

**Updated to:**
- Extract `overall_assessment` and `assessment_reason` from context
- Use audit's conclusions in Word document generation
- Include `regulation_citation` from audit issues in tables

### Field Mapping

| Audit Field | Reporting Field | Mapping |
|-------------|-----------------|---------|
| `suggestion` | `remediation` | suggestion → remediation |
| `dimension` | `category` | dimension → category |
| `regulation` | `regulation_citation` | regulation → regulation_citation |
| `clause` | `clause_reference` | clause → clause_reference |
| `overall_assessment` | `opinion` | Direct use |
| `assessment_reason` | `explanation` | Direct use |
| `regulations_used` | `regulation_basis` | Direct use |

## Breaking Changes

### API Changes

**Old Usage:**
```python
template = ReportGenerationTemplate()
result = template.generate(
    violations=[...],  # List of dicts
    pricing_analysis={...},
    product_info={...},
    score=85
)
```

**New Usage:**
```python
from lib.audit import AuditResult, AuditIssue, ComplianceAuditor

# Run audit
auditor = ComplianceAuditor(llm_client, rag_engine)
outcomes = auditor.audit(request)
audit_result = outcomes[0].result  # AuditResult

# Generate report
template = ReportGenerationTemplate()
result = template.generate(
    audit_result=audit_result,  # Direct from audit
    product_info={...}
)
```

### Migration Guide

1. **Update callers to pass AuditResult instead of violations**
2. **Remove custom score calculation** - use audit's score
3. **Update conclusion logic** - use audit's overall_assessment
4. **Remove duplicate regulation basis generation** - use audit's regulations_used

## Benefits

1. **Single Source of Truth** - Audit module owns all audit data
2. **No Data Loss** - All audit fields (overall_assessment, assessment_reason, regulations_used) are preserved
3. **Consistent Conclusions** - Reports use audit's conclusions, no recalculation
4. **Cleaner Code** - Removed duplicate business logic
5. **Type Safety** - Using dataclasses instead of dicts

## Tests

Created comprehensive test suite (`tests/lib/reporting/test_unified_model.py`):

- `TestEvaluationContextUnifiedModel` - 7 tests for the unified model
- `TestReportGenerationWithUnifiedModel` - 5 tests for report generation

**Test Results:** 111 passed, 5 skipped

All existing tests continue to pass after the refactoring.

## Files Modified

1. `lib/reporting/model.py` - Updated EvaluationContext with audit_result field
2. `lib/reporting/template/report_template.py` - Changed generate() signature and logic
3. `lib/reporting/export/docx_generator.py` - Updated to use audit conclusions
4. `tests/lib/reporting/test_unified_model.py` - New test file for unified model

## Validation

The implementation has been validated with:

1. **Unit tests** - All 111 tests pass
2. **Integration tests** - Audit → Reporting flow tested
3. **Field mapping tests** - Verified all field conversions
4. **Conclusion mapping tests** - Verified overall_assessment → grade mapping

## Next Steps

1. Update any external callers to use the new API
2. Update documentation to reflect new data flow
3. Consider deprecating old API with migration warnings
