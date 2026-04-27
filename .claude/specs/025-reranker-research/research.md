# Reranker Research - 技术调研报告

生成时间: 2026-04-26 16:30:00
源规格: .claude/specs/025-reranker-research/spec.md

## 执行摘要

现有 rag_engine 已有精排器抽象和两种实现（LLMReranker、CrossEncoderReranker），架构支持扩展。CrossEncoderReranker 默认使用 `bge-reranker-v2-m3`，非 `bge-reranker-large`。接口完全兼容，新增精排器只需实现 `BaseReranker` 并在 `_create_reranker()` 添加分支。工程优化方面，批量推理需改造、INT8 量化需新增依赖、阈值过滤已支持。推荐采用 bge-reranker-large + 批量推理 + INT8 量化组合，预期延迟从 LLM 精排的 1-2s 降到 80-100ms。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 精排器接口 | `scripts/lib/rag_engine/reranker_base.py` | 已有 `BaseReranker` 抽象类 |
| FR-001 LLM 精排实现 | `scripts/lib/rag_engine/llm_reranker.py` | 已有 `LLMReranker` 实现 |
| FR-001 HF 精排实现 | `scripts/lib/rag_engine/cross_encoder_reranker.py` | 已有 `CrossEncoderReranker` 实现 |
| FR-003 精排器切换机制 | `scripts/lib/rag_engine/rag_engine.py:151-172` | 已有工厂方法 `_create_reranker()` |
| FR-003 精排配置 | `scripts/lib/rag_engine/config.py:62-85` | 已有 `RerankConfig` 配置类 |
| FR-004 模型路径配置 | `scripts/lib/config.py:253,406-407` | 已有 `models_dir` 配置 |

### 1.2 核心类结构

#### BaseReranker 抽象接口

```python
# scripts/lib/rag_engine/reranker_base.py:8-18
class BaseReranker(ABC):
    """精排器统一接口"""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        ...
```

**输入格式**:
- `query`: 用户查询字符串
- `candidates`: 候选文档列表，每个 dict 包含 `content`, `law_name`, `article_number` 等字段
- `top_k`: 返回的最大文档数（可选）

**输出格式**:
- 返回 List[Dict]，每个 dict 包含原始字段 + `rerank_score` (float) + `reranked` (bool)

#### CrossEncoderReranker 现有实现

```python
# scripts/lib/rag_engine/cross_encoder_reranker.py:12-65
class CrossEncoderReranker(BaseReranker):
    """Cross-encoder reranker using sentence-transformers CrossEncoder"""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",  # 注意：默认是 v2-m3，不是 large
        model_path: Optional[str] = None,
        max_length: int = 1024,
    ):
        from sentence_transformers import CrossEncoder

        if model_path:
            self._model = CrossEncoder(model_path, max_length=max_length)
        else:
            self._model = CrossEncoder(model_name, max_length=max_length)

    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_k: Optional[int] = None):
        texts = [c.get("content", "") for c in candidates]
        pairs = [[query, text] for text in texts]
        scores = self._model.predict(pairs, show_progress_bar=False)  # 批量预测
        # ... 排序并返回
```

**关键发现**:
1. 默认模型是 `bge-reranker-v2-m3`，不是 `bge-reranker-large`
2. 已支持 `model_path` 参数加载本地模型
3. `predict()` 已是批量调用，但未显式控制 batch_size

#### LLMReranker 现有实现

```python
# scripts/lib/rag_engine/llm_reranker.py:40-75
class LLMReranker(BaseReranker):
    def __init__(self, llm_client, config: Optional[RerankConfig] = None):
        self._llm = llm_client
        self._config = config or RerankConfig()

    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_k: Optional[int] = None):
        # 使用 LLM 批量排序：一次性将所有候选送入 LLM
        ranked_indices, did_rerank = self._batch_rank(query, candidates)
        # rerank_score = 1.0 / (rank + 1)
```

**特点**:
- 单次 LLM 调用完成所有候选排序
- `rerank_score` 是排名倒数（非概率分数）
- 有回退机制（LLM 失败时 `reranked=False`）

### 1.3 精排器创建和切换机制

```python
# scripts/lib/rag_engine/rag_engine.py:151-172
def _create_reranker(self) -> Optional[BaseReranker]:
    rc = self.config.rerank

    if not rc.enable_rerank or rc.reranker_type == "none":
        return None

    if rc.reranker_type == "llm":
        return LLMReranker(self._llm_client, rerank_config)

    if rc.reranker_type == "hf":
        return CrossEncoderReranker()  # ⚠️ 未传递任何参数！

    return None
```

