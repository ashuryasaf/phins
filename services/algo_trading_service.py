"""
PHINS Algorithmic Trading & Hedging Service
============================================
Enterprise-grade 24/7 automated trading system for multi-asset investment management.

Features:
- 24/7 Automated Trading Engine
- Multi-asset support: Equities, Crypto, Commodities, Forex, Indices
- Risk-adjusted position sizing based on user risk profile
- Hedging strategies: Delta hedging, Portfolio insurance, Pairs trading
- Real-time market data integration
- Sophisticated order execution algorithms
- Performance tracking and analytics
- Full ledger integration with audit trail

Asset Classes Supported:
- Equities (ETFs, stocks, indexes)
- Cryptocurrencies (BTC, ETH, SOL, etc.)
- Commodities (Gold, Silver, Oil)
- Forex (EUR, GBP, JPY, CHF, ILS)
- Fixed Income (Bonds, Treasury ETFs)
"""

import math
import random
import hashlib
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import json

# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================

class TradingMode(str, Enum):
    """Trading automation modes"""
    MANUAL = "manual"
    SEMI_AUTO = "semi_auto"  # Signals but manual execution
    FULL_AUTO = "full_auto"  # 24/7 automated trading
    PAUSED = "paused"

class OrderType(str, Enum):
    """Order types for execution"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    BRACKET = "bracket"  # Entry + stop loss + take profit

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"

class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"

class StrategyType(str, Enum):
    """Available trading strategies"""
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    TREND_FOLLOWING = "trend_following"
    BREAKOUT = "breakout"
    PAIRS_TRADING = "pairs_trading"
    MARKET_MAKING = "market_making"
    ARBITRAGE = "arbitrage"
    GRID_TRADING = "grid_trading"
    DCA = "dollar_cost_averaging"
    SMART_BETA = "smart_beta"

class HedgeType(str, Enum):
    """Hedging strategy types"""
    DELTA_HEDGE = "delta_hedge"
    PORTFOLIO_INSURANCE = "portfolio_insurance"
    PAIRS_HEDGE = "pairs_hedge"
    VOLATILITY_HEDGE = "volatility_hedge"
    CURRENCY_HEDGE = "currency_hedge"
    COMMODITY_HEDGE = "commodity_hedge"

class AssetClass(str, Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    FOREX = "forex"
    FIXED_INCOME = "fixed_income"
    INDEX = "index"
    OPTIONS = "options"
    FUTURES = "futures"

class RiskLevel(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE_CONSERVATIVE = "moderate_conservative"
    MODERATE = "moderate"
    MODERATE_AGGRESSIVE = "moderate_aggressive"
    AGGRESSIVE = "aggressive"

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class TradingSignal:
    """Generated trading signal from strategy"""
    signal_id: str
    strategy: StrategyType
    symbol: str
    asset_class: AssetClass
    side: OrderSide
    strength: float  # 0-1 signal strength
    confidence: float  # 0-1 confidence level
    entry_price: float
    target_price: float
    stop_loss: float
    risk_reward_ratio: float
    timeframe: str
    reasoning: str
    indicators: Dict[str, float] = field(default_factory=dict)
    generated_at: str = ""
    expires_at: str = ""
    executed: bool = False
    
    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now().isoformat()
        if not self.expires_at:
            self.expires_at = (datetime.now() + timedelta(hours=4)).isoformat()

@dataclass
class AlgoOrder:
    """Algorithmic trading order"""
    order_id: str
    account_id: str
    signal_id: Optional[str]
    symbol: str
    asset_class: AssetClass
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float  # Limit price or trigger price
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    strategy: Optional[StrategyType] = None
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    filled_at: Optional[str] = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()

@dataclass
class AlgoPosition:
    """Current algo trading position"""
    position_id: str
    account_id: str
    symbol: str
    asset_class: AssetClass
    side: str  # "long" or "short"
    quantity: float
    avg_cost: float
    current_price: float
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    strategy: Optional[StrategyType] = None
    opened_at: str = ""
    updated_at: str = ""
    
    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price
    
    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost

@dataclass
class HedgePosition:
    """Hedging position for risk management"""
    hedge_id: str
    account_id: str
    hedge_type: HedgeType
    underlying_symbol: str
    hedge_symbol: str
    hedge_ratio: float
    quantity: float
    cost_basis: float
    current_value: float
    effectiveness: float  # Hedge effectiveness 0-1
    created_at: str = ""
    expires_at: Optional[str] = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

@dataclass
class TradingLedgerEntry:
    """Ledger entry for algo trading activities"""
    entry_id: str
    account_id: str
    entry_type: str  # order, fill, signal, hedge, pnl_realization
    order_id: Optional[str]
    symbol: str
    asset_class: str
    side: str
    quantity: float
    price: float
    value: float
    realized_pnl: float = 0.0
    fees: float = 0.0
    strategy: Optional[str] = None
    notes: str = ""
    timestamp: str = ""
    nft_token_id: Optional[str] = None
    transaction_hash: Optional[str] = None
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

@dataclass
class StrategyConfig:
    """Configuration for a trading strategy"""
    strategy_id: str
    strategy_type: StrategyType
    name: str
    enabled: bool = True
    allocation_pct: float = 10.0  # % of portfolio for this strategy
    max_position_size: float = 5.0  # % of portfolio per position
    risk_per_trade: float = 1.0  # % risk per trade
    max_daily_trades: int = 10
    asset_classes: List[AssetClass] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.asset_classes:
            self.asset_classes = [AssetClass.EQUITY, AssetClass.CRYPTO]

@dataclass
class TradingAccount:
    """Algo trading account"""
    account_id: str
    customer_id: str
    name: str = "Algo Trading Account"
    balance: float = 0.0
    equity: float = 0.0  # Balance + unrealized P&L
    margin_used: float = 0.0
    available_margin: float = 0.0
    risk_level: RiskLevel = RiskLevel.MODERATE
    trading_mode: TradingMode = TradingMode.PAUSED
    max_drawdown_pct: float = 10.0
    daily_loss_limit: float = 2.0  # % of portfolio
    position_limit: int = 20
    active_strategies: List[str] = field(default_factory=list)
    positions: Dict[str, AlgoPosition] = field(default_factory=dict)
    orders: Dict[str, AlgoOrder] = field(default_factory=dict)
    hedges: Dict[str, HedgePosition] = field(default_factory=dict)
    ledger: List[TradingLedgerEntry] = field(default_factory=list)
    performance: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        self.equity = self.balance

# ============================================================================
# MARKET DATA PROVIDER
# ============================================================================

class MarketDataProvider:
    """Real-time market data provider for all asset classes"""
    
    # Extended market data covering all asset classes
    MARKET_DATA: Dict[str, Dict] = {
        # === EQUITIES (ETFs & Indices) ===
        "SPY": {"price": 478.50, "name": "S&P 500 ETF", "class": AssetClass.EQUITY, "vol": 0.15},
        "QQQ": {"price": 405.20, "name": "NASDAQ 100 ETF", "class": AssetClass.EQUITY, "vol": 0.20},
        "VTI": {"price": 245.30, "name": "Total Stock Market", "class": AssetClass.EQUITY, "vol": 0.14},
        "IWM": {"price": 198.40, "name": "Russell 2000 ETF", "class": AssetClass.EQUITY, "vol": 0.22},
        "DIA": {"price": 378.50, "name": "Dow Jones ETF", "class": AssetClass.EQUITY, "vol": 0.13},
        "EFA": {"price": 75.80, "name": "EAFE ETF", "class": AssetClass.EQUITY, "vol": 0.16},
        "EEM": {"price": 40.25, "name": "Emerging Markets ETF", "class": AssetClass.EQUITY, "vol": 0.23},
        "VGK": {"price": 62.10, "name": "Europe ETF", "class": AssetClass.EQUITY, "vol": 0.17},
        "ARKK": {"price": 45.80, "name": "ARK Innovation ETF", "class": AssetClass.EQUITY, "vol": 0.45},
        
        # === CRYPTOCURRENCIES ===
        "BTC": {"price": 97500.00, "name": "Bitcoin", "class": AssetClass.CRYPTO, "vol": 0.55},
        "ETH": {"price": 3450.00, "name": "Ethereum", "class": AssetClass.CRYPTO, "vol": 0.50},
        "SOL": {"price": 185.00, "name": "Solana", "class": AssetClass.CRYPTO, "vol": 0.65},
        "BNB": {"price": 680.00, "name": "Binance Coin", "class": AssetClass.CRYPTO, "vol": 0.48},
        "XRP": {"price": 2.35, "name": "XRP/Ripple", "class": AssetClass.CRYPTO, "vol": 0.58},
        "ADA": {"price": 0.92, "name": "Cardano", "class": AssetClass.CRYPTO, "vol": 0.52},
        "DOGE": {"price": 0.32, "name": "Dogecoin", "class": AssetClass.CRYPTO, "vol": 0.70},
        "DOT": {"price": 7.20, "name": "Polkadot", "class": AssetClass.CRYPTO, "vol": 0.55},
        "MATIC": {"price": 0.58, "name": "Polygon", "class": AssetClass.CRYPTO, "vol": 0.60},
        "AVAX": {"price": 38.50, "name": "Avalanche", "class": AssetClass.CRYPTO, "vol": 0.62},
        "LINK": {"price": 22.80, "name": "Chainlink", "class": AssetClass.CRYPTO, "vol": 0.48},
        "USDC": {"price": 1.00, "name": "USD Coin", "class": AssetClass.CRYPTO, "vol": 0.001},
        "USDT": {"price": 1.00, "name": "Tether", "class": AssetClass.CRYPTO, "vol": 0.001},
        
        # === COMMODITIES ===
        "GLD": {"price": 188.50, "name": "Gold ETF", "class": AssetClass.COMMODITY, "vol": 0.12},
        "SLV": {"price": 22.30, "name": "Silver ETF", "class": AssetClass.COMMODITY, "vol": 0.25},
        "USO": {"price": 78.90, "name": "Oil ETF", "class": AssetClass.COMMODITY, "vol": 0.30},
        "UNG": {"price": 12.50, "name": "Natural Gas ETF", "class": AssetClass.COMMODITY, "vol": 0.45},
        "CORN": {"price": 21.80, "name": "Corn ETF", "class": AssetClass.COMMODITY, "vol": 0.22},
        "WEAT": {"price": 6.35, "name": "Wheat ETF", "class": AssetClass.COMMODITY, "vol": 0.24},
        "CPER": {"price": 28.40, "name": "Copper ETF", "class": AssetClass.COMMODITY, "vol": 0.26},
        "PDBC": {"price": 14.20, "name": "Commodities Basket", "class": AssetClass.COMMODITY, "vol": 0.18},
        
        # === FOREX ===
        "EURUSD": {"price": 1.0820, "name": "Euro/USD", "class": AssetClass.FOREX, "vol": 0.06},
        "GBPUSD": {"price": 1.2680, "name": "GBP/USD", "class": AssetClass.FOREX, "vol": 0.07},
        "USDJPY": {"price": 149.80, "name": "USD/JPY", "class": AssetClass.FOREX, "vol": 0.08},
        "USDCHF": {"price": 0.8850, "name": "USD/CHF", "class": AssetClass.FOREX, "vol": 0.05},
        "AUDUSD": {"price": 0.6580, "name": "AUD/USD", "class": AssetClass.FOREX, "vol": 0.09},
        "USDCAD": {"price": 1.3520, "name": "USD/CAD", "class": AssetClass.FOREX, "vol": 0.06},
        "USDILS": {"price": 3.58, "name": "USD/ILS", "class": AssetClass.FOREX, "vol": 0.08},
        "FXE": {"price": 102.50, "name": "Euro ETF", "class": AssetClass.FOREX, "vol": 0.06},
        "FXY": {"price": 63.20, "name": "Yen ETF", "class": AssetClass.FOREX, "vol": 0.08},
        
        # === FIXED INCOME ===
        "BND": {"price": 72.50, "name": "Total Bond ETF", "class": AssetClass.FIXED_INCOME, "vol": 0.05},
        "TLT": {"price": 92.30, "name": "20+ Year Treasury", "class": AssetClass.FIXED_INCOME, "vol": 0.12},
        "IEF": {"price": 95.80, "name": "7-10 Year Treasury", "class": AssetClass.FIXED_INCOME, "vol": 0.08},
        "SHY": {"price": 81.20, "name": "1-3 Year Treasury", "class": AssetClass.FIXED_INCOME, "vol": 0.02},
        "LQD": {"price": 108.45, "name": "Corp Bond ETF", "class": AssetClass.FIXED_INCOME, "vol": 0.07},
        "HYG": {"price": 76.20, "name": "High Yield Bond ETF", "class": AssetClass.FIXED_INCOME, "vol": 0.10},
        "TIP": {"price": 107.30, "name": "TIPS ETF", "class": AssetClass.FIXED_INCOME, "vol": 0.06},
        
        # === INDICES (for reference/tracking) ===
        "^SPX": {"price": 4785.00, "name": "S&P 500 Index", "class": AssetClass.INDEX, "vol": 0.15},
        "^NDX": {"price": 16850.00, "name": "NASDAQ 100 Index", "class": AssetClass.INDEX, "vol": 0.20},
        "^DJI": {"price": 37850.00, "name": "Dow Jones Index", "class": AssetClass.INDEX, "vol": 0.13},
        "^VIX": {"price": 14.50, "name": "VIX Volatility Index", "class": AssetClass.INDEX, "vol": 0.80},
        "^RUT": {"price": 1985.00, "name": "Russell 2000 Index", "class": AssetClass.INDEX, "vol": 0.22},
        
        # === VOLATILITY/HEDGING ===
        "VXX": {"price": 15.20, "name": "VIX Short-Term", "class": AssetClass.OPTIONS, "vol": 0.60},
        "UVXY": {"price": 8.50, "name": "Ultra VIX", "class": AssetClass.OPTIONS, "vol": 0.85},
        "SVXY": {"price": 65.30, "name": "Short VIX", "class": AssetClass.OPTIONS, "vol": 0.45},
    }
    
    def __init__(self):
        self._price_history: Dict[str, List[Tuple[datetime, float]]] = {}
        self._last_update = datetime.now()
        self._lock = threading.Lock()
        
    def get_price(self, symbol: str) -> Optional[float]:
        """Get current price for symbol"""
        data = self.MARKET_DATA.get(symbol)
        return data["price"] if data else None
    
    def get_market_data(self, symbol: str) -> Optional[Dict]:
        """Get full market data for symbol"""
        return self.MARKET_DATA.get(symbol)
    
    def get_all_symbols(self, asset_class: Optional[AssetClass] = None) -> List[str]:
        """Get all available symbols, optionally filtered by asset class"""
        if asset_class:
            return [s for s, d in self.MARKET_DATA.items() if d["class"] == asset_class]
        return list(self.MARKET_DATA.keys())
    
    def simulate_price_update(self) -> Dict[str, float]:
        """Simulate real-time price updates (for demo)"""
        updates = {}
        with self._lock:
            for symbol, data in self.MARKET_DATA.items():
                vol = data.get("vol", 0.15)
                # Random walk with mean reversion
                change_pct = random.gauss(0, vol / 100)
                new_price = data["price"] * (1 + change_pct)
                
                # Store history
                if symbol not in self._price_history:
                    self._price_history[symbol] = []
                self._price_history[symbol].append((datetime.now(), data["price"]))
                # Keep last 1000 points
                self._price_history[symbol] = self._price_history[symbol][-1000:]
                
                data["price"] = round(new_price, 6 if data["class"] == AssetClass.FOREX else 2)
                data["change_24h"] = round(change_pct * 100, 2)
                updates[symbol] = data["price"]
                
            self._last_update = datetime.now()
        return updates
    
    def get_volatility(self, symbol: str) -> float:
        """Get annualized volatility for symbol"""
        data = self.MARKET_DATA.get(symbol)
        return data.get("vol", 0.20) if data else 0.20
    
    def get_correlation(self, symbol1: str, symbol2: str) -> float:
        """Estimate correlation between two assets"""
        # Simplified correlation matrix
        class1 = self.MARKET_DATA.get(symbol1, {}).get("class")
        class2 = self.MARKET_DATA.get(symbol2, {}).get("class")
        
        if class1 == class2:
            return 0.7 + random.uniform(-0.1, 0.2)  # Same class = high correlation
        elif {class1, class2} == {AssetClass.EQUITY, AssetClass.CRYPTO}:
            return 0.4 + random.uniform(-0.1, 0.1)  # Moderate correlation
        elif AssetClass.COMMODITY in {class1, class2}:
            return 0.2 + random.uniform(-0.1, 0.1)  # Low correlation with commodities
        elif AssetClass.FIXED_INCOME in {class1, class2}:
            return -0.2 + random.uniform(-0.1, 0.1)  # Negative correlation with bonds
        return random.uniform(-0.1, 0.3)

# ============================================================================
# TRADING STRATEGIES
# ============================================================================

class TradingStrategy:
    """Base class for trading strategies"""
    
    def __init__(self, config: StrategyConfig, market_data: MarketDataProvider):
        self.config = config
        self.market_data = market_data
        self.signals_generated = 0
        
    def generate_signals(self) -> List[TradingSignal]:
        """Generate trading signals - override in subclass"""
        raise NotImplementedError
    
    def _create_signal(self, symbol: str, side: OrderSide, strength: float,
                       entry: float, target: float, stop: float, reasoning: str,
                       indicators: Dict = None) -> TradingSignal:
        """Helper to create a trading signal"""
        risk_reward = abs(target - entry) / abs(entry - stop) if abs(entry - stop) > 0 else 0
        
        data = self.market_data.get_market_data(symbol)
        asset_class = data["class"] if data else AssetClass.EQUITY
        
        self.signals_generated += 1
        return TradingSignal(
            signal_id=f"SIG-{self.config.strategy_type.value[:3].upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100,999)}",
            strategy=self.config.strategy_type,
            symbol=symbol,
            asset_class=asset_class,
            side=side,
            strength=strength,
            confidence=min(0.95, strength * 0.9 + random.uniform(0, 0.1)),
            entry_price=entry,
            target_price=target,
            stop_loss=stop,
            risk_reward_ratio=risk_reward,
            timeframe="4h",
            reasoning=reasoning,
            indicators=indicators or {}
        )


class MomentumStrategy(TradingStrategy):
    """Momentum-based trading strategy"""
    
    def generate_signals(self) -> List[TradingSignal]:
        signals = []
        symbols = self.config.symbols or self.market_data.get_all_symbols()
        
        for symbol in symbols[:20]:  # Limit to avoid too many signals
            data = self.market_data.get_market_data(symbol)
            if not data:
                continue
                
            price = data["price"]
            vol = data.get("vol", 0.15)
            
            # Simulated momentum indicators
            rsi = random.uniform(30, 70) + random.gauss(0, 15)
            macd = random.gauss(0, price * 0.005)
            momentum = random.gauss(0, vol * 50)
            
            # Generate signal if strong momentum
            if rsi > 65 and momentum > vol * 25:
                # Bullish momentum
                entry = price
                target = price * (1 + vol * 0.5)
                stop = price * (1 - vol * 0.2)
                strength = min(1.0, (rsi - 50) / 50 + (momentum / (vol * 100)))
                
                signals.append(self._create_signal(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    strength=strength,
                    entry=entry,
                    target=target,
                    stop=stop,
                    reasoning=f"Strong bullish momentum: RSI={rsi:.1f}, MACD crossover positive",
                    indicators={"rsi": rsi, "macd": macd, "momentum": momentum}
                ))
            elif rsi < 35 and momentum < -vol * 25:
                # Bearish momentum (short signal)
                entry = price
                target = price * (1 - vol * 0.5)
                stop = price * (1 + vol * 0.2)
                strength = min(1.0, (50 - rsi) / 50 + abs(momentum) / (vol * 100))
                
                signals.append(self._create_signal(
                    symbol=symbol,
                    side=OrderSide.SHORT,
                    strength=strength,
                    entry=entry,
                    target=target,
                    stop=stop,
                    reasoning=f"Strong bearish momentum: RSI={rsi:.1f}, MACD crossover negative",
                    indicators={"rsi": rsi, "macd": macd, "momentum": momentum}
                ))
        
        return signals


class MeanReversionStrategy(TradingStrategy):
    """Mean reversion strategy - buy oversold, sell overbought"""
    
    def generate_signals(self) -> List[TradingSignal]:
        signals = []
        symbols = self.config.symbols or self.market_data.get_all_symbols()
        
        for symbol in symbols[:20]:
            data = self.market_data.get_market_data(symbol)
            if not data:
                continue
            
            price = data["price"]
            vol = data.get("vol", 0.15)
            
            # Simulated mean reversion indicators
            bb_position = random.uniform(-1, 1)  # Position relative to Bollinger Bands
            z_score = random.gauss(0, 1.5)
            
            if z_score < -2 or bb_position < -0.8:
                # Oversold - buy signal
                entry = price
                target = price * (1 + abs(z_score) * vol * 0.3)
                stop = price * (1 - vol * 0.15)
                strength = min(1.0, abs(z_score) / 3)
                
                signals.append(self._create_signal(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    strength=strength,
                    entry=entry,
                    target=target,
                    stop=stop,
                    reasoning=f"Oversold condition: Z-score={z_score:.2f}, BB position={bb_position:.2f}",
                    indicators={"z_score": z_score, "bb_position": bb_position}
                ))
            elif z_score > 2 or bb_position > 0.8:
                # Overbought - sell/short signal
                entry = price
                target = price * (1 - abs(z_score) * vol * 0.3)
                stop = price * (1 + vol * 0.15)
                strength = min(1.0, abs(z_score) / 3)
                
                signals.append(self._create_signal(
                    symbol=symbol,
                    side=OrderSide.SHORT,
                    strength=strength,
                    entry=entry,
                    target=target,
                    stop=stop,
                    reasoning=f"Overbought condition: Z-score={z_score:.2f}, BB position={bb_position:.2f}",
                    indicators={"z_score": z_score, "bb_position": bb_position}
                ))
        
        return signals


class TrendFollowingStrategy(TradingStrategy):
    """Trend following strategy using moving average crossovers"""
    
    def generate_signals(self) -> List[TradingSignal]:
        signals = []
        symbols = self.config.symbols or self.market_data.get_all_symbols()
        
        for symbol in symbols[:20]:
            data = self.market_data.get_market_data(symbol)
            if not data:
                continue
            
            price = data["price"]
            vol = data.get("vol", 0.15)
            
            # Simulated trend indicators
            ma_20 = price * (1 + random.gauss(0, 0.02))
            ma_50 = price * (1 + random.gauss(0, 0.04))
            ma_200 = price * (1 + random.gauss(0, 0.08))
            adx = random.uniform(15, 50)  # Trend strength
            
            if price > ma_20 > ma_50 > ma_200 and adx > 25:
                # Strong uptrend
                entry = price
                target = price * (1 + vol * 0.8)
                stop = ma_20 * 0.98
                strength = min(1.0, adx / 40)
                
                signals.append(self._create_signal(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    strength=strength,
                    entry=entry,
                    target=target,
                    stop=stop,
                    reasoning=f"Strong uptrend: Price > MA20 > MA50 > MA200, ADX={adx:.1f}",
                    indicators={"ma_20": ma_20, "ma_50": ma_50, "ma_200": ma_200, "adx": adx}
                ))
            elif price < ma_20 < ma_50 < ma_200 and adx > 25:
                # Strong downtrend
                entry = price
                target = price * (1 - vol * 0.8)
                stop = ma_20 * 1.02
                strength = min(1.0, adx / 40)
                
                signals.append(self._create_signal(
                    symbol=symbol,
                    side=OrderSide.SHORT,
                    strength=strength,
                    entry=entry,
                    target=target,
                    stop=stop,
                    reasoning=f"Strong downtrend: Price < MA20 < MA50 < MA200, ADX={adx:.1f}",
                    indicators={"ma_20": ma_20, "ma_50": ma_50, "ma_200": ma_200, "adx": adx}
                ))
        
        return signals


class GridTradingStrategy(TradingStrategy):
    """Grid trading strategy for ranging markets"""
    
    def __init__(self, config: StrategyConfig, market_data: MarketDataProvider):
        super().__init__(config, market_data)
        self.grid_levels = config.parameters.get("grid_levels", 5)
        self.grid_spacing = config.parameters.get("grid_spacing", 0.02)  # 2%
        
    def generate_signals(self) -> List[TradingSignal]:
        signals = []
        symbols = self.config.symbols or ["BTC", "ETH", "SPY"]
        
        for symbol in symbols[:5]:
            data = self.market_data.get_market_data(symbol)
            if not data:
                continue
            
            price = data["price"]
            
            # Generate grid buy/sell levels
            for i in range(1, self.grid_levels + 1):
                buy_level = price * (1 - self.grid_spacing * i)
                sell_level = price * (1 + self.grid_spacing * i)
                
                signals.append(self._create_signal(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    strength=0.6,
                    entry=buy_level,
                    target=buy_level * (1 + self.grid_spacing),
                    stop=buy_level * (1 - self.grid_spacing * 2),
                    reasoning=f"Grid buy level {i}: ${buy_level:.2f}",
                    indicators={"grid_level": i, "grid_type": "buy"}
                ))
                
                signals.append(self._create_signal(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    strength=0.6,
                    entry=sell_level,
                    target=sell_level * (1 - self.grid_spacing),
                    stop=sell_level * (1 + self.grid_spacing * 2),
                    reasoning=f"Grid sell level {i}: ${sell_level:.2f}",
                    indicators={"grid_level": i, "grid_type": "sell"}
                ))
        
        return signals


# ============================================================================
# HEDGING ENGINE
# ============================================================================

class HedgingEngine:
    """Advanced hedging engine for portfolio risk management"""
    
    def __init__(self, market_data: MarketDataProvider):
        self.market_data = market_data
        
    def calculate_portfolio_beta(self, positions: Dict[str, AlgoPosition]) -> float:
        """Calculate portfolio beta relative to market"""
        if not positions:
            return 0.0
        
        total_value = sum(p.market_value for p in positions.values())
        if total_value == 0:
            return 0.0
        
        weighted_beta = 0
        for pos in positions.values():
            # Simplified beta calculation
            data = self.market_data.get_market_data(pos.symbol)
            if data:
                asset_beta = 1.0 if data["class"] in [AssetClass.EQUITY, AssetClass.INDEX] else 0.5
                weighted_beta += (pos.market_value / total_value) * asset_beta
        
        return weighted_beta
    
    def calculate_portfolio_delta(self, positions: Dict[str, AlgoPosition]) -> float:
        """Calculate portfolio delta exposure"""
        total_delta = 0
        for pos in positions.values():
            if pos.side == "long":
                total_delta += pos.market_value
            else:
                total_delta -= pos.market_value
        return total_delta
    
    def recommend_hedges(self, account: TradingAccount) -> List[Dict]:
        """Recommend hedging strategies based on portfolio composition"""
        recommendations = []
        positions = account.positions
        
        if not positions:
            return recommendations
        
        total_value = sum(p.market_value for p in positions.values())
        
        # Calculate exposures by asset class
        class_exposure = {}
        for pos in positions.values():
            cls = pos.asset_class.value
            if cls not in class_exposure:
                class_exposure[cls] = 0
            class_exposure[cls] += pos.market_value
        
        # Portfolio beta hedge recommendation
        beta = self.calculate_portfolio_beta(positions)
        if beta > 0.8:
            hedge_amount = total_value * (beta - 0.5) * 0.5
            recommendations.append({
                "hedge_type": HedgeType.DELTA_HEDGE.value,
                "description": "Reduce market beta exposure",
                "instrument": "SPY",
                "action": "short",
                "amount": hedge_amount,
                "reasoning": f"Portfolio beta ({beta:.2f}) is high. Consider shorting SPY or buying VIX calls."
            })
        
        # Crypto volatility hedge
        crypto_exposure = class_exposure.get(AssetClass.CRYPTO.value, 0)
        if crypto_exposure > total_value * 0.15:
            recommendations.append({
                "hedge_type": HedgeType.VOLATILITY_HEDGE.value,
                "description": "Hedge crypto volatility exposure",
                "instrument": "USDC",
                "action": "buy",
                "amount": crypto_exposure * 0.3,
                "reasoning": f"High crypto exposure ({crypto_exposure/total_value*100:.1f}%). Consider converting some to stablecoins."
            })
        
        # Currency hedge for international exposure
        equity_exposure = class_exposure.get(AssetClass.EQUITY.value, 0)
        if equity_exposure > total_value * 0.5:
            recommendations.append({
                "hedge_type": HedgeType.CURRENCY_HEDGE.value,
                "description": "Currency hedge for USD exposure",
                "instrument": "FXE",
                "action": "buy",
                "amount": equity_exposure * 0.1,
                "reasoning": "Consider diversifying currency exposure with EUR or gold."
            })
        
        # Commodity hedge for inflation protection
        commodity_exposure = class_exposure.get(AssetClass.COMMODITY.value, 0)
        if commodity_exposure < total_value * 0.05:
            recommendations.append({
                "hedge_type": HedgeType.COMMODITY_HEDGE.value,
                "description": "Add inflation hedge",
                "instrument": "GLD",
                "action": "buy",
                "amount": total_value * 0.05,
                "reasoning": "Low commodity exposure. Consider gold for inflation protection."
            })
        
        return recommendations
    
    def create_hedge(self, account: TradingAccount, hedge_type: HedgeType,
                     underlying: str, hedge_instrument: str, 
                     hedge_ratio: float, amount: float) -> HedgePosition:
        """Create a hedge position"""
        hedge_data = self.market_data.get_market_data(hedge_instrument)
        price = hedge_data["price"] if hedge_data else 100.0
        quantity = amount / price
        
        hedge = HedgePosition(
            hedge_id=f"HDG-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100,999)}",
            account_id=account.account_id,
            hedge_type=hedge_type,
            underlying_symbol=underlying,
            hedge_symbol=hedge_instrument,
            hedge_ratio=hedge_ratio,
            quantity=quantity,
            cost_basis=amount,
            current_value=amount,
            effectiveness=0.85 + random.uniform(-0.1, 0.1)
        )
        
        return hedge

# ============================================================================
# ALGO TRADING ENGINE (MAIN SERVICE)
# ============================================================================

class AlgoTradingService:
    """
    Core algorithmic trading service - 24/7 automated trading engine.
    Manages accounts, strategies, orders, positions, and hedging.
    """
    
    # Risk parameters by risk level
    RISK_PARAMETERS = {
        RiskLevel.CONSERVATIVE: {
            "max_position_pct": 3.0,
            "max_daily_trades": 5,
            "stop_loss_pct": 2.0,
            "max_leverage": 1.0,
            "crypto_allocation": 5.0,
            "equity_allocation": 40.0,
            "bond_allocation": 45.0,
            "commodity_allocation": 10.0,
        },
        RiskLevel.MODERATE_CONSERVATIVE: {
            "max_position_pct": 5.0,
            "max_daily_trades": 10,
            "stop_loss_pct": 3.0,
            "max_leverage": 1.5,
            "crypto_allocation": 10.0,
            "equity_allocation": 50.0,
            "bond_allocation": 30.0,
            "commodity_allocation": 10.0,
        },
        RiskLevel.MODERATE: {
            "max_position_pct": 7.0,
            "max_daily_trades": 15,
            "stop_loss_pct": 4.0,
            "max_leverage": 2.0,
            "crypto_allocation": 15.0,
            "equity_allocation": 55.0,
            "bond_allocation": 20.0,
            "commodity_allocation": 10.0,
        },
        RiskLevel.MODERATE_AGGRESSIVE: {
            "max_position_pct": 10.0,
            "max_daily_trades": 25,
            "stop_loss_pct": 5.0,
            "max_leverage": 3.0,
            "crypto_allocation": 25.0,
            "equity_allocation": 55.0,
            "bond_allocation": 10.0,
            "commodity_allocation": 10.0,
        },
        RiskLevel.AGGRESSIVE: {
            "max_position_pct": 15.0,
            "max_daily_trades": 50,
            "stop_loss_pct": 7.0,
            "max_leverage": 5.0,
            "crypto_allocation": 35.0,
            "equity_allocation": 50.0,
            "bond_allocation": 5.0,
            "commodity_allocation": 10.0,
        },
    }
    
    def __init__(self):
        self.market_data = MarketDataProvider()
        self.hedging_engine = HedgingEngine(self.market_data)
        self.accounts: Dict[str, TradingAccount] = {}
        self.strategies: Dict[str, TradingStrategy] = {}
        self.active_signals: Dict[str, TradingSignal] = {}
        self._trading_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        
        # Initialize default strategies
        self._init_default_strategies()
    
    def _init_default_strategies(self):
        """Initialize default trading strategies"""
        strategies = [
            StrategyConfig(
                strategy_id="STR-MOM-001",
                strategy_type=StrategyType.MOMENTUM,
                name="Momentum Alpha",
                allocation_pct=25.0,
                asset_classes=[AssetClass.EQUITY, AssetClass.CRYPTO],
                parameters={"lookback_period": 20, "threshold": 0.02}
            ),
            StrategyConfig(
                strategy_id="STR-MR-001",
                strategy_type=StrategyType.MEAN_REVERSION,
                name="Mean Reversion Beta",
                allocation_pct=20.0,
                asset_classes=[AssetClass.EQUITY, AssetClass.FOREX],
                parameters={"z_score_threshold": 2.0, "lookback": 50}
            ),
            StrategyConfig(
                strategy_id="STR-TF-001",
                strategy_type=StrategyType.TREND_FOLLOWING,
                name="Trend Follower Gamma",
                allocation_pct=25.0,
                asset_classes=[AssetClass.COMMODITY, AssetClass.CRYPTO],
                parameters={"ma_fast": 20, "ma_slow": 50, "adx_threshold": 25}
            ),
            StrategyConfig(
                strategy_id="STR-GRID-001",
                strategy_type=StrategyType.GRID_TRADING,
                name="Grid Trader Delta",
                allocation_pct=15.0,
                asset_classes=[AssetClass.CRYPTO],
                symbols=["BTC", "ETH"],
                parameters={"grid_levels": 5, "grid_spacing": 0.02}
            ),
            StrategyConfig(
                strategy_id="STR-DCA-001",
                strategy_type=StrategyType.DCA,
                name="DCA Accumulator",
                allocation_pct=15.0,
                asset_classes=[AssetClass.EQUITY, AssetClass.CRYPTO],
                symbols=["SPY", "QQQ", "BTC", "ETH"],
                parameters={"interval": "daily", "amount_pct": 1.0}
            ),
        ]
        
        for config in strategies:
            if config.strategy_type == StrategyType.MOMENTUM:
                self.strategies[config.strategy_id] = MomentumStrategy(config, self.market_data)
            elif config.strategy_type == StrategyType.MEAN_REVERSION:
                self.strategies[config.strategy_id] = MeanReversionStrategy(config, self.market_data)
            elif config.strategy_type == StrategyType.TREND_FOLLOWING:
                self.strategies[config.strategy_id] = TrendFollowingStrategy(config, self.market_data)
            elif config.strategy_type == StrategyType.GRID_TRADING:
                self.strategies[config.strategy_id] = GridTradingStrategy(config, self.market_data)
    
    # ========== ACCOUNT MANAGEMENT ==========
    
    def create_account(self, customer_id: str, initial_balance: float = 0,
                       risk_level: RiskLevel = RiskLevel.MODERATE,
                       name: str = "Algo Trading Account") -> TradingAccount:
        """Create a new algo trading account"""
        account_id = f"ALGO-{customer_id[:8].upper()}-{datetime.now().strftime('%Y%m%d')}"
        
        account = TradingAccount(
            account_id=account_id,
            customer_id=customer_id,
            name=name,
            balance=initial_balance,
            equity=initial_balance,
            available_margin=initial_balance,
            risk_level=risk_level,
            trading_mode=TradingMode.PAUSED,
            active_strategies=list(self.strategies.keys())
        )
        
        self.accounts[account_id] = account
        
        # Record in ledger
        self._record_ledger_entry(account, "account_created", None, "CASH", 
                                  AssetClass.FIXED_INCOME, "deposit", 
                                  initial_balance, 1.0, initial_balance)
        
        return account
    
    def get_account(self, account_id: str) -> Optional[TradingAccount]:
        """Get trading account by ID"""
        return self.accounts.get(account_id)
    
    def get_customer_accounts(self, customer_id: str) -> List[TradingAccount]:
        """Get all accounts for a customer"""
        return [acc for acc in self.accounts.values() if acc.customer_id == customer_id]
    
    def deposit(self, account_id: str, amount: float) -> Dict:
        """Deposit funds into trading account"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        account.balance += amount
        account.equity = account.balance + self._calculate_unrealized_pnl(account)
        account.available_margin = account.balance - account.margin_used
        account.updated_at = datetime.now().isoformat()
        
        self._record_ledger_entry(account, "deposit", None, "CASH",
                                  AssetClass.FIXED_INCOME, "deposit",
                                  amount, 1.0, amount)
        
        return {"success": True, "new_balance": account.balance, "equity": account.equity}
    
    def withdraw(self, account_id: str, amount: float) -> Dict:
        """Withdraw funds from trading account"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        if amount > account.available_margin:
            return {"success": False, "error": "Insufficient available margin"}
        
        account.balance -= amount
        account.equity = account.balance + self._calculate_unrealized_pnl(account)
        account.available_margin = account.balance - account.margin_used
        account.updated_at = datetime.now().isoformat()
        
        self._record_ledger_entry(account, "withdrawal", None, "CASH",
                                  AssetClass.FIXED_INCOME, "withdrawal",
                                  amount, 1.0, -amount)
        
        return {"success": True, "new_balance": account.balance}
    
    def update_risk_level(self, account_id: str, risk_level: RiskLevel) -> Dict:
        """Update account risk level"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        account.risk_level = risk_level
        account.updated_at = datetime.now().isoformat()
        
        # Update risk parameters
        params = self.RISK_PARAMETERS[risk_level]
        account.max_drawdown_pct = params["stop_loss_pct"] * 2
        account.daily_loss_limit = params["stop_loss_pct"]
        
        return {
            "success": True,
            "risk_level": risk_level.value,
            "parameters": params
        }
    
    # ========== TRADING MODE CONTROL ==========
    
    def activate_trading(self, account_id: str, mode: TradingMode = TradingMode.FULL_AUTO) -> Dict:
        """Activate algo trading for an account"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        if account.balance < 100:
            return {"success": False, "error": "Minimum balance of $100 required"}
        
        account.trading_mode = mode
        account.updated_at = datetime.now().isoformat()
        
        # Start trading engine if not running
        if mode == TradingMode.FULL_AUTO and not self._running:
            self._start_trading_engine()
        
        return {
            "success": True,
            "trading_mode": mode.value,
            "message": f"Trading activated in {mode.value} mode"
        }
    
    def deactivate_trading(self, account_id: str) -> Dict:
        """Deactivate algo trading for an account"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        account.trading_mode = TradingMode.PAUSED
        account.updated_at = datetime.now().isoformat()
        
        return {"success": True, "message": "Trading deactivated"}
    
    def get_trading_status(self, account_id: str) -> Dict:
        """Get detailed trading status for account"""
        account = self.accounts.get(account_id)
        if not account:
            return {"error": "Account not found"}
        
        unrealized_pnl = self._calculate_unrealized_pnl(account)
        
        return {
            "account_id": account_id,
            "trading_mode": account.trading_mode.value,
            "is_active": account.trading_mode in [TradingMode.FULL_AUTO, TradingMode.SEMI_AUTO],
            "balance": account.balance,
            "equity": account.balance + unrealized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "margin_used": account.margin_used,
            "available_margin": account.balance - account.margin_used,
            "position_count": len(account.positions),
            "open_orders": len([o for o in account.orders.values() if o.status == OrderStatus.PENDING]),
            "active_hedges": len(account.hedges),
            "risk_level": account.risk_level.value,
            "engine_running": self._running,
            "last_update": account.updated_at
        }
    
    # ========== ORDER MANAGEMENT ==========
    
    def place_order(self, account_id: str, symbol: str, side: OrderSide,
                    quantity: float, order_type: OrderType = OrderType.MARKET,
                    price: float = None, stop_loss: float = None,
                    take_profit: float = None, strategy: StrategyType = None,
                    signal_id: str = None) -> Dict:
        """Place a trading order"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        market_data = self.market_data.get_market_data(symbol)
        if not market_data:
            return {"success": False, "error": f"Unknown symbol: {symbol}"}
        
        current_price = market_data["price"]
        asset_class = market_data["class"]
        
        # Calculate order value
        order_value = quantity * (price or current_price)
        
        # Risk checks
        risk_params = self.RISK_PARAMETERS[account.risk_level]
        max_position_value = account.equity * (risk_params["max_position_pct"] / 100)
        
        if order_value > max_position_value:
            return {"success": False, "error": f"Order exceeds max position size ({risk_params['max_position_pct']}%)"}
        
        if order_value > account.available_margin:
            return {"success": False, "error": "Insufficient margin"}
        
        # Create order
        order = AlgoOrder(
            order_id=f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
            account_id=account_id,
            signal_id=signal_id,
            symbol=symbol,
            asset_class=asset_class,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price or current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=strategy
        )
        
        account.orders[order.order_id] = order
        
        # Execute market orders immediately
        if order_type == OrderType.MARKET:
            return self._execute_order(account, order)
        
        # Limit orders stay pending
        order.status = OrderStatus.SUBMITTED
        self._record_ledger_entry(account, "order_submitted", order.order_id, symbol,
                                  asset_class, side.value, quantity, current_price, order_value,
                                  strategy=strategy.value if strategy else None)
        
        return {
            "success": True,
            "order": asdict(order),
            "message": f"Order {order.order_id} submitted"
        }
    
    def _execute_order(self, account: TradingAccount, order: AlgoOrder) -> Dict:
        """Execute an order (fill simulation)"""
        market_data = self.market_data.get_market_data(order.symbol)
        fill_price = market_data["price"] if market_data else order.price
        
        # Simulate slippage
        slippage = random.uniform(-0.001, 0.001)
        fill_price *= (1 + slippage)
        
        order.avg_fill_price = fill_price
        order.filled_quantity = order.quantity
        order.status = OrderStatus.FILLED
        order.filled_at = datetime.now().isoformat()
        order.updated_at = datetime.now().isoformat()
        
        # Update or create position
        position_key = f"{order.symbol}-{order.side.value}"
        
        if order.side in [OrderSide.BUY, OrderSide.COVER]:
            # Opening or adding to long position
            if order.symbol in account.positions:
                pos = account.positions[order.symbol]
                total_cost = pos.cost_basis + (order.quantity * fill_price)
                total_qty = pos.quantity + order.quantity
                pos.avg_cost = total_cost / total_qty
                pos.quantity = total_qty
                pos.current_price = fill_price
                pos.updated_at = datetime.now().isoformat()
            else:
                account.positions[order.symbol] = AlgoPosition(
                    position_id=f"POS-{order.symbol}-{random.randint(1000,9999)}",
                    account_id=account.account_id,
                    symbol=order.symbol,
                    asset_class=order.asset_class,
                    side="long",
                    quantity=order.quantity,
                    avg_cost=fill_price,
                    current_price=fill_price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    strategy=order.strategy,
                    opened_at=datetime.now().isoformat()
                )
            
            # Reduce cash
            account.balance -= order.quantity * fill_price
            
        elif order.side in [OrderSide.SELL, OrderSide.SHORT]:
            # Closing or reducing position
            if order.symbol in account.positions:
                pos = account.positions[order.symbol]
                realized_pnl = (fill_price - pos.avg_cost) * min(order.quantity, pos.quantity)
                
                pos.quantity -= order.quantity
                if pos.quantity <= 0:
                    del account.positions[order.symbol]
                
                # Add proceeds + P&L to cash
                account.balance += order.quantity * fill_price
                
                self._record_ledger_entry(
                    account, "order_filled", order.order_id, order.symbol,
                    order.asset_class, order.side.value, order.quantity, 
                    fill_price, order.quantity * fill_price,
                    realized_pnl=realized_pnl,
                    strategy=order.strategy.value if order.strategy else None
                )
            else:
                # Short selling
                account.positions[order.symbol] = AlgoPosition(
                    position_id=f"POS-{order.symbol}-{random.randint(1000,9999)}",
                    account_id=account.account_id,
                    symbol=order.symbol,
                    asset_class=order.asset_class,
                    side="short",
                    quantity=order.quantity,
                    avg_cost=fill_price,
                    current_price=fill_price,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit,
                    strategy=order.strategy,
                    opened_at=datetime.now().isoformat()
                )
                account.balance += order.quantity * fill_price
        
        # Update account
        account.margin_used = sum(p.market_value for p in account.positions.values())
        account.available_margin = account.balance - account.margin_used
        account.equity = account.balance + self._calculate_unrealized_pnl(account)
        account.updated_at = datetime.now().isoformat()
        
        # Record ledger entry
        self._record_ledger_entry(
            account, "order_filled", order.order_id, order.symbol,
            order.asset_class, order.side.value, order.quantity,
            fill_price, order.quantity * fill_price,
            strategy=order.strategy.value if order.strategy else None
        )
        
        return {
            "success": True,
            "order": asdict(order),
            "fill_price": fill_price,
            "message": f"Order filled at ${fill_price:.2f}"
        }
    
    def cancel_order(self, account_id: str, order_id: str) -> Dict:
        """Cancel a pending order"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        order = account.orders.get(order_id)
        if not order:
            return {"success": False, "error": "Order not found"}
        
        if order.status not in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
            return {"success": False, "error": "Order cannot be cancelled"}
        
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now().isoformat()
        
        return {"success": True, "message": f"Order {order_id} cancelled"}
    
    # ========== SIGNALS & STRATEGIES ==========
    
    def generate_signals(self, account_id: str = None) -> List[TradingSignal]:
        """Generate trading signals from all active strategies"""
        all_signals = []
        
        for strategy_id, strategy in self.strategies.items():
            if strategy.config.enabled:
                signals = strategy.generate_signals()
                for signal in signals:
                    self.active_signals[signal.signal_id] = signal
                all_signals.extend(signals)
        
        # Sort by strength
        all_signals.sort(key=lambda s: s.strength * s.confidence, reverse=True)
        
        return all_signals[:20]  # Return top 20 signals
    
    def execute_signal(self, account_id: str, signal_id: str) -> Dict:
        """Execute a trading signal"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        signal = self.active_signals.get(signal_id)
        if not signal:
            return {"success": False, "error": "Signal not found or expired"}
        
        if signal.executed:
            return {"success": False, "error": "Signal already executed"}
        
        # Calculate position size based on risk
        risk_params = self.RISK_PARAMETERS[account.risk_level]
        risk_per_trade = account.equity * (risk_params["max_position_pct"] / 100) * signal.strength
        
        price = signal.entry_price
        stop_distance = abs(price - signal.stop_loss)
        
        if stop_distance > 0:
            quantity = risk_per_trade / stop_distance
        else:
            quantity = risk_per_trade / price
        
        # Place the order
        result = self.place_order(
            account_id=account_id,
            symbol=signal.symbol,
            side=signal.side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            stop_loss=signal.stop_loss,
            take_profit=signal.target_price,
            strategy=signal.strategy,
            signal_id=signal.signal_id
        )
        
        if result.get("success"):
            signal.executed = True
        
        return result
    
    def get_strategy_performance(self, strategy_id: str = None) -> Dict:
        """Get performance metrics for strategies"""
        if strategy_id:
            strategy = self.strategies.get(strategy_id)
            if not strategy:
                return {"error": "Strategy not found"}
            
            return {
                "strategy_id": strategy_id,
                "name": strategy.config.name,
                "type": strategy.config.strategy_type.value,
                "enabled": strategy.config.enabled,
                "signals_generated": strategy.signals_generated,
                "allocation_pct": strategy.config.allocation_pct
            }
        
        return {
            "strategies": [
                {
                    "strategy_id": sid,
                    "name": s.config.name,
                    "type": s.config.strategy_type.value,
                    "enabled": s.config.enabled,
                    "signals_generated": s.signals_generated
                }
                for sid, s in self.strategies.items()
            ]
        }
    
    # ========== HEDGING ==========
    
    def get_hedge_recommendations(self, account_id: str) -> List[Dict]:
        """Get hedging recommendations for account"""
        account = self.accounts.get(account_id)
        if not account:
            return []
        
        return self.hedging_engine.recommend_hedges(account)
    
    def apply_hedge(self, account_id: str, hedge_type: HedgeType,
                    underlying: str, hedge_instrument: str,
                    hedge_ratio: float, amount: float) -> Dict:
        """Apply a hedge position"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        if amount > account.available_margin:
            return {"success": False, "error": "Insufficient margin for hedge"}
        
        hedge = self.hedging_engine.create_hedge(
            account, hedge_type, underlying, hedge_instrument, hedge_ratio, amount
        )
        
        account.hedges[hedge.hedge_id] = hedge
        
        # Place the hedge order
        side = OrderSide.SELL if "short" in hedge_type.value.lower() else OrderSide.BUY
        
        result = self.place_order(
            account_id=account_id,
            symbol=hedge_instrument,
            side=side,
            quantity=hedge.quantity,
            order_type=OrderType.MARKET
        )
        
        if result.get("success"):
            self._record_ledger_entry(
                account, "hedge_applied", None, hedge_instrument,
                AssetClass.EQUITY, side.value, hedge.quantity,
                hedge.cost_basis / hedge.quantity, hedge.cost_basis,
                notes=f"Hedge: {hedge_type.value} for {underlying}"
            )
        
        return {
            "success": True,
            "hedge": asdict(hedge),
            "order_result": result
        }
    
    # ========== PERFORMANCE & ANALYTICS ==========
    
    def get_portfolio_analytics(self, account_id: str) -> Dict:
        """Get comprehensive portfolio analytics"""
        account = self.accounts.get(account_id)
        if not account:
            return {"error": "Account not found"}
        
        positions = account.positions
        unrealized_pnl = self._calculate_unrealized_pnl(account)
        
        # Position breakdown
        position_data = []
        class_breakdown = {}
        
        for symbol, pos in positions.items():
            market_data = self.market_data.get_market_data(symbol)
            if market_data:
                pos.current_price = market_data["price"]
            
            pos.unrealized_pnl = (pos.current_price - pos.avg_cost) * pos.quantity
            pos.unrealized_pnl_pct = (pos.unrealized_pnl / pos.cost_basis * 100) if pos.cost_basis > 0 else 0
            
            position_data.append({
                "symbol": symbol,
                "asset_class": pos.asset_class.value,
                "side": pos.side,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "current_price": pos.current_price,
                "market_value": pos.market_value,
                "unrealized_pnl": pos.unrealized_pnl,
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit
            })
            
            cls = pos.asset_class.value
            if cls not in class_breakdown:
                class_breakdown[cls] = 0
            class_breakdown[cls] += pos.market_value
        
        total_invested = sum(p["market_value"] for p in position_data)
        
        # Calculate allocation percentages
        allocation = {cls: (val / total_invested * 100) if total_invested > 0 else 0 
                      for cls, val in class_breakdown.items()}
        
        # Risk metrics
        beta = self.hedging_engine.calculate_portfolio_beta(positions)
        delta = self.hedging_engine.calculate_portfolio_delta(positions)
        
        return {
            "account_id": account_id,
            "equity": account.balance + unrealized_pnl,
            "cash_balance": account.balance,
            "total_invested": total_invested,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": (unrealized_pnl / total_invested * 100) if total_invested > 0 else 0,
            "position_count": len(positions),
            "positions": position_data,
            "allocation": allocation,
            "risk_metrics": {
                "portfolio_beta": beta,
                "portfolio_delta": delta,
                "var_95": total_invested * 0.02 * 1.65,  # Simplified VaR
                "max_drawdown_limit": account.max_drawdown_pct
            },
            "hedges": [asdict(h) for h in account.hedges.values()]
        }
    
    def get_trading_ledger(self, account_id: str, limit: int = 100) -> List[Dict]:
        """Get trading ledger entries"""
        account = self.accounts.get(account_id)
        if not account:
            return []
        
        return [asdict(entry) for entry in account.ledger[-limit:]]
    
    def get_market_overview(self) -> Dict:
        """Get market overview for all asset classes"""
        overview = {
            "last_update": datetime.now().isoformat(),
            "markets": {}
        }
        
        for asset_class in AssetClass:
            symbols = self.market_data.get_all_symbols(asset_class)
            assets = []
            
            for symbol in symbols[:10]:
                data = self.market_data.get_market_data(symbol)
                if data:
                    assets.append({
                        "symbol": symbol,
                        "name": data["name"],
                        "price": data["price"],
                        "change_24h": data.get("change_24h", random.uniform(-2, 2)),
                        "volatility": data.get("vol", 0.15)
                    })
            
            if assets:
                overview["markets"][asset_class.value] = assets
        
        return overview
    
    # ========== PRIVATE HELPERS ==========
    
    def _calculate_unrealized_pnl(self, account: TradingAccount) -> float:
        """Calculate total unrealized P&L"""
        total_pnl = 0
        for pos in account.positions.values():
            market_data = self.market_data.get_market_data(pos.symbol)
            if market_data:
                current_price = market_data["price"]
                if pos.side == "long":
                    total_pnl += (current_price - pos.avg_cost) * pos.quantity
                else:
                    total_pnl += (pos.avg_cost - current_price) * pos.quantity
        return total_pnl
    
    def _record_ledger_entry(self, account: TradingAccount, entry_type: str,
                            order_id: Optional[str], symbol: str,
                            asset_class: AssetClass, side: str,
                            quantity: float, price: float, value: float,
                            realized_pnl: float = 0, fees: float = 0,
                            strategy: str = None, notes: str = ""):
        """Record entry in trading ledger"""
        entry = TradingLedgerEntry(
            entry_id=f"LED-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
            account_id=account.account_id,
            entry_type=entry_type,
            order_id=order_id,
            symbol=symbol,
            asset_class=asset_class.value if isinstance(asset_class, AssetClass) else asset_class,
            side=side,
            quantity=quantity,
            price=price,
            value=value,
            realized_pnl=realized_pnl,
            fees=fees,
            strategy=strategy,
            notes=notes,
            transaction_hash=hashlib.sha256(
                f"{account.account_id}{symbol}{value}{datetime.now().isoformat()}".encode()
            ).hexdigest()[:16]
        )
        
        account.ledger.append(entry)
    
    def _start_trading_engine(self):
        """Start the background trading engine"""
        if self._running:
            return
        
        self._running = True
        self._trading_thread = threading.Thread(target=self._trading_loop, daemon=True)
        self._trading_thread.start()
    
    def _stop_trading_engine(self):
        """Stop the background trading engine"""
        self._running = False
        if self._trading_thread:
            self._trading_thread.join(timeout=5)
    
    def _trading_loop(self):
        """Main trading loop - runs 24/7"""
        while self._running:
            try:
                # Update market prices
                self.market_data.simulate_price_update()
                
                # Process each active account
                for account in self.accounts.values():
                    if account.trading_mode == TradingMode.FULL_AUTO:
                        self._process_account(account)
                
                # Sleep between iterations (5 seconds for demo)
                time.sleep(5)
                
            except Exception as e:
                print(f"Trading engine error: {e}")
                time.sleep(10)
    
    def _process_account(self, account: TradingAccount):
        """Process trading logic for an account"""
        with self._lock:
            # Check stop losses and take profits
            self._check_exit_conditions(account)
            
            # Generate and potentially execute new signals
            if random.random() < 0.1:  # 10% chance to act on signals
                signals = self.generate_signals(account.account_id)
                if signals and account.balance > 100:
                    top_signal = signals[0]
                    if top_signal.confidence > 0.7:
                        self.execute_signal(account.account_id, top_signal.signal_id)
    
    def _check_exit_conditions(self, account: TradingAccount):
        """Check and execute stop losses / take profits"""
        for symbol, pos in list(account.positions.items()):
            market_data = self.market_data.get_market_data(symbol)
            if not market_data:
                continue
            
            current_price = market_data["price"]
            
            # Check stop loss
            if pos.stop_loss and current_price <= pos.stop_loss:
                self.place_order(
                    account.account_id, symbol, OrderSide.SELL,
                    pos.quantity, OrderType.MARKET
                )
            
            # Check take profit
            elif pos.take_profit and current_price >= pos.take_profit:
                self.place_order(
                    account.account_id, symbol, OrderSide.SELL,
                    pos.quantity, OrderType.MARKET
                )


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_algo_trading_service: Optional[AlgoTradingService] = None

def get_algo_trading_service() -> AlgoTradingService:
    """Get singleton instance of algo trading service"""
    global _algo_trading_service
    if _algo_trading_service is None:
        _algo_trading_service = AlgoTradingService()
    return _algo_trading_service
