"""
PHINS Global Configuration Module
Settings for deployment, performance, and features
Lightweight and simple for millions of users
"""

from enum import Enum
from typing import Dict, Any
from i18n import Language


class Environment(Enum):
    """Deployment environments"""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class PHINSConfig:
    """Global PHINS configuration"""
    
    # ========== Environment ==========
    ENVIRONMENT = Environment.PRODUCTION
    DEBUG = False
    
    # ========== Application ==========
    APP_NAME = "PHINS Insurance Management"
    APP_VERSION = "2.0.0"
    PUBLISHER_ID = "PHI"
    DOMAIN = "www.phins.ai"
    BASE_URL = "https://www.phins.ai"
    
    # ========== Internationalization ==========
    DEFAULT_LANGUAGE = Language.EN
    SUPPORTED_LANGUAGES = [
        Language.EN, Language.ZH, Language.HI, Language.ES, Language.FR,
        Language.AR, Language.PT, Language.RU, Language.JA, Language.DE,
        Language.IT, Language.KO, Language.TR, Language.VI, Language.NL,
        Language.PL, Language.SV, Language.EL, Language.HE, Language.ID
    ]
    
    # ========== Performance & Scalability ==========
    # Max records per page for list views
    PAGE_SIZE = 50
    MAX_PAGE_SIZE = 1000
    
    # Connection pooling
    DATABASE_POOL_SIZE = 20
    DATABASE_MAX_OVERFLOW = 10
    
    # Caching
    ENABLE_CACHE = True
    CACHE_TTL_SECONDS = 3600  # 1 hour
    CACHE_MAX_SIZE = 10000  # Max items in cache
    
    # Query optimization
    ENABLE_LAZY_LOADING = True
    BATCH_OPERATION_SIZE = 100  # Batch inserts/updates
    
    # ========== API Settings ==========
    API_RATE_LIMIT = 1000  # Requests per hour per user
    API_TIMEOUT_SECONDS = 30
    API_MAX_BATCH_SIZE = 100
    
    # ========== File Management ==========
    MAX_FILE_SIZE_MB = 100
    MAX_TOTAL_STORAGE_GB = 10000
    ALLOWED_FILE_TYPES = [
        "pdf", "doc", "docx", "xls", "xlsx",
        "jpg", "jpeg", "png", "gif", "tiff",
        "txt", "csv", "zip"
    ]
    
    # ========== Reporting ==========
    MAX_REPORT_ROWS = 1000000
    REPORT_EXPORT_FORMATS = ["csv", "excel", "json", "pdf"]
    
    # ========== Security ==========
    ENABLE_AUDIT_LOG = True
    ENABLE_ENCRYPTION = True
    SESSION_TIMEOUT_MINUTES = 60
    MAX_LOGIN_ATTEMPTS = 5
    
    # ========== Feature Flags ==========
    FEATURES = {
        "file_management": True,
        "multi_language": True,
        "actuarial": True,
        "risk_management": True,
        "reinsurance": True,
        "customer_portal": True,
        "api": True,
        "reporting": True,
        "audit_logging": True,
    }
    
    # ========== Division Configuration ==========
    ACTIVE_DIVISIONS = [
        "Sales",
        "Underwriting",
        "Claims",
        "Accounting",
        "Actuarial",
        "Risk Management",
        "Reinsurance",
        "Legal",
        "Customer Portal"
    ]
    
    # ========== Email Configuration ==========
    ENABLE_EMAIL_NOTIFICATIONS = True
    SMTP_HOST = "localhost"
    SMTP_PORT = 587
    SMTP_USE_TLS = True
    EMAIL_FROM_ADDRESS = "noreply@phins.ai"
    
    # ========== SMS Configuration ==========
    ENABLE_SMS_NOTIFICATIONS = False
    SMS_PROVIDER = "twilio"  # or "aws-sns", "firebase"
    
    # ========== Data Retention ==========
    ARCHIVE_INACTIVE_RECORDS_DAYS = 365
    DELETE_ARCHIVED_RECORDS_DAYS = 2555  # 7 years for compliance
    
    # ========== Logging ==========
    LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_FORMAT = "json"  # json or text
    LOG_RETENTION_DAYS = 90
    
    # ========== Monitoring ==========
    ENABLE_METRICS = True
    METRICS_EXPORT_INTERVAL_SECONDS = 60
    HEALTH_CHECK_INTERVAL_SECONDS = 30
    
    @classmethod
    def get_config_summary(cls) -> Dict[str, Any]:
        """Get configuration summary for diagnostics"""
        return {
            "app_name": cls.APP_NAME,
            "app_version": cls.APP_VERSION,
            "environment": cls.ENVIRONMENT.value,
            "debug": cls.DEBUG,
            "default_language": cls.DEFAULT_LANGUAGE.value,
            "supported_languages": len(cls.SUPPORTED_LANGUAGES),
            "page_size": cls.PAGE_SIZE,
            "cache_enabled": cls.ENABLE_CACHE,
            "features_enabled": sum(1 for v in cls.FEATURES.values() if v),
            "total_features": len(cls.FEATURES),
            "active_divisions": len(cls.ACTIVE_DIVISIONS),
        }
    
    @classmethod
    def is_feature_enabled(cls, feature_name: str) -> bool:
        """Check if a feature is enabled"""
        return cls.FEATURES.get(feature_name, False)
    
    @classmethod
    def get_enabled_features(cls) -> list:
        """Get list of enabled features"""
        return [k for k, v in cls.FEATURES.items() if v]


