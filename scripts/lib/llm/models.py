#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 模型名称常量
"""
from enum import Enum


class ModelName(str, Enum):
    """模型名称常量"""
    GLM_4_FLASH = "glm-4-flash"
    GLM_4_PLUS = "glm-4-plus"
    GLM_Z1_AIR = "glm-z1-air"
    GLM_4_AIR = "glm-4-air"
    EMBEDDING_3 = "embedding-3"
    NOMIC_EMBED_TEXT = "nomic-embed-text"
