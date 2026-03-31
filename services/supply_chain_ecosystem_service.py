"""
PHINS Supply Chain Ecosystem Service
=====================================
Enterprise-grade invitation-only B2B supply chain management system.

Core Features:
1. INVITATION-ONLY SUPPLIER REGISTRATION
   - Invitation code generation and validation
   - Multi-tier approval workflow (auto/manual/AI-assisted)
   - B2B connection management (lawyers, doctors, pharmacies, delivery)

2. GLOBAL LOCATION-BASED MARKETPLACE
   - Co-created marketplace with supplier catalog
   - Geographic service coverage zones
   - Real-time availability and pricing

3. ADJUSTABLE MANAGEMENT FEES (COMMISSION)
   - Default 11% commission with category adjustments
   - Volume-based discounts
   - Promotional rate support

4. HEALTH WALLET & BILLING INTEGRATION
   - Direct payment from customer health wallets
   - Automated billing and settlement
   - Multi-currency support

5. DATA INTEGRITY PIPELINE
   - Cryptographic transaction ledger
   - NFT token verification
   - Real-time P&L tracking
   - Audit trail with hash chains

6. SUPPLIER-SIDE REPORTING
   - Sales analytics and forecasting
   - Delivery performance metrics
   - B2B/B2C statistics
   - Commission and payout reports

Author: PHINS Engineering Team
Version: 2.0 - Supply Chain Architecture
"""

import hashlib
import hmac
import json
import os
import secrets
import uuid
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import random

from services.delivery_provider_connectors import (
    create_delivery_provider_connector,
    DeliveryProviderConnectorError,
)


# ============================================================================
# ENUMERATIONS
# ============================================================================

class SupplierType(str, Enum):
    """B2B Supplier categories"""
    DOCTOR = "doctor"
    LAWYER = "lawyer"
    PHARMACY = "pharmacy"
    DELIVERY = "delivery"
    HOSPITAL = "hospital"
    CLINIC = "clinic"
    LABORATORY = "laboratory"
    EQUIPMENT = "equipment"
    WELLNESS = "wellness"
    FINANCIAL = "financial"
    TECH_PROVIDER = "tech_provider"
    OTHER = "other"


class InvitationStatus(str, Enum):
    """Invitation code status"""
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