class PerformanceOptimizations:
    """Performance tuning for high-volume scenarios"""
    
    # Query optimization
    USE_INDEXED_QUERIES = True
    ENABLE_QUERY_CACHING = True
    QUERY_TIMEOUT_MS = 5000
    
    # Memory management
    USE_GENERATOR_PATTERNS = True  # For large result sets
    ENABLE_GARBAGE_COLLECTION = True
    GC_INTERVAL_SECONDS = 60
    
    # Connection pooling
    CONNECTION_POOL_RECYCLE_SECONDS = 3600
    CONNECTION_IDLE_TIMEOUT_SECONDS = 900
    
    # Async operations for high-latency tasks
    ENABLE_ASYNC = True
    ASYNC_QUEUE_SIZE = 10000
    ASYNC_WORKER_THREADS = 10
    
    @classmethod
    def get_optimization_profile(cls, expected_users: int) -> Dict[str, Any]:
        """Get performance tuning profile based on expected users"""
        if expected_users < 1000:
            return {
                "page_size": 50,
                "cache_enabled": False,
                "connection_pool_size": 5,
                "worker_threads": 2,
            }
        elif expected_users < 100000:
            return {
                "page_size": 100,
                "cache_enabled": True,
                "cache_ttl": 600,
                "connection_pool_size": 20,
                "worker_threads": 5,
            }
        else:  # 1M+ users
            return {
                "page_size": 200,
                "cache_enabled": True,
                "cache_ttl": 1800,
                "connection_pool_size": 100,
                "worker_threads": 50,
                "use_redis_cache": True,
                "use_database_sharding": True,
                "enable_cdn": True,
            }


class DataValidation:
    """Lightweight data validation rules"""
    
    # Email validation (simple regex)
    EMAIL_PATTERN = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    # Phone validation (E.164 format)
    PHONE_PATTERN = r'^\+?1?\d{9,15}$'
    
    # Field length limits
    LIMITS = {
        "name": 255,
        "email": 255,
        "phone": 20,
        "address": 500,
        "description": 2000,
        "id": 50,
        "policy_number": 50,
        "customer_id": 50,
    }
    
    # Premium limits
    MIN_PREMIUM = 10.00
    MAX_PREMIUM = 1000000.00
    
    # Coverage limits
    MIN_COVERAGE = 1000.00
    MAX_COVERAGE = 10000000.00
    
    @classmethod
    def validate_field_length(cls, field_name: str, value: str) -> bool:
        """Validate field doesn't exceed max length"""
        max_length = cls.LIMITS.get(field_name, 255)
        return len(value) <= max_length
    
    @classmethod
    def validate_email(cls, email: str) -> bool:
        """Basic email validation"""
        import re
        return re.match(cls.EMAIL_PATTERN, email) is not None
    
    @classmethod
    def validate_phone(cls, phone: str) -> bool:
        """Basic phone validation"""
        import re
        return re.match(cls.PHONE_PATTERN, phone) is not None


class CacheStrategy:
    """Cache strategy for scalability"""
    
    # Cache keys
    CACHE_KEYS = {
        "company": "company:{company_id}",
        "customer": "customer:{customer_id}",
        "policy": "policy:{policy_id}",
        "claims": "claims:{claim_id}",
        "health_table": "health_table:{table_id}",
        "pricing_model": "pricing_model:{model_id}",
        "user_settings": "user:{user_id}:settings",
        "translations": "translations:{language}",
    }
    
    # Cache TTL (seconds) by data type
    TTL = {
        "static": 86400,      # 1 day - health tables, lookup tables
        "config": 3600,       # 1 hour - configuration
        "user": 1800,         # 30 minutes - user data
        "report": 300,        # 5 minutes - reports
        "temporary": 60,      # 1 minute - temporary data
    }
    
    @classmethod
    def get_cache_key(cls, key_template: str, **params) -> str:
        """Generate cache key from template"""
        return key_template.format(**params)
    
    @classmethod
    def should_cache(cls, data_type: str) -> bool:
        """Determine if data type should be cached"""
        return cls.TTL.get(data_type, 0) > 0


# Export key classes
__all__ = [
    'Environment',
    'PHINSConfig',
    'PerformanceOptimizations',
    'DataValidation',
    'CacheStrategy',
]
