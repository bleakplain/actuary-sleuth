from lib.rag_engine.eval_dataset import EvalSample, RegulationRef, ReviewStatus, QuestionType


def test_regulation_ref_roundtrip():
    ref = RegulationRef(
        doc_name="健康保险管理办法.txt",
        article="第27条",
        excerpt="健康保险的产品设计应当...",
    )
    d = ref.to_dict()
    restored = RegulationRef.from_dict(d)
    assert restored == ref


def test_regulation_ref_with_chunk_id():
    ref = RegulationRef(
        doc_name="保险法.txt",
        article="第18条",
        excerpt="保险合同中规定的等待期...",
        chunk_id="chunk_abc123",
    )
    d = ref.to_dict()
    restored = RegulationRef.from_dict(d)
    assert restored.chunk_id == "chunk_abc123"


def test_regulation_ref_defaults():
    ref = RegulationRef(doc_name="a.txt", article="第1条", excerpt="...")
    assert ref.chunk_id == ""


def test_eval_sample_with_review_fields():
    sample = EvalSample(
        id="test001",
        question="测试问题",
        ground_truth="测试答案",
        evidence_docs=["保险法.txt"],
        evidence_keywords=["等待期"],
        question_type=QuestionType.FACTUAL,
        difficulty="easy",
        topic="测试",
        regulation_refs=[RegulationRef(
            doc_name="保险法.txt", article="第18条",
            excerpt="保险合同中...",
        )],
        review_status=ReviewStatus.APPROVED,
        reviewer="张精算师",
        reviewed_at="2026-04-08T10:00:00+00:00",
    )
    d = sample.to_dict()
    restored = EvalSample.from_dict(d)
    assert restored.review_status == ReviewStatus.APPROVED
    assert len(restored.regulation_refs) == 1
    assert restored.regulation_refs[0].article == "第18条"
    assert restored.reviewer == "张精算师"


def test_eval_sample_backward_compatible():
    old_data = {
        "id": "f001",
        "question": "健康保险的等待期有什么规定？",
        "ground_truth": "既往症人群的等待期...",
        "evidence_docs": ["05_健康保险产品开发.md"],
        "evidence_keywords": ["等待期"],
        "question_type": "factual",
        "difficulty": "easy",
        "topic": "健康保险",
    }
    sample = EvalSample.from_dict(old_data)
    assert sample.review_status == ReviewStatus.PENDING
    assert sample.regulation_refs == []
    assert sample.reviewer == ""
    assert sample.created_by == "human"
    assert sample.kb_version == ""


def test_eval_sample_created_by_and_kb_version():
    sample = EvalSample(
        id="llm_001",
        question="LLM 生成的问题",
        ground_truth="答案",
        evidence_docs=[],
        evidence_keywords=[],
        question_type=QuestionType.FACTUAL,
        difficulty="medium",
        topic="",
        created_by="llm",
        kb_version="v1.2",
    )
    d = sample.to_dict()
    restored = EvalSample.from_dict(d)
    assert restored.created_by == "llm"
    assert restored.kb_version == "v1.2"


def test_eval_sample_frozen():
    sample = EvalSample(
        id="test_frozen",
        question="测试",
        ground_truth="答案",
        evidence_docs=[],
        evidence_keywords=[],
        question_type=QuestionType.FACTUAL,
        difficulty="easy",
        topic="",
    )
    import dataclasses
    assert dataclasses.is_dataclass(sample)
    assert sample.__dataclass_params__.frozen


def test_unanswerable_type_serialization():
    sample = EvalSample(
        id="unanswerable_001",
        question="保险公司可以在抖音上直播卖保险吗？",
        ground_truth="知识库中无对应规定",
        evidence_docs=[],
        evidence_keywords=["直播", "销售"],
        question_type=QuestionType.UNANSWERABLE,
        difficulty="easy",
        topic="互联网保险",
    )
    d = sample.to_dict()
    assert d['question_type'] == 'unanswerable'
    assert d['evidence_docs'] == []

    restored = EvalSample.from_dict(d)
    assert restored.question_type == QuestionType.UNANSWERABLE
    assert restored == sample


def test_default_dataset_includes_unanswerable():
    from lib.rag_engine.eval_dataset import create_default_eval_dataset
    dataset = create_default_eval_dataset()
    unanswerable = [s for s in dataset if s.question_type == QuestionType.UNANSWERABLE]
    assert len(unanswerable) >= 5


def test_load_eval_dataset_from_db():
    from lib.rag_engine.eval_dataset import load_eval_dataset
    # DB is empty in tests, so falls back to built-in default
    loaded = load_eval_dataset()
    assert isinstance(loaded, list)
    assert len(loaded) > 0
