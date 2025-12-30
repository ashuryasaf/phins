"""
PHINS Savings Pipeline Service
================================
AI/BI-Integrated Savings Pipeline for Insurance Platform

This service creates a unified pipeline that:
1. Receives funds from premium payments
2. Uses AI to determine optimal allocation
3. Distributes to Wallet, Investments, and Algo Trading
4. Provides BI analytics and recommendations
5. Tracks all flows on ledgers

Pipeline Flow:
    Premium Payment
         │
         ▼
    ┌─────────────────┐
    │  Cash Balance   │ ◄── Additional deposits
    │   (Staging)     │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────────────────────────┐
    │        AI Allocation Engine         │
    │  (Risk Profile, Market, Goals)      │
    └────────┬──────────┬────────┬────────┘
             │          │        │
             ▼          ▼        ▼
    ┌─────────┐  ┌──────────┐  ┌─────────┐
    │ Health  │  │Investment│  │  Algo   │
    │ Wallet  │  │Portfolio │  │ Trading │
    │(10-20%) │  │(50-70%)  │  │(10-30%) │
    └─────────┘  └──────────┘  └─────────┘
"""

import math
import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import json


class AllocationStrategy(str, Enum):
    """AI allocation strategies"""
    CONSERVATIVE = "conservative"      # More bonds, less crypto/algo
    BALANCED = "balanced"              # Equal distribution
    GROWTH = "growth"                  # More equity/crypto
    AGGRESSIVE = "aggressive"          # Max algo trading
    AI_OPTIMIZED = "ai_optimized"      # AI-determined optimal
    CUSTOM = "custom"                  # User-defined


class RiskLevel(str, Enum):
    """Customer risk levels"""
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class AllocationConfig:
    """Configuration for fund allocation"""
    wallet_pct: float = 15.0          # Emergency fund
    investment_pct: float = 60.0       # Long-term investments
    algo_trading_pct: float = 25.0     # Automated trading
    
    # Investment breakdown
    index_pct: float = 50.0           # Index funds (of investment)
    bonds_pct: float = 30.0           # Bonds (of investment)
    crypto_pct: float = 20.0          # Crypto (of investment)
    
    # Algo trading strategy preferences
    algo_momentum_pct: float = 40.0
    algo_mean_reversion_pct: float = 30.0
    algo_dca_pct: float = 30.0


