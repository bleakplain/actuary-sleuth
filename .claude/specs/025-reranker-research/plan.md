# Implementation Plan: Reranker Research

**Branch**: `025-reranker-research` | **Date**: 2026-04-26 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

**已完成**: research.md 调研报告，包含现有精排模块架构分析、bge-reranker-large 可行性评估、工程优化方案分析。

**结论**: bge-reranker-large 可以作为独立精排器集成，与现有接口完全兼容。推荐采用批量推理 + INT8 量化 + 阈值过滤组合，预期延迟从 LLM 精排 1-2s 降到 80-100ms。

**后续可选**: 实现 BgeReranker 类（Phase 2-4），这是独立的实现任务，不在本次调研范围内。

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: sentence-transformers>=2.2.0, transformers>=4.30.0, torch>=2.0.0
**Optional Dependencies**: optimum[onnxruntime]>=1.16.0 (INT8 量化)
**Storage**: 本地模型文件 (~1.1GB FP32, ~280MB INT8)
**Testing**: pytest
**Performance Goals**: 精排延迟 < 200ms (50 候选)
**Constraints**: 保持现有接口兼容、fail-fast 策略

## Constitution Check

- [x] **Library-First**: 复用现有 `BaseReranker` 接口和 `sentence-transformers` 库
- [x] **测试优先**: 规划了单元测试和集成测试
- [x] **简单优先**: 先实现 FP32 版本，验证后再考虑量化
- [x] **显式优于隐式**: 配置项明确，无魔法行为
- [x] **可追溯性**: 每个实现阶段回溯到 spec.md User Story
- [x] **独立可测试**: BgeReranker 可独立测试和交付

## Project Structure

### Documentation

```text
.claude/specs/025-reranker-research/
├── spec.md          # 需求规格
├── research.md      # 技术调研报告 ✅ 已完成
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成（如需实现）
```

### Source Code (可选实现)

```text
scripts/lib/rag_engine/
├── reranker_base.py           # 不变
├── llm_reranker.py            # 不变
├── cross_encoder_reranker.py  # 不变
├── bge_reranker.py            # 新增（可选）
├── config.py                  # 修改：扩展 RerankConfig（可选）
└── rag_engine.py              # 修改：_create_reranker() 添加分支（可选）
```

---

## Phase 1: 调研报告产出 ✅ 已完成

### 需求回溯

→ 对应 spec.md 所有 User Stories:
- User Story 1: 代码架构分析
- User Story 2: bge-reranker-large 可行性评估
- User Story 3: 工程优化方案评估
- User Story 4: 迁移建议

### 产出物

| 产物 | 状态 | 位置 |
|------|------|------|
| spec.md | ✅ 完成 | `.claude/specs/025-reranker-research/spec.md` |
| research.md | ✅ 完成 | `.claude/specs/025-reranker-research/research.md` |
| plan.md | ✅ 本文件 | `.claude/specs/025-reranker-research/plan.md` |

### 验收标准

| User Story | 验收标准 | 状态 |
|-----------|---------|------|
| US-1 代码架构分析 | research.md 包含类结构、接口定义、调用流程 | ✅ |
| US-2 可行性评估 | research.md 包含模型特性、接口兼容性、部署要求 | ✅ |
| US-3 工程优化分析 | research.md 包含批量推理、INT8 量化、阈值过滤方案 | ✅ |
| US-4 迁移建议 | research.md 包含实现路径和风险提示 | ✅ |

---

## Phase 2-4: BgeReranker 实现 (可选)

以下为实现 bge-reranker-large 作为新精排器的技术方案，供后续实现参考。

### Phase 2: 基础集成

#### 需求回溯

→ 对应 research.md 实现建议 7.1 Phase 1

#### 实现步骤

**步骤 2.1: 扩展 RerankConfig**

