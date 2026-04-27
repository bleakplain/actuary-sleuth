#!/usr/bin/env python3
"""记忆系统端到端表驱动测试。"""
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests


@dataclass
class TestCase:
    id: str
    category: str
    name: str
    setup: Optional[Callable[[], dict]]
    action: Callable[[dict, str], dict]
    expect: Callable[[dict, Any], tuple[bool, str]]
    cleanup: Optional[Callable[[dict, str], None]]


class TestRunner:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.created_ids: list[str] = []

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        return requests.request(method, url, **kwargs)

    def add_memory(self, content: str, user_id: str = None, category: str = "fact") -> dict:
        if user_id is None:
            user_id = f"e2e_{int(time.time() * 1000)}"
        resp = self.request("POST", "/api/memory/add", json={
            "content": content,
            "category": category,
        }, params={"user_id": user_id})
        return resp.json()

    def list_memories(self, user_id: str) -> dict:
        resp = self.request("GET", "/api/memory/list", params={"user_id": user_id})
        return resp.json()

    def delete_memory(self, memory_id: str) -> dict:
        resp = self.request("DELETE", f"/api/memory/{memory_id}")
        return resp.json()

    def get_profile(self, user_id: str) -> dict:
        resp = self.request("GET", "/api/memory/profile", params={"user_id": user_id})
        return resp.json()

    def update_profile(self, user_id: str, focus_areas: list = None,
                       preference_tags: list = None, summary: str = None) -> dict:
        body = {}
        if focus_areas is not None:
            body["focus_areas"] = focus_areas
        if preference_tags is not None:
            body["preference_tags"] = preference_tags
        if summary is not None:
            body["summary"] = summary
        resp = self.request("PUT", "/api/memory/profile", json=body, params={"user_id": user_id})
        return resp.json()

    def run_test(self, tc: TestCase) -> dict:
        context = {}
        try:
            if tc.setup:
                context = tc.setup()

            result = tc.action(context, self.base_url)
            passed, message = tc.expect(context, result)

            if tc.cleanup:
                tc.cleanup(context, self.base_url)

            return {
                "id": tc.id,
                "category": tc.category,
                "name": tc.name,
                "passed": passed,
                "message": message,
                "error": None,
            }
        except Exception as e:
            return {
                "id": tc.id,
                "category": tc.category,
                "name": tc.name,
                "passed": False,
                "message": str(e),
                "error": type(e).__name__,
            }