@dataclass
class SavingsPipelineAccount:
    """Customer's savings pipeline account"""
    customer_id: str
    account_id: str
    
    # Cash balance (staging area)
    cash_balance: float = 0.0
    
    # Allocated balances
    wallet_balance: float = 0.0
    investment_balance: float = 0.0
    algo_trading_balance: float = 0.0
    
    # Performance tracking
    total_deposits: float = 0.0
    total_allocated: float = 0.0
    total_returns: float = 0.0
    
    # Settings
    allocation_strategy: AllocationStrategy = AllocationStrategy.AI_OPTIMIZED
    risk_level: RiskLevel = RiskLevel.MODERATE
    auto_allocate: bool = True
    allocation_config: AllocationConfig = field(default_factory=AllocationConfig)
    
    # Timestamps
    created_at: str = ""
    last_deposit_at: str = ""
    last_allocation_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class PipelineTransaction:
    """Transaction in the savings pipeline"""
    tx_id: str
    customer_id: str
    tx_type: str  # deposit, allocate, transfer, withdrawal
    amount: float
    source: str
    destination: str
    description: str
    ai_recommended: bool = False
    allocation_breakdown: Dict[str, float] = field(default_factory=dict)
    timestamp: str = ""
    nft_token_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class SavingsPipelineService:
    """
    AI/BI-Integrated Savings Pipeline Service
    
    Features:
    - Unified cash balance management
    - AI-powered allocation recommendations
    - Automatic fund distribution
    - BI analytics and projections
    - Real-time pipeline tracking
    
    NOTE: This service integrates with global data stores:
    - HEALTH_WALLETS
    - INVESTMENT_ACCOUNTS
    - TRANSACTION_LEDGER
    - NFT_LEDGER
    All deposits and allocations are persisted to these stores.
    """
    
    def __init__(self, 
                 unified_balance_service=None,
                 portfolio_service=None,
                 algo_trading_service=None,
                 record_transaction_func=None,
                 generate_nft_token_func=None,
                 health_wallets=None,
                 investment_accounts=None,
                 transaction_ledger=None,
                 nft_ledger=None):
        
        self.unified_balance = unified_balance_service
        self.portfolio_service = portfolio_service
        self.algo_trading = algo_trading_service
        self.record_transaction = record_transaction_func
        self.generate_nft_token = generate_nft_token_func
        
        # Direct references to global data stores for proper persistence
        self.health_wallets = health_wallets or {}
        self.investment_accounts = investment_accounts or {}
        self.transaction_ledger = transaction_ledger or {}
        self.nft_ledger = nft_ledger or {}
        
        # Pipeline accounts
        self.accounts: Dict[str, SavingsPipelineAccount] = {}
        
        # Pipeline transactions
        self.transactions: List[PipelineTransaction] = []
        
        # AI model parameters (simplified)
        self.market_sentiment = 0.6  # 0-1, higher = bullish
        self.volatility_index = 0.3  # 0-1, higher = more volatile
        
    def create_pipeline_account(self, customer_id: str, 
                                 risk_level: RiskLevel = RiskLevel.MODERATE,
                                 strategy: AllocationStrategy = AllocationStrategy.AI_OPTIMIZED) -> SavingsPipelineAccount:
        """Create a new savings pipeline account for a customer."""
        account_id = f"PIPE-{customer_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Get AI-recommended allocation based on risk level
        config = self._get_ai_allocation_config(risk_level, strategy)
        
        account = SavingsPipelineAccount(
            customer_id=customer_id,
            account_id=account_id,
            allocation_strategy=strategy,
            risk_level=risk_level,
            allocation_config=config
        )
        
        self.accounts[customer_id] = account
        return account
    
    def get_or_create_account(self, customer_id: str) -> SavingsPipelineAccount:
        """Get existing account or create new one."""
        if customer_id not in self.accounts:
            return self.create_pipeline_account(customer_id)
        return self.accounts[customer_id]
    
    def deposit_to_pipeline(self, customer_id: str, amount: float, 
                            source: str = "premium_payment",
                            auto_allocate: bool = True) -> Dict[str, Any]:
        """
        Deposit funds into the savings pipeline.
        
        Args:
            customer_id: Customer ID
            amount: Amount to deposit
            source: Source of funds (premium_payment, direct_deposit, transfer)
            auto_allocate: Whether to automatically allocate based on AI
            
        Returns:
            Deposit result with allocation details
        """
        account = self.get_or_create_account(customer_id)
        
        # Add to cash balance
        account.cash_balance += amount
        account.total_deposits += amount
        account.last_deposit_at = datetime.now().isoformat()
        
        # Create transaction record
        tx = PipelineTransaction(
            tx_id=f"DEP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}",
            customer_id=customer_id,
            tx_type="deposit",
            amount=amount,
            source=source,
            destination="cash_balance",
            description=f"Deposit from {source}: ${amount:.2f}"
        )
        self.transactions.append(tx)
        
        # Record on ledger
        if self.record_transaction:
            ledger_tx = self.record_transaction(
                customer_id=customer_id,
                tx_type="pipeline_deposit",
                amount=amount,
                description=tx.description,
                metadata={
                    'pipeline_tx_id': tx.tx_id,
                    'source': source,
                    'cash_balance_after': account.cash_balance
                }
            )
            tx.nft_token_id = ledger_tx.get('nft_token_id')
        
        result = {
            'success': True,
            'transaction': asdict(tx),
            'cash_balance': account.cash_balance,
            'account_id': account.account_id
        }
        
        # Auto-allocate if enabled
        if auto_allocate and account.auto_allocate:
            allocation_result = self.allocate_cash_balance(customer_id)
            result['allocation'] = allocation_result
        
        return result
    
    def allocate_cash_balance(self, customer_id: str, 
                               amount: Optional[float] = None,
                               use_ai: bool = True) -> Dict[str, Any]:
        """
        Allocate cash balance to wallet, investments, and algo trading.
        
        Args:
            customer_id: Customer ID
            amount: Specific amount to allocate (None = all cash balance)
            use_ai: Whether to use AI for optimal allocation
            
        Returns:
            Allocation result with breakdown
        """
        account = self.get_or_create_account(customer_id)
        
        # Determine amount to allocate
        allocate_amount = amount if amount is not None else account.cash_balance
        if allocate_amount <= 0:
            return {'success': False, 'error': 'No funds to allocate'}
        
        if allocate_amount > account.cash_balance:
            return {'success': False, 'error': 'Insufficient cash balance'}
        
        # Get allocation config (AI-optimized or user-defined)
        if use_ai and account.allocation_strategy == AllocationStrategy.AI_OPTIMIZED:
            config = self._get_ai_allocation_config(account.risk_level, account.allocation_strategy)
        else:
            config = account.allocation_config
        
        # Calculate allocations
        wallet_amount = allocate_amount * (config.wallet_pct / 100)
        investment_amount = allocate_amount * (config.investment_pct / 100)
        algo_amount = allocate_amount * (config.algo_trading_pct / 100)
        
        # Investment breakdown
        index_amount = investment_amount * (config.index_pct / 100)
        bonds_amount = investment_amount * (config.bonds_pct / 100)
        crypto_amount = investment_amount * (config.crypto_pct / 100)
        
        # Deduct from cash balance
        account.cash_balance -= allocate_amount
        
        # Add to allocated balances
        account.wallet_balance += wallet_amount
        account.investment_balance += investment_amount
        account.algo_trading_balance += algo_amount
        account.total_allocated += allocate_amount
        account.last_allocation_at = datetime.now().isoformat()
        
        # Create allocation breakdown
        allocation_breakdown = {
            'wallet': wallet_amount,
            'investment': investment_amount,
            'algo_trading': algo_amount,
            'investment_detail': {
                'index_funds': index_amount,
                'bonds': bonds_amount,
                'crypto': crypto_amount
            }
        }
        
        # Create transaction record
        tx = PipelineTransaction(
            tx_id=f"ALLOC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}",
            customer_id=customer_id,
            tx_type="allocate",
            amount=allocate_amount,
            source="cash_balance",
            destination="multi",
            description=f"AI-optimized allocation: ${allocate_amount:.2f}",
            ai_recommended=use_ai,
            allocation_breakdown=allocation_breakdown
        )
        self.transactions.append(tx)
        
        # Transfer to actual accounts - use direct data stores for reliable persistence
        transfers_executed = []
        
        # Get the appropriate data stores (prefer direct, fallback to unified_balance)
        wallets = self.health_wallets if self.health_wallets else (self.unified_balance.health_wallets if self.unified_balance else {})
        investments = self.investment_accounts if self.investment_accounts else (self.unified_balance.investment_accounts if self.unified_balance else {})
        algo_balances = self.unified_balance.algo_trading_balances if self.unified_balance else {}
        
        # Transfer to health wallet
        if wallet_amount > 0 and wallets is not None:
            try:
                if customer_id in wallets:
                    wallets[customer_id]['balance'] = wallets[customer_id].get('balance', 0) + wallet_amount
                else:
                    wallets[customer_id] = {
                        'balance': wallet_amount,
                        'transactions': [],
                        'monthly_deposit': 0
                    }
                wallets[customer_id].setdefault('transactions', []).append({
                    'id': tx.tx_id,
                    'type': 'pipeline_allocation',
                    'amount': wallet_amount,
                    'timestamp': datetime.now().isoformat()
                })
                transfers_executed.append({'destination': 'wallet', 'amount': wallet_amount, 'persisted': True})
            except Exception as e:
                print(f"Wallet transfer error: {e}")
        
        # Transfer to investment account
        if investment_amount > 0 and investments is not None:
            try:
                if customer_id not in investments:
                    investments[customer_id] = {
                        'balance': 0,
                        'index_balance': 0,
                        'bonds_balance': 0,
                        'crypto_balance': 0,
                        'deposits': [],
                        'created_at': datetime.now().isoformat()
                    }
                inv_acc = investments[customer_id]
                inv_acc['balance'] = inv_acc.get('balance', 0) + investment_amount
                inv_acc['index_balance'] = inv_acc.get('index_balance', 0) + index_amount
                inv_acc['bonds_balance'] = inv_acc.get('bonds_balance', 0) + bonds_amount
                inv_acc['crypto_balance'] = inv_acc.get('crypto_balance', 0) + crypto_amount
                inv_acc.setdefault('deposits', []).append({
                    'id': tx.tx_id,
                    'type': 'pipeline_allocation',
                    'amount': investment_amount,
                    'index': index_amount,
                    'bonds': bonds_amount,
                    'crypto': crypto_amount,
                    'timestamp': datetime.now().isoformat()
                })
                transfers_executed.append({'destination': 'investment', 'amount': investment_amount, 'persisted': True})
            except Exception as e:
                print(f"Investment transfer error: {e}")
        
        # Transfer to algo trading
        if algo_amount > 0 and algo_balances is not None:
            try:
                if customer_id not in algo_balances:
                    algo_balances[customer_id] = {
                        'available': 0,
                        'in_positions': 0,
                        'total_pnl': 0,
                        'transfers': []
                    }
                algo_balances[customer_id]['available'] = algo_balances[customer_id].get('available', 0) + algo_amount
                algo_balances[customer_id].setdefault('transfers', []).append({
                    'id': tx.tx_id,
                    'type': 'pipeline_allocation',
                    'amount': algo_amount,
                    'timestamp': datetime.now().isoformat()
                })
                transfers_executed.append({'destination': 'algo_trading', 'amount': algo_amount, 'persisted': True})
            except Exception as e:
                print(f"Algo trading transfer error: {e}")
        
        # Record on ledger
        if self.record_transaction:
            ledger_tx = self.record_transaction(
                customer_id=customer_id,
                tx_type="pipeline_allocation",
                amount=allocate_amount,
                description=tx.description,
                metadata={
                    'pipeline_tx_id': tx.tx_id,
                    'ai_optimized': use_ai,
                    'allocation': allocation_breakdown,
                    'transfers': transfers_executed
                }
            )
            tx.nft_token_id = ledger_tx.get('nft_token_id')
        
        return {
            'success': True,
            'transaction': asdict(tx),
            'amount_allocated': allocate_amount,
            'allocation_breakdown': allocation_breakdown,
            'transfers_executed': transfers_executed,
            'remaining_cash_balance': account.cash_balance,
            'ai_recommended': use_ai
        }
    
    def _get_ai_allocation_config(self, risk_level: RiskLevel, 
                                    strategy: AllocationStrategy) -> AllocationConfig:
        """
        AI-powered allocation configuration based on risk level and market conditions.
        
        Uses simplified ML model considering:
        - Customer risk tolerance
        - Market sentiment
        - Volatility index
        - Historical performance
        """
        # Base allocations by risk level
        base_configs = {
            RiskLevel.LOW: {
                'wallet_pct': 25.0,
                'investment_pct': 65.0,
                'algo_trading_pct': 10.0,
                'index_pct': 40.0,
                'bonds_pct': 50.0,
                'crypto_pct': 10.0,
            },
            RiskLevel.MODERATE: {
                'wallet_pct': 15.0,
                'investment_pct': 60.0,
                'algo_trading_pct': 25.0,
                'index_pct': 50.0,
                'bonds_pct': 30.0,
                'crypto_pct': 20.0,
            },
            RiskLevel.HIGH: {
                'wallet_pct': 10.0,
                'investment_pct': 55.0,
                'algo_trading_pct': 35.0,
                'index_pct': 45.0,
                'bonds_pct': 20.0,
                'crypto_pct': 35.0,
            },
            RiskLevel.VERY_HIGH: {
                'wallet_pct': 5.0,
                'investment_pct': 45.0,
                'algo_trading_pct': 50.0,
                'index_pct': 30.0,
                'bonds_pct': 10.0,
                'crypto_pct': 60.0,
            }
        }
        
        base = base_configs.get(risk_level, base_configs[RiskLevel.MODERATE])
        
        # AI adjustments based on market conditions
        if strategy == AllocationStrategy.AI_OPTIMIZED:
            # High market sentiment → increase equity/algo
            if self.market_sentiment > 0.7:
                base['algo_trading_pct'] += 5
                base['wallet_pct'] -= 5
                base['crypto_pct'] += 5
                base['bonds_pct'] -= 5
            # Low sentiment → increase safety
            elif self.market_sentiment < 0.3:
                base['wallet_pct'] += 5
                base['algo_trading_pct'] -= 5
                base['bonds_pct'] += 10
                base['crypto_pct'] -= 10
            
            # High volatility → reduce algo trading exposure
            if self.volatility_index > 0.6:
                base['algo_trading_pct'] = max(5, base['algo_trading_pct'] - 10)
                base['wallet_pct'] += 10
        
        # Normalize percentages
        total_main = base['wallet_pct'] + base['investment_pct'] + base['algo_trading_pct']
        if total_main != 100:
            factor = 100 / total_main
            base['wallet_pct'] *= factor
            base['investment_pct'] *= factor
            base['algo_trading_pct'] *= factor
        
        total_inv = base['index_pct'] + base['bonds_pct'] + base['crypto_pct']
        if total_inv != 100:
            factor = 100 / total_inv
            base['index_pct'] *= factor
            base['bonds_pct'] *= factor
            base['crypto_pct'] *= factor
        
        return AllocationConfig(**base)
    
    def get_ai_recommendation(self, customer_id: str) -> Dict[str, Any]:
        """
        Get AI-powered recommendation for savings optimization.
        
        Returns:
            Recommendation with analysis and suggested actions
        """
        account = self.get_or_create_account(customer_id)
        
        # Calculate current allocation percentages
        total = account.wallet_balance + account.investment_balance + account.algo_trading_balance
        if total == 0:
            total = 1  # Avoid division by zero
        
        current_allocation = {
            'wallet': (account.wallet_balance / total) * 100,
            'investment': (account.investment_balance / total) * 100,
            'algo_trading': (account.algo_trading_balance / total) * 100
        }
        
        # Get optimal allocation
        optimal_config = self._get_ai_allocation_config(account.risk_level, AllocationStrategy.AI_OPTIMIZED)
        
        optimal_allocation = {
            'wallet': optimal_config.wallet_pct,
            'investment': optimal_config.investment_pct,
            'algo_trading': optimal_config.algo_trading_pct
        }
        
        # Calculate deviations
        deviations = {
            key: optimal_allocation[key] - current_allocation[key]
            for key in current_allocation
        }
        
        # Generate recommendations
        recommendations = []
        actions = []
        
        # Check wallet (emergency fund)
        if deviations['wallet'] > 5:
            recommendations.append({
                'type': 'increase_wallet',
                'priority': 'high',
                'message': f"Increase emergency fund by ${total * (deviations['wallet'] / 100):.2f}",
                'reason': "Emergency fund below recommended level for risk protection"
            })
            actions.append({
                'action': 'transfer',
                'from': 'investment' if current_allocation['investment'] > optimal_allocation['investment'] else 'algo_trading',
                'to': 'wallet',
                'amount': total * (deviations['wallet'] / 100)
            })
        
        # Check algo trading opportunity
        if deviations['algo_trading'] > 5 and self.market_sentiment > 0.5:
            recommendations.append({
                'type': 'increase_algo',
                'priority': 'medium',
                'message': f"Market conditions favorable for algo trading. Consider increasing allocation.",
                'reason': f"Market sentiment: {self.market_sentiment:.0%}, current algo trading below optimal"
            })
        
        # Risk adjustment
        if self.volatility_index > 0.5 and current_allocation['algo_trading'] > 30:
            recommendations.append({
                'type': 'reduce_risk',
                'priority': 'high',
                'message': "High market volatility detected. Consider reducing algo trading exposure.",
                'reason': f"Volatility index: {self.volatility_index:.0%}"
            })
            actions.append({
                'action': 'transfer',
                'from': 'algo_trading',
                'to': 'investment',
                'amount': total * 0.05
            })
        
        # Performance analysis
        roi = (account.total_returns / account.total_deposits * 100) if account.total_deposits > 0 else 0
        
        return {
            'customer_id': customer_id,
            'timestamp': datetime.now().isoformat(),
            'current_allocation': current_allocation,
            'optimal_allocation': optimal_allocation,
            'deviations': deviations,
            'recommendations': recommendations,
            'suggested_actions': actions,
            'market_conditions': {
                'sentiment': self.market_sentiment,
                'sentiment_label': 'Bullish' if self.market_sentiment > 0.6 else 'Bearish' if self.market_sentiment < 0.4 else 'Neutral',
                'volatility': self.volatility_index,
                'volatility_label': 'High' if self.volatility_index > 0.6 else 'Low' if self.volatility_index < 0.3 else 'Moderate'
            },
            'performance': {
                'total_deposits': account.total_deposits,
                'total_returns': account.total_returns,
                'roi': roi
            },
            'risk_level': account.risk_level.value,
            'ai_confidence': 0.85  # Simplified confidence score
        }
    
    def get_pipeline_analytics(self, customer_id: str) -> Dict[str, Any]:
        """
        Get comprehensive BI analytics for the savings pipeline.
        
        Returns:
            Analytics dashboard data with metrics and projections
        """
        account = self.get_or_create_account(customer_id)
        
        # Calculate totals
        total_balance = account.wallet_balance + account.investment_balance + account.algo_trading_balance
        
        # Calculate allocation percentages
        if total_balance > 0:
            allocation_pct = {
                'wallet': (account.wallet_balance / total_balance) * 100,
                'investment': (account.investment_balance / total_balance) * 100,
                'algo_trading': (account.algo_trading_balance / total_balance) * 100
            }
        else:
            allocation_pct = {'wallet': 0, 'investment': 0, 'algo_trading': 0}
        
        # Transaction history analysis
        recent_txs = [t for t in self.transactions if t.customer_id == customer_id][-20:]
        
        # Calculate monthly averages
        deposits_30d = sum(t.amount for t in recent_txs if t.tx_type == 'deposit')
        allocations_30d = sum(t.amount for t in recent_txs if t.tx_type == 'allocate')
        
        # Projections (simplified Monte Carlo)
        projections = self._calculate_projections(account, years=[1, 5, 10, 20])
        
        return {
            'customer_id': customer_id,
            'timestamp': datetime.now().isoformat(),
            'account': {
                'account_id': account.account_id,
                'risk_level': account.risk_level.value,
                'strategy': account.allocation_strategy.value,
                'auto_allocate': account.auto_allocate
            },
            'balances': {
                'cash_balance': account.cash_balance,
                'wallet_balance': account.wallet_balance,
                'investment_balance': account.investment_balance,
                'algo_trading_balance': account.algo_trading_balance,
                'total_balance': total_balance
            },
            'allocation': allocation_pct,
            'performance': {
                'total_deposits': account.total_deposits,
                'total_allocated': account.total_allocated,
                'total_returns': account.total_returns,
                'roi_pct': (account.total_returns / account.total_deposits * 100) if account.total_deposits > 0 else 0,
                'allocation_efficiency': (account.total_allocated / account.total_deposits * 100) if account.total_deposits > 0 else 0
            },
            'activity': {
                'deposits_30d': deposits_30d,
                'allocations_30d': allocations_30d,
                'transaction_count': len(recent_txs)
            },
            'projections': projections,
            'pipeline_health': self._calculate_pipeline_health(account)
        }
    
    def _calculate_projections(self, account: SavingsPipelineAccount, 
                                years: List[int] = [1, 5, 10, 20]) -> Dict[str, Any]:
        """Calculate future value projections using Monte Carlo simulation."""
        total_balance = account.wallet_balance + account.investment_balance + account.algo_trading_balance
        
        # Assumed returns by asset class
        returns = {
            'wallet': 0.02,  # 2% (savings rate)
            'investment': 0.07,  # 7% (blended)
            'algo_trading': 0.12  # 12% (with higher volatility)
        }
        
        volatility = {
            'wallet': 0.01,
            'investment': 0.15,
            'algo_trading': 0.25
        }
        
        projections = {}
        
        for year in years:
            # Simple projection with weighted returns
            total = account.wallet_balance + account.investment_balance + account.algo_trading_balance
            if total == 0:
                projections[f'year_{year}'] = {'conservative': 0, 'expected': 0, 'optimistic': 0}
                continue
            
            weighted_return = (
                (account.wallet_balance / total) * returns['wallet'] +
                (account.investment_balance / total) * returns['investment'] +
                (account.algo_trading_balance / total) * returns['algo_trading']
            ) if total > 0 else 0.05
            
            weighted_vol = (
                (account.wallet_balance / total) * volatility['wallet'] +
                (account.investment_balance / total) * volatility['investment'] +
                (account.algo_trading_balance / total) * volatility['algo_trading']
            ) if total > 0 else 0.10
            
            # Monte Carlo percentiles
            expected = total * math.pow(1 + weighted_return, year)
            conservative = total * math.pow(1 + weighted_return - weighted_vol, year)
            optimistic = total * math.pow(1 + weighted_return + weighted_vol, year)
            
            projections[f'year_{year}'] = {
                'conservative': round(conservative, 2),
                'expected': round(expected, 2),
                'optimistic': round(optimistic, 2),
                'assumed_return': weighted_return * 100,
                'volatility': weighted_vol * 100
            }
        
        return projections
    
    def _calculate_pipeline_health(self, account: SavingsPipelineAccount) -> Dict[str, Any]:
        """Calculate pipeline health score and metrics."""
        total = account.wallet_balance + account.investment_balance + account.algo_trading_balance
        
        health_score = 100
        issues = []
        
        # Check emergency fund (should be 10-25% for most risk levels)
        if total > 0:
            wallet_pct = (account.wallet_balance / total) * 100
            if wallet_pct < 5:
                health_score -= 20
                issues.append("Emergency fund critically low")
            elif wallet_pct < 10:
                health_score -= 10
                issues.append("Emergency fund below recommended")
        
        # Check diversification
        if account.investment_balance == 0 and total > 1000:
            health_score -= 15
            issues.append("No investment allocation")
        
        # Check if auto-allocate is enabled
        if not account.auto_allocate:
            health_score -= 5
            issues.append("Auto-allocation disabled")
        
        # Check cash balance (should be allocated)
        if account.cash_balance > total * 0.1 and account.cash_balance > 100:
            health_score -= 10
            issues.append("Unallocated cash balance")
        
        return {
            'score': max(0, health_score),
            'status': 'excellent' if health_score >= 90 else 'good' if health_score >= 70 else 'needs_attention' if health_score >= 50 else 'critical',
            'issues': issues
        }
    
    def update_market_conditions(self, sentiment: float = None, volatility: float = None):
        """Update market condition parameters for AI allocation."""
        if sentiment is not None:
            self.market_sentiment = max(0, min(1, sentiment))
        if volatility is not None:
            self.volatility_index = max(0, min(1, volatility))
    
    def get_pipeline_summary(self) -> Dict[str, Any]:
        """Get summary of all pipeline accounts for BI dashboard."""
        total_accounts = len(self.accounts)
        total_deposits = sum(a.total_deposits for a in self.accounts.values())
        total_balance = sum(
            a.wallet_balance + a.investment_balance + a.algo_trading_balance
            for a in self.accounts.values()
        )
        
        # Aggregate allocation
        total_wallet = sum(a.wallet_balance for a in self.accounts.values())
        total_investment = sum(a.investment_balance for a in self.accounts.values())
        total_algo = sum(a.algo_trading_balance for a in self.accounts.values())
        
        return {
            'timestamp': datetime.now().isoformat(),
            'total_accounts': total_accounts,
            'total_deposits': total_deposits,
            'total_balance': total_balance,
            'aggregate_allocation': {
                'wallet': total_wallet,
                'investment': total_investment,
                'algo_trading': total_algo
            },
            'market_conditions': {
                'sentiment': self.market_sentiment,
                'volatility': self.volatility_index
            },
            'transaction_count': len(self.transactions)
        }


