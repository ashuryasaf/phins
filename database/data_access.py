"""
Data Access Layer

Provides backward-compatible dictionary-like interface to database.
This allows gradual migration from in-memory to database storage.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

from database.manager import DatabaseManager

logger = logging.getLogger(__name__)


def convert_datetime_strings(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert ISO datetime strings to datetime objects for database insertion.
    
    Args:
        data: Dictionary that may contain datetime strings
    
    Returns:
        Dictionary with datetime strings converted to datetime objects
    """
    datetime_fields = [
        'created_date', 'updated_date', 'start_date', 'end_date',
        'approval_date', 'filed_date', 'payment_date', 'submitted_date',
        'decision_date', 'due_date', 'paid_date', 'expires', 'last_login',
        'timestamp'
    ]
    
    result = data.copy()
    for field in datetime_fields:
        if field in result and result[field] is not None:
            value = result[field]
            if isinstance(value, str):
                try:
                    # Parse ISO format datetime string
                    result[field] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    # If parsing fails, keep original value
                    pass
    
    return result


def _normalize_payload_for_repo(repository_name: str, value: Dict[str, Any], key: str) -> Dict[str, Any]:
    """
    Normalize common legacy/in-memory keys into DB schema keys.

    The web server uses some legacy field names (e.g. bill_id/amount_due, ip/created_at),
    so we translate them here to keep DB mode backward compatible.
    """
    v = dict(value)

    if repository_name == "billing":
        # Server uses bill_id/amount_due; DB model uses id/amount.
        if "bill_id" in v and "id" not in v:
            v["id"] = v["bill_id"]
        if "amount_due" in v and "amount" not in v:
            v["amount"] = v["amount_due"]
        # Some flows use "bill_id" only in the key.
        if "id" not in v:
            v["id"] = key

    if repository_name == "sessions":
        # Server uses ip/created_at; DB model uses ip_address/created_date.
        if "ip" in v and "ip_address" not in v:
            v["ip_address"] = v["ip"]
        if "created_at" in v and "created_date" not in v:
            v["created_date"] = v["created_at"]

    if repository_name == "users":
        # Server stores hash/salt; DB model uses password_hash/password_salt.
        if "hash" in v and "password_hash" not in v:
            v["password_hash"] = v["hash"]
        if "salt" in v and "password_salt" not in v:
            v["password_salt"] = v["salt"]
        if "email" not in v:
            # Often username is an email in the portal.
            v["email"] = key

    if repository_name == "underwriting":
        # Alternate naming used by older service code.
        if "risk_level" in v and "risk_assessment" not in v:
            v["risk_assessment"] = v["risk_level"]
        if "requires_medical" in v and "medical_exam_required" not in v:
            v["medical_exam_required"] = v["requires_medical"]

    return v


