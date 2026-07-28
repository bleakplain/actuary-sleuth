"""旧版 Word 产品条款解析器测试。"""
from lib.doc_parser.pd.legacy_doc_parser import LegacyDocParser


def test_supported_extensions() -> None:
    assert LegacyDocParser.supported_extensions() == [".doc"]