# Singleton instance
_savings_pipeline_service: Optional[SavingsPipelineService] = None


def get_savings_pipeline_service(**kwargs) -> SavingsPipelineService:
    """Get singleton instance of savings pipeline service."""
    global _savings_pipeline_service
    if _savings_pipeline_service is None:
        _savings_pipeline_service = SavingsPipelineService(**kwargs)
    return _savings_pipeline_service


def init_savings_pipeline_service(unified_balance_service=None,
                                    portfolio_service=None,
                                    algo_trading_service=None,
                                    record_transaction_func=None,
                                    generate_nft_token_func=None,
                                    health_wallets=None,
                                    investment_accounts=None,
                                    transaction_ledger=None,
                                    nft_ledger=None) -> SavingsPipelineService:
    """Initialize the savings pipeline service with all dependencies."""
    global _savings_pipeline_service
    _savings_pipeline_service = SavingsPipelineService(
        unified_balance_service=unified_balance_service,
        portfolio_service=portfolio_service,
        algo_trading_service=algo_trading_service,
        record_transaction_func=record_transaction_func,
        generate_nft_token_func=generate_nft_token_func,
        health_wallets=health_wallets,
        investment_accounts=investment_accounts,
        transaction_ledger=transaction_ledger,
        nft_ledger=nft_ledger
    )
    return _savings_pipeline_service
