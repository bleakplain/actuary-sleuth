from lib.rag_engine.weakness_analyzer import generate_weakness_report
from lib.rag_engine.dataset_coverage import CoverageReport


class TestWeaknessReport:

    def test_failed_samples(self):
        eval_results = [
            {'recall': 0.0, 'topic': '健康保险', 'question_type': 'factual'},
            {'recall': 0.3, 'topic': '健康保险', 'question_type': 'factual'},
            {'recall': 0.8, 'topic': '分红保险', 'question_type': 'factual'},
        ]
        coverage = CoverageReport(
            total_samples=3,
            docs={"01_保险法.md": 1, "05_健康保险产品开发.md": 1, "07_分红型人身保险.md": 1},
            blind_spots=[],
            undercovered=[],
            distribution={},
        )
        report = generate_weakness_report(eval_results, coverage)
        assert len(report.failed_samples) == 2

    def test_weak_areas_identification(self):
        eval_results = [
            {'recall': 0.2, 'topic': '健康保险', 'question_type': 'factual'},
            {'recall': 0.3, 'topic': '健康保险', 'question_type': 'factual'},
            {'recall': 0.8, 'topic': '分红保险', 'question_type': 'factual'},
        ]
        coverage = CoverageReport(
            total_samples=3,
            docs={},
            blind_spots=[],
            undercovered=[],
            distribution={},
        )
        report = generate_weakness_report(eval_results, coverage)
        assert len(report.weak_areas) == 1
        assert report.weak_areas[0]['topic'] == '健康保险'
        assert report.weak_areas[0]['avg_recall'] == 0.25

    def test_suggestions_include_blind_spots(self):
        eval_results = [
            {'recall': 0.8, 'topic': '健康保险', 'question_type': 'factual'},
        ]
        coverage = CoverageReport(
            total_samples=1,
            docs={"01_保险法.md": 1, "05_健康保险产品开发.md": 0},
            blind_spots=["05_健康保险产品开发.md"],
            undercovered=[],
            distribution={},
        )
        report = generate_weakness_report(eval_results, coverage)
        assert any("05_健康保险产品开发.md" in s for s in report.suggestions)

    def test_suggestions_include_weak_areas(self):
        eval_results = [
            {'recall': 0.1, 'topic': '健康保险', 'question_type': 'factual'},
        ]
        coverage = CoverageReport(
            total_samples=1,
            docs={},
            blind_spots=[],
            undercovered=[],
            distribution={},
        )
        report = generate_weakness_report(eval_results, coverage)
        assert any("健康保险" in s for s in report.suggestions)

    def test_no_failures_no_suggestions(self):
        eval_results = [
            {'recall': 0.9, 'topic': '健康保险', 'question_type': 'factual'},
        ]
        coverage = CoverageReport(
            total_samples=1,
            docs={"01_保险法.md": 1},
            blind_spots=[],
            undercovered=[],
            distribution={},
        )
        report = generate_weakness_report(eval_results, coverage)
        assert len(report.failed_samples) == 0
        assert len(report.weak_areas) == 0
        assert len(report.suggestions) == 0

    def test_to_dict(self):
        report = generate_weakness_report(
            [],
            CoverageReport(total_samples=0, docs={}, blind_spots=[], undercovered=[], distribution={}),
        )
        d = report.to_dict()
        assert 'failed_samples' in d
        assert 'weak_areas' in d
        assert 'suggestions' in d