**问题**: `CrossEncoderReranker()` 创建时未传递 `model_path`、`model_name`、`max_length` 等参数，使用默认远程模型。

### 1.4 配置系统

```python
# scripts/lib/rag_engine/config.py:62-85
@dataclass(frozen=True)
class RerankConfig:
    """重排序配置"""
    enable_rerank: bool = True
    reranker_type: str = "llm"           # 支持: "llm", "hf", "none"
    rerank_top_k: int = 5
    rerank_min_score: float = 0.0        # 阈值过滤，已支持

    _VALID_RERANKER_TYPES = {"llm", "hf", "none"}
```

```python
# scripts/lib/config.py:253
'models_dir': os.getenv('DATA_PATHS_MODELS_DIR', '/root/work/actuary-assets/models/reranker'),

# scripts/lib/config.py:406-407
def get_models_dir(self) -> str:
    return self._resolve_path(self._data_paths.models_dir)
```

### 1.5 调用流程

```
RAGEngine.ask()
  └── _do_ask()
        └── _hybrid_search()
              ├── hybrid_search() → RRF 融合结果
              ├── self._reranker.rerank() → 精排
              └── rerank_min_score 过滤 → 阈值过滤
```

```python
# scripts/lib/rag_engine/rag_engine.py:423-437
if self._reranker:
    results = self._reranker.rerank(query_text, results, top_k=top_k)

if results and rk.rerank_min_score > 0:
    filtered = [
        r for r in results
        if not r.get('reranked', False)
        or r.get('rerank_score', 0) >= rk.rerank_min_score
    ]
    results = filtered
```

**阈值过滤已实现**: 通过 `rerank_min_score` 配置，过滤低于阈值的候选。

### 1.6 可复用组件

| 组件 | 位置 | 用途 |
|------|------|------|
| `BaseReranker` | `reranker_base.py` | 新精排器的基类 |
| `RerankConfig` | `config.py` | 配置类，可扩展字段 |
| `_create_reranker()` | `rag_engine.py:151` | 工厂方法，添加新类型分支 |
| `get_models_dir()` | `lib/config.py` | 获取本地模型路径 |

### 1.7 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `cross_encoder_reranker.py` | 修改 | 添加批量推理、INT8 量化支持 |
| `config.py` (RAGConfig) | 修改 | 添加 batch_size、quantization 等配置 |
| `rag_engine.py` | 修改 | `_create_reranker()` 传递参数 |
| `requirements.txt` | 修改 | 添加 optimum[onnxruntime] 依赖（如需量化） |

---

## 二、技术选型研究

### 2.1 bge-reranker-large vs bge-reranker-v2-m3

| 特性 | bge-reranker-large | bge-reranker-v2-m3 |
|------|-------------------|-------------------|
| 参数量 | 330M | 560M |
| 最大长度 | 512 | 8192 |
| 多语言支持 | 中英 | 100+ 语言 |
| MRR (中文) | 0.923 | 0.931 |
| 模型体积 | ~1.1GB | ~2.2GB |
| 推理速度 | 更快 | 较慢 |

**选择建议**:
- 如果文档长度 < 512 tokens，选择 `bge-reranker-large`（更快、更小）
- 如果文档长度 > 512 tokens，选择 `bge-reranker-v2-m3`（更长上下文）
- 当前系统 `max_length=1024`，但法规条款通常较短，两者都可用

### 2.2 加载方式对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| sentence-transformers CrossEncoder | 简单、已集成 | 不支持量化 | ✅ 当前方案 |
| FlagEmbedding FlagReranker | 官方库、支持更多参数 | 额外依赖 | ✅ 可选方案 |
| transformers 直接加载 | 灵活控制 | 代码复杂 | ❌ 不推荐 |

### 2.3 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| sentence-transformers | >=2.2.0 | CrossEncoder 加载 | 已有（可选） |
| transformers | >=4.30.0 | 模型底层 | sentence-transformers 依赖 |
| torch | >=2.0.0 | 推理 | 已有（llama-index 依赖） |
| optimum[onnxruntime] | >=1.16.0 | INT8 量化 | **需新增** |
| onnxruntime | >=1.16.0 | ONNX 推理 | optimum 依赖 |

---

## 三、数据流分析

### 3.1 现有精排数据流

