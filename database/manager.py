"""
Database Manager

Provides a high-level interface to all repositories for use in the web server.
Handles session management and provides a clean API for database operations.

IMPORTANT: This manager includes automatic connection recovery. When database
connections fail, it will attempt to reconnect automatically.
"""

from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DatabaseError, DisconnectionError
import logging

from database import get_db_session, reset_connection, ensure_connection_healthy
from database.repositories import (
    CustomerRepository,
    PolicyRepository,
    ClaimRepository,
    UnderwritingRepository,
    BillingRepository,
    UserRepository,
    SessionRepository,
    AuditRepository,
    PlatformLedgerRepository,
    ActuarialRepository,
    TokenRepository,
    DocumentRepository,
    DocumentProcessingJobRepository,
    SupplierRepository,
    SupplierInvitationRepository,
    SupplierOfferRepository,
    SupplierOrderRepository,
    SupplierDocumentRepository,
    SupplyChainLedgerRepository,
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
    AgentRepository,
    AgentInvitationRepository,
    AgentAffiliationRepository,
    AgentCommissionRepository,
    AssessmentRecordRepository,
    BusinessInquiryRepository,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    High-level database manager that provides access to all repositories.
    
    Includes automatic connection recovery on database errors.
    
    Usage:
        db_manager = DatabaseManager()
        with db_manager.session_scope() as session:
            customer = db_manager.customers.get_by_id('CUST-123')
    """
    
    def __init__(self, session: Optional[Session] = None, max_retries: int = 3):
        """
        Initialize database manager.
        
        Args:
            session: Optional pre-existing session. If not provided, creates new sessions.
            max_retries: Maximum retry attempts for connection failures (default: 3)
        """
        self._session = session
        self._owns_session = session is None
        self._max_retries = max_retries
        
        # Initialize repositories (will be set when session is available)
        self._customers = None
        self._policies = None
        self._claims = None
        self._underwriting = None
        self._billing = None
        self._users = None
        self._sessions = None
        self._audit = None
        self._platform_ledger = None
        self._actuarial = None
        self._tokens = None
        self._documents = None
        self._processing_jobs = None
        self._suppliers = None
        self._supplier_invitations = None
        self._supplier_offers = None
        self._supplier_orders = None
        self._supplier_documents = None
        self._supply_chain_ledger = None
        # Health-marketplace foundation repositories.
        self._wallet_accounts = None
        self._wallet_holds = None
        self._wallet_ledger = None
        self._payment_intents = None
        self._refunds = None
        self._journal = None
        self._supplier_settlement_runs = None
        self._supplier_settlement_items = None
        self._external_payers = None
        self._marketplace_claims = None
        self._remittances = None
        self._payer_receivables = None
        self._idempotency = None
        self._outbox = None
        # Agent ecosystem repositories.
        self._agents = None
        self._agent_invitations = None
        self._agent_affiliations = None
        self._agent_commissions = None
        # Assessment loop repositories.
        self._assessment_records = None
        # Business Relations (contact / demo inquiries).
        self._business_inquiries = None
    
    def _ensure_session(self) -> Session:
        """
        Ensure we have a database session with connection recovery.
        
        Returns:
            Valid database session
        
        Raises:
            Exception: If connection cannot be established after retries
        """
        if self._session is None:
            self._session = get_db_session(max_retries=self._max_retries)
            self._owns_session = True
        return self._session
    
    def _reset_repositories(self):
        """Reset all repository references (used after session reset)"""
        self._customers = None
        self._policies = None
        self._claims = None
        self._underwriting = None
        self._billing = None
        self._users = None
        self._sessions = None
        self._audit = None
        self._platform_ledger = None
        self._actuarial = None
        self._tokens = None
        self._documents = None
        self._processing_jobs = None
        self._suppliers = None
        self._supplier_invitations = None
        self._supplier_offers = None
        self._supplier_orders = None
        self._supplier_documents = None
        self._supply_chain_ledger = None
        self._wallet_accounts = None
        self._wallet_holds = None
        self._wallet_ledger = None
        self._payment_intents = None
        self._refunds = None
        self._journal = None
        self._supplier_settlement_runs = None
        self._supplier_settlement_items = None
        self._external_payers = None
        self._marketplace_claims = None
        self._remittances = None
        self._payer_receivables = None
        self._idempotency = None
        self._outbox = None
        self._agents = None
        self._agent_invitations = None
        self._agent_affiliations = None
        self._agent_commissions = None
        self._assessment_records = None
        self._business_inquiries = None
    
    @property
    def customers(self) -> CustomerRepository:
        """Get customer repository"""
        if self._customers is None:
            self._customers = CustomerRepository(self._ensure_session())
        return self._customers
    
    @property
    def policies(self) -> PolicyRepository:
        """Get policy repository"""
        if self._policies is None:
            self._policies = PolicyRepository(self._ensure_session())
        return self._policies
    
    @property
    def claims(self) -> ClaimRepository:
        """Get claim repository"""
        if self._claims is None:
            self._claims = ClaimRepository(self._ensure_session())
        return self._claims
    
    @property
    def underwriting(self) -> UnderwritingRepository:
        """Get underwriting repository"""
        if self._underwriting is None:
            self._underwriting = UnderwritingRepository(self._ensure_session())
        return self._underwriting
    
    @property
    def billing(self) -> BillingRepository:
        """Get billing repository"""
        if self._billing is None:
            self._billing = BillingRepository(self._ensure_session())
        return self._billing
    
    @property
    def users(self) -> UserRepository:
        """Get user repository"""
        if self._users is None:
            self._users = UserRepository(self._ensure_session())
        return self._users
    
    @property
    def sessions(self) -> SessionRepository:
        """Get session repository"""
        if self._sessions is None:
            self._sessions = SessionRepository(self._ensure_session())
        return self._sessions
    
    @property
    def audit(self) -> AuditRepository:
        """Get audit repository"""
        if self._audit is None:
            self._audit = AuditRepository(self._ensure_session())
        return self._audit

    @property
    def platform_ledger(self) -> PlatformLedgerRepository:
        """Get platform ledger repository"""
        if self._platform_ledger is None:
            self._platform_ledger = PlatformLedgerRepository(self._ensure_session())
        return self._platform_ledger

    @property
    def actuarial(self) -> ActuarialRepository:
        """Get actuarial tables repository"""
        if self._actuarial is None:
            self._actuarial = ActuarialRepository(self._ensure_session())
        return self._actuarial

    @property
    def tokens(self) -> TokenRepository:
        """Get token registry repository"""
        if self._tokens is None:
            self._tokens = TokenRepository(self._ensure_session())
        return self._tokens

    @property
    def documents(self) -> DocumentRepository:
        """Get document repository"""
        if self._documents is None:
            self._documents = DocumentRepository(self._ensure_session())
        return self._documents

    @property
    def processing_jobs(self) -> DocumentProcessingJobRepository:
        """Get document processing-job repository"""
        if self._processing_jobs is None:
            self._processing_jobs = DocumentProcessingJobRepository(self._ensure_session())
        return self._processing_jobs

    @property
    def suppliers(self) -> SupplierRepository:
        """Get supplier repository"""
        if self._suppliers is None:
            self._suppliers = SupplierRepository(self._ensure_session())
        return self._suppliers

    @property
    def supplier_invitations(self) -> SupplierInvitationRepository:
        """Get supplier invitation repository"""
        if self._supplier_invitations is None:
            self._supplier_invitations = SupplierInvitationRepository(self._ensure_session())
        return self._supplier_invitations

    @property
    def supplier_offers(self) -> SupplierOfferRepository:
        """Get supplier offer repository"""
        if self._supplier_offers is None:
            self._supplier_offers = SupplierOfferRepository(self._ensure_session())
        return self._supplier_offers

    @property
    def supplier_orders(self) -> SupplierOrderRepository:
        """Get supplier order repository"""
        if self._supplier_orders is None:
            self._supplier_orders = SupplierOrderRepository(self._ensure_session())
        return self._supplier_orders

    @property
    def supplier_documents(self) -> SupplierDocumentRepository:
        """Get supplier document repository"""
        if self._supplier_documents is None:
            self._supplier_documents = SupplierDocumentRepository(self._ensure_session())
        return self._supplier_documents

    @property
    def supply_chain_ledger(self) -> SupplyChainLedgerRepository:
        """Get supply chain ledger repository"""
        if self._supply_chain_ledger is None:
            self._supply_chain_ledger = SupplyChainLedgerRepository(self._ensure_session())
        return self._supply_chain_ledger

    # ------------------------------------------------------------------
    # Health-marketplace foundation repositories (wallet, settlement,
    # payer recovery, integrity). See docs/health_marketplace_*.md.
    # ------------------------------------------------------------------

    @property
    def wallet_accounts(self) -> WalletAccountRepository:
        """Get wallet account repository (durable wallet balances)."""
        if self._wallet_accounts is None:
            self._wallet_accounts = WalletAccountRepository(self._ensure_session())
        return self._wallet_accounts

    @property
    def wallet_holds(self) -> WalletHoldRepository:
        """Get wallet hold repository (authorize-then-capture)."""
        if self._wallet_holds is None:
            self._wallet_holds = WalletHoldRepository(self._ensure_session())
        return self._wallet_holds

    @property
    def wallet_ledger(self) -> WalletLedgerRepository:
        """Get wallet ledger repository (append-only sub-ledger)."""
        if self._wallet_ledger is None:
            self._wallet_ledger = WalletLedgerRepository(self._ensure_session())
        return self._wallet_ledger

    @property
    def payment_intents(self) -> PaymentIntentRepository:
        """Get payment-intent repository."""
        if self._payment_intents is None:
            self._payment_intents = PaymentIntentRepository(self._ensure_session())
        return self._payment_intents

    @property
    def refunds(self) -> RefundRepository:
        """Get refund repository."""
        if self._refunds is None:
            self._refunds = RefundRepository(self._ensure_session())
        return self._refunds

    @property
    def journal(self) -> JournalRepository:
        """Get accounting journal repository."""
        if self._journal is None:
            self._journal = JournalRepository(self._ensure_session())
        return self._journal

    @property
    def supplier_settlement_runs(self) -> SupplierSettlementRunRepository:
        """Get supplier-settlement-run repository."""
        if self._supplier_settlement_runs is None:
            self._supplier_settlement_runs = SupplierSettlementRunRepository(self._ensure_session())
        return self._supplier_settlement_runs

    @property
    def supplier_settlement_items(self) -> SupplierSettlementItemRepository:
        """Get supplier-settlement-item repository."""
        if self._supplier_settlement_items is None:
            self._supplier_settlement_items = SupplierSettlementItemRepository(self._ensure_session())
        return self._supplier_settlement_items

    @property
    def external_payers(self) -> ExternalPayerRepository:
        """Get external payer repository."""
        if self._external_payers is None:
            self._external_payers = ExternalPayerRepository(self._ensure_session())
        return self._external_payers

    @property
    def marketplace_claims(self) -> MarketplaceClaimRepository:
        """Get marketplace-claim repository."""
        if self._marketplace_claims is None:
            self._marketplace_claims = MarketplaceClaimRepository(self._ensure_session())
        return self._marketplace_claims

    @property
    def remittances(self) -> RemittanceRepository:
        """Get remittance repository (advice + lines)."""
        if self._remittances is None:
            self._remittances = RemittanceRepository(self._ensure_session())
        return self._remittances

    @property
    def payer_receivables(self) -> PayerReceivableRepository:
        """Get payer-receivable repository."""
        if self._payer_receivables is None:
            self._payer_receivables = PayerReceivableRepository(self._ensure_session())
        return self._payer_receivables

    @property
    def idempotency(self) -> IdempotencyRepository:
        """Get idempotency-key repository."""
        if self._idempotency is None:
            self._idempotency = IdempotencyRepository(self._ensure_session())
        return self._idempotency

    @property
    def outbox(self) -> OutboxRepository:
        """Get outbox-event repository."""
        if self._outbox is None:
            self._outbox = OutboxRepository(self._ensure_session())
        return self._outbox

    # ------------------------------------------------------------------
    # Agent ecosystem repositories ("AgentOS").
    # See docs/agent_ecosystem_design.md.
    # ------------------------------------------------------------------

    @property
    def agents(self) -> AgentRepository:
        """Get agent profile repository."""
        if self._agents is None:
            self._agents = AgentRepository(self._ensure_session())
        return self._agents

    @property
    def agent_invitations(self) -> AgentInvitationRepository:
        """Get agent invitation repository."""
        if self._agent_invitations is None:
            self._agent_invitations = AgentInvitationRepository(self._ensure_session())
        return self._agent_invitations

    @property
    def agent_affiliations(self) -> AgentAffiliationRepository:
        """Get agent affiliation repository."""
        if self._agent_affiliations is None:
            self._agent_affiliations = AgentAffiliationRepository(self._ensure_session())
        return self._agent_affiliations

    @property
    def agent_commissions(self) -> AgentCommissionRepository:
        """Get agent commission repository."""
        if self._agent_commissions is None:
            self._agent_commissions = AgentCommissionRepository(self._ensure_session())
        return self._agent_commissions

    @property
    def assessment_records(self) -> AssessmentRecordRepository:
        """Get assessment record repository (score → decision loop)."""
        if self._assessment_records is None:
            self._assessment_records = AssessmentRecordRepository(self._ensure_session())
        return self._assessment_records

    @property
    def business_inquiries(self) -> BusinessInquiryRepository:
        """Get business-relations inquiry repository (contact / demo intake)."""
        if self._business_inquiries is None:
            self._business_inquiries = BusinessInquiryRepository(self._ensure_session())
        return self._business_inquiries

    def commit(self):
        """Commit current transaction"""
        if self._session:
            self._session.commit()
    
    def rollback(self):
        """Rollback current transaction"""
        if self._session:
            self._session.rollback()
    
    def close(self):
        """Close the session if we own it"""
        if self._owns_session and self._session:
            try:
                self._session.close()
            except Exception as e:
                logger.debug(f"Session close error (non-critical): {e}")
            self._session = None
            self._reset_repositories()
    
    @contextmanager
    def session_scope(self):
        """
        Provide a transactional scope around a series of operations.
        
        Includes automatic connection recovery on database errors.
        
        Usage:
            db = DatabaseManager()
            with db.session_scope():
                customer = db.customers.create(...)
                policy = db.policies.create(...)
                # Automatically commits on success, rolls back on exception
        """
        try:
            yield self
            self.commit()
        except (OperationalError, DatabaseError, DisconnectionError) as e:
            logger.error(f"Database connection error in transaction: {e}")
            self.rollback()
            # Reset connection for future operations
            try:
                reset_connection()
            except Exception as reset_err:
                logger.debug(f"Connection reset error: {reset_err}")
            raise
        except Exception as e:
            logger.error(f"Transaction failed: {e}")
            self.rollback()
            raise
        finally:
            if self._owns_session:
                self.close()
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()


# Convenience functions for quick operations

def create_customer(customer_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Quick function to create a customer"""
    with DatabaseManager() as db:
        customer = db.customers.create(**customer_data)
        return customer.to_dict() if customer else None


def get_customer(customer_id: str) -> Optional[Dict[str, Any]]:
    """Quick function to get a customer"""
    with DatabaseManager() as db:
        customer = db.customers.get_by_id(customer_id)
        return customer.to_dict() if customer else None


def create_policy(policy_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Quick function to create a policy"""
    with DatabaseManager() as db:
        policy = db.policies.create(**policy_data)
        return policy.to_dict() if policy else None


def get_policy(policy_id: str) -> Optional[Dict[str, Any]]:
    """Quick function to get a policy"""
    with DatabaseManager() as db:
        policy = db.policies.get_by_id(policy_id)
        return policy.to_dict() if policy else None


def create_claim(claim_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Quick function to create a claim"""
    with DatabaseManager() as db:
        claim = db.claims.create(**claim_data)
        return claim.to_dict() if claim else None


def get_claim(claim_id: str) -> Optional[Dict[str, Any]]:
    """Quick function to get a claim"""
    with DatabaseManager() as db:
        claim = db.claims.get_by_id(claim_id)
        return claim.to_dict() if claim else None


__all__ = [
    'DatabaseManager',
    'create_customer',
    'get_customer',
    'create_policy',
    'get_policy',
    'create_claim',
    'get_claim'
]
