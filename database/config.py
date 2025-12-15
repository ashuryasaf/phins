"""
Database Configuration for PHINS

Supports both SQLite (development) and PostgreSQL (production).
Configuration is determined by environment variables.
"""

import os
from typing import Dict, Any


class DatabaseConfig:
    """Database configuration with environment-based settings"""
    
    # Environment variable names
    ENV_DATABASE_URL = "DATABASE_URL"
    ENV_DB_HOST = "DB_HOST"
    ENV_DB_PORT = "DB_PORT"
    ENV_DB_NAME = "DB_NAME"
    ENV_DB_USER = "DB_USER"
    ENV_DB_PASSWORD = "DB_PASSWORD"
    ENV_USE_SQLITE = "USE_SQLITE"
    
    # Default SQLite settings (for development)
    DEFAULT_SQLITE_PATH = "phins.db"
    
    # Connection pool settings
    POOL_SIZE = 20
    MAX_OVERFLOW = 10
    POOL_TIMEOUT = 30
    POOL_RECYCLE = 3600  # 1 hour
    
    # Query settings
    # WARNING: ECHO_SQL logs all SQL queries including sensitive data like passwords
    # Only enable for debugging in development environments, NEVER in production
    ECHO_SQL = False  # Set to True to log all SQL queries (SECURITY RISK in production)
    
    @classmethod
    def get_database_url(cls) -> str:
        """
        Get database URL from environment variables.
        
        Priority:
        1. DATABASE_URL (full connection string)
        2. Individual DB_* environment variables
        3. SQLite (development fallback)
        """
        # Check for full database URL (Railway, Heroku style)
        database_url = os.environ.get(cls.ENV_DATABASE_URL)
        if database_url:
            # Railway provides postgres:// but SQLAlchemy needs postgresql://
            if database_url.startswith('postgres://'):
                database_url = database_url.replace('postgres://', 'postgresql://', 1)
            return database_url
        
        # Check if explicitly set to use SQLite
        use_sqlite = os.environ.get(cls.ENV_USE_SQLITE, '').lower() in ('true', '1', 'yes')
        if use_sqlite:
            return cls.get_sqlite_url()
        
        # Check for individual PostgreSQL variables
        db_host = os.environ.get(cls.ENV_DB_HOST)
        if db_host:
            db_port = os.environ.get(cls.ENV_DB_PORT, '5432')
            db_name = os.environ.get(cls.ENV_DB_NAME, 'phins')
            db_user = os.environ.get(cls.ENV_DB_USER, 'postgres')
            db_password = os.environ.get(cls.ENV_DB_PASSWORD, '')
            
            return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        
        # Default to SQLite for local development
        return cls.get_sqlite_url()
    
    @classmethod
    def get_sqlite_url(cls) -> str:
        """Get SQLite database URL"""
        sqlite_path = os.environ.get('SQLITE_PATH', cls.DEFAULT_SQLITE_PATH)
        return f"sqlite:///{sqlite_path}"
    
    @classmethod
    def is_postgresql(cls) -> bool:
        """Check if using PostgreSQL"""
        return cls.get_database_url().startswith('postgresql://')
    
    @classmethod
    def is_sqlite(cls) -> bool:
        """Check if using SQLite"""
        return cls.get_database_url().startswith('sqlite:///')
    
    @classmethod
    def get_engine_options(cls) -> Dict[str, Any]:
        """Get SQLAlchemy engine options"""
        options: Dict[str, Any] = {
            'echo': cls.ECHO_SQL,
            'pool_pre_ping': True,  # Verify connections before using
        }
        
        if cls.is_postgresql():
            # PostgreSQL-specific options
            options.update({
                'pool_size': cls.POOL_SIZE,
                'max_overflow': cls.MAX_OVERFLOW,
                'pool_timeout': cls.POOL_TIMEOUT,
                'pool_recycle': cls.POOL_RECYCLE,
            })
        else:
            # SQLite-specific options
            options.update({
                'connect_args': {'check_same_thread': False}  # Allow multi-threaded access
            })
        
        return options
    
    @classmethod
    def get_config_summary(cls) -> Dict[str, Any]:
        """Get configuration summary for diagnostics"""
        db_url = cls.get_database_url()
        # Mask password in URL for security
        if '@' in db_url:
            parts = db_url.split('@')
            user_pass = parts[0].split('://')[-1]
            if ':' in user_pass:
                user = user_pass.split(':')[0]
                masked_url = db_url.replace(user_pass, f"{user}:****")
            else:
                masked_url = db_url
        else:
            masked_url = db_url
        
        return {
            'database_type': 'PostgreSQL' if cls.is_postgresql() else 'SQLite',
            'database_url': masked_url,
            'pool_size': cls.POOL_SIZE if cls.is_postgresql() else 'N/A',
            'max_overflow': cls.MAX_OVERFLOW if cls.is_postgresql() else 'N/A',
            'echo_sql': cls.ECHO_SQL
        }


# Export
__all__ = ['DatabaseConfig']
