#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Infrastructure package init
"""
from .database import get_connection
from .config import get_config
from .id_generator import IDGenerator
from .exceptions import *
from .logger import AuditLogger, AuditStepLogger, get_logger, get_audit_logger
from .ollama import OllamaClient
from .vector_store import VectorDB

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
    # AI & Vector Store
    'OllamaClient',
    'VectorDB'
]