class SupplierStatus(str, Enum):
    """Supplier registration status"""
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class OrderStatus(str, Enum):
    """Order/transaction status"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    DISPUTED = "disputed"


class SettlementFrequency(str, Enum):
    """Payout settlement frequency"""
    DAILY = "daily"
    WEEKLY = "weekly"
    BI_WEEKLY = "bi_weekly"
    MONTHLY = "monthly"


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class SupplierInvitation:
    """Invitation code for supplier registration"""
    code: str
    created_at: str
    created_by: str
    supplier_type: Optional[str] = None  # Restrict to specific type
    expires_at: str = ""
    max_uses: int = 1
    used_count: int = 0
    used_by: List[str] = field(default_factory=list)
    status: str = "active"
    notes: str = ""
    referrer_id: Optional[str] = None  # Existing supplier referral
    commission_override: Optional[float] = None  # Special commission rate
    
    def __post_init__(self):
        if not self.expires_at:
            self.expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    
    def is_valid(self) -> bool:
        """Check if invitation is valid for use"""
        if self.status != "active":
            return False
        if datetime.fromisoformat(self.expires_at.replace('Z', '+00:00')) < datetime.now(timezone.utc):
            return False
        if self.used_count >= self.max_uses:
            return False
        return True
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FeeSchedule:
    """Commission/management fee configuration"""
    base_commission_pct: float = 11.0  # Default 11%
    category_adjustments: Dict[str, float] = field(default_factory=dict)
    volume_discounts: List[Dict] = field(default_factory=list)
    promotional_rates: List[Dict] = field(default_factory=list)
    minimum_fee: float = 1.0  # Minimum fee per transaction
    maximum_fee_pct: float = 25.0  # Maximum fee cap
    
    def __post_init__(self):
        # Default category adjustments
        if not self.category_adjustments:
            self.category_adjustments = {
                SupplierType.DOCTOR.value: 8.0,
                SupplierType.LAWYER.value: 12.0,
                SupplierType.PHARMACY.value: 9.0,
                SupplierType.DELIVERY.value: 15.0,
                SupplierType.HOSPITAL.value: 6.0,
                SupplierType.CLINIC.value: 8.0,
                SupplierType.LABORATORY.value: 10.0,
                SupplierType.EQUIPMENT.value: 12.0,
                SupplierType.WELLNESS.value: 14.0,
                SupplierType.FINANCIAL.value: 5.0,
                SupplierType.TECH_PROVIDER.value: 15.0,
                SupplierType.OTHER.value: 11.0
            }
        # Default volume discounts
        if not self.volume_discounts:
            self.volume_discounts = [
                {"monthly_volume_min": 10000, "discount_pct": 1.0},
                {"monthly_volume_min": 50000, "discount_pct": 2.0},
                {"monthly_volume_min": 100000, "discount_pct": 3.0},
                {"monthly_volume_min": 500000, "discount_pct": 5.0}
            ]
    
    def calculate_commission(self, amount: float, supplier_type: str, 
                           monthly_volume: float = 0, promo_code: str = None) -> Dict:
        """Calculate commission for a transaction"""
        # Base rate from category
        base_rate = self.category_adjustments.get(supplier_type, self.base_commission_pct)
        
        # Apply volume discount
        volume_discount = 0
        for tier in sorted(self.volume_discounts, key=lambda x: x["monthly_volume_min"], reverse=True):
            if monthly_volume >= tier["monthly_volume_min"]:
                volume_discount = tier["discount_pct"]
                break
        
        # Apply promotional rate
        promo_discount = 0
        if promo_code:
            for promo in self.promotional_rates:
                if promo.get("code") == promo_code and promo.get("active"):
                    promo_discount = promo.get("discount_pct", 0)
                    break
        
        # Calculate final rate
        effective_rate = max(base_rate - volume_discount - promo_discount, 0)
        effective_rate = min(effective_rate, self.maximum_fee_pct)
        
        commission = amount * (effective_rate / 100)
        commission = max(commission, self.minimum_fee)
        
        return {
            "amount": amount,
            "base_rate_pct": base_rate,
            "volume_discount_pct": volume_discount,
            "promo_discount_pct": promo_discount,
            "effective_rate_pct": effective_rate,
            "commission": round(commission, 2),
            "supplier_payout": round(amount - commission, 2)
        }
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SupplyChainLedgerEntry:
    """Cryptographic ledger entry for supply chain transactions"""
    entry_id: str
    timestamp: str
    entry_type: str  # order, payment, settlement, refund, commission
    supplier_id: str
    customer_id: Optional[str] = None
    order_id: Optional[str] = None
    amount: float = 0.0
    commission: float = 0.0
    supplier_payout: float = 0.0
    currency: str = "USD"
    description: str = ""
    metadata: Dict = field(default_factory=dict)
    previous_hash: str = ""
    entry_hash: str = ""
    nft_token_id: Optional[str] = None
    verified: bool = True
    
    def calculate_hash(self, secret_key: str = "PHINS_SUPPLY_CHAIN_2026") -> str:
        """Generate cryptographic hash for ledger entry"""
        data = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "entry_type": self.entry_type,
            "supplier_id": self.supplier_id,
            "customer_id": self.customer_id,
            "order_id": self.order_id,
            "amount": self.amount,
            "commission": self.commission,
            "supplier_payout": self.supplier_payout,
            "previous_hash": self.previous_hash
        }
        message = json.dumps(data, sort_keys=True)
        return hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    
    def verify_hash(self, secret_key: str = "PHINS_SUPPLY_CHAIN_2026") -> bool:
        """Verify entry hash integrity"""
        expected = self.calculate_hash(secret_key)
        return hmac.compare_digest(self.entry_hash, expected)
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SupplierPnLReport:
    """Profit & Loss report for supplier"""
    supplier_id: str
    period_start: str
    period_end: str
    
    # Revenue
    gross_sales: float = 0.0
    refunds: float = 0.0
    net_sales: float = 0.0
    
    # Deductions
    platform_commission: float = 0.0
    payment_processing_fees: float = 0.0
    other_fees: float = 0.0
    total_deductions: float = 0.0
    
    # Payouts
    net_payout: float = 0.0
    pending_settlement: float = 0.0
    settled_amount: float = 0.0
    
    # Metrics
    total_orders: int = 0
    completed_orders: int = 0
    cancelled_orders: int = 0
    average_order_value: float = 0.0
    commission_rate_avg: float = 0.0
    
    # Performance
    delivery_on_time_pct: float = 100.0
    customer_rating_avg: float = 5.0
    dispute_rate_pct: float = 0.0
    
    generated_at: str = ""
    hash_signature: str = ""
    
    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()
    
    def calculate_totals(self):
        """Recalculate derived fields"""
        self.net_sales = self.gross_sales - self.refunds
        self.total_deductions = self.platform_commission + self.payment_processing_fees + self.other_fees
        self.net_payout = self.net_sales - self.total_deductions
        if self.total_orders > 0:
            self.average_order_value = self.net_sales / self.total_orders
    
    def to_dict(self) -> Dict:
        return asdict(self)


# ============================================================================
# MAIN SERVICE CLASS
# ============================================================================

class SupplyChainEcosystemService:
    """
    Enterprise-grade supply chain ecosystem service.
    
    Manages:
    - Invitation-only B2B supplier registration
    - Global marketplace with location-based services
    - Adjustable commission/management fees
    - Health wallet and billing integration
    - Cryptographic ledger for data integrity
    - Supplier P&L and analytics
    """
    
    def __init__(self,
                 suppliers_store: Dict = None,
                 invitations_store: Dict = None,
                 offers_store: Dict = None,
                 orders_store: Dict = None,
                 ledger_store: Dict = None,
                 health_wallets: Dict = None,
                 billing_store: Dict = None,
                 nft_ledger: Dict = None,
                 transaction_ledger: Dict = None,
                 record_transaction_func = None,
                 secret_key: str = "PHINS_SUPPLY_CHAIN_2026"):
        """Initialize supply chain ecosystem service"""
        
        # Data stores
        self.suppliers = suppliers_store if suppliers_store is not None else {}
        self.invitations = invitations_store if invitations_store is not None else {}
        self.offers = offers_store if offers_store is not None else {}
        self.orders = orders_store if orders_store is not None else {}
        self.ledger = ledger_store if ledger_store is not None else {}
        self.health_wallets = health_wallets if health_wallets is not None else {}
        self.billing = billing_store if billing_store is not None else {}
        self.nft_ledger = nft_ledger if nft_ledger is not None else {}
        self.transaction_ledger = transaction_ledger if transaction_ledger is not None else {}
        self.record_transaction = record_transaction_func
        self.secret_key = secret_key
        
        # Fee schedule (adjustable)
        self.fee_schedule = FeeSchedule()
        self.default_expense_loading_pct = 0.15
        self.default_profit_margin_pct = 0.10
        self.default_discounted_rate_pct = 0.035
        
        # Settlement tracking
        self.pending_settlements: Dict[str, List] = {}  # supplier_id -> pending payouts
        self.settlement_history: List[Dict[str, Any]] = []
        self.connector_retry_queue: List[Dict[str, Any]] = []
        self.connector_audit_log: List[Dict[str, Any]] = []
        self.delivery_shipments: Dict[str, Dict[str, Any]] = {}
        
        # Ledger chain tracking
        self.ledger_chain: List[str] = []  # List of entry hashes in order

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """Safely cast a value to float."""
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        """Safely cast a value to int."""
        if value is None:
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_text(value: Any) -> Optional[str]:
        """Return a stripped text value or None."""
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _coerce_location(value: Any) -> Optional[Dict[str, Any]]:
        """Normalize a location payload into a predictable dict."""
        if not isinstance(value, dict):
            return None
        latitude = SupplyChainEcosystemService._safe_float(value.get("latitude"), None)
        longitude = SupplyChainEcosystemService._safe_float(value.get("longitude"), None)
        if latitude is None or longitude is None:
            return None
        return {
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "address": SupplyChainEcosystemService._safe_text(value.get("address")),
            "city": SupplyChainEcosystemService._safe_text(value.get("city")),
            "state": SupplyChainEcosystemService._safe_text(value.get("state")),
            "country": SupplyChainEcosystemService._safe_text(value.get("country")),
            "postal_code": SupplyChainEcosystemService._safe_text(value.get("postal_code")),
        }

    @staticmethod
    def _build_location_from_fields(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Build a normalized location from flat payload fields."""
        payload = payload or {}
        return SupplyChainEcosystemService._coerce_location({
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "address": payload.get("address"),
            "city": payload.get("city"),
            "state": payload.get("state"),
            "country": payload.get("country"),
            "postal_code": payload.get("postal_code"),
        })

    @staticmethod
    def _distance_km(origin: Optional[Dict[str, Any]], destination: Optional[Dict[str, Any]]) -> Optional[float]:
        """Approximate geodesic distance using the haversine formula."""
        if not origin or not destination:
            return None
        lat1 = SupplyChainEcosystemService._safe_float(origin.get("latitude"), None)
        lon1 = SupplyChainEcosystemService._safe_float(origin.get("longitude"), None)
        lat2 = SupplyChainEcosystemService._safe_float(destination.get("latitude"), None)
        lon2 = SupplyChainEcosystemService._safe_float(destination.get("longitude"), None)
        if None in {lat1, lon1, lat2, lon2}:
            return None
        from math import asin, cos, radians, sin, sqrt

        radius_km = 6371.0
        d_lat = radians(lat2 - lat1)
        d_lon = radians(lon2 - lon1)
        a = (
            sin(d_lat / 2) ** 2
            + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
        )
        c = 2 * asin(min(1.0, sqrt(a)))
        return round(radius_km * c, 2)

    @staticmethod
    def _build_settlement_qr_image_url(payload: str) -> str:
        """Render a QR image through the already-allowed QR image provider."""
        return f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={quote(payload, safe='')}"

    @staticmethod
    def _get_public_base_url() -> str:
        """Resolve the externally reachable PHINS base URL used in QR flows."""
        return str(
            os.environ.get("BASE_URL", "https://phins-portal-production.up.railway.app")
        ).strip().rstrip("/")

    @classmethod
    def _build_settlement_approval_url(cls, order_id: str, qr_token: str) -> str:
        """Build a first-party approval page URL for customer settlement flows."""
        return (
            f"{cls._get_public_base_url()}/settlement-approval.html"
            f"?order_id={quote(order_id, safe='')}&token={quote(qr_token, safe='')}"
        )

    def _is_settlement_token_valid(self, order: Dict[str, Any], token: Optional[str]) -> bool:
        """Validate a public settlement token/code for an order."""
        provided = self._safe_text(token)
        if not provided:
            return False
        artifacts = self._ensure_settlement_artifacts(order)
        return provided in {
            artifacts["settlement_qr_token"],
            artifacts["settlement_code"],
            artifacts["settlement_qr_data"],
            artifacts["settlement_approval_url"],
        }

    def _remove_pending_settlement_entry(self, supplier_id: Optional[str], order_id: str) -> None:
        """Ensure an order is not left in the supplier payout queue twice."""
        if not supplier_id:
            return
        pending = self.pending_settlements.get(supplier_id, [])
        filtered = [row for row in pending if row.get("order_id") != order_id]
        if filtered:
            self.pending_settlements[supplier_id] = filtered
        elif supplier_id in self.pending_settlements:
            self.pending_settlements.pop(supplier_id, None)

    def _append_settlement_message(
        self,
        order: Dict[str, Any],
        *,
        author_role: str,
        author_id: str,
        message_type: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Append an auditable settlement message to the order thread."""
        now = datetime.now(timezone.utc).isoformat()
        message = {
            "message_id": f"MSG-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}",
            "created_at": now,
            "author_role": self._safe_text(author_role) or "system",
            "author_id": self._safe_text(author_id) or "system",
            "message_type": self._safe_text(message_type) or "note",
            "content": self._safe_text(content) or "",
            "metadata": metadata or {},
        }
        order.setdefault("settlement_messages", []).append(message)
        return message

    def _append_settlement_notification(
        self,
        order: Dict[str, Any],
        *,
        audience: str,
        recipient: str,
        subject: str,
        content: str,
        customer_id: Optional[str] = None,
        priority: str = "normal",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record a settlement notification and best-effort send an in-app copy."""
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "notification_id": f"NOTIF-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}",
            "created_at": now,
            "audience": self._safe_text(audience) or "unknown",
            "recipient": self._safe_text(recipient) or "unknown",
            "subject": self._safe_text(subject) or "PHINS settlement update",
            "content": self._safe_text(content) or "",
            "metadata": metadata or {},
        }
        order.setdefault("settlement_notifications", []).append(record)

        try:
            from services.notification_service import (
                NotificationChannel,
                NotificationPriority,
                NotificationRequest,
                get_notification_service,
            )

            priority_value = NotificationPriority.HIGH if str(priority).strip().lower() == "high" else NotificationPriority.NORMAL
            result = get_notification_service().send(NotificationRequest(
                channel=NotificationChannel.IN_APP,
                recipient=record["recipient"],
                subject=record["subject"],
                content=record["content"],
                priority=priority_value,
                customer_id=customer_id,
                user_id=record["recipient"],
                metadata={
                    **(metadata or {}),
                    "order_id": order.get("id"),
                    "settlement_status": order.get("settlement_status"),
                    "audience": record["audience"],
                },
            ))
            record["delivery"] = result.to_dict()
        except Exception as exc:
            record["delivery_error"] = str(exc)

        return record

    def _notify_settlement_participants(
        self,
        order: Dict[str, Any],
        *,
        event_type: str,
        subject: str,
        content: str,
        actor: Optional[str] = None,
        priority: str = "normal",
        include_customer: bool = True,
        include_supplier: bool = True,
        include_admin: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Broadcast a settlement event to the relevant in-app audiences."""
        payload = {
            "event_type": self._safe_text(event_type) or "settlement_update",
            "actor": self._safe_text(actor),
            **(metadata or {}),
        }
        customer_id = self._safe_text(order.get("customer_id"))
        supplier_id = self._safe_text(order.get("supplier_id"))
        if include_customer and customer_id:
            self._append_settlement_notification(
                order,
                audience="customer",
                recipient=customer_id,
                subject=subject,
                content=content,
                customer_id=customer_id,
                priority=priority,
                metadata=payload,
            )
        if include_supplier and supplier_id:
            self._append_settlement_notification(
                order,
                audience="supplier",
                recipient=f"supplier:{supplier_id}",
                subject=subject,
                content=content,
                priority=priority,
                metadata=payload,
            )
        if include_admin:
            self._append_settlement_notification(
                order,
                audience="admin",
                recipient="admin:settlements",
                subject=subject,
                content=content,
                priority=priority,
                metadata=payload,
            )

    def _build_settlement_snapshot(
        self,
        order: Dict[str, Any],
        *,
        include_notifications: bool = True,
    ) -> Dict[str, Any]:
        """Expose a safe settlement-centric view of an order."""
        supplier = self.suppliers.get(order.get("supplier_id"), {}) if isinstance(order.get("supplier_id"), str) else {}
        settlement_request = order.get("settlement_request") if isinstance(order.get("settlement_request"), dict) else {}
        customer_approval = order.get("customer_approval") if isinstance(order.get("customer_approval"), dict) else {}
        delivery_validation = order.get("delivery_validation") if isinstance(order.get("delivery_validation"), dict) else {}
        settlement_dispute = order.get("settlement_dispute") if isinstance(order.get("settlement_dispute"), dict) else {}
        return {
            "order_id": order.get("id"),
            "supplier_id": order.get("supplier_id"),
            "supplier_name": supplier.get("company_name") or order.get("supplier_name") or order.get("supplier_id"),
            "customer_id": order.get("customer_id"),
            "customer_name": order.get("customer_name"),
            "item_name": order.get("item_name"),
            "order_type": order.get("order_type"),
            "currency": order.get("currency") or "USD",
            "status": order.get("status"),
            "settlement_status": order.get("settlement_status"),
            "settlement_phase": order.get("settlement_phase"),
            "amount": round(float(order.get("total_amount", 0) or 0), 2),
            "supplier_payout": round(float(order.get("supplier_payout", 0) or 0), 2),
            "settlement_code": order.get("settlement_code"),
            "settlement_qr_image_url": order.get("settlement_qr_image_url"),
            "settlement_approval_url": order.get("settlement_approval_url"),
            "settlement_request": settlement_request,
            "customer_approval": customer_approval,
            "delivery_validation": delivery_validation,
            "settlement_dispute": settlement_dispute,
            "settlement_messages": list(order.get("settlement_messages") or []),
            "settlement_notifications": (
                list(order.get("settlement_notifications") or [])
                if include_notifications
                else []
            ),
            "updated_date": order.get("updated_date"),
        }

    def _ensure_settlement_artifacts(self, order: Dict[str, Any]) -> Dict[str, str]:
        """Ensure an order has a stable settlement code and QR assets."""
        order_id = str(order.get("id") or "").strip()
        qr_token = self._safe_text(order.get("settlement_qr_token")) or secrets.token_urlsafe(10)
        settlement_code = self._safe_text(order.get("settlement_code")) or f"SET-{qr_token[:8].upper()}"
        approval_url = self._build_settlement_approval_url(order_id, qr_token)
        qr_image_url = self._build_settlement_qr_image_url(approval_url)

        order["settlement_qr_token"] = qr_token
        order["settlement_code"] = settlement_code
        order["settlement_qr_data"] = approval_url
        order["settlement_qr_image_url"] = qr_image_url
        order["settlement_approval_url"] = approval_url

        return {
            "settlement_qr_token": qr_token,
            "settlement_code": settlement_code,
            "settlement_qr_data": approval_url,
            "settlement_qr_image_url": qr_image_url,
            "settlement_approval_url": approval_url,
        }

    def _validate_customer_settlement_approval(
        self,
        *,
        order: Dict[str, Any],
        actor: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Validate the customer-side approval that releases an order into settlement."""
        payload = data or {}
        artifacts = self._ensure_settlement_artifacts(order)
        settlement_request = order.get("settlement_request") if isinstance(order.get("settlement_request"), dict) else {}
        requested_validation_type = str(
            payload.get("validation_type")
            or settlement_request.get("validation_type")
            or order.get("requested_validation_type")
            or "delivery_confirmation"
        ).strip().lower()

        provided_code = self._safe_text(
            payload.get("settlement_code")
            or payload.get("qr_token")
            or payload.get("settlement_qr_token")
            or payload.get("validation_code")
        )
        provided_pickup_code = self._safe_text(payload.get("pickup_code"))
        provided_service_pin = self._safe_text(payload.get("service_pin"))
        provided_photo = self._safe_text(payload.get("photo_url"))
        provided_recipient = self._safe_text(payload.get("recipient_name"))
        customer_acknowledged = bool(payload.get("customer_acknowledged", False))

        proof_location = (
            self._coerce_location(payload.get("delivery_location"))
            or self._coerce_location(payload.get("customer_location"))
            or self._build_location_from_fields(payload)
        )
        order_location = (
            self._coerce_location(order.get("delivery_location"))
            or self._build_location_from_fields(order.get("delivery_address"))
            or self._build_location_from_fields(order)
        )

        token_valid = bool(
            provided_code and (
                provided_code == artifacts["settlement_qr_token"]
                or provided_code == artifacts["settlement_code"]
                or provided_code == artifacts["settlement_qr_data"]
            )
        )

        requires_geo = requested_validation_type in {"pod_and_geo", "photo_and_geo", "geo_checkin", "qr_geo"}
        distance_km = self._distance_km(order_location, proof_location) if order_location and proof_location else None
        max_distance_km = 0.5 if requested_validation_type == "geo_checkin" else 1.5
        geo_valid = (order_location is None) or (
            proof_location is not None
            and distance_km is not None
            and distance_km <= max_distance_km
        )

        reasons: List[str] = []
        if requires_geo and not geo_valid:
            reasons.append("Customer approval location is outside the allowed validation radius")
        if requested_validation_type == "photo_and_geo" and not provided_photo:
            reasons.append("Photo proof is required for this settlement approval")

        fulfillment_kind = str(order.get("fulfillment_kind") or "").strip().lower() or (
            "service" if str(order.get("order_type") or "").strip().lower() == "service" else "delivery"
        )

        valid = False
        if requested_validation_type == "pickup_code":
            expected = self._safe_text(order.get("delivery_validation_code"))
            valid = bool((expected and provided_pickup_code and expected == provided_pickup_code) or token_valid)
            if not valid:
                reasons.append("Pickup code or PHINS settlement code is required")
        elif requested_validation_type == "digital_attestation":
            valid = bool(token_valid or customer_acknowledged or provided_service_pin)
            if not valid:
                reasons.append("Service approval requires customer acknowledgement, service PIN, or QR settlement code")
        elif requested_validation_type in {"pod_and_geo", "photo_and_geo", "geo_checkin", "qr_geo"}:
            valid = bool((token_valid or customer_acknowledged or provided_recipient) and geo_valid)
            if not valid and not reasons:
                reasons.append("Delivery approval requires QR confirmation or acknowledgement near the destination")
        else:
            valid = bool(token_valid or customer_acknowledged or provided_recipient or provided_service_pin)
            if not valid:
                reasons.append("Customer acknowledgement or PHINS settlement code is required")

        if fulfillment_kind == "service" and str(order.get("delivery_method") or "").strip().lower() == "on_site_visit":
            if order_location and not geo_valid:
                valid = False
                if "Customer approval location is outside the allowed validation radius" not in reasons:
                    reasons.append("On-site services require customer approval near the booked service location")

        if not valid:
            raise ValueError("; ".join(reasons) or "Settlement approval validation failed")

        proof = {
            "validation_type": requested_validation_type,
            "confirmed_by": self._safe_text(payload.get("confirmed_by")) or actor,
            "recipient_name": provided_recipient,
            "pickup_code": provided_pickup_code,
            "service_pin": provided_service_pin,
            "photo_url": provided_photo,
            "customer_acknowledged": customer_acknowledged,
            "notes": self._safe_text(payload.get("notes")),
            "delivery_location": proof_location,
            "settlement_code_validated": token_valid,
            "approval_target": fulfillment_kind,
        }
        if distance_km is not None:
            proof["distance_from_destination_km"] = distance_km
        return proof

    def _build_delivery_plan(
        self,
        *,
        supplier: Dict[str, Any],
        offer: Dict[str, Any],
        order_payload: Dict[str, Any],
        quantity: int,
    ) -> Dict[str, Any]:
        """Create location-aware delivery options and an AI-style recommended method."""
        supplier_location = self._build_location_from_fields(supplier)
        requested_location = self._coerce_location(order_payload.get("delivery_location"))
        if not requested_location:
            requested_location = self._build_location_from_fields(order_payload.get("delivery_address"))
        if not requested_location:
            requested_location = self._build_location_from_fields(order_payload)

        delivery_config = offer.get("delivery_config") if isinstance(offer.get("delivery_config"), dict) else {}
        item_type = str(offer.get("item_type") or "product").strip().lower()
        default_mode = str(delivery_config.get("mode") or ("on_site" if item_type == "service" else "delivery")).strip().lower()
        service_radius_km = max(
            1.0,
            self._safe_float(
                delivery_config.get("service_radius_km", supplier.get("service_radius_km", 50)),
                50.0,
            ),
        )
        distance_km = self._distance_km(supplier_location, requested_location)

        possible_methods: List[Dict[str, Any]] = []

        def add_method(method_id: str, label: str, *, available: bool, reason: Optional[str], eta_days: int, fee: float, validation_type: str) -> None:
            possible_methods.append({
                "method": method_id,
                "label": label,
                "available": available,
                "reason": reason,
                "eta_days": max(0, eta_days),
                "fee": round(max(0.0, fee), 2),
                "validation_type": validation_type,
            })

        base_eta = max(0, self._safe_int(delivery_config.get("eta_days"), 0))
        base_fee = round(max(0.0, self._safe_float(delivery_config.get("fee"), 0.0)), 2)

        if item_type == "service":
            on_site_available = (
                default_mode in {"on_site", "digital", "pickup", "delivery"}
                and (distance_km is None or distance_km <= service_radius_km)
            )
            add_method(
                "on_site_visit",
                "On-site visit",
                available=on_site_available,
                reason=None if on_site_available else f"Service address is outside supplier radius ({service_radius_km:.0f} km)",
                eta_days=max(0, base_eta),
                fee=base_fee,
                validation_type="geo_checkin",
            )
            add_method(
                "telehealth_video",
                "Telehealth / video session",
                available=True,
                reason=None,
                eta_days=0,
                fee=0.0,
                validation_type="digital_attestation",
            )
        else:
            delivery_available = distance_km is None or distance_km <= service_radius_km
            add_method(
                "courier_delivery",
                "Courier delivery",
                available=delivery_available,
                reason=None if delivery_available else f"Destination is outside supplier delivery radius ({service_radius_km:.0f} km)",
                eta_days=max(1, base_eta or 1),
                fee=base_fee,
                validation_type="pod_and_geo",
            )
            add_method(
                "pickup_counter",
                "Pickup / collection",
                available=True,
                reason=None,
                eta_days=0,
                fee=0.0,
                validation_type="pickup_code",
            )

        same_day_available = (
            distance_km is not None
            and distance_km <= min(service_radius_km, 15.0)
            and quantity <= 3
        )
        add_method(
            "same_day_priority",
            "Same-day priority",
            available=same_day_available,
            reason=None if same_day_available else "Available for nearby small orders only",
            eta_days=0,
            fee=round(base_fee + 12.0, 2),
            validation_type="photo_and_geo",
        )

        requested_method = str(
            order_payload.get("delivery_method")
            or order_payload.get("delivery_mode")
            or default_mode
        ).strip().lower()

        recommended = next((m for m in possible_methods if m["method"] == requested_method and m["available"]), None)
        if not recommended:
            if item_type == "service":
                preferred_order = ["on_site_visit", "telehealth_video", "same_day_priority"]
            else:
                preferred_order = ["courier_delivery", "same_day_priority", "pickup_counter"]
            for method_id in preferred_order:
                recommended = next((m for m in possible_methods if m["method"] == method_id and m["available"]), None)
                if recommended:
                    break
        if not recommended and possible_methods:
            recommended = possible_methods[0]

        recommended = dict(recommended or {})
        recommended["ai_reasoning"] = (
            f"Recommended {recommended.get('label', 'delivery method')} based on "
            f"{'distance ' + str(distance_km) + ' km, ' if distance_km is not None else ''}"
            f"{item_type} fulfillment constraints and supplier coverage."
        ) if recommended else "No viable delivery recommendation available."

        return {
            "supplier_location": supplier_location,
            "requested_location": requested_location,
            "distance_km": distance_km,
            "service_radius_km": round(service_radius_km, 2),
            "possible_methods": possible_methods,
            "recommended_method": recommended,
        }

    def recommend_delivery_options(
        self,
        *,
        supplier_id: str,
        offer_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return location-aware delivery recommendations before checkout."""
        supplier = self.suppliers.get(supplier_id)
        if not supplier:
            raise ValueError(f"Supplier {supplier_id} not found")
        offer = self.offers.get(offer_id)
        if not offer:
            raise ValueError(f"Offer {offer_id} not found")
        if offer.get("supplier_id") != supplier_id:
            raise ValueError("Offer does not belong to requested supplier")

        payload = data or {}
        quantity = max(1, self._safe_int(payload.get("quantity"), 1))
        delivery_plan = self._build_delivery_plan(
            supplier=supplier,
            offer=offer,
            order_payload=payload,
            quantity=quantity,
        )
        return {
            "success": True,
            "supplier_id": supplier_id,
            "offer_id": offer_id,
            "delivery_plan": delivery_plan,
        }

    def validate_delivery_completion(
        self,
        *,
        order_id: str,
        actor: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Validate customer approval and release an order into settlement."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")

        payload = data or {}
        order = self.orders[order_id]
        current_status = str(order.get("status") or "").strip().lower()
        if current_status not in {
            OrderStatus.CONFIRMED.value,
            OrderStatus.PROCESSING.value,
            OrderStatus.IN_TRANSIT.value,
            OrderStatus.DELIVERED.value,
        }:
            raise ValueError(f"Order {order_id} is not in a deliverable status")
        settlement_status = str(order.get("settlement_status") or "").strip().lower()
        if settlement_status not in {"awaiting_customer_approval", "customer_approved", "pending_admin_payout"}:
            raise ValueError("Supplier must request settlement approval before customer validation can release funds")

        proof = self._validate_customer_settlement_approval(order=order, actor=actor, data=payload)

        now = datetime.now(timezone.utc).isoformat()
        order["actual_delivery"] = now
        order["updated_date"] = now
        order["settlement_status"] = "customer_approved"
        order["settlement_phase"] = "ready_for_payout"
        order["customer_approval"] = {
            "approved": True,
            "approved_at": now,
            "approved_by": actor,
            "approval_target": proof.get("approval_target"),
            "proof": proof,
        }
        order["settlement_dispute"] = {}
        order["delivery_validation"] = {
            "validated": True,
            "validated_at": now,
            "validated_by": actor,
            "method": proof.get("validation_type"),
            "proof": proof,
        }
        if str(order.get("status") or "").strip().lower() != OrderStatus.DELIVERED.value:
            order["status"] = OrderStatus.DELIVERED.value

        self._append_settlement_message(
            order,
            author_role="customer",
            author_id=actor,
            message_type="approval",
            content=self._safe_text(payload.get("notes")) or "Customer approved the settlement request",
            metadata={
                "validation_type": proof.get("validation_type"),
                "settlement_code_validated": proof.get("settlement_code_validated"),
            },
        )
        self._notify_settlement_participants(
            order,
            event_type="settlement_approved",
            subject=f"Settlement approved for order {order_id}",
            content=(
                f"Customer approval was recorded for {order.get('item_name') or order_id}. "
                "The order has moved to pending admin payout."
            ),
            actor=actor,
            priority="normal",
            metadata={
                "validation_type": proof.get("validation_type"),
                "approval_target": proof.get("approval_target"),
            },
        )

        self._record_ledger_entry(
            entry_type="delivery_validated",
            supplier_id=order["supplier_id"],
            customer_id=order.get("customer_id"),
            order_id=order_id,
            amount=order.get("total_amount", 0.0),
            commission=order.get("commission", 0.0),
            supplier_payout=order.get("supplier_payout", 0.0),
            description=f"Delivery validated for order {order_id}",
            metadata={
                "validated_by": actor,
                "validation_type": proof.get("validation_type"),
                "proof_summary": {
                    "recipient_name": proof.get("recipient_name"),
                    "photo_url": proof.get("photo_url"),
                    "pickup_code": bool(proof.get("pickup_code")),
                    "customer_acknowledged": proof.get("customer_acknowledged"),
                },
            }
        )

        # Successful proof validation finalizes fulfillment and moves the order into settlement flow.
        completion_result = self.complete_order(order_id, completed_by=actor)
        completion_result.get("order", {}).setdefault("delivery_validation", order["delivery_validation"])

        return {
            "success": True,
            "order": completion_result.get("order", order),
            "validation": completion_result.get("order", order).get("delivery_validation", order["delivery_validation"]),
            "message": f"Delivery validated for order {order_id}",
        }

    def request_settlement_release(
        self,
        *,
        order_id: str,
        actor: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Supplier-side request that asks the customer to release settlement."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")

        payload = data or {}
        order = self.orders[order_id]
        current_status = str(order.get("status") or "").strip().lower()
        if current_status in {OrderStatus.CANCELLED.value, OrderStatus.REFUNDED.value, OrderStatus.COMPLETED.value}:
            raise ValueError("Settlement cannot be requested for this order")
        if str(order.get("payment_status") or "").strip().lower() != "paid":
            raise ValueError("Settlement can only be requested after payment is secured")

        fulfillment_kind = str(order.get("fulfillment_kind") or "").strip().lower() or (
            "service" if str(order.get("order_type") or "").strip().lower() == "service" else "delivery"
        )
        allowed_statuses = {
            "service": {
                OrderStatus.CONFIRMED.value,
                OrderStatus.PROCESSING.value,
                OrderStatus.DELIVERED.value,
            },
            "delivery": {
                OrderStatus.PROCESSING.value,
                OrderStatus.IN_TRANSIT.value,
                OrderStatus.DELIVERED.value,
            },
        }
        if current_status not in allowed_statuses.get(fulfillment_kind, set()):
            raise ValueError(
                "Settlement can be requested only after supplier fulfillment has started"
            )

        artifacts = self._ensure_settlement_artifacts(order)
        now = datetime.now(timezone.utc).isoformat()
        validation_type = str(
            payload.get("validation_type")
            or (order.get("delivery_plan") or {}).get("recommended_method", {}).get("validation_type")
            or ("digital_attestation" if fulfillment_kind == "service" else "pod_and_geo")
        ).strip().lower()

        order["settlement_status"] = "awaiting_customer_approval"
        order["settlement_phase"] = "awaiting_customer_approval"
        order["requested_validation_type"] = validation_type
        order["settlement_request"] = {
            "requested": True,
            "requested_at": now,
            "requested_by": actor,
            "notes": self._safe_text(payload.get("notes")),
            "validation_type": validation_type,
            "fulfillment_kind": fulfillment_kind,
            "supplier_location": (
                self._coerce_location(payload.get("supplier_location"))
                or self._build_location_from_fields(payload)
                or self._build_location_from_fields(self.suppliers.get(order.get("supplier_id")))
            ),
            "settlement_code": artifacts["settlement_code"],
            "settlement_qr_data": artifacts["settlement_qr_data"],
            "settlement_qr_image_url": artifacts["settlement_qr_image_url"],
            "settlement_approval_url": artifacts["settlement_approval_url"],
        }
        order["updated_date"] = now
        order["settlement_dispute"] = {}
        self._append_settlement_message(
            order,
            author_role="supplier",
            author_id=actor,
            message_type="request",
            content=self._safe_text(payload.get("notes")) or "Supplier requested customer settlement approval",
            metadata={
                "validation_type": validation_type,
                "settlement_code": artifacts["settlement_code"],
            },
        )
        self._notify_settlement_participants(
            order,
            event_type="settlement_requested",
            subject=f"Customer approval requested for order {order_id}",
            content=(
                f"Supplier settlement approval is waiting for customer action on "
                f"{order.get('item_name') or order_id}."
            ),
            actor=actor,
            priority="normal",
            metadata={
                "validation_type": validation_type,
                "settlement_approval_url": artifacts["settlement_approval_url"],
            },
        )

        self._record_ledger_entry(
            entry_type="settlement_requested",
            supplier_id=order["supplier_id"],
            customer_id=order.get("customer_id"),
            order_id=order_id,
            amount=order.get("total_amount", 0.0),
            commission=order.get("commission", 0.0),
            supplier_payout=order.get("supplier_payout", 0.0),
            description=f"Settlement requested for order {order_id}",
            metadata={
                "requested_by": actor,
                "validation_type": validation_type,
                "fulfillment_kind": fulfillment_kind,
                "settlement_code": artifacts["settlement_code"],
                "settlement_approval_url": artifacts["settlement_approval_url"],
            },
        )

        return {
            "success": True,
            "order": order,
            "message": f"Customer approval requested for order {order_id}",
        }

    def approve_order_settlement(
        self,
        *,
        order_id: str,
        actor: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Customer-facing alias for settlement approval and validation."""
        return self.validate_delivery_completion(order_id=order_id, actor=actor, data=data)

    def dispute_order_settlement(
        self,
        *,
        order_id: str,
        actor: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Place a settlement request into dispute for admin resolution."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")

        payload = data or {}
        order = self.orders[order_id]
        settlement_status = str(order.get("settlement_status") or "").strip().lower()
        if settlement_status not in {"awaiting_customer_approval", "settlement_dispute"}:
            raise ValueError("Only pending customer settlement approvals can be disputed")

        token = (
            payload.get("settlement_token")
            or payload.get("token")
            or payload.get("settlement_code")
            or payload.get("qr_token")
        )
        if token and not self._is_settlement_token_valid(order, token):
            raise ValueError("Invalid settlement token for this order")

        dispute_reason = self._safe_text(payload.get("reason")) or "Customer raised a settlement dispute"
        dispute_notes = self._safe_text(payload.get("notes"))
        dispute_category = self._safe_text(payload.get("category")) or "general"
        now = datetime.now(timezone.utc).isoformat()

        order["settlement_status"] = "settlement_dispute"
        order["settlement_phase"] = "awaiting_admin_resolution"
        order["updated_date"] = now
        order["settlement_dispute"] = {
            "open": True,
            "disputed_at": now,
            "disputed_by": actor,
            "reason": dispute_reason,
            "notes": dispute_notes,
            "category": dispute_category,
            "customer_requested_action": self._safe_text(payload.get("requested_action")) or "admin_review",
            "status": "open",
            "evidence": payload.get("evidence") if isinstance(payload.get("evidence"), list) else [],
            "admin_resolution": None,
        }
        self._remove_pending_settlement_entry(order.get("supplier_id"), order_id)

        self._append_settlement_message(
            order,
            author_role="customer",
            author_id=actor,
            message_type="dispute",
            content=dispute_notes or dispute_reason,
            metadata={
                "category": dispute_category,
                "requested_action": order["settlement_dispute"]["customer_requested_action"],
            },
        )
        self._notify_settlement_participants(
            order,
            event_type="settlement_disputed",
            subject=f"Settlement dispute opened for order {order_id}",
            content=(
                f"A customer dispute was submitted for {order.get('item_name') or order_id}. "
                "Admin review is required before payout can continue."
            ),
            actor=actor,
            priority="high",
            metadata={
                "category": dispute_category,
                "reason": dispute_reason,
            },
        )

        self._record_ledger_entry(
            entry_type="settlement_disputed",
            supplier_id=order["supplier_id"],
            customer_id=order.get("customer_id"),
            order_id=order_id,
            amount=order.get("total_amount", 0.0),
            commission=order.get("commission", 0.0),
            supplier_payout=order.get("supplier_payout", 0.0),
            description=f"Settlement disputed for order {order_id}",
            metadata={
                "disputed_by": actor,
                "reason": dispute_reason,
                "category": dispute_category,
            },
        )

        return {
            "success": True,
            "order": order,
            "dispute": order["settlement_dispute"],
            "message": f"Settlement dispute recorded for order {order_id}",
        }

    def resolve_settlement_dispute(
        self,
        *,
        order_id: str,
        actor: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resolve a disputed settlement by approving or rejecting the dispute."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")

        payload = data or {}
        order = self.orders[order_id]
        dispute = order.get("settlement_dispute") if isinstance(order.get("settlement_dispute"), dict) else {}
        if not dispute or not dispute.get("open"):
            raise ValueError("This order does not have an open settlement dispute")

        resolution = str(payload.get("resolution") or "").strip().lower()
        if resolution not in {"approve_settlement", "reject_settlement", "request_more_info"}:
            raise ValueError("resolution must be one of approve_settlement, reject_settlement, request_more_info")

        resolution_notes = self._safe_text(payload.get("notes"))
        now = datetime.now(timezone.utc).isoformat()
        dispute["open"] = resolution == "request_more_info"
        dispute["status"] = "awaiting_more_info" if resolution == "request_more_info" else "resolved"
        dispute["admin_resolution"] = {
            "resolution": resolution,
            "resolved_at": now,
            "resolved_by": actor,
            "notes": resolution_notes,
        }
        order["updated_date"] = now

        self._append_settlement_message(
            order,
            author_role="admin",
            author_id=actor,
            message_type="resolution",
            content=resolution_notes or f"Admin marked dispute as {resolution}",
            metadata={"resolution": resolution},
        )

        if resolution == "approve_settlement":
            order["settlement_status"] = "customer_approved"
            order["settlement_phase"] = "ready_for_payout"
            order["customer_approval"] = {
                "approved": True,
                "approved_at": now,
                "approved_by": actor,
                "approval_target": "admin_override",
                "proof": {
                    "validation_type": "admin_override",
                    "notes": resolution_notes,
                    "customer_acknowledged": False,
                },
            }
            result = self.complete_order(order_id, completed_by=actor)
            self._notify_settlement_participants(
                order,
                event_type="settlement_dispute_resolved",
                subject=f"Dispute resolved and payout resumed for order {order_id}",
                content=(
                    f"Admin resolved the settlement dispute for {order.get('item_name') or order_id} "
                    "and released the order back into payout flow."
                ),
                actor=actor,
                priority="normal",
                metadata={"resolution": resolution},
            )
            self._record_ledger_entry(
                entry_type="settlement_dispute_resolved",
                supplier_id=order["supplier_id"],
                customer_id=order.get("customer_id"),
                order_id=order_id,
                amount=order.get("total_amount", 0.0),
                commission=order.get("commission", 0.0),
                supplier_payout=order.get("supplier_payout", 0.0),
                description=f"Settlement dispute resolved with payout approval for order {order_id}",
                metadata={"resolved_by": actor, "resolution": resolution},
            )
            return {
                "success": True,
                "order": result.get("order", order),
                "dispute": dispute,
                "message": f"Settlement dispute resolved for order {order_id}",
            }

        if resolution == "reject_settlement":
            order["settlement_status"] = "settlement_rejected"
            order["settlement_phase"] = "closed_after_dispute"
            order["status"] = OrderStatus.DISPUTED.value
            self._notify_settlement_participants(
                order,
                event_type="settlement_dispute_rejected",
                subject=f"Settlement payout blocked for order {order_id}",
                content=(
                    f"Admin resolved the settlement dispute for {order.get('item_name') or order_id} "
                    "by rejecting the payout. Further manual action is required."
                ),
                actor=actor,
                priority="high",
                metadata={"resolution": resolution},
            )
            self._record_ledger_entry(
                entry_type="settlement_dispute_resolved",
                supplier_id=order["supplier_id"],
                customer_id=order.get("customer_id"),
                order_id=order_id,
                amount=order.get("total_amount", 0.0),
                commission=order.get("commission", 0.0),
                supplier_payout=order.get("supplier_payout", 0.0),
                description=f"Settlement dispute resolved with payout rejection for order {order_id}",
                metadata={"resolved_by": actor, "resolution": resolution},
            )
            return {
                "success": True,
                "order": order,
                "dispute": dispute,
                "message": f"Settlement dispute resolved for order {order_id}",
            }

        order["settlement_status"] = "settlement_dispute"
        order["settlement_phase"] = "awaiting_customer_response"
        self._notify_settlement_participants(
            order,
            event_type="settlement_dispute_more_info",
            subject=f"More information requested for order {order_id}",
            content=(
                f"Admin requested more information to resolve the settlement dispute for "
                f"{order.get('item_name') or order_id}."
            ),
            actor=actor,
            priority="high",
            metadata={"resolution": resolution},
        )
        return {
            "success": True,
            "order": order,
            "dispute": dispute,
            "message": f"Additional customer information requested for order {order_id}",
        }

    def add_settlement_message(
        self,
        *,
        order_id: str,
        actor_role: str,
        actor_id: str,
        content: str,
        message_type: str = "note",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Append a discussion message to an order's settlement thread."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")
        if not self._safe_text(content):
            raise ValueError("content is required")

        order = self.orders[order_id]
        message = self._append_settlement_message(
            order,
            author_role=actor_role,
            author_id=actor_id,
            message_type=message_type,
            content=content,
            metadata=metadata,
        )
        order["updated_date"] = datetime.now(timezone.utc).isoformat()
        self._notify_settlement_participants(
            order,
            event_type="settlement_message",
            subject=f"New settlement message for order {order_id}",
            content=content,
            actor=actor_id,
            priority="normal",
            metadata={"message_type": message_type},
        )
        return {
            "success": True,
            "message": message,
            "order": order,
        }

    def get_settlement_thread(self, order_id: str) -> Dict[str, Any]:
        """Return the settlement thread/messages for a single order."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")
        order = self.orders[order_id]
        return {
            "success": True,
            "thread": self._build_settlement_snapshot(order),
        }

    def get_public_settlement_detail(
        self,
        *,
        order_id: str,
        token: str,
    ) -> Dict[str, Any]:
        """Return settlement detail for a QR-scanned public approval page."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")
        order = self.orders[order_id]
        if not self._is_settlement_token_valid(order, token):
            raise ValueError("Invalid settlement token for this order")
        return {
            "success": True,
            "settlement": self._build_settlement_snapshot(
                order,
                include_notifications=False,
            ),
        }

    def get_settlement_disputes(
        self,
        supplier_id: Optional[str] = None,
        *,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return disputed settlement orders for admin or supplier review."""
        items: List[Dict[str, Any]] = []
        normalized_status = self._safe_text(status)
        for order in self.orders.values():
            if supplier_id and order.get("supplier_id") != supplier_id:
                continue
            dispute = order.get("settlement_dispute") if isinstance(order.get("settlement_dispute"), dict) else {}
            if not dispute:
                continue
            if normalized_status and str(dispute.get("status") or "").strip().lower() != normalized_status.lower():
                continue
            snapshot = self._build_settlement_snapshot(order)
            snapshot["dispute_status"] = dispute.get("status")
            items.append(snapshot)
        items.sort(
            key=lambda item: ((item.get("settlement_dispute") or {}).get("disputed_at") or item.get("updated_date") or ""),
            reverse=True,
        )
        return {
            "success": True,
            "items": items,
            "total": len(items),
        }

    def get_customer_pending_approvals(self, customer_id: str) -> Dict[str, Any]:
        """Return orders awaiting the customer's settlement approval."""
        items: List[Dict[str, Any]] = []
        for order in self.orders.values():
            if order.get("customer_id") != customer_id:
                continue
            if str(order.get("settlement_status") or "").strip().lower() != "awaiting_customer_approval":
                continue
            artifacts = self._ensure_settlement_artifacts(order)
            settlement_request = order.get("settlement_request") if isinstance(order.get("settlement_request"), dict) else {}
            items.append({
                "order_id": order.get("id"),
                "supplier_id": order.get("supplier_id"),
                "customer_id": customer_id,
                "item_name": order.get("item_name"),
                "order_type": order.get("order_type"),
                "amount": round(float(order.get("total_amount", 0) or 0), 2),
                "supplier_payout": round(float(order.get("supplier_payout", 0) or 0), 2),
                "status": order.get("status"),
                "settlement_status": order.get("settlement_status"),
                "validation_type": settlement_request.get("validation_type"),
                "requested_at": settlement_request.get("requested_at"),
                "notes": settlement_request.get("notes"),
                "settlement_code": artifacts["settlement_code"],
                "settlement_qr_data": artifacts["settlement_qr_data"],
                "settlement_qr_image_url": artifacts["settlement_qr_image_url"],
                "settlement_approval_url": artifacts["settlement_approval_url"],
                "settlement_messages": list(order.get("settlement_messages") or []),
                "settlement_dispute": order.get("settlement_dispute") if isinstance(order.get("settlement_dispute"), dict) else {},
            })
        items.sort(key=lambda x: x.get("requested_at") or "", reverse=True)
        return {
            "success": True,
            "customer_id": customer_id,
            "items": items,
            "total": len(items),
        }

    def get_supplier_pending_releases(self, supplier_id: str) -> Dict[str, Any]:
        """Return supplier orders that are waiting for customer approval."""
        items: List[Dict[str, Any]] = []
        for order in self.orders.values():
            if order.get("supplier_id") != supplier_id:
                continue
            if str(order.get("settlement_status") or "").strip().lower() != "awaiting_customer_approval":
                continue
            settlement_request = order.get("settlement_request") if isinstance(order.get("settlement_request"), dict) else {}
            items.append({
                "order_id": order.get("id"),
                "customer_id": order.get("customer_id"),
                "item_name": order.get("item_name"),
                "amount": round(float(order.get("supplier_payout", 0) or 0), 2),
                "requested_at": settlement_request.get("requested_at"),
                "validation_type": settlement_request.get("validation_type"),
                "settlement_code": order.get("settlement_code"),
                "settlement_approval_url": order.get("settlement_approval_url"),
                "settlement_dispute": order.get("settlement_dispute") if isinstance(order.get("settlement_dispute"), dict) else {},
            })
        items.sort(key=lambda x: x.get("requested_at") or "", reverse=True)
        return {
            "success": True,
            "supplier_id": supplier_id,
            "items": items,
            "total": len(items),
        }

    @staticmethod
    def _normalize_percentage(value: Any, default_value: float) -> float:
        """
        Normalize percentages supplied as either decimal (0.1) or percent (10).
        """
        raw = default_value if value is None else SupplyChainEcosystemService._safe_float(value, default_value)
        if abs(raw) > 1:
            raw = raw / 100.0
        return raw

    def _build_pricing_plan(self, base_amount: float, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Compute pricing components used across wallet/card purchases:
        expense loading, profit margin, and discounted rate.
        """
        payload = overrides or {}
        base = round(max(self._safe_float(base_amount, 0.0), 0.0), 2)

        expense_loading_pct = self._normalize_percentage(
            payload.get("expense_loading_pct"), self.default_expense_loading_pct
        )
        profit_margin_pct = self._normalize_percentage(
            payload.get("profit_margin_pct"), self.default_profit_margin_pct
        )
        discounted_rate_pct = self._normalize_percentage(
            payload.get("discounted_rate_pct"), self.default_discounted_rate_pct
        )

        expense_loading_amount = round(base * expense_loading_pct, 2)
        subtotal_before_profit = round(base + expense_loading_amount, 2)
        profit_margin_amount = round(subtotal_before_profit * profit_margin_pct, 2)
        gross_before_discount = round(subtotal_before_profit + profit_margin_amount, 2)
        discounted_rate_amount = round(gross_before_discount * discounted_rate_pct, 2)
        final_customer_amount = round(max(gross_before_discount - discounted_rate_amount, 0.0), 2)

        return {
            "base_amount": base,
            "expense_loading_pct": round(expense_loading_pct, 6),
            "expense_loading_amount": expense_loading_amount,
            "profit_margin_pct": round(profit_margin_pct, 6),
            "profit_margin_amount": profit_margin_amount,
            "discounted_rate_pct": round(discounted_rate_pct, 6),
            "discounted_rate_amount": discounted_rate_amount,
            "gross_before_discount": gross_before_discount,
            "final_customer_amount": final_customer_amount
        }

    @staticmethod
    def _normalize_payment_method(raw_method: Any) -> str:
        """Normalize payment method aliases into canonical values."""
        method = str(raw_method or "health_wallet").strip().lower()
        aliases = {
            "wallet": "health_wallet",
            "health": "health_wallet",
            "card": "credit_card",
            "credit": "credit_card",
            "debit": "debit_card",
            "bank": "bank_transfer",
            "ach": "bank_transfer"
        }
        return aliases.get(method, method)
    
    # =========================================================================
    # INVITATION MANAGEMENT
    # =========================================================================
    
    def generate_invitation_code(self,
                                created_by: str,
                                supplier_type: str = None,
                                max_uses: int = 1,
                                expires_days: int = 30,
                                referrer_id: str = None,
                                commission_override: float = None,
                                notes: str = "") -> Dict[str, Any]:
        """
        Generate a new supplier invitation code.
        
        Args:
            created_by: Admin or referrer creating the code
            supplier_type: Restrict to specific supplier type (optional)
            max_uses: Maximum number of registrations allowed
            expires_days: Days until expiration
            referrer_id: If referred by existing supplier
            commission_override: Special commission rate for this invite
            notes: Internal notes
        
        Returns:
            Invitation details with code
        """
        # Generate unique code
        code = f"PHINS-SUP-{datetime.now().strftime('%Y%m')}-{secrets.token_hex(4).upper()}"
        
        # Ensure uniqueness
        while code in self.invitations:
            code = f"PHINS-SUP-{datetime.now().strftime('%Y%m')}-{secrets.token_hex(4).upper()}"
        
        now = datetime.now(timezone.utc)
        invitation = SupplierInvitation(
            code=code,
            created_at=now.isoformat(),
            created_by=created_by,
            supplier_type=supplier_type,
            expires_at=(now + timedelta(days=expires_days)).isoformat(),
            max_uses=max_uses,
            referrer_id=referrer_id,
            commission_override=commission_override,
            notes=notes
        )
        
        self.invitations[code] = invitation
        
        return {
            "success": True,
            "invitation": invitation.to_dict(),
            "message": f"Invitation code generated: {code}"
        }
    
    def validate_invitation_code(self, code: str) -> Dict[str, Any]:
        """
        Validate an invitation code for supplier registration.
        
        Returns:
            Validation result with invitation details if valid
        """
        invitation = self.invitations.get(code)
        
        if not invitation:
            return {
                "valid": False,
                "error": "Invalid invitation code"
            }
        
        # Convert to SupplierInvitation if it's a dict
        if isinstance(invitation, dict):
            invitation = SupplierInvitation(**invitation)
            self.invitations[code] = invitation
        
        if not invitation.is_valid():
            if invitation.status == "revoked":
                return {"valid": False, "error": "Invitation code has been revoked"}
            if invitation.used_count >= invitation.max_uses:
                return {"valid": False, "error": "Invitation code has reached maximum uses"}
            if datetime.fromisoformat(invitation.expires_at.replace('Z', '+00:00')) < datetime.now(timezone.utc):
                return {"valid": False, "error": "Invitation code has expired"}
            return {"valid": False, "error": "Invitation code is not valid"}
        
        return {
            "valid": True,
            "invitation": invitation.to_dict(),
            "supplier_type_restriction": invitation.supplier_type,
            "commission_override": invitation.commission_override,
            "referrer_id": invitation.referrer_id
        }
    
    def use_invitation_code(self, code: str, supplier_id: str) -> bool:
        """Mark invitation code as used by a supplier"""
        invitation = self.invitations.get(code)
        if not invitation:
            return False
        
        if isinstance(invitation, dict):
            invitation = SupplierInvitation(**invitation)
            self.invitations[code] = invitation
        
        invitation.used_count += 1
        invitation.used_by.append(supplier_id)
        
        if invitation.used_count >= invitation.max_uses:
            invitation.status = "used"
        
        return True
    
    def revoke_invitation(self, code: str, revoked_by: str, reason: str = "") -> Dict[str, Any]:
        """Revoke an invitation code"""
        invitation = self.invitations.get(code)
        if not invitation:
            return {"success": False, "error": "Invitation not found"}
        
        if isinstance(invitation, dict):
            invitation = SupplierInvitation(**invitation)
            self.invitations[code] = invitation
        
        invitation.status = "revoked"
        invitation.notes = f"{invitation.notes}\nRevoked by {revoked_by}: {reason}"
        
        return {"success": True, "message": f"Invitation {code} revoked"}
    
    def get_invitations(self, status: str = None, created_by: str = None) -> List[Dict]:
        """Get invitation codes with optional filtering"""
        invitations = []
        for code, inv in self.invitations.items():
            if isinstance(inv, dict):
                inv_dict = inv
            else:
                inv_dict = inv.to_dict()
            
            if status and inv_dict.get("status") != status:
                continue
            if created_by and inv_dict.get("created_by") != created_by:
                continue
            
            invitations.append(inv_dict)
        
        return sorted(invitations, key=lambda x: x.get("created_at", ""), reverse=True)
    
    # =========================================================================
    # SUPPLIER REGISTRATION (INVITATION-ONLY)
    # =========================================================================
    
    def register_supplier(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a new supplier with invitation code.
        
        Required fields:
        - invitation_code (required)
        - company_name (required)
        - contact_email (required)
        - contact_name (required)
        - supplier_type (required)
        - password (required)
        
        Optional fields:
        - business details, address, license, etc.
        
        Returns:
            Registration result with supplier ID
        """
        # Validate invitation code
        invitation_code = data.get("invitation_code")
        if not invitation_code:
            raise ValueError("Invitation code is required for registration")
        
        validation = self.validate_invitation_code(invitation_code)
        if not validation.get("valid"):
            raise ValueError(validation.get("error", "Invalid invitation code"))
        
        invitation_data = validation.get("invitation", {})
        
        # Check supplier type restriction
        supplier_type = data.get("supplier_type")
        if invitation_data.get("supplier_type") and invitation_data["supplier_type"] != supplier_type:
            raise ValueError(f"This invitation is restricted to {invitation_data['supplier_type']} suppliers")
        
        # Validate required fields
        required = ["company_name", "contact_email", "contact_name", "supplier_type", "password"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        
        # Check for duplicate email
        for sup in self.suppliers.values():
            if isinstance(sup, dict):
                email = sup.get("contact_email", "")
            else:
                email = getattr(sup, "contact_email", "")
            if email.lower() == data["contact_email"].lower():
                raise ValueError(f"Email {data['contact_email']} is already registered")
        
        # Generate supplier ID
        supplier_id = f"SUP-{datetime.now().strftime('%Y%m')}-{secrets.token_hex(4).upper()}"
        
        # Hash password
        salt = secrets.token_hex(32)
        password_hash = hashlib.sha256(f"{data['password']}{salt}".encode()).hexdigest()
        
        # Get commission rate (use override if specified)
        commission_rate = invitation_data.get("commission_override")
        if commission_rate is None:
            commission_rate = self.fee_schedule.category_adjustments.get(
                supplier_type, self.fee_schedule.base_commission_pct
            )
        
        now = datetime.now(timezone.utc)
        
        # Build supplier record
        supplier = {
            "id": supplier_id,
            "company_name": data["company_name"].strip(),
            "contact_email": data["contact_email"].strip().lower(),
            "contact_name": data["contact_name"].strip(),
            "contact_phone": data.get("contact_phone", "").strip() or None,
            "supplier_type": supplier_type,
            "category": self._get_category_for_type(supplier_type),
            "sub_category": data.get("sub_category"),
            "description": data.get("description", "").strip() or None,
            
            # Business details
            "business_registration_number": data.get("business_registration_number"),
            "tax_id": data.get("tax_id"),
            "license_number": data.get("license_number"),
            "license_expiry": data.get("license_expiry"),
            "insurance_certificate": data.get("insurance_certificate"),
            "insurance_expiry": data.get("insurance_expiry"),
            
            # Location
            "address": data.get("address"),
            "city": data.get("city"),
            "state": data.get("state"),
            "country": data.get("country", "United States"),
            "postal_code": data.get("postal_code"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "service_radius_km": data.get("service_radius_km", 50),
            
            # Website/contact
            "website": data.get("website"),
            
            # Services/Products
            "services_offered": json.dumps(data.get("services_offered", [])),
            "products_offered": json.dumps(data.get("products_offered", [])),
            "operating_hours": json.dumps(data.get("operating_hours", {})),
            
            # Authentication
            "password_hash": password_hash,
            "password_salt": salt,
            "portal_active": False,  # Activated after approval
            "last_login": None,
            
            # Invitation tracking
            "invitation_code": invitation_code,
            "referrer_id": invitation_data.get("referrer_id"),
            
            # Status
            "status": SupplierStatus.PENDING.value,
            "application_date": now.isoformat(),
            "review_date": None,
            "approval_date": None,
            "approved_by": None,
            "rejection_reason": None,
            
            # Commission and billing
            "commission_rate": commission_rate,
            "settlement_frequency": data.get("settlement_frequency", SettlementFrequency.WEEKLY.value),
            "bank_details": json.dumps(data.get("bank_details", {})) if data.get("bank_details") else None,
            "crypto_wallet": data.get("crypto_wallet"),
            
            # Performance metrics
            "total_orders": 0,
            "completed_orders": 0,
            "total_revenue": 0.0,
            "total_commission_paid": 0.0,
            "average_rating": 0.0,
            "total_reviews": 0,
            "dispute_count": 0,
            "on_time_delivery_rate": 100.0,
            
            # B2B/B2C stats
            "b2b_orders": 0,
            "b2c_orders": 0,
            "b2b_revenue": 0.0,
            "b2c_revenue": 0.0,
            
            # Timestamps
            "created_date": now.isoformat(),
            "updated_date": now.isoformat()
        }
        
        # Perform AI risk assessment
        ai_assessment = self._assess_supplier_risk(supplier)
        supplier["ai_risk_score"] = ai_assessment["risk_score"]
        supplier["ai_trust_score"] = ai_assessment["trust_score"]
        supplier["ai_recommendation"] = ai_assessment["recommendation"]
        supplier["ai_assessment_date"] = now.isoformat()
        supplier["ai_assessment_notes"] = json.dumps(ai_assessment["notes"])
        
        # Store supplier
        self.suppliers[supplier_id] = supplier
        
        # Mark invitation as used
        self.use_invitation_code(invitation_code, supplier_id)
        
        # Record on ledger
        self._record_ledger_entry(
            entry_type="supplier_registration",
            supplier_id=supplier_id,
            amount=0,
            description=f"Supplier registration: {supplier['company_name']}",
            metadata={
                "company_name": supplier["company_name"],
                "supplier_type": supplier_type,
                "invitation_code": invitation_code,
                "ai_recommendation": ai_assessment["recommendation"]
            }
        )
        
        return {
            "success": True,
            "supplier_id": supplier_id,
            "status": supplier["status"],
            "ai_recommendation": ai_assessment["recommendation"],
            "commission_rate": commission_rate,
            "message": f"Application submitted successfully. ID: {supplier_id}"
        }
    
    def _get_category_for_type(self, supplier_type: str) -> str:
        """Get category for supplier type"""
        categories = {
            SupplierType.DOCTOR.value: "medical",
            SupplierType.LAWYER.value: "legal",
            SupplierType.PHARMACY.value: "medical",
            SupplierType.DELIVERY.value: "logistics",
            SupplierType.HOSPITAL.value: "medical",
            SupplierType.CLINIC.value: "medical",
            SupplierType.LABORATORY.value: "medical",
            SupplierType.EQUIPMENT.value: "medical",
            SupplierType.WELLNESS.value: "health",
            SupplierType.FINANCIAL.value: "financial",
            SupplierType.TECH_PROVIDER.value: "tech"
        }
        return categories.get(supplier_type, "other")
    
    def _assess_supplier_risk(self, supplier: Dict) -> Dict:
        """AI-powered risk assessment for supplier"""
        risk_factors = []
        trust_factors = []
        base_risk = 0.3
        base_trust = 0.7
        
        # Business info completeness
        info_fields = ["company_name", "contact_name", "contact_email", "address", "city", "country"]
        filled = sum(1 for f in info_fields if supplier.get(f))
        completeness = filled / len(info_fields)
        
        if completeness >= 0.9:
            trust_factors.append({"factor": "complete_business_info", "impact": 0.1})
            base_trust += 0.1
        elif completeness < 0.7:
            risk_factors.append({"factor": "incomplete_business_info", "impact": 0.15})
            base_risk += 0.15
        
        # License check for regulated industries
        regulated_types = [SupplierType.DOCTOR.value, SupplierType.PHARMACY.value, 
                          SupplierType.LAWYER.value, SupplierType.HOSPITAL.value]
        if supplier.get("supplier_type") in regulated_types:
            if supplier.get("license_number"):
                trust_factors.append({"factor": "license_provided", "impact": 0.15})
                base_trust += 0.15
            else:
                risk_factors.append({"factor": "missing_required_license", "impact": 0.25})
                base_risk += 0.25
        
        # Business registration
        if supplier.get("business_registration_number"):
            trust_factors.append({"factor": "business_registered", "impact": 0.1})
            base_trust += 0.1
        else:
            risk_factors.append({"factor": "no_registration", "impact": 0.1})
            base_risk += 0.1
        
        # Referral bonus
        if supplier.get("referrer_id"):
            trust_factors.append({"factor": "referred_by_partner", "impact": 0.05})
            base_trust += 0.05
        
        # Normalize scores
        risk_score = min(max(base_risk, 0), 1)
        trust_score = min(max(base_trust, 0), 1)
        
        # Determine recommendation
        if trust_score >= 0.8 and risk_score <= 0.3:
            recommendation = "approve"
        elif risk_score >= 0.6 or trust_score <= 0.4:
            recommendation = "reject"
        else:
            recommendation = "review"
        
        return {
            "risk_score": round(risk_score, 3),
            "trust_score": round(trust_score, 3),
            "recommendation": recommendation,
            "notes": {
                "risk_factors": risk_factors,
                "trust_factors": trust_factors,
                "completeness": completeness
            }
        }
    
    # =========================================================================
    # SUPPLIER APPROVAL WORKFLOW
    # =========================================================================
    
    def approve_supplier(self, supplier_id: str, approved_by: str, notes: str = "") -> Dict[str, Any]:
        """Approve a pending supplier application"""
        if supplier_id not in self.suppliers:
            raise ValueError(f"Supplier {supplier_id} not found")
        
        supplier = self.suppliers[supplier_id]
        if supplier["status"] not in [SupplierStatus.PENDING.value, SupplierStatus.UNDER_REVIEW.value]:
            raise ValueError(f"Supplier is already {supplier['status']}")
        
        now = datetime.now(timezone.utc)
        supplier["status"] = SupplierStatus.APPROVED.value
        supplier["approval_date"] = now.isoformat()
        supplier["approved_by"] = approved_by
        supplier["portal_active"] = True
        supplier["updated_date"] = now.isoformat()
        
        # Record on ledger
        self._record_ledger_entry(
            entry_type="supplier_approval",
            supplier_id=supplier_id,
            amount=0,
            description=f"Supplier approved: {supplier['company_name']}",
            metadata={"approved_by": approved_by, "notes": notes}
        )
        
        return {
            "success": True,
            "supplier_id": supplier_id,
            "status": SupplierStatus.APPROVED.value,
            "message": f"Supplier {supplier['company_name']} approved successfully"
        }
    
    def reject_supplier(self, supplier_id: str, rejected_by: str, reason: str) -> Dict[str, Any]:
        """Reject a supplier application"""
        if supplier_id not in self.suppliers:
            raise ValueError(f"Supplier {supplier_id} not found")
        
        if not reason:
            raise ValueError("Rejection reason is required")
        
        supplier = self.suppliers[supplier_id]
        if supplier["status"] not in [SupplierStatus.PENDING.value, SupplierStatus.UNDER_REVIEW.value]:
            raise ValueError(f"Supplier is already {supplier['status']}")
        
        now = datetime.now(timezone.utc)
        supplier["status"] = SupplierStatus.REJECTED.value
        supplier["rejection_reason"] = reason
        supplier["review_date"] = now.isoformat()
        supplier["portal_active"] = False
        supplier["updated_date"] = now.isoformat()
        
        # Record on ledger
        self._record_ledger_entry(
            entry_type="supplier_rejection",
            supplier_id=supplier_id,
            amount=0,
            description=f"Supplier rejected: {supplier['company_name']}",
            metadata={"rejected_by": rejected_by, "reason": reason}
        )
        
        return {
            "success": True,
            "supplier_id": supplier_id,
            "status": SupplierStatus.REJECTED.value,
            "message": f"Supplier {supplier['company_name']} rejected"
        }

    # =========================================================================
    # OFFER MANAGEMENT
    # =========================================================================

    def upsert_offer(self, supplier_id: str, data: Dict[str, Any], actor: str = "system") -> Dict[str, Any]:
        """
        Create or update a supplier offer with delivery/billing metadata.
        Only approved suppliers may publish offers to the marketplace.
        """
        supplier = self.suppliers.get(supplier_id)
        if not supplier:
            raise ValueError(f"Supplier {supplier_id} not found")
        if supplier.get("status") != SupplierStatus.APPROVED.value:
            raise ValueError("Only approved suppliers can publish offers")

        offer_id = str(data.get("id") or "").strip()
        if not offer_id:
            offer_id = f"OFF-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"

        existing = self.offers.get(offer_id)
        if existing and existing.get("supplier_id") != supplier_id:
            raise ValueError("Offer belongs to a different supplier")

        name = str(data.get("name") or "").strip()
        category = str(data.get("category") or "").strip().lower()
        item_type = str(data.get("item_type") or "product").strip().lower()
        if item_type not in ("service", "product"):
            raise ValueError("item_type must be 'service' or 'product'")
        if not name:
            raise ValueError("Offer name is required")
        if not category:
            raise ValueError("Offer category is required")

        price = self._safe_float(data.get("price"), -1)
        if price < 0:
            raise ValueError("Offer price must be non-negative")

        wallet_compatible = data.get("wallet_compatible")
        if isinstance(wallet_compatible, str):
            try:
                wallet_compatible = json.loads(wallet_compatible)
            except Exception:
                wallet_compatible = []
        if not isinstance(wallet_compatible, list):
            wallet_compatible = []
        wallet_compatible = sorted({
            str(w).strip().lower()
            for w in wallet_compatible
            if str(w).strip()
        })
        if not wallet_compatible:
            wallet_compatible = ["health"]

        raw_delivery_config = data.get("delivery_config") if isinstance(data.get("delivery_config"), dict) else {}
        delivery_mode = str(
            raw_delivery_config.get("mode")
            or data.get("delivery_mode")
            or ("on_site" if item_type == "service" else "delivery")
        ).strip().lower()
        delivery_eta_days = max(
            0,
            self._safe_int(
                raw_delivery_config.get("eta_days", data.get("delivery_eta_days", data.get("delivery_days", 0))),
                0
            )
        )
        delivery_fee = round(
            max(0.0, self._safe_float(raw_delivery_config.get("fee", data.get("delivery_fee", 0.0)), 0.0)), 2
        )
        delivery_notes = str(raw_delivery_config.get("notes") or data.get("delivery_notes") or "").strip() or None

        raw_billing_config = data.get("billing_config") if isinstance(data.get("billing_config"), dict) else {}
        tax_rate_pct = self._normalize_percentage(
            raw_billing_config.get("tax_rate_pct", data.get("tax_rate_pct", data.get("tax_rate", 0.0))), 0.0
        )
        billing_cycle = str(raw_billing_config.get("billing_cycle") or data.get("billing_cycle") or "one_time").strip().lower()
        billing_terms = str(raw_billing_config.get("billing_terms") or data.get("billing_terms") or "").strip() or None
        invoice_supported = bool(raw_billing_config.get("invoice_supported", data.get("invoice_supported", True)))

        delivery_config = {
            "mode": delivery_mode,
            "eta_days": delivery_eta_days,
            "fee": delivery_fee,
            "notes": delivery_notes
        }
        billing_config = {
            "billing_cycle": billing_cycle,
            "billing_terms": billing_terms,
            "invoice_supported": invoice_supported,
            "tax_rate_pct": round(tax_rate_pct, 6)
        }

        now = datetime.now(timezone.utc).isoformat()
        created_date = (existing or {}).get("created_date") or (existing or {}).get("created_at") or now
        offer_approved_on = (existing or {}).get("offer_approved_on") or now
        offer_active = bool(data.get("active", True))

        offer = {
            "id": offer_id,
            "supplier_id": supplier_id,
            "name": name,
            "description": str(data.get("description") or "").strip() or None,
            "item_type": item_type,
            "category": category,
            "sub_category": str(data.get("sub_category") or "").strip() or None,
            "price": round(price, 2),
            "currency": str(data.get("currency") or "USD").strip().upper(),
            "unit": str(data.get("unit") or "per_item").strip().lower(),
            "min_quantity": max(1, self._safe_int(data.get("min_quantity"), 1)),
            "max_quantity": (
                max(1, self._safe_int(data.get("max_quantity"), 0))
                if data.get("max_quantity") is not None and str(data.get("max_quantity")).strip() != ""
                else None
            ),
            "wallet_compatible": wallet_compatible,
            "active": offer_active,
            "featured": bool(data.get("featured", (existing or {}).get("featured", False))),
            "delivery_config": delivery_config,
            "billing_config": billing_config,
            "delivery_mode": delivery_mode,
            "delivery_eta_days": delivery_eta_days,
            "delivery_fee": delivery_fee,
            "billing_cycle": billing_cycle,
            "billing_terms": billing_terms,
            "invoice_supported": invoice_supported,
            "tax_rate_pct": round(tax_rate_pct, 6),
            "supplier_approved_on": supplier.get("approval_date"),
            "offer_status": "approved" if offer_active else "inactive",
            "offer_approved_on": offer_approved_on,
            "created_date": created_date,
            "updated_date": now,
            "created_at": created_date,
            "updated_at": now,
            "updated_by": actor,
            "total_orders": self._safe_int((existing or {}).get("total_orders"), 0),
            "total_revenue": round(self._safe_float((existing or {}).get("total_revenue"), 0.0), 2),
            "average_rating": self._safe_float((existing or {}).get("average_rating"), 0.0)
        }

        self.offers[offer_id] = offer

        self._record_ledger_entry(
            entry_type="offer_upsert",
            supplier_id=supplier_id,
            amount=offer["price"],
            description=f"Offer upsert: {offer['name']}",
            metadata={
                "offer_id": offer_id,
                "category": offer["category"],
                "item_type": offer["item_type"],
                "active": offer["active"],
                "delivery_mode": delivery_mode,
                "billing_cycle": billing_cycle,
                "updated_by": actor
            }
        )

        return {
            "success": True,
            "offer_id": offer_id,
            "offer": offer,
            "message": "Offer saved successfully"
        }

    def deactivate_offer(self, supplier_id: str, offer_id: str, actor: str = "system") -> Dict[str, Any]:
        """Soft deactivate an offer to preserve ledger and reporting integrity."""
        offer = self.offers.get(offer_id)
        if not offer:
            raise ValueError(f"Offer {offer_id} not found")
        if offer.get("supplier_id") != supplier_id:
            raise ValueError("Offer belongs to a different supplier")

        now = datetime.now(timezone.utc).isoformat()
        offer["active"] = False
        offer["offer_status"] = "inactive"
        offer["updated_date"] = now
        offer["updated_at"] = now
        offer["updated_by"] = actor

        self._record_ledger_entry(
            entry_type="offer_deactivate",
            supplier_id=supplier_id,
            amount=0.0,
            description=f"Offer deactivated: {offer.get('name', offer_id)}",
            metadata={"offer_id": offer_id, "updated_by": actor}
        )

        return {
            "success": True,
            "offer_id": offer_id,
            "message": "Offer deactivated successfully"
        }
    
    # =========================================================================
    # FEE SCHEDULE MANAGEMENT
    # =========================================================================
    
    def get_fee_schedule(self) -> Dict:
        """Get current fee schedule"""
        return self.fee_schedule.to_dict()
    
    def update_fee_schedule(self, updates: Dict, updated_by: str) -> Dict[str, Any]:
        """
        Update fee schedule (admin only).
        
        Updateable fields:
        - base_commission_pct: Default commission rate
        - category_adjustments: Dict of supplier_type -> commission %
        - volume_discounts: List of volume tier discounts
        - promotional_rates: List of promo codes
        """
        if "base_commission_pct" in updates:
            self.fee_schedule.base_commission_pct = float(updates["base_commission_pct"])
        
        if "category_adjustments" in updates:
            self.fee_schedule.category_adjustments.update(updates["category_adjustments"])
        
        if "volume_discounts" in updates:
            self.fee_schedule.volume_discounts = updates["volume_discounts"]
        
        if "promotional_rates" in updates:
            self.fee_schedule.promotional_rates = updates["promotional_rates"]
        
        if "minimum_fee" in updates:
            self.fee_schedule.minimum_fee = float(updates["minimum_fee"])
        
        if "maximum_fee_pct" in updates:
            self.fee_schedule.maximum_fee_pct = float(updates["maximum_fee_pct"])
        
        # Record change
        self._record_ledger_entry(
            entry_type="fee_schedule_update",
            supplier_id="SYSTEM",
            amount=0,
            description="Fee schedule updated",
            metadata={"updates": updates, "updated_by": updated_by}
        )
        
        return {
            "success": True,
            "fee_schedule": self.fee_schedule.to_dict(),
            "message": "Fee schedule updated"
        }
    
    def calculate_order_fees(self, supplier_id: str, amount: float, 
                            promo_code: str = None) -> Dict:
        """Calculate fees for an order"""
        supplier = self.suppliers.get(supplier_id)
        if not supplier:
            raise ValueError(f"Supplier {supplier_id} not found")
        
        supplier_type = supplier.get("supplier_type", "other")
        created_raw = str(supplier.get("created_date") or supplier.get("application_date") or "")
        try:
            created_dt = datetime.fromisoformat(created_raw.replace('Z', '+00:00'))
        except Exception:
            created_dt = datetime.now(timezone.utc)
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(created_dt.tzinfo)
        days_active = max(1, (now_dt - created_dt).days)
        monthly_volume = self._safe_float(supplier.get("total_revenue"), 0.0) / max(1, days_active / 30)
        
        return self.fee_schedule.calculate_commission(
            amount=amount,
            supplier_type=supplier_type,
            monthly_volume=monthly_volume,
            promo_code=promo_code
        )
    
    # =========================================================================
    # ORDER PROCESSING WITH HEALTH WALLET INTEGRATION
    # =========================================================================
    
    def create_order(self, customer_id: str, supplier_id: str, 
                    offer_id: str, data: Dict) -> Dict[str, Any]:
        """
        Create an order from customer to supplier.
        Integrates with health wallet for payment.
        
        Args:
            customer_id: Customer placing order
            supplier_id: Supplier fulfilling order
            offer_id: Product/service offer ID
            data: Order details (quantity, delivery_address, etc.)
        
        Returns:
            Order details with payment breakdown
        """
        # Get offer first so supplier can be inferred safely
        offer = self.offers.get(offer_id)
        if not offer:
            raise ValueError(f"Offer {offer_id} not found")
        if not offer.get("active", True):
            raise ValueError("This offer is no longer available")

        inferred_supplier_id = supplier_id or offer.get("supplier_id")
        if not inferred_supplier_id:
            raise ValueError("supplier_id is required")
        if offer.get("supplier_id") and offer.get("supplier_id") != inferred_supplier_id:
            raise ValueError("Offer does not belong to requested supplier")
        supplier_id = inferred_supplier_id

        # Validate supplier
        supplier = self.suppliers.get(supplier_id)
        if not supplier:
            raise ValueError(f"Supplier {supplier_id} not found")
        if supplier.get("status") != SupplierStatus.APPROVED.value:
            raise ValueError("Supplier is not active")

        # Validate quantity
        quantity = max(1, self._safe_int(data.get("quantity"), 1))
        min_qty = max(1, self._safe_int(offer.get("min_quantity"), 1))
        max_qty = self._safe_int(offer.get("max_quantity"), 0) if offer.get("max_quantity") is not None else 0
        if quantity < min_qty:
            raise ValueError(f"Minimum quantity is {min_qty}")
        if max_qty and quantity > max_qty:
            raise ValueError(f"Maximum quantity is {max_qty}")

        # Pricing plan: base + expense loading + profit margin - discounted rate
        unit_price = round(max(self._safe_float(offer.get("price"), 0.0), 0.0), 2)
        base_amount = round(unit_price * quantity, 2)
        pricing_plan = self._build_pricing_plan(base_amount, data)
        total_amount = pricing_plan["final_customer_amount"]

        # Calculate commission and payout against final customer charge
        fee_calc = self.calculate_order_fees(supplier_id, total_amount, data.get("promo_code"))
        commission = fee_calc["commission"]
        supplier_payout = fee_calc["supplier_payout"]

        payment_method = self._normalize_payment_method(data.get("payment_method", "health_wallet"))
        wallet_deduction = 0.0
        external_payment_amount = 0.0
        external_payment_method = None
        out_of_pocket = total_amount
        payment_status = "pending"

        wallet_methods = {"health_wallet"}

        if payment_method in wallet_methods:
            wallet = self.health_wallets.get(customer_id, {})
            wallet_balance = self._safe_float(wallet.get("balance"), 0.0)
            wallet_deduction = round(min(total_amount, wallet_balance), 2)
            out_of_pocket = round(total_amount - wallet_deduction, 2)

            if out_of_pocket > 0:
                if bool(data.get("allow_credit_fallback", True)):
                    external_payment_method = self._normalize_payment_method(
                        data.get("fallback_payment_method", "credit_card")
                    )
                    if external_payment_method in wallet_methods:
                        external_payment_method = "credit_card"
                    external_payment_amount = out_of_pocket
                    payment_status = "paid"
                else:
                    payment_status = "partially_paid"
            else:
                payment_status = "paid"
        elif payment_method == "mixed":
            wallet = self.health_wallets.get(customer_id, {})
            wallet_balance = self._safe_float(wallet.get("balance"), 0.0)
            requested_wallet = self._safe_float(data.get("wallet_amount"), wallet_balance)
            wallet_deduction = round(min(requested_wallet, wallet_balance, total_amount), 2)
            out_of_pocket = round(total_amount - wallet_deduction, 2)
            if out_of_pocket > 0:
                external_payment_method = self._normalize_payment_method(
                    data.get("external_payment_method", "credit_card")
                )
                if external_payment_method in wallet_methods:
                    external_payment_method = "credit_card"
                external_payment_amount = out_of_pocket
            payment_status = "paid"
        else:
            # Direct external payment path (credit/debit/bank/etc.)
            external_payment_method = payment_method
            external_payment_amount = total_amount
            payment_status = "paid"
            out_of_pocket = total_amount

        # Determine B2B or B2C
        is_b2b = bool(data.get("is_b2b", False) or data.get("business_customer", False))

        # Generate order ID
        order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        delivery_config = offer.get("delivery_config") if isinstance(offer.get("delivery_config"), dict) else {}
        billing_config = offer.get("billing_config") if isinstance(offer.get("billing_config"), dict) else {}
        delivery_plan = self._build_delivery_plan(
            supplier=supplier,
            offer=offer,
            order_payload=data,
            quantity=quantity,
        )
        recommended_method = delivery_plan.get("recommended_method") if isinstance(delivery_plan.get("recommended_method"), dict) else {}
        delivery_eta_days = self._safe_int(
            recommended_method.get("eta_days", delivery_config.get("eta_days")),
            0,
        )
        estimated_delivery = (now + timedelta(days=delivery_eta_days)).isoformat() if delivery_eta_days > 0 else None
        delivery_method = self._safe_text(
            data.get("delivery_method")
            or recommended_method.get("method")
            or delivery_config.get("mode")
        )
        delivery_validation_code = f"DLV-{secrets.token_hex(3).upper()}"

        order = {
            "id": order_id,
            "supplier_id": supplier_id,
            "customer_id": customer_id,
            "offer_id": offer_id,
            "order_type": offer.get("item_type", "service"),
            "item_name": offer.get("name"),
            "item_description": offer.get("description"),
            "quantity": quantity,
            "unit_price": unit_price,
            "base_amount": base_amount,
            "total_amount": total_amount,
            "pricing_plan": pricing_plan,
            "expense_loading_pct": pricing_plan["expense_loading_pct"],
            "expense_loading_amount": pricing_plan["expense_loading_amount"],
            "profit_margin_pct": pricing_plan["profit_margin_pct"],
            "profit_margin_amount": pricing_plan["profit_margin_amount"],
            "discounted_rate_pct": pricing_plan["discounted_rate_pct"],
            "discounted_rate_amount": pricing_plan["discounted_rate_amount"],
            "gross_before_discount": pricing_plan["gross_before_discount"],
            "commission": commission,
            "commission_rate_pct": fee_calc["effective_rate_pct"],
            "supplier_payout": supplier_payout,
            "payment_method": payment_method,
            "payment_status": payment_status,
            "payment_date": now_iso if payment_status == "paid" else None,
            "wallet_deduction": wallet_deduction,
            "out_of_pocket": out_of_pocket,
            "external_payment_method": external_payment_method,
            "external_payment_amount": external_payment_amount,
            "external_payment_reference": data.get("payment_reference"),
            "promo_code": data.get("promo_code"),
            "status": OrderStatus.PENDING.value,
            "delivery_address": data.get("delivery_address"),
            "delivery_notes": data.get("delivery_notes"),
            "delivery_config": delivery_config,
            "delivery_plan": delivery_plan,
            "delivery_method": delivery_method,
            "delivery_validation_code": delivery_validation_code,
            "billing_config": billing_config,
            "billing_terms": billing_config.get("billing_terms") or data.get("billing_terms"),
            "scheduled_date": data.get("scheduled_date"),
            "estimated_delivery": estimated_delivery,
            "supplier_approved_on": supplier.get("approval_date"),
            "offer_approved_on": offer.get("offer_approved_on"),
            "is_b2b": is_b2b,
            "business_name": data.get("business_name") if is_b2b else None,
            "created_date": now_iso,
            "updated_date": now_iso
        }

        # Deduct from health wallet if applicable
        if wallet_deduction > 0:
            if customer_id not in self.health_wallets:
                self.health_wallets[customer_id] = {"balance": 0.0, "transactions": []}
            self.health_wallets[customer_id]["balance"] = round(
                self._safe_float(self.health_wallets[customer_id].get("balance"), 0.0) - wallet_deduction, 2
            )
            self.health_wallets[customer_id]["transactions"] = self.health_wallets[customer_id].get("transactions", [])
            self.health_wallets[customer_id]["transactions"].append({
                "id": f"WAL-ORD-{order_id}",
                "type": "order_payment",
                "amount": -wallet_deduction,
                "order_id": order_id,
                "supplier_id": supplier_id,
                "payment_method": "health_wallet",
                "pricing_plan": pricing_plan,
                "timestamp": now_iso
            })

        # Generate NFT token for order
        nft_token_id = f"NFT-ORD-{secrets.token_hex(6).upper()}"
        order["nft_token_id"] = nft_token_id

        self.nft_ledger[nft_token_id] = {
            "token_id": nft_token_id,
            "owner_id": customer_id,
            "asset_type": "order",
            "asset_id": order_id,
            "created_at": now_iso,
            "metadata": {
                "supplier_id": supplier_id,
                "offer_id": offer_id,
                "total_amount": total_amount,
                "commission": commission,
                "supplier_payout": supplier_payout,
                "wallet_deduction": wallet_deduction,
                "external_payment_amount": external_payment_amount,
                "payment_method": payment_method,
                "pricing_plan": pricing_plan,
                "is_b2b": is_b2b
            }
        }

        # Store order
        self.orders[order_id] = order

        # Record on supply chain ledger
        self._record_ledger_entry(
            entry_type="order_created",
            supplier_id=supplier_id,
            customer_id=customer_id,
            order_id=order_id,
            amount=total_amount,
            commission=commission,
            supplier_payout=supplier_payout,
            description=f"Order created: {offer.get('name')}",
            metadata={
                "offer_id": offer_id,
                "quantity": quantity,
                "payment_method": payment_method,
                "is_b2b": is_b2b,
                "nft_token_id": nft_token_id
            }
        )
        self._record_ledger_entry(
            entry_type="order_pricing_plan",
            supplier_id=supplier_id,
            customer_id=customer_id,
            order_id=order_id,
            amount=base_amount,
            commission=commission,
            supplier_payout=supplier_payout,
            description=f"Pricing plan applied: {offer.get('name')}",
            metadata={
                "pricing_plan": pricing_plan,
                "wallet_deduction": wallet_deduction,
                "external_payment_amount": external_payment_amount
            }
        )
        if wallet_deduction > 0:
            self._record_ledger_entry(
                entry_type="wallet_payment",
                supplier_id=supplier_id,
                customer_id=customer_id,
                order_id=order_id,
                amount=wallet_deduction,
                description=f"Wallet payment for order {order_id}",
                metadata={"payment_method": "health_wallet"}
            )
        if external_payment_amount > 0:
            self._record_ledger_entry(
                entry_type="external_payment",
                supplier_id=supplier_id,
                customer_id=customer_id,
                order_id=order_id,
                amount=external_payment_amount,
                description=f"External payment for order {order_id}",
                metadata={"payment_method": external_payment_method}
            )

        # Record on main transaction ledger
        if self.record_transaction:
            try:
                self.record_transaction(
                    customer_id=customer_id,
                    tx_type="marketplace_order",
                    amount=total_amount,
                    description=f"Order {order_id} - {offer.get('name')}",
                    metadata={
                        "order_id": order_id,
                        "supplier_id": supplier_id,
                        "offer_id": offer_id,
                        "commission": commission,
                        "supplier_payout": supplier_payout,
                        "pricing_plan": pricing_plan,
                        "wallet_deduction": wallet_deduction,
                        "external_payment_amount": external_payment_amount,
                        "payment_method": payment_method
                    }
                )
            except Exception:
                pass

        return {
            "success": True,
            "order": order,
            "payment_breakdown": fee_calc,
            "pricing_plan": pricing_plan,
            "payment_summary": {
                "payment_method": payment_method,
                "wallet_deduction": wallet_deduction,
                "external_payment_method": external_payment_method,
                "external_payment_amount": external_payment_amount,
                "remaining_out_of_pocket": out_of_pocket,
                "payment_status": payment_status
            },
            "wallet_deduction": wallet_deduction,
            "out_of_pocket": out_of_pocket,
            "nft_token_id": nft_token_id,
            "message": f"Order {order_id} created successfully"
        }
    
    def complete_order(self, order_id: str, completed_by: str) -> Dict[str, Any]:
        """Mark order as completed and add to pending settlement"""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")
        
        order = self.orders[order_id]
        if order["status"] == OrderStatus.COMPLETED.value:
            raise ValueError("Order is already completed")
        settlement_status = str(order.get("settlement_status") or "").strip().lower()
        if bool(order.get("requires_customer_settlement_approval", True)) and settlement_status not in {
            "customer_approved",
            "pending_admin_payout",
            "settled",
        }:
            raise ValueError("Customer settlement approval is required before supplier payout can be released")
        
        now = datetime.now(timezone.utc)
        order["status"] = OrderStatus.COMPLETED.value
        order["completed_date"] = now.isoformat()
        order["updated_date"] = now.isoformat()
        order["settlement_status"] = "pending_admin_payout"
        order["settlement_phase"] = "awaiting_admin_payout"
        
        supplier_id = order["supplier_id"]
        supplier = self.suppliers.get(supplier_id)
        
        if supplier:
            # Update supplier metrics
            supplier["total_orders"] = supplier.get("total_orders", 0) + 1
            supplier["completed_orders"] = supplier.get("completed_orders", 0) + 1
            supplier["total_revenue"] = supplier.get("total_revenue", 0) + order["supplier_payout"]
            supplier["total_commission_paid"] = supplier.get("total_commission_paid", 0) + order["commission"]
            
            # Update B2B/B2C stats
            if order.get("is_b2b"):
                supplier["b2b_orders"] = supplier.get("b2b_orders", 0) + 1
                supplier["b2b_revenue"] = supplier.get("b2b_revenue", 0) + order["supplier_payout"]
            else:
                supplier["b2c_orders"] = supplier.get("b2c_orders", 0) + 1
                supplier["b2c_revenue"] = supplier.get("b2c_revenue", 0) + order["supplier_payout"]
            
            supplier["updated_date"] = now.isoformat()
            
            # Add to pending settlement
            if supplier_id not in self.pending_settlements:
                self.pending_settlements[supplier_id] = []
            self.pending_settlements[supplier_id].append({
                "order_id": order_id,
                "amount": order["supplier_payout"],
                "completed_date": now.isoformat(),
                "settlement_status": order.get("settlement_status"),
                "customer_approved_at": ((order.get("customer_approval") or {}).get("approved_at")),
            })
        
        # Record on ledger
        self._record_ledger_entry(
            entry_type="order_completed",
            supplier_id=supplier_id,
            customer_id=order["customer_id"],
            order_id=order_id,
            amount=order["total_amount"],
            commission=order["commission"],
            supplier_payout=order["supplier_payout"],
            description=f"Order completed: {order['item_name']}",
            metadata={"completed_by": completed_by}
        )
        
        return {
            "success": True,
            "order": order,
            "message": f"Order {order_id} completed"
        }

    def update_order_status(
        self,
        order_id: str,
        status: str,
        updated_by: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an order status with simple lifecycle validation."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")

        normalized_status = str(status or "").strip().lower()
        if not normalized_status:
            raise ValueError("status is required")

        order = self.orders[order_id]
        current_status = str(order.get("status") or "").strip().lower()

        if current_status == normalized_status:
            return {
                "success": True,
                "order": order,
                "message": f"Order {order_id} already {normalized_status}"
            }

        # Completing an order should continue to flow through the settlement logic.
        if normalized_status == OrderStatus.COMPLETED.value:
            if current_status == OrderStatus.COMPLETED.value:
                return {
                    "success": True,
                    "order": order,
                    "message": f"Order {order_id} already {normalized_status}"
                }
            return self.complete_order(order_id, completed_by=updated_by)

        allowed_transitions = {
            OrderStatus.PENDING.value: {
                OrderStatus.CONFIRMED.value,
                OrderStatus.CANCELLED.value,
            },
            OrderStatus.CONFIRMED.value: {
                OrderStatus.PROCESSING.value,
                OrderStatus.CANCELLED.value,
            },
            OrderStatus.PROCESSING.value: {
                OrderStatus.IN_TRANSIT.value,
                OrderStatus.DELIVERED.value,
                OrderStatus.CANCELLED.value,
            },
            OrderStatus.IN_TRANSIT.value: {
                OrderStatus.DELIVERED.value,
                OrderStatus.CANCELLED.value,
            },
            OrderStatus.DELIVERED.value: {
                OrderStatus.COMPLETED.value,
            },
        }

        if normalized_status not in {
            OrderStatus.PENDING.value,
            OrderStatus.CONFIRMED.value,
            OrderStatus.PROCESSING.value,
            OrderStatus.IN_TRANSIT.value,
            OrderStatus.DELIVERED.value,
            OrderStatus.CANCELLED.value,
            OrderStatus.REFUNDED.value,
            OrderStatus.DISPUTED.value,
        }:
            raise ValueError(f"Unsupported order status: {normalized_status}")

        allowed_next = allowed_transitions.get(current_status, set())
        if normalized_status not in allowed_next:
            raise ValueError(
                f"Invalid status transition from {current_status or 'unknown'} to {normalized_status}"
            )

        now = datetime.now(timezone.utc).isoformat()
        order["status"] = normalized_status
        order["updated_date"] = now
        if normalized_status == OrderStatus.DELIVERED.value:
            order["actual_delivery"] = now
        elif normalized_status == OrderStatus.CANCELLED.value:
            order["cancelled_by"] = updated_by
            order["cancelled_date"] = now

        self._record_ledger_entry(
            entry_type="order_status_updated",
            supplier_id=order["supplier_id"],
            customer_id=order.get("customer_id"),
            order_id=order_id,
            amount=order.get("total_amount", 0.0),
            commission=order.get("commission", 0.0),
            supplier_payout=order.get("supplier_payout", 0.0),
            description=f"Order status updated to {normalized_status}",
            metadata={
                "updated_by": updated_by,
                "previous_status": current_status,
                "new_status": normalized_status,
                "notes": notes,
            }
        )

        return {
            "success": True,
            "order": order,
            "message": f"Order {order_id} updated to {normalized_status}"
        }
    
    # =========================================================================
    # SETTLEMENT AND PAYOUTS
    # =========================================================================
    
    def get_pending_settlements(self, supplier_id: str = None) -> Dict[str, Any]:
        """Get pending settlements for suppliers"""
        if supplier_id:
            pending = self.pending_settlements.get(supplier_id, [])
            total = sum(p["amount"] for p in pending)
            awaiting_customer_approval = [
                o for o in self.orders.values()
                if o.get("supplier_id") == supplier_id
                and str(o.get("settlement_status") or "").strip().lower() == "awaiting_customer_approval"
            ]
            return {
                "supplier_id": supplier_id,
                "pending_orders": len(pending),
                "pending_amount": total,
                "orders": pending,
                "awaiting_customer_approval_orders": len(awaiting_customer_approval),
                "awaiting_customer_approval_amount": round(
                    sum(float(o.get("supplier_payout", 0) or 0) for o in awaiting_customer_approval),
                    2,
                ),
                "approval_required": [
                    {
                        "order_id": o.get("id"),
                        "item_name": o.get("item_name"),
                        "customer_id": o.get("customer_id"),
                        "customer_name": o.get("customer_name"),
                        "requested_at": (o.get("settlement_request") or {}).get("requested_at"),
                        "amount": round(float(o.get("supplier_payout", 0) or 0), 2),
                        "settlement_code": o.get("settlement_code"),
                    }
                    for o in awaiting_customer_approval
                ],
            }
        
        # All suppliers
        result = {}
        for sup_id, pending in self.pending_settlements.items():
            total = sum(p["amount"] for p in pending)
            awaiting_customer_approval = [
                o for o in self.orders.values()
                if o.get("supplier_id") == sup_id
                and str(o.get("settlement_status") or "").strip().lower() == "awaiting_customer_approval"
            ]
            result[sup_id] = {
                "pending_orders": len(pending),
                "pending_amount": total,
                "awaiting_customer_approval_orders": len(awaiting_customer_approval),
                "awaiting_customer_approval_amount": round(
                    sum(float(o.get("supplier_payout", 0) or 0) for o in awaiting_customer_approval),
                    2,
                ),
            }
        return result
    
    def process_settlement(self, supplier_id: str, processed_by: str) -> Dict[str, Any]:
        """Process settlement/payout for a supplier"""
        pending = self.pending_settlements.get(supplier_id, [])
        if not pending:
            return {"success": True, "message": "No pending settlements", "amount": 0}
        
        total_amount = sum(p["amount"] for p in pending)
        order_ids = [p["order_id"] for p in pending]
        
        now = datetime.now(timezone.utc)
        settlement_id = f"SET-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"
        
        # Clear pending
        self.pending_settlements[supplier_id] = []
        for order_id in order_ids:
            order = self.orders.get(order_id)
            if not order:
                continue
            order["settlement_status"] = "settled"
            order["settlement_phase"] = "paid_out"
            order["settled_at"] = now.isoformat()
            order["settled_by"] = processed_by
            order["updated_date"] = now.isoformat()

        settlement_record = {
            "settlement_id": settlement_id,
            "supplier_id": supplier_id,
            "amount": total_amount,
            "orders_settled": len(order_ids),
            "order_ids": order_ids,
            "processed_by": processed_by,
            "processed_at": now.isoformat(),
            "status": "processed",
        }
        self.settlement_history.append(settlement_record)
        
        # Record settlement
        self._record_ledger_entry(
            entry_type="settlement",
            supplier_id=supplier_id,
            amount=total_amount,
            supplier_payout=total_amount,
            description=f"Settlement processed: {len(order_ids)} orders",
            metadata={
                "settlement_id": settlement_id,
                "order_ids": order_ids,
                "processed_by": processed_by
            }
        )
        
        return {
            "success": True,
            "settlement_id": settlement_id,
            "supplier_id": supplier_id,
            "amount": total_amount,
            "orders_settled": len(order_ids),
            "message": f"Settlement of ${total_amount:,.2f} processed"
        }

    def get_settlement_history(self, supplier_id: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Return processed settlement history, optionally scoped to a supplier."""
        records = list(self.settlement_history)
        if supplier_id:
            records = [r for r in records if r.get("supplier_id") == supplier_id]
        records.sort(key=lambda x: x.get("processed_at", ""), reverse=True)
        return records[:max(1, limit)]

    def queue_connector_retry(
        self,
        supplier_id: str,
        connector_type: str,
        reason: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Queue an external connector retry for supplier sync/ops visibility."""
        now = datetime.now(timezone.utc).isoformat()
        retry_id = f"RETRY-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"
        record = {
            "retry_id": retry_id,
            "supplier_id": supplier_id,
            "connector_type": connector_type,
            "reason": reason,
            "payload": payload or {},
            "status": "queued",
            "attempt_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        self.connector_retry_queue.append(record)
        self.connector_audit_log.append({
            "event_id": f"AUD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}",
            "supplier_id": supplier_id,
            "connector_type": connector_type,
            "event_type": "retry_queued",
            "reason": reason,
            "timestamp": now,
            "payload": payload or {},
        })
        return record

    def get_connector_retry_queue(self, supplier_id: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Return queued connector retries."""
        items = list(self.connector_retry_queue)
        if supplier_id:
            items = [item for item in items if item.get("supplier_id") == supplier_id]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items[:max(1, limit)]

    def get_connector_audit_log(self, supplier_id: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Return connector audit history."""
        items = list(self.connector_audit_log)
        if supplier_id:
            items = [item for item in items if item.get("supplier_id") == supplier_id]
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items[:max(1, limit)]

    def _resolve_delivery_provider(self, order: Dict[str, Any], payload: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Resolve the external delivery provider name for a shipment request."""
        payload = payload or {}
        requested = self._safe_text(payload.get("provider") or payload.get("carrier") or payload.get("connector"))
        if requested:
            return requested.lower()
        supplier = self.suppliers.get(order.get("supplier_id"), {})
        preferred = self._safe_text(
            payload.get("preferred_delivery_provider")
            or order.get("preferred_delivery_provider")
            or supplier.get("preferred_delivery_provider")
            or supplier.get("connector_mode")
        )
        return preferred.lower() if preferred else None

    def create_delivery_shipment(
        self,
        *,
        order_id: str,
        actor: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create an external shipment via Wolt/UPS/FedEx style delivery connectors."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")

        payload = data or {}
        order = self.orders[order_id]
        provider_name = self._resolve_delivery_provider(order, payload)
        if not provider_name:
            raise ValueError("provider is required")

        shipping_address = (
            self._coerce_location(payload.get("delivery_location"))
            or self._coerce_location(payload.get("destination"))
            or self._coerce_location(order.get("delivery_location"))
            or self._build_location_from_fields(order.get("delivery_address"))
        )
        if not shipping_address:
            raise ValueError("A delivery location with latitude/longitude is required")

        supplier = self.suppliers.get(order.get("supplier_id"))
        if not supplier:
            raise ValueError(f"Supplier {order.get('supplier_id')} not found")

        supplier_location = self._build_location_from_fields(supplier)
        if not supplier_location:
            raise ValueError("Supplier location must include latitude and longitude")

        connector = create_delivery_provider_connector(provider_name)
        shipment_payload = {
            "order_id": order_id,
            "item_name": order.get("item_name"),
            "quantity": order.get("quantity"),
            "amount": order.get("total_amount"),
            "customer_id": order.get("customer_id"),
            "supplier_id": order.get("supplier_id"),
            "supplier_name": supplier.get("company_name"),
            "origin": supplier_location,
            "destination": shipping_address,
            "delivery_method": payload.get("delivery_method")
            or ((order.get("delivery_plan") or {}).get("recommended_method") or {}).get("method")
            or order.get("delivery_mode"),
        }

        try:
            shipment_result = connector.create_shipment(shipment_payload)
        except DeliveryProviderConnectorError as exc:
            retry = self.queue_connector_retry(
                supplier_id=order.get("supplier_id"),
                connector_type=provider_name,
                reason=str(exc),
                payload={"order_id": order_id, "provider": provider_name},
            )
            supplier["connector_status"] = "degraded"
            supplier["last_order_sync_at"] = datetime.now(timezone.utc).isoformat()
            self.connector_audit_log.append({
                "event_id": f"AUD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}",
                "supplier_id": order.get("supplier_id"),
                "connector_type": provider_name,
                "event_type": "shipment_create_failed",
                "reason": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"order_id": order_id, "retry_id": retry.get("retry_id")},
            })
            raise ValueError(str(exc)) from exc

        shipment = shipment_result.to_dict() if hasattr(shipment_result, "to_dict") else dict(shipment_result)
        if not shipment.get("success") or shipment.get("status") == "unconfigured":
            reason = shipment.get("error") or f"{provider_name} shipment creation failed"
            retry = self.queue_connector_retry(
                supplier_id=order.get("supplier_id"),
                connector_type=provider_name,
                reason=reason,
                payload={"order_id": order_id, "provider": provider_name},
            )
            supplier["connector_status"] = "degraded"
            supplier["last_order_sync_at"] = datetime.now(timezone.utc).isoformat()
            self.connector_audit_log.append({
                "event_id": f"AUD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}",
                "supplier_id": order.get("supplier_id"),
                "connector_type": provider_name,
                "event_type": "shipment_create_failed",
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"order_id": order_id, "retry_id": retry.get("retry_id")},
            })
            return {
                "success": False,
                "provider": provider_name,
                "order": order,
                "shipment": shipment,
                "retry": retry,
                "message": reason,
            }

        shipment_id = shipment.get("shipment_id")
        self.delivery_shipments[shipment_id] = shipment
        supplier["connector_mode"] = provider_name
        supplier["connector_status"] = "active"
        supplier["last_order_sync_at"] = datetime.now(timezone.utc).isoformat()

        order["delivery_provider"] = provider_name
        order["shipment_id"] = shipment_id
        order["tracking_number"] = shipment.get("tracking_number")
        order["tracking_url"] = shipment.get("tracking_url")
        order["delivery_status"] = shipment.get("status")
        order["delivery_provider_payload"] = shipment
        order["updated_date"] = datetime.now(timezone.utc).isoformat()
        if str(order.get("status") or "").strip().lower() == OrderStatus.PROCESSING.value:
            order["status"] = OrderStatus.IN_TRANSIT.value

        self.connector_audit_log.append({
            "event_id": f"AUD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}",
            "supplier_id": order.get("supplier_id"),
            "connector_type": provider_name,
            "event_type": "shipment_created",
            "reason": "Delivery connector shipment created",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "order_id": order_id,
                "shipment_id": shipment_id,
                "tracking_number": shipment.get("tracking_number"),
            },
        })

        self._record_ledger_entry(
            entry_type="delivery_shipment_created",
            supplier_id=order["supplier_id"],
            customer_id=order.get("customer_id"),
            order_id=order_id,
            amount=order.get("total_amount", 0.0),
            commission=order.get("commission", 0.0),
            supplier_payout=order.get("supplier_payout", 0.0),
            description=f"Delivery shipment created via {provider_name.upper()}",
            metadata={
                "provider": provider_name,
                "shipment_id": shipment_id,
                "tracking_number": shipment.get("tracking_number"),
                "created_by": actor,
            },
        )

        return {
            "success": True,
            "provider": provider_name,
            "order": order,
            "shipment": shipment,
        }

    def track_delivery_shipment(
        self,
        *,
        order_id: str,
        actor: str,
    ) -> Dict[str, Any]:
        """Return live tracking information for an externally connected delivery shipment."""
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")

        order = self.orders[order_id]
        provider_name = self._safe_text(order.get("delivery_provider"))
        shipment_id = self._safe_text(order.get("shipment_id"))
        if not provider_name or not shipment_id:
            raise ValueError("Order does not have an external delivery shipment")

        connector = create_delivery_provider_connector(provider_name)
        try:
            tracking = connector.track_shipment(shipment_id)
        except DeliveryProviderConnectorError as exc:
            retry = self.queue_connector_retry(
                supplier_id=order.get("supplier_id"),
                connector_type=provider_name,
                reason=str(exc),
                payload={"order_id": order_id, "shipment_id": shipment_id},
            )
            self.connector_audit_log.append({
                "event_id": f"AUD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}",
                "supplier_id": order.get("supplier_id"),
                "connector_type": provider_name,
                "event_type": "tracking_failed",
                "reason": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"order_id": order_id, "retry_id": retry.get("retry_id")},
            })
            raise ValueError(str(exc)) from exc

        stored = self.delivery_shipments.get(shipment_id, {})
        stored.update(tracking)
        self.delivery_shipments[shipment_id] = stored
        order["delivery_status"] = tracking.get("status")
        order["tracking_url"] = tracking.get("tracking_url") or order.get("tracking_url")
        order["updated_date"] = datetime.now(timezone.utc).isoformat()

        self.connector_audit_log.append({
            "event_id": f"AUD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}",
            "supplier_id": order.get("supplier_id"),
            "connector_type": provider_name,
            "event_type": "tracking_polled",
            "reason": "Delivery tracking refreshed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"order_id": order_id, "shipment_id": shipment_id, "status": tracking.get("status")},
        })

        return {
            "success": True,
            "order_id": order_id,
            "provider": provider_name,
            "shipment": stored,
        }
    
    # =========================================================================
    # SUPPLIER P&L AND REPORTS
    # =========================================================================
    
    def _order_reporting_date(self, order: Dict[str, Any]) -> str:
        """Resolve the most relevant lifecycle timestamp for reporting windows."""
        status = str(order.get("status") or "").strip().lower()
        if status == OrderStatus.COMPLETED.value:
            return (
                order.get("completed_date")
                or order.get("updated_date")
                or order.get("created_date")
                or ""
            )
        if status == OrderStatus.CANCELLED.value:
            return (
                order.get("cancelled_date")
                or order.get("updated_date")
                or order.get("created_date")
                or ""
            )
        if status == OrderStatus.REFUNDED.value:
            return (
                order.get("updated_date")
                or order.get("completed_date")
                or order.get("created_date")
                or ""
            )
        return order.get("updated_date") or order.get("created_date") or ""

    def generate_supplier_pnl(self, supplier_id: str, 
                             period_start: str = None,
                             period_end: str = None) -> Dict[str, Any]:
        """Generate P&L report for a supplier"""
        supplier = self.suppliers.get(supplier_id)
        if not supplier:
            raise ValueError(f"Supplier {supplier_id} not found")
        
        now = datetime.now(timezone.utc)
        if not period_end:
            period_end = now.isoformat()
        if not period_start:
            period_start = (now - timedelta(days=30)).isoformat()
        
        def in_reporting_period(order: Dict[str, Any]) -> bool:
            event_date = self._order_reporting_date(order)
            return period_start <= event_date <= period_end
        
        # Use lifecycle event dates so supplier settlements and P&L report on the same activity window.
        orders = [
            o for o in self.orders.values()
            if o.get("supplier_id") == supplier_id and in_reporting_period(o)
        ]
        
        # Calculate metrics
        completed = [o for o in orders if o.get("status") == OrderStatus.COMPLETED.value]
        cancelled = [o for o in orders if o.get("status") == OrderStatus.CANCELLED.value]
        refunded = [o for o in orders if o.get("status") == OrderStatus.REFUNDED.value]
        
        gross_sales = sum(o.get("total_amount", 0) for o in completed)
        refunds = sum(o.get("total_amount", 0) for o in refunded)
        commission = sum(o.get("commission", 0) for o in completed)
        processing_fees = sum(float(o.get("payment_processing_fee", 0) or 0) for o in completed)
        net_payout = (
            sum(float(o.get("supplier_payout", 0) or 0) for o in completed)
            - sum(float(o.get("supplier_payout", 0) or 0) for o in refunded)
        )
        pending_settlement = sum(float(p.get("amount", 0) or 0) for p in self.pending_settlements.get(supplier_id, []))
        awaiting_customer_approval = sum(
            float(o.get("supplier_payout", 0) or 0)
            for o in orders
            if str(o.get("settlement_status") or "").strip().lower() == "awaiting_customer_approval"
        )
        settled_amount = sum(
            float(record.get("amount", 0) or 0)
            for record in self.settlement_history
            if record.get("supplier_id") == supplier_id
        )
        
        report = SupplierPnLReport(
            supplier_id=supplier_id,
            period_start=period_start,
            period_end=period_end,
            gross_sales=gross_sales,
            refunds=refunds,
            platform_commission=commission,
            payment_processing_fees=processing_fees,
            net_payout=net_payout,
            pending_settlement=pending_settlement,
            settled_amount=settled_amount,
            total_orders=len(orders),
            completed_orders=len(completed),
            cancelled_orders=len(cancelled),
            customer_rating_avg=supplier.get("average_rating", 5.0),
            delivery_on_time_pct=supplier.get("on_time_delivery_rate", 100.0),
            dispute_rate_pct=(supplier.get("dispute_count", 0) / max(1, len(completed))) * 100
        )
        report.calculate_totals()
        report.payment_processing_fees = round(report.payment_processing_fees, 2)
        report.pending_settlement = round(report.pending_settlement, 2)
        report.settled_amount = round(report.settled_amount, 2)
        report.net_payout = round(net_payout, 2)
        report.other_fees = round(awaiting_customer_approval, 2)
        
        if len(completed) > 0:
            report.commission_rate_avg = commission / gross_sales * 100 if gross_sales > 0 else 0
        
        # Sign report
        report_data = json.dumps(report.to_dict(), sort_keys=True)
        report.hash_signature = hmac.new(
            self.secret_key.encode(),
            report_data.encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        
        return {
            "success": True,
            "report": report.to_dict(),
            "supplier_name": supplier.get("company_name")
        }
    
    def get_supplier_statistics(self, supplier_id: str) -> Dict[str, Any]:
        """Get comprehensive statistics for a supplier"""
        supplier = self.suppliers.get(supplier_id)
        if not supplier:
            raise ValueError(f"Supplier {supplier_id} not found")
        
        # Get orders
        all_orders = [o for o in self.orders.values() if o.get("supplier_id") == supplier_id]
        
        # B2B vs B2C breakdown
        b2b_orders = [o for o in all_orders if o.get("is_b2b")]
        b2c_orders = [o for o in all_orders if not o.get("is_b2b")]
        
        # Time-based analysis (last 30 days)
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        recent_orders = [o for o in all_orders if self._order_reporting_date(o) >= thirty_days_ago]
        
        # Order status breakdown
        status_breakdown = {}
        for order in all_orders:
            status = order.get("status", "unknown")
            status_breakdown[status] = status_breakdown.get(status, 0) + 1
        
        # Revenue by month
        revenue_by_month = {}
        for order in all_orders:
            if order.get("status") == OrderStatus.COMPLETED.value:
                month = self._order_reporting_date(order)[:7]
                revenue_by_month[month] = revenue_by_month.get(month, 0) + order.get("supplier_payout", 0)
        
        return {
            "supplier_id": supplier_id,
            "company_name": supplier.get("company_name"),
            "supplier_type": supplier.get("supplier_type"),
            "status": supplier.get("status"),
            "commission_rate": supplier.get("commission_rate"),
            
            # Totals
            "total_orders": len(all_orders),
            "total_revenue": supplier.get("total_revenue", 0),
            "total_commission_paid": supplier.get("total_commission_paid", 0),
            "net_earnings": supplier.get("total_revenue", 0) - supplier.get("total_commission_paid", 0),
            
            # B2B/B2C
            "b2b_orders": len(b2b_orders),
            "b2c_orders": len(b2c_orders),
            "b2b_revenue": supplier.get("b2b_revenue", 0),
            "b2c_revenue": supplier.get("b2c_revenue", 0),
            "b2b_pct": (len(b2b_orders) / max(1, len(all_orders))) * 100,
            
            # Recent activity
            "orders_last_30_days": len(recent_orders),
            "revenue_last_30_days": sum(o.get("supplier_payout", 0) for o in recent_orders 
                                       if o.get("status") == OrderStatus.COMPLETED.value),
            
            # Status breakdown
            "orders_by_status": status_breakdown,
            
            # Performance
            "average_rating": supplier.get("average_rating", 0),
            "total_reviews": supplier.get("total_reviews", 0),
            "on_time_delivery_rate": supplier.get("on_time_delivery_rate", 100),
            "dispute_count": supplier.get("dispute_count", 0),
            
            # Pending
            "pending_settlement": sum(p["amount"] for p in self.pending_settlements.get(supplier_id, [])),
            "awaiting_customer_approval": sum(
                float(o.get("supplier_payout", 0) or 0)
                for o in all_orders
                if str(o.get("settlement_status") or "").strip().lower() == "awaiting_customer_approval"
            ),
            
            # Revenue trend
            "revenue_by_month": revenue_by_month
        }
    
    # =========================================================================
    # PLATFORM-WIDE ANALYTICS
    # =========================================================================
    
    def get_platform_analytics(self) -> Dict[str, Any]:
        """Get platform-wide supply chain analytics"""
        suppliers = list(self.suppliers.values())
        orders = list(self.orders.values())
        
        # Supplier stats
        active_suppliers = [s for s in suppliers if s.get("status") == SupplierStatus.APPROVED.value]
        pending_suppliers = [s for s in suppliers if s.get("status") == SupplierStatus.PENDING.value]
        
        # Order stats
        completed_orders = [o for o in orders if o.get("status") == OrderStatus.COMPLETED.value]
        total_gmv = sum(o.get("total_amount", 0) for o in completed_orders)
        total_commission = sum(o.get("commission", 0) for o in completed_orders)
        total_payouts = sum(o.get("supplier_payout", 0) for o in completed_orders)
        
        # B2B vs B2C
        b2b_orders = [o for o in completed_orders if o.get("is_b2b")]
        b2c_orders = [o for o in completed_orders if not o.get("is_b2b")]
        
        # Supplier type breakdown
        by_type = {}
        for sup in suppliers:
            stype = sup.get("supplier_type", "other")
            if stype not in by_type:
                by_type[stype] = {"count": 0, "active": 0, "revenue": 0}
            by_type[stype]["count"] += 1
            if sup.get("status") == SupplierStatus.APPROVED.value:
                by_type[stype]["active"] += 1
            by_type[stype]["revenue"] += sup.get("total_revenue", 0)
        
        return {
            "suppliers": {
                "total": len(suppliers),
                "active": len(active_suppliers),
                "pending_approval": len(pending_suppliers),
                "by_type": by_type
            },
            "orders": {
                "total": len(orders),
                "completed": len(completed_orders),
                "gmv": total_gmv,
                "b2b_orders": len(b2b_orders),
                "b2c_orders": len(b2c_orders),
                "b2b_gmv": sum(o.get("total_amount", 0) for o in b2b_orders),
                "b2c_gmv": sum(o.get("total_amount", 0) for o in b2c_orders)
            },
            "financials": {
                "total_commission_earned": total_commission,
                "total_supplier_payouts": total_payouts,
                "average_commission_rate": (total_commission / total_gmv * 100) if total_gmv > 0 else 0,
                "pending_settlements": sum(
                    sum(p["amount"] for p in pending)
                    for pending in self.pending_settlements.values()
                )
            },
            "invitations": {
                "total_issued": len(self.invitations),
                "active": len([i for i in self.invitations.values() 
                              if (i.get("status") if isinstance(i, dict) else i.status) == "active"])
            },
            "ledger": {
                "total_entries": len(self.ledger),
                "chain_length": len(self.ledger_chain)
            }
        }
    
    # =========================================================================
    # LEDGER AND DATA INTEGRITY
    # =========================================================================
    
    def _record_ledger_entry(self, entry_type: str, supplier_id: str,
                            customer_id: str = None, order_id: str = None,
                            amount: float = 0, commission: float = 0,
                            supplier_payout: float = 0, description: str = "",
                            metadata: Dict = None) -> SupplyChainLedgerEntry:
        """Record an entry on the supply chain ledger"""
        now = datetime.now(timezone.utc)
        entry_id = f"SCL-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"
        
        # Get previous hash for chain
        previous_hash = self.ledger_chain[-1] if self.ledger_chain else "GENESIS"
        
        entry = SupplyChainLedgerEntry(
            entry_id=entry_id,
            timestamp=now.isoformat(),
            entry_type=entry_type,
            supplier_id=supplier_id,
            customer_id=customer_id,
            order_id=order_id,
            amount=amount,
            commission=commission,
            supplier_payout=supplier_payout,
            description=description,
            metadata=metadata or {},
            previous_hash=previous_hash
        )
        
        # Calculate and set hash
        entry.entry_hash = entry.calculate_hash(self.secret_key)
        
        # Generate NFT token
        nft_token_id = f"NFT-SCL-{secrets.token_hex(6).upper()}"
        entry.nft_token_id = nft_token_id
        
        # Store in NFT ledger
        self.nft_ledger[nft_token_id] = {
            "token_id": nft_token_id,
            "owner_id": "PHINS_PLATFORM",
            "asset_type": "ledger_entry",
            "asset_id": entry_id,
            "created_at": now.isoformat(),
            "metadata": {
                "entry_type": entry_type,
                "supplier_id": supplier_id,
                "amount": amount,
                "hash": entry.entry_hash[:16]
            }
        }
        
        # Store entry and update chain
        self.ledger[entry_id] = entry.to_dict()
        self.ledger_chain.append(entry.entry_hash)
        
        return entry
    
    def verify_ledger_integrity(self) -> Dict[str, Any]:
        """Verify integrity of the entire supply chain ledger"""
        issues = []
        valid_count = 0
        
        entries = sorted(self.ledger.values(), key=lambda x: x.get("timestamp", ""))
        
        for i, entry_dict in enumerate(entries):
            entry = SupplyChainLedgerEntry(**entry_dict)
            
            # Verify hash
            if not entry.verify_hash(self.secret_key):
                issues.append({
                    "entry_id": entry.entry_id,
                    "issue": "Hash verification failed",
                    "severity": "critical"
                })
            else:
                valid_count += 1
            
            # Verify chain continuity
            if i > 0:
                prev_entry = entries[i - 1]
                if entry.previous_hash != prev_entry.get("entry_hash"):
                    issues.append({
                        "entry_id": entry.entry_id,
                        "issue": "Chain continuity broken",
                        "severity": "critical"
                    })
        
        return {
            "total_entries": len(entries),
            "valid_entries": valid_count,
            "issues": issues,
            "integrity_score": (valid_count / max(1, len(entries))) * 100,
            "chain_length": len(self.ledger_chain),
            "verified_at": datetime.now(timezone.utc).isoformat()
        }
    
    def get_ledger_entries(self, supplier_id: str = None, entry_type: str = None,
                          limit: int = 100) -> List[Dict]:
        """Get ledger entries with optional filtering"""
        entries = list(self.ledger.values())
        
        if supplier_id:
            entries = [e for e in entries if e.get("supplier_id") == supplier_id]
        
        if entry_type:
            entries = [e for e in entries if e.get("entry_type") == entry_type]
        
        entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return entries[:limit]


# ============================================================================
# SERVICE INITIALIZATION
# ============================================================================

_supply_chain_service = None

def init_supply_chain_service(suppliers: Dict = None,
                             invitations: Dict = None,
                             offers: Dict = None,
                             orders: Dict = None,
                             ledger: Dict = None,
                             health_wallets: Dict = None,
                             billing: Dict = None,
                             nft_ledger: Dict = None,
                             transaction_ledger: Dict = None,
                             record_transaction_func = None) -> SupplyChainEcosystemService:
    """Initialize the supply chain ecosystem service"""
    global _supply_chain_service
    _supply_chain_service = SupplyChainEcosystemService(
        suppliers_store=suppliers,
        invitations_store=invitations,
        offers_store=offers,
        orders_store=orders,
        ledger_store=ledger,
        health_wallets=health_wallets,
        billing_store=billing,
        nft_ledger=nft_ledger,
        transaction_ledger=transaction_ledger,
        record_transaction_func=record_transaction_func
    )
    return _supply_chain_service

def get_supply_chain_service() -> SupplyChainEcosystemService:
    """Get the supply chain service instance"""
    return _supply_chain_service
