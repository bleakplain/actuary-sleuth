# 对话流畅性轻量修复计划

日期：2026-10-13。状态：执行中；基线通过后在隔离工作区实施，完成验收前不重启现有服务。进度见 tasks.md。

采用 gen-plan 兼容模式；替代 10 月 10 日计划作为本轮最小交付范围。需求回溯沿用 [038 QA 规格](../038-professional-regulatory-qa/spec.md) 的 US1（库隔离）、US2（有据回答）、US3（多轮理解）、US4（评测）。输入为当前源码诊断、[低人工方案调研](../qa-conversation-repair-20261010/ima-like-low-manual-research.md) 及 [校验调研](../039-qa-verification-ontology/research.md)。

## 1. 本轮目标与不做事项

目标：减少空等，减少不必要的模型调用；用户用口语或连续追问也能得到有来源的回答，避免“等很久最后只收到校验失败”。

- 不扩建本体，不建立人工标注项目，不要求用户组织专家审核。
- 不重建混合检索、向量库或 agent 平台，不训练模型，不上传资料到 ima。
- 不以未经验证的“准确率 95%”承诺验收；30–50 个自动回放案例用于发现回归，不能证明总体准确率。
- QA 与合规库继续隔离；只改 QA 行为，不改变合规规则和共享本体关系的审核状态。
- 不全面关闭校验；明确错误仍拦截，语义未知不直接等同错误。

首版仍在终检后交付正文。先用真实进度反馈与关键路径提速改善体验，不把“正在思考”算作答案首字，也不把未校验的法律结论提前流出。

## 2. 诊断依据

| 问题 | 当前代码位置 | 影响 |
|---|---|---|
| 首字等待整个图结束 | `scripts/api/routers/ask.py:297,310` | 全流程结束后才每 4 字发送，前端只有等待状态 |
| 前置模型串行 | `scripts/lib/rag_engine/query_preprocessor.py:233`；`rag_engine.py:780`；`llm_reranker.py:104` | 改写、重排先于答案生成；改写被丢弃也已支付延迟 |
| 机械校验触发第二次生成 | `scripts/lib/rag_engine/attribution.py:779,1174`；`repair.py:408,453`；`graph.py:566` | 词法不一致可触发复核，再失败则全文拒答 |
| 多轮问题靠字符串拼接 | `scripts/lib/rag_engine/graph.py:209,227,350,460,501,676` | 路由、检索、生成、校验可能理解不一致 |
| 非关键后处理挡住首答 | `scripts/lib/rag_engine/graph.py:637,651,715` | 特定偏好问句触发画像更新模型调用，也要等完 |

2026-08-28 保存的一个 QA trace：改写 0.84 秒、混合检索 2.24 秒、LLM 重排 5.04 秒、生成 1.08 秒、复核 2.77 秒，总计约 12 秒。这里只是历史个案，不是当前性能基线或 P95。2026-10-13 只读健康检查显示工作区记录的实例 QA ready、库 v1；健康接口不能证明实际 QA 模型配置、运行代码版本或回答质量。

当前检索各支路已经并行，前置读取用户画像也并行且是数据库读，不能把它们误当新增提速项目。后置画像只在特定问句触发，不是每问都会发生。

关键现行代码独立摘录：

```python
# ask.py：整条图返回后才发正文
result = await asyncio.shield(graph_task)
answer = result.get("answer", "")
chunk_size = 4
for i in range(0, len(answer), chunk_size):
    chunk = answer[i : i + chunk_size]
    yield {
        "event": "message",
        "data": json.dumps({"type": "token", "data": chunk}, ensure_ascii=False),
    }

# query_preprocessor.py：短问题直接跳过改写
if len(query) <= _SIMPLE_QUERY_THRESHOLD:
    return None

# graph.py：最终仍有问题则整段替换
elif verification["status"] == "needs_review":
    answer_str = _NEEDS_REVIEW_ANSWER
```

