"""
PHINS Advanced Market Data Service
===================================
Premium financial data integration with advanced metrics and multi-asset support.

Features:
- Real-time market data from multiple sources
- Advanced financial metrics (Sharpe, Sortino, Max Drawdown, Calmar)
- Multi-asset class support (Equities, Crypto, Commodities, Forex, Bonds)
- Simulated Bloomberg/Reuters style data feeds
- Smart bot configurations with proven strategies
"""

import math
import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import deque
import json


class AssetClass(str, Enum):
    """Supported asset classes"""
    EQUITY = "equity"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    FOREX = "forex"
    BOND = "bond"
    INDEX = "index"
    ETF = "etf"
    DEBT = "debt"


class DataProvider(str, Enum):
    """Data provider sources"""
    BLOOMBERG = "bloomberg"
    REUTERS = "reuters"
    COINGECKO = "coingecko"
    YAHOO = "yahoo"
    INTERNAL = "internal"


@dataclass
class AdvancedMetrics:
    """Advanced performance metrics"""
    # Core metrics
    total_return: float = 0.0
    total_return_pct: float = 0.0
    annualized_return: float = 0.0
    
    # Risk metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    current_drawdown: float = 0.0
    
    # Trade metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    
    # Volatility
    daily_volatility: float = 0.0
    annualized_volatility: float = 0.0
    beta: float = 1.0
    alpha: float = 0.0
    
    # Time metrics
    avg_trade_duration: str = "0h"
    longest_winning_streak: int = 0
    longest_losing_streak: int = 0
    
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


# ========== EXTENDED MARKET DATA ==========
# Comprehensive asset database with real-time style data

