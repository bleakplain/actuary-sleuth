"""反馈 API 端到端测试。"""


class TestSubmitFeedback:
    def test_submit_feedback_success(self, app_client, make_conversation, make_message):
        make_conversation()
        msg_id = make_message(role="assistant", content="测试回答")

        resp = app_client.post("/api/feedback/submit", json={
            "message_id": msg_id,
            "rating": "down",
            "reason": "答案错误",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["rating"] == "down"
        assert data["reason"] == "答案错误"
        assert data["message_id"] == msg_id
        assert data["user_question"] == ""
        assert data["assistant_answer"] == "测试回答"

    def test_submit_feedback_upvote(self, app_client, make_conversation, make_message):
        make_conversation()
        msg_id = make_message()

        resp = app_client.post("/api/feedback/submit", json={
            "message_id": msg_id,
            "rating": "up",
        })
        assert resp.status_code == 200
        assert resp.json()["rating"] == "up"

    def test_submit_feedback_with_correction(self, app_client, make_conversation, make_message):
        make_conversation()
        msg_id = make_message()

        resp = app_client.post("/api/feedback/submit", json={
            "message_id": msg_id,
            "rating": "down",
            "reason": "答案错误",
            "correction": "正确答案是60天",
        })
        assert resp.status_code == 200
        assert resp.json()["correction"] == "正确答案是60天"

    def test_submit_feedback_message_not_found(self, app_client):
        resp = app_client.post("/api/feedback/submit", json={
            "message_id": 99999,
            "rating": "down",
        })
        assert resp.status_code == 404
        assert "消息不存在" in resp.json()["detail"]

    def test_submit_feedback_invalid_rating(self, app_client):
        resp = app_client.post("/api/feedback/submit", json={
            "message_id": 1,
            "rating": "invalid",
        })
        assert resp.status_code == 422

    def test_submit_feedback_invalid_message_id(self, app_client):
        resp = app_client.post("/api/feedback/submit", json={
            "message_id": -1,
            "rating": "up",
        })
        assert resp.status_code == 422

    def test_submit_feedback_missing_fields(self, app_client):
        resp = app_client.post("/api/feedback/submit", json={"rating": "up"})
        assert resp.status_code == 422

    def test_submit_feedback_with_user_question_enriched(self, app_client, make_conversation, make_message):
        import api.database as api_db

        conv_id = "conv_feedback_test"
        make_conversation(conversation_id=conv_id)

        # 创建 user + assistant 消息对
        api_db.add_message(conv_id, "user", "等待期多长？")
        msg_id = api_db.add_message(conv_id, "assistant", "不超过90天")

        resp = app_client.post("/api/feedback/submit", json={
            "message_id": msg_id,
            "rating": "down",
            "reason": "答案不完整",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_question"] == "等待期多长？"
        assert data["assistant_answer"] == "不超过90天"


class TestListBadcases:
    def test_list_all_badcases(self, app_client, make_conversation, make_message):
        make_conversation()
        msg_id = make_message()

        app_client.post("/api/feedback/submit", json={
            "message_id": msg_id, "rating": "down", "reason": "测试",
        })

        resp = app_client.get("/api/feedback/badcases")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_list_badcases_filter_by_status(self, app_client, make_conversation, make_message):
        make_conversation()
        msg_id = make_message()

        app_client.post("/api/feedback/submit", json={
            "message_id": msg_id, "rating": "down",
        })

        resp = app_client.get("/api/feedback/badcases", params={"status": "pending"})
        assert resp.status_code == 200
        for item in resp.json():
            assert item["status"] == "pending"

    def test_list_badcases_empty(self, app_client):
        resp = app_client.get("/api/feedback/badcases")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetBadcase:
    def test_get_badcase_success(self, app_client, make_conversation, make_message):
        make_conversation()
        msg_id = make_message()

        submit_resp = app_client.post("/api/feedback/submit", json={
            "message_id": msg_id, "rating": "up",
        })
        fb_id = submit_resp.json()["id"]

        resp = app_client.get(f"/api/feedback/badcases/{fb_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == fb_id

    def test_get_badcase_not_found(self, app_client):
        resp = app_client.get("/api/feedback/badcases/nonexistent")
        assert resp.status_code == 404


class TestUpdateBadcase:
    def test_update_badcase_status(self, app_client, make_conversation, make_message):
        make_conversation()
        msg_id = make_message()

        submit_resp = app_client.post("/api/feedback/submit", json={
            "message_id": msg_id, "rating": "down",
        })
        fb_id = submit_resp.json()["id"]

        resp = app_client.put(f"/api/feedback/badcases/{fb_id}", json={
            "status": "classified",
            "classified_type": "hallucination",
            "classified_reason": "回答包含法规中不存在的信息",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "classified"
        assert data["classified_type"] == "hallucination"

    def test_update_badcase_not_found(self, app_client):
        resp = app_client.put("/api/feedback/badcases/nonexistent", json={
            "status": "fixed",
        })
        assert resp.status_code == 404

    def test_update_badcase_invalid_status(self, app_client):
        resp = app_client.put("/api/feedback/badcases/fb_xxx", json={
            "status": "invalid_status",
        })
        assert resp.status_code == 422


class TestFeedbackStats:
    def test_stats_empty(self, app_client):
        resp = app_client.get("/api/feedback/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["up_count"] == 0
        assert data["down_count"] == 0

    def test_stats_after_submissions(self, app_client, make_conversation, make_message):
        msg_id1 = make_message(role="assistant", content="回答1")
        msg_id2 = make_message(role="assistant", content="回答2")

        app_client.post("/api/feedback/submit", json={"message_id": msg_id1, "rating": "up"})
        app_client.post("/api/feedback/submit", json={"message_id": msg_id2, "rating": "down"})

        resp = app_client.get("/api/feedback/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["up_count"] == 1
        assert data["down_count"] == 1
        assert data["satisfaction_rate"] == 0.5
