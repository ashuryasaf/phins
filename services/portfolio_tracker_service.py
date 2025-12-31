"""
PHINS Portfolio Tracker Service
================================
Real-time portfolio tracking with P&L monitoring for investments and algo trading.

Features:
- Real-time P&L tracking for all positions
- Margin % calculation for trades
- Long/short term capital gains tracking
- Portfolio-level performance metrics
- Algo trading as a sub-portfolio within investments
- Cash balance management for trading
- NFT ledger integration for all transactions

This is the AI/BI backbone for healthcare fund management.
"""

import math
import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import json


class PositionType(str, Enum):
    """Position type for tax purposes"""
    LONG = "long"   # Held > 1 year
    SHORT = "short"  # Held < 1 year


class TradeType(str, Enum):
    """Type of trade"""
    BUY = "buy"
    SELL = "sell"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"


class PortfolioType(str, Enum):
    """Portfolio types"""
    INVESTMENT = "investment"
    ALGO_TRADING = "algo_trading"
    HEALTH_WALLET = "health_wallet"
    COMBINED = "combined"


@dataclass
class Position:
    """Individual position in portfolio"""
    position_id: str
    customer_id: str
    symbol: str
    name: str
    quantity: float
    avg_cost: float
    current_price: float
    portfolio_type: PortfolioType
    
    # Trade info
    buy_date: str
    last_update: str
    
    # P&L tracking
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    realized_pnl: float = 0.0
    
    # Tax tracking
    holding_period_days: int = 0
    position_type: PositionType = PositionType.SHORT
    
    # Algo trading specific
    bot_id: Optional[str] = None
    strategy: Optional[str] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    def __post_init__(self):
        self.calculate_pnl()
    
    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price
    
    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost
    
    def calculate_pnl(self):
        """Calculate P&L and holding period"""
        # Unrealized P&L
        self.unrealized_pnl = self.market_value - self.cost_basis
        self.unrealized_pnl_pct = (self.unrealized_pnl / self.cost_basis * 100) if self.cost_basis > 0 else 0
        
        # Holding period
        try:
            buy_dt = datetime.fromisoformat(self.buy_date.replace('Z', '+00:00'))
            self.holding_period_days = (datetime.now() - buy_dt.replace(tzinfo=None)).days
            self.position_type = PositionType.LONG if self.holding_period_days >= 365 else PositionType.SHORT
        except:
            self.holding_period_days = 0
            self.position_type = PositionType.SHORT
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Trade:
    """Individual trade record"""
    trade_id: str
    customer_id: str
    symbol: str
    trade_type: TradeType
    quantity: float
    price: float
    amount: float  # USD value
    portfolio_type: PortfolioType
    timestamp: str
    
    # P&L for sell trades
    realized_pnl: float = 0.0
    realized_pnl_pct: float = 0.0
    margin_pct: float = 0.0
    
    # Source/destination for transfers
    source: Optional[str] = None
    destination: Optional[str] = None
    
    # NFT tracking
    nft_token_id: Optional[str] = None
    ledger_tx_id: Optional[str] = None
    
    # Algo trading specific
    bot_id: Optional[str] = None
    strategy: Optional[str] = None
    signal_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['trade_type'] = self.trade_type.value
        d['portfolio_type'] = self.portfolio_type.value
        return d


@dataclass
class PortfolioSummary:
    """Portfolio summary with P&L"""
    customer_id: str
    portfolio_type: PortfolioType
    timestamp: str
    
    # Balances
    cash_balance: float = 0.0
    invested_value: float = 0.0
    market_value: float = 0.0
    total_value: float = 0.0
    
    # P&L
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    realized_pnl: float = 0.0
    total_pnl: float = 0.0
    
    # Performance
    day_change: float = 0.0
    day_change_pct: float = 0.0
    week_change: float = 0.0
    month_change: float = 0.0
    year_change: float = 0.0
    
    # Positions
    total_positions: int = 0
    winning_positions: int = 0
    losing_positions: int = 0
    
    # Tax info
    short_term_gains: float = 0.0
    long_term_gains: float = 0.0
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['portfolio_type'] = self.portfolio_type.value
        return d


