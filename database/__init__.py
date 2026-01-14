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
    # In pytest/CI we want deterministic, isolated DB state.
    # Many tests call init_database() multiple times and reuse the same SQLITE_PATH.
    try:
        phins_test_mode = str(os.environ.get('PHINS_TEST_MODE', '')).lower() in ('1', 'true', 'yes', 'y')
        if (not drop_existing) and phins_test_mode and DatabaseConfig.is_sqlite():
            sqlite_path = os.environ.get('SQLITE_PATH', '')
            if sqlite_path.startswith('/tmp/'):
                drop_existing = True
    except Exception:
        pass

    engine = get_engine()
    
    if drop_existing:
        logger.warning("Dropping all existing database tables!")
        Base.metadata.drop_all(engine)
    
    logger.info("Creating database tables...")
    Base.metadata.create_all(engine)
    logger.info("Database tables created successfully")
    
    # Upgrade schema to add any new columns
    upgrade_schema(engine)


def upgrade_schema(engine=None):
    """
    Add missing columns to existing tables.
    This handles schema migrations for new columns added to models.
    """
    if engine is None:
        engine = get_engine()
    
    from sqlalchemy import inspect, text
    
    inspector = inspect(engine)
    
    # Define new columns to add (table_name, column_name, column_type, default)
    new_columns = [
        # Claim extended fields
        ('claims', 'incident_date', 'VARCHAR(50)', None),
        ('claims', 'provider', 'VARCHAR(200)', None),
        ('claims', 'payment_destination', 'VARCHAR(50)', "'health_wallet'"),
        ('claims', 'bank_details', 'TEXT', None),
        ('claims', 'files_metadata', 'TEXT', None),
        ('claims', 'files_count', 'INTEGER', '0'),
        ('claims', 'nft_token_id', 'VARCHAR(100)', None),
        ('claims', 'ledger_tx_id', 'VARCHAR(100)', None),
        ('claims', 'approved_by', 'VARCHAR(100)', None),
        ('claims', 'approval_notes', 'TEXT', None),
        ('claims', 'rejected_by', 'VARCHAR(100)', None),
        ('claims', 'processed_by', 'VARCHAR(100)', None),
        ('claims', 'payment_method', 'VARCHAR(50)', None),
        ('claims', 'payment_reference', 'VARCHAR(100)', None),
        ('claims', 'paid_amount', 'FLOAT', None),
    ]
    
    with engine.connect() as conn:
        for table_name, column_name, column_type, default in new_columns:
            # Check if table exists
            if table_name not in inspector.get_table_names():
                continue
                
            # Check if column already exists
            columns = [col['name'] for col in inspector.get_columns(table_name)]
            if column_name in columns:
                continue
            
            # Add the new column
            try:
                default_clause = f" DEFAULT {default}" if default else ""
                sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}{default_clause}"
                conn.execute(text(sql))
                conn.commit()
                logger.info(f"Added column {column_name} to {table_name}")
            except Exception as e:
                logger.warning(f"Could not add column {column_name} to {table_name}: {e}")


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


def check_database_connection(timeout: int = 10) -> bool:
    """
    Check if database connection is working.
    
    Args:
        timeout: Maximum seconds to wait for connection check
    
    Returns:
        True if connection is successful, False otherwise
    """
    import threading
    import queue
    
    result_queue: queue.Queue[bool] = queue.Queue()
    
    def _check():
        try:
            from sqlalchemy import text
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            result_queue.put(True)
        except Exception as e:
            logger.error(f"Database connection check failed: {e}")
            result_queue.put(False)
    
    # Run check in a thread with timeout
    check_thread = threading.Thread(target=_check, daemon=True)
    check_thread.start()
    
    try:
        result = result_queue.get(timeout=timeout)
        if result:
            logger.info("Database connection check: OK")
        return result
    except queue.Empty:
        logger.error(f"Database connection check timed out after {timeout}s")
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
    'upgrade_schema',
    'close_database',
    'check_database_connection',
    'get_database_info',
    'Base'
]
