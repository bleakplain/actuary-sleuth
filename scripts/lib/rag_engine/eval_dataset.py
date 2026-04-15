#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 评估数据集模块，覆盖事实题、多跳推理题、否定性查询、口语化查询、不可回答查询五种题型。
"""
import json
import logging
from dataclasses import dataclass, asdict, fields, field
from enum import Enum
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class QuestionType(Enum):
    FACTUAL = "factual"
    MULTI_HOP = "multi_hop"
    NEGATIVE = "negative"
    COLLOQUIAL = "colloquial"
    UNANSWERABLE = "unanswerable"


class ReviewStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"


@dataclass(frozen=True)
class RegulationRef:
    doc_name: str
    article: str
    excerpt: str
    chunk_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'RegulationRef':
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass(frozen=True)
class EvalSample:
    id: str
    question: str
    ground_truth: str
    evidence_docs: List[str]
    evidence_keywords: List[str]
    question_type: QuestionType
    difficulty: str
    topic: str
    regulation_refs: List[RegulationRef] = field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.PENDING
    reviewer: str = ""
    reviewed_at: str = ""
    review_comment: str = ""
    created_by: str = "human"
    kb_version: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d['question_type'] = self.question_type.value
        d['review_status'] = self.review_status.value
        d['regulation_refs'] = [r.to_dict() for r in self.regulation_refs]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'EvalSample':
        valid = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in valid}
        d['question_type'] = QuestionType(d['question_type'])
        if 'review_status' in d and d['review_status']:
            d['review_status'] = ReviewStatus(d['review_status'])
        else:
            d['review_status'] = ReviewStatus.PENDING
        if 'regulation_refs' in d and d['regulation_refs']:
            d['regulation_refs'] = [RegulationRef.from_dict(r) for r in d['regulation_refs']]
        else:
            d['regulation_refs'] = []
        return cls(**d)


def load_eval_dataset() -> List[EvalSample]:
    """从数据库加载评估数据集。数据库为空时返回空列表。"""
    try:
        from api.database import get_eval_samples as _get_db_samples
        db_rows = _get_db_samples()
        if not db_rows:
            return []
        samples = []
        for d in db_rows:
            d = dict(d)
            db_only = {'created_at', 'updated_at', 'reviewer', 'reviewed_at',
                       'review_comment', 'created_by', 'kb_version'}
            for k in db_only:
                d.pop(k, None)
            samples.append(EvalSample.from_dict(d))
        logger.info(f"从 DB 加载 {len(samples)} 条评测数据")
        return samples
    except Exception as e:
        logger.warning(f"从 DB 加载评测数据失败: {e}")
        return []


def save_eval_dataset(samples: List[EvalSample], path: str) -> None:
    """将评估数据集保存为 JSON 文件（需指定路径）。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    data = {
        'samples': [s.to_dict() for s in samples],
        'total': len(samples),
    }

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"评估数据集已保存: {path} ({len(samples)} 条)")
