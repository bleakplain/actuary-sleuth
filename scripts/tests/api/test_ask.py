"""问答 API 端到端测试 — 包含 SSE message_id 回归测试。"""
import json


class TestChatSSE:
    def test_chat_sse_includes_message_id(self, app_client):
        """核心回归测试：SSE done 事件必须包含真实的数据库 message_id。"""
        resp = app_client.post("/api/ask/chat", json={
            "question": "健康保险等待期多长？",
            "mode": "qa",
        })
        assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        done_event = _find_event_by_type(events, "done")
        assert done_event is not None, "SSE 流中未找到 done 事件"

        done_data = done_event["data"]
        assert "message_id" in done_data, "done 事件缺少 message_id 字段"
        assert isinstance(done_data["message_id"], int)
        assert done_data["message_id"] > 0

    def test_chat_sse_message_id_matches_database(self, app_client):
        """验证 SSE 返回的 message_id 确实存在于数据库中。"""
        resp = app_client.post("/api/ask/chat", json={
            "question": "测试问题",
            "mode": "qa",
        })
        assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        done_data = _find_event_by_type(events, "done")["data"]
        message_id = done_data["message_id"]
        conversation_id = done_data["conversation_id"]

        # 用 feedback API 验证 message_id 有效
        feedback_resp = app_client.post("/api/feedback/submit", json={
            "message_id": message_id,
            "rating": "down",
            "reason": "测试",
        })
        assert feedback_resp.status_code == 200, (
            f"使用 SSE message_id={message_id} 提交反馈失败: {feedback_resp.json()}"
        )
        fb = feedback_resp.json()
        assert fb["message_id"] == message_id
        assert fb["conversation_id"] == conversation_id

    def test_chat_sse_feedback_roundtrip(self, app_client):
        """端到端：发消息 → 获取 message_id → 提交反馈 → 查询 badcase。"""
        # 1. 发起 SSE 对话
        chat_resp = app_client.post("/api/ask/chat", json={
            "question": "核辐射在承保范围内吗？",
            "mode": "qa",
        })
        assert chat_resp.status_code == 200

        events = _parse_sse_events(chat_resp.text)
        done_data = _find_event_by_type(events, "done")["data"]
        message_id = done_data["message_id"]

        # 2. 用获取到的 message_id 提交反馈
        feedback_resp = app_client.post("/api/feedback/submit", json={
            "message_id": message_id,
            "rating": "down",
            "reason": "答案错误",
            "correction": "核辐射属于免责条款",
        })
        assert feedback_resp.status_code == 200
        fb_id = feedback_resp.json()["id"]

        # 3. 查询该 badcase，验证数据完整
        badcase_resp = app_client.get(f"/api/feedback/badcases/{fb_id}")
        assert badcase_resp.status_code == 200
        badcase = badcase_resp.json()
        assert badcase["rating"] == "down"
        assert badcase["reason"] == "答案错误"
        assert badcase["correction"] == "核辐射属于免责条款"
        assert badcase["status"] == "pending"

    def test_chat_sse_has_token_events(self, app_client):
        """SSE 流包含 token 类型事件。"""
        resp = app_client.post("/api/ask/chat", json={
            "question": "测试",
            "mode": "qa",
        })
        assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        token_events = [e for e in events if e.get("type") == "token"]
        assert len(token_events) > 0, "SSE 流中没有 token 事件"

    def test_chat_sse_includes_conversation_id(self, app_client):
        resp = app_client.post("/api/ask/chat", json={
            "question": "测试",
            "mode": "qa",
        })
        assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        done_data = _find_event_by_type(events, "done")["data"]
        assert done_data["conversation_id"].startswith("conv_")


class TestSearchMode:
    def test_chat_search_mode(self, app_client):
        resp = app_client.post("/api/ask/chat", json={
            "question": "等待期",
            "mode": "search",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "search"
        assert "sources" in data


class TestConversations:
    def test_list_conversations(self, app_client, make_conversation):
        make_conversation("conv_list1", "对话1")
        make_conversation("conv_list2", "对话2")

        resp = app_client.get("/api/ask/conversations")
        assert resp.status_code == 200
        convs = resp.json()
        assert len(convs) >= 2

    def test_get_messages(self, app_client, make_conversation, make_message):
        conv_id = "conv_msg_test"
        make_conversation(conv_id)

        import api.database as api_db
        api_db.add_message(conv_id, "user", "问题")
        api_db.add_message(conv_id, "assistant", "回答")

        resp = app_client.get(f"/api/ask/conversations/{conv_id}/messages")
        assert resp.status_code == 200
        msgs = resp.json()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_get_messages_not_found(self, app_client):
        resp = app_client.get("/api/ask/conversations/nonexistent/messages")
        assert resp.status_code == 404

    def test_delete_conversation(self, app_client, make_conversation):
        conv_id = "conv_delete_test"
        make_conversation(conv_id)
        import api.database as api_db
        api_db.add_message(conv_id, "user", "要删除的消息")

        resp = app_client.delete(f"/api/ask/conversations/{conv_id}")
        assert resp.status_code == 200

        # 验证对话已删除
        msg_resp = app_client.get(f"/api/ask/conversations/{conv_id}/messages")
        assert msg_resp.status_code == 404

    def test_delete_conversation_not_found(self, app_client):
        resp = app_client.delete("/api/ask/conversations/nonexistent")
        assert resp.status_code == 404


# ===== SSE 辅助函数 =====

def _parse_sse_events(text: str) -> list:
    """解析 SSE 事件流文本为事件列表。"""
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
                events.append(data)
            except json.JSONDecodeError:
                continue
    return events


def _find_event_by_type(events: list, event_type: str):
    """在事件列表中找到指定类型的事件。"""
    for event in events:
        if event.get("type") == event_type:
            return event
    return None