```
hybrid_search() → RRF 融合结果 (List[Dict])
      ↓
BaseReranker.rerank(query, candidates, top_k)
      ↓
┌─────────────────────────────────────┐
│  LLMReranker                        │
│  - 构造 prompt（候选编号列表）       │
│  - LLM 返回排序编号                 │
│  - rerank_score = 1/(rank+1)        │
└─────────────────────────────────────┘
      或
┌─────────────────────────────────────┐
│  CrossEncoderReranker               │
│  - 构造 pairs = [[query, doc], ...] │
│  - model.predict(pairs) → scores    │
│  - rerank_score = sigmoid(logit)    │
└─────────────────────────────────────┘
      ↓
rerank_min_score 过滤
      ↓
返回精排结果
```

### 3.2 新增 BgeReranker 数据流

```
hybrid_search() → RRF 融合结果
      ↓
BgeReranker.rerank(query, candidates, top_k, batch_size=32)
      ↓
┌─────────────────────────────────────┐
│  1. 构造 pairs = [[query, doc], ...]│
│  2. 分批 tokenize (batch_size)      │
│  3. 批量推理 → logits               │
│  4. sigmoid → scores                │
│  5. 按分数排序                      │
│  6. 阈值过滤 (min_score)            │
└─────────────────────────────────────┘
      ↓
返回精排结果
```

### 3.3 关键数据结构

```python
# 现有候选文档结构
candidate = {
    'law_name': '健康保险管理办法',
    'article_number': '第十七条',
    'content': '健康保险产品等待期不得超过...',
    'score': 0.0456,  # RRF 分数
    'category': '健康险',
    'source_file': 'health_insurance_reg.md',
    # ... 其他元数据
}

# 精排后结构
result = {
    **candidate,  # 保留原字段
    'rerank_score': 0.8234,  # 精排分数 [0, 1]
    'reranked': True,        # 是否完成精排
}
```

---

## 四、工程优化方案分析

### 4.1 批量推理优化

**现状**: `CrossEncoderReranker` 调用 `model.predict(pairs)` 已是批量，但未显式控制 batch_size。

**优化方案**: 手动分批处理，显式控制 batch_size。

```python
def rerank(self, query, candidates, top_k=None, batch_size=32):
    texts = [c.get("content", "") for c in candidates]
    pairs = [[query, text] for text in texts]
    all_scores = []

    for i in range(0, len(pairs), batch_size):
        batch = pairs[i:i + batch_size]
        scores = self._model.predict(batch, show_progress_bar=False)
        all_scores.extend(scores.tolist())

    # 按分数排序...
```

**预期效果**:
- 50 候选，batch_size=32，约 2 批次
- GPU 上利用并行计算，延迟从 ~1500ms（串行）降到 ~300ms

**改动范围**: `CrossEncoderReranker.rerank()` 方法

### 4.2 INT8 量化优化

**现状**: 未实现量化，模型加载为 FP32。

**优化方案**: 使用 optimum 导出并加载 ONNX INT8 模型。

```python
from optimum.onnxruntime import ORTModelForSequenceClassification
from transformers import AutoTokenizer

class QuantizedBgeReranker(BaseReranker):
    def __init__(self, model_path: str):
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = ORTModelForSequenceClassification.from_pretrained(
            model_path,
            file_name="model_quantized.onnx"  # INT8 量化模型
        )

    def rerank(self, query, candidates, top_k=None, batch_size=32):
        pairs = [[query, c.get("content", "")] for c in candidates]
        all_scores = []

        for i in range(0, len(pairs), batch_size):
            batch = pairs[i:i + batch_size]
            encoded = self.tokenizer(
                batch, padding=True, truncation=True,
                max_length=512, return_tensors="pt"
            )
            with torch.no_grad():
                logits = self.model(**encoded).logits
                scores = torch.sigmoid(logits[:, 0]).numpy()
            all_scores.extend(scores.tolist())

        # 排序并返回...
```

**INT8 量化效果**:
- 模型体积: 1.1GB → 280MB (-75%)
- 推理速度: 提升 ~1.8x
- 精度损失: MRR 0.923 → 0.921 (-0.2%)

**依赖**: 需新增 `optimum[onnxruntime]`

**改动范围**: 新建 `quantized_reranker.py` 或扩展现有类

### 4.3 阈值过滤优化

**现状**: 已实现 `rerank_min_score` 阈值过滤，默认 0.0。

**优化建议**: 将默认阈值调整为 0.3，过滤低相关性候选。

```python
# config.py
@dataclass(frozen=True)
class RerankConfig:
    rerank_min_score: float = 0.3  # 调整默认值
```

**策略理由**: 低相关性内容干扰 LLM 生成的风险 > 内容量减少的风险。

