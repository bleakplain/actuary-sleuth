# Actuary Sleuth - AI 精算审核助手

## Build And Test
- **Install**: `pip install -r requirements.txt`
- **Dev**: `python3 scripts/audit.py --documentUrl <feishu_url>`
- **Test**: `pytest scripts/tests/`
- **Type Check**: `mypy scripts/lib/`

## Architecture Boundaries
- **Entry points**: `scripts/*.py`
- **Domain logic**: `scripts/lib/audit/`, `scripts/lib/preprocessing`, `scripts/lib/reporting`
- **Data models**: `scripts/lib/common/models.py`, `scripts/lib/common/audit.py`
- **Utilities**: `scripts/lib/common/`
- **Do not** put persistence in domain modules → use `scripts/lib/common/database.py`
- **Do not** put LLM logic in domain modules → use `scripts/lib/llm/`

## NEVER
- Modify `scripts/.env`, `scripts/config/settings.json` or CI secrets without approval
- Remove feature flags/constants without searching all call sites
- Commit without running tests (`pytest scripts/tests/`)
- Add `from lib.exceptions import *` wildcard imports
- Add sys.path manipulation in library files
- Create new service packages, reuse existing `scripts/lib/` structure

## ALWAYS
- Show diff before committing (`git diff HEAD`)
- Run tests before pushing
- Use type annotations for public APIs
- Use frozen dataclass for data models
- Archive exceptions to corresponding modules

## Code Style

### Naming
- Functions: business semantics, verb-noun组合 (`fetch_feishu_document`, `execute_preprocess`)
- Classes: nouns (`AuditService`, `DocumentFetcher`, `Product`)
- Private: prefix `_` (`_managed_query`)

### OOP Principles
- Hide implementation: `result.get_clauses()` not `result['clauses']`
- Bool check as property: `if result.success:` not `if result.is_success():`
- Single responsibility: one class, one purpose

### API Design
- Complex internal, simple external
```python
# ✓ Good
def execute_audit(document_url: str) -> AuditResult:
    document_content = fetch_feishu_document(document_url)
    ...

# ✗ Bad
def execute_audit(document_url: str, document_content: str) -> AuditResult:
    """User must fetch content themselves"""
```

### Data Models
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PreprocessedResult:
    audit_id: str
    document_url: str
    timestamp: datetime
    product: Product
    clauses: List[Dict[str, Any]]
```

### Exceptions
```python
# lib/exceptions.py - base
class ActuarySleuthException(Exception): pass

# lib/common/exceptions.py - re-export
from lib.exceptions import ActuarySleuthException, DatabaseError

# lib/preprocessing/exceptions.py - module specific
class DocumentFetchError(ActuarySleuthException): pass
```

## Core Flow

```
fetch_feishu_document → execute_preprocess → check_negative_list
→ analyze_pricing → calculate_result → save_db → export_report
```

## Module Organization
- **lib/common/** - models, database, exceptions, constants, shared utilities
- **lib/audit/** - audit orchestration
- **lib/preprocessing/** - document fetching, extraction
- **lib/reporting/** - report generation, export
- **lib/rag_engine/** - vector search, QA
- **lib/llm/** - LLM client abstraction

## Development

### Add check rule
Insert into `negative_list` table (supports keyword & regex)

### Add product type
1. Add to `ProductCategory` enum in `lib/common/models.py`
2. Add mapping in `lib/common/product_type.py`

### Add LLM client
1. Create client file in `lib/llm/`
2. Implement `lib/llm/base.py` interface
3. Register in `lib/llm/factory.py`
4. Configure in `scripts/config/settings.json`

### Modify report template
Edit `lib/reporting/template.py` → `ReportGenerationTemplate` class

## Configuration
Located at `scripts/config/settings.json`, overrideable via env vars.

```json
{
  "llm": {"default_provider": "ollama", "models": {...}},
  "feishu": {...},
  "report": {...}
}
```

## Constraints Summary
1. Business-semantic function names
2. Hide implementation, use object methods
3. Complex internal, simple external API
4. Specific exceptions, archived to modules
5. Frozen dataclass, metadata included, avoid nesting
6. No new service packages, reuse lib/ structure
7. Tests must pass before commit
8. Self-documenting code, no redundant comments
10. Avoid unnecessary type conversions
12. Minimal parameters, use metadata
13. Constants in `lib/common/constants.py`
