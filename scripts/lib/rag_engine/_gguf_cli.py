#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jina-reranker-v3 GGUF 精排模块

基于 Hanxiao 的 llama.cpp fork，通过 llama-embedding CLI 实现精排。
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from safetensors import safe_open

_MODULE_DIR = Path(__file__).parent
_DATA_DIR = _MODULE_DIR / "models" / "reranker"
_TOOLS_DIR = _MODULE_DIR / "tools" / "hanxiao-llama.cpp"


class MLPProjector:
    """MLP projector to project hidden states to embedding space."""

    def __init__(self, linear1_weight, linear2_weight):
        self.linear1_weight = linear1_weight
        self.linear2_weight = linear2_weight

    def __call__(self, x):
        x = x @ self.linear1_weight.T
        x = np.maximum(0, x)
        x = x @ self.linear2_weight.T
        return x


def _load_projector(projector_path: str) -> MLPProjector:
    with safe_open(projector_path, framework="numpy") as f:
        w0 = f.get_tensor("projector.0.weight")
        w2 = f.get_tensor("projector.2.weight")
    return MLPProjector(w0, w2)


def _sanitize_input(text: str, special_tokens: Dict[str, str]) -> str:
    for token in special_tokens.values():
        text = text.replace(token, "")
    return text


def _format_docs_prompts_func(
    query: str,
    docs: list[str],
    instruction: Optional[str] = None,
    special_tokens: Dict[str, str] = {},
) -> str:
    query = _sanitize_input(query, special_tokens)
    docs = [_sanitize_input(doc, special_tokens) for doc in docs]

    prefix = (
        "<|im_start|>system\n"
        "You are a search relevance expert who can determine a ranking of the passages based on how relevant they are to the query. "
        "If the query is a question, how relevant a passage is depends on how well it answers the question. "
        "If not, try to analyze the intent of the query and assess how well each passage satisfies the intent. "
        "If an instruction is provided, you should follow the instruction when determining the ranking."
        "<|im_end|>\n<|im_start|>user\n"
    )
    suffix = "<|im_end|>\n<|im_start|>assistant\n"

    doc_emb_token = special_tokens["doc_embed_token"]
    query_emb_token = special_tokens["query_embed_token"]

    prompt = (
        f"I will provide you with {len(docs)} passages, each indicated by a numerical identifier. "
        f"Rank the passages based on their relevance to query: {query}\n"
    )

    if instruction:
        prompt += f'<instruct>\n{instruction}\n</instruct>\n'

    doc_prompts = [f'<passage id="{i}">\n{doc}{doc_emb_token}\n</passage>' for i, doc in enumerate(docs)]
    prompt += "\n".join(doc_prompts) + "\n"
    prompt += f"<query>\n{query}{query_emb_token}\n</query>"

    return prefix + prompt + suffix


class GGUFReranker:
    """基于 GGUF 的 jina-reranker-v3 精排器"""

    _DOC_EMBED_TOKEN_ID = 151670
    _QUERY_EMBED_TOKEN_ID = 151671

    def __init__(
        self,
        model_path: Optional[str] = None,
        projector_path: Optional[str] = None,
        llama_embedding_path: Optional[str] = None,
    ):
        model_path = model_path or str(_DATA_DIR / "jina-reranker-v3-Q4_K_M.gguf")
        projector_path = projector_path or str(_DATA_DIR / "projector.safetensors")
        llama_embedding_path = llama_embedding_path or str(_TOOLS_DIR / "build" / "bin" / "llama-embedding")

        for path, label in [(model_path, "model"), (projector_path, "projector"), (llama_embedding_path, "llama-embedding")]:
            if not os.path.isfile(path):
                raise FileNotFoundError(f"{label} not found: {path}")

        self.model_path = model_path
        self.llama_embedding_path = llama_embedding_path
        self._llama_tokenize_path = os.path.join(os.path.dirname(llama_embedding_path), "llama-tokenize")
        self.projector = _load_projector(projector_path)

        self.special_tokens = {
            "query_embed_token": "<|rerank_token|>",
            "doc_embed_token": "<|embed_token|>",
        }

    def _get_hidden_states(self, prompt: str) -> np.ndarray:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            result = subprocess.run(
                [
                    self.llama_embedding_path,
                    '-m', self.model_path,
                    '-f', prompt_file,
                    '--pooling', 'none',
                    '--embd-separator', '<#JINA_SEP#>',
                    '--embd-normalize', '-1',
                    '--embd-output-format', 'json',
                    '--ubatch-size', '512',
                    '--ctx-size', '8192',
                    '--flash-attn',
                    '-ngl', '99',
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            output = json.loads(result.stdout)
            embeddings = [item['embedding'] for item in output['data']]
            return np.array(embeddings)
        finally:
            os.unlink(prompt_file)

    def _tokenize(self, prompt: str) -> List[int]:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            result = subprocess.run(
                [self._llama_tokenize_path, '-m', self.model_path, '-f', prompt_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            tokens = []
            for line in result.stdout.decode('utf-8', errors='replace').strip().split('\n'):
                if '->' in line:
                    token_id = int(line.split('->')[0].strip())
                    tokens.append(token_id)
            return tokens
        finally:
            os.unlink(prompt_file)

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
        return_embeddings: bool = False,
        instruction: Optional[str] = None,
    ) -> List[Dict]:
        prompt = _format_docs_prompts_func(
            query, documents,
            instruction=instruction,
            special_tokens=self.special_tokens,
        )

        embeddings = self._get_hidden_states(prompt)
        tokens = self._tokenize(prompt)
        tokens_array = np.array(tokens)

        query_positions = np.where(tokens_array == self._QUERY_EMBED_TOKEN_ID)[0]
        doc_positions = np.where(tokens_array == self._DOC_EMBED_TOKEN_ID)[0]

        if len(query_positions) == 0:
            raise ValueError(f"Query embed token (ID {self._QUERY_EMBED_TOKEN_ID}) not found in input")
        if len(doc_positions) == 0:
            raise ValueError(f"Document embed tokens (ID {self._DOC_EMBED_TOKEN_ID}) not found in input")

        query_pos = query_positions[0]

        query_hidden = embeddings[query_pos:query_pos + 1]
        doc_hidden = embeddings[doc_positions]

        query_embeds = self.projector(query_hidden)
        doc_embeds = self.projector(doc_hidden)

        query_expanded = np.tile(query_embeds, (len(doc_embeds), 1))

        dot_product = np.sum(doc_embeds * query_expanded, axis=-1)
        doc_norm = np.sqrt(np.sum(doc_embeds * doc_embeds, axis=-1))
        query_norm = np.sqrt(np.sum(query_expanded * query_expanded, axis=-1))
        scores = dot_product / (doc_norm * query_norm)

        results = []
        for idx, (doc, score, embed) in enumerate(zip(documents, scores, doc_embeds)):
            result = {
                "index": idx,
                "relevance_score": float(score),
                "document": doc,
            }
            if return_embeddings:
                result["embedding"] = embed.tolist()
            results.append(result)

        results.sort(key=lambda x: x["relevance_score"], reverse=True)

        if top_n is not None:
            results = results[:top_n]

        return results
