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
    
    # DCA specific
    dca_interval_hours: int = 24
    dca_amount: float = 100.0
    
    # Performance tracking
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    
    # State
    last_trade_at: str = ""
    daily_trades_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100


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
        """Initialize price history for technical analysis"""
        if not self.portfolio_service:
            return
            
        market_data = self.portfolio_service.MARKET_DATA
        for symbol, data in market_data.items():
            current_price = data["price"]
            volatility = 0.02 if data["class"].value != "crypto" else 0.05
            
            # Generate 200 days of historical prices
            history = deque(maxlen=200)
            price = current_price * 0.85  # Start lower
            for i in range(200):
                change = random.gauss(0.0003, volatility / math.sqrt(365))
                price = price * (1 + change)
                history.append({
                    "price": price,
                    "volume": random.uniform(1000000, 10000000),
                    "timestamp": (datetime.now() - timedelta(days=200-i)).isoformat()
                })
            # Adjust last price to match current
            history[-1]["price"] = current_price
            self.price_history[symbol] = history
    
    def calculate_indicators(self, symbol: str) -> TechnicalIndicators:
        """Calculate all technical indicators for a symbol"""
        if symbol not in self.price_history:
            return TechnicalIndicators(symbol=symbol, timestamp=datetime.now().isoformat())
        
        history = list(self.price_history[symbol])
        prices = [h["price"] for h in history]
        volumes = [h.get("volume", 0) for h in history]
        
        current_price = prices[-1] if prices else 0
        
        # Calculate Moving Averages
        sma_20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else current_price
        sma_50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else current_price
        sma_200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else current_price
        
        # Calculate EMA
        ema_12 = self._calculate_ema(prices, 12)
        ema_26 = self._calculate_ema(prices, 26)
        
        # Calculate RSI
        rsi = self._calculate_rsi(prices, 14)
        
        # Calculate MACD
        macd_line = ema_12 - ema_26
        macd_signal = self._calculate_ema([macd_line] * 9, 9)  # Simplified
        macd_histogram = macd_line - macd_signal
        
        # Calculate Bollinger Bands
        std_20 = self._calculate_std(prices[-20:]) if len(prices) >= 20 else 0
        bb_upper = sma_20 + (2 * std_20)
        bb_lower = sma_20 - (2 * std_20)
        
        # Calculate ATR
        atr = self._calculate_atr(prices, 14)
        
        # Calculate volatility
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        volatility = self._calculate_std(returns[-30:]) * math.sqrt(365) if len(returns) >= 30 else 0.2
        
        # Support/Resistance (simplified)
        recent_lows = min(prices[-20:]) if len(prices) >= 20 else current_price * 0.95
        recent_highs = max(prices[-20:]) if len(prices) >= 20 else current_price * 1.05
        
        indicators = TechnicalIndicators(
            symbol=symbol,
            timestamp=datetime.now().isoformat(),
            current_price=current_price,
            price_change_24h=((current_price / prices[-2]) - 1) * 100 if len(prices) >= 2 else 0,
            price_change_7d=((current_price / prices[-7]) - 1) * 100 if len(prices) >= 7 else 0,
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
            volume_change=((volumes[-1] / volumes[-2]) - 1) * 100 if len(volumes) >= 2 else 0,
            volatility=volatility,
            atr_14=atr,
            support_level=recent_lows,
            resistance_level=recent_highs
        )
        
        self.indicators_cache[symbol] = indicators
        return indicators
    
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
        """Get bot performance metrics"""
        bot = self.bots.get(bot_id)
        if not bot:
            return {"error": "Bot not found"}
        
        return {
            "bot_id": bot_id,
            "name": bot.name,
            "strategy": bot.strategy.value,
            "status": "running" if bot.is_active else "stopped",
            "performance": {
                "total_trades": bot.total_trades,
                "winning_trades": bot.winning_trades,
                "win_rate": bot.win_rate,
                "total_pnl": bot.total_pnl,
                "max_drawdown": bot.max_drawdown,
                "sharpe_ratio": bot.sharpe_ratio
            },
            "settings": {
                "symbols": bot.symbols,
                "max_position_size": bot.max_position_size,
                "max_daily_trades": bot.max_daily_trades,
                "stop_loss_pct": bot.stop_loss_pct,
                "take_profit_pct": bot.take_profit_pct
            },
            "activity": {
                "daily_trades": bot.daily_trades_count,
                "last_trade": bot.last_trade_at
            },
            "created_at": bot.created_at,
            "updated_at": bot.updated_at
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
        """Get market overview with signals for major assets"""
        if not self.portfolio_service:
            return {"error": "Portfolio service not available"}
        
        overview = {
            "timestamp": datetime.now().isoformat(),
            "assets": []
        }
        
        for symbol in ["SPY", "QQQ", "BTC", "ETH", "GLD", "BND"]:
            indicators = self.calculate_indicators(symbol)
            signal = self.generate_signal(symbol, TradingStrategy.MOMENTUM)
            
            overview["assets"].append({
                "symbol": symbol,
                "name": self.portfolio_service.MARKET_DATA.get(symbol, {}).get("name", symbol),
                "price": indicators.current_price,
                "change_24h": indicators.price_change_24h,
                "rsi": indicators.rsi_14,
                "signal": signal.signal_type.value,
                "confidence": signal.confidence
            })
        
        return overview


# Singleton instance
_algo_trading_service: Optional[AlgoTradingService] = None


def get_algo_trading_service(portfolio_service=None) -> AlgoTradingService:
    """Get singleton instance of algo trading service"""
    global _algo_trading_service
    if _algo_trading_service is None:
        _algo_trading_service = AlgoTradingService(portfolio_service)
    return _algo_trading_service
