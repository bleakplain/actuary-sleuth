# Implementation Plan: 038 变异注入违规评测集

**Date**: 2026-08-25
**Status**: Draft — 待评审
**Input**: `spec.md`（2026-08-21 定稿决策）、`research.md`（规则分层与 9 宿主方案）

## 1. Summary

从负面清单规则反向派生变异算子，对 9 份真实产品做受控编辑生成违规变体文档，经人工确认后冻结为带金标的评测集，接入现有审核管线产出逐规则漏检率报告：

```text
变异算子库（JSON 声明式）
→ 宿主 × 打包计划 → 变体条款包 / 变体文档（双轨）
→ 人工确认（60 条上限）→ 冻结（版本 + SHA-256 指纹）
→ run_audit_pipeline 执行 → 与金标比对
→ 逐规则漏检率（双口径）+ 误报率 + 漂移报告 → eval 快照
```

本计划不修改法规原文与审核主链语义，评测集构建与指标计算全部为新增旁路模块。

## 2. Technical Context

**Language**: Python 3.14（遵循现有代码风格：frozen dataclass、动词名词命名、模块内 data/ 放数据文件）
**复用模块**：
- `scripts/lib/doc_parser/`（parser.py → DocumentAnnotation/Clause，原文档级变体再解析）
- `scripts/lib/compliance/audit_pipeline.py:819 run_audit_pipeline`（评测执行入口；条款块级变异直接构造 `AuditPipelineRequest.clauses`，无需改管线）
- `scripts/lib/compliance/data/clause_topic_relations.json` 同款 data/ 目录约定
- KB 冻结指纹机制（`kb_build_identity.json` 的 SHA-256 做法）
- `lib/eval` 快照存储（`eval_snapshots` 表）

**新增模块**（全部在 `scripts/lib/` 下，不新建 service package）：
```
scripts/lib/benchmark_mutation/
├── __init__.py
├── operator_schema.py      # 变异算子数据模型与加载校验
├── operators.py            # 算子执行（四类变异原语）
├── host_planner.py         # 宿主加载、算子-宿主匹配、打包计划
├── variant_builder.py      # 变体条款包/变体文档构建（双轨）
├── golden_label.py         # 金标生成与冻结（指纹、版本）
├── confirmation.py         # 确认清单读写（生成/导入/冻结）
├── metrics.py              # 漏检率双口径、误报率、漂移计算
├── runner.py               # 评测执行编排（调用 run_audit_pipeline）
└── data/
    └── operators.v1.json   # ≥30 个变异算子声明
scripts/benchmark_build.py  # 入口脚本：构建变体与确认清单
scripts/benchmark_run.py    # 入口脚本：执行评测出报告
```

## 3. Constitution Check

- [x] **Library-First**：复用 doc_parser、audit_pipeline、KB 指纹、eval 存储表；不重写任何解析/审核逻辑
- [x] **测试优先**：每个模块先写单测（算子执行 diff、金标冻结、指标计算），评测 runner 用模型桩集成测试
- [x] **简单优先**：算子声明式 JSON 而非 DSL/规则引擎；确认清单 CSV/JSON 而非界面
- [x] **显式优于隐式**：算子→规则→法规依据显式关联；金标与指纹绑定；确认人/时间/结论三字段
- [x] **可追溯性**：Phase 划分对应 spec US1-US5
- [x] **独立可测试**：算子库、变体构建、确认、指标、runner 均可独立运行

## 4. 方案权衡

| 决策点 | 方案 | 取舍 |
|---|---|---|
| 算子表示 | 声明式 JSON（rule_ref + tier + payload） | 放弃代码内算子类层次——JSON 可版本化、可被确认工作流直接引用、论文附录可直接导出 |
| 变体构建 | 双轨：条款块级（主）+ 原文档级（验证批次） | 块级走 `AuditPipelineRequest.clauses` 直接注入；文档级仅 2-3 份验证 doc_parser 解析鲁棒性 |
| 指标归属 | 新增 `benchmark_mutation/metrics.py`，不改 `lib/eval/rating.py` | 现有 recall@k 是检索指标，语义不同；快照存储复用，计算独立 |
| 金标"其余规则维持原判定" | 不作为硬断言，漂移单列 | research.md 风险 3：变异可能合法引发连锁判定变化，硬断言会产生假失败 |

## 5. 数据模型（核心）

