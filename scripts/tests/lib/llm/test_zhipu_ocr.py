#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZhipuClient OCR method tests."""
import pytest
from unittest.mock import MagicMock, patch


class TestZhipuClientOCR:
    """ZhipuClient.ocr_table() tests."""

    def test_ocr_table_calls_layout_parsing_endpoint(self):
        """ocr_table should POST to /v4/layout_parsing with glm-ocr model."""
        from lib.llm.zhipu import ZhipuClient

        client = ZhipuClient(api_key="test-key", base_url="https://fake.api/v4/")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": "| Col1 | Col2 |\n|------|------|\n| A | B |"}
        mock_response.raise_for_status = MagicMock()

        session = MagicMock()
        session.post.return_value = mock_response
        client._session = session

        result = client.ocr_table("data:image/png;base64,abc123")
        assert "| Col1 | Col2 |" in result
        session.post.assert_called_once()
        call_kwargs = session.post.call_args
        assert "/layout_parsing" in call_kwargs[0][0]
        assert call_kwargs[1]["json"]["model"] == "glm-ocr"

    def test_ocr_table_extracts_content_from_response(self):
        """ocr_table should return the 'content' field from response."""
        from lib.llm.zhipu import ZhipuClient

        client = ZhipuClient(api_key="test-key", base_url="https://fake.api/v4/")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": "markdown table content here"}
        mock_response.raise_for_status = MagicMock()

        session = MagicMock()
        session.post.return_value = mock_response
        client._session = session

        result = client.ocr_table("base64data")
        assert result == "markdown table content here"

    def test_ocr_table_raises_on_http_error(self):
        """ocr_table should propagate HTTP errors."""
        from lib.llm.zhipu import ZhipuClient

        client = ZhipuClient(api_key="test-key", base_url="https://fake.api/v4/")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("Server error")

        session = MagicMock()
        session.post.return_value = mock_response
        client._session = session

        with pytest.raises(Exception, match="Server error"):
            client._do_ocr_table("base64data")

    def test_ocr_table_empty_content(self):
        """ocr_table should return empty string when content field missing."""
        from lib.llm.zhipu import ZhipuClient

        client = ZhipuClient(api_key="test-key", base_url="https://fake.api/v4/")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"other_field": "value"}
        mock_response.raise_for_status = MagicMock()

        session = MagicMock()
        session.post.return_value = mock_response
        client._session = session

        result = client.ocr_table("base64data")
        assert result == ""
