from llama_index.core.schema import TextNode

from lib.rag_engine.quality_checker import QualityChecker


def test_same_regulation_text_with_different_metadata_is_preserved():
    nodes = [
        TextNode(text="同一规则文字", metadata={"article_number": "第1项", "适用标签": "health"}),
        TextNode(text="同一规则文字", metadata={"article_number": "第2项", "适用标签": "life"}),
    ]

    result = QualityChecker(min_content_chars=1).check_chunks(nodes)

    assert len(result) == 2


def test_exact_duplicate_is_removed():
    nodes = [
        TextNode(text="同一规则文字", metadata={"article_number": "第1项"}),
        TextNode(text="同一规则文字", metadata={"article_number": "第1项"}),
    ]

    result = QualityChecker(min_content_chars=1).check_chunks(nodes)

    assert len(result) == 1


def test_structured_short_legal_requirement_is_preserved():
    node = TextNode(
        text="保险期间不得低于5年",
        metadata={"law_name": "精算规定", "article_number": "第1项", "source_file": "规定.md"},
    )

    result = QualityChecker(allow_structured_short_chunks=True).check_chunks([node])

    assert result == [node]


def test_short_noise_is_rejected_even_for_structured_source():
    metadata = {"law_name": "精算规定", "article_number": "第1项", "source_file": "规定.md"}

    result = QualityChecker(allow_structured_short_chunks=True).check_chunks([
        TextNode(text="。", metadata=metadata),
    ])

    assert result == []


def test_unstructured_short_text_is_rejected():
    node = TextNode(text="保险期间不得低于5年", metadata={})

    result = QualityChecker(allow_structured_short_chunks=True).check_chunks([node])

    assert result == []
