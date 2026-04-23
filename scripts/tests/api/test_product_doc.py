#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品文档 API 测试"""
import pytest
from datetime import datetime, timezone

from api.database import init_db, save_parsed_document, get_parsed_document, list_parsed_documents


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


def test_save_and_get_parsed_document():
    doc = {
        "id": "test-1",
        "file_name": "test.pdf",
        "file_path": "/tmp/test.pdf",
        "file_type": ".pdf",
        "clauses": [{"number": "1.1", "title": "测试条款", "text": "内容"}],
        "premium_tables": [],
        "notices": [],
        "health_disclosures": [],
        "exclusions": [],
        "rider_clauses": [],
        "raw_content": None,
        "parse_time": datetime.now(timezone.utc).isoformat(),
        "warnings": [],
    }
    save_parsed_document(doc)
    result = get_parsed_document("test-1")
    assert result is not None
    assert result["file_name"] == "test.pdf"
    assert len(result["clauses"]) == 1
    assert result["clauses"][0]["number"] == "1.1"


def test_list_parsed_documents():
    doc = {
        "id": "test-2",
        "file_name": "test2.pdf",
        "file_path": "/tmp/test2.pdf",
        "file_type": ".pdf",
        "clauses": [],
        "premium_tables": [],
        "notices": [],
        "health_disclosures": [],
        "exclusions": [],
        "rider_clauses": [],
        "raw_content": None,
        "parse_time": datetime.now(timezone.utc).isoformat(),
        "warnings": [],
        "review_status": "pending",
    }
    save_parsed_document(doc)
    results = list_parsed_documents(review_status="pending")
    assert len(results) >= 1
    assert any(r["id"] == "test-2" for r in results)
