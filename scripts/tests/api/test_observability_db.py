"""Observability 数据库函数测试。"""
import pytest
from scripts.tests.api.conftest import *


class TestConversationSearch:
    def test_search_conversations_no_filter(self, _patch_database, make_conversation):
        import api.database as db
        make_conversation("conv_aaa", "健康保险等待期")
        make_conversation("conv_bbb", "免责条款查询")
        make_conversation("conv_ccc", "等待期相关问题")
        rows = db.search_conversations(search="", page=1, size=10)
        assert rows[1] == 3  # total count

    def test_search_conversations_by_title(self, _patch_database, make_conversation):
        import api.database as db
        make_conversation("conv_aaa", "健康保险等待期")
        make_conversation("conv_bbb", "免责条款查询")
        make_conversation("conv_ccc", "等待期相关问题")
        rows = db.search_conversations(search="等待期", page=1, size=10)
        assert rows[1] == 2
        titles = [r["title"] for r in rows[0]]
        assert "健康保险等待期" in titles
        assert "等待期相关问题" in titles

    def test_search_conversations_pagination(self, _patch_database, make_conversation):
        import api.database as db
        for i in range(5):
            make_conversation(f"conv_{i}", f"对话 {i}")
        rows = db.search_conversations(search="", page=1, size=2)
        assert len(rows[0]) == 2
        assert rows[1] == 5


class TestBatchDeleteConversations:
    def test_batch_delete(self, _patch_database, make_conversation, make_message):
        import api.database as db
        make_conversation("conv_del1", "删除1")
        make_message("conv_del1", "user", "问题1")
        make_message("conv_del1", "assistant", "回答1")
        make_conversation("conv_del2", "删除2")
        make_message("conv_del2", "user", "问题2")
        make_conversation("conv_keep", "保留")
        deleted = db.batch_delete_conversations(["conv_del1", "conv_del2"])
        assert deleted == 2
        remaining = db.get_conversations()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "conv_keep"
