const METRIC_LABELS: Record<string, { label: string; tooltip: string }> = {
  precision_at_k: { label: 'Precision@K', tooltip: '前K个检索结果中相关文档的比例' },
  recall_at_k: { label: 'Recall@K', tooltip: '相关文档中被检索到的比例' },
  mrr: { label: 'MRR', tooltip: '第一个相关结果的排名倒数的均值 (Mean Reciprocal Rank)' },
  ndcg: { label: 'NDCG', tooltip: '归一化折损累计增益，衡量排序质量 (Normalized DCG)' },
  redundancy_rate: { label: '冗余率', tooltip: '检索结果中重复内容的比例，越低越好' },
  context_relevance: { label: '上下文相关性', tooltip: '检索内容与问题的相关程度' },
  faithfulness: { label: '忠实度', tooltip: '生成答案是否有检索依据支撑 (Faithfulness)' },
  answer_relevancy: { label: '答案相关性', tooltip: '生成答案与用户问题的相关程度' },
  answer_correctness: { label: '答案正确性', tooltip: '生成答案与标准答案的一致性' },
  avg_score: { label: '平均分', tooltip: '综合评分的均值' },
  total_samples: { label: '样本数', tooltip: '评测样本总数' },
  failed_samples: { label: '失败样本', tooltip: '评测过程中失败的样本数' },
};

export interface MetricMeta {
  label: string;
  tooltip: string;
}

export function resolveMetricMeta(key: string, k?: number): MetricMeta {
  const meta = METRIC_LABELS[key];
  if (!meta) return { label: key, tooltip: '' };
  const kStr = k && (key === 'precision_at_k' || key === 'recall_at_k') ? `@${k}` : '';
  if (kStr) {
    return {
      label: meta.label.replace('@K', kStr),
      tooltip: meta.tooltip.replace('@K', kStr),
    };
  }
  return meta;
}

export function stripCategoryPrefix(name: string): string {
  const dotIndex = name.indexOf('.');
  return dotIndex > 0 ? name.slice(dotIndex + 1) : name;
}
