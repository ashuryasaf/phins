"""
Supplier Repository

Provides data-access methods for supplier-related tables:
- Supplier (suppliers)
- SupplierInvitationCode (supplier_invitation_codes)
- SupplierOffer (supplier_offers)
- SupplierOrder (supplier_orders)
- SupplierDocument (supplier_documents)
- SupplyChainLedgerEntry (supply_chain_ledger)
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import json
import logging

from .base import BaseRepository
from database.models import (
    Supplier,
    SupplierInvitationCode,
    SupplierOffer,
    SupplierOrder,
    SupplierDocument,
    SupplyChainLedgerEntry,
)

logger = logging.getLogger(__name__)


class SupplierRepository(BaseRepository):
    """Repository for Supplier records"""

    def __init__(self, session: Session):
        super().__init__(Supplier, session)

    def get_by_email(self, email: str) -> Optional[Supplier]:
        try:
            return self.session.query(Supplier).filter_by(contact_email=email).first()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching supplier by email: {e}")
            return None

    def get_by_status(self, status: str) -> List[Supplier]:
        try:
            return self.session.query(Supplier).filter_by(status=status).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching suppliers by status: {e}")
            return []

    def load_all_as_dicts(self) -> Dict[str, Dict[str, Any]]:
        """Load all suppliers into an id-keyed dict compatible with in-memory stores."""
        result: Dict[str, Dict[str, Any]] = {}
        try:
            for s in self.session.query(Supplier).all():
                result[s.id] = s.to_dict(include_sensitive=True)
        except SQLAlchemyError as e:
            logger.error(f"Error loading suppliers: {e}")
        return result


class SupplierInvitationRepository(BaseRepository):
    """Repository for SupplierInvitationCode records"""

    def __init__(self, session: Session):
        super().__init__(SupplierInvitationCode, session)

    def get_by_code(self, code: str) -> Optional[SupplierInvitationCode]:
        return self.get_by_id(code)

    def get_by_status(self, status: str) -> List[SupplierInvitationCode]:
        try:
            return self.session.query(SupplierInvitationCode).filter_by(status=status).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching invitations by status: {e}")
            return []

    def load_all_as_dicts(self) -> Dict[str, Dict[str, Any]]:
        """Load all invitation codes into a code-keyed dict."""
        result: Dict[str, Dict[str, Any]] = {}
        try:
            for inv in self.session.query(SupplierInvitationCode).all():
                result[inv.code] = inv.to_dict()
        except SQLAlchemyError as e:
            logger.error(f"Error loading invitations: {e}")
        return result

    def upsert_from_dict(self, code: str, data: Dict[str, Any]) -> bool:
        """Create or update an invitation from a dict (in-memory format)."""
        try:
            existing = self.get_by_id(code)
            used_by_val = data.get('used_by', [])
            if isinstance(used_by_val, list):
                used_by_json = json.dumps(used_by_val)
            else:
                used_by_json = str(used_by_val)

            if existing:
                existing.created_at = data.get('created_at', existing.created_at)
                existing.created_by = data.get('created_by', existing.created_by)
                existing.supplier_type = data.get('supplier_type', existing.supplier_type)
                existing.expires_at = data.get('expires_at', existing.expires_at)
                existing.max_uses = data.get('max_uses', existing.max_uses)
                existing.used_count = data.get('used_count', existing.used_count)
                existing.used_by = used_by_json
                existing.status = data.get('status', existing.status)
                existing.notes = data.get('notes', existing.notes)
                existing.referrer_id = data.get('referrer_id', existing.referrer_id)
                existing.commission_override = data.get('commission_override', existing.commission_override)
                self.session.commit()
            else:
                obj = SupplierInvitationCode(
                    code=code,
                    created_at=data.get('created_at', ''),
                    created_by=data.get('created_by', ''),
                    supplier_type=data.get('supplier_type'),
                    expires_at=data.get('expires_at', ''),
                    max_uses=data.get('max_uses', 1),
                    used_count=data.get('used_count', 0),
                    used_by=used_by_json,
                    status=data.get('status', 'active'),
                    notes=data.get('notes', ''),
                    referrer_id=data.get('referrer_id'),
                    commission_override=data.get('commission_override'),
                )
                self.session.add(obj)
                self.session.commit()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Error upserting invitation {code}: {e}")
            self.session.rollback()
            return False


class SupplierOfferRepository(BaseRepository):
    """Repository for SupplierOffer records"""

    def __init__(self, session: Session):
        super().__init__(SupplierOffer, session)

    def get_active(self) -> List[SupplierOffer]:
        try:
            return self.session.query(SupplierOffer).filter_by(active=True).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching active offers: {e}")
            return []

    def get_by_supplier(self, supplier_id: str) -> List[SupplierOffer]:
        try:
            return self.session.query(SupplierOffer).filter_by(supplier_id=supplier_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching offers for supplier: {e}")
            return []

    def load_all_as_dicts(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        try:
            for o in self.session.query(SupplierOffer).all():
                result[o.id] = o.to_dict()
        except SQLAlchemyError as e:
            logger.error(f"Error loading offers: {e}")
        return result


class SupplierOrderRepository(BaseRepository):
    """Repository for SupplierOrder records"""

    def __init__(self, session: Session):
        super().__init__(SupplierOrder, session)

    def get_by_supplier(self, supplier_id: str) -> List[SupplierOrder]:
        try:
            return self.session.query(SupplierOrder).filter_by(supplier_id=supplier_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching orders for supplier: {e}")
            return []

    def get_by_customer(self, customer_id: str) -> List[SupplierOrder]:
        try:
            return self.session.query(SupplierOrder).filter_by(customer_id=customer_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching orders for customer: {e}")
            return []

    def load_all_as_dicts(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        try:
            for o in self.session.query(SupplierOrder).all():
                result[o.id] = o.to_dict()
        except SQLAlchemyError as e:
            logger.error(f"Error loading orders: {e}")
        return result


class SupplierDocumentRepository(BaseRepository):
    """Repository for SupplierDocument records"""

    def __init__(self, session: Session):
        super().__init__(SupplierDocument, session)

    def get_by_supplier(self, supplier_id: str) -> List[SupplierDocument]:
        try:
            return self.session.query(SupplierDocument).filter_by(supplier_id=supplier_id).all()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching documents for supplier: {e}")
            return []

    def load_all_as_dicts(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        try:
            for d in self.session.query(SupplierDocument).all():
                result[d.id] = d.to_dict()
        except SQLAlchemyError as e:
            logger.error(f"Error loading documents: {e}")
        return result


class SupplyChainLedgerRepository(BaseRepository):
    """Repository for SupplyChainLedgerEntry records"""

    def __init__(self, session: Session):
        super().__init__(SupplyChainLedgerEntry, session)

    def load_all_as_dicts(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        try:
            for e in self.session.query(SupplyChainLedgerEntry).all():
                result[e.id] = e.to_dict()
        except SQLAlchemyError as e:
            logger.error(f"Error loading ledger entries: {e}")
        return result

    def upsert_from_dict(self, entry_id: str, data: Dict[str, Any]) -> bool:
        """Create or update a ledger entry from a dict."""
        try:
            existing = self.get_by_id(entry_id)
            known_cols = {
                'id', 'entry_type', 'timestamp', 'amount', 'supplier_id',
                'customer_id', 'order_id', 'description', 'previous_hash',
                'entry_hash', 'metadata_json',
            }
            extra = {k: v for k, v in data.items() if k not in known_cols}
            metadata_json = json.dumps(extra) if extra else None

            if existing:
                existing.entry_type = data.get('entry_type', existing.entry_type)
                existing.timestamp = data.get('timestamp', existing.timestamp)
                existing.amount = data.get('amount', existing.amount)
                existing.supplier_id = data.get('supplier_id', existing.supplier_id)
                existing.customer_id = data.get('customer_id', existing.customer_id)
                existing.order_id = data.get('order_id', existing.order_id)
                existing.description = data.get('description', existing.description)
                existing.previous_hash = data.get('previous_hash', existing.previous_hash)
                existing.entry_hash = data.get('entry_hash', existing.entry_hash)
                existing.metadata_json = metadata_json or existing.metadata_json
                self.session.commit()
            else:
                obj = SupplyChainLedgerEntry(
                    id=entry_id,
                    entry_type=data.get('entry_type', ''),
                    timestamp=data.get('timestamp', ''),
                    amount=data.get('amount', 0.0),
                    supplier_id=data.get('supplier_id'),
                    customer_id=data.get('customer_id'),
                    order_id=data.get('order_id'),
                    description=data.get('description'),
                    previous_hash=data.get('previous_hash'),
                    entry_hash=data.get('entry_hash'),
                    metadata_json=metadata_json,
                )
                self.session.add(obj)
                self.session.commit()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Error upserting ledger entry {entry_id}: {e}")
            self.session.rollback()
            return False