## 3. 四阶段实施

### A. 即时反馈与关键路径拆分（约 0.5–1 开发人日）

对应 US3/US4。

1. 先记录当前实例、QA 模型/重排器、库/策略指纹，回放少量原始问题建立新基线；不使用历史 12 秒充当新基线。
2. 在现有 SSE 增加 `progress` 事件：已接收、检索资料、组织回答、必要时核对依据。事件来自真实阶段，不伪造进度百分比；前端增加 `onProgress` 和请求级状态。
3. 改造等待方式，使 API 等待图结果期间也能转发阶段事件；沿用工作线程，使用线程安全的事件桥接，不能把同步模型调用搬到事件循环阻塞所有连接。事件携带请求标识，取消/切换会话后丢弃旧事件。
4. `extract_memory`、`update_user_profile` 等非必要画像工作移到回答持久化后的后台路径；使用现有任务生命周期管理方式，异常只记录、不影响答案。去重并限制并发，不能无限派生任务。
5. **助手消息与会话上下文仍须先可靠保存，再释放同会话锁**。不可将关键会话状态一起后台化，避免用户立即追问读到旧历史。
6. 最终正文按完整结果或自然段发送，取消每 4 字反复更新造成的伪流式。首版不承诺边生成边显示；已核验结果优先于打字动画。

文件：`scripts/api/routers/ask.py`、`scripts/lib/rag_engine/graph.py`、`scripts/web/src/api/ask.ts`、`stores/askStore.ts`、`components/MessageBubble.tsx`；既有 API/前端测试。

验收：本地健康连接首次阶段反馈 P95 ≤1 秒；无未核验正文泄露；断连/重试/切会话/连续追问不会串事件或丢上下文。分别报告首次反馈、首段可用答案、完整完成时间。

### B. 减少前置模型调用，并接好上下文（约 1–1.5 开发人日）

对应 US3，保留 US1 隔离边界。

1. 清晰问题保留确定性快路径，不再对所有较长问题默认调用改写模型；也不把短句默认当作清晰。是否需解析先用已有结构信号判断，不新增一轮模型“判断要不要调用模型”。
2. 对未链接口语实体、指代、多轮替换做一次结构化解释，存入 frozen 问题对象；在意图路由前产生，法规元数据查询和时间解析也消费该对象。
3. 路由、检索、生成、验证、修订复用同一解释；原查询保留，显式日期、地区、数字、否定、条件不丢。模型候选不是正式本体关系，不写回共享数据。
4. “重疾等待期多久”不得强改为“监管上限”；可以明确从法规角度作答，并区分具体合同约定。“那医疗呢”“我问的是以前规定”按槽位替换，不沿用过时条件。
5. 对同一批候选比较：现有 LLM 重排、现有 BGE 重排、RRF 排序直接截取。首选实测达到质量底线的低延迟路径，LLM 重排只在已定义的复杂场景使用，而非默认每问调用。
6. BGE 不能凭名称直接切换：确认本地权重可用，候选数上限对齐，测冷/热启动、长条款截断；现有 LLM 排名与 BGE 分数不同，不能原样套用 `min_score`。不可为了提速把关键证据过滤掉。
7. 增补总 deadline；并行检索已有，不重复建设。对慢支路使用受控截止并清理任务，不留下无限运行的线程。已知单路故障保留可用结果，不回退合规库。

文件：`scripts/lib/common/models.py`、`scripts/lib/rag_engine/query_preprocessor.py`、`graph.py`、`rag_engine.py`、`retrieval.py`、现有 reranker；必要时新增现有 `scripts/lib/llm/` 包内 `qa_interpretation.py`。

验收：清晰精确问题不触发模型改写；原始失败口语和多轮换产品/主题/时点回放通过；按需策略确实减少模型次数。QA 与合规策略分开，不能改全局共享重排配置影响审核。

