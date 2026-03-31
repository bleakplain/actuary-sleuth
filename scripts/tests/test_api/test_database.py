"""数据库层单元测试。"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "test.db"
    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)

    with patch("lib.config.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None), \
         patch("lib.common.connection_pool._global_pool", None):
        from lib.common import database as db_mod
        db_mod._connection_pool = None
        from api.database import init_db
        init_db()
        yield
        db_mod.close_pool()


class TestConversations:
    def test_create_and_get_conversations(self, db):
        from api.database import create_conversation, get_conversations
        create_conversation("conv-1", "测试对话")
        convs = get_conversations()
        assert len(convs) == 1
        assert convs[0]["id"] == "conv-1"
        assert convs[0]["title"] == "测试对话"
        assert convs[0]["message_count"] == 0

    def test_add_and_get_messages(self, db):
        from api.database import (
            create_conversation, add_message, get_messages,
        )
        create_conversation("conv-1")
        add_message("conv-1", "user", "健康保险等待期多久？")
        add_message(
            "conv-1", "assistant", "根据法规，等待期不超过180天。",
            citations=[{"source_idx": 0, "law_name": "保险法", "article_number": "第X条", "content": "..."}],
            sources=[{"law_name": "保险法", "article_number": "第X条", "content": "..."}],
        )
        msgs = get_messages("conv-1")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert len(msgs[1]["citations"]) == 1
        assert len(msgs[1]["sources"]) == 1

    def test_delete_conversation(self, db):
        from api.database import (
            create_conversation, add_message, delete_conversation,
            get_conversations,
        )
        create_conversation("conv-1")
        add_message("conv-1", "user", "test")
        deleted = delete_conversation("conv-1")
        assert deleted == 1
        assert len(get_conversations()) == 0


class TestEvalSamples:
    def test_upsert_and_get(self, db):
        from api.database import upsert_eval_sample, get_eval_sample
        sample = {
            "id": "f001",
            "question": "健康保险等待期最长多少天？",
            "ground_truth": "180天",
            "evidence_docs": ["05_健康保险产品开发.md"],
            "evidence_keywords": ["等待期", "180天"],
            "question_type": "factual",
            "difficulty": "easy",
            "topic": "健康保险",
        }
        upsert_eval_sample(sample)
        result = get_eval_sample("f001")
        assert result is not None
        assert result["question"] == sample["question"]
        assert result["evidence_docs"] == ["05_健康保险产品开发.md"]

    def test_filter_by_type(self, db):
        from api.database import upsert_eval_sample, get_eval_samples
        upsert_eval_sample({
            "id": "f001", "question": "q1", "question_type": "factual",
            "difficulty": "easy", "topic": "",
        })
        upsert_eval_sample({
            "id": "m001", "question": "q2", "question_type": "multi_hop",
            "difficulty": "hard", "topic": "",
        })
        factual = get_eval_samples(question_type="factual")
        assert len(factual) == 1
        assert factual[0]["id"] == "f001"

    def test_delete_sample(self, db):
        from api.database import upsert_eval_sample, delete_eval_sample, get_eval_sample
        upsert_eval_sample({"id": "f001", "question": "q1"})
        assert delete_eval_sample("f001") is True
        assert get_eval_sample("f001") is None

    def test_import_samples(self, db):
        from api.database import import_eval_samples, eval_sample_count
        samples = [
            {"id": "f001", "question": "q1"},
            {"id": "f002", "question": "q2"},
        ]
        count = import_eval_samples(samples)
        assert count == 2
        assert eval_sample_count() == 2

    def test_import_idempotent(self, db):
        from api.database import import_eval_samples, eval_sample_count
        samples = [{"id": "f001", "question": "q1"}]
        import_eval_samples(samples)
        import_eval_samples(samples)
        assert eval_sample_count() == 1


class TestSnapshots:
    def test_create_and_list(self, db):
        from api.database import (
            upsert_eval_sample, create_snapshot, get_snapshots,
        )
        upsert_eval_sample({"id": "f001", "question": "q1"})
        snap_id = create_snapshot("v1", "初始版本")
        snaps = get_snapshots()
        assert len(snaps) == 1
        assert snaps[0]["id"] == snap_id
        assert snaps[0]["sample_count"] == 1
        assert snaps[0]["name"] == "v1"

    def test_restore_snapshot(self, db):
        from api.database import (
            upsert_eval_sample, create_snapshot, restore_snapshot,
            get_eval_samples, delete_eval_sample,
        )
        upsert_eval_sample({"id": "f001", "question": "q1"})
        upsert_eval_sample({"id": "f002", "question": "q2"})
        snap_id = create_snapshot("v1")
        delete_eval_sample("f002")
        assert len(get_eval_samples()) == 1
        restored = restore_snapshot(snap_id)
        assert restored == 2
        assert len(get_eval_samples()) == 2


class TestEvalRuns:
    def test_create_and_get(self, db):
        from api.database import create_eval_run, get_eval_run
        create_eval_run("run-1", "full", {"top_k": 5})
        run = get_eval_run("run-1")
        assert run is not None
        assert run["mode"] == "full"
        assert run["status"] == "pending"
        assert run["config"]["top_k"] == 5

    def test_update_status(self, db):
        from api.database import create_eval_run, update_eval_run_status, get_eval_run
        create_eval_run("run-1", "retrieval", {})
        update_eval_run_status("run-1", "running", progress=5, total=30)
        run = get_eval_run("run-1")
        assert run["status"] == "running"
        assert run["progress"] == 5
        assert run["total"] == 30

    def test_save_and_get_report(self, db):
        from api.database import (
            create_eval_run, save_eval_report, get_eval_run,
        )
        create_eval_run("run-1", "full", {})
        report = {"retrieval": {"precision_at_k": 0.8}, "generation": {}}
        save_eval_report("run-1", report)
        run = get_eval_run("run-1")
        assert run["report"]["retrieval"]["precision_at_k"] == 0.8


class TestComplianceReports:
    def test_save_and_get(self, db):
        from api.database import save_compliance_report, get_compliance_report, get_compliance_reports
        result = {
            "summary": {"compliant": 3, "non_compliant": 1, "attention": 0},
            "items": [{"param": "等待期", "status": "compliant"}],
        }
        save_compliance_report("cr-1", "产品A", "健康险", "product", result)
        report = get_compliance_report("cr-1")
        assert report is not None
        assert report["result"]["summary"]["compliant"] == 3
        reports = get_compliance_reports()
        assert len(reports) == 1
