#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG 引擎异常定义"""

from lib.common.exceptions import ActuarySleuthException


class RAGEngineError(ActuarySleuthException):
    """RAG 引擎基础异常"""
    pass


class EngineInitializationError(RAGEngineError):
    """引擎初始化失败"""
    pass


class RetrievalError(RAGEngineError):
    """检索失败"""
    pass
