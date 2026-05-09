# 合规审查模块代码审查报告

**审查日期**: 2026-04-29
**审查范围**: 合规核心链路 (checker.py, prompts.py, compliance.py 路由)
**审查类型**: 系统、深入 review

---

## 一、整体架构评价

### 1.1 架构优点

**✅ 清晰的分层设计**
- `ComplianceChecker` 类封装了核心检查逻辑
- 依赖注入模式：`llm` 和 `config` 可注入，便于测试
- 法规检索 (`regulation_registry`) 与业务逻辑分离

**✅ 分块检查策略**
- `check_document` 按章节分块检查，避免单次 LLM 调用过长
- 支持多种章节类型：条款、责任免除、投保须知、健康告知、附加险、数据表格

**✅ 负面清单批量检查**
- 已从逐条调用改为单次批量调用，显著降低成本

### 1.2 架构问题

**⚠️ 两种检查模式并存**
- `check_document`: 分块检查模式（推荐）
- `run_compliance_check` + `build_enhanced_context`: 批量检查模式（遗留）
- 两者职责重叠，增加维护成本

**⚠️ 法规上下文缓存设计**
- `_regulations_cache` 和 `_regulations_context` 在实例级别缓存
- 如果同一 `ComplianceChecker` 实例检查不同险种，会返回错误缓存

---

## 二、核心功能审查

### 2.1 特定险种合规检查

**实现路径**: `check_document` → `_load_all_regulations` → `get_category_regulations`

**优点**:
- `CATEGORY_REGULATION_REGISTRY` 集中管理险种-法规映射
- 险种专属法规 + 通用法规两层加载

**问题**:

| 问题 | 严重程度 | 位置 | 说明 |
|------|---------|------|------|
| 枚举值不一致 | **P0** | `product_types.py:19-29` | `ProductCategory.value` 返回简称（如"寿险"），与 `VALID_CATEGORIES` 一致，但需验证所有调用方 |
| 法规名称匹配失败 | **P0** | `checker.py:206-209` | `get_category_regulations(category)` 返回法规名称列表，`search_by_metadata({"law_name": reg_name})` 要求知识库中 `law_name` 精确匹配 |

**验证建议**:
```python
# 测试险种识别 → 法规检索链路
def test_health_insurance_regulation_retrieval():
    checker = ComplianceChecker()
    result = checker.identify_category("", "健康无忧保险")
    assert result.category == "健康险"  # 枚举值必须匹配 registry key
    regs = get_category_regulations(result.category)
    assert len(regs) > 0  # 必须能找到对应的法规
```

### 2.2 通用法规合规检查

**实现路径**: `_load_all_regulations` → `get_general_regulations` → `search_by_metadata`

**优点**:
- `GENERAL_REGULATIONS` 定义明确：保险法、人身保险条款管理办法、精算规定等
- 强制全量加载，不依赖险种

**问题**:

| 问题 | 严重程度 | 说明 |
|------|---------|------|
| RAG 引擎未初始化静默失败 | **P1** | `get_engine()` 返回 `None` 时只记录 warning，返回空列表 |
| 无降级提示 | **P1** | 调用方无法区分"无法规"和"引擎不可用" |

**改进建议**:
```python
@dataclass
class RegulationLoadResult:
    regulations: List[Dict]
    sources_info: Dict[str, List[str]]
    engine_available: bool  # 显式传递降级状态
```

### 2.3 负面清单检查

**实现路径**: `check_negative_list` → `search_by_metadata({"category": "负面清单检查"})`

**优点**:
- 批量检查（一次 LLM 调用检查所有规则）
- 返回 `(items, result)` 元组，显式传递检查状态

**问题**:

| 问题 | 严重程度 | 位置 | 说明 |
|------|---------|------|------|
| LLM 错误抛异常 | **P1** | `checker.py:525` | 测试期望返回 `SKIPPED`，实现是 `raise`，设计与实现不一致 |
| Token 截断日志 | **P2** | `checker.py:494` | 文档截断只记录 warning，无指标追踪 |
| `source_excerpt` 取值 | **P2** | `checker.py:113` | 取 `negative_rule[:300]`，是法规原文，非文档违规原文 |

**修复建议**:
```python
# checker.py:524-526 改为
except Exception as e:
    logger.error(f"Negative list check failed: {e}")
    return [], CheckResult.SKIPPED  # 不抛异常，返回 SKIPPED
```

---

