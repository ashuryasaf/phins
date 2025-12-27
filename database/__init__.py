"""
Database Initialization and Connection Management

This module provides database session management, connection pooling,
and initialization functions for the PHINS platform.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.pool import Pool
from typing import Optional
import logging
import os

from .config import DatabaseConfig
from .models import Base

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global engine and session factory
_engine = None
_session_factory = None


def get_engine():
    """Get or create the SQLAlchemy engine"""
    global _engine
    if _engine is None:
        database_url = DatabaseConfig.get_database_url()
        engine_options = DatabaseConfig.get_engine_options()
        
        logger.info(f"Initializing database: {DatabaseConfig.get_config_summary()['database_type']}")
        
        _engine = create_engine(database_url, **engine_options)
        
        # Add event listeners for connection pool monitoring
        @event.listens_for(Pool, "connect")
        def receive_connect(dbapi_conn, connection_record):
            logger.debug("Database connection established")
        
        @event.listens_for(Pool, "checkout")
        def receive_checkout(dbapi_conn, connection_record, connection_proxy):
            logger.debug("Database connection checked out from pool")
    
    return _engine


def get_session_factory():
    """Get or create the session factory"""
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = scoped_session(
            sessionmaker(
                bind=engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False
            )
        )
    return _session_factory


def get_db_session() -> Session:
    """
    Get a database session.
    
    This should be used in a context manager or try/finally block:
    
    session = get_db_session()
    try:
        # Use session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    """
    session_factory = get_session_factory()
    return session_factory()


def init_database(drop_existing: bool = False):
    """
    Initialize the database schema.
    
    Args:
        drop_existing: If True, drop all existing tables before creating (USE WITH CAUTION)
    """
    # In test runs we want deterministic behavior (no state leaking between tests)
    # even when using a file-backed SQLite DB.
    if os.environ.get("PYTEST_CURRENT_TEST") and not drop_existing:
        drop_existing = True
    engine = get_engine()
    
    if drop_existing:
        logger.warning("Dropping all existing database tables!")
        Base.metadata.drop_all(engine)
    
    logger.info("Creating database tables...")
    Base.metadata.create_all(engine)
    logger.info("Database tables created successfully")


def close_database():
    """Close database connections and clean up resources"""
    global _engine, _session_factory
    
    if _session_factory:
        _session_factory.remove()
        _session_factory = None
        logger.info("Database session factory closed")
    
    if _engine:
        _engine.dispose()
        _engine = None
        logger.info("Database engine disposed")


def check_database_connection() -> bool:
    """
    Check if database connection is working.
    
    Returns:
        True if connection is successful, False otherwise
    """
    try:
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection check: OK")
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False


def get_database_info() -> dict:
    """Get information about the current database configuration"""
    config_summary = DatabaseConfig.get_config_summary()
    
    try:
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            connection_ok = result.fetchone() is not None
    except Exception as e:
        connection_ok = False
    
    return {
        **config_summary,
        'connection_ok': connection_ok,
        'engine_initialized': _engine is not None,
        'session_factory_initialized': _session_factory is not None
    }


# Export public interface
__all__ = [
    'get_engine',
    'get_session_factory',
    'get_db_session',
    'init_database',
    'close_database',
    'check_database_connection',
    'get_database_info',
    'Base'
]