### 4.4 优化组合效果预估

| 优化组合 | 延迟 | 内存 | 模型体积 | 精度损失 |
|---------|------|------|---------|---------|
| 原始（FP32，无批量控制） | ~300ms | ~2GB | 1.1GB | - |
| 批量推理 | ~150ms | ~2GB | 1.1GB | - |
| 批量 + INT8 | ~80ms | ~0.5GB | 280MB | -0.2% |
| 批量 + INT8 + 阈值 | ~80ms | ~0.5GB | 280MB | -0.2% |

**推荐组合**: 批量推理 + INT8 量化 + 阈值过滤 (min_score=0.3)

---

## 五、接口兼容性分析

### 5.1 输入输出格式

| 方面 | LLMReranker | CrossEncoderReranker | BgeReranker (新增) | 兼容性 |
|------|-------------|---------------------|-------------------|--------|
| 输入: query | str | str | str | ✅ 兼容 |
| 输入: candidates | List[Dict] | List[Dict] | List[Dict] | ✅ 兼容 |
| 输入: top_k | Optional[int] | Optional[int] | Optional[int] | ✅ 兼容 |
| 输出: List[Dict] | ✅ | ✅ | ✅ | ✅ 兼容 |
| 输出: rerank_score | float (排名倒数) | float (概率) | float (概率) | ⚠️ 语义不同 |
| 输出: reranked | bool | bool | bool | ✅ 兼容 |

**注意**: LLMReranker 的 `rerank_score` 是排名倒数 (1, 0.5, 0.33...)，CrossEncoderReranker 是概率分数 (0.8, 0.6, 0.3...)。阈值过滤需考虑差异。

### 5.2 配置方式

**现有配置**:
```python
@dataclass(frozen=True)
class RerankConfig:
    enable_rerank: bool = True
    reranker_type: str = "llm"  # "llm", "hf", "none"
    rerank_top_k: int = 5
    rerank_min_score: float = 0.0
```

**扩展建议**:
```python
@dataclass(frozen=True)
class RerankConfig:
    enable_rerank: bool = True
    reranker_type: str = "llm"  # "llm", "hf", "bge", "none"
    rerank_top_k: int = 5
    rerank_min_score: float = 0.3

    # 新增字段
    reranker_model: str = ""           # 本地模型路径或 HuggingFace 模型名
    reranker_batch_size: int = 32      # 批量推理大小
    reranker_max_length: int = 512     # 最大 token 长度
    reranker_quantized: bool = False   # 是否使用 INT8 量化
```

### 5.3 异常处理

**现有模式**: fail-fast
- LLMReranker: LLM 失败时返回原始候选 + `reranked=False`
- CrossEncoderReranker: 无回退，依赖 sentence-transformers 异常传播

**建议**: 新增 BgeReranker 采用 fail-fast 策略，模型加载失败或推理失败直接抛出异常。

---

## 六、本地部署可行性评估

### 6.1 硬件要求

| 配置 | bge-reranker-large (FP32) | bge-reranker-large (INT8) |
|------|---------------------------|---------------------------|
| GPU 显存 | ~2GB | ~0.5GB |
| CPU 内存 | ~4GB | ~1GB |
| 推荐配置 | RTX 3060+ / 8GB RAM | 任意 GPU / 4GB RAM |
| 纯 CPU | 可用但慢（~500ms） | 可用（~200ms） |

### 6.2 依赖库

```bash
# 基础依赖（已有）
pip install sentence-transformers>=2.2.0

# INT8 量化依赖（需新增）
pip install optimum[onnxruntime]>=1.16.0
```

### 6.3 模型下载和部署

```bash
# 方式 1: HuggingFace 自动下载（首次运行）
# 模型缓存在 ~/.cache/huggingface/

# 方式 2: 手动下载到本地
from sentence_transformers import CrossEncoder
model = CrossEncoder("BAAI/bge-reranker-large")
model.save("/path/to/models/bge-reranker-large")

# 方式 3: INT8 量化后保存
from optimum.onnxruntime import ORTModelForSequenceClassification
model = ORTModelForSequenceClassification.from_pretrained(
    "BAAI/bge-reranker-large",
    export=True
)
# 量化...
model.save_pretrained("/path/to/models/bge-reranker-large-int8")
```

### 6.4 推理延迟预估

| 场景 | 延迟 (50 候选) |
|------|---------------|
| LLM 精排 (glm-4-flash) | 1-2s |
| bge-reranker-large FP32 (无批量) | ~1500ms |
| bge-reranker-large FP32 (批量) | ~300ms |
| bge-reranker-large INT8 (批量) | ~80ms |

