#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评估指标阈值和解读指南"""
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class MetricThreshold:
    name: str
    excellent: float
    good: float
    description: str
    higher_is_better: bool = True


EVAL_THRESHOLDS: List[MetricThreshold] = [
    MetricThreshold('recall_at_k', 0.8, 0.6, '关键文档是否被检索到', True),
    MetricThreshold('precision_at_k', 0.7, 0.5, '检索结果中相关文档比例', True),
    MetricThreshold('mrr', 0.8, 0.5, '第一个正确结果的排名', True),
    MetricThreshold('ndcg', 0.7, 0.5, '整体排序质量', True),
    MetricThreshold('redundancy_rate', 0.1, 0.3, '结果冗余程度', False),
    MetricThreshold('faithfulness', 0.85, 0.7, '答案是否有检索依据', True),
    MetricThreshold('answer_relevancy', 0.85, 0.7, '是否回答了用户问题', True),
    MetricThreshold('answer_correctness', 0.8, 0.6, '答案与标准答案的一致性', True),
    MetricThreshold('context_relevance', 0.7, 0.5, '检索内容与问题相关程度', True),
    MetricThreshold('rejection_rate', 0.8, 0.6, '无答案问题正确拒绝比例', True),
]


def interpret_metric(name: str, value: float) -> Dict[str, str]:
    for t in EVAL_THRESHOLDS:
        if t.name == name:
            if t.higher_is_better:
                if value >= t.excellent:
                    return {'level': 'excellent', 'label': '优秀', 'suggestion': ''}
                elif value >= t.good:
                    return {'level': 'good', 'label': '良好', 'suggestion': f'{t.description}可进一步优化'}
                else:
                    return {'level': 'needs_improvement', 'label': '需改进', 'suggestion': f'{t.description}不足，需重点优化'}
            else:
                if value <= t.excellent:
                    return {'level': 'excellent', 'label': '优秀', 'suggestion': ''}
                elif value <= t.good:
                    return {'level': 'good', 'label': '良好', 'suggestion': f'{t.description}可进一步降低'}
                else:
                    return {'level': 'needs_improvement', 'label': '需改进', 'suggestion': f'{t.description}过高，浪费上下文窗口'}
    return {'level': 'unknown', 'label': '未知指标', 'suggestion': ''}


def generate_eval_summary(report_dict: Dict) -> Dict[str, List]:
    summary: Dict[str, List] = {'excellent': [], 'good': [], 'needs_improvement': []}
    for section in ['retrieval', 'generation']:
        metrics = report_dict.get(section, {})
        for key, value in metrics.items():
            if not isinstance(value, (int, float)):
                continue
            interp = interpret_metric(key, value)
            if interp['level'] == 'unknown':
                continue
            summary[interp['level']].append({
                'metric': key,
                'value': round(value, 3),
                'label': interp['label'],
                'suggestion': interp['suggestion'],
            })
    return summary
