# 执行基线与源码依据

日期：2026-10-13。此文件记录本轮代码核查，不新增行业结论。

## 当前链路

- `api/routers/ask.py` 在 `await asyncio.shield(graph_task)` 完成后才发送正文，每四字一个 token 事件；助手消息在正文发送后保存。
- `lib/rag_engine/graph.py` 在生成后串行执行记忆提取、画像更新、会话上下文保存；路由使用原问题，检索使用拼接追问，校验再构造问题，理解未统一。
- `query_preprocessor.py` 以八字阈值决定改写，主题分词严格相等的保护又会丢弃语义改写。
- `attribution.py` 的词面覆盖与子串匹配产生待复核结果；`repair.py` 已有一次修订，但缺少通用的三分类证据判断与补检索。
- QA/合规已有用途隔离、QA 发布清单和请求级版本租约，本轮必须保留。

## 基线与隔离约束

主仓库 HEAD 为 `08944eb`，与 `origin/master` 一致。开始时有 276 项未提交状态，含 QA、合规和前端。不得提交、覆盖或清理这些既有工作；隔离开发必须带入现有代码快照，并另存本轮修改前的快照以便比较。

QA 定向基线：`pytest scripts/tests/lib/rag_engine/ scripts/tests/api/test_ask.py -q --no-cov`：489 passed、22 skipped。跳过项不计为真实模型验收。

全量测试在沙箱内遇到 LibreOffice `.doc` 转换超时；同一适用性测试组在沙箱外 10 passed。沙箱外完整基线：3413 passed、38 skipped、2 deselected，覆盖率 82.93%，228.17 秒。系统 Python 缺少开发类型存根，使用临时隔离环境补齐仓库声明的开发依赖后，按 `scripts/mypy.ini` 检查 141 个源码文件全部通过，不修改系统环境或项目 `.env`。

历史 trace 只用于定位可疑环节，不用作此次提速对照。实施前后的真实 HTTP/SSE 回放必须固定模型、语料快照、问题和缓存条件，记录全部超时与拒答。

## 既有调研的使用边界

本轮沿用 `qa-conversation-repair-20261010/ima-like-low-manual-research.md` 与 `039-qa-verification-ontology/research.md` 的方向：自然问法、有据作答、可追溯引用、有限纠错。ima 未公开内部实现或可比较的法规准确率；本轮不宣称复刻其内部架构或达到 95% 准确率。

具体实施、预算、验收和不做事项以同目录 plan.md 为准。不要求先扩建本体或投入大规模人工标注。
