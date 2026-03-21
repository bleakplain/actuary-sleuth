import pytest
from lib.preprocessing.document_fetcher import fetch_feishu_document, DocumentFetchError


def test_fetch_feishu_document_invalid_url():
    with pytest.raises(DocumentFetchError) as exc_info:
        fetch_feishu_document("https://example.com/not-a-feishu-url")
    assert "不允许的域名" in str(exc_info.value)


def test_fetch_feishu_document_missing_docx():
    with pytest.raises(DocumentFetchError) as exc_info:
        fetch_feishu_document("https://feishu.cn/docx/")
    assert "无效的飞书 URL 格式" in str(exc_info.value)
