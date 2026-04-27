#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BGE Reranker with batch inference and optional INT8 quantization."""
import logging
from typing import List, Dict, Any, Optional

from .reranker_base import BaseReranker

logger = logging.getLogger(__name__)


def _get_best_device() -> str:
    """Auto-detect best available device: cuda, mps, or cpu."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


class BgeReranker(BaseReranker):
    """BGE reranker using sentence-transformers CrossEncoder with batch inference.

    Why separate class from CrossEncoderReranker: batch_size control is
    critical for latency — CrossEncoder.predict() sends all pairs in one call
    which can OOM on large candidate sets. Explicit batching prevents this.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-large",
        max_length: int = 512,
        batch_size: int = 32,
        device: Optional[str] = None,
    ):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for BgeReranker. "
                "Install with: pip install sentence-transformers"
            )
        self._max_length = max_length
        self._batch_size = batch_size
        actual_device = device if device else _get_best_device()
        self._model = CrossEncoder(model_name, max_length=max_length, device=actual_device)
        logger.info(f"BgeReranker initialized: {model_name}, batch_size={batch_size}, device={actual_device}")

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
        return self._apply_scores(candidates, all_scores, top_k)


class QuantizedBgeReranker(BaseReranker):
    """Quantized BGE reranker — MPS uses PyTorch dynamic INT8, others use ONNX Runtime.

    Why two backends: ONNX Runtime has no MPS ExecutionProvider, so Apple Silicon
    GPU acceleration requires PyTorch native quantization. CUDA/CPU use ONNX for
    better throughput.
    """

    def __init__(
        self,
        model_path: str,
        batch_size: int = 32,
        max_length: int = 512,
        device: Optional[str] = None,
    ):
        import torch
        self._device = device or _get_best_device()
        self._batch_size = batch_size
        self._max_length = max_length
        self._use_pytorch = self._device == "mps"
        if self._use_pytorch:
            self._init_pytorch_backend(model_path)
        else:
            self._init_onnx_backend(model_path)
        logger.info(
            f"QuantizedBgeReranker initialized from {model_path}, "
            f"device={self._device}, backend={'pytorch' if self._use_pytorch else 'onnx'}"
        )

    def _init_pytorch_backend(self, model_path: str) -> None:
        """PyTorch dynamic INT8 quantization for MPS."""
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        model = AutoModelForSequenceClassification.from_pretrained(model_path)
        model.eval()
        self._model = torch.quantization.quantize_dynamic(
            model, {torch.nn.Linear}, dtype=torch.qint8,
        ).to(self._device)

    def _init_onnx_backend(self, model_path: str) -> None:
        """ONNX Runtime INT8 for CUDA/CPU."""
        try:
            from optimum.onnxruntime import ORTModelForSequenceClassification
            from transformers import AutoTokenizer
        except ImportError:
            raise ImportError(
                "optimum[onnxruntime] is required for QuantizedBgeReranker on CUDA/CPU. "
                "Install with: pip install optimum[onnxruntime]"
            )
        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        provider = "CUDAExecutionProvider" if self._device == "cuda" else "CPUExecutionProvider"
        self._model = ORTModelForSequenceClassification.from_pretrained(
            model_path,
            file_name="model_quantized.onnx",
            provider=provider,
        )

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
            if self._use_pytorch:
                encoded = {k: v.to(self._device) for k, v in encoded.items()}
            with torch.no_grad():
                logits = self._model(**encoded).logits
                if self._use_pytorch:
                    scores = torch.sigmoid(logits[:, 0]).cpu().numpy()
                else:
                    scores = torch.sigmoid(logits[:, 0]).numpy()
            all_scores.extend(scores.tolist())
        return self._apply_scores(candidates, all_scores, top_k)