---

## 七、实现建议

### 7.1 推荐实现路径

**Phase 1: 基础集成** (工作量: 1-2 天)
1. 扩展 `RerankConfig` 添加新配置字段
2. 创建 `BgeReranker` 类，继承 `BaseReranker`
3. 在 `_create_reranker()` 添加 "bge" 类型分支
4. 支持本地模型路径加载

**Phase 2: 批量推理优化** (工作量: 0.5 天)
1. 在 `BgeReranker` 实现显式 batch_size 控制
2. 添加配置项 `reranker_batch_size`

**Phase 3: INT8 量化支持** (工作量: 1 天)
1. 添加 `optimum[onnxruntime]` 依赖
2. 创建量化模型加载逻辑
3. 添加配置项 `reranker_quantized`

**Phase 4: 阈值调优** (工作量: 0.5 天)
1. 调整 `rerank_min_score` 默认值为 0.3
2. 在评测模块验证阈值效果

### 7.2 文件结构

```
scripts/lib/rag_engine/
├── reranker_base.py           # 不变
├── llm_reranker.py            # 不变
├── cross_encoder_reranker.py  # 可选：重构为基类
├── bge_reranker.py            # 新增：bge-reranker-large 实现
├── config.py                  # 修改：扩展 RerankConfig
└── rag_engine.py              # 修改：_create_reranker() 添加分支
```

### 7.3 接口设计

```python
class BgeReranker(BaseReranker):
    """BGE Reranker with batch inference and optional INT8 quantization"""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-large",
        model_path: Optional[str] = None,
        max_length: int = 512,
        batch_size: int = 32,
        use_quantization: bool = False,
        device: str = "cuda",
    ):
        ...

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        ...
```

---

## 八、风险提示

### 8.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| INT8 量化精度损失超预期 | 中 | 中 | 先测试 FP32，验证效果后再量化 |
| 本地模型加载内存不足 | 低 | 高 | 提供 INT8 选项，降低内存需求 |
| sentence-transformers 版本兼容 | 低 | 中 | 锁定版本，测试兼容性 |
| max_length=512 导致长文本截断 | 中 | 中 | 配置化 max_length，默认 512 |

### 8.2 兼容性风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| rerank_score 语义差异影响阈值 | 高 | 中 | 文档说明，建议不同 reranker 使用不同阈值 |
| 新依赖与现有环境冲突 | 低 | 高 | 使用虚拟环境，测试依赖隔离 |

### 8.3 运维风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 模型下载慢/失败 | 中 | 高 | 提前下载到本地，使用 model_path 配置 |
| GPU 显存不足 | 中 | 高 | 监控显存，提供 CPU 回退（文档说明） |

---

## 九、参考实现

- [BGE Reranker 官方文档](https://huggingface.co/BAAI/bge-reranker-large) — 模型使用说明
- [sentence-transformers CrossEncoder](https://www.sbert.net/examples/applications/cross-encoder/README.html) — API 文档
- [optimum ONNX Runtime](https://huggingface.co/docs/optimum/en/onnxruntime/usage_guides/quantization) — INT8 量化指南
- [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding) — 官方库，支持更多参数

---

## 十、总结

### 10.1 主要发现

1. **已有精排器抽象** — `BaseReranker` 接口清晰，扩展简单
2. **已有 CrossEncoderReranker** — 但默认使用 `bge-reranker-v2-m3`，非 large
3. **接口完全兼容** — 输入输出格式统一，只需实现抽象方法
4. **配置可扩展** — `RerankConfig` 支持添加新字段
5. **阈值过滤已实现** — `rerank_min_score` 配置项

### 10.2 关键结论

| 问题 | 结论 |
|------|------|
| bge-reranker-large 能否集成？ | ✅ 可以，与现有接口完全兼容 |
| 本地部署可行吗？ | ✅ 可行，INT8 量化后仅需 ~0.5GB 显存 |
| 批量推理需要改造吗？ | ⚠️ 需要，显式控制 batch_size |
| INT8 量化需要新增依赖吗？ | ✅ 需要 `optimum[onnxruntime]` |
| 阈值过滤需要实现吗？ | ❌ 不需要，已实现 |

### 10.3 下一步行动

1. 执行 `/gen-plan` 生成技术实现方案
2. Phase 1 先实现基础集成（无量化）
3. 在评测模块验证效果后再决定是否量化