### C. 消除机械误拒答，保留证据约束（约 1.5–2 开发人日）

对应 US2/US3。

1. 调整生成提示：允许有依据的释义、归纳和有限推理，不再笼统禁止一切推断；不得补造法规数字、适用范围和效力状态。
2. 本地引用、数值、日期、极性及可明确解析的范围/条件检查保留。低词覆盖、非原文子串属于待确认，不再直接触发整段拒答。
3. 确定性证据/既有受控关系足够时直接交付；只有语义未知主张才批量调用一次证据判断，要求返回“支持/冲突/不足”及真实证据 ID、定位片段，不能只接受“模型说没问题”。
4. 缺证据时在同一 QA 版本补检索最多一次；有证据但草稿错误时修订最多一次。修订与必要终检预算预留；模型不能覆盖硬冲突，也不能因耗尽预算直接发新草稿。
5. 初稿最多一次、修订最多一次、语义检查最多两次（初检/终检），共享一个总时限；不逐主张循环请求。理解、重排、嵌入、生成与复核都记成本，不把开销转移到新环节后声称提速。
6. graph 与直接 ask 共用结果策略；能独立成立的内容保留，不把多个产品的数值或删掉例外的半句拼成“部分答案”。确实缺材料时具体说明缺口或只问一个关键问题。
7. UI 区分完整、部分、澄清、不可用；普通回答不展示内部错误码。引用按最终证据 ID 绑定，补检索后不能沿用旧序号。
8. 本体不扩建、不批量改审核标签；共享关系只辅助 QA。资料效力未知时显示“依据所提供资料”，不声称现行有效已核实；合规结论仍走原审核链路。

文件：`scripts/lib/rag_engine/rag_engine.py`（提示与直接路径）、`graph.py`、`attribution.py`、`repair.py`；模型调用复用 `lib/llm`，必要时新增 `qa_evidence.py`；API schema、前端 types/store/展示同步。持久化沿用 `lib/common/database.py` 及现有 API 接口。

验收：正式词与口语变体不再仅因词面差异被拒；错误引用/数字/极性/主体等关键回归保持拦截。只有待确认主张进入模型判断；不能将软失败一律忽略或给无来源内容加“已验证”。

### D. 自动回放、同机对照与试用发布（约 0.5–1 开发人日）

对应 US1–US4。

1. 从现有真实失败问句、已有 fixture 自动整理 30–50 个回放问题/会话；派生口语、指代、主题/地区/日期替换、无资料和反例。保留来源标签，合成问题不冒充真实日志。
2. 既有精确证据断言检查关键事实和引用；问题变体检查同义一致性、约束保留、多轮状态；模型评分只筛查分歧，不能自证准确。
3. 至少真实 HTTP/SSE 路径测普通、修订、多轮、缓存命中/失效；Mock graph 单测不能替代真实链路。模型和索引固定，分冷/热缓存，代表性场景至少重复三轮。
4. 可回答性未知的自动变体单独列出，不强行当正确金标。无答案/超时/拒答必须保留在报告，不能只统计成功回答。
5. 新旧版并排检查：首反馈、正文可用时间、P50/P95、分阶段耗时、模型次数、误拒答案例、明显错放行、检索关键证据是否丢失。
6. 正文完成时间目标：同条件普通问题 P50/P95 较当前基线下降至少 30%；不以更短拒答、缓存预热差异或缺失问题来达标。达不到时报告瓶颈，不能仅凭转圈更快宣称提速。
7. 硬错误/跨库/来源错位在固定回归中为 0；原始失败问题和已确认同义变体必须通过。该结论仅适用于这组回归，不宣称总体准确率 95%。
8. 完整单测、类型/前端构建通过后，发布候选实例并明确测试入口、QA 版本和策略指纹；核对前端代理、SSE、保存历史一致。保留原构建与配置用于回滚，不按端口盲目停止其他实例。