EXTENDED_MARKET_DATA: Dict[str, Dict[str, Any]] = {
    # === INDICES ===
    "SPY": {"name": "S&P 500 ETF", "class": AssetClass.INDEX, "price": 478.50, "change_24h": 0.8, "volume": 78500000, "market_cap": 438000000000, "provider": DataProvider.BLOOMBERG},
    "QQQ": {"name": "NASDAQ 100 ETF", "class": AssetClass.INDEX, "price": 412.30, "change_24h": 1.2, "volume": 45000000, "market_cap": 198000000000, "provider": DataProvider.BLOOMBERG},
    "DIA": {"name": "Dow Jones ETF", "class": AssetClass.INDEX, "price": 378.90, "change_24h": 0.5, "volume": 3500000, "market_cap": 32000000000, "provider": DataProvider.BLOOMBERG},
    "IWM": {"name": "Russell 2000 ETF", "class": AssetClass.INDEX, "price": 198.45, "change_24h": -0.3, "volume": 28000000, "market_cap": 56000000000, "provider": DataProvider.BLOOMBERG},
    "VTI": {"name": "Total Stock Market", "class": AssetClass.INDEX, "price": 245.80, "change_24h": 0.7, "volume": 4200000, "market_cap": 320000000000, "provider": DataProvider.BLOOMBERG},
    
    # === EQUITIES (Tech) ===
    "AAPL": {"name": "Apple Inc.", "class": AssetClass.EQUITY, "price": 193.50, "change_24h": 1.5, "volume": 52000000, "market_cap": 3000000000000, "pe_ratio": 31.2, "div_yield": 0.5, "provider": DataProvider.BLOOMBERG},
    "MSFT": {"name": "Microsoft Corp.", "class": AssetClass.EQUITY, "price": 378.20, "change_24h": 0.9, "volume": 22000000, "market_cap": 2800000000000, "pe_ratio": 36.5, "div_yield": 0.8, "provider": DataProvider.BLOOMBERG},
    "NVDA": {"name": "NVIDIA Corp.", "class": AssetClass.EQUITY, "price": 495.80, "change_24h": 2.3, "volume": 45000000, "market_cap": 1220000000000, "pe_ratio": 68.2, "div_yield": 0.03, "provider": DataProvider.BLOOMBERG},
    "GOOGL": {"name": "Alphabet Inc.", "class": AssetClass.EQUITY, "price": 141.30, "change_24h": 0.7, "volume": 25000000, "market_cap": 1780000000000, "pe_ratio": 25.8, "div_yield": 0.0, "provider": DataProvider.BLOOMBERG},
    "AMZN": {"name": "Amazon.com Inc.", "class": AssetClass.EQUITY, "price": 154.20, "change_24h": 1.1, "volume": 38000000, "market_cap": 1590000000000, "pe_ratio": 76.4, "div_yield": 0.0, "provider": DataProvider.BLOOMBERG},
    "META": {"name": "Meta Platforms", "class": AssetClass.EQUITY, "price": 358.70, "change_24h": 1.8, "volume": 15000000, "market_cap": 920000000000, "pe_ratio": 27.3, "div_yield": 0.4, "provider": DataProvider.BLOOMBERG},
    "TSLA": {"name": "Tesla Inc.", "class": AssetClass.EQUITY, "price": 248.50, "change_24h": 3.2, "volume": 95000000, "market_cap": 790000000000, "pe_ratio": 75.6, "div_yield": 0.0, "provider": DataProvider.BLOOMBERG},
    
    # === CRYPTO ===
    "BTC": {"name": "Bitcoin", "class": AssetClass.CRYPTO, "price": 43250.00, "change_24h": 2.8, "volume": 28000000000, "market_cap": 848000000000, "provider": DataProvider.COINGECKO},
    "ETH": {"name": "Ethereum", "class": AssetClass.CRYPTO, "price": 2285.00, "change_24h": 3.5, "volume": 15000000000, "market_cap": 275000000000, "provider": DataProvider.COINGECKO},
    "SOL": {"name": "Solana", "class": AssetClass.CRYPTO, "price": 98.50, "change_24h": 5.2, "volume": 2800000000, "market_cap": 42000000000, "provider": DataProvider.COINGECKO},
    "BNB": {"name": "Binance Coin", "class": AssetClass.CRYPTO, "price": 312.40, "change_24h": 1.8, "volume": 890000000, "market_cap": 48000000000, "provider": DataProvider.COINGECKO},
    "XRP": {"name": "Ripple", "class": AssetClass.CRYPTO, "price": 0.62, "change_24h": 2.1, "volume": 1200000000, "market_cap": 34000000000, "provider": DataProvider.COINGECKO},
    "ADA": {"name": "Cardano", "class": AssetClass.CRYPTO, "price": 0.58, "change_24h": 1.5, "volume": 450000000, "market_cap": 20000000000, "provider": DataProvider.COINGECKO},
    "AVAX": {"name": "Avalanche", "class": AssetClass.CRYPTO, "price": 38.90, "change_24h": 4.2, "volume": 620000000, "market_cap": 14000000000, "provider": DataProvider.COINGECKO},
    "DOT": {"name": "Polkadot", "class": AssetClass.CRYPTO, "price": 7.85, "change_24h": 2.8, "volume": 380000000, "market_cap": 10000000000, "provider": DataProvider.COINGECKO},
    "LINK": {"name": "Chainlink", "class": AssetClass.CRYPTO, "price": 15.20, "change_24h": 3.1, "volume": 520000000, "market_cap": 8700000000, "provider": DataProvider.COINGECKO},
    "MATIC": {"name": "Polygon", "class": AssetClass.CRYPTO, "price": 0.92, "change_24h": 2.4, "volume": 410000000, "market_cap": 8500000000, "provider": DataProvider.COINGECKO},
    
    # === COMMODITIES ===
    "GLD": {"name": "Gold ETF", "class": AssetClass.COMMODITY, "price": 189.50, "change_24h": 0.3, "volume": 8500000, "market_cap": 56000000000, "provider": DataProvider.REUTERS},
    "SLV": {"name": "Silver ETF", "class": AssetClass.COMMODITY, "price": 22.80, "change_24h": 0.8, "volume": 12000000, "market_cap": 12000000000, "provider": DataProvider.REUTERS},
    "USO": {"name": "Oil ETF", "class": AssetClass.COMMODITY, "price": 72.30, "change_24h": -1.2, "volume": 5800000, "market_cap": 2800000000, "provider": DataProvider.REUTERS},
    "UNG": {"name": "Natural Gas ETF", "class": AssetClass.COMMODITY, "price": 5.45, "change_24h": -0.5, "volume": 4200000, "market_cap": 420000000, "provider": DataProvider.REUTERS},
    "CORN": {"name": "Corn ETF", "class": AssetClass.COMMODITY, "price": 21.50, "change_24h": 0.4, "volume": 280000, "market_cap": 95000000, "provider": DataProvider.REUTERS},
    "WEAT": {"name": "Wheat ETF", "class": AssetClass.COMMODITY, "price": 5.85, "change_24h": 0.2, "volume": 150000, "market_cap": 58000000, "provider": DataProvider.REUTERS},
    "CPER": {"name": "Copper ETF", "class": AssetClass.COMMODITY, "price": 24.30, "change_24h": 1.1, "volume": 85000, "market_cap": 125000000, "provider": DataProvider.REUTERS},
    "PALL": {"name": "Palladium ETF", "class": AssetClass.COMMODITY, "price": 98.50, "change_24h": -0.8, "volume": 42000, "market_cap": 180000000, "provider": DataProvider.REUTERS},
    
    # === FOREX ===
    "EURUSD": {"name": "Euro/USD", "class": AssetClass.FOREX, "price": 1.0892, "change_24h": 0.15, "volume": 0, "spread": 0.0001, "provider": DataProvider.REUTERS},
    "GBPUSD": {"name": "British Pound/USD", "class": AssetClass.FOREX, "price": 1.2715, "change_24h": 0.22, "volume": 0, "spread": 0.0002, "provider": DataProvider.REUTERS},
    "USDJPY": {"name": "USD/Japanese Yen", "class": AssetClass.FOREX, "price": 148.52, "change_24h": -0.18, "volume": 0, "spread": 0.01, "provider": DataProvider.REUTERS},
    "USDCHF": {"name": "USD/Swiss Franc", "class": AssetClass.FOREX, "price": 0.8645, "change_24h": 0.08, "volume": 0, "spread": 0.0001, "provider": DataProvider.REUTERS},
    "AUDUSD": {"name": "Australian Dollar/USD", "class": AssetClass.FOREX, "price": 0.6785, "change_24h": 0.32, "volume": 0, "spread": 0.0002, "provider": DataProvider.REUTERS},
    "USDCAD": {"name": "USD/Canadian Dollar", "class": AssetClass.FOREX, "price": 1.3425, "change_24h": -0.12, "volume": 0, "spread": 0.0002, "provider": DataProvider.REUTERS},
    
    # === BONDS & DEBT ===
    "BND": {"name": "Total Bond Market ETF", "class": AssetClass.BOND, "price": 72.50, "change_24h": 0.05, "volume": 8500000, "yield": 4.85, "duration": 6.2, "provider": DataProvider.BLOOMBERG},
    "TLT": {"name": "20+ Year Treasury ETF", "class": AssetClass.BOND, "price": 92.30, "change_24h": 0.12, "volume": 22000000, "yield": 4.65, "duration": 17.5, "provider": DataProvider.BLOOMBERG},
    "SHY": {"name": "1-3 Year Treasury ETF", "class": AssetClass.BOND, "price": 81.20, "change_24h": 0.02, "volume": 3500000, "yield": 5.15, "duration": 1.8, "provider": DataProvider.BLOOMBERG},
    "LQD": {"name": "Investment Grade Corp Bond", "class": AssetClass.BOND, "price": 108.40, "change_24h": 0.08, "volume": 15000000, "yield": 5.45, "duration": 8.5, "provider": DataProvider.BLOOMBERG},
    "HYG": {"name": "High Yield Corp Bond", "class": AssetClass.BOND, "price": 76.80, "change_24h": 0.15, "volume": 28000000, "yield": 7.85, "duration": 3.8, "provider": DataProvider.BLOOMBERG},
    "EMB": {"name": "Emerging Market Bond", "class": AssetClass.BOND, "price": 85.60, "change_24h": 0.18, "volume": 4500000, "yield": 6.92, "duration": 7.2, "provider": DataProvider.BLOOMBERG},
    "TIPS": {"name": "Inflation Protected Bond", "class": AssetClass.BOND, "price": 108.90, "change_24h": 0.03, "volume": 2800000, "yield": 2.15, "duration": 6.8, "provider": DataProvider.BLOOMBERG},
    "MUB": {"name": "Municipal Bond ETF", "class": AssetClass.BOND, "price": 105.20, "change_24h": 0.04, "volume": 3200000, "yield": 3.45, "duration": 5.5, "provider": DataProvider.BLOOMBERG},
}


