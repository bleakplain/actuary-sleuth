# Ollama Jina Embedding 切换实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将嵌入模型从智谱 embedding-3 切换为本地 Ollama jina-embeddings-v5-text-small，并添加 Jina v5 task-specific 前缀支持。

**Architecture:** 在 `llamaindex_adapter.py` 新增 `JinaEmbeddingAdapter` 类（组合 `OllamaEmbedding`，自动加 `search_query:` / `passage:` 前缀）。通过 `settings.json` 的 `ollama.embed_provider` 字段控制 embedding provider 选择，`get_embedding_config()` 根据配置返回 ollama 或 zhipu 配置。

**Tech Stack:** Python, Ollama API, LlamaIndex BaseEmbedding, llama-index OllamaEmbedding

---

### Task 1: 配置层 — OllamaConfig 增加 embed_provider 属性

**Files:**
- Modify: `scripts/lib/config.py:157-182`

- [ ] **Step 1: 在 OllamaConfig 类中增加 embed_provider 属性**

在 `scripts/lib/config.py` 的 `OllamaConfig` 类中，在 `embed_model` 属性之后（约第176行后）添加：

```python
    @property
    def embed_provider(self) -> str:
        """嵌入模型提供商：ollama 或 zhipu"""
        return self._config.get('embed_provider', 'zhipu')
```

- [ ] **Step 2: 运行类型检查**

Run: `cd /mnt/d/work/actuary-sleuth && python3 -c "from lib.config import get_config; c = get_config(); print(c.ollama.embed_provider)"`
Expected: 输出 `zhipu`（settings.json 中还没有该字段，走默认值）

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/config.py
git commit -m "feat: add embed_provider property to OllamaConfig"
```

---

### Task 2: 配置层 — settings.json 增加 embed_provider 字段

**Files:**
- Modify: `scripts/config/settings.json:14-19`

- [ ] **Step 1: 在 ollama 节点增加 embed_provider 和更新 embed_model**

将 `scripts/config/settings.json` 中的 `ollama` 节从：

```json
"ollama": {
    "host": "http://localhost:11434",
    "chat_model": "qwen2:7b",
    "embed_model": "nomic-embed-text",
    "timeout": 120
}
```

改为：

```json
"ollama": {
    "host": "http://localhost:11434",
    "chat_model": "qwen2:7b",
    "embed_provider": "ollama",
    "embed_model": "jinaai/jina-embeddings-v5-text-small",
    "timeout": 120
}
```

- [ ] **Step 2: 验证配置读取**

Run: `cd /mnt/d/work/actuary-sleuth/scripts && python3 -c "from lib.config import get_config; c = get_config(); print('provider:', c.ollama.embed_provider); print('model:', c.ollama.embed_model)"`
Expected: `provider: ollama` 和 `model: jinaai/jina-embeddings-v5-text-small`

- [ ] **Step 3: Commit**

```bash
git add scripts/config/settings.json
git commit -m "feat: configure Ollama jina-embeddings-v5-text-small as default embedding model"
```

---

### Task 3: 工厂层 — get_embedding_config() 从配置读取 provider

**Files:**
- Modify: `scripts/lib/llm/factory.py:112-121`

- [ ] **Step 1: 修改 get_embedding_config() 根据配置决定 provider**

将 `scripts/lib/llm/factory.py` 中的 `get_embedding_config()` 方法从：

```python
    @staticmethod
    def get_embedding_config() -> dict:
        """获取嵌入模型配置"""
        api_key, base_url = LLMClientFactory._get_base_config()
        return {
            'provider': 'zhipu',
            'model': ModelName.EMBEDDING_3,
            'api_key': api_key,
            'base_url': base_url,
            'timeout': 120,
        }
```

改为：

```python
    @staticmethod
    def get_embedding_config() -> dict:
        """获取嵌入模型配置（根据 ollama.embed_provider 决定）"""
        from lib.config import get_config
        app_config = get_config()

        if app_config.ollama.embed_provider == 'ollama':
            return {
                'provider': 'ollama',
                'model': app_config.ollama.embed_model,
                'host': app_config.ollama.host,
                'timeout': app_config.ollama.timeout,
            }

        api_key, base_url = LLMClientFactory._get_base_config()
        return {
            'provider': 'zhipu',
            'model': ModelName.EMBEDDING_3,
            'api_key': api_key,
            'base_url': base_url,
            'timeout': 120,
        }
