import pytest

from lib.rag_engine.sample_synthesizer import SynthQA, SynthConfig, SynthResult
from lib.rag_engine.eval_dataset import EvalSample, QuestionType


@pytest.fixture
def synth():
    return SynthQA(SynthConfig(min_answer_length=20))


@pytest.fixture
def existing_samples():
    return [
        EvalSample(
            id="existing_001",
            question="健康保险的等待期有什么规定？",
            ground_truth="等待期不应与健康人群有过大差距",
            evidence_docs=["05_健康保险产品开发.md"],
            evidence_keywords=["等待期", "既往症"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="健康保险",
        ),
    ]


class TestParseResponse:

    def test_parse_response_valid_json(self, synth):
        response = '[{"question": "等待期多长", "answer": "等待期不超过90天", "keywords": ["等待期"], "topic": "健康保险", "difficulty": "easy"}]'
        result = synth._parse_response(response)
        assert len(result) == 1
        assert result[0]["question"] == "等待期多长"

    def test_parse_response_markdown_wrapped(self, synth):
        response = '```json\n[{"question": "Q1", "answer": "A1", "keywords": ["k1"], "topic": "t1", "difficulty": "medium"}]\n```'
        result = synth._parse_response(response)
        assert len(result) == 1

    def test_parse_response_invalid(self, synth):
        result = synth._parse_response("这不是JSON")
        assert result == []

    def test_parse_response_empty(self, synth):
        result = synth._parse_response("")
        assert result == []


class TestFilterSamples:

    def test_filter_short_answer(self, synth, existing_samples):
        candidates = [
            EvalSample(
                id="short_001",
                question="短问题",
                ground_truth="太短",
                evidence_docs=["05_健康保险产品开发.md"],
                evidence_keywords=["等待期"],
                question_type=QuestionType.FACTUAL,
                difficulty="easy",
                topic="健康保险",
            ),
        ]
        filtered = synth._filter_samples(candidates, existing_samples)
        assert len(filtered) == 0

    def test_filter_duplicate_question(self, synth, existing_samples):
        candidates = [
            EvalSample(
                id="dup_001",
                question="健康保险的等待期有什么规定？",
                ground_truth="等待期不超过90天，与既往症人群不应有过大差距",
                evidence_docs=["05_健康保险产品开发.md"],
                evidence_keywords=["等待期"],
                question_type=QuestionType.FACTUAL,
                difficulty="easy",
                topic="健康保险",
            ),
        ]
        filtered = synth._filter_samples(candidates, existing_samples)
        assert len(filtered) == 0

    def test_filter_missing_keyword_in_answer(self, synth, existing_samples):
        candidates = [
            EvalSample(
                id="no_kw_001",
                question="等待期有多长？",
                ground_truth="根据相关规定，保险公司应当遵守法律要求",
                evidence_docs=["05_健康保险产品开发.md"],
                evidence_keywords=["等待期", "保险期间"],
                question_type=QuestionType.FACTUAL,
                difficulty="easy",
                topic="健康保险",
            ),
        ]
        filtered = synth._filter_samples(candidates, existing_samples)
        assert len(filtered) == 0

    def test_filter_valid_sample(self, synth, existing_samples):
        candidates = [
            EvalSample(
                id="valid_001",
                question="犹豫期有什么规定？",
                ground_truth="犹豫期自收到保险单之日起不少于15天，投保人在此期间可以解除保险合同",
                evidence_docs=["05_健康保险产品开发.md"],
                evidence_keywords=["犹豫期"],
                question_type=QuestionType.FACTUAL,
                difficulty="easy",
                topic="健康保险",
            ),
        ]
        filtered = synth._filter_samples(candidates, existing_samples)
        assert len(filtered) == 1

    def test_synth_sample_created_by_llm(self, synth, existing_samples):
        candidates = [
            EvalSample(
                id="synth_test",
                question="免赔额是多少？",
                ground_truth="免赔额为每次就诊的自付金额，不低于100元，具体金额由保险合同约定",
                evidence_docs=["05_健康保险产品开发.md"],
                evidence_keywords=["免赔额"],
                question_type=QuestionType.FACTUAL,
                difficulty="medium",
                topic="健康保险",
                created_by="llm",
            ),
        ]
        filtered = synth._filter_samples(candidates, existing_samples)
        assert len(filtered) == 1
        assert filtered[0].created_by == "llm"


class TestSynthResult:

    def test_to_dict(self):
        result = SynthResult(
            total_chunks=10,
            processed_chunks=10,
            generated_samples=25,
            filtered_samples=5,
            failed_chunks=2,
        )
        d = result.to_dict()
        assert d['total_chunks'] == 10
        assert d['generated_samples'] == 25
        assert d['filtered_samples'] == 5
        assert d['samples'] == []