class PortfolioTrackerService:
    """
    Comprehensive portfolio tracking with real-time P&L monitoring.
    Integrates investment and algo trading portfolios.
    """
    
    # Simulated market prices (would connect to real APIs in production)
    MARKET_PRICES = {
        'BTC': {'price': 42500, 'change_24h': 2.5, 'name': 'Bitcoin'},
        'ETH': {'price': 2280, 'change_24h': 1.8, 'name': 'Ethereum'},
        'SPY': {'price': 478, 'change_24h': 0.3, 'name': 'S&P 500 ETF'},
        'QQQ': {'price': 415, 'change_24h': 0.5, 'name': 'Nasdaq 100 ETF'},
        'AAPL': {'price': 195, 'change_24h': 0.8, 'name': 'Apple Inc'},
        'MSFT': {'price': 375, 'change_24h': 0.6, 'name': 'Microsoft'},
        'GOOGL': {'price': 140, 'change_24h': 0.4, 'name': 'Alphabet'},
        'BND': {'price': 72, 'change_24h': 0.1, 'name': 'Bond ETF'},
        'GLD': {'price': 185, 'change_24h': 0.2, 'name': 'Gold ETF'},
        'VTI': {'price': 245, 'change_24h': 0.3, 'name': 'Total Stock Market'},
        'SOL': {'price': 108, 'change_24h': 3.2, 'name': 'Solana'},
        'LINK': {'price': 15.5, 'change_24h': 2.1, 'name': 'Chainlink'},
    }
    
    def __init__(self, 
                 health_wallets: Dict = None,
                 investment_accounts: Dict = None,
                 transaction_ledger: Dict = None,
                 nft_ledger: Dict = None,
                 record_transaction_func=None,
                 generate_nft_token_func=None):
        """Initialize with data store references"""
        self.health_wallets = health_wallets or {}
        self.investment_accounts = investment_accounts or {}
        self.transaction_ledger = transaction_ledger or {}
        self.nft_ledger = nft_ledger or {}
        self.record_transaction = record_transaction_func
        self.generate_nft_token = generate_nft_token_func
        
        # Portfolio data
        self.positions: Dict[str, Dict[str, Position]] = {}  # customer_id -> position_id -> Position
        self.trades: Dict[str, List[Trade]] = {}  # customer_id -> trades
        self.algo_balances: Dict[str, Dict] = {}  # customer_id -> algo trading balance
        self.cash_balances: Dict[str, float] = {}  # customer_id -> cash available for trading
    
    def get_market_price(self, symbol: str) -> Dict:
        """Get current market price for a symbol"""
        base = self.MARKET_PRICES.get(symbol.upper(), {'price': 100, 'change_24h': 0, 'name': symbol})
        
        # Add some randomness for real-time feel
        volatility = 0.001
        if symbol.upper() in ['BTC', 'ETH', 'SOL', 'LINK']:
            volatility = 0.003
        
        price_change = base['price'] * random.uniform(-volatility, volatility)
        return {
            'symbol': symbol.upper(),
            'name': base['name'],
            'price': base['price'] + price_change,
            'change_24h': base['change_24h'] + random.uniform(-0.5, 0.5),
            'timestamp': datetime.now().isoformat()
        }
    
    def get_cash_balance(self, customer_id: str) -> float:
        """Get cash balance available for trading"""
        # Cash balance = Health Wallet + Investment Cash + Algo Cash
        wallet_bal = self.health_wallets.get(customer_id, {}).get('balance', 0)
        inv_bal = self.investment_accounts.get(customer_id, {}).get('balance', 0)
        algo_bal = self.algo_balances.get(customer_id, {}).get('available', 0)
        
        # Return combined or just trading cash
        return self.cash_balances.get(customer_id, inv_bal + algo_bal)
    
    def deposit_to_algo(self, customer_id: str, amount: float, source: str = 'investment') -> Dict:
        """Deposit funds to algo trading from source account"""
        # Validate source and check balance
        if source == 'investment':
            # Initialize investment account if not exists
            if customer_id not in self.investment_accounts:
                self.investment_accounts[customer_id] = {
                    'balance': 0,
                    'deposits': [],
                    'created_at': datetime.now().isoformat()
                }
            
            inv_acc = self.investment_accounts[customer_id]
            current_balance = inv_acc.get('balance', 0)
            
            if current_balance < amount:
                return {
                    'success': False, 
                    'error': f'Insufficient investment balance. Available: ${current_balance:.2f}, Requested: ${amount:.2f}'
                }
            
            # Deduct from investment
            self.investment_accounts[customer_id]['balance'] = current_balance - amount
            source_balance = self.investment_accounts[customer_id]['balance']
            
        elif source == 'health_wallet':
            # Initialize wallet if not exists
            if customer_id not in self.health_wallets:
                self.health_wallets[customer_id] = {
                    'balance': 0,
                    'transactions': [],
                    'created_at': datetime.now().isoformat()
                }
            
            wallet = self.health_wallets[customer_id]
            current_balance = wallet.get('balance', 0)
            
            if current_balance < amount:
                return {
                    'success': False, 
                    'error': f'Insufficient wallet balance. Available: ${current_balance:.2f}, Requested: ${amount:.2f}'
                }
            
            # Deduct from wallet
            self.health_wallets[customer_id]['balance'] = current_balance - amount
            source_balance = self.health_wallets[customer_id]['balance']
        else:
            return {'success': False, 'error': f'Invalid source account: {source}'}
        
        # Add to algo trading
        if customer_id not in self.algo_balances:
            self.algo_balances[customer_id] = {'available': 0, 'in_positions': 0, 'total_pnl': 0}
        
        self.algo_balances[customer_id]['available'] += amount
        
        # Record trade
        trade = Trade(
            trade_id=f"TRD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}",
            customer_id=customer_id,
            symbol='CASH',
            trade_type=TradeType.TRANSFER_IN,
            quantity=amount,
            price=1.0,
            amount=amount,
            portfolio_type=PortfolioType.ALGO_TRADING,
            timestamp=datetime.now().isoformat(),
            source=source,
            destination='algo_trading'
        )
        
        # Record on ledger
        if self.record_transaction:
            tx = self.record_transaction(
                customer_id=customer_id,
                tx_type='algo_trading_deposit',
                amount=amount,
                description=f'Transfer ${amount:.2f} from {source} to Algo Trading',
                metadata={
                    'trade_id': trade.trade_id,
                    'source': source,
                    'source_balance_after': source_balance,
                    'algo_balance_after': self.algo_balances[customer_id]['available']
                }
            )
            trade.nft_token_id = tx.get('nft_token_id')
            trade.ledger_tx_id = tx.get('id')
        
        if customer_id not in self.trades:
            self.trades[customer_id] = []
        self.trades[customer_id].append(trade)
        
        return {
            'success': True,
            'trade_id': trade.trade_id,
            'amount': amount,
            'algo_balance': self.algo_balances[customer_id]['available'],
            'source_balance': source_balance,
            'nft_token_id': trade.nft_token_id,
            'ledger_tx_id': trade.ledger_tx_id
        }
    
    def execute_trade(self, customer_id: str, symbol: str, trade_type: TradeType, 
                      amount: float, portfolio_type: PortfolioType = PortfolioType.ALGO_TRADING,
                      bot_id: str = None, strategy: str = None) -> Dict:
        """Execute a buy or sell trade with P&L tracking"""
        
        market = self.get_market_price(symbol)
        price = market['price']
        quantity = amount / price
        
        # Initialize customer data if needed
        if customer_id not in self.positions:
            self.positions[customer_id] = {}
        if customer_id not in self.trades:
            self.trades[customer_id] = []
        if customer_id not in self.algo_balances:
            self.algo_balances[customer_id] = {'available': 0, 'in_positions': 0, 'total_pnl': 0}
        
        if trade_type == TradeType.BUY:
            # Check balance
            if portfolio_type == PortfolioType.ALGO_TRADING:
                if self.algo_balances[customer_id]['available'] < amount:
                    return {'success': False, 'error': 'Insufficient algo trading balance'}
                self.algo_balances[customer_id]['available'] -= amount
                self.algo_balances[customer_id]['in_positions'] += amount
            else:
                inv_acc = self.investment_accounts.get(customer_id, {})
                if inv_acc.get('balance', 0) < amount:
                    return {'success': False, 'error': 'Insufficient investment balance'}
                self.investment_accounts[customer_id]['balance'] -= amount
            
            # Create or update position
            position_id = f"POS-{customer_id}-{symbol}-{portfolio_type.value}"
            if position_id in self.positions[customer_id]:
                # Average into existing position
                pos = self.positions[customer_id][position_id]
                total_cost = pos.cost_basis + amount
                total_qty = pos.quantity + quantity
                pos.avg_cost = total_cost / total_qty
                pos.quantity = total_qty
                pos.current_price = price
                pos.last_update = datetime.now().isoformat()
                pos.calculate_pnl()
            else:
                # New position
                pos = Position(
                    position_id=position_id,
                    customer_id=customer_id,
                    symbol=symbol,
                    name=market['name'],
                    quantity=quantity,
                    avg_cost=price,
                    current_price=price,
                    portfolio_type=portfolio_type,
                    buy_date=datetime.now().isoformat(),
                    last_update=datetime.now().isoformat(),
                    bot_id=bot_id,
                    strategy=strategy
                )
                self.positions[customer_id][position_id] = pos
            
            realized_pnl = 0
            margin_pct = 0
            
        elif trade_type == TradeType.SELL:
            # Find position
            position_id = f"POS-{customer_id}-{symbol}-{portfolio_type.value}"
            if position_id not in self.positions.get(customer_id, {}):
                return {'success': False, 'error': f'No position found for {symbol}'}
            
            pos = self.positions[customer_id][position_id]
            if pos.quantity < quantity:
                return {'success': False, 'error': f'Insufficient quantity. Have {pos.quantity}, need {quantity}'}
            
            # Calculate P&L
            sell_value = quantity * price
            cost_basis = quantity * pos.avg_cost
            realized_pnl = sell_value - cost_basis
            margin_pct = (realized_pnl / cost_basis * 100) if cost_basis > 0 else 0
            
            # Update position
            pos.quantity -= quantity
            pos.realized_pnl += realized_pnl
            pos.current_price = price
            pos.last_update = datetime.now().isoformat()
            pos.calculate_pnl()
            
            # Update balance
            if portfolio_type == PortfolioType.ALGO_TRADING:
                self.algo_balances[customer_id]['available'] += sell_value
                self.algo_balances[customer_id]['in_positions'] -= cost_basis
                self.algo_balances[customer_id]['total_pnl'] += realized_pnl
            else:
                self.investment_accounts[customer_id]['balance'] = \
                    self.investment_accounts.get(customer_id, {}).get('balance', 0) + sell_value
            
            # Remove position if fully sold
            if pos.quantity <= 0:
                del self.positions[customer_id][position_id]
        
        else:
            return {'success': False, 'error': 'Invalid trade type'}
        
        # Record trade
        trade = Trade(
            trade_id=f"TRD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}",
            customer_id=customer_id,
            symbol=symbol,
            trade_type=trade_type,
            quantity=quantity,
            price=price,
            amount=amount,
            portfolio_type=portfolio_type,
            timestamp=datetime.now().isoformat(),
            realized_pnl=realized_pnl if trade_type == TradeType.SELL else 0,
            margin_pct=margin_pct if trade_type == TradeType.SELL else 0,
            bot_id=bot_id,
            strategy=strategy
        )
        
        # Record on ledger
        if self.record_transaction:
            tx = self.record_transaction(
                customer_id=customer_id,
                tx_type=f'{portfolio_type.value}_{trade_type.value}',
                amount=amount,
                description=f'{trade_type.value.upper()} {quantity:.6f} {symbol} @ ${price:.2f}',
                metadata={
                    'trade_id': trade.trade_id,
                    'symbol': symbol,
                    'quantity': quantity,
                    'price': price,
                    'realized_pnl': realized_pnl,
                    'margin_pct': margin_pct,
                    'portfolio_type': portfolio_type.value,
                    'bot_id': bot_id,
                    'strategy': strategy
                }
            )
            trade.nft_token_id = tx.get('nft_token_id')
            trade.ledger_tx_id = tx.get('id')
        
        self.trades[customer_id].append(trade)
        
        return {
            'success': True,
            'trade': trade.to_dict(),
            'realized_pnl': realized_pnl,
            'margin_pct': margin_pct,
            'position': self.positions[customer_id].get(position_id).to_dict() if position_id in self.positions.get(customer_id, {}) else None,
            'nft_token_id': trade.nft_token_id
        }
    
    def get_position(self, customer_id: str, symbol: str, portfolio_type: PortfolioType) -> Optional[Dict]:
        """Get a specific position"""
        position_id = f"POS-{customer_id}-{symbol}-{portfolio_type.value}"
        pos = self.positions.get(customer_id, {}).get(position_id)
        if pos:
            # Update current price
            market = self.get_market_price(symbol)
            pos.current_price = market['price']
            pos.calculate_pnl()
            return pos.to_dict()
        return None
    
    def get_all_positions(self, customer_id: str, portfolio_type: PortfolioType = None) -> List[Dict]:
        """Get all positions for a customer"""
        positions = []
        for pos_id, pos in self.positions.get(customer_id, {}).items():
            if portfolio_type and pos.portfolio_type != portfolio_type:
                continue
            
            # Update current price
            market = self.get_market_price(pos.symbol)
            pos.current_price = market['price']
            pos.calculate_pnl()
            positions.append(pos.to_dict())
        
        return positions
    
    def get_portfolio_summary(self, customer_id: str, 
                               portfolio_type: PortfolioType = PortfolioType.COMBINED) -> PortfolioSummary:
        """Get comprehensive portfolio summary with P&L"""
        
        # Get positions
        positions = self.get_all_positions(customer_id, 
            portfolio_type if portfolio_type != PortfolioType.COMBINED else None)
        
        # Calculate totals
        market_value = sum(p['quantity'] * p['current_price'] for p in positions)
        cost_basis = sum(p['quantity'] * p['avg_cost'] for p in positions)
        unrealized_pnl = market_value - cost_basis
        unrealized_pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0
        
        # Realized P&L from trades
        realized_pnl = sum(t.realized_pnl for t in self.trades.get(customer_id, []))
        
        # Cash balance
        if portfolio_type == PortfolioType.ALGO_TRADING:
            cash = self.algo_balances.get(customer_id, {}).get('available', 0)
        elif portfolio_type == PortfolioType.INVESTMENT:
            cash = self.investment_accounts.get(customer_id, {}).get('balance', 0)
        else:
            cash = (self.algo_balances.get(customer_id, {}).get('available', 0) +
                   self.investment_accounts.get(customer_id, {}).get('balance', 0))
        
        # Position counts
        winning = sum(1 for p in positions if p['unrealized_pnl'] > 0)
        losing = sum(1 for p in positions if p['unrealized_pnl'] < 0)
        
        # Tax tracking
        short_term = sum(p['unrealized_pnl'] for p in positions if p['position_type'] == 'short')
        long_term = sum(p['unrealized_pnl'] for p in positions if p['position_type'] == 'long')
        
        summary = PortfolioSummary(
            customer_id=customer_id,
            portfolio_type=portfolio_type,
            timestamp=datetime.now().isoformat(),
            cash_balance=cash,
            invested_value=cost_basis,
            market_value=market_value,
            total_value=cash + market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            realized_pnl=realized_pnl,
            total_pnl=unrealized_pnl + realized_pnl,
            total_positions=len(positions),
            winning_positions=winning,
            losing_positions=losing,
            short_term_gains=short_term,
            long_term_gains=long_term
        )
        
        return summary
    
    def get_trade_history(self, customer_id: str, limit: int = 50, 
                          portfolio_type: PortfolioType = None) -> List[Dict]:
        """Get trade history with P&L"""
        trades = self.trades.get(customer_id, [])
        
        if portfolio_type:
            trades = [t for t in trades if t.portfolio_type == portfolio_type]
        
        # Sort by timestamp descending
        trades = sorted(trades, key=lambda t: t.timestamp, reverse=True)
        
        return [t.to_dict() for t in trades[:limit]]
    
    def get_pnl_summary(self, customer_id: str, period: str = 'day') -> Dict:
        """Get P&L summary for a period"""
        now = datetime.now()
        
        if period == 'day':
            start = now - timedelta(days=1)
        elif period == 'week':
            start = now - timedelta(weeks=1)
        elif period == 'month':
            start = now - timedelta(days=30)
        elif period == 'year':
            start = now - timedelta(days=365)
        else:
            start = datetime.min
        
        trades = self.trades.get(customer_id, [])
        period_trades = [t for t in trades if datetime.fromisoformat(t.timestamp) >= start]
        
        buy_volume = sum(t.amount for t in period_trades if t.trade_type == TradeType.BUY)
        sell_volume = sum(t.amount for t in period_trades if t.trade_type == TradeType.SELL)
        realized_pnl = sum(t.realized_pnl for t in period_trades)
        
        return {
            'period': period,
            'start_date': start.isoformat(),
            'end_date': now.isoformat(),
            'total_trades': len(period_trades),
            'buy_volume': buy_volume,
            'sell_volume': sell_volume,
            'realized_pnl': realized_pnl,
            'avg_margin_pct': (sum(t.margin_pct for t in period_trades if t.margin_pct) / 
                              len([t for t in period_trades if t.margin_pct]) 
                              if any(t.margin_pct for t in period_trades) else 0)
        }
    
    def get_algo_portfolio(self, customer_id: str) -> Dict:
        """Get algo trading portfolio as sub-portfolio of investments"""
        algo_positions = self.get_all_positions(customer_id, PortfolioType.ALGO_TRADING)
        algo_summary = self.get_portfolio_summary(customer_id, PortfolioType.ALGO_TRADING)
        algo_trades = self.get_trade_history(customer_id, 20, PortfolioType.ALGO_TRADING)
        
        return {
            'portfolio_type': 'algo_trading',
            'summary': algo_summary.to_dict(),
            'positions': algo_positions,
            'recent_trades': algo_trades,
            'balance': self.algo_balances.get(customer_id, {'available': 0, 'in_positions': 0, 'total_pnl': 0}),
            'is_sub_portfolio_of': 'investment'
        }
    
    def get_unified_portfolio(self, customer_id: str) -> Dict:
        """Get unified view of all portfolios"""
        
        # Investment portfolio
        inv_positions = self.get_all_positions(customer_id, PortfolioType.INVESTMENT)
        inv_summary = self.get_portfolio_summary(customer_id, PortfolioType.INVESTMENT)
        
        # Algo trading as sub-portfolio
        algo_portfolio = self.get_algo_portfolio(customer_id)
        
        # Combined summary
        combined_summary = self.get_portfolio_summary(customer_id, PortfolioType.COMBINED)
        
        # Cash balances
        wallet_balance = self.health_wallets.get(customer_id, {}).get('balance', 0)
        inv_cash = self.investment_accounts.get(customer_id, {}).get('balance', 0)
        algo_cash = self.algo_balances.get(customer_id, {}).get('available', 0)
        
        return {
            'customer_id': customer_id,
            'timestamp': datetime.now().isoformat(),
            'combined_summary': combined_summary.to_dict(),
            'cash_balances': {
                'health_wallet': wallet_balance,
                'investment_cash': inv_cash,
                'algo_trading_cash': algo_cash,
                'total_cash': wallet_balance + inv_cash + algo_cash,
                'available_for_trading': inv_cash + algo_cash
            },
            'portfolios': {
                'investment': {
                    'summary': inv_summary.to_dict(),
                    'positions': inv_positions,
                    'includes_algo_trading': True
                },
                'algo_trading': algo_portfolio
            },
            'pnl_summary': {
                'day': self.get_pnl_summary(customer_id, 'day'),
                'week': self.get_pnl_summary(customer_id, 'week'),
                'month': self.get_pnl_summary(customer_id, 'month')
            }
        }


# Singleton instance
_portfolio_tracker: Optional[PortfolioTrackerService] = None


def get_portfolio_tracker(**kwargs) -> PortfolioTrackerService:
    """Get or create portfolio tracker instance"""
    global _portfolio_tracker
    if _portfolio_tracker is None:
        _portfolio_tracker = PortfolioTrackerService(**kwargs)
    return _portfolio_tracker


def init_portfolio_tracker(health_wallets, investment_accounts, transaction_ledger,
                           nft_ledger, record_transaction_func, generate_nft_token_func):
    """Initialize portfolio tracker with dependencies"""
    global _portfolio_tracker
    _portfolio_tracker = PortfolioTrackerService(
        health_wallets=health_wallets,
        investment_accounts=investment_accounts,
        transaction_ledger=transaction_ledger,
        nft_ledger=nft_ledger,
        record_transaction_func=record_transaction_func,
        generate_nft_token_func=generate_nft_token_func
    )
    return _portfolio_tracker
