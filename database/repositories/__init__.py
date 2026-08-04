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
from .platform_ledger_repository import PlatformLedgerRepository
from .actuarial_repository import ActuarialRepository
from .token_repository import TokenRepository
from .document_repository import DocumentRepository, DocumentProcessingJobRepository
from .supplier_repository import (
    SupplierRepository,
    SupplierInvitationRepository,
    SupplierOfferRepository,
    SupplierOrderRepository,
    SupplierDocumentRepository,
    SupplyChainLedgerRepository,
)
from .marketplace_repository import (
    WalletAccountRepository,
    WalletHoldRepository,
    WalletLedgerRepository,
    PaymentIntentRepository,
    RefundRepository,
    JournalRepository,
    SupplierSettlementRunRepository,
    SupplierSettlementItemRepository,
    ExternalPayerRepository,
    MarketplaceClaimRepository,
    RemittanceRepository,
    PayerReceivableRepository,
    IdempotencyRepository,
    OutboxRepository,
)
from .agent_repository import (
    AgentRepository,
    AgentInvitationRepository,
    AgentAffiliationRepository,
    AgentCommissionRepository,
)
from .assessment_record_repository import AssessmentRecordRepository

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
    'PlatformLedgerRepository',
    'ActuarialRepository',
    'TokenRepository',
    'DocumentRepository',
    'DocumentProcessingJobRepository',
    'SupplierRepository',
    'SupplierInvitationRepository',
    'SupplierOfferRepository',
    'SupplierOrderRepository',
    'SupplierDocumentRepository',
    'SupplyChainLedgerRepository',
    'WalletAccountRepository',
    'WalletHoldRepository',
    'WalletLedgerRepository',
    'PaymentIntentRepository',
    'RefundRepository',
    'JournalRepository',
    'SupplierSettlementRunRepository',
    'SupplierSettlementItemRepository',
    'ExternalPayerRepository',
    'MarketplaceClaimRepository',
    'RemittanceRepository',
    'PayerReceivableRepository',
    'IdempotencyRepository',
    'OutboxRepository',
    'AgentRepository',
    'AgentInvitationRepository',
    'AgentAffiliationRepository',
    'AgentCommissionRepository',
    'AssessmentRecordRepository',
]