```

- [ ] **Step 2: 验证配置输出**

Run: `cd /mnt/d/work/actuary-sleuth/scripts && python3 -c "from lib.llm import LLMClientFactory; cfg = LLMClientFactory.get_embedding_config(); print(cfg)"`
Expected: `{'provider': 'ollama', 'model': 'jinaai/jina-embeddings-v5-text-small', 'host': 'http://localhost:11434', 'timeout': 120}`

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/llm/factory.py
git commit -m "feat: read embedding provider from config instead of hardcoding zhipu"
```

---

### Task 4: 适配器层 — 新增 JinaEmbeddingAdapter 类

**Files:**
- Modify: `scripts/lib/rag_engine/llamaindex_adapter.py:17-23` (更新 _MODEL_LIMITS)
- Modify: `scripts/lib/rag_engine/llamaindex_adapter.py:193-236` (新增类和更新工厂函数)

- [ ] **Step 1: 在 _MODEL_LIMITS 中添加 jina small 条目**

在 `scripts/lib/rag_engine/llamaindex_adapter.py` 的 `_MODEL_LIMITS` 字典中添加：

```python
    'jinaai/jina-embeddings-v5-text-small': {'context': 8192, 'output': 1024},
```

- [ ] **Step 2: 在 ZhipuEmbeddingAdapter 之后、get_embedding_model() 之前新增 JinaEmbeddingAdapter 类**

在 `ZhipuEmbeddingAdapter` 类结束（约第196行）之后、`get_embedding_model` 函数之前插入：

```python
class JinaEmbeddingAdapter(BaseEmbedding):
    """Jina v5 嵌入适配器（通过 Ollama 调用，自动添加 task-specific 前缀）"""

    _PREFIX_QUERY = "search_query: "
    _PREFIX_PASSAGE = "passage: "

    def __init__(
        self,
        model_name: str = "jinaai/jina-embeddings-v5-text-small",
        base_url: str = "http://localhost:11434",
        embed_batch_size: int = 50,
    ):
        from llama_index.embeddings.ollama import OllamaEmbedding
        super().__init__(
            model_name=model_name,
            embed_batch_size=embed_batch_size,
        )
        self._ollama_embed = OllamaEmbedding(
            model_name=model_name,
            base_url=base_url,
            embed_batch_size=embed_batch_size,
        )

    def _get_query_embedding(self, query: str) -> List[float]:
        prefixed = self._PREFIX_QUERY + query
        return self._ollama_embed.get_text_embedding(prefixed)

    def _get_text_embedding(self, text: str) -> List[float]:
        prefixed = self._PREFIX_PASSAGE + text
        return self._ollama_embed.get_text_embedding(prefixed)

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        prefixed = [self._PREFIX_PASSAGE + t for t in texts]
        return self._ollama_embed.get_text_embeddings(prefixed)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return await asyncio.to_thread(self._get_query_embedding, query)

    async def aget_text_embedding(self, text: str) -> List[float]:
        return await asyncio.to_thread(self.get_text_embedding, text)

    async def aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self._get_text_embeddings, texts)
```

- [ ] **Step 3: 更新 get_embedding_model() 工厂函数，增加 jina 分支**

将 `get_embedding_model()` 函数中的 `ollama` 分支从：

```python
    elif provider == 'ollama':
        return OllamaEmbedding(
            model_name=config.get('model', 'nomic-embed-text'),
            base_url=config.get('host', 'http://localhost:11434'),
            embed_batch_size=config.get('embed_batch_size', 50),
        )
```

改为：

```python
    elif provider == 'ollama':
        model = config.get('model', 'nomic-embed-text')
        if 'jina' in model:
            return JinaEmbeddingAdapter(
                model_name=model,
                base_url=config.get('host', 'http://localhost:11434'),
                embed_batch_size=config.get('embed_batch_size', 50),
            )
        return OllamaEmbedding(
            model_name=model,
            base_url=config.get('host', 'http://localhost:11434'),
            embed_batch_size=config.get('embed_batch_size', 50),
        )
```

