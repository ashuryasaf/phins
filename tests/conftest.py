"""Test configuration to ensure project root is importable.

This allows `pytest` to find top-level modules like `accounting_engine.py`
when tests are run from any working directory.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Enable test mode BEFORE importing any modules
# This enables test-specific behaviors like the test invitation code
os.environ['PHINS_TEST_MODE'] = '1'

# Add repository root to sys.path once
ROOT_DIR = Path(__file__).resolve().parents[1]
root_str = str(ROOT_DIR)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="function")
def db_engine():
    """Create an in-memory SQLite engine with all notification tables."""
    from database.models import Base as MainBase
    from database import notification_models  # noqa: F401 — registers models on Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    MainBase.metadata.create_all(engine)
    yield engine
    MainBase.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Provide a transactional SQLAlchemy session for each test."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def mock_email_provider():
    """Return a fresh MockEmailProvider."""
    from services.notification_service import MockEmailProvider
    return MockEmailProvider()


@pytest.fixture()
def mock_sms_provider():
    """Return a fresh MockSMSProvider."""
    from services.notification_service import MockSMSProvider
    return MockSMSProvider()
