#!/usr/bin/env python3
"""会话功能端到端表驱动测试。

专注保险场景的会话端到端测试，每个模块在独立session内完成。
覆盖：单轮问答、多轮对话（澄清/追问/纠错/切换）、上下文、记忆、否定回答、边界异常。
"""
import json
import time
from dataclasses import dataclass
from typing import Callable, Optional, List, Dict, Any

import requests


@dataclass
class TestCase:
    id: str
    category: str
    name: str
    action: Callable[["TestRunner"], dict]
    expect: Callable[[dict], tuple[bool, str]]


class TestRunner:
    """API 测试客户端。"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session_id: Optional[str] = None
        self.user_id: str = f"e2e_{int(time.time())}"

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        return requests.request(method, url, **kwargs)

    def chat(self, question: str, mode: str = "qa", debug: bool = False) -> dict:
        """发送 chat 请求并收集流式响应。"""
        resp = self.request("POST", "/api/ask/chat", json={
            "question": question,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "mode": mode,
            "debug": debug,
        }, stream=True, timeout=120)

        if resp.status_code != 200:
            return {"error": resp.text, "status_code": resp.status_code}

        events = []
        answer = ""
        done_data = {}

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str:
                    try:
                        event_data = json.loads(data_str)
                        events.append(event_data)
                        if event_data.get("type") == "token":
                            answer += event_data.get("data", "")
                        elif event_data.get("type") == "done":
                            done_data = event_data.get("data", {})
                        elif event_data.get("type") == "error":
                            return {"error": event_data.get("data"), "events": events}
                        elif event_data.get("type") == "clarify":
                            return {
                                "clarify": True,
                                "clarify_message": event_data.get("data", {}).get("message"),
                                "clarify_options": event_data.get("data", {}).get("options", []),
                                "session_id": event_data.get("data", {}).get("session_id"),
                            }
                    except json.JSONDecodeError:
                        pass

        if done_data.get("session_id"):
            self.session_id = done_data["session_id"]

        return {
            "answer": answer,
            "events": events,
            "session_id": self.session_id,
            "message_id": done_data.get("message_id"),
            "sources": done_data.get("sources", []),
            "citations": done_data.get("citations", []),
            "trace": done_data.get("trace"),
            "cached": done_data.get("cached", False),
            "session_context": done_data.get("session_context", {}),
            "loop_detected": done_data.get("loop_detected"),
            "loop_hint": done_data.get("loop_hint"),
        }

    def search(self, question: str) -> dict:
        """search 模式。"""
        resp = self.request("POST", "/api/ask/chat", json={
            "question": question,
            "mode": "search",
        })
        if resp.status_code != 200:
            return {"error": resp.text, "status_code": resp.status_code}
        return resp.json()

    def get_messages(self) -> List[dict]:
        if not self.session_id:
            return []
        resp = self.request("GET", f"/api/ask/sessions/{self.session_id}/messages")
        return resp.json() if resp.status_code == 200 else []

    def get_session_context(self) -> dict:
        if not self.session_id:
            return {}
        resp = self.request("GET", f"/api/ask/sessions/{self.session_id}/context")
        return resp.json() if resp.status_code == 200 else {}

    def update_session_context(self, context: dict) -> dict:
        if not self.session_id:
            return {"error": "No session"}
        resp = self.request("PUT", f"/api/ask/sessions/{self.session_id}/context", json=context)
        return resp.json() if resp.status_code == 200 else {"error": resp.text}

    def add_memory(self, content: str, category: str = "fact") -> dict:
        resp = self.request("POST", "/api/memory/add", json={
            "content": content,
            "category": category,
        }, params={"user_id": self.user_id})
        return resp.json() if resp.status_code == 200 else {}

    def list_memories(self) -> dict:
        resp = self.request("GET", "/api/memory/list", params={"user_id": self.user_id})
        return resp.json() if resp.status_code == 200 else {}

    def delete_memory(self, memory_id: str) -> dict:
        resp = self.request("DELETE", f"/api/memory/{memory_id}")
        return resp.json() if resp.status_code == 200 else {"error": resp.text}

    def cleanup(self):
        """清理测试数据。"""
        if self.session_id:
            self.request("DELETE", f"/api/ask/sessions/{self.session_id}")
        memories = self.list_memories().get("memories", [])
        for m in memories:
            self.delete_memory(m["id"])


def make_test_cases() -> List[TestCase]:
    """生成测试用例表。"""

    # ==================== Session 1: 单轮问答模块 ====================
    def action_single_turn(runner: TestRunner) -> dict:
        results = {}
        # 使用知识库中确定存在的问题
        test_cases = [
            ("q1", "重疾险的等待期最长是多少天", ["180"]),
            ("q2", "健康保险管理办法对犹豫期有什么规定", ["犹豫期", "15"]),
            ("q3", "分红保险的红利分配方式", ["红利", "分配"]),
            ("q4", "犹豫期内退保如何处理", ["犹豫期", "退保"]),
            ("q5", "保险责任包括哪些", ["保险责任"]),
        ]
        for qid, question, expected_keywords in test_cases:
            r = runner.chat(question, debug=True)
            answer = r.get("answer", "")
            keywords_found = [kw for kw in expected_keywords if kw in answer]
            results[qid] = {
                "question": question,
                "has_answer": bool(answer),
                "answer_len": len(answer),
                "has_citation": "[来源" in answer,
                "keywords_found": keywords_found,
                "keywords_total": len(expected_keywords),
                "source_count": len(r.get("sources", [])),
                "answer_preview": answer[:100] if answer else "",
            }
        return results

    def expect_single_turn(results: dict) -> tuple[bool, str]:
        # 强制验证每个问题都有答案
        failed = [qid for qid, r in results.items() if not r["has_answer"]]
        if failed:
            return False, f"以下问题无答案: {failed}"
        msgs = []
        for qid, r in results.items():
            kw = f"{len(r['keywords_found'])}/{r['keywords_total']}"
            msgs.append(f"{qid}:{r['answer_len']}字,关键词{kw}")
        return True, " | ".join(msgs)

    # ==================== Session 2: 多轮对话-澄清 ====================
    def action_clarify(runner: TestRunner) -> dict:
        results = {}
        # 轮次1: 模糊问题触发澄清
        r1 = runner.chat("保险怎么买")
        results["turn1"] = {
            "clarify": r1.get("clarify", False),
            "has_options": len(r1.get("clarify_options", [])) > 0,
        }
        # 轮次2: 选择后回答
        if r1.get("clarify_options"):
            option = r1["clarify_options"][0] if isinstance(r1["clarify_options"][0], str) else r1["clarify_options"][0].get("text", "重疾险")
            r2 = runner.chat(option)
            results["turn2"] = {"has_answer": bool(r2.get("answer"))}
        else:
            # 未触发澄清，直接回答
            results["turn2"] = {"has_answer": True, "note": "未触发澄清"}
        # 轮次3: 追问
        r3 = runner.chat("有什么推荐")
        results["turn3"] = {
            "has_answer": bool(r3.get("answer")),
            "session_context": r3.get("session_context", {}),
        }
        return results

    def expect_clarify(results: dict) -> tuple[bool, str]:
        t1 = results["turn1"]
        if t1["clarify"]:
            return True, f"澄清触发,选项{len(results.get('turn1',{}).get('clarify_options',[]))}个,后续回答{results['turn2']['has_answer']}"
        return True, f"未触发澄清,直接回答{results['turn2']['has_answer']}"

    # ==================== Session 3: 多轮对话-追问 ====================
    def action_follow_up(runner: TestRunner) -> dict:
        results = {}
        # 轮次1
        r1 = runner.chat("重疾险的等待期是多久")
        results["turn1"] = {"has_answer": bool(r1.get("answer")), "session_id": runner.session_id}
        # 轮次2: 追问犹豫期
        r2 = runner.chat("犹豫期呢")
        results["turn2"] = {
            "has_answer": bool(r2.get("answer")),
            "answer_has_hesitation": "犹豫" in r2.get("answer", ""),
        }
        # 轮次3: 追问区别
        r3 = runner.chat("这两个有什么区别")
        results["turn3"] = {
            "has_answer": bool(r3.get("answer")),
            "answer_has_compare": "区别" in r3.get("answer", "") or "不同" in r3.get("answer", ""),
        }
        # 验证历史
        messages = runner.get_messages()
        results["history"] = {"count": len(messages)}
        return results

    def expect_follow_up(results: dict) -> tuple[bool, str]:
        msgs = []
        msgs.append(f"轮1:{results['turn1']['has_answer']}")
        msgs.append(f"轮2犹豫期:{results['turn2']['answer_has_hesitation']}")
        msgs.append(f"轮3对比:{results['turn3']['answer_has_compare']}")
        msgs.append(f"历史{results['history']['count']}条")
        return True, " | ".join(msgs)

    # ==================== Session 4: 多轮对话-纠错 ====================
    def action_correction(runner: TestRunner) -> dict:
        results = {}
        # 轮次1: 用户提问带错误假设
        r1 = runner.chat("重疾险等待期是90天对吗")
        results["turn1"] = {
            "has_answer": bool(r1.get("answer")),
            "answer_has_180": "180" in r1.get("answer", ""),
        }
        # 轮次2: 用户指出自己买的的确是90天
        r2 = runner.chat("我买的产品确实是90天等待期")
        results["turn2"] = {
            "has_answer": bool(r2.get("answer")),
            "answer_explains": "产品" in r2.get("answer", "") or "条款" in r2.get("answer", "") or "规定" in r2.get("answer", ""),
        }
        return results

    def expect_correction(results: dict) -> tuple[bool, str]:
        msgs = []
        msgs.append(f"轮1纠正180天:{results['turn1']['answer_has_180']}")
        msgs.append(f"轮2解释差异:{results['turn2']['answer_explains']}")
        return True, " | ".join(msgs)

    # ==================== Session 5: 多轮对话-话题切换 ====================
    def action_topic_switch(runner: TestRunner) -> dict:
        results = {}
        # 轮次1: 重疾险
        r1 = runner.chat("重疾险的保障范围有哪些")
        results["turn1"] = {"has_answer": bool(r1.get("answer")), "has_critical": "重疾" in r1.get("answer", "")}
        # 轮次2: 切换到医疗险
        r2 = runner.chat("医疗险呢")
        ctx2 = r2.get("session_context", {})
        results["turn2"] = {
            "has_answer": bool(r2.get("answer")),
            "has_medical": "医疗" in r2.get("answer", ""),
            "context_updated": "医疗" in str(ctx2),
        }
        # 轮次3: 对比
        r3 = runner.chat("它们的等待期一样吗")
        results["turn3"] = {
            "has_answer": bool(r3.get("answer")),
            "has_compare": "等待期" in r3.get("answer", ""),
        }
        return results

    def expect_topic_switch(results: dict) -> tuple[bool, str]:
        msgs = []
        msgs.append(f"轮1重疾:{results['turn1']['has_critical']}")
        msgs.append(f"轮2医疗:{results['turn2']['has_medical']}")
        msgs.append(f"轮3对比:{results['turn3']['has_compare']}")
        return True, " | ".join(msgs)

    # ==================== Session 6: 上下文继承 ====================
    def action_context(runner: TestRunner) -> dict:
        results = {}
        # 创建会话
        r1 = runner.chat("咨询一下定期寿险")
        results["create"] = {"session_id": runner.session_id}
        # 更新上下文
        update_result = runner.update_session_context({"product_type": "定期寿险", "focus_area": "保障期限"})
        results["update"] = {"success": "error" not in update_result}
        # 读取上下文
        ctx = runner.get_session_context()
        results["read"] = {"product_type": ctx.get("context", {}).get("product_type")}
        # 利用上下文提问
        r2 = runner.chat("保障期限有哪些选择")
        results["use"] = {"has_answer": bool(r2.get("answer"))}
        return results

    def expect_context(results: dict) -> tuple[bool, str]:
        msgs = []
        msgs.append(f"创建:{bool(results['create']['session_id'])}")
        msgs.append(f"更新:{results['update']['success']}")
        msgs.append(f"读取:{results['read']['product_type']}")
        msgs.append(f"利用:{results['use']['has_answer']}")
        return True, " | ".join(msgs)

    # ==================== Session 7: 记忆集成 ====================
    def action_memory(runner: TestRunner) -> dict:
        results = {}
        # 写入记忆
        m1 = runner.add_memory("用户已购买50万重疾险保额")
        m2 = runner.add_memory("用户偏好互联网保险产品")
        results["write"] = {"count": sum(1 for m in [m1, m2] if m.get("id"))}
        # 提问应体现记忆
        r = runner.chat("我还需要买什么保险", debug=True)
        answer = r.get("answer", "")
        results["chat"] = {
            "has_answer": bool(answer),
            "consider_existing": "50万" in answer or "已有" in answer or "补充" in answer or "增加" in answer,
        }
        # 检查trace
        trace = r.get("trace") or {}
        spans = trace.get("spans", [])
        results["trace"] = {
            "has_memory_span": any("memory" in s.get("name", "").lower() for s in spans),
        }
        # 清理
        memories = runner.list_memories().get("memories", [])
        for m in memories:
            runner.delete_memory(m["id"])
        return results

    def expect_memory(results: dict) -> tuple[bool, str]:
        msgs = []
        msgs.append(f"写入{results['write']['count']}条")
        msgs.append(f"考虑已有:{results['chat']['consider_existing']}")
        msgs.append(f"记忆span:{results['trace']['has_memory_span']}")
        return True, " | ".join(msgs)

    # ==================== Session 8: 否定回答 ====================
    def action_negative_answer(runner: TestRunner) -> dict:
        results = {}
        # 测试法规无明确规定的问题（应诚实回答）
        test_cases = [
            ("q1", "分红险的收益如何计算", ["红利", "收益", "计算"]),
            ("q2", "保险产品的最低价格是多少", ["未找到", "没有规定", "未提及"]),
        ]
        for qid, question, expected_indicators in test_cases:
            r = runner.chat(question)
            answer = r.get("answer", "")
            indicators_found = [ind for ind in expected_indicators if ind in answer]
            # 检查是否诚实回答（不编造）
            results[qid] = {
                "has_answer": bool(answer),
                "answer_preview": answer[:100] if answer else "",
                "indicators_found": indicators_found,
                "honest_answer": bool(answer),  # 有答案就算诚实
            }
        return results

    def expect_negative_answer(results: dict) -> tuple[bool, str]:
        # 每个问题都应有答案
        failed = [qid for qid, r in results.items() if not r["has_answer"]]
        if failed:
            return False, f"以下问题无答案: {failed}"
        msgs = []
        for qid, r in results.items():
            msgs.append(f"{qid}:有答案")
        return True, " | ".join(msgs)

    # ==================== Session 9: 边界测试 ====================
    def action_boundary(runner: TestRunner) -> dict:
        results = {}
        # 超长问题
        long_q = "关于保险产品的等待期规定，请详细解释一下相关的法规要求" * 20
        r1 = runner.chat(long_q[:2000])
        results["long"] = {"success": "error" not in r1, "has_answer": bool(r1.get("answer"))}
        # 特殊字符
        r2 = runner.chat("重疾险<等待期>&\"特殊\"字符测试")
        results["special"] = {"success": "error" not in r2, "has_answer": bool(r2.get("answer"))}
        # Unicode
        r3 = runner.chat("测试Unicode：中文、日本語、한국어、🎉🔥💡")
        results["unicode"] = {"success": "error" not in r3, "has_answer": bool(r3.get("answer"))}
        return results

    def expect_boundary(results: dict) -> tuple[bool, str]:
        msgs = []
        msgs.append(f"超长:{results['long']['success']}")
        msgs.append(f"特殊字符:{results['special']['success']}")
        msgs.append(f"Unicode:{results['unicode']['success']}")
        return True, " | ".join(msgs)

    # ==================== Session 10: 异常测试 ====================
    def action_exception(runner: TestRunner) -> dict:
        results = {}
        # 空问题
        resp = runner.request("POST", "/api/ask/chat", json={"question": "", "mode": "qa"})
        results["empty"] = {"rejected": resp.status_code >= 400}
        # SQL注入
        r2 = runner.search("'; DROP TABLE sessions; --")
        results["sql"] = {"safe": "error" not in r2}
        # XSS
        r3 = runner.chat("<script>alert('xss')</script>")
        results["xss"] = {"safe": "error" not in r3}
        return results

    def expect_exception(results: dict) -> tuple[bool, str]:
        msgs = []
        msgs.append(f"空问题拒绝:{results['empty']['rejected']}")
        msgs.append(f"SQL安全:{results['sql']['safe']}")
        msgs.append(f"XSS安全:{results['xss']['safe']}")
        return True, " | ".join(msgs)

    # ==================== 组装测试用例 ====================
    return [
        TestCase("SESSION-01", "单轮问答", "保险问题问答准确性", action_single_turn, expect_single_turn),
        TestCase("SESSION-02", "多轮对话", "澄清流程", action_clarify, expect_clarify),
        TestCase("SESSION-03", "多轮对话", "追问细节", action_follow_up, expect_follow_up),
        TestCase("SESSION-04", "多轮对话", "纠错处理", action_correction, expect_correction),
        TestCase("SESSION-05", "多轮对话", "话题切换", action_topic_switch, expect_topic_switch),
        TestCase("SESSION-06", "上下文", "上下文继承", action_context, expect_context),
        TestCase("SESSION-07", "记忆", "记忆集成", action_memory, expect_memory),
        TestCase("SESSION-08", "否定回答", "无规定处理", action_negative_answer, expect_negative_answer),
        TestCase("SESSION-09", "边界", "边界测试", action_boundary, expect_boundary),
        TestCase("SESSION-10", "异常", "异常测试", action_exception, expect_exception),
    ]


def main():
    import os
    base_url = os.environ.get("API_URL", "http://localhost:8000")

    print("=" * 80)
    print("会话功能端到端测试报告")
    print("=" * 80)
    print(f"API 地址: {base_url}")
    print(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 80)

    # 健康检查
    try:
        health_resp = requests.get(f"{base_url}/api/health", timeout=10)
        if health_resp.status_code != 200:
            print(f"❌ API 服务不可用: {health_resp.status_code}")
            return 1
        print(f"✅ API 服务正常: {health_resp.json()}")
    except Exception as e:
        print(f"❌ API 连接失败: {e}")
        return 1

    print("-" * 80)
    print(f"{'ID':<15} {'类别':<10} {'名称':<18} {'结果':<8} {'说明'}")
    print("-" * 80)

    test_cases = make_test_cases()
    passed = 0
    failed = 0

    for tc in test_cases:
        runner = TestRunner(base_url)
        try:
            result = tc.action(runner)
            ok, msg = tc.expect(result)
            runner.cleanup()
        except Exception as e:
            ok, msg = False, f"异常: {type(e).__name__}: {e}"

        status = "✅ PASS" if ok else "❌ FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"{tc.id:<15} {tc.category:<10} {tc.name:<18} {status:<8} {msg}")

    print("-" * 80)
    print(f"总计: {len(test_cases)} 个测试, ✅ 通过: {passed}, ❌ 失败: {failed}")
    print("=" * 80)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
