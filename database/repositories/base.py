"""
Base Repository Class

Provides common CRUD operations for all repositories.

NOTE: Repository methods that modify data (create, update, delete) automatically
commit transactions. When using repositories within a larger transaction context,
it's recommended to use the DatabaseManager's session_scope() context manager
to ensure proper transaction boundaries.

Example:
    with DatabaseManager() as db:
        # Multiple operations in one transaction
        customer = db.customers.create(...)
        policy = db.policies.create(...)
        # All committed together at context exit
"""

from typing import TypeVar, Generic, List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import logging

T = TypeVar('T')

logger = logging.getLogger(__name__)


class BaseRepository(Generic[T]):
    """Base repository with common CRUD operations"""
    
    def __init__(self, model_class: type, session: Session):
        """
        Initialize repository.
        
        Args:
            model_class: SQLAlchemy model class
            session: Database session
        """
        self.model_class = model_class
        self.session = session
    
    def create(self, **kwargs) -> Optional[T]:
        """
        Create a new record.
        
        Args:
            **kwargs: Field values for the new record
        
        Returns:
            Created model instance or None if failed
        """
        try:
            instance = self.model_class(**kwargs)
            self.session.add(instance)
            self.session.commit()
            self.session.refresh(instance)
            logger.info(f"Created {self.model_class.__name__}: {kwargs.get('id', 'N/A')}")
            return instance
        except SQLAlchemyError as e:
            logger.error(f"Error creating {self.model_class.__name__}: {e}")
            self.session.rollback()
            return None
    
    def get_by_id(self, id_value: Any) -> Optional[T]:
        """
        Get a record by its primary key.
        
        Args:
            id_value: Primary key value
        
        Returns:
            Model instance or None if not found
        """
        try:
            # SQLAlchemy 2.x: prefer Session.get over Query.get (legacy).
            return self.session.get(self.model_class, id_value)
        except SQLAlchemyError as e:
            logger.error(f"Error fetching {self.model_class.__name__} by id {id_value}: {e}")
            return None
    
    def get_all(self, limit: Optional[int] = None, offset: int = 0) -> List[T]:
        """
        Get all records with optional pagination.
        
        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip
        
        Returns:
            List of model instances
        """
        try:
            query = self.session.query(self.model_class)
            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)
            return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching all {self.model_class.__name__}: {e}")
            return []
    
    def update(self, id_value: Any, **kwargs) -> Optional[T]:
        """
        Update a record by its primary key.
        
        Args:
            id_value: Primary key value
            **kwargs: Fields to update
        
        Returns:
            Updated model instance or None if not found
        """
        try:
            instance = self.get_by_id(id_value)
            if instance:
                for key, value in kwargs.items():
                    if hasattr(instance, key):
                        setattr(instance, key, value)
                self.session.commit()
                self.session.refresh(instance)
                logger.info(f"Updated {self.model_class.__name__}: {id_value}")
                return instance
            return None
        except SQLAlchemyError as e:
            logger.error(f"Error updating {self.model_class.__name__} {id_value}: {e}")
            self.session.rollback()
            return None
    
    def delete(self, id_value: Any) -> bool:
        """
        Delete a record by its primary key.
        
        Args:
            id_value: Primary key value
        
        Returns:
            True if deleted, False otherwise
        """
        try:
            instance = self.get_by_id(id_value)
            if instance:
                self.session.delete(instance)
                self.session.commit()
                logger.info(f"Deleted {self.model_class.__name__}: {id_value}")
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error deleting {self.model_class.__name__} {id_value}: {e}")
            self.session.rollback()
            return False
    
    def count(self) -> int:
        """
        Count total records.
        
        Returns:
            Total number of records
        """
        try:
            return self.session.query(self.model_class).count()
        except SQLAlchemyError as e:
            logger.error(f"Error counting {self.model_class.__name__}: {e}")
            return 0
    
    def exists(self, id_value: Any) -> bool:
        """
        Check if a record exists.
        
        Args:
            id_value: Primary key value
        
        Returns:
            True if exists, False otherwise
        """
        try:
            return self.session.query(self.model_class).filter_by(id=id_value).count() > 0
        except SQLAlchemyError as e:
            logger.error(f"Error checking existence of {self.model_class.__name__} {id_value}: {e}")
            return False
    
    def filter_by(self, **kwargs) -> List[T]:
        """
        Filter records by field values.
        
        Args:
            **kwargs: Field filters
        
        Returns:
            List of matching model instances
        """
        try:
            return self.session.query(self.model_class).filter_by(**kwargs).all()
        except SQLAlchemyError as e:
            logger.error(f"Error filtering {self.model_class.__name__}: {e}")
            return []
    
    def find_one_by(self, **kwargs) -> Optional[T]:
        """
        Find a single record by field values.
        
        Args:
            **kwargs: Field filters
        
        Returns:
            Model instance or None if not found
        """
        try:
            return self.session.query(self.model_class).filter_by(**kwargs).first()
        except SQLAlchemyError as e:
            logger.error(f"Error finding {self.model_class.__name__}: {e}")
            return None