- [ ] **Step 4: 运行类型检查**

Run: `cd /mnt/d/work/actuary-sleuth && python3 -c "from lib.rag_engine.llamaindex_adapter import JinaEmbeddingAdapter, get_embedding_model; print('JinaEmbeddingAdapter imported OK')"`
Expected: 无报错

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/rag_engine/llamaindex_adapter.py
git commit -m "feat: add JinaEmbeddingAdapter with task-specific prefix support"
```

---

### Task 5: 测试更新 — 替换硬编码的 nomic-embed-text 模型名

**Files:**
- Modify: `scripts/tests/utils/rag_fixtures.py` (2处: 行115, 行242)
- Modify: `scripts/tests/lib/rag_engine/test_qa_engine.py` (3处: 行141, 行195, 行269)
- Modify: `scripts/tests/lib/rag_engine/test_resource_cleanup.py` (1处: 行46)
- Modify: `scripts/tests/integration/test_rag_integration.py` (4处: 行35, 行128, 行195, 行279)

- [ ] **Step 1: 替换 rag_fixtures.py 中的模型名**

在 `scripts/tests/utils/rag_fixtures.py` 中，将所有 `model_name="nomic-embed-text"` 替换为 `model_name="jinaai/jina-embeddings-v5-text-small"`（共2处：行115和行242）。

- [ ] **Step 2: 替换 test_qa_engine.py 中的模型名**

在 `scripts/tests/lib/rag_engine/test_qa_engine.py` 中，将所有 `model_name="nomic-embed-text"` 替换为 `model_name="jinaai/jina-embeddings-v5-text-small"`（共3处：行141、行195、行269）。

- [ ] **Step 3: 替换 test_resource_cleanup.py 中的模型名**

在 `scripts/tests/lib/rag_engine/test_resource_cleanup.py` 中，将 `model_name="nomic-embed-text"` 替换为 `model_name="jinaai/jina-embeddings-v5-text-small"`（共1处：行46）。

- [ ] **Step 4: 替换 test_rag_integration.py 中的模型名**

在 `scripts/tests/integration/test_rag_integration.py` 中，将所有 `model_name="nomic-embed-text"` 替换为 `model_name="jinaai/jina-embeddings-v5-text-small"`（共4处：行35、行128、行195、行279）。

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/utils/rag_fixtures.py scripts/tests/lib/rag_engine/test_qa_engine.py scripts/tests/lib/rag_engine/test_resource_cleanup.py scripts/tests/integration/test_rag_integration.py
git commit -m "test: update embedding model name to jinaai/jina-embeddings-v5-text-small"
```

---

### Task 6: 单元测试 — JinaEmbeddingAdapter 前缀逻辑

**Files:**
- Create: `scripts/tests/lib/rag_engine/test_jina_adapter.py`

- [ ] **Step 1: 编写 JinaEmbeddingAdapter 单元测试**

