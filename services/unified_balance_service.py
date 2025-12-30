"""
PHINS Unified Balance Service
==============================
Central service for managing customer balances across all systems:
- Health Wallet
- Investment Account (Savings Portfolio)
- Algo Trading Account
- Policy Premiums

All transactions are documented on:
- Transaction Ledger (master record)
- NFT Ledger (blockchain-ready immutable record)

This service provides:
- Unified balance view across all accounts
- Fund transfers between accounts
- Transaction recording on all ledgers
- Balance validation and reconciliation
"""

from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import random
import hashlib


class UnifiedBalanceService:
    """
    Central balance management connecting all PHINS financial systems.
    """
    
    def __init__(self, 
                 health_wallets: Dict,
                 investment_accounts: Dict,
                 transaction_ledger: Dict,
                 nft_ledger: Dict,
                 record_transaction_func,
                 generate_nft_token_func,
                 portfolio_service=None,
                 algo_trading_service=None):
        """
        Initialize with references to all data stores and services.
        
        Args:
            health_wallets: HEALTH_WALLETS dictionary from server
            investment_accounts: INVESTMENT_ACCOUNTS dictionary from server
            transaction_ledger: TRANSACTION_LEDGER dictionary from server
            nft_ledger: NFT_LEDGER dictionary from server
            record_transaction_func: Function to record transactions
            generate_nft_token_func: Function to generate NFT tokens
            portfolio_service: Investment portfolio service instance
            algo_trading_service: Algo trading service instance
        """
        self.health_wallets = health_wallets
        self.investment_accounts = investment_accounts
        self.transaction_ledger = transaction_ledger
        self.nft_ledger = nft_ledger
        self.record_transaction = record_transaction_func
        self.generate_nft_token = generate_nft_token_func
        self.portfolio_service = portfolio_service
        self.algo_trading_service = algo_trading_service
        
        # Algo trading balances (dedicated trading capital)
        self.algo_trading_balances: Dict[str, Dict[str, Any]] = {}
    
    def get_unified_balance(self, customer_id: str) -> Dict[str, Any]:
        """
        Get complete balance view across all systems for a customer.
        
        Returns:
            Dictionary with balances from all systems:
            - health_wallet: Health wallet balance and details
            - investment_account: Investment/savings balance
            - algo_trading: Algo trading dedicated balance
            - portfolio: Investment portfolio value
            - total_assets: Sum of all liquid assets
        """
        result = {
            'customer_id': customer_id,
            'timestamp': datetime.now().isoformat(),
            'balances': {},
            'total_assets': 0.0
        }
        
        # 1. Health Wallet Balance
        wallet = self.health_wallets.get(customer_id, {})
        wallet_balance = float(wallet.get('balance', 0))
        result['balances']['health_wallet'] = {
            'balance': wallet_balance,
            'monthly_deposit': wallet.get('monthly_deposit', 0),
            'available': wallet_balance,
            'transactions_count': len(wallet.get('transactions', []))
        }
        result['total_assets'] += wallet_balance
        
        # 2. Investment Account (Savings) Balance
        inv_account = self.investment_accounts.get(customer_id, {})
        inv_balance = float(inv_account.get('balance', 0))
        result['balances']['investment_account'] = {
            'total_balance': inv_balance,
            'index_balance': inv_account.get('index_balance', 0),
            'bonds_balance': inv_account.get('bonds_balance', 0),
            'crypto_balance': inv_account.get('crypto_balance', 0),
            'deposits_count': len(inv_account.get('deposits', []))
        }
        result['total_assets'] += inv_balance
        
        # 3. Algo Trading Balance
        algo_balance = self.algo_trading_balances.get(customer_id, {})
        algo_total = float(algo_balance.get('available', 0)) + float(algo_balance.get('in_positions', 0))
        result['balances']['algo_trading'] = {
            'available': algo_balance.get('available', 0),
            'in_positions': algo_balance.get('in_positions', 0),
            'total': algo_total,
            'active_bots': algo_balance.get('active_bots', 0),
            'total_pnl': algo_balance.get('total_pnl', 0)
        }
        result['total_assets'] += algo_total
        
        # 4. Portfolio Value (from portfolio service)
        if self.portfolio_service:
            try:
                accounts = self.portfolio_service.get_customer_accounts(customer_id)
                if accounts:
                    portfolio_value = 0
                    for acc in accounts:
                        summary = self.portfolio_service.get_portfolio_summary(acc.account_id)
                        portfolio_value += summary.get('total_value', 0)
                    result['balances']['portfolio'] = {
                        'total_value': portfolio_value,
                        'accounts_count': len(accounts)
                    }
                    # Note: Portfolio value may overlap with investment_account
            except Exception:
                result['balances']['portfolio'] = {'total_value': 0, 'accounts_count': 0}
        
        # Summary
        result['summary'] = {
            'total_liquid_assets': result['total_assets'],
            'health_wallet_pct': (wallet_balance / result['total_assets'] * 100) if result['total_assets'] > 0 else 0,
            'investment_pct': (inv_balance / result['total_assets'] * 100) if result['total_assets'] > 0 else 0,
            'algo_trading_pct': (algo_total / result['total_assets'] * 100) if result['total_assets'] > 0 else 0
        }
        
        return result
    
    def transfer_to_algo_trading(self, customer_id: str, amount: float, 
                                   source: str = 'investment_account',
                                   bot_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Transfer funds to algo trading account from another account.
        
        Args:
            customer_id: Customer ID
            amount: Amount to transfer
            source: Source account ('health_wallet', 'investment_account')
            bot_id: Optional bot to allocate funds to
            
        Returns:
            Transfer result with transaction details and NFT token
        """
        # Validate source and get balance
        if source == 'health_wallet':
            wallet = self.health_wallets.get(customer_id)
            if not wallet:
                return {'success': False, 'error': 'Health wallet not found'}
            if wallet.get('balance', 0) < amount:
                return {'success': False, 'error': 'Insufficient health wallet balance'}
            source_balance = wallet['balance']
        elif source == 'investment_account':
            inv_acc = self.investment_accounts.get(customer_id)
            if not inv_acc:
                return {'success': False, 'error': 'Investment account not found'}
            if inv_acc.get('balance', 0) < amount:
                return {'success': False, 'error': 'Insufficient investment balance'}
            source_balance = inv_acc['balance']
        else:
            return {'success': False, 'error': f'Invalid source: {source}'}
        
        # Initialize algo trading balance if needed
        if customer_id not in self.algo_trading_balances:
            self.algo_trading_balances[customer_id] = {
                'available': 0.0,
                'in_positions': 0.0,
                'total_pnl': 0.0,
                'active_bots': 0,
                'transfers': [],
                'created_at': datetime.now().isoformat()
            }
        
        # Perform transfer
        transfer_id = f"TRF-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
        
        # Deduct from source
        if source == 'health_wallet':
            self.health_wallets[customer_id]['balance'] -= amount
            # Record wallet transaction
            self.health_wallets[customer_id].setdefault('transactions', []).append({
                'id': transfer_id,
                'type': 'transfer_out',
                'amount': -amount,
                'description': f'Transfer to Algo Trading',
                'timestamp': datetime.now().isoformat()
            })
        else:  # investment_account
            self.investment_accounts[customer_id]['balance'] -= amount
            # Proportionally reduce balances
            total = self.investment_accounts[customer_id]['balance'] + amount
            if total > 0:
                ratio = self.investment_accounts[customer_id]['balance'] / total
                for key in ['index_balance', 'bonds_balance', 'crypto_balance']:
                    if key in self.investment_accounts[customer_id]:
                        self.investment_accounts[customer_id][key] *= ratio
        
        # Add to algo trading
        self.algo_trading_balances[customer_id]['available'] += amount
        self.algo_trading_balances[customer_id]['transfers'].append({
            'id': transfer_id,
            'type': 'deposit',
            'source': source,
            'amount': amount,
            'bot_id': bot_id,
            'timestamp': datetime.now().isoformat()
        })
        
        # Record in transaction ledger
        tx = self.record_transaction(
            customer_id=customer_id,
            tx_type='algo_trading_deposit',
            amount=amount,
            description=f'Transfer ${amount:.2f} from {source} to Algo Trading',
            metadata={
                'transfer_id': transfer_id,
                'source': source,
                'source_balance_before': source_balance,
                'source_balance_after': source_balance - amount,
                'algo_balance_after': self.algo_trading_balances[customer_id]['available'],
                'bot_id': bot_id
            }
        )
        
        return {
            'success': True,
            'transfer_id': transfer_id,
            'amount': amount,
            'source': source,
            'new_algo_balance': self.algo_trading_balances[customer_id]['available'],
            'new_source_balance': source_balance - amount,
            'transaction': tx,
            'nft_token_id': tx.get('nft_token_id')
        }
    
    def withdraw_from_algo_trading(self, customer_id: str, amount: float,
                                     destination: str = 'investment_account') -> Dict[str, Any]:
        """
        Withdraw funds from algo trading to another account.
        
        Args:
            customer_id: Customer ID
            amount: Amount to withdraw
            destination: Destination account ('health_wallet', 'investment_account')
            
        Returns:
            Withdrawal result with transaction details
        """
        algo_balance = self.algo_trading_balances.get(customer_id)
        if not algo_balance:
            return {'success': False, 'error': 'Algo trading account not found'}
        
        if algo_balance.get('available', 0) < amount:
            return {'success': False, 'error': 'Insufficient available balance (funds may be in positions)'}
        
        # Validate destination
        if destination == 'health_wallet':
            if customer_id not in self.health_wallets:
                self.health_wallets[customer_id] = {'balance': 0, 'transactions': []}
        elif destination == 'investment_account':
            if customer_id not in self.investment_accounts:
                self.investment_accounts[customer_id] = {'balance': 0, 'deposits': []}
        else:
            return {'success': False, 'error': f'Invalid destination: {destination}'}
        
        # Perform withdrawal
        withdrawal_id = f"WDR-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
        
        # Deduct from algo trading
        self.algo_trading_balances[customer_id]['available'] -= amount
        self.algo_trading_balances[customer_id]['transfers'].append({
            'id': withdrawal_id,
            'type': 'withdrawal',
            'destination': destination,
            'amount': -amount,
            'timestamp': datetime.now().isoformat()
        })
        
        # Add to destination
        if destination == 'health_wallet':
            self.health_wallets[customer_id]['balance'] += amount
            self.health_wallets[customer_id].setdefault('transactions', []).append({
                'id': withdrawal_id,
                'type': 'transfer_in',
                'amount': amount,
                'description': 'Transfer from Algo Trading',
                'timestamp': datetime.now().isoformat()
            })
            new_dest_balance = self.health_wallets[customer_id]['balance']
        else:
            self.investment_accounts[customer_id]['balance'] += amount
            self.investment_accounts[customer_id].setdefault('deposits', []).append({
                'id': withdrawal_id,
                'type': 'algo_trading_withdrawal',
                'amount': amount,
                'timestamp': datetime.now().isoformat()
            })
            new_dest_balance = self.investment_accounts[customer_id]['balance']
        
        # Record transaction
        tx = self.record_transaction(
            customer_id=customer_id,
            tx_type='algo_trading_withdrawal',
            amount=amount,
            description=f'Withdraw ${amount:.2f} from Algo Trading to {destination}',
            metadata={
                'withdrawal_id': withdrawal_id,
                'destination': destination,
                'algo_balance_after': self.algo_trading_balances[customer_id]['available'],
                'dest_balance_after': new_dest_balance
            }
        )
        
        return {
            'success': True,
            'withdrawal_id': withdrawal_id,
            'amount': amount,
            'destination': destination,
            'new_algo_balance': self.algo_trading_balances[customer_id]['available'],
            'new_destination_balance': new_dest_balance,
            'transaction': tx,
            'nft_token_id': tx.get('nft_token_id')
        }
    
    def record_algo_trade(self, customer_id: str, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Record an algo trading trade on all ledgers.
        
        Args:
            customer_id: Customer ID
            order_data: Order details from algo trading service
            
        Returns:
            Transaction and NFT token details
        """
        order_id = order_data.get('order_id', f"ORD-{random.randint(10000, 99999)}")
        symbol = order_data.get('symbol', 'UNKNOWN')
        side = order_data.get('side', 'buy')
        quantity = order_data.get('quantity', 0)
        price = order_data.get('price', 0)
        total_value = quantity * price
        
        # Update algo trading balance
        if customer_id in self.algo_trading_balances:
            if side == 'buy':
                # Move from available to positions
                self.algo_trading_balances[customer_id]['available'] -= total_value
                self.algo_trading_balances[customer_id]['in_positions'] += total_value
            else:  # sell
                # Move from positions back to available (with P&L)
                pnl = order_data.get('pnl', 0)
                self.algo_trading_balances[customer_id]['in_positions'] -= total_value
                self.algo_trading_balances[customer_id]['available'] += total_value + pnl
                self.algo_trading_balances[customer_id]['total_pnl'] += pnl
        
        # Record transaction
        tx = self.record_transaction(
            customer_id=customer_id,
            tx_type=f'algo_trade_{side}',
            amount=total_value,
            description=f'{side.upper()} {quantity:.6f} {symbol} @ ${price:.2f}',
            metadata={
                'order_id': order_id,
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'price': price,
                'total_value': total_value,
                'strategy': order_data.get('strategy'),
                'bot_id': order_data.get('bot_id'),
                'signal_id': order_data.get('signal_id'),
                'stop_loss': order_data.get('stop_loss'),
                'take_profit': order_data.get('take_profit'),
                'pnl': order_data.get('pnl', 0)
            }
        )
        
        return {
            'success': True,
            'order_id': order_id,
            'transaction': tx,
            'nft_token_id': tx.get('nft_token_id')
        }
    
    def get_algo_trading_balance(self, customer_id: str) -> Dict[str, Any]:
        """Get algo trading balance for a customer."""
        balance = self.algo_trading_balances.get(customer_id, {
            'available': 0,
            'in_positions': 0,
            'total_pnl': 0,
            'active_bots': 0,
            'transfers': []
        })
        
        # Count active bots if algo service available
        if self.algo_trading_service:
            active_bots = sum(
                1 for bot in self.algo_trading_service.bots.values()
                if bot.account_id == customer_id and bot.is_active
            )
            balance['active_bots'] = active_bots
        
        return balance
    
    def get_all_transactions(self, customer_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get all transactions across all systems for a customer.
        
        Args:
            customer_id: Customer ID
            limit: Max transactions to return
            
        Returns:
            List of transactions sorted by timestamp (newest first)
        """
        transactions = []
        
        # Get from transaction ledger
        for tx in self.transaction_ledger.values():
            if tx.get('customer_id') == customer_id:
                transactions.append(tx)
        
        # Sort by timestamp descending
        transactions.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return transactions[:limit]
    
    def get_all_nft_tokens(self, customer_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get all NFT tokens for a customer across all systems.
        
        Args:
            customer_id: Customer ID
            limit: Max tokens to return
            
        Returns:
            List of NFT tokens sorted by creation time (newest first)
        """
        tokens = []
        
        for nft in self.nft_ledger.values():
            if nft.get('owner_id') == customer_id:
                tokens.append(nft)
        
        # Sort by created_at descending
        tokens.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return tokens[:limit]
    
    def reconcile_balances(self, customer_id: str) -> Dict[str, Any]:
        """
        Reconcile all balances for a customer against transaction ledger.
        
        Returns:
            Reconciliation report showing any discrepancies
        """
        # Calculate expected balances from transactions
        expected = {
            'health_wallet': 0,
            'investment_account': 0,
            'algo_trading': 0
        }
        
        for tx in self.transaction_ledger.values():
            if tx.get('customer_id') != customer_id:
                continue
            
            tx_type = tx.get('type', '')
            amount = float(tx.get('amount', 0))
            
            if tx_type == 'wallet_deposit':
                expected['health_wallet'] += amount
            elif tx_type == 'medical_purchase':
                expected['health_wallet'] -= amount
            elif tx_type in ['premium_payment', 'investment_deposit']:
                expected['investment_account'] += amount * 0.25  # savings portion
            elif tx_type == 'algo_trading_deposit':
                expected['algo_trading'] += amount
            elif tx_type == 'algo_trading_withdrawal':
                expected['algo_trading'] -= amount
            elif tx_type.startswith('algo_trade_'):
                pass  # Internal movement, no change to total
        
        # Get actual balances
        actual = {
            'health_wallet': self.health_wallets.get(customer_id, {}).get('balance', 0),
            'investment_account': self.investment_accounts.get(customer_id, {}).get('balance', 0),
            'algo_trading': self.algo_trading_balances.get(customer_id, {}).get('available', 0) +
                          self.algo_trading_balances.get(customer_id, {}).get('in_positions', 0)
        }
        
        # Calculate discrepancies
        discrepancies = {}
        for account, expected_bal in expected.items():
            actual_bal = actual.get(account, 0)
            if abs(expected_bal - actual_bal) > 0.01:
                discrepancies[account] = {
                    'expected': expected_bal,
                    'actual': actual_bal,
                    'difference': actual_bal - expected_bal
                }
        
        return {
            'customer_id': customer_id,
            'timestamp': datetime.now().isoformat(),
            'expected_balances': expected,
            'actual_balances': actual,
            'discrepancies': discrepancies,
            'is_reconciled': len(discrepancies) == 0
        }


# Singleton instance
_unified_balance_service: Optional[UnifiedBalanceService] = None


def get_unified_balance_service(**kwargs) -> UnifiedBalanceService:
    """Get singleton instance of unified balance service."""
    global _unified_balance_service
    if _unified_balance_service is None:
        _unified_balance_service = UnifiedBalanceService(**kwargs)
    return _unified_balance_service


def init_unified_balance_service(health_wallets, investment_accounts, transaction_ledger,
                                   nft_ledger, record_transaction_func, generate_nft_token_func,
                                   portfolio_service=None, algo_trading_service=None):
    """Initialize the unified balance service with all dependencies."""
    global _unified_balance_service
    _unified_balance_service = UnifiedBalanceService(
        health_wallets=health_wallets,
        investment_accounts=investment_accounts,
        transaction_ledger=transaction_ledger,
        nft_ledger=nft_ledger,
        record_transaction_func=record_transaction_func,
        generate_nft_token_func=generate_nft_token_func,
        portfolio_service=portfolio_service,
        algo_trading_service=algo_trading_service
    )
    return _unified_balance_service
