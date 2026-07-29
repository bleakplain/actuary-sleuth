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


def test_same_markdown_produces_same_deterministic_node_ids():
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
        metadata={
            "file_name": "test.md",
            "source_path": "00_保险法/test.md",
            "kb_version": "v5",
        },
    )

    first = MdParser(min_chunk_chars=1).parse_document(document)
    second = MdParser(min_chunk_chars=1).parse_document(document)

    assert [node.node_id for node in first] == [
        node.node_id for node in second
    ]
    assert all(node.node_id.startswith("kb-chunk:") for node in first)


def test_different_chunks_never_share_deterministic_node_id():
    document = Document(
        text="""---
regulation: 测试法规
---

# 测试法规

## 第1条检核规则

相同正文。

## 第2条检核规则

相同正文。
""",
        metadata={
            "file_name": "test.md",
            "source_path": "00_保险法/test.md",
            "kb_version": "v5",
        },
    )

    nodes = MdParser(min_chunk_chars=1).parse_document(document)

    assert len(nodes) == 2
    assert len({node.node_id for node in nodes}) == 2


def test_kb_version_is_part_of_deterministic_node_id():
    text = """---
regulation: 测试法规
---

# 测试法规

## 第1条检核规则

同一正文。
"""
    first = MdParser(min_chunk_chars=1).parse_document(Document(
        text=text,
        metadata={
            "file_name": "test.md",
            "source_path": "00_保险法/test.md",
            "kb_version": "v5",
        },
    ))
    second = MdParser(min_chunk_chars=1).parse_document(Document(
        text=text,
        metadata={
            "file_name": "test.md",
            "source_path": "00_保险法/test.md",
            "kb_version": "v6",
        },
    ))

    assert first[0].node_id != second[0].node_id