创建 `scripts/tests/lib/rag_engine/test_jina_adapter.py`：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JinaEmbeddingAdapter 单元测试"""
from unittest.mock import patch, MagicMock
import pytest


class TestJinaEmbeddingAdapter:
    """测试 Jina v5 嵌入适配器的前缀逻辑"""

    def test_query_prefix_added(self):
        """查询时添加 search_query: 前缀"""
        from lib.rag_engine.llamaindex_adapter import JinaEmbeddingAdapter

        with patch('lib.rag_engine.llamaindex_adapter.OllamaEmbedding') as mock_ollama_cls:
            mock_instance = MagicMock()
            mock_instance.get_text_embedding.return_value = [0.1] * 1024
            mock_ollama_cls.return_value = mock_instance

            adapter = JinaEmbeddingAdapter(
                model_name="jinaai/jina-embeddings-v5-text-small",
                base_url="http://localhost:11434",
            )
            result = adapter._get_query_embedding("等待期规定")

            mock_instance.get_text_embedding.assert_called_once_with("search_query: 等待期规定")
            assert result == [0.1] * 1024

    def test_text_prefix_added(self):
        """文档嵌入时添加 passage: 前缀"""
        from lib.rag_engine.llamaindex_adapter import JinaEmbeddingAdapter

        with patch('lib.rag_engine.llamaindex_adapter.OllamaEmbedding') as mock_ollama_cls:
            mock_instance = MagicMock()
            mock_instance.get_text_embedding.return_value = [0.2] * 1024
            mock_ollama_cls.return_value = mock_instance

            adapter = JinaEmbeddingAdapter(
                model_name="jinaai/jina-embeddings-v5-text-small",
                base_url="http://localhost:11434",
            )
            result = adapter._get_text_embedding("健康保险等待期不超过90天")

            mock_instance.get_text_embedding.assert_called_once_with("passage: 健康保险等待期不超过90天")
            assert result == [0.2] * 1024

    def test_batch_text_prefix_added(self):
        """批量文档嵌入时添加 passage: 前缀"""
        from lib.rag_engine.llamaindex_adapter import JinaEmbeddingAdapter

        with patch('lib.rag_engine.llamaindex_adapter.OllamaEmbedding') as mock_ollama_cls:
            mock_instance = MagicMock()
            mock_instance.get_text_embeddings.return_value = [[0.1] * 1024, [0.2] * 1024]
            mock_ollama_cls.return_value = mock_instance

            adapter = JinaEmbeddingAdapter(
                model_name="jinaai/jina-embeddings-v5-text-small",
                base_url="http://localhost:11434",
            )
            result = adapter._get_text_embeddings(["条款一", "条款二"])

            mock_instance.get_text_embeddings.assert_called_once_with(["passage: 条款一", "passage: 条款二"])
            assert len(result) == 2

    def test_get_embedding_model_factory_jina(self):
        """工厂函数对 jina 模型返回 JinaEmbeddingAdapter"""
        from lib.rag_engine.llamaindex_adapter import get_embedding_model, JinaEmbeddingAdapter

        with patch('lib.rag_engine.llamaindex_adapter.OllamaEmbedding'):
            config = {
                'provider': 'ollama',
                'model': 'jinaai/jina-embeddings-v5-text-small',
                'host': 'http://localhost:11434',
            }
            model = get_embedding_model(config)
            assert isinstance(model, JinaEmbeddingAdapter)

    def test_get_embedding_model_factory_non_jina(self):
        """工厂函数对非 jina 模型返回原始 OllamaEmbedding"""
        from lib.rag_engine.llamaindex_adapter import get_embedding_model
        from llama_index.embeddings.ollama import OllamaEmbedding

        config = {
            'provider': 'ollama',
            'model': 'nomic-embed-text',
            'host': 'http://localhost:11434',
        }
        model = get_embedding_model(config)
        assert isinstance(model, OllamaEmbedding)

    def test_prefix_constants(self):
        """验证前缀常量值"""
        from lib.rag_engine.llamaindex_adapter import JinaEmbeddingAdapter

        assert JinaEmbeddingAdapter._PREFIX_QUERY == "search_query: "
        assert JinaEmbeddingAdapter._PREFIX_PASSAGE == "passage: "
```

- [ ] **Step 2: 运行测试**

Run: `cd /mnt/d/work/actuary-sleuth && pytest scripts/tests/lib/rag_engine/test_jina_adapter.py -v`
Expected: 所有 6 个测试通过

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/lib/rag_engine/test_jina_adapter.py
git commit -m "test: add unit tests for JinaEmbeddingAdapter prefix logic"
```

---

### Task 7: 全量测试验证

**Files:** 无新文件修改

- [ ] **Step 1: 运行全量测试**

Run: `cd /mnt/d/work/actuary-sleuth && pytest scripts/tests/ -v --tb=short`
Expected: 所有现有测试通过（需要 Ollama 服务运行且 jina 模型已拉取的测试可能 skip）

- [ ] **Step 2: 运行类型检查**

Run: `cd /mnt/d/work/actuary-sleuth && mypy scripts/lib/`
Expected: 无新增错误

- [ ] **Step 3: 最终 Commit（如有修复）**

```bash
git add -A
git commit -m "fix: address test and type-check issues from jina embedding migration"
```
