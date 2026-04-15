from lib.rag_engine.eval_rating import interpret_metric, generate_eval_summary, EVAL_THRESHOLDS, MetricThreshold


class TestMetricThreshold:
    def test_frozen(self):
        t = MetricThreshold('test', 0.9, 0.7, 'test metric')
        import dataclasses
        assert dataclasses.is_dataclass(t)
        assert t.__dataclass_params__.frozen

    def test_all_thresholds_have_required_fields(self):
        for t in EVAL_THRESHOLDS:
            assert len(t.name) > 0
            assert len(t.description) > 0


class TestInterpretMetric:
    def test_excellent_higher_is_better(self):
        result = interpret_metric('recall_at_k', 0.85)
        assert result['level'] == 'excellent'
        assert result['label'] == '优秀'
        assert result['suggestion'] == ''

    def test_good_higher_is_better(self):
        result = interpret_metric('recall_at_k', 0.65)
        assert result['level'] == 'good'
        assert result['label'] == '良好'

    def test_needs_improvement_higher_is_better(self):
        result = interpret_metric('recall_at_k', 0.3)
        assert result['level'] == 'needs_improvement'
        assert result['label'] == '需改进'
        assert '不足' in result['suggestion']

    def test_excellent_lower_is_better(self):
        result = interpret_metric('redundancy_rate', 0.05)
        assert result['level'] == 'excellent'

    def test_good_lower_is_better(self):
        result = interpret_metric('redundancy_rate', 0.2)
        assert result['level'] == 'good'

    def test_needs_improvement_lower_is_better(self):
        result = interpret_metric('redundancy_rate', 0.5)
        assert result['level'] == 'needs_improvement'
        assert '过高' in result['suggestion']

    def test_unknown_metric(self):
        result = interpret_metric('nonexistent_metric', 0.5)
        assert result['level'] == 'unknown'
        assert result['label'] == '未知指标'

    def test_rejection_rate_higher_is_better(self):
        result = interpret_metric('rejection_rate', 0.9)
        assert result['level'] == 'excellent'


class TestGenerateEvalSummary:
    def test_empty_report(self):
        summary = generate_eval_summary({})
        assert summary['excellent'] == []
        assert summary['good'] == []
        assert summary['needs_improvement'] == []

    def test_retrieval_metrics(self):
        report = {
            'retrieval': {
                'recall_at_k': 0.85,
                'precision_at_k': 0.3,
                'mrr': 0.9,
                'ndcg': 0.75,
                'redundancy_rate': 0.05,
                'context_relevance': 0.8,
            }
        }
        summary = generate_eval_summary(report)
        assert any(m['metric'] == 'recall_at_k' and m['label'] == '优秀' for m in summary['excellent'])
        assert any(m['metric'] == 'precision_at_k' and m['label'] == '需改进' for m in summary['needs_improvement'])

    def test_generation_metrics(self):
        report = {
            'generation': {
                'faithfulness': 0.9,
                'answer_relevancy': 0.75,
                'answer_correctness': 0.4,
            }
        }
        summary = generate_eval_summary(report)
        assert any(m['metric'] == 'faithfulness' and m['label'] == '优秀' for m in summary['excellent'])
        assert any(m['metric'] == 'answer_correctness' and m['label'] == '需改进' for m in summary['needs_improvement'])

    def test_ignores_non_numeric_values(self):
        report = {
            'retrieval': {
                'recall_at_k': 0.85,
                'by_type': {'factual': {}},
            }
        }
        summary = generate_eval_summary(report)
        assert len(summary['excellent']) == 1

    def test_rounded_values(self):
        report = {'retrieval': {'recall_at_k': 0.856789}}
        summary = generate_eval_summary(report)
        assert summary['excellent'][0]['value'] == 0.857
