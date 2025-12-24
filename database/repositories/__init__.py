"""
Repository Pattern Implementation

This module provides data access layer using the repository pattern,
abstracting database operations from business logic.
"""

from .base import BaseRepository
from .customer_repository import CustomerRepository
from .policy_repository import PolicyRepository
from .claim_repository import ClaimRepository
from .underwriting_repository import UnderwritingRepository
from .billing_repository import BillingRepository
from .user_repository import UserRepository
from .session_repository import SessionRepository
from .audit_repository import AuditRepository
from .token_registry_repository import TokenRegistryRepository
from .notification_repository import NotificationRepository

__all__ = [
    'BaseRepository',
    'CustomerRepository',
    'PolicyRepository',
    'ClaimRepository',
    'UnderwritingRepository',
    'BillingRepository',
    'UserRepository',
    'SessionRepository',
    'AuditRepository',
    'TokenRegistryRepository',
    'NotificationRepository',
]
