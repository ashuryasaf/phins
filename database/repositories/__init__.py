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
from .actuarial_repository import ActuarialRepository
from .token_repository import TokenRepository

# Sully Chain repositories
from .sully_chain_repository import (
    SupplierRepository,
    SupplierSpecialtyRepository,
    SupplierCredentialRepository,
    ServiceRequestRepository,
    AllocationRepository,
    BidRepository,
    ServiceFulfillmentRepository,
    ServiceMilestoneRepository,
    SullyLedgerRepository,
    ClientInteractionRepository,
    SupplierTransactionRepository,
    EscrowAccountRepository,
    SupplierScoreRepository,
    AllocationAnalyticsRepository,
)

__all__ = [
    # Base
    'BaseRepository',
    # PHINS Core
    'CustomerRepository',
    'PolicyRepository',
    'ClaimRepository',
    'UnderwritingRepository',
    'BillingRepository',
    'UserRepository',
    'SessionRepository',
    'AuditRepository',
    'ActuarialRepository',
    'TokenRepository',
    # Sully Chain
    'SupplierRepository',
    'SupplierSpecialtyRepository',
    'SupplierCredentialRepository',
    'ServiceRequestRepository',
    'AllocationRepository',
    'BidRepository',
    'ServiceFulfillmentRepository',
    'ServiceMilestoneRepository',
    'SullyLedgerRepository',
    'ClientInteractionRepository',
    'SupplierTransactionRepository',
    'EscrowAccountRepository',
    'SupplierScoreRepository',
    'AllocationAnalyticsRepository',
]