用户无需提供专家金标；正常试用反馈即可，可选 10–20 分钟体验抽查，不作为必须投入。开发自行承担自动化回归和证据核对。无人专业审定意味着不能将首版宣传成法律适用准确率认证。

## 4. 方案权衡与风险

| 问题 | 方案 A | 选定方案 B | 方案 C |
|---|---|---|---|
| 首反馈慢 | 立即流出未核验正文：风险高 | 真实阶段反馈 + 缩短关键路径，核验后显示正文 | 逐段生成逐段核验：后续按需要做，首期不扩复杂度 |
| 串行模型多 | 全关改写/重排：可能丢召回 | 结构快路径 + 按需语义解释，重排同机比较后选择 | 新模型/框架迁移：首期不做 |
| 误拒答多 | 完全关校验：错误直接泄漏 | 硬冲突保留、未知语义按需判断、一次纠错 | 每问双模型强校验：延迟和费用增加 |
| 验收成本高 | 无回归直接试用：退化难定位 | 复用现有例子和日志自动回放 | 200 题专家金标/本体审核：后置，不要求用户投入 |

| 风险 | 概率/影响（规划估计） | 缓解 |
|---|---|---|
| BGE 或截候选后反而更慢/漏依据 | 中/高 | 同候选预算、冷/热启动与阈值校准；未过对照不切 |
| 新语义调用抵消重排节省 | 中/中 | 总时限与调用账本，快路径零额外判断，不逐条循环 |
| 软失败直接放行导致错误 | 中/高 | 仍须证据支持；明确冲突不可覆盖，未知不标已验证 |
| 后台画像影响下一轮会话 | 中/高 | 关键历史先持久化、同会话锁、后台幂等/隔离 |
| 阶段提示假装性能改善 | 高/中 | 首反馈与正文延迟分开报告，只以可用正文衡量提速 |
| 改写或继承丢失条件 | 中/高 | 原句保留、约束来源记录、地区/否定/时点反例 |
| 多实例测错或发错版本 | 中/高 | 明确入口、构建指纹、QA 快照、历史与 SSE 核对 |

## 5. 核心策略草案（可独立运行）

以下为“明确冲突不能被软判断覆盖”的最小决策契约，不包含生产 LLM/检索实现。完整代码及测试可复制运行；生产集成按阶段 C 修改既有模块。结构对象用 frozen dataclass，公共函数带类型注解；落地时类型/常量分别归既有 common 模块。

```python
from dataclasses import dataclass
from typing import Literal
import unittest

Action = Literal["deliver", "check_evidence", "repair_once", "limited_answer"]

@dataclass(frozen=True)
class EvidenceCheck:
    supported: bool = False
    answers_question: bool = False
    hard_conflict: bool = False
    semantic_unknown: bool = False
    evidence_available: bool = False
    checked_semantics: bool = False
    repair_used: bool = False
    budget_available: bool = True

def choose_action(result: EvidenceCheck) -> Action:
    """先保护明确冲突，再把有限模型预算用于未知；不能无证据直通。"""
    if (result.supported and result.answers_question and result.evidence_available
            and not result.hard_conflict and not result.semantic_unknown):
        return "deliver"
    if result.repair_used or not result.budget_available:
        return "limited_answer"
    if result.hard_conflict:
        return "repair_once" if result.evidence_available else "limited_answer"
    if (result.semantic_unknown and result.evidence_available
            and not result.checked_semantics):
        return "check_evidence"
    return "limited_answer"

class PolicyTests(unittest.TestCase):
    def test_supported_answer(self) -> None:
        result = EvidenceCheck(supported=True, answers_question=True,
                               evidence_available=True)
        self.assertEqual(choose_action(result), "deliver")

    def test_soft_gap_is_not_refusal(self) -> None:
        result = EvidenceCheck(semantic_unknown=True, evidence_available=True)
        self.assertEqual(choose_action(result), "check_evidence")

    def test_model_support_does_not_override_conflict(self) -> None:
        result = EvidenceCheck(supported=True, answers_question=True,
                               hard_conflict=True, evidence_available=True)
        self.assertEqual(choose_action(result), "repair_once")

    def test_no_unbounded_repair(self) -> None:
        result = EvidenceCheck(hard_conflict=True, evidence_available=True,
                               repair_used=True)
        self.assertEqual(choose_action(result), "limited_answer")

    def test_no_evidence_is_not_supported(self) -> None:
        result = EvidenceCheck(supported=True, answers_question=True)
        self.assertEqual(choose_action(result), "limited_answer")

    def test_no_repeated_semantic_call(self) -> None:
        result = EvidenceCheck(semantic_unknown=True, evidence_available=True,
                               checked_semantics=True)
        self.assertEqual(choose_action(result), "limited_answer")

if __name__ == "__main__":
    unittest.main()
```

