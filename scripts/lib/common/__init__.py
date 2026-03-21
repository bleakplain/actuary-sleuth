# scripts/lib/common/__init__.py

from .models import (
    RegulationStatus,
    RegulationLevel,
    RegulationRecord,
    RegulationProcessingOutcome,
    RegulationDocument,
    ProductCategory,
    Product,
    Coverage,
    Premium,
    AuditRequest,
)
from .audit import (
    PreprocessedResult,
    CheckedResult,
    AnalyzedResult,
    EvaluationResult,
)
from .result import ProcessResult
from .database import get_connection
from .logger import get_logger, get_audit_logger, AuditLogger, AuditStepLogger
from .id_generator import IDGenerator
from .exceptions import (
    ActuarySleuthException,
    ValidationException,
    MissingParameterException,
    InvalidParameterException,
    ProcessingException,
    DatabaseException,
    RecordNotFoundError,
)
from .product_type import from_code, get_category, get_name
from .constants import (
    DocumentValidation,
    AuditConstants,
    ScoringConstants,
    ViolationConstants,
    PreprocessingConstants,
)
from .cache import CacheManager, cached
from .logging_config import setup_logging, StructuredFormatter
from .date_utils import get_current_timestamp
from .middleware import Middleware, LoggingMiddleware, PerformanceMiddleware, MiddlewareChain

__all__ = [
    # Models
    'RegulationStatus',
    'RegulationLevel',
    'RegulationRecord',
    'RegulationProcessingOutcome',
    'RegulationDocument',
    'ProductCategory',
    'Product',
    'Coverage',
    'Premium',
    'AuditRequest',
    # Audit flow models
    'PreprocessedResult',
    'CheckedResult',
    'AnalyzedResult',
    'EvaluationResult',
    # Result
    'ProcessResult',
    # Database
    'get_connection',
    # Logger
    'get_logger',
    'get_audit_logger',
    'AuditLogger',
    'AuditStepLogger',
    # ID Generator
    'IDGenerator',
    # Exceptions
    'ActuarySleuthException',
    'ValidationException',
    'MissingParameterException',
    'InvalidParameterException',
    'ProcessingException',
    'DatabaseException',
    'RecordNotFoundError',
    # Product type
    'from_code',
    'get_category',
    'get_name',
    # Constants
    'DocumentValidation',
    'AuditConstants',
    'ScoringConstants',
    'ViolationConstants',
    'PreprocessingConstants',
    # Cache
    'CacheManager',
    'cached',
    # Logging
    'setup_logging',
    'StructuredFormatter',
    # Date utils
    'get_current_timestamp',
    # Middleware
    'Middleware',
    'LoggingMiddleware',
    'PerformanceMiddleware',
    'MiddlewareChain',
]
