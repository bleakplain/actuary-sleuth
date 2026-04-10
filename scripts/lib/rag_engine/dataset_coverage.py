"""知识库文档覆盖度评估 — 检查评测数据集对 KB 文档的引用覆盖情况。"""
from dataclasses import dataclass
from typing import List, Dict
from pathlib import Path

from .eval_dataset import EvalSample
from .evaluator import _normalize_doc_name


@dataclass(frozen=True)
class CoverageReport:
    total_samples: int
    docs: Dict[str, int]
    blind_spots: List[str]
    undercovered: List[str]
    distribution: Dict[str, int]

    def to_dict(self) -> Dict[str, object]:
        return {
            'total_samples': self.total_samples,
            'docs': self.docs,
            'blind_spots': self.blind_spots,
            'undercovered': self.undercovered,
            'distribution': self.distribution,
        }


def compute_coverage(
    samples: List[EvalSample],
    kb_docs: List[str],
    min_coverage: int = 5,
) -> CoverageReport:
    doc_counts: Dict[str, int] = {doc: 0 for doc in kb_docs}
    topic_counts: Dict[str, int] = {}

    kb_lookup: Dict[str, str] = {}
    for kb_doc in kb_docs:
        normalized = _normalize_doc_name(kb_doc)
        if normalized:
            kb_lookup[normalized] = kb_doc

    for sample in samples:
        for doc in sample.evidence_docs:
            doc_normalized = _normalize_doc_name(doc)
            if doc_normalized in kb_lookup:
                doc_counts[kb_lookup[doc_normalized]] += 1
        if sample.topic:
            topic_counts[sample.topic] = topic_counts.get(sample.topic, 0) + 1

    blind_spots = [doc for doc, count in doc_counts.items() if count == 0]
    undercovered = [doc for doc, count in doc_counts.items()
                    if 0 < count < min_coverage]

    return CoverageReport(
        total_samples=len(samples),
        docs=doc_counts,
        blind_spots=blind_spots,
        undercovered=undercovered,
        distribution=topic_counts,
    )


def get_kb_doc_names(regulations_dir: str) -> List[str]:
    reg_path = Path(regulations_dir)
    if not reg_path.exists():
        return []
    return sorted(f.name for f in reg_path.glob("*.md"))
