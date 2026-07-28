from llama_index.core import Document

from lib.doc_parser.kb.md_parser import MdParser


def test_overlap_does_not_cross_regulation_section_boundaries():
    document = Document(
        text="""---
regulation: 测试法规
---

# 测试法规

## 第1条检核规则

第一条独立内容。

## 第2条检核规则

第二条独立内容。
""",
        metadata={"file_name": "test.md"},
    )

    nodes = MdParser(chunk_overlap_chars=150, min_chunk_chars=1).parse_document(document)
    second = next(
        node for node in nodes
        if node.metadata["article_number"] == "第2条检核规则"
    )

    assert second.text == "第二条独立内容。"
    assert "第一条独立内容" not in second.text


def test_overlap_is_kept_between_chunks_inside_same_section():
    parser = MdParser(max_chunk_chars=20, chunk_overlap_chars=5, min_chunk_chars=1)
    document = Document(
        text="""---
regulation: 测试法规
---

# 测试法规

## 第1条检核规则

abcdefghijklmnop

qrstuvwxyz
""",
        metadata={"file_name": "test.md"},
    )

    nodes = parser.parse_document(document)

    assert len(nodes) >= 2
    assert all(
        node.metadata["article_number"] == "第1条检核规则"
        for node in nodes
    )
    assert nodes[1].text.startswith("lmnop")
