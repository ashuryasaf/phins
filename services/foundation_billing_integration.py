"""
PHINS Foundation Billing Integration Service
=============================================
Integrates foundation contributions/deposits with customer billing dashboard.

This service ensures that:
1. Every foundation deposit creates a corresponding billing record
2. Contributions are tracked in the customer's billing history
3. Foundation-related transactions appear on the customer dashboard
4. Data flows seamlessly from foundation → billing → dashboard

Pipeline Flow:
  Foundation Deposit → Billing Record → Transaction Ledger → Dashboard
"""

import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger('phins.foundation_billing')


@dataclass
class FoundationBillingRecord:
    """A billing record linked to a foundation transaction"""
    id: str
    customer_id: str
    foundation_id: str
    foundation_name: str
    
    # Transaction details
    transaction_type: str  # deposit, contribution, claim_payout, fee
    amount: float
    currency: str = "USD"
    
    # Billing status
    status: str = "completed"  # pending, completed, failed, refunded
    
    # References
    foundation_transaction_id: str = ""  # Reference to contribution/claim ID
    billing_reference: str = ""  # External billing reference
    
    # Timestamps
    created_at: str = ""
    completed_at: str = ""
    
    # Additional metadata
    description: str = ""
    metadata: Dict = None
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        if self.metadata is None:
            result['metadata'] = {}
        return result


