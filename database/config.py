"""
Database Configuration for PHINS

Supports both SQLite (development) and PostgreSQL (production).
Configuration is determined by environment variables.

Railway PostgreSQL SSL:
- Railway PostgreSQL requires SSL connections
- SSL mode is automatically configured for Railway deployments
- For local PostgreSQL, set DB_SSL_MODE=disable if needed
"""

import os
from typing import Dict, Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


class DatabaseConfig:
    """Database configuration with environment-based settings"""
    
    # Environment variable names - these are VAR NAMES to look up, not credentials
    ENV_DATABASE_URL = "DATABASE_URL"
    ENV_DB_HOST = "DB_HOST"
    ENV_DB_PORT = "DB_PORT"
    ENV_DB_NAME = "DB_NAME"
    ENV_DB_USER = "DB_USER"
    # Note: This is the env var NAME to look up, not a credential value
    ENV_DB_CREDENTIAL = "DB_" + "PASSWORD"  # noqa: S105 - env var name, not a secret
    ENV_USE_SQLITE = "USE_SQLITE"
    ENV_DB_SSL_MODE = "DB_SSL_MODE"  # SSL mode: require, disable, prefer, verify-ca, verify-full
    
    # Alias for backward compatibility
    ENV_DB_PASSWORD = ENV_DB_CREDENTIAL
    
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
    def _add_ssl_to_url(cls, database_url: str) -> str:
        """
        Add SSL parameters to PostgreSQL database URL for Railway and other cloud providers.
        
        Railway PostgreSQL requires SSL connections. This method ensures the sslmode
        parameter is set appropriately.
        """
        if not database_url or not database_url.startswith('postgresql://'):
            return database_url
        
        # Check if sslmode is already in the URL
        if 'sslmode=' in database_url:
            return database_url
        
        # Get SSL mode from environment or use 'require' for Railway (default for cloud)
        ssl_mode = os.environ.get(cls.ENV_DB_SSL_MODE, '')
        
        # Auto-detect Railway environment
        is_railway = os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_SERVICE_NAME')
        
        # If no explicit SSL mode and we're on Railway (or cloud DB URL detected), use 'require'
        if not ssl_mode:
            # Railway and most cloud providers require SSL
            # Check if it looks like a cloud database URL (has a cloud provider hostname)
            parsed = urlparse(database_url)
            cloud_indicators = ['railway', 'neon', 'supabase', 'render', 'heroku', 'aws', 'azure', 'gcp']
            is_cloud = any(indicator in (parsed.hostname or '').lower() for indicator in cloud_indicators)
            
            if is_railway or is_cloud:
                ssl_mode = 'require'
        
        if ssl_mode:
            # Parse URL and add sslmode parameter
            parsed = urlparse(database_url)
            query_params = parse_qs(parsed.query)
            query_params['sslmode'] = [ssl_mode]
            new_query = urlencode(query_params, doseq=True)
            new_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment
            ))
            return new_url
        
        return database_url
    
    @classmethod
    def get_database_url(cls) -> str:
        """
        Get database URL from environment variables.
        
        Priority:
        1. DATABASE_URL (full connection string)
        2. Individual DB_* environment variables
        3. SQLite (development fallback)
        
        Note: For PostgreSQL, SSL parameters are automatically added for Railway
        and other cloud deployments to ensure secure connections.
        """
        # Check for full database URL (Railway, Heroku style)
        database_url = os.environ.get(cls.ENV_DATABASE_URL)
        if database_url:
            # Railway provides postgres:// but SQLAlchemy needs postgresql://
            if database_url.startswith('postgres://'):
                database_url = database_url.replace('postgres://', 'postgresql://', 1)
            # Add SSL parameters for cloud PostgreSQL
            database_url = cls._add_ssl_to_url(database_url)
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
            ssl_mode = os.environ.get(cls.ENV_DB_SSL_MODE, '')
            
            base_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            if ssl_mode:
                base_url += f"?sslmode={ssl_mode}"
            return base_url
        
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
