"""中间件单元测试"""
import sys
sys.path.insert(0, 'scripts')


class TestSessionContextMiddleware:
    def test_before_invoke_loads_context(self):
        """验证 before_invoke 加载上下文"""
        from lib.common.middleware import SessionContextMiddleware

        mw = SessionContextMiddleware()
        state = {"session_id": "test_session", "question": "测试"}

        result = mw.before_invoke(state)

        assert "session_context" in result
        assert isinstance(result["session_context"], dict)

    def test_extract_product_type(self):
        """验证险种类型提取"""
        from lib.common.middleware import SessionContextMiddleware

        mw = SessionContextMiddleware()

        assert mw._extract_product_type("重疾险等待期") is not None
        assert "重疾" in mw._extract_product_type("重疾险等待期") or mw._extract_product_type("重疾险等待期") == "重疾险"
        assert mw._extract_product_type("医疗险保费") is not None
        assert mw._extract_product_type("等待期") is None


class TestClarificationMiddleware:
    def test_needs_clarification_without_product_type(self):
        """验证无险种类型时触发澄清"""
        from lib.common.middleware import ClarificationMiddleware

        mw = ClarificationMiddleware()
        state = {
            "question": "等待期是多少？",
            "session_context": {},
            "skip_clarify": False,
        }

        result = mw.before_invoke(state)

        assert result["next_action"] == "clarify"
        assert "clarification_message" in result

    def test_skip_clarify_flag(self):
        """验证 skip_clarify 跳过检测"""
        from lib.common.middleware import ClarificationMiddleware

        mw = ClarificationMiddleware()
        state = {
            "question": "等待期是多少？",
            "session_context": {},
            "skip_clarify": True,
        }

        result = mw.before_invoke(state)

        assert result["next_action"] == "search"

    def test_no_clarification_with_product_type(self):
        """验证有险种类型时无需澄清"""
        from lib.common.middleware import ClarificationMiddleware

        mw = ClarificationMiddleware()
        state = {
            "question": "等待期是多少？",
            "session_context": {"product_type": "重疾险"},
            "skip_clarify": False,
        }

        result = mw.before_invoke(state)

        assert result["next_action"] == "search"


class TestLoopDetectionMiddleware:
    def test_detects_loop(self):
        """验证循环检测"""
        from lib.common.middleware import LoopDetectionMiddleware

        mw = LoopDetectionMiddleware()

        hash_val = mw._hash_question("等待期")

        session_context = {"query_history": [hash_val, hash_val]}
        result = mw.after_invoke(session_context, "等待期")

        assert result.get("loop_detected") is True

    def test_no_loop_with_different_questions(self):
        """验证不同问题不触发循环"""
        from lib.common.middleware import LoopDetectionMiddleware

        mw = LoopDetectionMiddleware()

        session_context = {"query_history": ["a", "b", "c"]}
        result = mw.after_invoke(session_context, "犹豫期")

        assert result.get("loop_detected") is not True


class TestIterationLimitMiddleware:
    def test_iteration_count_increments(self):
        """验证迭代次数递增"""
        from lib.common.middleware import IterationLimitMiddleware

        mw = IterationLimitMiddleware()
        result = mw.after_invoke(0)

        assert result["iteration_count"] == 1

    def test_error_after_max_iterations(self):
        """验证达到最大迭代次数时设置错误"""
        from lib.common.middleware import IterationLimitMiddleware

        mw = IterationLimitMiddleware()
        result = mw.after_invoke(9)

        assert result["iteration_count"] == 10
        assert result.get("error") is not None
        assert result.get("next_action") == "end"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