def _filter_to_model_fields(model_class: Any, value: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys that are not columns on the SQLAlchemy model."""
    try:
        allowed = set(model_class.__table__.columns.keys())
        return {k: v for k, v in value.items() if k in allowed}
    except Exception:
        # If introspection fails, do not filter (best-effort).
        return value


class DatabaseDict:
    """
    Dictionary-like wrapper around database repository.
    Provides dict API for backward compatibility with existing code.
    """
    
    def __init__(self, repository_name: str):
        """
        Initialize database dict wrapper.
        
        Args:
            repository_name: Name of repository (customers, policies, claims, etc.)
        """
        self.repository_name = repository_name
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_valid = False
    
    def _get_repository(self, db: DatabaseManager):
        """Get the appropriate repository from database manager"""
        return getattr(db, self.repository_name)
    
    def _refresh_cache(self):
        """Refresh cache from database"""
        with DatabaseManager() as db:
            repo = self._get_repository(db)
            items = repo.get_all()
            self._cache = {item.id if hasattr(item, 'id') else 
                          (item.username if hasattr(item, 'username') else 
                          (item.token if hasattr(item, 'token') else str(item))): 
                          item.to_dict() for item in items}
            self._cache_valid = True
    
    def __getitem__(self, key: str) -> Dict[str, Any]:
        """Get item by key"""
        with DatabaseManager() as db:
            repo = self._get_repository(db)
            item = repo.get_by_id(key)
            if item is None:
                raise KeyError(key)
            return item.to_dict()
    
    def __setitem__(self, key: str, value: Dict[str, Any]):
        """Set item by key (create or update)"""
        # Normalize legacy keys then convert datetime strings to datetime objects
        value = _normalize_payload_for_repo(self.repository_name, value, key)
        value = convert_datetime_strings(value)
        
        with DatabaseManager() as db:
            repo = self._get_repository(db)
            # Filter payload to model columns to avoid invalid keyword errors
            value = _filter_to_model_fields(repo.model_class, value)
            existing = repo.get_by_id(key)
            if existing:
                # Update existing
                repo.update(key, **value)
            else:
                # Create new (ensure id is set)
                if 'id' not in value and self.repository_name not in ['users', 'sessions']:
                    value['id'] = key
                elif 'username' not in value and self.repository_name == 'users':
                    value['username'] = key
                elif 'token' not in value and self.repository_name == 'sessions':
                    value['token'] = key
                repo.create(**value)
        self._cache_valid = False
    
    def __delitem__(self, key: str):
        """Delete item by key"""
        with DatabaseManager() as db:
            repo = self._get_repository(db)
            if not repo.delete(key):
                raise KeyError(key)
        self._cache_valid = False
    
    def __contains__(self, key: str) -> bool:
        """Check if key exists"""
        with DatabaseManager() as db:
            repo = self._get_repository(db)
            return repo.exists(key)
    
    def __len__(self) -> int:
        """Get count of items"""
        with DatabaseManager() as db:
            repo = self._get_repository(db)
            return repo.count()
    
    def __iter__(self):
        """Iterate over keys"""
        if not self._cache_valid:
            self._refresh_cache()
        return iter(self._cache)
    
    def keys(self):
        """Get all keys"""
        if not self._cache_valid:
            self._refresh_cache()
        return self._cache.keys()
    
    def values(self):
        """Get all values"""
        if not self._cache_valid:
            self._refresh_cache()
        return self._cache.values()
    
    def items(self):
        """Get all items"""
        if not self._cache_valid:
            self._refresh_cache()
        return self._cache.items()
    
    def get(self, key: str, default=None):
        """Get item with default"""
        try:
            return self[key]
        except KeyError:
            return default
    
    def clear(self):
        """Clear all items (USE WITH CAUTION)"""
        logger.warning(f"Clearing all {self.repository_name}")
        with DatabaseManager() as db:
            repo = self._get_repository(db)
            for item in repo.get_all():
                item_id = item.id if hasattr(item, 'id') else \
                         (item.username if hasattr(item, 'username') else \
                         (item.token if hasattr(item, 'token') else None))
                if item_id:
                    repo.delete(item_id)
        self._cache_valid = False


# Global database-backed dictionaries (backward compatible with in-memory version)
CUSTOMERS = DatabaseDict('customers')
POLICIES = DatabaseDict('policies')
CLAIMS = DatabaseDict('claims')
UNDERWRITING_APPLICATIONS = DatabaseDict('underwriting')
SESSIONS = DatabaseDict('sessions')
BILLING = DatabaseDict('billing')
USERS_DB = DatabaseDict('users')


def get_db_backed_dicts():
    """Get all database-backed dictionaries"""
    return {
        'CUSTOMERS': CUSTOMERS,
        'POLICIES': POLICIES,
        'CLAIMS': CLAIMS,
        'UNDERWRITING_APPLICATIONS': UNDERWRITING_APPLICATIONS,
        'SESSIONS': SESSIONS,
        'BILLING': BILLING,
        'USERS': USERS_DB
    }


__all__ = [
    'DatabaseDict',
    'CUSTOMERS',
    'POLICIES',
    'CLAIMS',
    'UNDERWRITING_APPLICATIONS',
    'SESSIONS',
    'BILLING',
    'USERS_DB',
    'get_db_backed_dicts'
]
