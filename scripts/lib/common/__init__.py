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
from .database import get_connection
from .logger import get_logger, get_audit_logger, AuditLogger, AuditStepLogger
from .exceptions import (
    ActuarySleuthException,
    ValidationException,
    MissingParameterException,
    InvalidParameterException,
    ProcessingException,
    DatabaseException,
    RecordNotFoundError,
)
from .product import from_code, get_category, get_name, map_to_scoring_type, ScoringType
from .constants import (
    DocumentValidation,
    AuditConstants,
    ScoringConstants,
    ViolationConstants,
    PreprocessingConstants,
)
from .cache import CacheManager, get_cache_manager, reset_cache_manager
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
    # Database
    'get_connection',
    # Logger
    'get_logger',
    'get_audit_logger',
    'AuditLogger',
    'AuditStepLogger',
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
    'map_to_scoring_type',
    'ScoringType',
    # Constants
    'DocumentValidation',
    'AuditConstants',
    'ScoringConstants',
    'ViolationConstants',
    'PreprocessingConstants',
    # Cache
    'CacheManager',
    'get_cache_manager',
    'reset_cache_manager',
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
