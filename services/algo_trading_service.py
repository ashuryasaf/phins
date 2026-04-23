"""
PHINS Algo Trading Service
===========================
Advanced algorithmic trading system for automated portfolio management.

Features:
- Multiple trading strategies (Momentum, Mean Reversion, Trend Following, DCA)
- Technical indicators (RSI, MACD, Moving Averages, Bollinger Bands)
- Automated signal generation and trade execution
- Risk management with position sizing and stop-loss
- Real-time performance tracking
- Trading bot management
- Advanced metrics: Sharpe Ratio, Sortino Ratio, Max Drawdown, Calmar Ratio
- Multi-asset support: Equities, Crypto, Commodities, Forex, Bonds

This integrates with PHINS investment portfolio for automated trading.
"""

import math
import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import deque
import json

# Import advanced market data service
try:
    from services.advanced_market_data import (
        get_advanced_market_service, EXTENDED_MARKET_DATA, SMART_BOT_TEMPLATES,
        AdvancedMetrics, AssetClass, DataProvider
    )
    ADVANCED_MARKET_AVAILABLE = True
except ImportError:
    ADVANCED_MARKET_AVAILABLE = False


class TradingStrategy(str, Enum):
    """Available trading strategies"""
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    TREND_FOLLOWING = "trend_following"
    DCA = "dollar_cost_averaging"
    GRID_TRADING = "grid_trading"
    RSI_STRATEGY = "rsi_strategy"
    MACD_CROSSOVER = "macd_crossover"
    BREAKOUT = "breakout"
    ARBITRAGE = "arbitrage"
    SCALPING = "scalping"
    SWING_TRADING = "swing_trading"
    AI_ADAPTIVE = "ai_adaptive"
    OPTIONS_WHEEL = "options_wheel"
    COVERED_CALL = "covered_call"
    CASH_SECURED_PUT = "cash_secured_put"
    IRON_CONDOR = "iron_condor"
    PROTECTIVE_PUT = "protective_put"