## 三、数据流审查

### 3.1 正向流程

```
用户上传文档
    ↓
parse_product_document (doc_parser)
    ↓
AuditDocument (结构化)
    ↓
ComplianceChecker.check_document
    ├── identify_category (险种识别)
    ├── _load_all_regulations (法规加载)
    ├── _extract_sections (章节提取)
    ├── _check_section (逐章节检查)
    └── _merge_results (结果合并)
    ↓
check_negative_list (负面清单检查)
    ↓
聚合结果 + 存储
```

### 3.2 关键转换点

| 转换点 | 输入 | 输出 | 风险 |
|--------|------|------|------|
| 文档 → AuditDocument | 文件路径 | 结构化对象 | 解析失败返回 None |
| 险种识别 | 产品名称 + 文档 | CategoryResult | 关键词匹配失败走 LLM |
| 法规检索 | 险种名称 | 法规列表 | RAG 引擎不可用返回空 |
| LLM 检查 | 章节 + 法规 | JSON 结果 | 解析失败返回空 items |

---

## 四、测试覆盖审查

### 4.1 测试状态

| 测试文件 | 状态 | 覆盖内容 |
|---------|------|---------|
| `test_checker.py` | ✅ 通过 | 险种识别、法规加载 |
| `test_negative_list.py` | ⚠️ 1 失败 | LLM 错误处理不一致 |
| `test_clause_level.py` | ✅ 通过 | JSON 解析 fallback |
| `test_chunked_checker.py` | ✅ 新增 | 分块检查、token 估算 |
| `test_e2e_compliance.py` | ⏭️ 跳过 | 需要 API 服务运行 |

### 4.2 覆盖缺口

| 函数 | 测试覆盖 | 缺失场景 |
|------|---------|---------|
| `check_document` | 部分 | 多章节、错误恢复、缓存 |
| `_merge_results` | 无 | 错误聚合、空结果 |
| `_build_section_prompt` | 无 | 法规上下文截断 |

---

## 五、代码质量审查

### 5.1 优点

- **类型注解完整**: 公开 API 都有类型注解
- **日志记录充分**: 关键步骤有 info/warning/error 日志
- **错误处理**: LLM 调用有 try-except，JSON 解析有多层 fallback

### 5.2 问题

**1. 魔法数字**

```python
# checker.py:56-57
max_context_tokens: int = 80000
max_output_tokens: int = 8192
chars_per_token: float = 1.5
```

建议移至 `constants.py` 统一管理。

**2. 重复的 JSON 解析逻辑**

- `_parse_section_response` 和 `run_compliance_check` 有重复的 JSON 解析代码
- 建议抽取为 `_parse_llm_json_response(answer: str) -> Dict` 工具函数

**3. 条款编号字段不一致**

- `_build_section_prompt` 要求 `clause_number` 字段
- `check_negative_list` 生成的 item 中 `clause_number` 为空字符串
- 建议明确 `clause_number` 是否可选

---

## 六、关键发现与建议

### P0 - 必须修复

1. **LLM 错误处理不一致** (`checker.py:525`)
   - 测试期望返回 `SKIPPED`，实现抛异常
   - 修复：捕获异常后返回 `([], CheckResult.SKIPPED)`

### P1 - 应该修复

2. **法规检索无降级提示**
   - 当 RAG 引擎不可用时，调用方无法区分"无法规"和"引擎不可用"
   - 建议：`_load_all_regulations` 返回结构化结果，包含 `engine_available` 标志

3. **重复的 JSON 解析代码**
   - 两处相同逻辑，增加维护成本
   - 建议：抽取为通用工具函数

### P2 - 可以改进

4. **魔法数字移至常量**
   - token 预算相关数字分散在代码中
   - 建议：统一至 `ComplianceConstants`

5. **缓存策略改进**
   - 当前实例级缓存可能导致错误复用
   - 建议：每次 `check_document` 调用清空缓存，或使用方法级局部变量

---

## 七、审查结论

### 整体评价

合规模块架构清晰，核心功能实现完整，分块检查策略合理。主要问题集中在：

1. **测试-实现不一致**: LLM 错误处理
2. **降级状态传递不足**: RAG 引擎不可用时静默失败
3. **代码复用**: JSON 解析逻辑重复

### 建议优先级

1. **立即修复**: P0 测试失败
2. **本迭代修复**: P1 降级状态传递
3. **后续迭代**: P2 代码质量改进
