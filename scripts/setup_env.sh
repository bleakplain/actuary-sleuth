#!/bin/bash
# Actuary Sleuth 运行环境配置脚本
# 用法: bash scripts/setup_env.sh

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RERANKER_DIR="$ROOT_DIR/lib/rag_engine/models/reranker"
TOOLS_DIR="$ROOT_DIR/lib/rag_engine/tools"

echo "=== Actuary Sleuth 环境配置 ==="
echo ""

# ---- 1. Ollama ----
echo "[1/3] 检查 Ollama ..."
if ! command -v ollama &>/dev/null; then
    echo "  Ollama 未安装，正在安装 ..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "  Ollama 已安装: $(ollama --version)"
fi

OLLAMA_MODEL="jinaai/jina-embeddings-v5-text-small"
if ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
    echo "  $OLLAMA_MODEL 已存在"
else
    echo "  拉取 embedding 模型: $OLLAMA_MODEL"
    ollama pull "$OLLAMA_MODEL"
fi

echo ""

# ---- 2. Reranker (jina-reranker-v3 GGUF) ----
echo "[2/3] 配置 Reranker ..."

mkdir -p "$RERANKER_DIR"

# 下载 GGUF 模型和投影层权重
GGUF_FILE="$RERANKER_DIR/jina-reranker-v3-Q4_K_M.gguf"
if [ ! -f "$GGUF_FILE" ]; then
    echo "  下载 jina-reranker-v3-Q4_K_M.gguf ..."
    wget -q --show-progress -O "$GGUF_FILE" \
        "https://huggingface.co/jinaai/jina-reranker-v3-GGUF/resolve/main/jina-reranker-v3-Q4_K_M.gguf"
else
    echo "  jina-reranker-v3-Q4_K_M.gguf 已存在"
fi

PROJECTOR_FILE="$RERANKER_DIR/projector.safetensors"
if [ ! -f "$PROJECTOR_FILE" ]; then
    echo "  下载 projector.safetensors ..."
    wget -q --show-progress -O "$PROJECTOR_FILE" \
        "https://huggingface.co/jinaai/jina-reranker-v3-GGUF/resolve/main/projector.safetensors"
else
    echo "  projector.safetensors 已存在"
fi

# 编译 Hanxiao 的 llama.cpp fork
LLAMA_DIR="$TOOLS_DIR/hanxiao-llama.cpp"
LLAMA_BIN="$LLAMA_DIR/build/bin/llama-embedding"
if [ ! -f "$LLAMA_BIN" ]; then
    echo "  克隆并编译 hanxiao/llama.cpp ..."
    mkdir -p "$TOOLS_DIR"
    if [ ! -d "$LLAMA_DIR" ]; then
        git clone --depth 1 https://github.com/hanxiao/llama.cpp.git "$LLAMA_DIR"
    fi
    cd "$LLAMA_DIR"
    cmake -B build -DGGML_CUDA=OFF
    cmake --build build --config Release -j"$(nproc)"
    cd "$ROOT_DIR"
else
    echo "  llama-embedding 已编译"
fi

echo ""
echo "=== 配置完成 ==="