```python
# 文件: scripts/lib/rag_engine/config.py
# 位置: 第 62-85 行

@dataclass(frozen=True)
class RerankConfig:
    """重排序配置"""
    enable_rerank: bool = True
    reranker_type: str = "llm"
    rerank_top_k: int = 5
    rerank_min_score: float = 0.0

    # 新增字段
    reranker_model: str = ""           # 本地模型路径或 HuggingFace 模型名
    reranker_batch_size: int = 32      # 批量推理大小
    reranker_max_length: int = 512     # 最大 token 长度
    reranker_quantized: bool = False   # 是否使用 INT8 量化

    _VALID_RERANKER_TYPES = {"llm", "hf", "bge", "none"}

    def __post_init__(self):
        if self.rerank_top_k < 1:
            raise ValueError(f"rerank_top_k must be >= 1, got {self.rerank_top_k}")
        if self.reranker_type not in self._VALID_RERANKER_TYPES:
            raise ValueError(
                f"reranker_type must be one of {self._VALID_RERANKER_TYPES}, "
                f"got {self.reranker_type}"
            )
        if not 0.0 <= self.rerank_min_score <= 1.0:
            raise ValueError(
                f"rerank_min_score must be between 0.0 and 1.0, "
                f"got {self.rerank_min_score}"
            )
        if self.reranker_batch_size < 1:
            raise ValueError(f"reranker_batch_size must be >= 1, got {self.reranker_batch_size}")
        if self.reranker_max_length < 64:
            raise ValueError(f"reranker_max_length must be >= 64, got {self.reranker_max_length}")
```

**步骤 2.2: 创建 BgeReranker 类**

```python
# 文件: scripts/lib/rag_engine/bge_reranker.py
# 新增文件

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BGE Reranker with batch inference support."""
import logging
from typing import List, Dict, Any, Optional

from .reranker_base import BaseReranker

logger = logging.getLogger(__name__)


class BgeReranker(BaseReranker):
    """BGE Reranker with batch inference support.

    Supports bge-reranker-large and bge-reranker-v2-m3 models.
    Uses sentence-transformers CrossEncoder for inference.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-large",
        model_path: Optional[str] = None,
        max_length: int = 512,
        batch_size: int = 32,
        device: str = "cuda",
    ):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for BgeReranker. "
                "Install with: pip install sentence-transformers"
            )

        self._model_name = model_name
        self._max_length = max_length
        self._batch_size = batch_size
        self._device = device

        if model_path:
            self._model = CrossEncoder(
                model_path,
                max_length=max_length,
                device=device,
            )
        else:
            self._model = CrossEncoder(
                model_name,
                max_length=max_length,
                device=device,
            )

        logger.info(f"BgeReranker initialized: {model_path or model_name}, batch_size={batch_size}")

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        texts = [c.get("content", "") for c in candidates]
        pairs = [[query, text] for text in texts]
        all_scores: List[float] = []

        for i in range(0, len(pairs), self._batch_size):
            batch = pairs[i:i + self._batch_size]
            scores = self._model.predict(batch, show_progress_bar=False)
            all_scores.extend(scores.tolist() if hasattr(scores, 'tolist') else list(scores))

        scored: List[Dict[str, Any]] = []
        for idx, candidate in enumerate(candidates):
            item = dict(candidate)
            item["rerank_score"] = float(all_scores[idx])
            item["reranked"] = True
            scored.append(item)

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)

        if top_k is not None:
            scored = scored[:top_k]

        return scored
```

**步骤 2.3: 修改 RAGEngine 工厂方法**

```python
# 文件: scripts/lib/rag_engine/rag_engine.py
# 位置: 第 151-172 行
# 修改 _create_reranker() 方法

from .bge_reranker import BgeReranker

def _create_reranker(self) -> Optional[BaseReranker]:
    rc = self.config.rerank

    if not rc.enable_rerank or rc.reranker_type == "none":
        self._active_reranker_type = "none"
        return None

    rerank_config = RerankConfig(
        enabled=True,
        top_k=rc.rerank_top_k,
    )

    if rc.reranker_type == "llm":
        self._active_reranker_type = "llm"
        return LLMReranker(self._llm_client, rerank_config)

    if rc.reranker_type == "hf":
        self._active_reranker_type = "cross_encoder"
        model_path = rc.reranker_model if rc.reranker_model else None
        return CrossEncoderReranker(
            model_path=model_path,
            max_length=rc.reranker_max_length,
        )

    if rc.reranker_type == "bge":
        self._active_reranker_type = "bge"
        model_path = rc.reranker_model if rc.reranker_model else None
        model_name = "BAAI/bge-reranker-large" if not model_path else ""
        return BgeReranker(
            model_name=model_name,
            model_path=model_path,
            max_length=rc.reranker_max_length,
            batch_size=rc.reranker_batch_size,
        )

    self._active_reranker_type = "none"
    return None
```

**步骤 2.4: 更新 __init__.py 导出**

```python
# 文件: scripts/lib/rag_engine/__init__.py
# 位置: 第 30 行后添加

from .bge_reranker import BgeReranker

# __all__ 列表中添加
'BgeReranker',
```

