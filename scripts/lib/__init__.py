#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Infrastructure package init
"""
from .common.database import get_connection
from .config import get_config
from .common.id_generator import IDGenerator
from .common.exceptions import *
from .common.logger import AuditLogger, AuditStepLogger, get_logger, get_audit_logger

# VectorDB - 延迟导入以避免依赖问题
try:
    from .rag_engine.vector_store import VectorDB
except ImportError:
    VectorDB = None

__all__ = [
    'get_connection',
    'get_config',
    'IDGenerator',
    # Exceptions
    'ActuarySleuthException',
    'ValidationException',
    'MissingParameterException',
    'InvalidParameterException',
    'ProcessingException',
    'DocumentPreprocessException',
    'NegativeListCheckException',
    'PricingAnalysisException',
    'ReportGenerationException',
    'AuditStepException',
    'DatabaseException',
    'DataNotFoundException',
    'ExternalServiceException',
    'FeishuAPIException',
    'OllamaException',
    'ConfigurationException',
    # Logger
    'AuditLogger',
    'AuditStepLogger',
    'get_logger',
    'get_audit_logger',
]