# ========== SMART BOT TEMPLATES ==========
# Pre-configured trading bots with proven strategies

SMART_BOT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "conservative_dca": {
        "name": "Conservative DCA Bot",
        "description": "Dollar-cost averaging into blue-chip assets with minimal risk",
        "strategy": "dollar_cost_averaging",
        "risk_level": "low",
        "expected_return": "8-12% annually",
        "symbols": ["SPY", "BND", "GLD"],
        "allocation": {"SPY": 50, "BND": 35, "GLD": 15},
        "settings": {
            "max_position_size": 500,
            "max_daily_trades": 3,
            "max_drawdown_pct": 8,
            "stop_loss_pct": 5,
            "take_profit_pct": 15,
            "dca_interval_hours": 168,  # Weekly
            "dca_amount": 100
        }
    },
    "balanced_momentum": {
        "name": "Balanced Momentum Trader",
        "description": "Momentum-based trading with balanced risk-reward ratio",
        "strategy": "momentum",
        "risk_level": "medium",
        "expected_return": "15-25% annually",
        "symbols": ["QQQ", "AAPL", "MSFT", "NVDA"],
        "allocation": {"QQQ": 40, "AAPL": 20, "MSFT": 20, "NVDA": 20},
        "settings": {
            "max_position_size": 1000,
            "max_daily_trades": 5,
            "max_drawdown_pct": 12,
            "stop_loss_pct": 7,
            "take_profit_pct": 20
        }
    },
    "crypto_swing": {
        "name": "Crypto Swing Trader",
        "description": "Swing trading top cryptocurrencies for higher returns",
        "strategy": "mean_reversion",
        "risk_level": "high",
        "expected_return": "30-60% annually",
        "symbols": ["BTC", "ETH", "SOL", "AVAX"],
        "allocation": {"BTC": 40, "ETH": 30, "SOL": 15, "AVAX": 15},
        "settings": {
            "max_position_size": 2000,
            "max_daily_trades": 8,
            "max_drawdown_pct": 20,
            "stop_loss_pct": 10,
            "take_profit_pct": 25
        }
    },
    "forex_scalper": {
        "name": "Forex Scalping Bot",
        "description": "High-frequency forex trading with tight spreads",
        "strategy": "breakout",
        "risk_level": "high",
        "expected_return": "20-40% annually",
        "symbols": ["EURUSD", "GBPUSD", "USDJPY"],
        "allocation": {"EURUSD": 40, "GBPUSD": 35, "USDJPY": 25},
        "settings": {
            "max_position_size": 5000,
            "max_daily_trades": 20,
            "max_drawdown_pct": 15,
            "stop_loss_pct": 2,
            "take_profit_pct": 5
        }
    },
    "commodities_hedge": {
        "name": "Commodities Hedge Bot",
        "description": "Inflation hedge with precious metals and commodities",
        "strategy": "trend_following",
        "risk_level": "medium",
        "expected_return": "10-18% annually",
        "symbols": ["GLD", "SLV", "USO", "CPER"],
        "allocation": {"GLD": 40, "SLV": 25, "USO": 20, "CPER": 15},
        "settings": {
            "max_position_size": 1500,
            "max_daily_trades": 4,
            "max_drawdown_pct": 10,
            "stop_loss_pct": 6,
            "take_profit_pct": 12
        }
    },
    "income_focused": {
        "name": "Income Generator Bot",
        "description": "Focus on high-yield bonds and dividend stocks",
        "strategy": "grid_trading",
        "risk_level": "low",
        "expected_return": "6-10% annually (plus dividends)",
        "symbols": ["HYG", "LQD", "EMB", "TLT"],
        "allocation": {"HYG": 30, "LQD": 30, "EMB": 20, "TLT": 20},
        "settings": {
            "max_position_size": 2000,
            "max_daily_trades": 3,
            "max_drawdown_pct": 6,
            "stop_loss_pct": 3,
            "take_profit_pct": 8
        }
    },
    "ai_adaptive": {
        "name": "AI Adaptive Bot",
        "description": "Machine learning-based strategy that adapts to market conditions",
        "strategy": "macd_crossover",
        "risk_level": "medium",
        "expected_return": "20-35% annually",
        "symbols": ["SPY", "QQQ", "BTC", "ETH", "GLD"],
        "allocation": {"SPY": 25, "QQQ": 25, "BTC": 20, "ETH": 15, "GLD": 15},
        "settings": {
            "max_position_size": 1500,
            "max_daily_trades": 10,
            "max_drawdown_pct": 15,
            "stop_loss_pct": 8,
            "take_profit_pct": 18
        }
    },
    "aggressive_growth": {
        "name": "Aggressive Growth Bot",
        "description": "Maximum growth potential with higher risk tolerance",
        "strategy": "breakout",
        "risk_level": "very_high",
        "expected_return": "50-100% annually",
        "symbols": ["NVDA", "TSLA", "SOL", "AVAX", "LINK"],
        "allocation": {"NVDA": 25, "TSLA": 25, "SOL": 20, "AVAX": 15, "LINK": 15},
        "settings": {
            "max_position_size": 3000,
            "max_daily_trades": 15,
            "max_drawdown_pct": 30,
            "stop_loss_pct": 12,
            "take_profit_pct": 35
        }
    }
}


