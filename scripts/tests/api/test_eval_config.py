"""eval_configs 表扁平版本管理测试。"""
import pytest
from api.database import (
    insert_eval_config, get_eval_configs, get_eval_config,
    get_active_config, activate_eval_config, remove_eval_config,
    _ensure_default_config,
)


@pytest.fixture()
def db(_patch_database):
    """确保 eval_configs 表存在，插入默认配置。"""
    _ensure_default_config()
    yield


class TestInsertEvalConfig:
    def test_auto_increment_version(self, db):
        _, v1 = insert_eval_config("第一个配置", {"retrieval": {"vector_top_k": 10}})
        _, v2 = insert_eval_config("第二个配置", {"retrieval": {"vector_top_k": 20}})
        configs = get_eval_configs()
        versions = [c["version"] for c in configs]
        assert v1 == 2
        assert v2 == 3
        assert versions == [3, 2, 1]  # default=1, c1=2, c2=3, DESC order

    def test_first_insert_returns_id(self, db):
        cid, _ = insert_eval_config("初始配置", {})
        assert cid == 2  # default config is id=1 so new one is id=2

    def test_stores_config_json(self, db):
        config = {"retrieval": {"vector_top_k": 15}, "rerank": {"enable_rerank": False}}
        cid, _ = insert_eval_config("测试", config)
        result = get_eval_config(cid)
        assert result["config_json"]["retrieval"]["vector_top_k"] == 15
        assert result["config_json"]["rerank"]["enable_rerank"] is False

    def test_description_defaults_empty(self, db):
        cid, _ = insert_eval_config("", {})
        result = get_eval_config(cid)
        assert result["description"] == ""


class TestGetEvalConfigs:
    def test_returns_all_configs_desc(self, db):
        insert_eval_config("A", {})
        insert_eval_config("B", {})
        configs = get_eval_configs()
        assert len(configs) == 3  # default + A + B
        assert configs[0]["version"] >= configs[1]["version"]


class TestActivateEvalConfig:
    def test_only_one_active(self, db):
        c1, _ = insert_eval_config("配置1", {})
        c2, _ = insert_eval_config("配置2", {})
        activate_eval_config(c2)
        cfg1 = get_eval_config(c1)
        cfg2 = get_eval_config(c2)
        assert cfg1["is_active"] == 0
        assert cfg2["is_active"] == 1

    def test_get_active_config(self, db):
        c, _ = insert_eval_config("新配置", {})
        activate_eval_config(c)
        active = get_active_config()
        assert active is not None
        assert active["id"] == c

    def test_default_config_is_active(self, db):
        active = get_active_config()
        assert active is not None


class TestRemoveEvalConfig:
    def test_cannot_delete_active(self, db):
        active = get_active_config()
        assert active is not None
        result = remove_eval_config(active["id"])
        assert result is False

    def test_delete_inactive(self, db):
        c, _ = insert_eval_config("可删除", {})
        result = remove_eval_config(c)
        assert result is True
        assert get_eval_config(c) is None
