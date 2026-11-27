"""Money unit-of-work (ERP/MGA integrity U12).

Every money write that touches the durable accounting journal, the platform
ledger, and/or a fiduciary table should run inside ``money_uow`` so a partial
post cannot land. When a ``DatabaseManager`` session is available the UoW is
``session_scope()``; otherwise the block is still fail-closed (exceptions
propagate; no silent commit of half a write).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional


class UnitOfWorkError(RuntimeError):
    """Raised when a money UoW cannot open or must abort."""


@contextmanager
def money_uow(
    *,
    db_manager: Any = None,
    label: str = 'money',
) -> Iterator[Optional[Any]]:
    """Yield a DB session (or ``None`` in memory mode) for one money write.

    Callers that need a session use the yielded value. Callers that only need
    atomicity rely on the context: an exception rolls back the session and
    never invents a second money store.
    """
    manager = db_manager
    if manager is None:
        try:
            from database.manager import DatabaseManager
            manager = DatabaseManager.get_instance() if hasattr(DatabaseManager, 'get_instance') else None
            if manager is None:
                # Singleton accessors vary by boot path.
                from database import manager as mgr_mod
                manager = getattr(mgr_mod, 'get_database_manager', lambda: None)()
        except Exception:
            manager = None

    if manager is not None and hasattr(manager, 'session_scope'):
        try:
            with manager.session_scope() as session:
                yield session
            return
        except Exception as exc:
            raise UnitOfWorkError(f'{label}: session_scope failed: {exc}') from exc

    # In-memory / demo: no durable transaction boundary, but still a single
    # scope so callers share one code path. Failures propagate unchanged.
    yield None


def require_uow(fn):
    """Decorator: wrap a money-mutating function in ``money_uow``."""

    def wrapper(*args, **kwargs):
        with money_uow(label=getattr(fn, '__name__', 'money')):
            return fn(*args, **kwargs)

    wrapper.__name__ = getattr(fn, '__name__', 'wrapped')
    wrapper.__doc__ = getattr(fn, '__doc__', None)
    return wrapper


__all__ = [
    'UnitOfWorkError',
    'money_uow',
    'require_uow',
]