```python
@dataclass(frozen=True)
class MutationOperator:
    operator_id: str            # OP-001…
    rule_ref: str               # "01_负面清单检查/产品责任设计#原序号22"
    tier: MutationTier          # INSERTION / NUMERIC / DELETION / REWRITE
    host_tags: Tuple[str, ...]  # 算子要求的宿主标签（来自规则适用标签）
    target_topics: Tuple[str, ...]  # 定位条款块（clause_topics 注册表值）
    payload: Mapping[str, Any]  # tier 专属：插入文本 / 数值改写对 / 删除锚文本
    expected_decision: str      # "violated"
    description: str            # 人读说明（确认清单展示用）

@dataclass(frozen=True)
class VariantRecord:
    variant_id: str             # VAR-<host>-<n>
    host_product_id: str        # real-0xx
    operator_ids: Tuple[str, ...]   # 打包的算子（互斥分组）
    track: MutationTrack        # CLAUSE_BLOCK / SOURCE_DOCUMENT
    diff: Tuple[MutationDiff, ...]  # 每个变异：块定位 + 原文 + 变异后文本
    golden_labels: Tuple[GoldenLabel, ...]

@dataclass(frozen=True)
class GoldenLabel:
    rule_ref: str
    expected: str               # violated
    evidence_clause_ids: Tuple[str, ...]
    confirmed_by: str           # 确认人（空 = 未确认，不计入评测）
    confirmed_at: str
```

## 6. 实施阶段

### Phase 1：算子库（US1）— 纯离线
1. `operator_schema.py` + 加载校验（rule_ref 必须能在 KB 中解析到、host_tags 非空、payload 与 tier 匹配）
2. 手工编写 `data/operators.v1.json`：Tier A 15-18 个 + Tier B 4-6 个 + Tier C 6-8 个
3. 单测：schema 校验、非法算子拒绝

### Phase 2：宿主与变体构建（US2）
1. `host_planner.py`：9 宿主清单硬编码（产品路径 + 预期标签）；算子-宿主匹配 = 算子 host_tags ⊆ 宿主 ProductTags
2. 打包计划：按 target_topics 互斥分组，每变体文档 ≤8 算子；每宿主留 1 个单变异样本
3. `variant_builder.py`：
   - CLAUSE_BLOCK 轨：加载宿主解析结果 → 定位目标块（topic 匹配 + 锚文本）→ 应用变异 → 输出变体条款包
   - SOURCE_DOCUMENT 轨：对 docx 源文本做同样编辑 → 重新走 `doc_parser`
4. 定位失败处理：算子定位不到目标块时显式报错（不静默跳过）——这可能暴露主题路由覆盖不足，记录到 research 增补
5. 单测：四类变异原语的 diff 正确性、互斥分组、定位失败

### Phase 3：金标与确认工作流（US3）
1. `golden_label.py`：变体 → 金标草案（目标规则 violated + 证据块）；"其余规则维持原判定"不生成硬金标
2. `confirmation.py`：生成确认清单（CSV：变异条目 / 规则 / 原文→变异后 / 确认字段）；导入确认结果；未确认条目剔除
3. 冻结：评测集清单 SHA-256 + 算子文件 SHA-256 + 版本号，写入数据文件（对齐 `kb_build_identity.json` 格式）
4. 单测：冻结指纹稳定性、确认导入校验

### Phase 4：评测执行与指标（US4）
1. `runner.py`：遍历已确认变体 → `run_audit_pipeline`（块级轨）/ doc_parser + pipeline（文档级轨）→ 收集 decisions
2. `metrics.py`：
   - 漏检率（严格：satisfied|indeterminate|manual_review 计漏；宽松：仅 satisfied 计漏）
   - 误报率（非目标规则判 violated 的比例）
   - 漂移（非目标规则判定相对宿主基线的变化，单列不判错）
   - 按规则 ID / tier 分组
3. 报告输出：markdown + JSON 双格式，写入 eval snapshots 目录
4. 可复现性：LLM 参数冻结记录在报告头（模型、温度、KB 版本指纹）

### Phase 5：回归基线接入（US5）
1. `benchmark_run.py` 支持 `--baseline <snapshot_id>` 对比模式，输出增量报告
2. 集成测试：模型桩跑通全流程（不含真实 LLM）

## 7. 测试计划

- 单元：算子 schema、四类变异原语、互斥打包、金标冻结、指标计算（含双口径边界）
- 集成：模型桩下 runner 端到端；文档级轨 1 份宿主验证 doc_parser 兼容
- 真实验收：≥30 算子全部通过 schema 校验；9 宿主中 ≥8 份成功构建变体；确认 60 条内；评测跑完产出完整报告

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 算子定位不到目标块（主题覆盖 70.9% 缺口） | 显式报错清单 → 反哺主题注册表扩充（对齐 036 OPT-003） |
| 打包变异互相干扰 | target_topics 互斥分组 + 每宿主单变异对照样本 |
| LLM 判定不稳定影响指标 | 双次运行一致性检查纳入报告；温度等参数冻结 |
| 确认量超 60 | Phase 3 生成确认清单时按规则分组排序，优先 Tier A |