调用契约：初检与修后终检先运行，再消费本函数结果。`limited_answer` 不是原草稿放行，外层最多一次补检索可改变证据；仍不足时仅展示可独立成立且已经核验的部分或具体缺口。终检与补证共用整请求预算。这里的纯函数测试不证明语义模型准确或完整链路达标。

## 6. 测试落点与执行

复用并扩展：

- `scripts/tests/lib/rag_engine/test_query_preprocessor.py`、`test_graph_multi_turn.py`、`test_attribution.py`、`test_repair.py`、`test_qa_engine.py`。
- `scripts/tests/lib/rag_engine/test_retrieval_correctness.py`、`test_llm_reranker.py`、`test_bge_reranker.py`、`test_kb_purpose_isolation.py`。
- `scripts/tests/api/test_ask.py`、`test_rag_runtime_readiness.py`，覆盖进度事件/取消/错误/历史/版本；新增必要的真实会话回放用例放同一测试包，模型和索引的集成依赖显式标记。
- `scripts/web/src/api/ask.test.ts`、`stores/askStore.test.ts`，覆盖新事件、旧事件兼容、完成和取消后的状态清理。
- `scripts/lib/eval/evaluator.py` / `scripts/evaluate_rag.py` 复用现有评估入口，补会话回放，不另建评估平台；输出全样本 outcome。

实施后执行；当前尚未运行整个应用测试：

```bash
pytest scripts/tests/lib/rag_engine/ scripts/tests/api/test_ask.py
pytest scripts/tests/
mypy scripts/lib/
npm --prefix scripts/web test
npm --prefix scripts/web run build
```

仓库已有失败先记录，不掩盖新增失败；提交前按 AGENTS.md 跑测试和检查 diff。真实回放不得用返回固定答案的 Mock graph 代替。

## 7. 交付节奏与治理

- A → B → C → D。A/B 的低风险改动先形成可测候选，C 完成后才报告误拒答得到修复。
- 粗估 **4–6 个开发人日**，视现有模型响应和本地重排可用性校准；首个阶段反馈/耗时改进候选目标约 **1–2 开发日**。这是缩小范围后的估算，不是法律准确性项目的压缩承诺。
- **用户侧没有专家审核或成批标注的前置任务**；如自动回放发现证据本身矛盾，报告具体资料缺口，不把问题变成要求用户先建完整本体。
- Constitution Check：复用已有库与模块；失败回归优先；不新建 service 包；问题解释、预算、事件与版本显式；阶段回溯 US；各组件可独立测试。
- 本次不改 `.env`，不自动下载新模型或改模型供应商。实施如需配置/权重变更，列明影响再确认；不碰无关合规改动。不可只改全局配置令合规链路变更。

完成标准：真实网页有及时而真实的反馈；同条件可用正文确实更快；原始失败及确认同义问题能回答；关键错误仍能拦住；多轮、历史、引用及 QA 版本一致。未达到条件就报告剩余卡点，不能因“加了进度提示”宣布整体修复完成。
