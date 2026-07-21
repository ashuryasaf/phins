"""
Database Initialization and Connection Management

This module provides database session management, connection pooling,
and initialization functions for the PHINS platform.

IMPORTANT: This module includes automatic connection recovery for production
reliability. When database connections fail, it will attempt to reconnect
automatically with exponential backoff.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.pool import Pool
from sqlalchemy.exc import OperationalError, DatabaseError, DisconnectionError
from typing import Optional
import logging
import os
import time
import threading
import tempfile

from .config import DatabaseConfig
from .models import Base
# Register marketplace foundation tables on the shared metadata so that
# `Base.metadata.create_all` includes them. The import is intentionally
# side-effect only.
from . import marketplace_models  # noqa: F401

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global engine and session factory
_engine = None
_session_factory = None
_connection_lock = threading.Lock()
_last_connection_check = 0
_connection_check_interval = 30  # seconds between health checks


def reset_connection():
    """
    Reset database connection by disposing engine and clearing session factory.
    This is used when connection errors occur to force a fresh reconnection.
    
    Thread-safe using global lock.
    """
    global _engine, _session_factory
    
    with _connection_lock:
        logger.warning("Resetting database connection...")
        
        if _session_factory:
            try:
                _session_factory.remove()
            except Exception as e:
                logger.debug(f"Session factory removal error (non-critical): {e}")
            _session_factory = None
        
        if _engine:
            try:
                _engine.dispose()
            except Exception as e:
                logger.debug(f"Engine disposal error (non-critical): {e}")
            _engine = None
        
        logger.info("Database connection reset complete")


def get_engine(force_new: bool = False):
    """
    Get or create the SQLAlchemy engine.
    
    Args:
        force_new: If True, force creation of a new engine even if one exists.
    
    Returns:
        SQLAlchemy engine instance
    """
    global _engine
    
    if force_new:
        reset_connection()
    
    if _engine is None:
        with _connection_lock:
            # Double-check after acquiring lock
            if _engine is None:
                database_url = DatabaseConfig.get_database_url()
                engine_options = DatabaseConfig.get_engine_options()
                
                logger.info(f"Initializing database: {DatabaseConfig.get_config_summary()['database_type']}")
                
                _engine = create_engine(database_url, **engine_options)
                
                # Add event listeners for connection pool monitoring
                @event.listens_for(_engine, "connect")
                def receive_connect(dbapi_conn, connection_record):
                    logger.debug("Database connection established")
                
                @event.listens_for(_engine, "checkout")
                def receive_checkout(dbapi_conn, connection_record, connection_proxy):
                    logger.debug("Database connection checked out from pool")
                
                # Handle invalidation events (connection errors)
                @event.listens_for(_engine, "invalidate")
                def receive_invalidate(dbapi_conn, connection_record, exception):
                    logger.warning(f"Database connection invalidated: {exception}")
    
    return _engine


def get_session_factory(force_new: bool = False):
    """
    Get or create the session factory.
    
    Args:
        force_new: If True, force creation of a new session factory.
    
    Returns:
        Scoped session factory
    """
    global _session_factory
    
    if force_new:
        with _connection_lock:
            if _session_factory:
                try:
                    _session_factory.remove()
                except Exception:
                    pass
                _session_factory = None
    
    if _session_factory is None:
        with _connection_lock:
            # Double-check after acquiring lock
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


def get_db_session(max_retries: int = 3, retry_delay: float = 0.5) -> Session:
    """
    Get a database session with automatic retry on connection failures.
    
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
    
    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        retry_delay: Initial delay between retries in seconds (default: 0.5)
    
    Returns:
        Database session
    
    Raises:
        Exception: If connection fails after all retries
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            session_factory = get_session_factory()
            session = session_factory()
            
            # Test the session with a simple query to ensure connection is valid
            from sqlalchemy import text
            session.execute(text("SELECT 1"))
            
            return session
            
        except (OperationalError, DatabaseError, DisconnectionError) as e:
            last_error = e
            logger.warning(f"Database session creation failed (attempt {attempt + 1}/{max_retries}): {e}")
            
            # Reset connection and retry
            reset_connection()
            
            if attempt < max_retries - 1:
                sleep_time = retry_delay * (2 ** attempt)  # exponential backoff
                logger.info(f"Retrying in {sleep_time:.1f}s...")
                time.sleep(sleep_time)
        except Exception as e:
            # Non-connection errors - don't retry
            logger.error(f"Unexpected error getting database session: {e}")
            raise
    
    logger.error(f"Failed to get database session after {max_retries} attempts")
    raise last_error or Exception("Failed to establish database connection")