class FoundationBillingIntegration:
    """
    Integrates foundation transactions with the billing system.
    
    This service:
    - Creates billing records for foundation deposits
    - Links foundation contributions to customer billing
    - Ensures transactions appear on customer dashboard
    - Maintains data integrity across the pipeline
    """
    
    def __init__(
        self,
        billing_records: Dict[str, Dict] = None,
        transaction_ledger: Dict[str, Dict] = None,
        customer_dashboards: Dict[str, Dict] = None,
        bills: Dict[str, Dict] = None
    ):
        """
        Initialize with references to data stores.
        
        Args:
            billing_records: Foundation billing records store
            transaction_ledger: Global transaction ledger
            customer_dashboards: Customer dashboard data (optional)
            bills: Main billing system bills dict (for BillingService compatibility)
        """
        self.billing_records = billing_records if billing_records is not None else {}
        self.transaction_ledger = transaction_ledger if transaction_ledger is not None else {}
        self.customer_dashboards = customer_dashboards if customer_dashboards is not None else {}
        self.bills = bills if bills is not None else {}
        
        # Track last billing record ID
        self._last_id = 0
        
        logger.info("Foundation billing integration initialized")
    
    def record_foundation_deposit(
        self,
        customer_id: str,
        foundation_id: str,
        foundation_name: str,
        amount: float,
        contribution_id: str = "",
        fund_name: str = "",
        notes: str = ""
    ) -> FoundationBillingRecord:
        """
        Record a foundation deposit in the billing system.
        
        This is called when a customer makes a deposit/contribution to a foundation.
        It creates:
        1. A billing record for tracking
        2. A transaction ledger entry
        3. Updates the customer dashboard data
        
        Args:
            customer_id: Customer making the deposit
            foundation_id: Foundation receiving the deposit
            foundation_name: Name of the foundation
            amount: Amount deposited
            contribution_id: Reference to the contribution record
            fund_name: Name of the fund (if applicable)
            notes: Additional notes
            
        Returns:
            FoundationBillingRecord
        """
        now = datetime.now(timezone.utc)
        
        # Generate billing record ID
        self._last_id += 1
        record_id = f"FNDBILL-{now.strftime('%Y%m%d')}-{self._last_id:06d}"
        
        # Create the billing record
        record = FoundationBillingRecord(
            id=record_id,
            customer_id=customer_id,
            foundation_id=foundation_id,
            foundation_name=foundation_name,
            transaction_type="deposit",
            amount=amount,
            status="completed",
            foundation_transaction_id=contribution_id,
            billing_reference=f"FND-DEP-{now.strftime('%Y%m%d%H%M%S')}",
            created_at=now.isoformat(),
            completed_at=now.isoformat(),
            description=f"Foundation deposit: {foundation_name}" + (f" - {fund_name}" if fund_name else ""),
            metadata={
                "fund_name": fund_name,
                "notes": notes,
                "source": "foundation_contribution"
            }
        )
        
        # Store the record
        self.billing_records[record_id] = record.to_dict()
        
        # Create transaction ledger entry
        self._record_to_transaction_ledger(record)
        
        # Update customer dashboard
        self._update_customer_dashboard(customer_id, record)
        
        # Create a bill record for billing service compatibility
        self._create_bill_record(record)
        
        logger.info(f"Foundation deposit recorded: {record_id} - ${amount} for customer {customer_id}")
        
        return record
    
    def record_claim_payout(
        self,
        customer_id: str,
        foundation_id: str,
        foundation_name: str,
        amount: float,
        claim_id: str = "",
        claim_type: str = "",
        notes: str = ""
    ) -> FoundationBillingRecord:
        """
        Record a foundation claim payout in the billing system.
        
        This is called when a customer receives a payout from a foundation claim.
        
        Args:
            customer_id: Customer receiving the payout
            foundation_id: Foundation making the payout
            foundation_name: Name of the foundation
            amount: Payout amount
            claim_id: Reference to the claim record
            claim_type: Type of claim
            notes: Additional notes
            
        Returns:
            FoundationBillingRecord
        """
        now = datetime.now(timezone.utc)
        
        # Generate billing record ID
        self._last_id += 1
        record_id = f"FNDBILL-{now.strftime('%Y%m%d')}-{self._last_id:06d}"
        
        # Create the billing record
        record = FoundationBillingRecord(
            id=record_id,
            customer_id=customer_id,
            foundation_id=foundation_id,
            foundation_name=foundation_name,
            transaction_type="claim_payout",
            amount=amount,
            status="completed",
            foundation_transaction_id=claim_id,
            billing_reference=f"FND-CLM-{now.strftime('%Y%m%d%H%M%S')}",
            created_at=now.isoformat(),
            completed_at=now.isoformat(),
            description=f"Foundation claim payout: {foundation_name}" + (f" - {claim_type}" if claim_type else ""),
            metadata={
                "claim_type": claim_type,
                "notes": notes,
                "source": "foundation_claim"
            }
        )
        
        # Store the record
        self.billing_records[record_id] = record.to_dict()
        
        # Create transaction ledger entry (credit to customer)
        self._record_to_transaction_ledger(record, is_credit=True)
        
        # Update customer dashboard
        self._update_customer_dashboard(customer_id, record, is_credit=True)
        
        logger.info(f"Foundation claim payout recorded: {record_id} - ${amount} to customer {customer_id}")
        
        return record
    
    def get_customer_foundation_billing(
        self,
        customer_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get all foundation billing records for a customer.
        
        Args:
            customer_id: Customer ID
            limit: Maximum records to return
            
        Returns:
            List of billing records
        """
        records = []
        
        for record_id, record in self.billing_records.items():
            if record.get('customer_id') == customer_id:
                records.append(record)
        
        # Sort by created_at descending
        records.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return records[:limit]
    
    def get_foundation_billing_summary(
        self,
        customer_id: str
    ) -> Dict[str, Any]:
        """
        Get billing summary for a customer's foundation activity.
        
        Returns:
            Summary with totals, transaction counts, etc.
        """
        records = self.get_customer_foundation_billing(customer_id, limit=1000)
        
        total_deposits = 0.0
        total_payouts = 0.0
        deposits_count = 0
        payouts_count = 0
        foundations = set()
        
        for record in records:
            amount = float(record.get('amount', 0))
            tx_type = record.get('transaction_type', '')
            
            if tx_type in ['deposit', 'contribution']:
                total_deposits += amount
                deposits_count += 1
            elif tx_type in ['claim_payout']:
                total_payouts += amount
                payouts_count += 1
            
            if record.get('foundation_id'):
                foundations.add(record.get('foundation_id'))
        
        return {
            'customer_id': customer_id,
            'total_deposits': total_deposits,
            'total_payouts': total_payouts,
            'net_contributions': total_deposits - total_payouts,
            'deposits_count': deposits_count,
            'payouts_count': payouts_count,
            'total_transactions': len(records),
            'foundations_count': len(foundations),
            'foundations': list(foundations),
            'last_activity': records[0].get('created_at') if records else None,
            'generated_at': datetime.now(timezone.utc).isoformat()
        }
    
    def get_dashboard_billing_data(
        self,
        customer_id: str
    ) -> Dict[str, Any]:
        """
        Get foundation billing data formatted for the customer dashboard.
        
        This is the data that appears on the customer's billing dashboard.
        
        Returns:
            Dashboard-formatted billing data
        """
        records = self.get_customer_foundation_billing(customer_id, limit=20)
        summary = self.get_foundation_billing_summary(customer_id)
        
        # Format for dashboard display
        recent_transactions = []
        for record in records[:10]:
            tx_type = record.get('transaction_type', '')
            is_credit = tx_type in ['claim_payout']
            
            recent_transactions.append({
                'id': record.get('id'),
                'date': record.get('created_at'),
                'description': record.get('description'),
                'amount': record.get('amount'),
                'type': 'credit' if is_credit else 'debit',
                'status': record.get('status'),
                'foundation': record.get('foundation_name'),
                'reference': record.get('billing_reference')
            })
        
        return {
            'customer_id': customer_id,
            'foundation_billing': {
                'summary': {
                    'total_contributed': summary['total_deposits'],
                    'total_received': summary['total_payouts'],
                    'net_position': summary['net_contributions'],
                    'active_foundations': summary['foundations_count']
                },
                'recent_transactions': recent_transactions,
                'transaction_count': summary['total_transactions']
            },
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
    
    def _record_to_transaction_ledger(
        self,
        record: FoundationBillingRecord,
        is_credit: bool = False
    ) -> None:
        """Create a transaction ledger entry for the billing record."""
        if self.transaction_ledger is None:
            return
        
        tx_id = f"FNDTX-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{record.id[-6:]}"
        
        ledger_entry = {
            'id': tx_id,
            'customer_id': record.customer_id,
            'type': f"foundation_{record.transaction_type}",
            'amount': record.amount if is_credit else -record.amount,  # Negative for debits
            'description': record.description,
            'reference': record.billing_reference,
            'foundation_id': record.foundation_id,
            'foundation_name': record.foundation_name,
            'billing_record_id': record.id,
            'status': record.status,
            'timestamp': record.created_at,
            'metadata': {
                'source': 'foundation_billing_integration',
                'transaction_type': record.transaction_type,
                **(record.metadata or {})
            }
        }
        
        self.transaction_ledger[tx_id] = ledger_entry
        
        logger.debug(f"Transaction ledger entry created: {tx_id}")
    
    def _update_customer_dashboard(
        self,
        customer_id: str,
        record: FoundationBillingRecord,
        is_credit: bool = False
    ) -> None:
        """Update the customer dashboard data with the billing record."""
        if self.customer_dashboards is None:
            return
        
        if customer_id not in self.customer_dashboards:
            self.customer_dashboards[customer_id] = {
                'customer_id': customer_id,
                'foundation_summary': {
                    'total_deposits': 0.0,
                    'total_payouts': 0.0,
                    'net_contributions': 0.0,
                    'active_foundations': set()
                },
                'recent_foundation_activity': [],
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
        
        dashboard = self.customer_dashboards[customer_id]
        
        # Update summary
        summary = dashboard.setdefault('foundation_summary', {
            'total_deposits': 0.0,
            'total_payouts': 0.0,
            'net_contributions': 0.0,
            'active_foundations': set()
        })
        
        if is_credit:
            summary['total_payouts'] = float(summary.get('total_payouts', 0)) + record.amount
        else:
            summary['total_deposits'] = float(summary.get('total_deposits', 0)) + record.amount
        
        summary['net_contributions'] = float(summary.get('total_deposits', 0)) - float(summary.get('total_payouts', 0))
        
        # Track active foundations
        if isinstance(summary.get('active_foundations'), set):
            summary['active_foundations'].add(record.foundation_id)
            summary['active_foundations_count'] = len(summary['active_foundations'])
            # Convert set to list for JSON serialization
            summary['active_foundations'] = list(summary['active_foundations'])
        
        # Add to recent activity
        activity = dashboard.setdefault('recent_foundation_activity', [])
        activity.insert(0, {
            'record_id': record.id,
            'type': record.transaction_type,
            'amount': record.amount,
            'foundation_name': record.foundation_name,
            'description': record.description,
            'timestamp': record.created_at
        })
        
        # Keep only recent 20 activities
        dashboard['recent_foundation_activity'] = activity[:20]
        dashboard['updated_at'] = datetime.now(timezone.utc).isoformat()
    
    def _create_bill_record(self, record: FoundationBillingRecord) -> None:
        """Create a bill record for BillingService compatibility."""
        if self.bills is None:
            return
        
        # Only create bills for deposits (not payouts)
        if record.transaction_type not in ['deposit', 'contribution']:
            return
        
        bill_id = f"FNDBILL-{record.id}"
        
        bill = {
            'bill_id': bill_id,
            'customer_id': record.customer_id,
            'policy_id': f"FND-{record.foundation_id}",  # Use foundation as "policy"
            'amount_due': record.amount,
            'amount_paid': record.amount,  # Foundation deposits are pre-paid
            'status': 'paid',
            'due_date': record.created_at[:10],  # Date portion
            'created_at': record.created_at,
            'updated_at': record.completed_at,
            'type': 'foundation_contribution',
            'description': record.description,
            'foundation_id': record.foundation_id,
            'foundation_name': record.foundation_name,
            'billing_reference': record.billing_reference
        }
        
        self.bills[bill_id] = bill
        
        logger.debug(f"Bill record created: {bill_id}")
    
    def sync_all_contributions(
        self,
        contributions: Dict[str, Dict],
        foundations: Dict[str, Dict],
        members: Dict[str, Dict]
    ) -> int:
        """
        Sync all existing contributions to billing records.
        
        This is called on startup to ensure all contributions are reflected
        in the billing system.
        
        Returns:
            Number of records synced
        """
        synced = 0
        
        for contrib_id, contrib in contributions.items():
            # Check if already has a billing record
            existing = False
            for record in self.billing_records.values():
                if record.get('foundation_transaction_id') == contrib_id:
                    existing = True
                    break
            
            if existing:
                continue
            
            # Get member info
            member_id = contrib.get('member_id', '')
            member = members.get(member_id, {})
            customer_id = member.get('member_id', member_id)
            
            # Get foundation info
            fund_id = contrib.get('fund_id', '')
            foundation_id = None
            foundation_name = None
            
            for fnd_id, fnd in foundations.items():
                # Check if this foundation has the fund
                if any(f.get('id') == fund_id for f in fnd.get('_funds', [])):
                    foundation_id = fnd_id
                    foundation_name = fnd.get('name', 'Unknown Foundation')
                    break
            
            if not foundation_id:
                # Try to find foundation from member
                foundation_id = member.get('foundation_id')
                foundation = foundations.get(foundation_id, {})
                foundation_name = foundation.get('name', 'Unknown Foundation')
            
            if foundation_id:
                self.record_foundation_deposit(
                    customer_id=customer_id,
                    foundation_id=foundation_id,
                    foundation_name=foundation_name or 'Unknown Foundation',
                    amount=float(contrib.get('amount', 0)),
                    contribution_id=contrib_id,
                    notes=contrib.get('notes', '')
                )
                synced += 1
        
        logger.info(f"Synced {synced} contributions to billing records")
        return synced


# Singleton instance
_billing_integration: Optional[FoundationBillingIntegration] = None


def get_billing_integration(
    billing_records: Dict = None,
    transaction_ledger: Dict = None,
    customer_dashboards: Dict = None,
    bills: Dict = None
) -> FoundationBillingIntegration:
    """
    Get or create the billing integration singleton.
    
    If external dictionaries are provided, they will be used for storage,
    ensuring data is visible to the caller.
    """
    global _billing_integration
    if _billing_integration is None:
        _billing_integration = FoundationBillingIntegration(
            billing_records=billing_records,
            transaction_ledger=transaction_ledger,
            customer_dashboards=customer_dashboards,
            bills=bills
        )
    else:
        # Update references if new dictionaries are provided
        # This ensures the caller's dictionaries are used
        if billing_records is not None:
            _billing_integration.billing_records = billing_records
        if transaction_ledger is not None:
            _billing_integration.transaction_ledger = transaction_ledger
        if customer_dashboards is not None:
            _billing_integration.customer_dashboards = customer_dashboards
        if bills is not None:
            _billing_integration.bills = bills
    
    return _billing_integration


def init_billing_integration(
    billing_records: Dict = None,
    transaction_ledger: Dict = None,
    customer_dashboards: Dict = None,
    bills: Dict = None
) -> FoundationBillingIntegration:
    """
    Initialize or reinitialize the billing integration with new data stores.
    
    Use this when you need to ensure specific dictionaries are used for storage.
    """
    global _billing_integration
    _billing_integration = FoundationBillingIntegration(
        billing_records=billing_records,
        transaction_ledger=transaction_ledger,
        customer_dashboards=customer_dashboards,
        bills=bills
    )
    return _billing_integration


def reset_billing_integration() -> None:
    """Reset the billing integration (for testing)."""
    global _billing_integration
    _billing_integration = None