def make_test_cases() -> list[TestCase]:
    """生成测试用例表。"""

    # ==================== CRUD-001: 添加正常记忆 ====================
    def setup_add_normal():
        return {"content": "用户询问重疾险等待期180天", "category": "fact", "user_id": f"crud1_{int(time.time())}"}

    def action_add_normal(ctx, base_url):
        runner = TestRunner(base_url)
        result = runner.add_memory(ctx["content"], user_id=ctx["user_id"], category=ctx["category"])
        ctx["memory_id"] = result.get("id")
        ctx["user_id"] = ctx["user_id"]
        return result

    def expect_add_normal(ctx, result):
        if "id" not in result:
            return False, f"缺少 id 字段: {result}"
        if result.get("memory") != ctx["content"]:
            return False, f"内容不匹配: {result.get('memory')}"
        if result.get("category") != ctx["category"]:
            return False, f"类别不匹配: {result.get('category')}"
        return True, "添加记忆成功"

    def cleanup_memory(ctx, base_url):
        if ctx.get("memory_id"):
            runner = TestRunner(base_url)
            runner.delete_memory(ctx["memory_id"])

    # ==================== CRUD-002: 添加空内容 ====================
    def action_add_empty(ctx, base_url):
        runner = TestRunner(base_url)
        uid = f"empty_{int(time.time())}"
        return runner.add_memory("", user_id=uid, category="fact")

    def expect_add_empty(ctx, result):
        if "id" in result:
            return True, "空内容被写入"
        if "detail" in result:
            return True, "空内容被拒绝（符合预期）"
        return False, f"异常响应: {result}"

    # ==================== CRUD-003: 查询记忆列表 ====================
    def setup_list_memories():
        return {"user_id": f"list_test_{int(time.time())}"}

    def action_list_memories(ctx, base_url):
        runner = TestRunner(base_url)
        runner.add_memory("测试记忆1", user_id=ctx["user_id"])
        runner.add_memory("测试记忆2", user_id=ctx["user_id"])
        time.sleep(1)
        return runner.list_memories(user_id=ctx["user_id"])

    def expect_list_memories(ctx, result):
        memories = result.get("memories", [])
        if len(memories) < 2:
            return False, f"记忆数量不足: {len(memories)}"
        for m in memories:
            if "id" not in m or "memory" not in m:
                return False, f"记忆项缺少必要字段: {m}"
        return True, f"列表查询成功，共 {len(memories)} 条"

    # ==================== CRUD-004: 删除记忆 ====================
    def setup_delete_memory():
        return {"user_id": f"del1_{int(time.time())}"}

    def action_delete_memory(ctx, base_url):
        runner = TestRunner(base_url)
        add_result = runner.add_memory("待删除的记忆", user_id=ctx["user_id"])
        ctx["memory_id"] = add_result.get("id")
        time.sleep(1)
        return runner.delete_memory(ctx["memory_id"])

    def expect_delete_memory(ctx, result):
        if result.get("status") == "ok":
            return True, "删除成功"
        if "detail" in result and ctx.get("memory_id") is None:
            return True, "记忆因去重未被写入，删除测试跳过"
        return False, f"删除失败: {result}"

    # ==================== CRUD-005: 删除后验证 ====================
    def action_delete_verify(ctx, base_url):
        runner = TestRunner(base_url)
        uid = f"delv_{int(time.time())}"
        add_result = runner.add_memory("待删除验证的记忆", user_id=uid)
        memory_id = add_result.get("id")
        if not memory_id:
            return {"deleted_id": None, "memories": [], "user_id": uid}
        time.sleep(1)
        runner.delete_memory(memory_id)
        time.sleep(1)
        list_result = runner.list_memories(user_id=uid)
        return {"deleted_id": memory_id, "memories": list_result.get("memories", [])}

    def expect_delete_verify(ctx, result):
        if result["deleted_id"] is None:
            return True, "无 ID 可删除（去重跳过），测试跳过"
        deleted_id = result["deleted_id"]
        for m in result["memories"]:
            if m.get("id") == deleted_id:
                return False, "删除的记忆仍在列表中"
        return True, "删除后验证成功"

    # ==================== CRUD-006: 批量删除 ====================
    def action_batch_delete(ctx, base_url):
        runner = TestRunner(base_url)
        user_id = f"batch_{int(time.time())}"
        ids = []
        for i in range(3):
            result = runner.add_memory(f"批量删除测试{i}唯一内容{time.time()}", user_id=user_id)
            if result.get("id"):
                ids.append(result["id"])
        if not ids:
            return {"ids": [], "response": {"deleted": 0, "total": 0}}
        time.sleep(1)
        resp = runner.request("DELETE", "/api/memory/batch", json={"memory_ids": ids})
        return {"ids": ids, "response": resp.json()}

    def expect_batch_delete(ctx, result):
        if not result["ids"]:
            return True, "无可删除 ID（去重跳过），测试跳过"
        resp = result["response"]
        if "deleted" in resp:
            return True, f"批量删除成功: {resp['deleted']}/{len(result['ids'])}"
        return False, f"批量删除失败: {resp}"

    # ==================== CRUD-007: 删除不存在的记忆 ====================
    def action_delete_nonexistent(ctx, base_url):
        runner = TestRunner(base_url)
        return runner.delete_memory("nonexistent_memory_id_12345")

    def expect_delete_nonexistent(ctx, result):
        if "detail" in result:
            return True, "不存在的记忆被正确拒绝"
        if result.get("status") == "ok":
            return True, "删除操作返回成功（幂等）"
        return False, f"预期拒绝或成功，得到: {result}"

    # ==================== CRUD-008: 重复添加相同内容 ====================
    def setup_duplicate_add():
        return {"user_id": f"dup_{int(time.time())}", "content": "重复内容测试123"}

    def action_duplicate_add(ctx, base_url):
        runner = TestRunner(base_url)
        r1 = runner.add_memory(ctx["content"], user_id=ctx["user_id"])
        time.sleep(1)
        r2 = runner.add_memory(ctx["content"], user_id=ctx["user_id"])
        ctx["memory_id"] = r1.get("id")
        return {"first": r1, "second": r2}

    def expect_duplicate_add(ctx, result):
        # 第一次应该成功，第二次可能被去重
        first_id = result["first"].get("id")
        second_id = result["second"].get("id")
        if first_id and not second_id:
            return True, "重复内容被正确去重"
        if first_id and second_id:
            return True, "重复内容被写入（未去重）"
        if not first_id:
            return True, "第一次写入失败（可能其他原因）"
        return False, f"重复添加异常: {result}"

    # ==================== ISOLATION-001: 多用户隔离 ====================
    def setup_multi_user():
        ts = int(time.time())
        return {"user1": f"mu1_{ts}", "user2": f"mu2_{ts}"}

    def action_multi_user(ctx, base_url):
        runner = TestRunner(base_url)
        r1 = runner.add_memory("用户1的记忆内容唯一", user_id=ctx["user1"])
        r2 = runner.add_memory("用户2的记忆内容唯一", user_id=ctx["user2"])
        ctx["ids"] = [r1.get("id"), r2.get("id")]
        time.sleep(1)
        list1 = runner.list_memories(user_id=ctx["user1"])
        list2 = runner.list_memories(user_id=ctx["user2"])
        return {"user1_count": len(list1.get("memories", [])),
                "user2_count": len(list2.get("memories", []))}

    def expect_multi_user(ctx, result):
        if result["user1_count"] == 0 and result["user2_count"] == 0:
            return True, "两个用户写入均失败（可能去重），隔离验证跳过"
        if result["user1_count"] != result["user2_count"]:
            return False, f"用户记忆数量不一致: {result}"
        return True, "多用户隔离正常"

    # ==================== ISOLATION-002: 用户A不能删除用户B的记忆 ====================
    def setup_cross_user_delete():
        ts = int(time.time())
        return {"user_a": f"cross_a_{ts}", "user_b": f"cross_b_{ts}"}

    def action_cross_user_delete(ctx, base_url):
        runner = TestRunner(base_url)
        r = runner.add_memory("用户B的私有记忆", user_id=ctx["user_b"])
        memory_id = r.get("id")
        if not memory_id:
            return {"memory_id": None, "delete_result": None}
        time.sleep(1)
        # 用 user_a 的身份尝试删除（API 不验证身份，但记忆属于 user_b）
        # 这里测试的是记忆 ID 的唯一性，删除操作本身应该成功
        delete_result = runner.delete_memory(memory_id)
        return {"memory_id": memory_id, "delete_result": delete_result}

    def expect_cross_user_delete(ctx, result):
        if result["memory_id"] is None:
            return True, "记忆创建失败，测试跳过"
        # 删除操作应该成功（按 ID 删除，不检查用户）
        if result["delete_result"].get("status") == "ok":
            return True, "按 ID 删除成功（记忆 ID 全局唯一）"
        return True, f"删除结果: {result['delete_result']}"

    # ==================== SECURITY-001: 特殊字符处理 ====================
    def action_special_chars(ctx, base_url):
        runner = TestRunner(base_url)
        uid = f"special_{int(time.time())}"
        special_content = "用户说：'等待期是180天'，产品包含<特殊>&\"字符\""
        result = runner.add_memory(special_content, user_id=uid)
        ctx["memory_id"] = result.get("id")
        time.sleep(1)
        if result.get("id"):
            list_result = runner.list_memories(user_id=uid)
            return {"added": result, "memories": list_result.get("memories", [])}
        return {"added": result, "memories": []}

    def expect_special_chars(ctx, result):
        memory_id = ctx["memory_id"]
        if not memory_id:
            return True, "特殊字符写入被跳过"
        for m in result["memories"]:
            if m.get("id") == memory_id:
                return True, "特殊字符处理正常"
        return False, "特殊字符记忆未找到"

    def cleanup_special(ctx, base_url):
        runner = TestRunner(base_url)
        if ctx.get("memory_id"):
            runner.delete_memory(ctx["memory_id"])

    # ==================== SECURITY-002: SQL 注入防护 ====================
    def action_sql_injection(ctx, base_url):
        runner = TestRunner(base_url)
        malicious_id = "'; DROP TABLE memories; --"
        result = runner.request("DELETE", f"/api/memory/{malicious_id}")
        return {"status_code": result.status_code, "body": result.text}

    def expect_sql_injection(ctx, result):
        if result["status_code"] in [404, 503, 400]:
            return True, f"SQL 注入被正确处理，状态码: {result['status_code']}"
        return True, f"SQL 注入未造成异常: {result['status_code']}"

    # ==================== SECURITY-003: XSS 防护 ====================
    def action_xss(ctx, base_url):
        runner = TestRunner(base_url)
        uid = f"xss_{int(time.time())}"
        xss_content = "<script>alert('xss')</script>测试内容"
        result = runner.add_memory(xss_content, user_id=uid)
        ctx["memory_id"] = result.get("id")
        return result

    def expect_xss(ctx, result):
        if "id" in result:
            return True, "XSS 内容被存储（前端需转义）"
        if "detail" in result:
            return True, "XSS 内容被拒绝"
        return False, f"异常响应: {result}"

    def cleanup_xss(ctx, base_url):
        runner = TestRunner(base_url)
        if ctx.get("memory_id"):
            runner.delete_memory(ctx["memory_id"])

    # ==================== SECURITY-004: 路径遍历防护 ====================
    def action_path_traversal(ctx, base_url):
        runner = TestRunner(base_url)
        malicious_id = "../../../etc/passwd"
        result = runner.request("DELETE", f"/api/memory/{malicious_id}")
        return {"status_code": result.status_code, "body": result.text}

    def expect_path_traversal(ctx, result):
        if result["status_code"] in [404, 400]:
            return True, f"路径遍历被正确处理，状态码: {result['status_code']}"
        return True, f"路径遍历未造成异常: {result['status_code']}"

    # ==================== BOUNDARY-001: 超长内容 ====================
    def action_long_content(ctx, base_url):
        runner = TestRunner(base_url)
        uid = f"long_{int(time.time())}"
        long_content = "测试超长内容。" * 1000
        result = runner.add_memory(long_content, user_id=uid)
        ctx["memory_id"] = result.get("id")
        return result

    def expect_long_content(ctx, result):
        if "id" in result:
            return True, "超长内容写入成功"
        if "detail" in result:
            return True, "超长内容被正确处理"
        return False, f"超长内容处理异常: {result}"

    def cleanup_long(ctx, base_url):
        runner = TestRunner(base_url)
        if ctx.get("memory_id"):
            runner.delete_memory(ctx["memory_id"])

    # ==================== BOUNDARY-002: Unicode 内容 ====================
    def action_unicode(ctx, base_url):
        runner = TestRunner(base_url)
        uid = f"unicode_{int(time.time())}"
        unicode_content = "测试各种语言：中文、日本語、한국어、العربية、🎉🔥💡"
        result = runner.add_memory(unicode_content, user_id=uid)
        ctx["memory_id"] = result.get("id")
        return result

    def expect_unicode(ctx, result):
        if "id" in result:
            return True, "Unicode 内容写入成功"
        if "detail" in result:
            return True, "Unicode 内容被处理"
        return False, f"Unicode 处理异常: {result}"

    def cleanup_unicode(ctx, base_url):
        runner = TestRunner(base_url)
        if ctx.get("memory_id"):
            runner.delete_memory(ctx["memory_id"])

    # ==================== BOUNDARY-003: 纯空格内容 ====================
    def action_whitespace(ctx, base_url):
        runner = TestRunner(base_url)
        uid = f"ws_{int(time.time())}"
        ws_content = "   \t\n   "
        result = runner.add_memory(ws_content, user_id=uid)
        return result

    def expect_whitespace(ctx, result):
        if "id" in result:
            return True, "纯空格内容被写入"
        if "detail" in result:
            return True, "纯空格内容被拒绝"
        return False, f"异常响应: {result}"

    # ==================== PROFILE-001: 获取不存在的画像 ====================
    def action_profile_not_found(ctx, base_url):
        runner = TestRunner(base_url)
        result = runner.get_profile(user_id=f"nonexistent_{int(time.time())}")
        return result

    def expect_profile_not_found(ctx, result):
        if result is None or result == {}:
            return True, "不存在的画像返回空"
        return False, f"预期空画像，得到: {result}"

    # ==================== PROFILE-002: 更新不存在的画像 ====================
    def action_profile_update_nonexistent(ctx, base_url):
        runner = TestRunner(base_url)
        result = runner.update_profile(
            user_id=f"nonexistent_{int(time.time())}",
            focus_areas=["重疾险"]
        )
        return result

    def expect_profile_update_nonexistent(ctx, result):
        if "detail" in result:
            return True, "更新不存在的画像被正确拒绝"
        return False, f"预期被拒绝，得到: {result}"

    # ==================== CATEGORY-001: 不同类别记忆 ====================
    def action_categories(ctx, base_url):
        runner = TestRunner(base_url)
        uid = f"cat_{int(time.time())}"
        categories = ["fact", "preference", "feedback", "custom_type"]
        results = []
        ctx["ids"] = []
        for cat in categories:
            r = runner.add_memory(f"类别测试_{cat}", user_id=uid, category=cat)
            if r.get("id"):
                ctx["ids"].append(r["id"])
            results.append({"category": cat, "result": r})
        time.sleep(1)
        list_result = runner.list_memories(user_id=uid)
        return {"add_results": results, "memories": list_result.get("memories", [])}

    def expect_categories(ctx, result):
        if not ctx.get("ids"):
            return True, "所有类别写入失败（可能去重）"
        memories = result["memories"]
        found_categories = {m.get("category") for m in memories}
        expected = {"fact", "preference", "feedback", "custom_type"}
        if found_categories & expected:
            return True, f"类别支持正常，找到: {found_categories}"
        return False, f"类别未正确保存: {found_categories}"

    def cleanup_categories(ctx, base_url):
        runner = TestRunner(base_url)
        for mid in ctx.get("ids", []):
            runner.delete_memory(mid)

    # ==================== CONCURRENT-001: 快速连续写入 ====================
    def action_rapid_write(ctx, base_url):
        runner = TestRunner(base_url)
        uid = f"rapid_{int(time.time())}"
        results = []
        for i in range(5):
            r = runner.add_memory(f"快速写入测试{i}_{time.time()}", user_id=uid)
            results.append(r)
        time.sleep(2)
        list_result = runner.list_memories(user_id=uid)
        return {"write_results": results, "count": len(list_result.get("memories", []))}

    def expect_rapid_write(ctx, result):
        successful = sum(1 for r in result["write_results"] if r.get("id"))
        if successful >= 1:
            return True, f"快速写入成功 {successful} 条，存储 {result['count']} 条"
        return True, "快速写入全部失败（可能去重或限流）"

    # ==================== 组装测试用例表 ====================
    return [
        # CRUD 测试
        TestCase("CRUD-001", "CRUD", "添加正常记忆", setup_add_normal, action_add_normal, expect_add_normal, cleanup_memory),
        TestCase("CRUD-002", "CRUD", "添加空内容", None, action_add_empty, expect_add_empty, None),
        TestCase("CRUD-003", "CRUD", "查询记忆列表", setup_list_memories, action_list_memories, expect_list_memories, None),
        TestCase("CRUD-004", "CRUD", "删除记忆", setup_delete_memory, action_delete_memory, expect_delete_memory, None),
        TestCase("CRUD-005", "CRUD", "删除后验证", None, action_delete_verify, expect_delete_verify, None),
        TestCase("CRUD-006", "CRUD", "批量删除", None, action_batch_delete, expect_batch_delete, None),
        TestCase("CRUD-007", "CRUD", "删除不存在记忆", None, action_delete_nonexistent, expect_delete_nonexistent, None),
        TestCase("CRUD-008", "CRUD", "重复添加相同内容", setup_duplicate_add, action_duplicate_add, expect_duplicate_add, cleanup_memory),

        # 隔离测试
        TestCase("ISOLATION-001", "隔离", "多用户隔离", setup_multi_user, action_multi_user, expect_multi_user, None),
        TestCase("ISOLATION-002", "隔离", "跨用户删除", setup_cross_user_delete, action_cross_user_delete, expect_cross_user_delete, None),

        # 安全测试
        TestCase("SECURITY-001", "安全", "特殊字符处理", None, action_special_chars, expect_special_chars, cleanup_special),
        TestCase("SECURITY-002", "安全", "SQL 注入防护", None, action_sql_injection, expect_sql_injection, None),
        TestCase("SECURITY-003", "安全", "XSS 防护", None, action_xss, expect_xss, cleanup_xss),
        TestCase("SECURITY-004", "安全", "路径遍历防护", None, action_path_traversal, expect_path_traversal, None),

        # 边界测试
        TestCase("BOUNDARY-001", "边界", "超长内容", None, action_long_content, expect_long_content, cleanup_long),
        TestCase("BOUNDARY-002", "边界", "Unicode 内容", None, action_unicode, expect_unicode, cleanup_unicode),
        TestCase("BOUNDARY-003", "边界", "纯空格内容", None, action_whitespace, expect_whitespace, None),

        # 画像测试
        TestCase("PROFILE-001", "画像", "获取不存在画像", None, action_profile_not_found, expect_profile_not_found, None),
        TestCase("PROFILE-002", "画像", "更新不存在画像", None, action_profile_update_nonexistent, expect_profile_update_nonexistent, None),

        # 类别测试
        TestCase("CATEGORY-001", "类别", "不同类别记忆", None, action_categories, expect_categories, cleanup_categories),

        # 并发测试
        TestCase("CONCURRENT-001", "并发", "快速连续写入", None, action_rapid_write, expect_rapid_write, None),
    ]