#### 测试用例

```python
# 文件: scripts/tests/lib/rag_engine/test_bge_reranker.py
# 新增文件

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock, patch

from lib.rag_engine.bge_reranker import BgeReranker


def _make_candidates(n: int) -> list:
    return [
        {'content': f'条款内容第{i}条', 'law_name': f'法规{i}', 'article_number': f'第{i}条'}
        for i in range(1, n + 1)
    ]


class TestBgeReranker:
    """BgeReranker 单元测试"""

    @pytest.fixture
    def mock_cross_encoder(self):
        with patch('lib.rag_engine.bge_reranker.CrossEncoder') as mock:
            mock_instance = MagicMock()
            mock.return_value = mock_instance
            mock_instance.predict.return_value = [0.9, 0.5, 0.3, 0.1, 0.2]
            yield mock_instance

    def test_rerank_basic(self, mock_cross_encoder):
        reranker = BgeReranker()
        candidates = _make_candidates(5)
        results = reranker.rerank('等待期', candidates)

        assert len(results) == 5
        assert results[0]['rerank_score'] == 0.9
        assert results[0]['reranked'] is True
        assert results[0]['article_number'] == '第1条'

    def test_rerank_with_top_k(self, mock_cross_encoder):
        mock_cross_encoder.predict.return_value = [0.9, 0.5, 0.3]
        reranker = BgeReranker()
        candidates = _make_candidates(3)

        results = reranker.rerank('等待期', candidates, top_k=2)

        assert len(results) == 2

    def test_rerank_empty_candidates(self, mock_cross_encoder):
        reranker = BgeReranker()
        results = reranker.rerank('test', [])

        assert results == []
        mock_cross_encoder.predict.assert_not_called()

    def test_rerank_batch_processing(self, mock_cross_encoder):
        mock_cross_encoder.predict.side_effect = [
            [0.9, 0.8],  # batch 1
            [0.5, 0.3],  # batch 2
        ]
        reranker = BgeReranker(batch_size=2)
        candidates = _make_candidates(4)

        results = reranker.rerank('test', candidates)

        assert len(results) == 4
        assert mock_cross_encoder.predict.call_count == 2

    def test_rerank_preserves_metadata(self, mock_cross_encoder):
        mock_cross_encoder.predict.return_value = [0.9, 0.5]
        reranker = BgeReranker()
        candidates = [
            {'content': '内容1', 'law_name': '法规A', 'article_number': '第一条', 'extra': 'value'},
            {'content': '内容2', 'law_name': '法规B', 'article_number': '第二条'},
        ]

        results = reranker.rerank('test', candidates)

        assert results[0]['law_name'] == '法规A'
        assert results[0]['extra'] == 'value'
```

---

### Phase 3: INT8 量化支持 (可选)

#### 需求回溯

→ 对应 research.md 工程优化 4.2 INT8 量化

#### 实现步骤

**步骤 3.1: 添加依赖**

```text
# 文件: scripts/requirements.txt
# 新增

# INT8 quantization for reranker (optional)
# optimum[onnxruntime]>=1.16.0
```

**步骤 3.2: 创建量化版 BgeReranker**

```python
# 文件: scripts/lib/rag_engine/bge_reranker.py
# 添加 QuantizedBgeReranker 类

class QuantizedBgeReranker(BaseReranker):
    """Quantized BGE Reranker using ONNX Runtime INT8."""

    def __init__(
        self,
        model_path: str,
        batch_size: int = 32,
        max_length: int = 512,
    ):
        try:
            from optimum.onnxruntime import ORTModelForSequenceClassification
            from transformers import AutoTokenizer
        except ImportError:
            raise ImportError(
                "optimum[onnxruntime] is required for QuantizedBgeReranker. "
                "Install with: pip install optimum[onnxruntime]"
            )

        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._model = ORTModelForSequenceClassification.from_pretrained(
            model_path,
            file_name="model_quantized.onnx",
        )
        self._batch_size = batch_size
        self._max_length = max_length

        logger.info(f"QuantizedBgeReranker initialized from {model_path}")

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        import torch

        if not candidates:
            return []

        pairs = [[query, c.get("content", "")] for c in candidates]
        all_scores: List[float] = []

        for i in range(0, len(pairs), self._batch_size):
            batch = pairs[i:i + self._batch_size]
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self._max_length,
                return_tensors="pt",
            )
            with torch.no_grad():
                logits = self._model(**encoded).logits
                scores = torch.sigmoid(logits[:, 0]).numpy()
            all_scores.extend(scores.tolist())

        scored: List[Dict[str, Any]] = []
        for idx, candidate in enumerate(candidates):
            item = dict(candidate)
            item["rerank_score"] = float(all_scores[idx])
            item["reranked"] = True
            scored.append(item)

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)

        if top_k is not None:
            scored = scored[:top_k]

        return scored
```

