"""记忆系统模块。"""
from __future__ import annotations

import os
from pathlib import Path

from lib.config import get_memory_dir

# 在导入 mem0 前设置 MEM0_DIR
# 每个 worktree 使用不同的 DATA_PATHS_MEMORY_DIR 配置
# Telemetry 会在此目录下创建 migrations_qdrant/ 子目录，与主 Qdrant (qdrant/) 目录隔离
_memory_dir = Path(get_memory_dir())
_memory_dir.mkdir(parents=True, exist_ok=True)
os.environ["MEM0_DIR"] = str(_memory_dir)
