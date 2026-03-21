import pytest
from lib.preprocessing.document_fetcher import fetch_feishu_document, DocumentFetchError


def test_fetch_feishu_document_invalid_url():
    with pytest.raises(DocumentFetchError) as exc_info:
        fetch_feishu_document("https://example.com/not-a-feishu-url")
    assert "Invalid Feishu document URL" in str(exc_info.value)


def test_fetch_feishu_document_missing_docx():
    with pytest.raises(DocumentFetchError) as exc_info:
        fetch_feishu_document("https://feishu.cn/docx/")
    assert "Invalid Feishu document URL" in str(exc_info.value)
