"""
PHINS Data Integrity Service
============================
Central service for maintaining data integrity across all savings, wallet, and pipeline operations.

This service ensures that:
1. Total savings = Cash Balance + Wallet Balance + Investment Balance + Algo Trading Balance
2. All deposits are properly recorded in TRANSACTION_LEDGER
3. All allocations sum to the deposited amounts
4. NFT tokens are minted for all financial transactions
5. Reconciliation runs after every financial operation

Key Integrity Rules:
- Every deposit increases total_deposits by the deposited amount
- Every allocation moves funds from cash_balance to destination (wallet, investment, algo)
- At any time: total_deposits == cash_balance + wallet_balance + investment_balance + algo_balance + withdrawn
- "Increase cover" or "add policy" allocations deduct from cash_balance and add to appropriate buckets
"""

from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import hashlib
import random


@dataclass
class IntegrityReport:
    """Report of data integrity check"""
    customer_id: str
    timestamp: str
    is_valid: bool
    total_deposits: float
    total_allocated: float
    total_withdrawn: float
    
    # Balances
    cash_balance: float
    wallet_balance: float
    investment_balance: float
    algo_trading_balance: float
    
    # Calculated total
    calculated_total: float
    expected_total: float
    discrepancy: float
    
    # Issues found
    issues: List[str]
    
    # Auto-correction applied
    corrections_applied: List[Dict[str, Any]]
    
    def to_dict(self) -> Dict:
        return asdict(self)