# Static migration definitions applied by ``upgrade_schema``. Kept at module
# scope so ``_schema_fingerprint`` can fold them into the skip-gate hash; their
# effects are not reflected in the ORM metadata, so changes here must still
# re-trigger the DDL sync.
# New columns to add (table_name, column_name, column_type, default).
_UPGRADE_NEW_COLUMNS = [
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
    # Supplier invitation code reference
    ('suppliers', 'invitation_code', 'VARCHAR(100)', None),
    # Supplier offer media gallery (JSON list of media items)
    ('supplier_offers', 'media', 'TEXT', None),
    # Agent ecosystem: referring agent linkage
    ('customers', 'referring_agent_id', 'VARCHAR(50)', None),
    ('suppliers', 'referring_agent_id', 'VARCHAR(50)', None),
]
# Columns whose declared type must be widened on existing databases
# (table_name, column_name, new_type).
_UPGRADE_COLUMN_WIDENING = [
    ('sessions', 'token', 'VARCHAR(512)'),
]


def _schema_fingerprint() -> str:
    """Deterministic fingerprint of the declared SQLAlchemy schema.

    Derived from every table's name and column names, so any model change
    (new table, new column, renamed column) yields a new fingerprint. It also
    folds in the ``upgrade_schema`` migration definitions (added columns and
    column widenings), whose effects are not reflected in the ORM metadata, so
    that changing those lists re-triggers the DDL sync rather than being masked
    by a matching model fingerprint. Used to skip the per-table reflection
    queries of ``create_all`` + ``upgrade_schema`` on boots where the schema is
    already in sync.
    """
    import hashlib

    parts = []
    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        columns = ",".join(sorted(column.name for column in table.columns))
        parts.append(f"{table.name}({columns})")
    parts.append("new_columns=" + ";".join(
        f"{t}.{c}:{ct}:{d}" for t, c, ct, d in _UPGRADE_NEW_COLUMNS
    ))
    parts.append("column_widening=" + ";".join(
        f"{t}.{c}:{nt}" for t, c, nt in _UPGRADE_COLUMN_WIDENING
    ))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _read_schema_marker(engine) -> Optional[str]:
    """Read the stored schema fingerprint (None when absent/unreadable)."""
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT fingerprint FROM schema_sync_state WHERE id = 1")
            ).fetchone()
            return row[0] if row else None
    except Exception:
        # Missing marker table (first boot / pre-marker database) or any
        # read failure simply means "no marker": run the full DDL sync.
        return None