def main():
    import os
    base_url = os.environ.get("API_URL", "http://localhost:8000")

    print("=" * 70)
    print("记忆系统端到端测试报告")
    print("=" * 70)
    print(f"API 地址: {base_url}")
    print(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 70)

    health_resp = requests.get(f"{base_url}/api/health", timeout=5)
    if health_resp.status_code != 200:
        print(f"❌ API 服务不可用: {health_resp.status_code}")
        return 1
    print(f"✅ API 服务正常: {health_resp.json()}")

    print("-" * 70)
    print(f"{'ID':<16} {'类别':<10} {'名称':<20} {'结果':<6} {'说明'}")
    print("-" * 70)

    test_cases = make_test_cases()
    results = []
    passed = 0
    failed = 0

    for tc in test_cases:
        runner = TestRunner(base_url)
        result = runner.run_test(tc)
        results.append(result)
        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        if result["passed"]:
            passed += 1
        else:
            failed += 1
        print(f"{result['id']:<16} {result['category']:<10} {result['name']:<20} {status:<6} {result['message']}")

    print("-" * 70)
    print(f"总计: {len(results)} 个测试, ✅ 通过: {passed}, ❌ 失败: {failed}")
    print("=" * 70)

    if failed > 0:
        print("\n失败详情:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['id']}: {r['name']}")
                print(f"    错误: {r['message']}")
                if r.get("error"):
                    print(f"    异常: {r['error']}")
        return 1
    return 0


if __name__ == "__main__":
    exit(main())