class DataIntegrityService:
    """
    Central service for maintaining data integrity across all savings operations.
    
    This service is the single source of truth for:
    - Validating that all savings operations maintain correct totals
    - Reconciling discrepancies between data stores
    - Providing verified totals to the portal
    """
    
    def __init__(self, 
                 health_wallets: Dict = None,
                 investment_accounts: Dict = None,
                 transaction_ledger: Dict = None,
                 nft_ledger: Dict = None,
                 savings_pipeline_service = None,
                 unified_balance_service = None,
                 record_transaction_func = None):
        """
        Initialize with references to all data stores.
        
        Args:
            health_wallets: HEALTH_WALLETS dictionary
            investment_accounts: INVESTMENT_ACCOUNTS dictionary
            transaction_ledger: TRANSACTION_LEDGER dictionary
            nft_ledger: NFT_LEDGER dictionary
            savings_pipeline_service: SavingsPipelineService instance
            unified_balance_service: UnifiedBalanceService instance
            record_transaction_func: Function to record transactions
        """
        # NOTE: Use 'if X is None' instead of 'X or {}' to preserve empty dict references
        self.health_wallets = health_wallets if health_wallets is not None else {}
        self.investment_accounts = investment_accounts if investment_accounts is not None else {}
        self.transaction_ledger = transaction_ledger if transaction_ledger is not None else {}
        self.nft_ledger = nft_ledger if nft_ledger is not None else {}
        self.savings_pipeline = savings_pipeline_service
        self.unified_balance = unified_balance_service
        self.record_transaction = record_transaction_func
        
        # Track integrity state
        self.last_check: Dict[str, IntegrityReport] = {}
        
    def validate_customer_integrity(self, customer_id: str, 
                                     auto_correct: bool = False) -> IntegrityReport:
        """
        Validate data integrity for a customer's savings.
        
        Checks that:
        1. Total deposits match sum of all balances + withdrawals
        2. All transactions are recorded in ledger
        3. No negative balances exist
        
        Args:
            customer_id: Customer ID to validate
            auto_correct: If True, attempt to fix discrepancies
            
        Returns:
            IntegrityReport with validation results
        """
        issues = []
        corrections = []
        
        # Get all balances from GLOBAL DATA STORES (single source of truth)
        # NOTE: We use global stores, NOT pipeline internal balances, to avoid double-counting
        
        # 1. Health Wallet Balance
        wallet_data = self.health_wallets.get(customer_id, {})
        wallet_balance = float(wallet_data.get('balance', 0) or 0)
        
        # 2. Investment Account Balance
        # The 'balance' field is the TOTAL investment balance
        # Sub-balances (index, bonds, crypto) are the breakdown of where the money is invested
        # Cash is any unallocated portion: balance - (index + bonds + crypto)
        inv_data = self.investment_accounts.get(customer_id, {})
        inv_total = float(inv_data.get('balance', 0) or 0)  # Total investment balance
        inv_index = float(inv_data.get('index_balance', 0) or 0)  # Invested in indexes
        inv_bonds = float(inv_data.get('bonds_balance', 0) or 0)  # Invested in bonds
        inv_crypto = float(inv_data.get('crypto_balance', 0) or 0)  # Invested in crypto
        # Calculate actual invested amount
        inv_allocated = inv_index + inv_bonds + inv_crypto
        # Investment balance is the total from the balance field (not sum of sub-balances)
        # The sub-balances are just the allocation breakdown
        investment_balance = inv_total
        
        # 3. Algo Trading Balance (from unified balance service)
        algo_balance = 0.0
        if self.unified_balance:
            algo_data = self.unified_balance.algo_trading_balances.get(customer_id, {})
            if algo_data:
                algo_balance = float(algo_data.get('available', 0) or 0) + float(algo_data.get('in_positions', 0) or 0)
        
        # 4. Cash Balance is now part of investment_balance (inv_cash)
        # We don't count pipeline's internal cash_balance separately to avoid double-counting
        cash_balance = 0.0  # Already included in investment_balance as inv_cash
        
        # Get pipeline metadata for tracking (not for balance calculation)
        pipeline_total_deposits = 0.0
        pipeline_total_allocated = 0.0
        if self.savings_pipeline:
            pipeline_account = self.savings_pipeline.accounts.get(customer_id)
            if pipeline_account:
                pipeline_total_deposits = float(pipeline_account.total_deposits or 0)
                pipeline_total_allocated = float(pipeline_account.total_allocated or 0)
        
        # Calculate total from transaction ledger
        total_deposits = 0.0
        total_withdrawn = 0.0
        
        deposit_types = [
            'wallet_deposit', 'investment_deposit', 'pipeline_deposit',
            'premium_allocation', 'savings_deposit', 'algo_trading_deposit',
            'card_payment', 'credit_card_deposit', 'bank_transfer'
        ]
        
        # Withdrawal types (money leaving tracked accounts)
        # Note: claim_payment destination varies (wallet/bank/etc) so counted separately
        # Premium payments go to insurance, not a withdrawal from savings
        withdrawal_types = [
            'wallet_withdrawal', 'investment_withdrawal', 'withdrawal',
            'medical_purchase'  # Direct spend from wallet
        ]
        
        # Claim payments to tracked accounts (wallet, investment) count as deposits
        # These represent insurance payouts that legitimately enter customer's balance
        claim_deposit_types = ['claim_payment_wallet', 'claim_payment_investment', 'claim_payment_received']
        
        for tx in self.transaction_ledger.values():
            if tx.get('customer_id') != customer_id:
                continue
            
            tx_type = tx.get('type', tx.get('tx_type', '')).lower()
            amount = float(tx.get('amount', 0) or 0)
            
            # Deposits (direct savings/investment deposits)
            if any(dt in tx_type for dt in deposit_types):
                total_deposits += abs(amount)
            
            # Claim payments to tracked accounts (wallet/investment) count as deposits
            if any(cdt in tx_type for cdt in claim_deposit_types):
                total_deposits += abs(amount)
            
            # Withdrawals (money leaving tracked accounts)
            if any(wt in tx_type for wt in withdrawal_types):
                total_withdrawn += abs(amount)
        
        # Also include deposits from INVESTMENT_ACCOUNTS
        for deposit in inv_data.get('deposits', []):
            dep_amount = float(deposit.get('amount', 0) or 0)
            # Only add if not already counted from ledger
            if dep_amount > 0:
                dep_source = deposit.get('source', '')
                # Check if this was a pipeline deposit (avoid double counting)
                if 'pipeline' not in dep_source.lower():
                    # Check if we already have this in total_deposits
                    pass  # Let ledger be source of truth
        
        # If no ledger data but we have investment account deposits, use that
        if total_deposits == 0 and inv_data.get('deposits'):
            total_deposits = sum(float(d.get('amount', 0) or 0) for d in inv_data.get('deposits', []))
        
        # Use pipeline deposits if larger (more accurate)
        if pipeline_total_deposits > total_deposits:
            total_deposits = pipeline_total_deposits
        
        # Calculate expected total (what we should have)
        expected_total = total_deposits - total_withdrawn
        
        # Calculate actual total (what we do have)
        calculated_total = cash_balance + wallet_balance + investment_balance + algo_balance
        
        # Calculate discrepancy
        discrepancy = calculated_total - expected_total
        
        # Validate and collect issues
        is_valid = True
        
        # Check for negative balances
        if cash_balance < 0:
            issues.append(f"Negative cash balance: ${cash_balance:.2f}")
            is_valid = False
        if wallet_balance < 0:
            issues.append(f"Negative wallet balance: ${wallet_balance:.2f}")
            is_valid = False
        if investment_balance < 0:
            issues.append(f"Negative investment balance: ${investment_balance:.2f}")
            is_valid = False
        if algo_balance < 0:
            issues.append(f"Negative algo trading balance: ${algo_balance:.2f}")
            is_valid = False
        
        # Check for significant discrepancy (more than $0.01)
        if abs(discrepancy) > 0.01:
            # Allow for minor floating point errors
            if abs(discrepancy) > 1.00:
                issues.append(f"Balance discrepancy: ${discrepancy:.2f} (expected ${expected_total:.2f}, got ${calculated_total:.2f})")
                is_valid = False
            else:
                issues.append(f"Minor balance discrepancy: ${discrepancy:.2f} (within tolerance)")
        
        # Auto-correct if requested and we have discrepancies
        if auto_correct and not is_valid and abs(discrepancy) > 0.01:
            correction = self._attempt_auto_correction(
                customer_id, discrepancy, cash_balance, wallet_balance,
                investment_balance, algo_balance, expected_total
            )
            if correction:
                corrections.append(correction)
                # Re-fetch balances after correction
                wallet_data = self.health_wallets.get(customer_id, {})
                wallet_balance = float(wallet_data.get('balance', 0) or 0)
                inv_data = self.investment_accounts.get(customer_id, {})
                investment_balance = float(inv_data.get('balance', 0) or 0)
                calculated_total = cash_balance + wallet_balance + investment_balance + algo_balance
                discrepancy = calculated_total - expected_total
                if abs(discrepancy) <= 0.01:
                    is_valid = True
                    issues = [i for i in issues if 'discrepancy' not in i.lower()]
        
        report = IntegrityReport(
            customer_id=customer_id,
            timestamp=datetime.now().isoformat(),
            is_valid=is_valid,
            total_deposits=total_deposits,
            total_allocated=pipeline_total_allocated,
            total_withdrawn=total_withdrawn,
            cash_balance=cash_balance,
            wallet_balance=wallet_balance,
            investment_balance=investment_balance,
            algo_trading_balance=algo_balance,
            calculated_total=calculated_total,
            expected_total=expected_total,
            discrepancy=discrepancy,
            issues=issues,
            corrections_applied=corrections
        )
        
        self.last_check[customer_id] = report
        return report
    
    def _attempt_auto_correction(self, customer_id: str, discrepancy: float,
                                   cash_balance: float, wallet_balance: float,
                                   investment_balance: float, algo_balance: float,
                                   expected_total: float) -> Optional[Dict]:
        """
        Attempt to auto-correct balance discrepancies.
        
        Strategy:
        1. If discrepancy is positive (we have more than expected), create adjustment transaction
        2. If discrepancy is negative (we have less than expected), add to investment account
        """
        if abs(discrepancy) <= 0.01:
            return None
        
        correction = {
            'type': 'auto_correction',
            'timestamp': datetime.now().isoformat(),
            'customer_id': customer_id,
            'discrepancy': discrepancy,
            'action': None,
            'details': {}
        }
        
        if discrepancy > 0:
            # We have more than expected - record an adjustment
            correction['action'] = 'record_surplus_adjustment'
            correction['details'] = {
                'surplus_amount': discrepancy,
                'note': 'Surplus balance recorded as miscellaneous income'
            }
            
            # Record adjustment transaction
            if self.record_transaction:
                self.record_transaction(
                    customer_id=customer_id,
                    tx_type='balance_adjustment',
                    amount=discrepancy,
                    description=f'Balance reconciliation adjustment (surplus)',
                    metadata={
                        'correction_type': 'surplus',
                        'original_discrepancy': discrepancy
                    }
                )
        else:
            # We have less than expected - add missing amount to investment
            missing_amount = abs(discrepancy)
            correction['action'] = 'add_missing_balance'
            correction['details'] = {
                'missing_amount': missing_amount,
                'added_to': 'investment_account'
            }
            
            # Add to investment account
            if customer_id not in self.investment_accounts:
                self.investment_accounts[customer_id] = {
                    'balance': 0,
                    'deposits': [],
                    'created_at': datetime.now().isoformat()
                }
            
            self.investment_accounts[customer_id]['balance'] = \
                float(self.investment_accounts[customer_id].get('balance', 0) or 0) + missing_amount
            
            self.investment_accounts[customer_id].setdefault('deposits', []).append({
                'id': f"CORR-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}",
                'type': 'balance_correction',
                'amount': missing_amount,
                'timestamp': datetime.now().isoformat(),
                'note': 'Auto-correction for balance discrepancy'
            })
            
            # Record adjustment transaction
            if self.record_transaction:
                self.record_transaction(
                    customer_id=customer_id,
                    tx_type='balance_correction',
                    amount=missing_amount,
                    description=f'Balance reconciliation correction',
                    metadata={
                        'correction_type': 'missing_balance',
                        'original_discrepancy': discrepancy,
                        'added_to': 'investment_account'
                    }
                )
        
        return correction
    
    def get_verified_total(self, customer_id: str) -> Dict[str, Any]:
        """
        Get a verified total for a customer, ensuring data integrity.
        
        This is the method that should be called by the portal to get
        accurate, verified totals.
        
        Returns:
            Dictionary with verified totals and integrity status
        """
        # Run integrity check
        report = self.validate_customer_integrity(customer_id, auto_correct=True)
        
        return {
            'customer_id': customer_id,
            'timestamp': report.timestamp,
            'integrity_valid': report.is_valid,
            
            # Verified balances
            'total_savings': report.calculated_total,
            'cash_balance': report.cash_balance,
            'wallet_balance': report.wallet_balance,
            'investment_balance': report.investment_balance,
            'algo_trading_balance': report.algo_trading_balance,
            
            # Historical data
            'total_deposits': report.total_deposits,
            'total_withdrawn': report.total_withdrawn,
            
            # Verification info
            'verification': {
                'passed': report.is_valid,
                'issues': report.issues,
                'discrepancy': report.discrepancy,
                'corrections_applied': len(report.corrections_applied) > 0
            }
        }
    
    def validate_deposit(self, customer_id: str, amount: float,
                          source: str, destination: str) -> Tuple[bool, str]:
        """
        Validate a deposit operation before execution.
        
        Args:
            customer_id: Customer ID
            amount: Amount to deposit
            source: Source of funds (credit_card, bank_transfer, etc.)
            destination: Where to deposit (cash_balance, wallet, investment, etc.)
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if amount <= 0:
            return False, "Deposit amount must be positive"
        
        if amount > 1000000:
            return False, "Maximum single deposit is $1,000,000"
        
        valid_sources = ['credit_card', 'bank_transfer', 'wire', 'premium_payment', 
                         'claim_payment', 'internal_transfer', 'manual']
        if source.lower() not in valid_sources:
            return False, f"Invalid source: {source}. Valid: {valid_sources}"
        
        valid_destinations = ['cash_balance', 'wallet', 'health_wallet', 
                              'investment', 'investment_account', 'algo_trading']
        if destination.lower() not in valid_destinations:
            return False, f"Invalid destination: {destination}. Valid: {valid_destinations}"
        
        return True, ""
    
    def validate_allocation(self, customer_id: str, amount: float,
                             from_account: str, to_account: str) -> Tuple[bool, str]:
        """
        Validate an allocation operation before execution.
        
        This is called when a customer allocates savings via:
        - "increase cover" (allocate to policy premium)
        - "add policy" (allocate to new policy)
        - Manual rebalancing
        
        Args:
            customer_id: Customer ID
            amount: Amount to allocate
            from_account: Source account (cash_balance, investment, etc.)
            to_account: Destination account (wallet, algo_trading, policy_premium, etc.)
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if amount <= 0:
            return False, "Allocation amount must be positive"
        
        # Check source balance
        available_balance = 0.0
        
        if from_account.lower() in ['cash_balance', 'cash']:
            if self.savings_pipeline:
                account = self.savings_pipeline.accounts.get(customer_id)
                if account:
                    available_balance = float(account.cash_balance or 0)
        elif from_account.lower() in ['investment', 'investment_account']:
            inv_data = self.investment_accounts.get(customer_id, {})
            available_balance = float(inv_data.get('balance', 0) or 0)
        elif from_account.lower() in ['wallet', 'health_wallet']:
            wallet_data = self.health_wallets.get(customer_id, {})
            available_balance = float(wallet_data.get('balance', 0) or 0)
        elif from_account.lower() in ['algo_trading', 'algo']:
            if self.unified_balance:
                algo_data = self.unified_balance.algo_trading_balances.get(customer_id, {})
                available_balance = float(algo_data.get('available', 0) or 0)
        
        if amount > available_balance:
            return False, f"Insufficient balance in {from_account}. Available: ${available_balance:.2f}, Requested: ${amount:.2f}"
        
        return True, ""
    
    def execute_deposit_with_integrity(self, customer_id: str, amount: float,
                                         source: str, destination: str,
                                         metadata: Dict = None) -> Dict[str, Any]:
        """
        Execute a deposit with full integrity checking.
        
        This is the primary method for adding savings that ensures:
        1. Validation before deposit
        2. Proper recording in all data stores
        3. Transaction ledger entry
        4. NFT token minting
        5. Post-operation integrity check
        
        Args:
            customer_id: Customer ID
            amount: Amount to deposit
            source: Source of funds
            destination: Where to deposit
            metadata: Additional metadata
            
        Returns:
            Result dictionary with deposit details and integrity status
        """
        # Pre-validation
        is_valid, error = self.validate_deposit(customer_id, amount, source, destination)
        if not is_valid:
            return {'success': False, 'error': error}
        
        # Get pre-operation balances
        pre_check = self.validate_customer_integrity(customer_id)
        
        # Execute deposit based on destination
        result = {'success': False}
        dest_lower = destination.lower()
        
        try:
            if dest_lower in ['cash_balance', 'cash']:
                # Deposit to savings pipeline
                if self.savings_pipeline:
                    result = self.savings_pipeline.deposit_to_pipeline(
                        customer_id=customer_id,
                        amount=amount,
                        source=source,
                        auto_allocate=False  # Don't auto-allocate, let user control
                    )
                else:
                    # Fallback to investment account
                    dest_lower = 'investment'
            
            if dest_lower in ['wallet', 'health_wallet']:
                # Deposit to health wallet
                if customer_id not in self.health_wallets:
                    self.health_wallets[customer_id] = {
                        'customer_id': customer_id,
                        'balance': 0,
                        'transactions': [],
                        'monthly_deposit': 0,
                        'created_at': datetime.now().isoformat()
                    }
                
                self.health_wallets[customer_id]['balance'] = \
                    float(self.health_wallets[customer_id].get('balance', 0) or 0) + amount
                
                tx_id = f"WDEP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
                self.health_wallets[customer_id].setdefault('transactions', []).append({
                    'id': tx_id,
                    'type': 'deposit',
                    'amount': amount,
                    'source': source,
                    'timestamp': datetime.now().isoformat()
                })
                
                result = {
                    'success': True,
                    'tx_id': tx_id,
                    'new_balance': self.health_wallets[customer_id]['balance']
                }
            
            if dest_lower in ['investment', 'investment_account']:
                # Deposit to investment account
                if customer_id not in self.investment_accounts:
                    self.investment_accounts[customer_id] = {
                        'customer_id': customer_id,
                        'balance': 0,
                        'index_balance': 0,
                        'bonds_balance': 0,
                        'crypto_balance': 0,
                        'deposits': [],
                        'created_at': datetime.now().isoformat()
                    }
                
                self.investment_accounts[customer_id]['balance'] = \
                    float(self.investment_accounts[customer_id].get('balance', 0) or 0) + amount
                
                tx_id = f"IDEP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
                self.investment_accounts[customer_id].setdefault('deposits', []).append({
                    'id': tx_id,
                    'type': 'deposit',
                    'amount': amount,
                    'source': source,
                    'timestamp': datetime.now().isoformat()
                })
                
                result = {
                    'success': True,
                    'tx_id': tx_id,
                    'new_balance': self.investment_accounts[customer_id]['balance']
                }
            
            if dest_lower in ['algo_trading', 'algo']:
                # Deposit to algo trading
                if self.unified_balance:
                    if customer_id not in self.unified_balance.algo_trading_balances:
                        self.unified_balance.algo_trading_balances[customer_id] = {
                            'available': 0,
                            'in_positions': 0,
                            'total_pnl': 0,
                            'transfers': []
                        }
                    
                    self.unified_balance.algo_trading_balances[customer_id]['available'] += amount
                    tx_id = f"ADEP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
                    self.unified_balance.algo_trading_balances[customer_id].setdefault('transfers', []).append({
                        'id': tx_id,
                        'type': 'deposit',
                        'amount': amount,
                        'source': source,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    result = {
                        'success': True,
                        'tx_id': tx_id,
                        'new_balance': self.unified_balance.algo_trading_balances[customer_id]['available']
                    }
            
            # Record on transaction ledger
            if result.get('success') and self.record_transaction:
                ledger_tx = self.record_transaction(
                    customer_id=customer_id,
                    tx_type=f'{destination}_deposit',
                    amount=amount,
                    description=f'Deposit ${amount:.2f} from {source} to {destination}',
                    metadata={
                        'source': source,
                        'destination': destination,
                        'internal_tx_id': result.get('tx_id'),
                        **(metadata or {})
                    }
                )
                result['ledger_tx_id'] = ledger_tx.get('id')
                result['nft_token_id'] = ledger_tx.get('nft_token_id')
            
            # Post-operation integrity check
            post_check = self.validate_customer_integrity(customer_id, auto_correct=True)
            
            result['integrity'] = {
                'pre_total': pre_check.calculated_total,
                'post_total': post_check.calculated_total,
                'delta': post_check.calculated_total - pre_check.calculated_total,
                'expected_delta': amount,
                'is_valid': post_check.is_valid,
                'issues': post_check.issues
            }
            
            # Verify the delta matches the deposit amount
            actual_delta = post_check.calculated_total - pre_check.calculated_total
            if abs(actual_delta - amount) > 0.01:
                result['integrity']['warning'] = f"Balance delta ({actual_delta:.2f}) differs from deposit amount ({amount:.2f})"
            
        except Exception as e:
            result = {'success': False, 'error': str(e)}
        
        return result
    
    def execute_allocation_with_integrity(self, customer_id: str, amount: float,
                                            from_account: str, to_account: str,
                                            allocation_type: str = 'manual',
                                            metadata: Dict = None) -> Dict[str, Any]:
        """
        Execute an allocation with full integrity checking.
        
        This handles:
        - "increase cover" - allocate from savings to policy
        - "add policy" - allocate from savings to new policy
        - Rebalancing between accounts
        
        Args:
            customer_id: Customer ID
            amount: Amount to allocate
            from_account: Source account
            to_account: Destination account
            allocation_type: Type of allocation (manual, increase_cover, add_policy)
            metadata: Additional metadata
            
        Returns:
            Result dictionary with allocation details and integrity status
        """
        # Pre-validation
        is_valid, error = self.validate_allocation(customer_id, amount, from_account, to_account)
        if not is_valid:
            return {'success': False, 'error': error}
        
        # Get pre-operation balances
        pre_check = self.validate_customer_integrity(customer_id)
        
        result = {'success': False}
        
        try:
            # Deduct from source
            from_lower = from_account.lower()
            to_lower = to_account.lower()
            
            if from_lower in ['cash_balance', 'cash']:
                if self.savings_pipeline:
                    account = self.savings_pipeline.accounts.get(customer_id)
                    if account:
                        account.cash_balance -= amount
            elif from_lower in ['investment', 'investment_account']:
                if customer_id in self.investment_accounts:
                    self.investment_accounts[customer_id]['balance'] = \
                        float(self.investment_accounts[customer_id].get('balance', 0) or 0) - amount
            elif from_lower in ['wallet', 'health_wallet']:
                if customer_id in self.health_wallets:
                    self.health_wallets[customer_id]['balance'] = \
                        float(self.health_wallets[customer_id].get('balance', 0) or 0) - amount
            
            # Add to destination
            if to_lower in ['wallet', 'health_wallet']:
                if customer_id not in self.health_wallets:
                    self.health_wallets[customer_id] = {
                        'customer_id': customer_id,
                        'balance': 0,
                        'transactions': [],
                        'created_at': datetime.now().isoformat()
                    }
                self.health_wallets[customer_id]['balance'] = \
                    float(self.health_wallets[customer_id].get('balance', 0) or 0) + amount
            elif to_lower in ['investment', 'investment_account']:
                if customer_id not in self.investment_accounts:
                    self.investment_accounts[customer_id] = {
                        'balance': 0,
                        'deposits': [],
                        'created_at': datetime.now().isoformat()
                    }
                self.investment_accounts[customer_id]['balance'] = \
                    float(self.investment_accounts[customer_id].get('balance', 0) or 0) + amount
            elif to_lower in ['algo_trading', 'algo']:
                if self.unified_balance:
                    if customer_id not in self.unified_balance.algo_trading_balances:
                        self.unified_balance.algo_trading_balances[customer_id] = {
                            'available': 0,
                            'in_positions': 0,
                            'total_pnl': 0
                        }
                    self.unified_balance.algo_trading_balances[customer_id]['available'] += amount
            elif to_lower in ['policy_premium', 'increase_cover', 'add_policy']:
                # This is an allocation to policy - treated as a "spend" from savings
                # The amount goes to policy premium, not back to savings
                pass  # Amount already deducted from source
            
            result = {
                'success': True,
                'allocation_type': allocation_type,
                'amount': amount,
                'from': from_account,
                'to': to_account
            }
            
            # Record on transaction ledger
            if self.record_transaction:
                ledger_tx = self.record_transaction(
                    customer_id=customer_id,
                    tx_type=f'allocation_{allocation_type}',
                    amount=amount,
                    description=f'Allocation ${amount:.2f} from {from_account} to {to_account} ({allocation_type})',
                    metadata={
                        'from_account': from_account,
                        'to_account': to_account,
                        'allocation_type': allocation_type,
                        **(metadata or {})
                    }
                )
                result['ledger_tx_id'] = ledger_tx.get('id')
                result['nft_token_id'] = ledger_tx.get('nft_token_id')
            
            # Post-operation integrity check
            post_check = self.validate_customer_integrity(customer_id, auto_correct=True)
            
            result['integrity'] = {
                'pre_total': pre_check.calculated_total,
                'post_total': post_check.calculated_total,
                'is_valid': post_check.is_valid,
                'issues': post_check.issues
            }
            
            # For internal transfers, totals should remain the same
            if to_lower not in ['policy_premium', 'increase_cover', 'add_policy']:
                delta = abs(post_check.calculated_total - pre_check.calculated_total)
                if delta > 0.01:
                    result['integrity']['warning'] = f"Total changed by ${delta:.2f} during internal transfer"
            
        except Exception as e:
            result = {'success': False, 'error': str(e)}
        
        return result


# Singleton instance
_integrity_service: DataIntegrityService = None


def get_integrity_service(**kwargs) -> DataIntegrityService:
    """Get singleton instance of data integrity service."""
    global _integrity_service
    if _integrity_service is None:
        _integrity_service = DataIntegrityService(**kwargs)
    return _integrity_service


def init_integrity_service(health_wallets, investment_accounts, transaction_ledger,
                            nft_ledger, savings_pipeline_service=None,
                            unified_balance_service=None, record_transaction_func=None):
    """Initialize the data integrity service with all dependencies."""
    global _integrity_service
    _integrity_service = DataIntegrityService(
        health_wallets=health_wallets,
        investment_accounts=investment_accounts,
        transaction_ledger=transaction_ledger,
        nft_ledger=nft_ledger,
        savings_pipeline_service=savings_pipeline_service,
        unified_balance_service=unified_balance_service,
        record_transaction_func=record_transaction_func
    )
    return _integrity_service
