"""合规检查测试验证流程"""
import json
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any


@dataclass
class ValidationSample:
    id: str
    document_path: str
    human_result: Dict[str, Any]


@dataclass
class ClauseMatch:
    clause_number: str
    auto_status: str
    human_status: str
    match: bool


@dataclass
class ValidationResult:
    sample_id: str
    clause_accuracy: float
    status_accuracy: float
    mismatches: List[ClauseMatch]


@dataclass
class ValidationReport:
    total_samples: int
    avg_clause_accuracy: float
    avg_status_accuracy: float
    results: List[ValidationResult]


def compare_clause_level(auto_result: Dict, human_result: Dict) -> ValidationResult:
    """条款级对比：按条款编号整体判定"""
    auto_items = {item["clause_number"]: item for item in auto_result.get("items", []) if item.get("clause_number")}
    human_items = {item["clause_number"]: item for item in human_result.get("items", []) if item.get("clause_number")}

    all_clauses = set(auto_items.keys()) | set(human_items.keys())
    mismatches = []
    correct = 0

    for clause_num in all_clauses:
        auto_item = auto_items.get(clause_num, {})
        human_item = human_items.get(clause_num, {})

        auto_status = auto_item.get("status", "missing")
        human_status = human_item.get("status", "missing")

        if auto_status == human_status:
            correct += 1
            mismatches.append(ClauseMatch(
                clause_number=clause_num,
                auto_status=auto_status,
                human_status=human_status,
                match=True,
            ))
        else:
            mismatches.append(ClauseMatch(
                clause_number=clause_num,
                auto_status=auto_status,
                human_status=human_status,
                match=False,
            ))

    accuracy = correct / len(all_clauses) if all_clauses else 0.0

    return ValidationResult(
        sample_id="",
        clause_accuracy=accuracy,
        status_accuracy=accuracy,
        mismatches=mismatches,
    )


def load_fixture(fixture_path: str) -> Dict[str, Any]:
    """加载测试数据"""
    path = Path(fixture_path)
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="合规检查测试验证")
    parser.add_argument("--fixtures", type=str, default="scripts/tests/fixtures/compliance")
    parser.add_argument("--output", type=str, default="validation_report.json")
    args = parser.parse_args()

    fixtures_dir = Path(args.fixtures)
    if not fixtures_dir.exists():
        print(f"Fixtures directory not found: {fixtures_dir}")
        return

    results: List[ValidationResult] = []
    for fixture_file in fixtures_dir.glob("*.json"):
        fixture = load_fixture(str(fixture_file))
        if not fixture:
            continue

        human_result = fixture.get("human_result", {})
        auto_result = fixture.get("auto_result", {})

        if human_result and auto_result:
            result = compare_clause_level(auto_result, human_result)
            result.sample_id = fixture_file.stem
            results.append(result)

    if not results:
        print("No valid fixtures found")
        return

    avg_clause_accuracy = sum(r.clause_accuracy for r in results) / len(results)
    avg_status_accuracy = sum(r.status_accuracy for r in results) / len(results)

    report = ValidationReport(
        total_samples=len(results),
        avg_clause_accuracy=avg_clause_accuracy,
        avg_status_accuracy=avg_status_accuracy,
        results=results,
    )

    report_dict = {
        "total_samples": report.total_samples,
        "avg_clause_accuracy": report.avg_clause_accuracy,
        "avg_status_accuracy": report.avg_status_accuracy,
        "results": [
            {
                "sample_id": r.sample_id,
                "clause_accuracy": r.clause_accuracy,
                "status_accuracy": r.status_accuracy,
                "mismatches": [asdict(m) for m in r.mismatches],
            }
            for r in report.results
        ],
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(report_dict, f, ensure_ascii=False, indent=2)

    print(f"Validation report saved to {args.output}")
    print(f"Total samples: {report.total_samples}")
    print(f"Avg clause accuracy: {report.avg_clause_accuracy:.2%}")
    print(f"Avg status accuracy: {report.avg_status_accuracy:.2%}")


if __name__ == "__main__":
    main()
