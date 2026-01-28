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
    Convert ISO datetime strings to datetime objects and dict fields to JSON strings.
    
    Args:
        data: Dictionary that may contain datetime strings and nested dicts
    
    Returns:
        Dictionary with datetime strings converted to datetime objects
        and dict fields converted to JSON strings
    """
    import json
    
    datetime_fields = [
        'created_date', 'updated_date', 'start_date', 'end_date',
        'approval_date', 'filed_date', 'payment_date', 'submitted_date',
        'decision_date', 'due_date', 'paid_date', 'expires', 'last_login',
        'timestamp'
    ]
    
    # Fields that should be stored as JSON strings
    json_fields = [
        'questionnaire_responses', 'payment_setup', 'health_wallet', 
        'billing', 'metadata', 'additional_data',
        'medical_conditions', 'documents', 'data_sources'
    ]
    
    result = data.copy()
    
    # Convert datetime fields
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
    
    # Convert dict/list fields to JSON strings for storage
    for field in json_fields:
        if field in result and result[field] is not None:
            value = result[field]
            if isinstance(value, (dict, list)):
                try:
                    result[field] = json.dumps(value)
                except (TypeError, ValueError):
                    # If JSON encoding fails, try str
                    result[field] = str(value)
    
    return result


# Field mappings from server dictionary keys to database model fields
# This ensures backward compatibility with existing code that uses different key names
FIELD_MAPPINGS = {
    'billing': {
        'bill_id': 'id',           # bill_id → id (database uses 'id' as primary key)
        'amount_due': 'amount',    # amount_due → amount
    },
    'claims': {
        'claim_id': 'id',          # claim_id → id
        'files': 'files_metadata', # files → files_metadata (stored as JSON string)
    },
    'policies': {
        'policy_id': 'id',         # policy_id → id (if used)
    },
    'underwriting': {
        'uw_id': 'id',             # uw_id → id (if used)
        'application_id': 'id',    # application_id → id
    }
}

# Fields that need JSON serialization when storing
JSON_FIELDS = {
    'claims': ['files_metadata', 'bank_details'],
}


def map_fields_for_repository(repository_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map field names from server dictionary format to database model format.
    Also handles JSON serialization for complex fields.
    
    Args:
        repository_name: Name of the repository (billing, claims, etc.)
        data: Dictionary with server field names
    
    Returns:
        Dictionary with database model field names
    """
    import json
    
    result = data.copy()
    
    # Apply field name mappings
    mappings = FIELD_MAPPINGS.get(repository_name, {})
    for old_name, new_name in mappings.items():
        if old_name in result:
            # Copy value to new field name
            if new_name not in result:  # Don't overwrite if already present
                result[new_name] = result[old_name]
            # Remove old field name (to avoid 'unexpected keyword argument' errors)
            del result[old_name]
    
    # Serialize JSON fields (convert dicts/lists to JSON strings)
    json_fields = JSON_FIELDS.get(repository_name, [])
    for field in json_fields:
        if field in result and result[field] is not None:
            if isinstance(result[field], (dict, list)):
                result[field] = json.dumps(result[field])
    
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
            def _key_for_item(item):
                # Use correct primary key per repository (prevents subtle bugs like sessions keyed by username)
                if self.repository_name == 'sessions' and hasattr(item, 'token'):
                    return item.token
                if self.repository_name == 'users' and hasattr(item, 'username'):
                    return item.username
                if hasattr(item, 'id'):
                    return item.id
                if hasattr(item, 'username'):
                    return item.username
                if hasattr(item, 'token'):
                    return item.token
                return str(item)

            self._cache = {_key_for_item(item): item.to_dict() for item in items}
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
        
        # Map field names from server format to database format
        value = map_fields_for_repository(self.repository_name, value)
        
        with DatabaseManager() as db:
            repo = self._get_repository(db)
            existing = repo.get_by_id(key)
            if existing:
                # Update existing - filter out keys that aren't model attributes
                update_data = {k: v for k, v in value.items() if hasattr(existing, k)}
                repo.update(key, **update_data)
            else:
                # Create new (ensure id is set)
                if 'id' not in value and self.repository_name not in ['users', 'sessions']:
                    value['id'] = key
                elif 'username' not in value and self.repository_name == 'users':
                    value['username'] = key
                elif 'token' not in value and self.repository_name == 'sessions':
                    value['token'] = key
                
                # Filter out keys that aren't valid model attributes to prevent errors
                try:
                    model_class = repo.model_class
                    valid_columns = {c.name for c in model_class.__table__.columns}
                    filtered_value = {k: v for k, v in value.items() if k in valid_columns}
                    repo.create(**filtered_value)
                except Exception as e:
                    # Fallback: try creating with all values
                    logger.warning(f"Error filtering columns for {self.repository_name}: {e}")
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
    
    def pop(self, key: str, *args):
        """
        Remove and return item by key.
        If key not found, return default if provided, else raise KeyError.
        
        Args:
            key: Key to remove
            *args: Optional default value
        
        Returns:
            The removed value, or default if key not found
        """
        try:
            value = self[key]
            del self[key]
            return value
        except KeyError:
            if args:
                return args[0]  # Return default
            raise
    
    def setdefault(self, key: str, default=None):
        """Get item, setting default if not present"""
        try:
            return self[key]
        except KeyError:
            self[key] = default
            return default
    
    def update(self, other=None, **kwargs):
        """Update dict with items from other dict or kwargs"""
        if other:
            if hasattr(other, 'items'):
                for k, v in other.items():
                    self[k] = v
            else:
                for k, v in other:
                    self[k] = v
        for k, v in kwargs.items():
            self[k] = v
    
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