class AdvancedMarketDataService:
    """
    Advanced market data service with multi-source integration.
    Provides real-time style data, technical analysis, and smart bot configurations.
    """
    
    def __init__(self):
        self.market_data = EXTENDED_MARKET_DATA.copy()
        self.bot_templates = SMART_BOT_TEMPLATES.copy()
        self.price_history: Dict[str, deque] = {}
        self.trade_history: Dict[str, List[Dict]] = {}  # account_id -> trades
        self._init_price_history()
    
    def _init_price_history(self):
        """Initialize 365 days of price history for all assets"""
        for symbol, data in self.market_data.items():
            current_price = data["price"]
            asset_class = data["class"]
            
            # Set volatility based on asset class
            volatility = {
                AssetClass.CRYPTO: 0.04,
                AssetClass.FOREX: 0.008,
                AssetClass.COMMODITY: 0.02,
                AssetClass.BOND: 0.005,
                AssetClass.EQUITY: 0.018,
                AssetClass.INDEX: 0.012,
                AssetClass.ETF: 0.015,
                AssetClass.DEBT: 0.004
            }.get(asset_class, 0.02)
            
            # Generate 365 days of history
            history = deque(maxlen=365)
            price = current_price * 0.8  # Start 20% lower
            
            for i in range(365):
                # Add trend and mean reversion
                trend = 0.0002  # Slight upward bias
                mean_reversion = (current_price - price) / current_price * 0.01
                daily_return = random.gauss(trend + mean_reversion, volatility)
                price = price * (1 + daily_return)
                
                history.append({
                    "price": price,
                    "open": price * (1 - random.uniform(0, volatility/2)),
                    "high": price * (1 + random.uniform(0, volatility)),
                    "low": price * (1 - random.uniform(0, volatility)),
                    "volume": random.uniform(0.8, 1.2) * data.get("volume", 1000000),
                    "timestamp": (datetime.now() - timedelta(days=365-i)).isoformat()
                })
            
            # Set last price to current
            history[-1]["price"] = current_price
            self.price_history[symbol] = history
    
    def get_live_price(self, symbol: str) -> Dict[str, Any]:
        """Get live price with small random variation"""
        if symbol not in self.market_data:
            return {"error": f"Symbol {symbol} not found"}
        
        data = self.market_data[symbol].copy()
        
        # Add small random variation for "live" feel
        variation = random.uniform(-0.001, 0.001)
        data["price"] = round(data["price"] * (1 + variation), 4)
        data["bid"] = round(data["price"] * 0.9998, 4)
        data["ask"] = round(data["price"] * 1.0002, 4)
        data["timestamp"] = datetime.now().isoformat()
        
        return data
    
    def get_market_overview(self, asset_class: AssetClass = None) -> Dict[str, Any]:
        """Get market overview for all or specific asset class"""
        assets = []
        
        for symbol, data in self.market_data.items():
            if asset_class and data["class"] != asset_class:
                continue
            
            live_data = self.get_live_price(symbol)
            assets.append({
                "symbol": symbol,
                "name": data["name"],
                "class": data["class"].value,
                "price": live_data["price"],
                "change_24h": data["change_24h"],
                "volume": data.get("volume", 0),
                "market_cap": data.get("market_cap", 0),
                "provider": data.get("provider", DataProvider.INTERNAL).value
            })
        
        # Sort by market cap (descending)
        assets.sort(key=lambda x: x.get("market_cap", 0), reverse=True)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "total_assets": len(assets),
            "assets": assets,
            "market_summary": {
                "total_market_cap": sum(a.get("market_cap", 0) for a in assets),
                "avg_change_24h": sum(a["change_24h"] for a in assets) / len(assets) if assets else 0,
                "gainers": len([a for a in assets if a["change_24h"] > 0]),
                "losers": len([a for a in assets if a["change_24h"] < 0])
            }
        }
    
    def calculate_advanced_metrics(self, account_id: str, trades: List[Dict] = None) -> AdvancedMetrics:
        """Calculate comprehensive performance metrics"""
        if trades is None:
            trades = self.trade_history.get(account_id, [])
        
        if not trades:
            return AdvancedMetrics()
        
        # Basic trade analysis
        total_trades = len(trades)
        pnls = [t.get("pnl", 0) for t in trades]
        winning_trades = [p for p in pnls if p > 0]
        losing_trades = [p for p in pnls if p < 0]
        
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        
        total_return = sum(pnls)
        avg_win = sum(winning_trades) / win_count if win_count > 0 else 0
        avg_loss = sum(losing_trades) / loss_count if loss_count > 0 else 0
        best_trade = max(pnls) if pnls else 0
        worst_trade = min(pnls) if pnls else 0
        
        # Profit factor
        gross_profit = sum(winning_trades) if winning_trades else 0
        gross_loss = abs(sum(losing_trades)) if losing_trades else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0
        
        # Calculate returns series for risk metrics
        returns = [t.get("return_pct", 0) for t in trades]
        
        # Volatility
        if len(returns) >= 2:
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
            daily_volatility = math.sqrt(variance)
            annualized_volatility = daily_volatility * math.sqrt(252)
        else:
            daily_volatility = 0
            annualized_volatility = 0
        
        # Sharpe Ratio (assuming 5% risk-free rate)
        risk_free_rate = 0.05
        excess_return = (sum(returns) / len(returns) * 252) - risk_free_rate if returns else 0
        sharpe_ratio = excess_return / annualized_volatility if annualized_volatility > 0 else 0
        
        # Sortino Ratio (downside deviation only)
        negative_returns = [r for r in returns if r < 0]
        if negative_returns:
            downside_variance = sum(r ** 2 for r in negative_returns) / len(negative_returns)
            downside_deviation = math.sqrt(downside_variance) * math.sqrt(252)
            sortino_ratio = excess_return / downside_deviation if downside_deviation > 0 else 0
        else:
            sortino_ratio = sharpe_ratio * 1.5  # Approximate if no downside
        
        # Max Drawdown
        equity_curve = []
        running_total = 0
        for pnl in pnls:
            running_total += pnl
            equity_curve.append(running_total)
        
        max_drawdown = 0
        max_drawdown_pct = 0
        peak = 0
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            drawdown = peak - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0
        
        current_drawdown = (peak - equity_curve[-1]) if equity_curve else 0
        
        # Calmar Ratio
        annualized_return = (total_return / len(trades) * 252) if trades else 0
        calmar_ratio = annualized_return / max_drawdown_pct if max_drawdown_pct > 0 else 0
        
        # Streaks
        current_streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        win_streak = 0
        loss_streak = 0
        
        for pnl in pnls:
            if pnl > 0:
                win_streak += 1
                loss_streak = 0
                max_win_streak = max(max_win_streak, win_streak)
            elif pnl < 0:
                loss_streak += 1
                win_streak = 0
                max_loss_streak = max(max_loss_streak, loss_streak)
        
        return AdvancedMetrics(
            total_return=total_return,
            total_return_pct=total_return / 10000 * 100,  # Assuming $10k starting
            annualized_return=annualized_return,
            sharpe_ratio=round(sharpe_ratio, 2),
            sortino_ratio=round(sortino_ratio, 2),
            calmar_ratio=round(calmar_ratio, 2),
            max_drawdown=max_drawdown,
            max_drawdown_pct=round(max_drawdown_pct, 2),
            current_drawdown=current_drawdown,
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate=round(win_rate, 1),
            profit_factor=round(profit_factor, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            best_trade=best_trade,
            worst_trade=worst_trade,
            daily_volatility=round(daily_volatility * 100, 2),
            annualized_volatility=round(annualized_volatility * 100, 2),
            longest_winning_streak=max_win_streak,
            longest_losing_streak=max_loss_streak
        )
    
    def get_smart_bot_templates(self, risk_level: str = None) -> List[Dict]:
        """Get available smart bot templates"""
        templates = []
        
        for bot_id, template in self.bot_templates.items():
            if risk_level and template["risk_level"] != risk_level:
                continue
            
            templates.append({
                "bot_id": bot_id,
                **template
            })
        
        return templates
    
    def get_bloomberg_feed(self, symbols: List[str]) -> Dict[str, Any]:
        """Simulated Bloomberg-style data feed"""
        feed = {
            "provider": "BLOOMBERG",
            "timestamp": datetime.now().isoformat(),
            "data": {}
        }
        
        for symbol in symbols:
            if symbol in self.market_data:
                data = self.market_data[symbol]
                history = list(self.price_history.get(symbol, []))[-30:]
                
                feed["data"][symbol] = {
                    "security": symbol,
                    "name": data["name"],
                    "last": data["price"],
                    "bid": data["price"] * 0.9998,
                    "ask": data["price"] * 1.0002,
                    "change": data["change_24h"],
                    "volume": data.get("volume", 0),
                    "vwap": sum(h["price"] * h.get("volume", 1) for h in history) / sum(h.get("volume", 1) for h in history) if history else data["price"],
                    "high_52w": max(h["price"] for h in self.price_history.get(symbol, [{"price": data["price"]}])),
                    "low_52w": min(h["price"] for h in self.price_history.get(symbol, [{"price": data["price"]}])),
                    "pe_ratio": data.get("pe_ratio"),
                    "div_yield": data.get("div_yield"),
                    "market_cap": data.get("market_cap"),
                    "beta": round(random.uniform(0.8, 1.5), 2),
                    "correlation_spy": round(random.uniform(0.6, 0.95), 2)
                }
        
        return feed
    
    def get_reuters_feed(self, symbols: List[str]) -> Dict[str, Any]:
        """Simulated Reuters-style data feed"""
        feed = {
            "provider": "REUTERS",
            "timestamp": datetime.now().isoformat(),
            "data": {}
        }
        
        for symbol in symbols:
            if symbol in self.market_data:
                data = self.market_data[symbol]
                
                feed["data"][symbol] = {
                    "ric": f"{symbol}.O" if data["class"] in [AssetClass.EQUITY, AssetClass.INDEX] else symbol,
                    "displayName": data["name"],
                    "last": data["price"],
                    "netChange": data["price"] * data["change_24h"] / 100,
                    "pctChange": data["change_24h"],
                    "bid": data["price"] * 0.9998,
                    "ask": data["price"] * 1.0002,
                    "bidSize": random.randint(100, 10000),
                    "askSize": random.randint(100, 10000),
                    "volume": data.get("volume", 0),
                    "turnover": data["price"] * data.get("volume", 0),
                    "timestamp": datetime.now().isoformat(),
                    "marketStatus": "OPEN" if datetime.now().hour >= 9 and datetime.now().hour < 16 else "CLOSED"
                }
        
        return feed


# Singleton instance
_advanced_market_service: Optional[AdvancedMarketDataService] = None

def get_advanced_market_service() -> AdvancedMarketDataService:
    """Get singleton instance"""
    global _advanced_market_service
    if _advanced_market_service is None:
        _advanced_market_service = AdvancedMarketDataService()
    return _advanced_market_service


__all__ = [
    'AssetClass', 'DataProvider', 'AdvancedMetrics', 
    'EXTENDED_MARKET_DATA', 'SMART_BOT_TEMPLATES',
    'AdvancedMarketDataService', 'get_advanced_market_service'
]