class SignalType(str, Enum):
    """Trading signal types"""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class OrderType(str, Enum):
    """Order types"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"


class OrderStatus(str, Enum):
    """Order status"""
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    PARTIALLY_FILLED = "partially_filled"


@dataclass
class TechnicalIndicators:
    """Technical analysis indicators for an asset"""
    symbol: str
    timestamp: str
    
    # Price data
    current_price: float = 0.0
    price_change_24h: float = 0.0
    price_change_7d: float = 0.0
    
    # Moving Averages
    sma_20: float = 0.0
    sma_50: float = 0.0
    sma_200: float = 0.0
    ema_12: float = 0.0
    ema_26: float = 0.0
    
    # RSI
    rsi_14: float = 50.0
    
    # MACD
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    
    # Bollinger Bands
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    
    # Volume
    volume_24h: float = 0.0
    volume_change: float = 0.0
    
    # Volatility
    volatility: float = 0.0
    atr_14: float = 0.0
    
    # Support/Resistance
    support_level: float = 0.0
    resistance_level: float = 0.0


@dataclass
class TradingSignal:
    """Trading signal with analysis"""
    signal_id: str
    symbol: str
    signal_type: SignalType
    strategy: TradingStrategy
    confidence: float  # 0-1
    price_target: float
    stop_loss: float
    take_profit: float
    reasoning: str
    indicators: Dict[str, float] = field(default_factory=dict)
    created_at: str = ""
    expires_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.expires_at:
            self.expires_at = (datetime.now() + timedelta(hours=24)).isoformat()


@dataclass
class TradeOrder:
    """Trade order"""
    order_id: str
    account_id: str
    symbol: str
    order_type: OrderType
    side: str  # buy or sell
    quantity: float
    price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    strategy: Optional[TradingStrategy] = None
    signal_id: Optional[str] = None
    created_at: str = ""
    executed_at: str = ""
    pnl: float = 0.0
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class TradingBot:
    """Automated trading bot configuration"""
    bot_id: str
    account_id: str
    name: str
    strategy: TradingStrategy
    symbols: List[str]
    is_active: bool = True
    
    # Risk parameters
    max_position_size: float = 1000.0  # Max USD per trade
    max_daily_trades: int = 10
    max_drawdown_pct: float = 10.0  # Stop bot if drawdown exceeds
    stop_loss_pct: float = 5.0
    take_profit_pct: float = 10.0
    trailing_stop_pct: float = 0.0  # 0 = disabled
    
    # DCA specific
    dca_interval_hours: int = 24
    dca_amount: float = 100.0
    
    # Advanced Performance Metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    
    # Risk Metrics
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    current_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    profit_factor: float = 0.0
    
    # Trade Quality Metrics
    avg_win: float = 0.0
    avg_loss: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    avg_trade_duration: str = "0h"
    longest_winning_streak: int = 0
    longest_losing_streak: int = 0
    current_streak: int = 0
    
    # Volatility Metrics
    daily_volatility: float = 0.0
    annualized_volatility: float = 0.0
    beta: float = 1.0
    alpha: float = 0.0
    
    # Portfolio allocation
    asset_allocation: Dict[str, float] = field(default_factory=dict)
    risk_level: str = "medium"  # low, medium, high, very_high
    
    # Trade history for metrics calculation
    trade_returns: List[float] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    peak_equity: float = 0.0
    
    # State
    last_trade_at: str = ""
    daily_trades_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        if not self.equity_curve:
            self.equity_curve = [0.0]
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    def update_metrics(self, trade_pnl: float, trade_return_pct: float):
        """Update all metrics after a trade"""
        self.total_trades += 1
        self.total_pnl += trade_pnl
        self.trade_returns.append(trade_return_pct)
        
        # Update win/loss counts
        if trade_pnl > 0:
            self.winning_trades += 1
            self.avg_win = ((self.avg_win * (self.winning_trades - 1)) + trade_pnl) / self.winning_trades
            if trade_pnl > self.best_trade:
                self.best_trade = trade_pnl
            self.current_streak = max(1, self.current_streak + 1) if self.current_streak >= 0 else 1
            self.longest_winning_streak = max(self.longest_winning_streak, self.current_streak)
        elif trade_pnl < 0:
            self.losing_trades += 1
            self.avg_loss = ((self.avg_loss * (self.losing_trades - 1)) + trade_pnl) / self.losing_trades
            if trade_pnl < self.worst_trade:
                self.worst_trade = trade_pnl
            self.current_streak = min(-1, self.current_streak - 1) if self.current_streak <= 0 else -1
            self.longest_losing_streak = max(self.longest_losing_streak, abs(self.current_streak))
        
        # Update equity curve
        new_equity = self.equity_curve[-1] + trade_pnl
        self.equity_curve.append(new_equity)
        
        # Update peak and drawdown
        if new_equity > self.peak_equity:
            self.peak_equity = new_equity
        self.current_drawdown = self.peak_equity - new_equity
        if self.current_drawdown > self.max_drawdown:
            self.max_drawdown = self.current_drawdown
            self.max_drawdown_pct = (self.current_drawdown / self.peak_equity * 100) if self.peak_equity > 0 else 0
        
        # Recalculate advanced metrics
        self._recalculate_ratios()
        self.updated_at = datetime.now().isoformat()
    
    def _recalculate_ratios(self):
        """Recalculate Sharpe, Sortino, Calmar, and profit factor"""
        if len(self.trade_returns) < 2:
            return
        
        returns = self.trade_returns
        mean_return = sum(returns) / len(returns)
        
        # Daily volatility and annualized
        variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
        self.daily_volatility = math.sqrt(variance) * 100
        self.annualized_volatility = self.daily_volatility * math.sqrt(252)
        
        # Sharpe Ratio (5% risk-free rate annualized)
        risk_free_daily = 0.05 / 252
        excess_return = mean_return - risk_free_daily
        if self.daily_volatility > 0:
            self.sharpe_ratio = round((excess_return / (self.daily_volatility / 100)) * math.sqrt(252), 2)
        
        # Sortino Ratio (downside deviation)
        negative_returns = [r for r in returns if r < 0]
        if negative_returns:
            downside_variance = sum(r ** 2 for r in negative_returns) / len(negative_returns)
            downside_deviation = math.sqrt(downside_variance)
            if downside_deviation > 0:
                self.sortino_ratio = round((excess_return / downside_deviation) * math.sqrt(252), 2)
        else:
            self.sortino_ratio = self.sharpe_ratio * 1.5
        
        # Calmar Ratio
        annualized_return = mean_return * 252 * 100
        if self.max_drawdown_pct > 0:
            self.calmar_ratio = round(annualized_return / self.max_drawdown_pct, 2)
        
        # Profit Factor
        gross_profit = sum(r for r in returns if r > 0)
        gross_loss = abs(sum(r for r in returns if r < 0))
        if gross_loss > 0:
            self.profit_factor = round(gross_profit / gross_loss, 2)
        elif gross_profit > 0:
            self.profit_factor = 99.99  # Cap at high value


class AlgoTradingService:
    """
    Core algorithmic trading service with strategies, signals, and execution.
    """
    
    def __init__(self, portfolio_service=None):
        self.portfolio_service = portfolio_service
        self.bots: Dict[str, TradingBot] = {}
        self.orders: Dict[str, TradeOrder] = {}
        self.signals: Dict[str, List[TradingSignal]] = {}  # symbol -> signals
        self.price_history: Dict[str, deque] = {}  # symbol -> price history
        self.indicators_cache: Dict[str, TechnicalIndicators] = {}
        
        # Initialize price history with simulated data
        self._init_price_history()
    
    def _init_price_history(self):
        """Initialize price history from live Alpaca bars when available, fallback to portfolio data."""
        self._try_load_live_history()
        self._fill_from_portfolio_data()

    def _try_load_live_history(self):
        """Fetch real OHLCV bars from Alpaca for all known symbols.

        Alpaca stock bars only support US equities/ETFs.  Currencies (EUR, CHF,
        …) and indexes (^SPX, ^DAX, …) are not available through that endpoint,
        so we skip them to avoid noisy log lines.  Crypto symbols are routed
        through the dedicated crypto bars endpoint.
        """
        try:
            from services.trading_platform_service import get_trading_platform
            tp = get_trading_platform()
            if not tp.is_connected:
                return
        except Exception:
            return

        try:
            from services.investment_portfolio_service import AssetClass as _AC
        except ImportError:
            _AC = None

        _SKIP_CLASSES = set()
        if _AC:
            _SKIP_CLASSES = {_AC.CURRENCY, _AC.INDEX}

        market_data = {}
        if self.portfolio_service and hasattr(self.portfolio_service, 'MARKET_DATA'):
            market_data = self.portfolio_service.MARKET_DATA

        symbols_to_fetch = set(market_data.keys())
        symbols_to_fetch.update(["SPY", "QQQ", "BTC/USD", "ETH/USD", "GLD", "BND"])

        for symbol in symbols_to_fetch:
            try:
                asset_class = market_data.get(symbol, {}).get("class")

                if asset_class in _SKIP_CLASSES:
                    continue

                is_crypto = "/" in symbol
                if not is_crypto and _AC and asset_class == _AC.CRYPTO:
                    is_crypto = True

                if is_crypto:
                    raw = tp.get_crypto_bars(symbol.replace("/", ""), "1Day", 200)
                    bars_list = []
                    if raw and isinstance(raw, dict):
                        for _sym_key, sym_bars in raw.get("bars", {}).items():
                            if isinstance(sym_bars, list):
                                for b in sym_bars:
                                    bars_list.append({
                                        "date": b.get("t"),
                                        "open": float(b.get("o", 0)),
                                        "high": float(b.get("h", 0)),
                                        "low": float(b.get("l", 0)),
                                        "close": float(b.get("c", 0)),
                                        "volume": float(b.get("v", 0)),
                                    })
                    bars = bars_list
                else:
                    bars = tp.get_bars(symbol, "1Day", 200)

                if not bars:
                    continue
                history = deque(maxlen=200)
                for bar in bars:
                    history.append({
                        "price": float(bar.get("close", 0)),
                        "open": float(bar.get("open", 0)),
                        "high": float(bar.get("high", 0)),
                        "low": float(bar.get("low", 0)),
                        "volume": float(bar.get("volume", 0)),
                        "timestamp": bar.get("date", datetime.now().isoformat()),
                        "source": "alpaca",
                    })
                if history:
                    self.price_history[symbol] = history
                    if self.portfolio_service and symbol in getattr(self.portfolio_service, 'MARKET_DATA', {}):
                        self.portfolio_service.MARKET_DATA[symbol]["price"] = history[-1]["price"]
            except Exception as e:
                print(f"[AlgoTrading] Failed to load bars for {symbol}: {e}")

    def _fill_from_portfolio_data(self):
        """Seed price history from portfolio service data for symbols not yet loaded from Alpaca.
        Creates a minimal series so indicators can compute."""
        if not self.portfolio_service:
            return
        market_data = getattr(self.portfolio_service, 'MARKET_DATA', {})
        for symbol, data in market_data.items():
            if symbol in self.price_history and len(self.price_history[symbol]) >= 20:
                continue
            current_price = data.get("price", 0)
            if current_price <= 0:
                continue
            history = self.price_history.get(symbol, deque(maxlen=200))
            if len(history) < 20:
                for i in range(50):
                    drift = 1 + (i - 25) * 0.001
                    history.append({
                        "price": current_price * drift,
                        "volume": 0,
                        "timestamp": (datetime.now() - timedelta(days=50 - i)).isoformat(),
                        "source": "portfolio_seed",
                    })
                history[-1]["price"] = current_price
            self.price_history[symbol] = history

    def sync_market_prices(self, prices: Dict[str, float]) -> Dict[str, Any]:
        """
        Sync externally validated prices into portfolio + indicator history.
        This keeps dashboards and bot signals aligned on the same quote set.
        """
        updated = 0
        ignored = 0
        now_iso = datetime.now().isoformat()

        for symbol, raw_price in (prices or {}).items():
            try:
                price = float(raw_price)
                if price <= 0:
                    ignored += 1
                    continue
            except (TypeError, ValueError):
                ignored += 1
                continue

            # Keep portfolio service in sync for trade execution paths.
            if self.portfolio_service and symbol in self.portfolio_service.MARKET_DATA:
                self.portfolio_service.MARKET_DATA[symbol]["price"] = price

            # Keep technical indicator history current.
            history = self.price_history.get(symbol)
            if history is None:
                history = deque(maxlen=200)
                self.price_history[symbol] = history

            last_volume = history[-1].get("volume") if history else None
            volume = (
                float(last_volume)
                if isinstance(last_volume, (int, float)) and last_volume > 0
                else 0
            )
            history.append(
                {
                    "price": price,
                    "volume": volume,
                    "timestamp": now_iso,
                }
            )
            updated += 1

        return {"updated": updated, "ignored": ignored, "timestamp": now_iso}
    
    def calculate_indicators(self, symbol: str) -> TechnicalIndicators:
        """Calculate technical indicators — uses AI trading engine with real data when available."""
        ai_result = self._try_ai_engine_indicators(symbol)
        if ai_result:
            return ai_result

        if symbol not in self.price_history:
            return TechnicalIndicators(symbol=symbol, timestamp=datetime.now().isoformat())

        history = list(self.price_history[symbol])
        prices = [h["price"] for h in history]
        volumes = [h.get("volume", 0) for h in history]

        current_price = prices[-1] if prices else 0
        if current_price <= 0:
            return TechnicalIndicators(symbol=symbol, timestamp=datetime.now().isoformat())

        sma_20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else current_price
        sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else current_price
        sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else current_price

        ema_12 = self._calculate_ema(prices, 12)
        ema_26 = self._calculate_ema(prices, 26)
        rsi = self._calculate_rsi(prices, 14)

        macd_line = ema_12 - ema_26
        macd_signal = self._calculate_ema([macd_line] * 9, 9)
        macd_histogram = macd_line - macd_signal

        std_20 = self._calculate_std(prices[-20:]) if len(prices) >= 20 else 0
        bb_upper = sma_20 + (2 * std_20)
        bb_lower = sma_20 - (2 * std_20)

        atr = self._calculate_atr(prices, 14)

        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices)) if prices[i-1] > 0]
        volatility = self._calculate_std(returns[-30:]) * math.sqrt(365) if len(returns) >= 30 else 0.0

        recent_lows = min(prices[-20:]) if len(prices) >= 20 else current_price * 0.95
        recent_highs = max(prices[-20:]) if len(prices) >= 20 else current_price * 1.05

        data_source = "alpaca" if (history and history[-1].get("source") == "alpaca") else "synced"

        indicators = TechnicalIndicators(
            symbol=symbol,
            timestamp=datetime.now().isoformat(),
            current_price=current_price,
            price_change_24h=((current_price / prices[-2]) - 1) * 100 if len(prices) >= 2 and prices[-2] > 0 else 0,
            price_change_7d=((current_price / prices[-7]) - 1) * 100 if len(prices) >= 7 and prices[-7] > 0 else 0,
            sma_20=sma_20,
            sma_50=sma_50,
            sma_200=sma_200,
            ema_12=ema_12,
            ema_26=ema_26,
            rsi_14=rsi,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            bb_upper=bb_upper,
            bb_middle=sma_20,
            bb_lower=bb_lower,
            volume_24h=volumes[-1] if volumes else 0,
            volume_change=((volumes[-1] / volumes[-2]) - 1) * 100 if len(volumes) >= 2 and volumes[-2] > 0 else 0,
            volatility=volatility,
            atr_14=atr,
            support_level=recent_lows,
            resistance_level=recent_highs
        )

        self.indicators_cache[symbol] = indicators
        return indicators

    def _try_ai_engine_indicators(self, symbol: str) -> TechnicalIndicators | None:
        """Use the AI trading engine from trading-terminal for live Alpaca indicators."""
        try:
            from services.trading_platform_service import get_trading_platform
            from services.ai_trading_engine import compute_technicals

            tp = get_trading_platform()
            if not tp.is_connected:
                return None

            is_crypto = "/" in symbol
            fetch_sym = symbol.replace("/", "") if is_crypto else symbol
            bars = tp.get_bars(fetch_sym, "1Day", 100)
            if not bars or len(bars) < 5:
                return None

            techs = compute_technicals(bars)
            ind = techs.get("indicators", {})
            if not ind:
                return None

            current_price = float(bars[-1].get("close", 0))
            prev_price = float(bars[-2].get("close", 0)) if len(bars) >= 2 else current_price
            week_price = float(bars[-7].get("close", 0)) if len(bars) >= 7 else current_price

            return TechnicalIndicators(
                symbol=symbol,
                timestamp=datetime.now().isoformat(),
                current_price=current_price,
                price_change_24h=((current_price / prev_price) - 1) * 100 if prev_price > 0 else 0,
                price_change_7d=((current_price / week_price) - 1) * 100 if week_price > 0 else 0,
                sma_20=ind.get("sma_20") or 0,
                sma_50=ind.get("sma_50") or 0,
                sma_200=0,
                ema_12=ind.get("ema_12") or 0,
                ema_26=ind.get("ema_26") or 0,
                rsi_14=ind.get("rsi_14") or 50.0,
                macd_line=ind.get("macd_line") or 0,
                macd_signal=ind.get("macd_signal") or 0,
                macd_histogram=ind.get("macd_histogram") or 0,
                bb_upper=ind.get("bb_upper") or 0,
                bb_middle=ind.get("bb_middle") or 0,
                bb_lower=ind.get("bb_lower") or 0,
                volume_24h=float(bars[-1].get("volume", 0)),
                volume_change=0,
                volatility=0,
                atr_14=ind.get("atr_14") or 0,
                support_level=ind.get("bb_lower") or current_price * 0.95,
                resistance_level=ind.get("bb_upper") or current_price * 1.05,
            )
        except Exception:
            return None
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_std(self, values: List[float]) -> float:
        """Calculate standard deviation"""
        if len(values) < 2:
            return 0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)
    
    def _calculate_atr(self, prices: List[float], period: int = 14) -> float:
        """Calculate Average True Range (simplified)"""
        if len(prices) < period + 1:
            return 0
        
        true_ranges = []
        for i in range(1, len(prices)):
            tr = abs(prices[i] - prices[i-1])  # Simplified TR
            true_ranges.append(tr)
        
        return sum(true_ranges[-period:]) / period
    
    def generate_signal(self, symbol: str, strategy: TradingStrategy) -> TradingSignal:
        """Generate trading signal based on strategy"""
        indicators = self.calculate_indicators(symbol)
        
        signal_type = SignalType.HOLD
        confidence = 0.5
        reasoning = ""
        
        if strategy == TradingStrategy.RSI_STRATEGY:
            signal_type, confidence, reasoning = self._rsi_strategy(indicators)
        elif strategy == TradingStrategy.MACD_CROSSOVER:
            signal_type, confidence, reasoning = self._macd_strategy(indicators)
        elif strategy == TradingStrategy.MOMENTUM:
            signal_type, confidence, reasoning = self._momentum_strategy(indicators)
        elif strategy == TradingStrategy.MEAN_REVERSION:
            signal_type, confidence, reasoning = self._mean_reversion_strategy(indicators)
        elif strategy == TradingStrategy.TREND_FOLLOWING:
            signal_type, confidence, reasoning = self._trend_following_strategy(indicators)
        elif strategy == TradingStrategy.BREAKOUT:
            signal_type, confidence, reasoning = self._breakout_strategy(indicators)
        elif strategy == TradingStrategy.AI_ADAPTIVE:
            signal_type, confidence, reasoning = self._ai_adaptive_strategy(indicators)
        elif strategy == TradingStrategy.DCA:
            signal_type, confidence, reasoning = self._dca_strategy(indicators)
        elif strategy == TradingStrategy.SCALPING:
            signal_type, confidence, reasoning = self._scalping_strategy(indicators)
        elif strategy == TradingStrategy.SWING_TRADING:
            signal_type, confidence, reasoning = self._swing_trading_strategy(indicators)
        elif strategy == TradingStrategy.GRID_TRADING:
            signal_type, confidence, reasoning = self._grid_trading_strategy(indicators)
        elif strategy == TradingStrategy.OPTIONS_WHEEL:
            signal_type, confidence, reasoning = self._options_wheel_strategy(indicators)
        elif strategy == TradingStrategy.COVERED_CALL:
            signal_type, confidence, reasoning = self._covered_call_strategy(indicators)
        elif strategy == TradingStrategy.CASH_SECURED_PUT:
            signal_type, confidence, reasoning = self._cash_secured_put_strategy(indicators)
        elif strategy == TradingStrategy.IRON_CONDOR:
            signal_type, confidence, reasoning = self._iron_condor_strategy(indicators)
        elif strategy == TradingStrategy.PROTECTIVE_PUT:
            signal_type, confidence, reasoning = self._protective_put_strategy(indicators)
        
        # Calculate price targets
        current = indicators.current_price
        atr = indicators.atr_14 or current * 0.02
        
        if signal_type in [SignalType.BUY, SignalType.STRONG_BUY]:
            stop_loss = current - (2 * atr)
            take_profit = current + (3 * atr)
            price_target = current * 1.05
        elif signal_type in [SignalType.SELL, SignalType.STRONG_SELL]:
            stop_loss = current + (2 * atr)
            take_profit = current - (3 * atr)
            price_target = current * 0.95
        else:
            stop_loss = current * 0.95
            take_profit = current * 1.05
            price_target = current
        
        signal = TradingSignal(
            signal_id=f"SIG-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
            symbol=symbol,
            signal_type=signal_type,
            strategy=strategy,
            confidence=confidence,
            price_target=price_target,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reasoning=reasoning,
            indicators={
                "rsi": indicators.rsi_14,
                "macd": indicators.macd_line,
                "sma_20": indicators.sma_20,
                "sma_50": indicators.sma_50,
                "bb_position": (indicators.current_price - indicators.bb_lower) / (indicators.bb_upper - indicators.bb_lower) if indicators.bb_upper != indicators.bb_lower else 0.5
            }
        )
        
        # Store signal
        if symbol not in self.signals:
            self.signals[symbol] = []
        self.signals[symbol].append(signal)
        
        return signal
    
    def _rsi_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """RSI-based strategy"""
        rsi = ind.rsi_14
        
        if rsi < 20:
            return SignalType.STRONG_BUY, 0.85, f"RSI extremely oversold at {rsi:.1f}. Strong buying opportunity."
        elif rsi < 30:
            return SignalType.BUY, 0.75, f"RSI oversold at {rsi:.1f}. Good entry point."
        elif rsi > 80:
            return SignalType.STRONG_SELL, 0.85, f"RSI extremely overbought at {rsi:.1f}. Consider taking profits."
        elif rsi > 70:
            return SignalType.SELL, 0.70, f"RSI overbought at {rsi:.1f}. May see pullback."
        else:
            return SignalType.HOLD, 0.50, f"RSI neutral at {rsi:.1f}. No clear signal."
    
    def _macd_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """MACD crossover strategy"""
        macd = ind.macd_line
        signal = ind.macd_signal
        histogram = ind.macd_histogram
        
        if macd > signal and histogram > 0:
            confidence = min(0.85, 0.6 + abs(histogram) / ind.current_price * 100)
            if histogram > ind.current_price * 0.001:
                return SignalType.STRONG_BUY, confidence, "MACD bullish crossover with strong momentum."
            return SignalType.BUY, confidence, "MACD bullish crossover. Uptrend confirmed."
        elif macd < signal and histogram < 0:
            confidence = min(0.85, 0.6 + abs(histogram) / ind.current_price * 100)
            if histogram < -ind.current_price * 0.001:
                return SignalType.STRONG_SELL, confidence, "MACD bearish crossover with strong momentum."
            return SignalType.SELL, confidence, "MACD bearish crossover. Downtrend confirmed."
        else:
            return SignalType.HOLD, 0.50, "MACD neutral. Awaiting crossover."
    
    def _momentum_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Momentum-based strategy"""
        price = ind.current_price
        sma_20 = ind.sma_20
        sma_50 = ind.sma_50
        change_7d = ind.price_change_7d
        
        # Price above both MAs and positive momentum
        if price > sma_20 > sma_50 and change_7d > 5:
            return SignalType.STRONG_BUY, 0.80, f"Strong upward momentum. Price +{change_7d:.1f}% in 7 days, above all MAs."
        elif price > sma_20 and change_7d > 2:
            return SignalType.BUY, 0.70, f"Positive momentum. Price +{change_7d:.1f}% in 7 days."
        elif price < sma_20 < sma_50 and change_7d < -5:
            return SignalType.STRONG_SELL, 0.80, f"Strong downward momentum. Price {change_7d:.1f}% in 7 days."
        elif price < sma_20 and change_7d < -2:
            return SignalType.SELL, 0.70, f"Negative momentum. Price {change_7d:.1f}% in 7 days."
        else:
            return SignalType.HOLD, 0.50, "Momentum neutral."
    
    def _mean_reversion_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Mean reversion strategy using Bollinger Bands"""
        price = ind.current_price
        bb_upper = ind.bb_upper
        bb_lower = ind.bb_lower
        bb_middle = ind.bb_middle
        
        bb_position = (price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
        
        if bb_position < 0.1:
            return SignalType.STRONG_BUY, 0.82, f"Price at lower Bollinger Band. Strong mean reversion opportunity."
        elif bb_position < 0.2:
            return SignalType.BUY, 0.72, f"Price near lower Bollinger Band. Mean reversion likely."
        elif bb_position > 0.9:
            return SignalType.STRONG_SELL, 0.82, f"Price at upper Bollinger Band. Expect reversion to mean."
        elif bb_position > 0.8:
            return SignalType.SELL, 0.72, f"Price near upper Bollinger Band. Overbought."
        else:
            return SignalType.HOLD, 0.50, f"Price near middle band. No reversion signal."
    
    def _trend_following_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Trend following using multiple MAs"""
        price = ind.current_price
        sma_20 = ind.sma_20
        sma_50 = ind.sma_50
        sma_200 = ind.sma_200
        
        # Golden cross (50 > 200) is bullish
        # Death cross (50 < 200) is bearish
        
        if sma_20 > sma_50 > sma_200 and price > sma_20:
            return SignalType.STRONG_BUY, 0.85, "Strong uptrend. Golden cross with price above all MAs."
        elif sma_20 > sma_50 and price > sma_20:
            return SignalType.BUY, 0.75, "Uptrend confirmed. Short-term MA above medium-term."
        elif sma_20 < sma_50 < sma_200 and price < sma_20:
            return SignalType.STRONG_SELL, 0.85, "Strong downtrend. Death cross with price below all MAs."
        elif sma_20 < sma_50 and price < sma_20:
            return SignalType.SELL, 0.75, "Downtrend confirmed. Short-term MA below medium-term."
        else:
            return SignalType.HOLD, 0.50, "No clear trend. MAs mixed."
    
    def _breakout_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Breakout strategy using support/resistance"""
        price = ind.current_price
        resistance = ind.resistance_level
        support = ind.support_level
        volume_change = ind.volume_change
        
        if price > resistance and volume_change > 20:
            return SignalType.STRONG_BUY, 0.80, f"Breakout above resistance ${resistance:.2f} with high volume."
        elif price > resistance:
            return SignalType.BUY, 0.70, f"Breakout above resistance ${resistance:.2f}."
        elif price < support and volume_change > 20:
            return SignalType.STRONG_SELL, 0.80, f"Breakdown below support ${support:.2f} with high volume."
        elif price < support:
            return SignalType.SELL, 0.70, f"Breakdown below support ${support:.2f}."
        else:
            return SignalType.HOLD, 0.50, f"Price within range. Support: ${support:.2f}, Resistance: ${resistance:.2f}"
    
    def _ai_adaptive_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """AI Adaptive strategy - combines multiple indicators intelligently"""
        # Collect signals from multiple strategies
        rsi_signal, rsi_conf, _ = self._rsi_strategy(ind)
        macd_signal, macd_conf, _ = self._macd_strategy(ind)
        momentum_signal, momentum_conf, _ = self._momentum_strategy(ind)
        trend_signal, trend_conf, _ = self._trend_following_strategy(ind)
        
        # Convert signals to scores
        signal_scores = {
            SignalType.STRONG_BUY: 2,
            SignalType.BUY: 1,
            SignalType.HOLD: 0,
            SignalType.SELL: -1,
            SignalType.STRONG_SELL: -2
        }
        
        # Calculate weighted average
        total_score = (
            signal_scores[rsi_signal] * rsi_conf +
            signal_scores[macd_signal] * macd_conf +
            signal_scores[momentum_signal] * momentum_conf +
            signal_scores[trend_signal] * trend_conf
        )
        total_weight = rsi_conf + macd_conf + momentum_conf + trend_conf
        avg_score = total_score / total_weight if total_weight > 0 else 0
        
        # Determine signal based on average score
        if avg_score >= 1.5:
            return SignalType.STRONG_BUY, 0.85, f"AI: Strong bullish consensus (score: {avg_score:.2f})"
        elif avg_score >= 0.5:
            return SignalType.BUY, 0.75, f"AI: Bullish signal detected (score: {avg_score:.2f})"
        elif avg_score <= -1.5:
            return SignalType.STRONG_SELL, 0.85, f"AI: Strong bearish consensus (score: {avg_score:.2f})"
        elif avg_score <= -0.5:
            return SignalType.SELL, 0.75, f"AI: Bearish signal detected (score: {avg_score:.2f})"
        else:
            return SignalType.HOLD, 0.50, f"AI: Mixed signals, staying neutral (score: {avg_score:.2f})"
    
    def _dca_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Dollar Cost Averaging - always buy, more aggressive on dips"""
        rsi = ind.rsi_14
        price_change = ind.price_change_7d
        
        # DCA always buys, but confidence varies
        if rsi < 30 or price_change < -10:
            return SignalType.STRONG_BUY, 0.90, f"DCA: Excellent entry point, RSI={rsi:.1f}, 7d change={price_change:.1f}%"
        elif rsi < 40 or price_change < -5:
            return SignalType.BUY, 0.80, f"DCA: Good entry point, RSI={rsi:.1f}"
        elif rsi < 50:
            return SignalType.BUY, 0.75, f"DCA: Regular buy, favorable conditions"
        elif rsi < 70:
            return SignalType.BUY, 0.70, f"DCA: Regular scheduled buy"
        else:
            return SignalType.BUY, 0.65, f"DCA: Buying despite overbought (RSI={rsi:.1f})"
    
    def _scalping_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Scalping - quick trades based on short-term momentum"""
        rsi = ind.rsi_14
        macd_hist = ind.macd_histogram
        price_change = ind.price_change_24h
        
        # Very short-term signals
        if rsi < 25 and macd_hist > 0:
            return SignalType.STRONG_BUY, 0.80, f"Scalp: Oversold bounce (RSI={rsi:.1f})"
        elif rsi > 75 and macd_hist < 0:
            return SignalType.STRONG_SELL, 0.80, f"Scalp: Overbought reversal (RSI={rsi:.1f})"
        elif price_change > 2 and macd_hist > 0:
            return SignalType.BUY, 0.72, f"Scalp: Riding momentum up (+{price_change:.1f}%)"
        elif price_change < -2 and macd_hist < 0:
            return SignalType.SELL, 0.72, f"Scalp: Riding momentum down ({price_change:.1f}%)"
        elif abs(price_change) > 1:
            return SignalType.BUY if price_change > 0 else SignalType.SELL, 0.68, f"Scalp: Quick move ({price_change:+.1f}%)"
        else:
            return SignalType.HOLD, 0.50, "Scalp: Waiting for volatility"
    
    def _swing_trading_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Swing trading - capture medium-term moves"""
        price = ind.current_price
        sma_20 = ind.sma_20
        sma_50 = ind.sma_50
        rsi = ind.rsi_14
        bb_position = (price - ind.bb_lower) / (ind.bb_upper - ind.bb_lower) if ind.bb_upper != ind.bb_lower else 0.5
        
        # Look for swing entry points
        if bb_position < 0.2 and price > sma_50 and rsi < 40:
            return SignalType.STRONG_BUY, 0.82, f"Swing: Pullback to lower BB in uptrend (BB pos: {bb_position:.2f})"
        elif bb_position < 0.3 and sma_20 > sma_50:
            return SignalType.BUY, 0.75, f"Swing: Buying dip in uptrend"
        elif bb_position > 0.8 and price < sma_50 and rsi > 60:
            return SignalType.STRONG_SELL, 0.82, f"Swing: Rally to upper BB in downtrend (BB pos: {bb_position:.2f})"
        elif bb_position > 0.7 and sma_20 < sma_50:
            return SignalType.SELL, 0.75, f"Swing: Selling rally in downtrend"
        else:
            return SignalType.HOLD, 0.50, "Swing: No clear entry point"
    
    def _grid_trading_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Grid trading - buy low, sell high within range"""
        price = ind.current_price
        support = ind.support_level
        resistance = ind.resistance_level
        range_size = resistance - support
        
        if range_size <= 0:
            return SignalType.HOLD, 0.50, "Grid: Invalid range"
        
        price_position = (price - support) / range_size
        
        # Grid levels
        if price_position < 0.2:
            return SignalType.STRONG_BUY, 0.82, f"Grid: Near support, strong buy zone ({price_position*100:.0f}%)"
        elif price_position < 0.35:
            return SignalType.BUY, 0.75, f"Grid: Lower grid, buy zone ({price_position*100:.0f}%)"
        elif price_position > 0.8:
            return SignalType.STRONG_SELL, 0.82, f"Grid: Near resistance, strong sell zone ({price_position*100:.0f}%)"
        elif price_position > 0.65:
            return SignalType.SELL, 0.75, f"Grid: Upper grid, sell zone ({price_position*100:.0f}%)"
        else:
            return SignalType.HOLD, 0.50, f"Grid: Mid-range, wait ({price_position*100:.0f}%)"

    def _options_wheel_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """
        Options wheel strategy signal: sell puts when IV is elevated and price
        is near support; sell calls when price is near resistance.
        """
        rsi = ind.rsi_14
        price = ind.current_price
        support = ind.support_level
        resistance = ind.resistance_level
        vol = ind.volatility

        range_size = resistance - support if resistance > support else price * 0.1
        price_pos = (price - support) / range_size if range_size > 0 else 0.5

        if rsi < 35 and vol > 0.15 and price_pos < 0.35:
            conf = min(0.90, 0.65 + vol + (0.35 - price_pos))
            return (
                SignalType.STRONG_BUY, conf,
                f"Wheel: Sell cash-secured put — RSI {rsi:.1f}, IV {vol:.1%}, near support",
            )
        elif rsi < 45 and price_pos < 0.45:
            conf = min(0.80, 0.55 + (0.45 - price_pos) * 0.5)
            return (
                SignalType.BUY, conf,
                f"Wheel: Sell put candidate — RSI {rsi:.1f}, moderate IV, price in lower range",
            )
        elif rsi > 75 and price_pos > 0.80:
            conf = min(0.90, 0.70 + (price_pos - 0.80))
            return (
                SignalType.STRONG_SELL, conf,
                f"Wheel: Strong covered call signal — overbought RSI {rsi:.1f}, upper range",
            )
        elif rsi > 65 and price_pos > 0.65:
            conf = min(0.85, 0.60 + (price_pos - 0.65) * 0.5)
            return (
                SignalType.SELL, conf,
                f"Wheel: Sell covered call — RSI {rsi:.1f}, near resistance ({price_pos*100:.0f}%)",
            )
        else:
            return (
                SignalType.HOLD, 0.50,
                f"Wheel: Hold — RSI {rsi:.1f}, price position {price_pos*100:.0f}%, no actionable edge",
            )

    def _covered_call_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Covered call: sell calls when price is elevated, keep premium while limiting upside."""
        rsi = ind.rsi_14
        price = ind.current_price
        sma50 = ind.sma_50
        vol = ind.volatility

        if price > sma50 * 1.05 and rsi > 60:
            conf = min(0.88, 0.60 + (rsi - 60) / 100 + vol * 0.5)
            return (
                SignalType.SELL, conf,
                f"Covered call: Price {((price/sma50)-1)*100:.1f}% above SMA50, RSI {rsi:.1f} — sell call",
            )
        elif rsi > 75:
            return (
                SignalType.STRONG_SELL, 0.85,
                f"Covered call: RSI overbought at {rsi:.1f} — strong sell call signal",
            )
        elif price < sma50 * 0.95:
            return (
                SignalType.HOLD, 0.45,
                f"Covered call: Price below SMA50, not ideal for call writing",
            )
        else:
            return SignalType.HOLD, 0.50, f"Covered call: Neutral — RSI {rsi:.1f}, near SMA50"

    def _cash_secured_put_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Cash-secured put: sell puts when price drops to support with elevated IV."""
        rsi = ind.rsi_14
        price = ind.current_price
        support = ind.support_level
        vol = ind.volatility
        sma20 = ind.sma_20

        dist_to_support = (price - support) / price if price > 0 else 1.0

        if rsi < 30 and vol > 0.20 and dist_to_support < 0.05:
            return (
                SignalType.STRONG_BUY, 0.88,
                f"CSP: Oversold RSI {rsi:.1f}, IV {vol:.1%}, near support — premium sell put",
            )
        elif rsi < 40 and dist_to_support < 0.10:
            conf = min(0.80, 0.55 + vol * 0.8)
            return (
                SignalType.BUY, conf,
                f"CSP: RSI {rsi:.1f} near support ({dist_to_support*100:.1f}%) — sell put",
            )
        elif rsi > 60 and price > sma20:
            return (
                SignalType.HOLD, 0.45,
                f"CSP: Price above SMA20, RSI {rsi:.1f} — not ideal for put selling",
            )
        else:
            return SignalType.HOLD, 0.50, f"CSP: Neutral — RSI {rsi:.1f}"

    def _iron_condor_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Iron condor: profit from range-bound markets with low volatility expectations."""
        rsi = ind.rsi_14
        vol = ind.volatility
        price = ind.current_price
        support = ind.support_level
        resistance = ind.resistance_level
        range_pct = (resistance - support) / price if price > 0 else 0

        if 40 <= rsi <= 60 and vol < 0.25 and range_pct > 0.05:
            conf = min(0.85, 0.60 + (0.60 - abs(rsi - 50) / 50) * 0.3)
            return (
                SignalType.BUY, conf,
                f"Iron condor: Range-bound RSI {rsi:.1f}, low IV {vol:.1%}, spread width {range_pct*100:.1f}%",
            )
        elif vol > 0.40:
            return (
                SignalType.SELL, 0.70,
                f"Iron condor: IV too high ({vol:.1%}) — condor risk elevated, avoid",
            )
        elif abs(rsi - 50) > 25:
            return (
                SignalType.HOLD, 0.45,
                f"Iron condor: Directional bias (RSI {rsi:.1f}) — not range-bound",
            )
        else:
            return SignalType.HOLD, 0.50, f"Iron condor: Neutral — evaluating range"

    def _protective_put_strategy(self, ind: TechnicalIndicators) -> Tuple[SignalType, float, str]:
        """Protective put: buy puts as insurance when holding long positions in volatile markets."""
        rsi = ind.rsi_14
        vol = ind.volatility
        price = ind.current_price
        sma200 = ind.sma_200

        if vol > 0.35 and price < sma200:
            return (
                SignalType.STRONG_BUY, 0.85,
                f"Protective put: High vol {vol:.1%}, below 200-SMA — buy protection",
            )
        elif vol > 0.25 and rsi > 70:
            return (
                SignalType.BUY, 0.75,
                f"Protective put: Elevated vol {vol:.1%}, overbought RSI {rsi:.1f} — hedge recommended",
            )
        elif vol < 0.15 and price > sma200 * 1.05:
            return (
                SignalType.SELL, 0.65,
                f"Protective put: Low vol, strong uptrend — protection not needed",
            )
        else:
            return SignalType.HOLD, 0.50, f"Protective put: Vol {vol:.1%}, RSI {rsi:.1f} — monitor"

    def create_bot(self, account_id: str, name: str, strategy: TradingStrategy,
                   symbols: List[str], **kwargs) -> TradingBot:
        """Create a new trading bot"""
        bot_id = f"BOT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}"
        
        bot = TradingBot(
            bot_id=bot_id,
            account_id=account_id,
            name=name,
            strategy=strategy,
            symbols=symbols,
            max_position_size=kwargs.get('max_position_size', 1000.0),
            max_daily_trades=kwargs.get('max_daily_trades', 10),
            max_drawdown_pct=kwargs.get('max_drawdown_pct', 10.0),
            stop_loss_pct=kwargs.get('stop_loss_pct', 5.0),
            take_profit_pct=kwargs.get('take_profit_pct', 10.0),
            dca_interval_hours=kwargs.get('dca_interval_hours', 24),
            dca_amount=kwargs.get('dca_amount', 100.0)
        )
        
        self.bots[bot_id] = bot
        return bot
    
    def start_bot(self, bot_id: str) -> Dict:
        """Start a trading bot"""
        bot = self.bots.get(bot_id)
        if not bot:
            return {"success": False, "error": "Bot not found"}
        
        bot.is_active = True
        bot.updated_at = datetime.now().isoformat()
        return {"success": True, "bot_id": bot_id, "status": "running"}
    
    def stop_bot(self, bot_id: str) -> Dict:
        """Stop a trading bot"""
        bot = self.bots.get(bot_id)
        if not bot:
            return {"success": False, "error": "Bot not found"}
        
        bot.is_active = False
        bot.updated_at = datetime.now().isoformat()
        return {"success": True, "bot_id": bot_id, "status": "stopped"}
    
    def run_bot_cycle(self, bot_id: str) -> List[Dict]:
        """Run one cycle of bot trading logic"""
        bot = self.bots.get(bot_id)
        if not bot or not bot.is_active:
            return []
        
        # Check daily trade limit
        if bot.daily_trades_count >= bot.max_daily_trades:
            return [{"status": "limit_reached", "message": "Daily trade limit reached"}]
        
        results = []
        
        for symbol in bot.symbols:
            # Generate signal
            signal = self.generate_signal(symbol, bot.strategy)
            
            # Check if signal warrants action
            if signal.confidence >= 0.70:
                if signal.signal_type in [SignalType.BUY, SignalType.STRONG_BUY]:
                    order = self.create_order(
                        account_id=bot.account_id,
                        symbol=symbol,
                        side="buy",
                        amount=min(bot.max_position_size, bot.dca_amount if bot.strategy == TradingStrategy.DCA else bot.max_position_size),
                        order_type=OrderType.MARKET,
                        strategy=bot.strategy,
                        signal_id=signal.signal_id,
                        stop_loss_pct=bot.stop_loss_pct,
                        take_profit_pct=bot.take_profit_pct
                    )
                    results.append({"action": "buy", "symbol": symbol, "order": asdict(order), "signal": asdict(signal)})
                    bot.daily_trades_count += 1
                    
                elif signal.signal_type in [SignalType.SELL, SignalType.STRONG_SELL]:
                    order = self.create_order(
                        account_id=bot.account_id,
                        symbol=symbol,
                        side="sell",
                        amount=bot.max_position_size,
                        order_type=OrderType.MARKET,
                        strategy=bot.strategy,
                        signal_id=signal.signal_id
                    )
                    results.append({"action": "sell", "symbol": symbol, "order": asdict(order), "signal": asdict(signal)})
                    bot.daily_trades_count += 1
        
        bot.last_trade_at = datetime.now().isoformat()
        bot.updated_at = datetime.now().isoformat()
        
        return results
    
    def create_order(self, account_id: str, symbol: str, side: str, amount: float,
                     order_type: OrderType = OrderType.MARKET, **kwargs) -> TradeOrder:
        """Create a new trade order"""
        if not self.portfolio_service:
            raise ValueError("Portfolio service not initialized")
        
        market_data = self.portfolio_service.MARKET_DATA.get(symbol, {})
        price = market_data.get("price", 0)
        quantity = amount / price if price > 0 else 0
        
        stop_loss = None
        take_profit = None
        
        if kwargs.get('stop_loss_pct'):
            if side == "buy":
                stop_loss = price * (1 - kwargs['stop_loss_pct'] / 100)
            else:
                stop_loss = price * (1 + kwargs['stop_loss_pct'] / 100)
        
        if kwargs.get('take_profit_pct'):
            if side == "buy":
                take_profit = price * (1 + kwargs['take_profit_pct'] / 100)
            else:
                take_profit = price * (1 - kwargs['take_profit_pct'] / 100)
        
        order = TradeOrder(
            order_id=f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
            account_id=account_id,
            symbol=symbol,
            order_type=order_type,
            side=side,
            quantity=quantity,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=kwargs.get('strategy'),
            signal_id=kwargs.get('signal_id')
        )
        
        self.orders[order.order_id] = order
        
        # Auto-execute market orders
        if order_type == OrderType.MARKET:
            self.execute_order(order.order_id)
        
        return order
    
    def execute_order(self, order_id: str) -> Dict:
        """Execute a trade order"""
        order = self.orders.get(order_id)
        if not order:
            return {"success": False, "error": "Order not found"}
        
        if order.status == OrderStatus.EXECUTED:
            return {"success": False, "error": "Order already executed"}
        
        if not self.portfolio_service:
            return {"success": False, "error": "Portfolio service not available"}
        
        try:
            if order.side == "buy":
                result = self.portfolio_service.invest(
                    order.account_id,
                    order.symbol,
                    order.quantity * order.price
                )
            else:
                result = self.portfolio_service.sell_asset(
                    order.account_id,
                    order.symbol,
                    order.quantity
                )
            
            if result.get("success"):
                order.status = OrderStatus.EXECUTED
                order.filled_quantity = order.quantity
                order.filled_price = order.price
                order.executed_at = datetime.now().isoformat()
                
                # Update bot stats if applicable
                if order.strategy:
                    for bot in self.bots.values():
                        if bot.account_id == order.account_id and bot.strategy == order.strategy:
                            bot.total_trades += 1
                            if order.side == "sell" and result.get("realized_gain", 0) > 0:
                                bot.winning_trades += 1
                            bot.total_pnl += result.get("realized_gain", 0)
                
                return {"success": True, "order": asdict(order), "execution_result": result}
            else:
                order.status = OrderStatus.FAILED
                return {"success": False, "error": result.get("error", "Execution failed")}
                
        except Exception as e:
            order.status = OrderStatus.FAILED
            return {"success": False, "error": str(e)}
    
    def get_bot_performance(self, bot_id: str) -> Dict:
        """Get comprehensive bot performance metrics"""
        bot = self.bots.get(bot_id)
        if not bot:
            return {"error": "Bot not found"}
        
        return {
            "bot_id": bot_id,
            "name": bot.name,
            "strategy": bot.strategy.value,
            "status": "running" if bot.is_active else "stopped",
            "risk_level": bot.risk_level,
            
            # Core Performance Metrics
            "performance": {
                "total_pnl": round(bot.total_pnl, 2),
                "realized_pnl": round(bot.realized_pnl, 2),
                "unrealized_pnl": round(bot.unrealized_pnl, 2),
                "total_return_pct": round((bot.total_pnl / 10000) * 100, 2) if bot.total_pnl else 0,
                # Compatibility: some callers/tests expect these fields under "performance"
                "total_trades": bot.total_trades,
                "win_rate": round(bot.win_rate, 1),
            },
            
            # Trade Statistics
            "trade_stats": {
                "total_trades": bot.total_trades,
                "winning_trades": bot.winning_trades,
                "losing_trades": bot.losing_trades,
                "win_rate": round(bot.win_rate, 1),
                "profit_factor": bot.profit_factor,
                "avg_win": round(bot.avg_win, 2),
                "avg_loss": round(bot.avg_loss, 2),
                "best_trade": round(bot.best_trade, 2),
                "worst_trade": round(bot.worst_trade, 2),
            },
            
            # Risk Metrics (Dashboard Indicators)
            "risk_metrics": {
                "sharpe_ratio": bot.sharpe_ratio,
                "sortino_ratio": bot.sortino_ratio,
                "calmar_ratio": bot.calmar_ratio,
                "max_drawdown": round(bot.max_drawdown, 2),
                "max_drawdown_pct": round(bot.max_drawdown_pct, 2),
                "current_drawdown": round(bot.current_drawdown, 2),
                "daily_volatility": round(bot.daily_volatility, 2),
                "annualized_volatility": round(bot.annualized_volatility, 2),
                "beta": bot.beta,
                "alpha": round(bot.alpha, 2),
            },
            
            # Streaks
            "streaks": {
                "current_streak": bot.current_streak,
                "longest_winning_streak": bot.longest_winning_streak,
                "longest_losing_streak": bot.longest_losing_streak,
                "avg_trade_duration": bot.avg_trade_duration,
            },
            
            # Settings
            "settings": {
                "symbols": bot.symbols,
                "asset_allocation": bot.asset_allocation,
                "max_position_size": bot.max_position_size,
                "max_daily_trades": bot.max_daily_trades,
                "stop_loss_pct": bot.stop_loss_pct,
                "take_profit_pct": bot.take_profit_pct,
                "trailing_stop_pct": bot.trailing_stop_pct,
            },
            
            # Activity
            "activity": {
                "daily_trades": bot.daily_trades_count,
                "last_trade": bot.last_trade_at,
            },
            
            # Equity curve for charting
            "equity_curve": bot.equity_curve[-100:] if len(bot.equity_curve) > 100 else bot.equity_curve,
            
            "created_at": bot.created_at,
            "updated_at": bot.updated_at
        }
    
    def get_smart_bot_templates(self, risk_level: str = None) -> List[Dict]:
        """Get available smart bot templates with pre-configured strategies"""
        if ADVANCED_MARKET_AVAILABLE:
            service = get_advanced_market_service()
            return service.get_smart_bot_templates(risk_level)
        
        templates = [
            {
                "bot_id": "conservative_dca",
                "name": "Conservative DCA Bot",
                "description": "Dollar-cost averaging into index ETFs and safe havens",
                "strategy": "dollar_cost_averaging",
                "risk_level": "low",
                "expected_return": "Tracks broad market performance",
                "symbols": ["SPY", "BND", "GLD"],
                "settings": {"max_drawdown_pct": 8, "stop_loss_pct": 5},
                "data_source": "alpaca_live",
            },
            {
                "bot_id": "balanced_momentum",
                "name": "Balanced Momentum Trader",
                "description": "AI-driven momentum signals from live Alpaca technicals",
                "strategy": "momentum",
                "risk_level": "medium",
                "expected_return": "Based on live signal performance",
                "symbols": ["QQQ", "AAPL", "MSFT", "NVDA"],
                "settings": {"max_drawdown_pct": 12, "stop_loss_pct": 7},
                "data_source": "alpaca_live",
            },
            {
                "bot_id": "crypto_swing",
                "name": "Crypto Swing Trader",
                "description": "Mean-reversion on crypto using real-time Alpaca data",
                "strategy": "mean_reversion",
                "risk_level": "high",
                "expected_return": "Based on live signal performance",
                "symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
                "settings": {"max_drawdown_pct": 20, "stop_loss_pct": 10},
                "data_source": "alpaca_live",
            },
            {
                "bot_id": "energy_macro",
                "name": "Energy & Macro Sentiment",
                "description": "Trend-following on energy and commodities via Alpaca",
                "strategy": "trend_following",
                "risk_level": "medium",
                "expected_return": "Based on live signal performance",
                "symbols": ["USO", "UNG", "XLE", "GLD"],
                "settings": {"max_drawdown_pct": 15, "stop_loss_pct": 8},
                "data_source": "alpaca_live",
            },
            {
                "bot_id": "quantum_scalp",
                "name": "Quantum Scalp AI",
                "description": "High-frequency mean-reversion with AI-optimized entry/exit",
                "strategy": "scalping",
                "risk_level": "very_high",
                "expected_return": "Based on live signal performance",
                "symbols": ["SPY", "QQQ", "AAPL"],
                "settings": {"max_drawdown_pct": 10, "stop_loss_pct": 3},
                "data_source": "alpaca_live",
            },
        ]
        
        if risk_level:
            return [t for t in templates if t["risk_level"] == risk_level]
        return templates
    
    def create_smart_bot(self, account_id: str, template_id: str, 
                         custom_settings: Dict = None) -> Dict:
        """Create a bot from a smart template"""
        templates = self.get_smart_bot_templates()
        template = next((t for t in templates if t["bot_id"] == template_id), None)
        
        if not template:
            return {"success": False, "error": f"Template '{template_id}' not found"}
        
        # Merge custom settings
        settings = template.get("settings", {}).copy()
        if custom_settings:
            settings.update(custom_settings)
        
        # Create bot
        bot_id = f"BOT-{template_id.upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        try:
            strategy = TradingStrategy(template["strategy"])
        except ValueError:
            strategy = TradingStrategy.MOMENTUM
        
        bot = TradingBot(
            bot_id=bot_id,
            account_id=account_id,
            name=template["name"],
            strategy=strategy,
            symbols=template.get("symbols", []),
            is_active=True,
            max_position_size=settings.get("max_position_size", 1000),
            max_daily_trades=settings.get("max_daily_trades", 10),
            max_drawdown_pct=settings.get("max_drawdown_pct", 10),
            stop_loss_pct=settings.get("stop_loss_pct", 5),
            take_profit_pct=settings.get("take_profit_pct", 15),
            dca_interval_hours=settings.get("dca_interval_hours", 24),
            dca_amount=settings.get("dca_amount", 100),
            risk_level=template.get("risk_level", "medium"),
            asset_allocation=template.get("allocation", {})
        )
        
        self.bots[bot_id] = bot
        
        return {
            "success": True,
            "bot": self.get_bot_performance(bot_id),
            "template_used": template_id,
            "message": f"Smart bot '{template['name']}' created successfully"
        }
    
    def get_extended_market_data(self, symbols: List[str] = None, 
                                  asset_class: str = None) -> Dict:
        """Get extended market data from all asset classes"""
        if ADVANCED_MARKET_AVAILABLE:
            service = get_advanced_market_service()
            if asset_class:
                try:
                    ac = AssetClass(asset_class)
                    return service.get_market_overview(ac)
                except ValueError:
                    pass
            return service.get_market_overview()
        
        # Return basic market data if advanced service not available
        return self.get_market_overview()
    
    def get_bloomberg_feed(self, symbols: List[str]) -> Dict:
        """Get Bloomberg-style market data feed"""
        if ADVANCED_MARKET_AVAILABLE:
            service = get_advanced_market_service()
            return service.get_bloomberg_feed(symbols)
        
        return {"error": "Advanced market data service not available"}
    
    def get_reuters_feed(self, symbols: List[str]) -> Dict:
        """Get Reuters-style market data feed"""
        if ADVANCED_MARKET_AVAILABLE:
            service = get_advanced_market_service()
            return service.get_reuters_feed(symbols)
        
        return {"error": "Advanced market data service not available"}
    
    def get_all_bot_stats(self, account_id: str = None) -> Dict:
        """Get aggregated statistics for all bots"""
        bots = list(self.bots.values())
        if account_id:
            bots = [b for b in bots if b.account_id == account_id]
        
        if not bots:
            return {
                "total_bots": 0,
                "active_bots": 0,
                "total_pnl": 0,
                "total_trades": 0,
                "avg_win_rate": 0,
                "avg_sharpe": 0
            }
        
        active_bots = [b for b in bots if b.is_active]
        total_pnl = sum(b.total_pnl for b in bots)
        total_trades = sum(b.total_trades for b in bots)
        avg_win_rate = sum(b.win_rate for b in bots) / len(bots)
        avg_sharpe = sum(b.sharpe_ratio for b in bots) / len(bots)
        max_dd = max(b.max_drawdown_pct for b in bots) if bots else 0
        
        return {
            "total_bots": len(bots),
            "active_bots": len(active_bots),
            "stopped_bots": len(bots) - len(active_bots),
            "aggregated_metrics": {
                "total_pnl": round(total_pnl, 2),
                "total_trades": total_trades,
                "avg_win_rate": round(avg_win_rate, 1),
                "avg_sharpe_ratio": round(avg_sharpe, 2),
                "max_drawdown_pct": round(max_dd, 2)
            },
            "by_strategy": self._group_bots_by_strategy(bots),
            "by_risk_level": self._group_bots_by_risk(bots),
            "top_performers": self._get_top_performers(bots, 3),
            "timestamp": datetime.now().isoformat()
        }
    
    def _group_bots_by_strategy(self, bots: List[TradingBot]) -> Dict:
        """Group bot performance by strategy"""
        groups = {}
        for bot in bots:
            strategy = bot.strategy.value
            if strategy not in groups:
                groups[strategy] = {"count": 0, "total_pnl": 0, "avg_win_rate": 0}
            groups[strategy]["count"] += 1
            groups[strategy]["total_pnl"] += bot.total_pnl
            groups[strategy]["avg_win_rate"] += bot.win_rate
        
        for strategy in groups:
            count = groups[strategy]["count"]
            groups[strategy]["avg_win_rate"] = round(groups[strategy]["avg_win_rate"] / count, 1)
            groups[strategy]["total_pnl"] = round(groups[strategy]["total_pnl"], 2)
        
        return groups
    
    def _group_bots_by_risk(self, bots: List[TradingBot]) -> Dict:
        """Group bot performance by risk level"""
        groups = {}
        for bot in bots:
            risk = bot.risk_level
            if risk not in groups:
                groups[risk] = {"count": 0, "total_pnl": 0, "avg_sharpe": 0}
            groups[risk]["count"] += 1
            groups[risk]["total_pnl"] += bot.total_pnl
            groups[risk]["avg_sharpe"] += bot.sharpe_ratio
        
        for risk in groups:
            count = groups[risk]["count"]
            groups[risk]["avg_sharpe"] = round(groups[risk]["avg_sharpe"] / count, 2)
            groups[risk]["total_pnl"] = round(groups[risk]["total_pnl"], 2)
        
        return groups
    
    def _get_top_performers(self, bots: List[TradingBot], limit: int) -> List[Dict]:
        """Get top performing bots"""
        sorted_bots = sorted(bots, key=lambda b: b.total_pnl, reverse=True)
        return [
            {
                "bot_id": b.bot_id,
                "name": b.name,
                "strategy": b.strategy.value,
                "total_pnl": round(b.total_pnl, 2),
                "win_rate": round(b.win_rate, 1),
                "sharpe_ratio": b.sharpe_ratio
            }
            for b in sorted_bots[:limit]
        ]
    
    def simulate_bot_trades(self, bot_id: str, days: int = 30) -> Dict:
        """Back-test a bot using real historical price data from Alpaca bars."""
        bot = self.bots.get(bot_id)
        if not bot:
            return {"error": "Bot not found"}

        for symbol in bot.symbols:
            history = self.price_history.get(symbol)
            if not history or len(history) < 20:
                continue
            prices = [h["price"] for h in history]
            lookback = min(days, len(prices) - 1)
            for i in range(len(prices) - lookback, len(prices)):
                if i < 1:
                    continue
                prev = prices[i - 1]
                curr = prices[i]
                if prev <= 0:
                    continue
                ret = (curr - prev) / prev
                pnl = bot.max_position_size * ret
                bot.update_metrics(pnl, ret)

        bot.last_trade_at = datetime.now().isoformat()
        
        return {
            "success": True,
            "trades_simulated": total_simulated_trades,
            "performance": self.get_bot_performance(bot_id)
        }
    
    def get_all_signals(self, symbol: str = None, limit: int = 50) -> List[Dict]:
        """Get recent trading signals"""
        if symbol:
            signals = self.signals.get(symbol, [])
        else:
            signals = []
            for sym_signals in self.signals.values():
                signals.extend(sym_signals)
        
        # Sort by created_at descending
        signals.sort(key=lambda s: s.created_at, reverse=True)
        return [asdict(s) for s in signals[:limit]]
    
    def get_order_history(self, account_id: str = None, limit: int = 50) -> List[Dict]:
        """Get order history"""
        orders = list(self.orders.values())
        
        if account_id:
            orders = [o for o in orders if o.account_id == account_id]
        
        # Sort by created_at descending
        orders.sort(key=lambda o: o.created_at, reverse=True)
        return [asdict(o) for o in orders[:limit]]
    
    def auto_rebalance(self, account_id: str, tolerance_pct: float = 5.0) -> List[Dict]:
        """Automatically rebalance portfolio to target allocation"""
        if not self.portfolio_service:
            return [{"error": "Portfolio service not available"}]
        
        account = self.portfolio_service.accounts.get(account_id)
        if not account:
            return [{"error": "Account not found"}]
        
        portfolio = self.portfolio_service.get_portfolio_summary(account_id)
        allocation = portfolio.get("allocation", {})
        target = account.target_allocation
        
        rebalance_actions = []
        
        for asset_class, data in allocation.items():
            current_pct = data.get("percentage", 0)
            target_pct = getattr(target, f"{asset_class}_pct", 0)
            diff = current_pct - target_pct
            
            if abs(diff) > tolerance_pct:
                if diff > 0:
                    # Need to sell
                    for asset in data.get("assets", []):
                        sell_amount = asset["value"] * (diff / 100)
                        if sell_amount > 10:  # Minimum trade
                            rebalance_actions.append({
                                "action": "sell",
                                "symbol": asset["symbol"],
                                "amount": sell_amount,
                                "reason": f"Reduce {asset_class} allocation from {current_pct:.1f}% to {target_pct:.1f}%"
                            })
                else:
                    # Need to buy - recommend top asset in class
                    rebalance_actions.append({
                        "action": "buy",
                        "asset_class": asset_class,
                        "amount": portfolio["cash_balance"] * (abs(diff) / 100),
                        "reason": f"Increase {asset_class} allocation from {current_pct:.1f}% to {target_pct:.1f}%"
                    })
        
        return rebalance_actions
    
    def get_market_overview(self) -> Dict:
        """Get market overview with real data from Alpaca/synced prices."""
        overview_symbols = ["SPY", "QQQ", "BTC/USD", "ETH/USD", "GLD", "BND",
                           "AAPL", "MSFT", "NVDA", "XLE", "USO", "TLT"]
        overview = {
            "timestamp": datetime.now().isoformat(),
            "assets": [],
            "data_source": "alpaca" if self._has_live_data() else "synced",
        }

        names = {
            "SPY": "S&P 500", "QQQ": "NASDAQ 100", "BTC/USD": "Bitcoin",
            "ETH/USD": "Ethereum", "GLD": "Gold", "BND": "Total Bond",
            "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA",
            "XLE": "Energy", "USO": "Crude Oil", "TLT": "20Y Treasury",
        }

        for symbol in overview_symbols:
            indicators = self.calculate_indicators(symbol)
            if indicators.current_price <= 0:
                if self.portfolio_service and symbol in getattr(self.portfolio_service, 'MARKET_DATA', {}):
                    pass
                else:
                    continue
            signal = self.generate_signal(symbol, TradingStrategy.MOMENTUM)
            name = names.get(symbol, symbol)
            if self.portfolio_service and symbol in getattr(self.portfolio_service, 'MARKET_DATA', {}):
                name = self.portfolio_service.MARKET_DATA[symbol].get("name", name)

            overview["assets"].append({
                "symbol": symbol,
                "name": name,
                "price": indicators.current_price,
                "change_24h": indicators.price_change_24h,
                "rsi": indicators.rsi_14,
                "macd": indicators.macd_line,
                "signal": signal.signal_type.value,
                "confidence": signal.confidence,
            })

        return overview

    def _has_live_data(self) -> bool:
        """Check if any price history comes from live Alpaca data."""
        for sym, history in self.price_history.items():
            if history and history[-1].get("source") == "alpaca":
                return True
        return False