**步骤 3.3: 更新工厂方法支持量化**

```python
# 文件: scripts/lib/rag_engine/rag_engine.py
# 修改 _create_reranker() 的 "bge" 分支

if rc.reranker_type == "bge":
    self._active_reranker_type = "bge"
    model_path = rc.reranker_model

    if rc.reranker_quantized:
        from .bge_reranker import QuantizedBgeReranker
        return QuantizedBgeReranker(
            model_path=model_path,
            batch_size=rc.reranker_batch_size,
            max_length=rc.reranker_max_length,
        )
    else:
        model_name = "BAAI/bge-reranker-large" if not model_path else ""
        return BgeReranker(
            model_name=model_name,
            model_path=model_path,
            max_length=rc.reranker_max_length,
            batch_size=rc.reranker_batch_size,
        )
```

---

### Phase 4: 配置和阈值调优

#### 需求回溯

→ 对应 research.md 工程优化 4.3 阈值过滤

#### 实现步骤

**步骤 4.1: 调整默认阈值**

```python
# 文件: scripts/lib/rag_engine/config.py
# 修改 RerankConfig 默认值

@dataclass(frozen=True)
class RerankConfig:
    """重排序配置"""
    enable_rerank: bool = True
    reranker_type: str = "llm"
    rerank_top_k: int = 5
    rerank_min_score: float = 0.3  # 从 0.0 调整为 0.3
```

**步骤 4.2: 添加环境变量支持**

```python
# 文件: scripts/lib/config.py
# 在 _load() 方法中添加

'rag': {
    'reranker_type': os.getenv('RAG_RERANKER_TYPE', 'llm'),
    'reranker_model': os.getenv('RAG_RERANKER_MODEL', ''),
    'reranker_batch_size': int(os.getenv('RAG_RERANKER_BATCH_SIZE', '32')),
    'reranker_min_score': float(os.getenv('RAG_RERANKER_MIN_SCORE', '0.3')),
    'reranker_quantized': os.getenv('RAG_RERANKER_QUANTIZED', 'false').lower() == 'true',
},
```

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | - | - |

---

## Appendix

### 执行顺序建议

```
Phase 1: 调研报告 ✅ 已完成
    ↓
Phase 2: 基础集成（可选）
    ├── 步骤 2.1: 扩展 RerankConfig
    ├── 步骤 2.2: 创建 BgeReranker 类
    ├── 步骤 2.3: 修改工厂方法
    └── 步骤 2.4: 更新导出
    ↓
Phase 3: INT8 量化（可选）
    └── 需要 Phase 2 完成后
    ↓
Phase 4: 配置调优
    └── 可与 Phase 2 并行
```

### 验收标准总结

| User Story | 验收标准 | 对应测试 | 状态 |
|-----------|---------|---------|------|
| US-1 代码架构分析 | research.md 包含类结构、接口、调用流程 | 文档审查 | ✅ |
| US-2 可行性评估 | research.md 包含模型特性、兼容性、部署要求 | 文档审查 | ✅ |
| US-3 工程优化 | research.md 包含批量推理、INT8 量化、阈值过滤 | 文档审查 | ✅ |
| US-4 迁移建议 | research.md 包含实现路径和风险提示 | 文档审查 | ✅ |

### 依赖关系

```
Phase 2 (基础集成)
    ├── 依赖: sentence-transformers (已有)
    └── 无新增依赖

Phase 3 (INT8 量化)
    └── 依赖: optimum[onnxruntime] (需新增)
```

### 配置示例

```python
# 使用 bge-reranker-large (FP32)
config = RAGConfig(
    rerank=RerankConfig(
        enable_rerank=True,
        reranker_type="bge",
        rerank_top_k=5,
        rerank_min_score=0.3,
        reranker_batch_size=32,
        reranker_max_length=512,
    )
)

# 使用本地量化模型
config = RAGConfig(
    rerank=RerankConfig(
        enable_rerank=True,
        reranker_type="bge",
        reranker_model="/path/to/models/bge-reranker-large-int8",
        reranker_quantized=True,
        rerank_min_score=0.3,
    )
)
```
