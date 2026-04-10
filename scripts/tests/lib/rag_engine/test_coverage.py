from lib.rag_engine.eval_dataset import EvalSample, QuestionType
from lib.rag_engine.dataset_coverage import compute_coverage, get_kb_doc_names, CoverageReport


def _make_sample(id: str, doc: str, topic: str = "健康保险") -> EvalSample:
    return EvalSample(
        id=id,
        question=f"问题_{id}",
        ground_truth="答案",
        evidence_docs=[doc],
        evidence_keywords=["关键词"],
        question_type=QuestionType.FACTUAL,
        difficulty="easy",
        topic=topic,
    )


class TestComputeCoverage:

    def test_coverage_all_covered(self):
        samples = [
            _make_sample("s1", "01_保险法.md"),
            _make_sample("s2", "05_健康保险产品开发.md"),
            _make_sample("s3", "06_健康保险管理办法.md"),
        ]
        kb_docs = ["01_保险法.md", "05_健康保险产品开发.md", "06_健康保险管理办法.md"]
        report = compute_coverage(samples, kb_docs)
        assert len(report.blind_spots) == 0
        assert report.docs["01_保险法.md"] == 1

    def test_coverage_blind_spots(self):
        samples = [
            _make_sample("s1", "01_保险法.md"),
        ]
        kb_docs = ["01_保险法.md", "05_健康保险产品开发.md", "06_健康保险管理办法.md"]
        report = compute_coverage(samples, kb_docs)
        assert len(report.blind_spots) == 2
        assert "05_健康保险产品开发.md" in report.blind_spots
        assert "06_健康保险管理办法.md" in report.blind_spots

    def test_coverage_undercovered(self):
        samples = [
            _make_sample("s1", "01_保险法.md"),
            _make_sample("s2", "01_保险法.md"),
            _make_sample("s3", "05_健康保险产品开发.md"),
        ]
        kb_docs = ["01_保险法.md", "05_健康保险产品开发.md"]
        report = compute_coverage(samples, kb_docs, min_coverage=5)
        assert "01_保险法.md" in report.undercovered
        assert "05_健康保险产品开发.md" in report.undercovered

    def test_coverage_empty_dataset(self):
        report = compute_coverage(
            [],
            ["01_保险法.md", "05_健康保险产品开发.md"],
        )
        assert report.total_samples == 0
        assert len(report.blind_spots) == 2

    def test_coverage_topic_distribution(self):
        samples = [
            _make_sample("s1", "01_保险法.md", "健康保险"),
            _make_sample("s2", "05_健康保险产品开发.md", "健康保险"),
            _make_sample("s3", "07_分红型人身保险.md", "分红保险"),
        ]
        kb_docs = ["01_保险法.md", "05_健康保险产品开发.md", "07_分红型人身保险.md"]
        report = compute_coverage(samples, kb_docs)
        assert report.distribution["健康保险"] == 2
        assert report.distribution["分红保险"] == 1

    def test_coverage_to_dict(self):
        report = compute_coverage([], ["01_保险法.md"])
        d = report.to_dict()
        assert 'total_samples' in d
        assert 'blind_spots' in d
        assert 'undercovered' in d
        assert 'distribution' in d


class TestGetKbDocNames:

    def test_nonexistent_dir(self):
        result = get_kb_doc_names("/nonexistent/path")
        assert result == []

    def test_empty_dir(self, tmp_path):
        result = get_kb_doc_names(str(tmp_path))
        assert result == []