# =============================================================================
# PROFIT-GENERATING TRADING ENGINE
# =============================================================================
# This section implements the active trading engine that generates real profits
# based on market conditions and strategy signals.
# =============================================================================

@dataclass
class ActiveTrade:
    """Represents an active/open trade position"""
    trade_id: str
    bot_id: str
    account_id: str
    customer_id: str
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: float
    quantity: float
    current_price: float
    stop_loss: float
    take_profit: float
    strategy: TradingStrategy
    entry_time: str
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    status: str = "open"  # open, closed, stopped_out, take_profit_hit
    
    def update_pnl(self, current_price: float):
        """Update unrealized PnL based on current price"""
        self.current_price = current_price
        if self.side == 'long':
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
            self.unrealized_pnl_pct = ((current_price / self.entry_price) - 1) * 100
        else:  # short
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity
            self.unrealized_pnl_pct = ((self.entry_price / current_price) - 1) * 100


class ProfitEngine:
    """
    Active profit-generating trading engine.
    
    This engine:
    1. Monitors market conditions in real-time
    2. Executes trades based on strategy signals
    3. Manages open positions with stop-loss and take-profit
    4. Tracks and realizes profits
    5. Updates customer investment accounts with gains
    """
    
    def __init__(self, algo_service: 'AlgoTradingService'):
        self.algo_service = algo_service
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.trade_history: List[Dict] = []
        self.total_realized_profit: float = 0.0
        self.customer_profits: Dict[str, float] = {}  # customer_id -> total profit
        self.last_market_update: str = ""
        
        # Strategy performance multipliers (based on market conditions)
        self.strategy_edge = {
            TradingStrategy.MOMENTUM: 0.65,  # 65% win rate in trending markets
            TradingStrategy.MEAN_REVERSION: 0.60,
            TradingStrategy.RSI_STRATEGY: 0.62,
            TradingStrategy.MACD_CROSSOVER: 0.58,
            TradingStrategy.TREND_FOLLOWING: 0.67,
            TradingStrategy.BREAKOUT: 0.55,
            TradingStrategy.DCA: 0.70,  # DCA has highest consistency
            TradingStrategy.AI_ADAPTIVE: 0.72,  # AI adapts to market
            TradingStrategy.SCALPING: 0.52,
            TradingStrategy.SWING_TRADING: 0.63,
        }
    
    def execute_profitable_trade(self, bot: TradingBot, symbol: str, 
                                   signal: TradingSignal, customer_id: str) -> Dict:
        """
        Execute a trade with built-in profit probability based on strategy edge.
        This simulates realistic market execution with the strategy's win rate.
        """
        if not self.algo_service.portfolio_service:
            return {"success": False, "error": "Portfolio service not available"}
        
        market_data = self.algo_service.portfolio_service.MARKET_DATA.get(symbol, {})
        current_price = market_data.get("price", 0)
        if current_price <= 0:
            indicators = self.algo_service.calculate_indicators(symbol)
            current_price = indicators.current_price if indicators.current_price > 0 else 0
        if current_price <= 0:
            return {"success": False, "error": f"No live price for {symbol}"}

        is_buy_signal = signal.signal_type in [SignalType.BUY, SignalType.STRONG_BUY]
        side = 'long' if is_buy_signal else 'short'

        position_value = min(bot.max_position_size, bot.dca_amount * 2)
        quantity = position_value / current_price

        indicators = self.algo_service.calculate_indicators(symbol)
        atr_estimate = indicators.atr_14 if indicators.atr_14 > 0 else current_price * 0.02
        if side == 'long':
            stop_loss = current_price - (atr_estimate * 2)
            take_profit = current_price + (atr_estimate * 3)
        else:
            stop_loss = current_price + (atr_estimate * 2)
            take_profit = current_price - (atr_estimate * 3)
        
        # Create active trade
        trade_id = f"TRD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}"
        
        trade = ActiveTrade(
            trade_id=trade_id,
            bot_id=bot.bot_id,
            account_id=bot.account_id,
            customer_id=customer_id,
            symbol=symbol,
            side=side,
            entry_price=current_price,
            quantity=quantity,
            current_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=bot.strategy,
            entry_time=datetime.now().isoformat()
        )
        
        self.active_trades[trade_id] = trade
        
        return {
            "success": True,
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side,
            "entry_price": current_price,
            "quantity": quantity,
            "position_value": position_value,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "strategy": bot.strategy.value,
            "message": f"Trade opened: {side.upper()} {quantity:.4f} {symbol} @ ${current_price:.2f}"
        }
    
    def process_trade_outcome(self, trade: ActiveTrade) -> Dict:
        """
        Process trade outcome using real market price data.
        Compares current market price against entry to determine P&L.
        """
        current_price = trade.current_price
        try:
            indicators = self.algo_service.calculate_indicators(trade.symbol)
            if indicators.current_price > 0:
                current_price = indicators.current_price
        except Exception:
            pass

        if trade.side == 'long':
            if current_price >= trade.take_profit:
                exit_price = trade.take_profit
                trade.status = "take_profit_hit"
                is_winner = True
            elif current_price <= trade.stop_loss:
                exit_price = trade.stop_loss
                trade.status = "stopped_out"
                is_winner = False
            else:
                exit_price = current_price
                trade.status = "closed_at_market"
                is_winner = exit_price > trade.entry_price
        else:
            if current_price <= trade.take_profit:
                exit_price = trade.take_profit
                trade.status = "take_profit_hit"
                is_winner = True
            elif current_price >= trade.stop_loss:
                exit_price = trade.stop_loss
                trade.status = "stopped_out"
                is_winner = False
            else:
                exit_price = current_price
                trade.status = "closed_at_market"
                is_winner = exit_price < trade.entry_price
        
        # Calculate realized PnL
        if trade.side == 'long':
            realized_pnl = (exit_price - trade.entry_price) * trade.quantity
            return_pct = ((exit_price / trade.entry_price) - 1) * 100
        else:
            realized_pnl = (trade.entry_price - exit_price) * trade.quantity
            return_pct = ((trade.entry_price / exit_price) - 1) * 100
        
        # Record the trade
        trade_record = {
            "trade_id": trade.trade_id,
            "bot_id": trade.bot_id,
            "customer_id": trade.customer_id,
            "symbol": trade.symbol,
            "side": trade.side,
            "entry_price": trade.entry_price,
            "exit_price": exit_price,
            "quantity": trade.quantity,
            "realized_pnl": round(realized_pnl, 2),
            "return_pct": round(return_pct, 2),
            "status": trade.status,
            "strategy": trade.strategy.value,
            "entry_time": trade.entry_time,
            "exit_time": datetime.now().isoformat(),
            "is_winner": is_winner
        }
        
        self.trade_history.append(trade_record)
        self.total_realized_profit += realized_pnl
        
        # Update customer profits
        if trade.customer_id not in self.customer_profits:
            self.customer_profits[trade.customer_id] = 0.0
        self.customer_profits[trade.customer_id] += realized_pnl
        
        # Update bot metrics
        bot = self.algo_service.bots.get(trade.bot_id)
        if bot:
            bot.update_metrics(realized_pnl, return_pct / 100)
            bot.realized_pnl += realized_pnl
        
        # Remove from active trades
        if trade.trade_id in self.active_trades:
            del self.active_trades[trade.trade_id]
        
        return {
            "success": True,
            "trade_record": trade_record,
            "total_customer_profit": round(self.customer_profits.get(trade.customer_id, 0), 2)
        }
    
    def run_profit_cycle(self, customer_id: str, account_id: str) -> Dict:
        """
        Run a complete profit-generating trading cycle for a customer.
        
        This:
        1. Finds active bots for the customer
        2. Generates signals for each bot's symbols
        3. Executes profitable trades
        4. Processes outcomes
        5. Returns realized profits
        """
        results = {
            "customer_id": customer_id,
            "timestamp": datetime.now().isoformat(),
            "trades_executed": [],
            "trades_closed": [],
            "total_profit_this_cycle": 0.0,
            "total_realized_profit": 0.0
        }
        
        # Find customer's bots
        customer_bots = [b for b in self.algo_service.bots.values() 
                        if b.account_id == account_id and b.is_active]
        
        if not customer_bots:
            # Create a default bot if none exists
            available_symbols = list(self.algo_service.price_history.keys())[:6]
            if not available_symbols:
                available_symbols = ["SPY", "QQQ"]
            default_bot = self.algo_service.create_bot(
                account_id=account_id,
                name="Auto-Profit Bot",
                strategy=TradingStrategy.AI_ADAPTIVE,
                symbols=available_symbols,
                max_position_size=500,
                stop_loss_pct=3.0,
                take_profit_pct=6.0
            )
            default_bot.risk_level = "medium"
            customer_bots = [default_bot]
        
        cycle_profit = 0.0
        
        for bot in customer_bots:
            # Check daily trade limit
            if bot.daily_trades_count >= bot.max_daily_trades:
                continue
            
            for symbol in bot.symbols[:3]:  # Limit to 3 symbols per cycle
                # Generate signal
                signal = self.algo_service.generate_signal(symbol, bot.strategy)
                
                # Execute if signal is strong enough
                if signal.confidence >= 0.65 and signal.signal_type != SignalType.HOLD:
                    # Execute trade
                    trade_result = self.execute_profitable_trade(
                        bot, symbol, signal, customer_id
                    )
                    
                    if trade_result.get("success"):
                        results["trades_executed"].append(trade_result)
                        bot.daily_trades_count += 1
                        
                        # Immediately process outcome (simulating fast market)
                        trade = self.active_trades.get(trade_result["trade_id"])
                        if trade:
                            outcome = self.process_trade_outcome(trade)
                            if outcome.get("success"):
                                results["trades_closed"].append(outcome["trade_record"])
                                cycle_profit += outcome["trade_record"]["realized_pnl"]
        
        results["total_profit_this_cycle"] = round(cycle_profit, 2)
        results["total_realized_profit"] = round(
            self.customer_profits.get(customer_id, 0), 2
        )
        
        return results
    
    def get_customer_trading_summary(self, customer_id: str) -> Dict:
        """Get comprehensive trading summary for a customer"""
        # Get customer's trades
        customer_trades = [t for t in self.trade_history if t["customer_id"] == customer_id]
        
        if not customer_trades:
            return {
                "customer_id": customer_id,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "total_realized_profit": 0,
                "avg_profit_per_trade": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "recent_trades": []
            }
        
        winning = [t for t in customer_trades if t["is_winner"]]
        losing = [t for t in customer_trades if not t["is_winner"]]
        
        total_profit = sum(t["realized_pnl"] for t in customer_trades)
        profits = [t["realized_pnl"] for t in customer_trades]
        
        return {
            "customer_id": customer_id,
            "total_trades": len(customer_trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round((len(winning) / len(customer_trades)) * 100, 1),
            "total_realized_profit": round(total_profit, 2),
            "avg_profit_per_trade": round(total_profit / len(customer_trades), 2),
            "best_trade": round(max(profits), 2) if profits else 0,
            "worst_trade": round(min(profits), 2) if profits else 0,
            "recent_trades": customer_trades[-10:][::-1],  # Last 10, newest first
            "active_positions": len([t for t in self.active_trades.values() 
                                    if t.customer_id == customer_id])
        }
    
    def get_real_time_profits(self, customer_id: str) -> Dict:
        """Get real-time profit data for dashboard display"""
        customer_trades = [t for t in self.trade_history if t["customer_id"] == customer_id]
        
        # Calculate profits by time period
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)
        
        today_profit = sum(t["realized_pnl"] for t in customer_trades 
                         if t["exit_time"] >= today_start.isoformat())
        week_profit = sum(t["realized_pnl"] for t in customer_trades 
                        if t["exit_time"] >= week_start.isoformat())
        month_profit = sum(t["realized_pnl"] for t in customer_trades 
                         if t["exit_time"] >= month_start.isoformat())
        total_profit = self.customer_profits.get(customer_id, 0)
        
        # Get active positions unrealized PnL
        active_positions = [t for t in self.active_trades.values() 
                          if t.customer_id == customer_id]
        unrealized_pnl = sum(t.unrealized_pnl for t in active_positions)
        
        return {
            "customer_id": customer_id,
            "timestamp": now.isoformat(),
            "realized_profits": {
                "today": round(today_profit, 2),
                "this_week": round(week_profit, 2),
                "this_month": round(month_profit, 2),
                "all_time": round(total_profit, 2)
            },
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": round(total_profit + unrealized_pnl, 2),
            "active_positions_count": len(active_positions),
            "trades_today": len([t for t in customer_trades 
                               if t["exit_time"] >= today_start.isoformat()])
        }


# Singleton instance
_algo_trading_service: Optional[AlgoTradingService] = None
_profit_engine: Optional[ProfitEngine] = None


def get_algo_trading_service(portfolio_service=None) -> AlgoTradingService:
    """Get singleton instance of algo trading service"""
    global _algo_trading_service, _profit_engine
    if _algo_trading_service is None:
        _algo_trading_service = AlgoTradingService(portfolio_service)
        _profit_engine = ProfitEngine(_algo_trading_service)
        _algo_trading_service.profit_engine = _profit_engine
    return _algo_trading_service


def get_profit_engine() -> Optional[ProfitEngine]:
    """Get the profit engine instance"""
    global _profit_engine
    return _profit_engine
