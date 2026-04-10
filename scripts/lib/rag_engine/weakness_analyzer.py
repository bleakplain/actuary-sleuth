"""弱点驱动的样本补充建议 — 分析评估结果，识别薄弱领域。"""
from dataclasses import dataclass
from typing import List, Dict, Tuple

from .dataset_coverage import CoverageReport


@dataclass(frozen=True)
class WeaknessReport:
    failed_samples: List[Dict]
    weak_areas: List[Dict]
    suggestions: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            'failed_samples': self.failed_samples,
            'weak_areas': self.weak_areas,
            'suggestions': self.suggestions,
        }


def generate_weakness_report(
    eval_results: List[Dict],
    coverage: CoverageReport,
    recall_threshold: float = 0.5,
) -> WeaknessReport:
    failed = [
        r for r in eval_results
        if r.get('recall', 0.0) < recall_threshold
    ]

    area_stats: Dict[Tuple[str, str], List[float]] = {}
    for r in eval_results:
        topic = r.get('topic', 'unknown')
        qtype = r.get('question_type', 'unknown')
        key = (topic, qtype)
        area_stats.setdefault(key, []).append(r.get('recall', 0.0))

    weak_areas: List[Dict] = []
    for (topic, qtype), recalls in area_stats.items():
        avg_recall = sum(recalls) / len(recalls)
        if avg_recall < recall_threshold:
            weak_areas.append({
                'topic': topic,
                'question_type': qtype,
                'avg_recall': round(avg_recall, 3),
                'count': len(recalls),
            })

    weak_areas.sort(key=lambda x: x['avg_recall'])

    suggestions: List[str] = []
    for area in weak_areas:
        suggestions.append(
            f"优先在 '{area['topic']}' 补充 {area['question_type']} 类型样本"
            f"（当前 {area['count']} 条，平均 recall={area['avg_recall']}）"
        )

    for doc in coverage.blind_spots:
        suggestions.append(f"知识库文档 '{doc}' 无覆盖样本，需要补充")

    return WeaknessReport(
        failed_samples=failed,
        weak_areas=weak_areas,
        suggestions=suggestions,
    )
