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
        # Convert datetime strings to datetime objects
        value = convert_datetime_strings(value)
        
        with DatabaseManager() as db:
            repo = self._get_repository(db)
            existing = repo.get_by_id(key)
            if existing:
                # Update existing
                repo.update(key, **value)
            else:
                # Create new (ensure id is set)
                if self.repository_name == 'users' and 'username' not in value:
                    value['username'] = key
                elif self.repository_name == 'sessions' and 'token' not in value:
                    value['token'] = key
                elif self.repository_name == 'token_registry' and 'token' not in value:
                    value['token'] = key
                elif self.repository_name not in ['users', 'sessions', 'token_registry', 'notifications'] and 'id' not in value:
                    # Most tables use string ids as primary keys; autoincrement tables (notifications) are excluded.
                    value['id'] = key
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
TOKEN_REGISTRY = DatabaseDict('token_registry')
NOTIFICATIONS = DatabaseDict('notifications')


def get_db_backed_dicts():
    """Get all database-backed dictionaries"""
    return {
        'CUSTOMERS': CUSTOMERS,
        'POLICIES': POLICIES,
        'CLAIMS': CLAIMS,
        'UNDERWRITING_APPLICATIONS': UNDERWRITING_APPLICATIONS,
        'SESSIONS': SESSIONS,
        'BILLING': BILLING,
        'USERS': USERS_DB,
        'TOKEN_REGISTRY': TOKEN_REGISTRY,
        'NOTIFICATIONS': NOTIFICATIONS,
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
    'TOKEN_REGISTRY',
    'NOTIFICATIONS',
    'get_db_backed_dicts'
]
