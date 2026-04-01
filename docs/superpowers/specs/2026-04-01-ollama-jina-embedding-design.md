# Ollama Jina Embedding 切换设计

## 目标

将嵌入模型从智谱 embedding-3 切换为本地 Ollama 运行的 `jinaai/jina-embeddings-v5-text-small`，并修复 Jina v5 task-specific 前缀缺失问题。

## 配置变更

### settings.json

`ollama` 节增加 `embed_provider` 字段，控制 embedding 使用 ollama 还是 zhipu：

```json
"ollama": {
    "host": "http://localhost:11434",
    "chat_model": "qwen2:7b",
    "embed_provider": "ollama",
    "embed_model": "jinaai/jina-embeddings-v5-text-small",
    "timeout": 120
}
```

- `embed_provider`: `"ollama"` 或 `"zhipu"`，默认 `"zhipu"`（向后兼容）
- `embed_model`: 当 `embed_provider` 为 `"ollama"` 时使用的模型名

## 代码变更

### 1. lib/config.py — OllamaConfig 增加 embed_provider 属性

```python
@property
def embed_provider(self) -> str:
    """嵌入模型提供商：ollama 或 zhipu"""
    return self._config.get('embed_provider', 'zhipu')
```

### 2. lib/llm/factory.py — get_embedding_config() 从配置读取 provider

当前硬编码返回 zhipu 配置。改为根据 `ollama.embed_provider` 决定：

- `"ollama"` → 返回 `{provider: 'ollama', model: ollama.embed_model, host: ollama.host, timeout: 120}`
- `"zhipu"` 或默认 → 保持现有逻辑不变

### 3. lib/rag_engine/llamaindex_adapter.py — 新增 JinaEmbeddingAdapter

与 `ZhipuEmbeddingAdapter` 平级的新类：

- 内部组合 `OllamaEmbedding` 实例做 API 调用
- `_PREFIX_QUERY = "search_query: "`，`_PREFIX_PASSAGE = "passage: "`
- `_get_query_embedding(query)`: 加 query 前缀后调用 ollama embedding
- `_get_text_embedding(text)` / `_get_text_embeddings(texts)`: 加 passage 前缀后调用
- 异步方法委托给同步方法

### 4. lib/rag_engine/llamaindex_adapter.py — get_embedding_model() 增加 jina 分支

当 `provider == 'ollama'` 且 model 名包含 `"jina"` 时返回 `JinaEmbeddingAdapter`，否则返回原始 `OllamaEmbedding`。

### 5. _MODEL_LIMITS 表更新

增加 jina small 的维度信息：`'jinaai/jina-embeddings-v5-text-small': {'context': 8192, 'output': 1024}`

### 6. 测试文件更新

将测试中硬编码的 `nomic-embed-text` 替换为 `jinaai/jina-embeddings-v5-text-small`（涉及 test fixtures、integration tests 等）。

## 不改动的部分

- LLM chat 仍用智谱（不变）
- LanceDB 索引需用户手动 `force_rebuild`（维度从 2048→1024）
- BM25 索引不受影响

## 文件清单

| 文件 | 操作 |
|------|------|
| `scripts/config/settings.json` | 修改：增加 embed_provider 字段 |
| `scripts/lib/config.py` | 修改：OllamaConfig 增加 embed_provider 属性 |
| `scripts/lib/llm/factory.py` | 修改：get_embedding_config 从配置读取 provider |
| `scripts/lib/rag_engine/llamaindex_adapter.py` | 修改：新增 JinaEmbeddingAdapter，更新工厂函数 |
| `scripts/tests/utils/rag_fixtures.py` | 修改：更新模型名 |
| `scripts/tests/lib/rag_engine/test_qa_engine.py` | 修改：更新模型名 |
| `scripts/tests/lib/rag_engine/test_resource_cleanup.py` | 修改：更新模型名 |
| `scripts/tests/integration/test_rag_integration.py` | 修改：更新模型名 |