def _write_schema_marker(engine, fingerprint: str) -> None:
    """Persist the schema fingerprint after a successful DDL sync."""
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS schema_sync_state ("
                "id INTEGER PRIMARY KEY, "
                "fingerprint VARCHAR(64) NOT NULL, "
                "applied_at TIMESTAMP)"
            ))
            updated = conn.execute(
                text(
                    "UPDATE schema_sync_state "
                    "SET fingerprint = :fp, applied_at = CURRENT_TIMESTAMP "
                    "WHERE id = 1"
                ),
                {"fp": fingerprint},
            )
            if updated.rowcount == 0:
                conn.execute(
                    text(
                        "INSERT INTO schema_sync_state (id, fingerprint, applied_at) "
                        "VALUES (1, :fp, CURRENT_TIMESTAMP)"
                    ),
                    {"fp": fingerprint},
                )
            conn.commit()
    except Exception as exc:
        # Non-fatal: without a marker the next boot just re-runs the
        # idempotent DDL sync.
        logger.debug(f"Could not persist schema sync marker: {exc}")


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
            if sqlite_path.startswith(f"{tempfile.gettempdir()}/"):
                drop_existing = True
    except Exception:
        pass

    engine = get_engine()

    # Fast path: when the stored schema fingerprint matches the declared
    # models, the previous successful DDL sync already created every table
    # and column — skip create_all (one reflection query per table) and
    # upgrade_schema (full table/column inspection) and boot with a single
    # SELECT instead. Any model change produces a new fingerprint and the
    # full sync runs again. PHINS_FORCE_SCHEMA_SYNC=true bypasses the marker.
    force_sync = str(os.environ.get('PHINS_FORCE_SCHEMA_SYNC', '')).lower() in ('1', 'true', 'yes', 'y')
    fingerprint = _schema_fingerprint()
    if not drop_existing and not force_sync:
        if _read_schema_marker(engine) == fingerprint:
            logger.info("Database schema up to date (fingerprint match); skipping DDL sync")
            return

    if drop_existing:
        logger.warning("Dropping all existing database tables!")
        Base.metadata.drop_all(engine)
        # The marker table is not part of Base.metadata; drop it explicitly so
        # a wiped database never reports a stale fingerprint match.
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS schema_sync_state"))
                conn.commit()
        except Exception:
            pass
    
    logger.info("Creating database tables...")
    Base.metadata.create_all(engine)
    logger.info("Database tables created successfully")
    
    # Upgrade schema to add any new columns
    upgrade_schema(engine)

    _write_schema_marker(engine, fingerprint)


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
    new_columns = _UPGRADE_NEW_COLUMNS

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

        # Widen columns that were originally defined too narrow.
        # The sessions.token column was VARCHAR(100) but JWT tokens are ~220 chars.
        # Note: SQLite does not support ALTER COLUMN TYPE, but it also does not
        # enforce VARCHAR lengths, so this migration only matters on PostgreSQL.
        column_widening = _UPGRADE_COLUMN_WIDENING
        is_sqlite = str(engine.url).startswith('sqlite')
        if not is_sqlite:
            for table_name, column_name, new_type in column_widening:
                if table_name not in inspector.get_table_names():
                    continue
                try:
                    sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE {new_type}"
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"Widened {table_name}.{column_name} to {new_type}")
                except Exception as e:
                    if 'already' in str(e).lower() or 'nothing to alter' in str(e).lower():
                        pass
                    else:
                        logger.debug(f"Column widen {table_name}.{column_name}: {e}")


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


def check_database_connection(retry_on_failure: bool = True) -> bool:
    """
    Check if database connection is working.
    
    Args:
        retry_on_failure: If True, attempt to reset and reconnect on failure
    
    Returns:
        True if connection is successful, False otherwise
    """
    global _last_connection_check
    
    try:
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _last_connection_check = time.time()
        logger.debug("Database connection check: OK")
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        
        if retry_on_failure:
            logger.info("Attempting to reconnect...")
            try:
                reset_connection()
                engine = get_engine(force_new=True)
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                _last_connection_check = time.time()
                logger.info("Database reconnection successful!")
                return True
            except Exception as retry_error:
                logger.error(f"Database reconnection failed: {retry_error}")
        
        return False


def ensure_connection_healthy() -> bool:
    """
    Ensure database connection is healthy, reconnecting if necessary.
    This is a lightweight check that uses cached status when possible.
    
    Returns:
        True if connection is healthy, False otherwise
    """
    global _last_connection_check
    
    current_time = time.time()
    
    # Skip check if recently verified
    if current_time - _last_connection_check < _connection_check_interval:
        return True
    
    return check_database_connection(retry_on_failure=True)


def get_database_info() -> dict:
    """Get information about the current database configuration"""
    config_summary = DatabaseConfig.get_config_summary()
    
    connection_ok = False
    connection_error = None
    
    try:
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            connection_ok = result.fetchone() is not None
    except Exception as e:
        connection_ok = False
        connection_error = str(e)
    
    return {
        **config_summary,
        'connection_ok': connection_ok,
        'connection_error': connection_error,
        'engine_initialized': _engine is not None,
        'session_factory_initialized': _session_factory is not None,
        'last_connection_check': _last_connection_check
    }


# Export public interface
__all__ = [
    'get_engine',
    'get_session_factory',
    'get_db_session',
    'init_database',
    'upgrade_schema',
    'close_database',
    'reset_connection',
    'check_database_connection',
    'ensure_connection_healthy',
    'get_database_info',
    'Base'
]
