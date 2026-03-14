#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公共数据模型

预处理、审核、RAG 等模块共享的数据结构。
从 preprocessing.models 导入，保持单一数据源。
"""

# 从预处理模块导入共享模型
# 注意：这里使用相对导入避免循环依赖
import sys
from pathlib import Path

# 添加 scripts 目录到路径以便导入
scripts_dir = Path(__file__).parent.parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from lib.preprocessing.models import (
    RegulationStatus,
    RegulationLevel,
    RegulationRecord,
    RegulationProcessingOutcome,
    RegulationDocument,
)

__all__ = [
    'RegulationStatus',
    'RegulationLevel',
    'RegulationRecord',
    'RegulationProcessingOutcome',
    'RegulationDocument',
]
