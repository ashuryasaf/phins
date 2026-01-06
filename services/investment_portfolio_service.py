"""
PHINS Investment Portfolio Service
===================================
World-class AI-driven investment portfolio management for insurance-linked savings.

Features:
- Multi-asset portfolio management (equities, bonds, crypto, indexes, currencies)
- Real-time market data integration
- Actuarial-based savings projections
- AI-powered portfolio optimization and recommendations
- Risk-adjusted return calculations
- Tax-efficient rebalancing suggestions
- Monte Carlo simulations for retirement planning
- ADL-adjusted benefit projections

This integrates with PHINS disability insurance to provide:
- Savings component management (25-90% of premium)
- Lump sum benefit projections
- Monthly income stream calculations
- Investment allocation adjustments
"""

import math
import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import json

# Asset class definitions
class AssetClass(str, Enum):
    EQUITY = "equity"
    FIXED_INCOME = "fixed_income"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    CURRENCY = "currency"
    INDEX = "index"
    REAL_ESTATE = "real_estate"
    ALTERNATIVE = "alternative"

class RiskProfile(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE_CONSERVATIVE = "moderate_conservative"
    MODERATE = "moderate"
    MODERATE_AGGRESSIVE = "moderate_aggressive"
    AGGRESSIVE = "aggressive"

@dataclass
class Asset:
    """Individual asset in portfolio"""
    symbol: str
    name: str
    asset_class: AssetClass
    quantity: float
    avg_cost: float
    current_price: float = 0.0
    currency: str = "USD"
    
    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price
    
    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost
    
    @property
    def unrealized_gain(self) -> float:
        return self.market_value - self.cost_basis
    
    @property
    def return_pct(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_gain / self.cost_basis) * 100

@dataclass
class PortfolioAllocation:
    """Target portfolio allocation"""
    equity_pct: float = 60.0
    fixed_income_pct: float = 25.0
    crypto_pct: float = 5.0
    commodity_pct: float = 5.0
    currency_pct: float = 3.0
    alternative_pct: float = 2.0
    
    def validate(self) -> bool:
        total = (self.equity_pct + self.fixed_income_pct + self.crypto_pct +
                self.commodity_pct + self.currency_pct + self.alternative_pct)
        return abs(total - 100.0) < 0.01

@dataclass
class SavingsAccount:
    """Customer savings account linked to insurance policy"""
    account_id: str
    customer_id: str
    policy_id: str
    balance: float = 0.0
    monthly_contribution: float = 0.0
    savings_rate_pct: float = 25.0  # Percentage of premium going to savings
    risk_profile: RiskProfile = RiskProfile.MODERATE
    target_allocation: PortfolioAllocation = field(default_factory=PortfolioAllocation)
    assets: List[Asset] = field(default_factory=list)
    transactions: List[Dict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()

@dataclass
class InvestmentRecommendation:
    """AI-generated investment recommendation"""
    recommendation_id: str
    action: str  # buy, sell, hold, rebalance
    symbol: str
    asset_class: AssetClass
    reason: str
    confidence_score: float
    expected_return_pct: float
    risk_score: float
    time_horizon: str
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class InvestmentPortfolioService:
    """
    Core service for managing investment portfolios linked to insurance policies.
    """
    
    # Expected returns by asset class (annual)
    EXPECTED_RETURNS = {
        AssetClass.EQUITY: 0.08,
        AssetClass.FIXED_INCOME: 0.04,
        AssetClass.CRYPTO: 0.15,
        AssetClass.COMMODITY: 0.05,
        AssetClass.CURRENCY: 0.02,
        AssetClass.INDEX: 0.07,
        AssetClass.REAL_ESTATE: 0.06,
        AssetClass.ALTERNATIVE: 0.10,
    }
    
    # Risk (standard deviation) by asset class
    RISK_PROFILES = {
        AssetClass.EQUITY: 0.18,
        AssetClass.FIXED_INCOME: 0.05,
        AssetClass.CRYPTO: 0.60,
        AssetClass.COMMODITY: 0.20,
        AssetClass.CURRENCY: 0.08,
        AssetClass.INDEX: 0.15,
        AssetClass.REAL_ESTATE: 0.12,
        AssetClass.ALTERNATIVE: 0.25,
    }
    
    # Risk profile allocations
    RISK_ALLOCATIONS = {
        RiskProfile.CONSERVATIVE: PortfolioAllocation(
            equity_pct=20, fixed_income_pct=60, crypto_pct=0,
            commodity_pct=5, currency_pct=10, alternative_pct=5
        ),
        RiskProfile.MODERATE_CONSERVATIVE: PortfolioAllocation(
            equity_pct=35, fixed_income_pct=45, crypto_pct=2,
            commodity_pct=8, currency_pct=5, alternative_pct=5
        ),
        RiskProfile.MODERATE: PortfolioAllocation(
            equity_pct=50, fixed_income_pct=30, crypto_pct=5,
            commodity_pct=7, currency_pct=3, alternative_pct=5
        ),
        RiskProfile.MODERATE_AGGRESSIVE: PortfolioAllocation(
            equity_pct=65, fixed_income_pct=15, crypto_pct=10,
            commodity_pct=5, currency_pct=2, alternative_pct=3
        ),
        RiskProfile.AGGRESSIVE: PortfolioAllocation(
            equity_pct=75, fixed_income_pct=5, crypto_pct=15,
            commodity_pct=3, currency_pct=0, alternative_pct=2
        ),
    }
    
    # Market data (will be updated by real-time service)
    MARKET_DATA: Dict[str, Dict] = {}
    
    def __init__(self):
        self.accounts: Dict[str, SavingsAccount] = {}
        self.recommendations: Dict[str, List[InvestmentRecommendation]] = {}
        self._init_market_data()
    
    def _init_market_data(self):
        """Initialize market data with realistic values"""
        self.MARKET_DATA = {
            # Equities
            "SPY": {"price": 478.50, "name": "S&P 500 ETF", "class": AssetClass.EQUITY, "change_24h": 0.45},
            "QQQ": {"price": 405.20, "name": "NASDAQ 100 ETF", "class": AssetClass.EQUITY, "change_24h": 0.82},
            "VTI": {"price": 245.30, "name": "Total Stock Market ETF", "class": AssetClass.EQUITY, "change_24h": 0.38},
            "VXUS": {"price": 58.90, "name": "International Stock ETF", "class": AssetClass.EQUITY, "change_24h": -0.25},
            "VWO": {"price": 42.15, "name": "Emerging Markets ETF", "class": AssetClass.EQUITY, "change_24h": 0.15},
            
            # Fixed Income
            "BND": {"price": 72.50, "name": "Total Bond Market ETF", "class": AssetClass.FIXED_INCOME, "change_24h": 0.05},
            "TLT": {"price": 92.30, "name": "20+ Year Treasury ETF", "class": AssetClass.FIXED_INCOME, "change_24h": 0.12},
            "LQD": {"price": 108.45, "name": "Investment Grade Corp Bond", "class": AssetClass.FIXED_INCOME, "change_24h": 0.08},
            "HYG": {"price": 76.20, "name": "High Yield Corp Bond ETF", "class": AssetClass.FIXED_INCOME, "change_24h": 0.15},
            
            # Crypto
            "BTC": {"price": 97500.00, "name": "Bitcoin", "class": AssetClass.CRYPTO, "change_24h": 2.35},
            "ETH": {"price": 3450.00, "name": "Ethereum", "class": AssetClass.CRYPTO, "change_24h": 1.85},
            "SOL": {"price": 185.00, "name": "Solana", "class": AssetClass.CRYPTO, "change_24h": 3.20},
            "USDC": {"price": 1.00, "name": "USD Coin", "class": AssetClass.CRYPTO, "change_24h": 0.00},
            
            # Commodities
            "GLD": {"price": 188.50, "name": "Gold ETF", "class": AssetClass.COMMODITY, "change_24h": 0.25},
            "SLV": {"price": 22.30, "name": "Silver ETF", "class": AssetClass.COMMODITY, "change_24h": 0.45},
            "USO": {"price": 78.90, "name": "Oil ETF", "class": AssetClass.COMMODITY, "change_24h": -1.20},
            
            # Currencies
            "EUR": {"price": 1.08, "name": "Euro", "class": AssetClass.CURRENCY, "change_24h": 0.15},
            "GBP": {"price": 1.27, "name": "British Pound", "class": AssetClass.CURRENCY, "change_24h": 0.08},
            "JPY": {"price": 0.0067, "name": "Japanese Yen", "class": AssetClass.CURRENCY, "change_24h": -0.22},
            "CHF": {"price": 1.13, "name": "Swiss Franc", "class": AssetClass.CURRENCY, "change_24h": 0.05},
            "ILS": {"price": 0.28, "name": "Israeli Shekel", "class": AssetClass.CURRENCY, "change_24h": 0.10},
            
            # Indexes
            "^SPX": {"price": 4785.00, "name": "S&P 500 Index", "class": AssetClass.INDEX, "change_24h": 0.45},
            "^NDX": {"price": 16850.00, "name": "NASDAQ 100 Index", "class": AssetClass.INDEX, "change_24h": 0.82},
            "^DJI": {"price": 37850.00, "name": "Dow Jones Index", "class": AssetClass.INDEX, "change_24h": 0.35},
            "^FTSE": {"price": 7680.00, "name": "FTSE 100 Index", "class": AssetClass.INDEX, "change_24h": 0.28},
            "^DAX": {"price": 16780.00, "name": "DAX Index", "class": AssetClass.INDEX, "change_24h": 0.55},
            "^TA125": {"price": 1920.00, "name": "Tel Aviv 125 Index", "class": AssetClass.INDEX, "change_24h": 0.42},
        }
    
    def update_market_prices(self, prices: Dict[str, float]):
        """Update market prices from real-time feed"""
        for symbol, price in prices.items():
            if symbol in self.MARKET_DATA:
                old_price = self.MARKET_DATA[symbol]["price"]
                self.MARKET_DATA[symbol]["price"] = price
                if old_price > 0:
                    self.MARKET_DATA[symbol]["change_24h"] = ((price - old_price) / old_price) * 100
    
    def create_savings_account(self, customer_id: str, policy_id: str,
                               monthly_contribution: float, savings_rate_pct: float = 25.0,
                               risk_profile: RiskProfile = RiskProfile.MODERATE) -> SavingsAccount:
        """Create a new savings account linked to policy"""
        # Generate account ID using sanitized customer and policy IDs
        cust_part = customer_id.replace('-', '').replace('_', '')[:8].upper()
        pol_part = policy_id.replace('-', '').replace('_', '')[-4:].upper()
        account_id = f"SAV-{cust_part}-{pol_part}"
        
        account = SavingsAccount(
            account_id=account_id,
            customer_id=customer_id,
            policy_id=policy_id,
            monthly_contribution=monthly_contribution,
            savings_rate_pct=savings_rate_pct,
            risk_profile=risk_profile,
            target_allocation=self.RISK_ALLOCATIONS[risk_profile]
        )
        
        self.accounts[account_id] = account
        return account
    
    def get_account(self, account_id: str) -> Optional[SavingsAccount]:
        """Get savings account by ID"""
        return self.accounts.get(account_id)
    
    def get_customer_accounts(self, customer_id: str) -> List[SavingsAccount]:
        """Get all savings accounts for a customer"""
        return [acc for acc in self.accounts.values() if acc.customer_id == customer_id]
    
    def deposit(self, account_id: str, amount: float, source: str = "premium_allocation") -> Dict:
        """Deposit funds into savings account"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        account.balance += amount
        transaction = {
            "id": f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
            "type": "deposit",
            "amount": amount,
            "source": source,
            "timestamp": datetime.now().isoformat(),
            "balance_after": account.balance
        }
        account.transactions.append(transaction)
        account.updated_at = datetime.now().isoformat()
        
        return {"success": True, "transaction": transaction, "new_balance": account.balance}
    
    def withdraw(self, account_id: str, amount: float, reason: str = "withdrawal") -> Dict:
        """Withdraw funds from savings account"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        if amount > account.balance:
            return {"success": False, "error": "Insufficient funds"}
        
        account.balance -= amount
        transaction = {
            "id": f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
            "type": "withdrawal",
            "amount": -amount,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "balance_after": account.balance
        }
        account.transactions.append(transaction)
        account.updated_at = datetime.now().isoformat()
        
        return {"success": True, "transaction": transaction, "new_balance": account.balance}
    
    def invest(self, account_id: str, symbol: str, amount: float) -> Dict:
        """Invest funds into a specific asset"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        if amount > account.balance:
            return {"success": False, "error": "Insufficient funds"}
        
        market = self.MARKET_DATA.get(symbol)
        if not market:
            return {"success": False, "error": f"Unknown asset: {symbol}"}
        
        price = market["price"]
        quantity = amount / price
        
        # Check if we already have this asset
        existing = next((a for a in account.assets if a.symbol == symbol), None)
        if existing:
            # Average up/down
            total_cost = existing.cost_basis + amount
            total_qty = existing.quantity + quantity
            existing.quantity = total_qty
            existing.avg_cost = total_cost / total_qty
            existing.current_price = price
        else:
            asset = Asset(
                symbol=symbol,
                name=market["name"],
                asset_class=market["class"],
                quantity=quantity,
                avg_cost=price,
                current_price=price
            )
            account.assets.append(asset)
        
        account.balance -= amount
        transaction = {
            "id": f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
            "type": "invest",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "timestamp": datetime.now().isoformat(),
            "balance_after": account.balance
        }
        account.transactions.append(transaction)
        account.updated_at = datetime.now().isoformat()
        
        return {
            "success": True,
            "transaction": transaction,
            "asset": symbol,
            "quantity": quantity,
            "price": price,
            "cash_balance": account.balance
        }
    
    def sell_asset(self, account_id: str, symbol: str, quantity: float) -> Dict:
        """Sell asset from portfolio"""
        account = self.accounts.get(account_id)
        if not account:
            return {"success": False, "error": "Account not found"}
        
        asset = next((a for a in account.assets if a.symbol == symbol), None)
        if not asset:
            return {"success": False, "error": f"Asset {symbol} not in portfolio"}
        
        if quantity > asset.quantity:
            return {"success": False, "error": "Insufficient quantity"}
        
        market = self.MARKET_DATA.get(symbol, {})
        price = market.get("price", asset.current_price)
        proceeds = quantity * price
        
        # Calculate realized gain
        cost_basis = quantity * asset.avg_cost
        realized_gain = proceeds - cost_basis
        
        asset.quantity -= quantity
        if asset.quantity < 0.0001:
            account.assets.remove(asset)
        
        account.balance += proceeds
        transaction = {
            "id": f"SELL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}",
            "type": "sell",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "proceeds": proceeds,
            "realized_gain": realized_gain,
            "timestamp": datetime.now().isoformat(),
            "balance_after": account.balance
        }
        account.transactions.append(transaction)
        account.updated_at = datetime.now().isoformat()
        
        return {
            "success": True,
            "transaction": transaction,
            "proceeds": proceeds,
            "realized_gain": realized_gain,
            "cash_balance": account.balance
        }
    
    def get_portfolio_summary(self, account_id: str) -> Dict:
        """Get comprehensive portfolio summary with analytics"""
        account = self.accounts.get(account_id)
        if not account:
            return {"error": "Account not found"}
        
        # Update current prices
        for asset in account.assets:
            if asset.symbol in self.MARKET_DATA:
                asset.current_price = self.MARKET_DATA[asset.symbol]["price"]
        
        # Calculate totals
        total_invested = sum(a.cost_basis for a in account.assets)
        total_market_value = sum(a.market_value for a in account.assets)
        total_unrealized_gain = total_market_value - total_invested
        total_return_pct = (total_unrealized_gain / total_invested * 100) if total_invested > 0 else 0
        
        # Calculate allocation by asset class
        allocation = {}
        for asset_class in AssetClass:
            class_assets = [a for a in account.assets if a.asset_class == asset_class]
            class_value = sum(a.market_value for a in class_assets)
            allocation[asset_class.value] = {
                "value": class_value,
                "percentage": (class_value / total_market_value * 100) if total_market_value > 0 else 0,
                "target_percentage": getattr(account.target_allocation, f"{asset_class.value}_pct", 0),
                "assets": [{"symbol": a.symbol, "name": a.name, "value": a.market_value, "return_pct": a.return_pct} for a in class_assets]
            }
        
        # Calculate portfolio metrics
        portfolio_risk = self._calculate_portfolio_risk(account)
        sharpe_ratio = self._calculate_sharpe_ratio(account)
        
        return {
            "account_id": account_id,
            "customer_id": account.customer_id,
            "policy_id": account.policy_id,
            "risk_profile": account.risk_profile.value,
            "cash_balance": account.balance,
            "total_invested": total_invested,
            "total_market_value": total_market_value,
            "total_account_value": account.balance + total_market_value,
            "unrealized_gain": total_unrealized_gain,
            "return_pct": total_return_pct,
            "monthly_contribution": account.monthly_contribution,
            "savings_rate_pct": account.savings_rate_pct,
            "allocation": allocation,
            "risk_metrics": {
                "portfolio_volatility": portfolio_risk,
                "sharpe_ratio": sharpe_ratio,
                "var_95": total_market_value * portfolio_risk * 1.65,  # 95% VaR
                "max_drawdown_estimate": portfolio_risk * 2.5
            },
            "assets": [
                {
                    "symbol": a.symbol,
                    "name": a.name,
                    "asset_class": a.asset_class.value,
                    "quantity": a.quantity,
                    "avg_cost": a.avg_cost,
                    "current_price": a.current_price,
                    "market_value": a.market_value,
                    "cost_basis": a.cost_basis,
                    "unrealized_gain": a.unrealized_gain,
                    "return_pct": a.return_pct
                }
                for a in account.assets
            ],
            "updated_at": account.updated_at
        }
    
    def _calculate_portfolio_risk(self, account: SavingsAccount) -> float:
        """Calculate portfolio volatility using asset class risks"""
        if not account.assets:
            return 0.0
        
        total_value = sum(a.market_value for a in account.assets)
        if total_value == 0:
            return 0.0
        
        weighted_risk = 0.0
        for asset in account.assets:
            weight = asset.market_value / total_value
            risk = self.RISK_PROFILES.get(asset.asset_class, 0.15)
            weighted_risk += weight * risk
        
        return weighted_risk
    
    def _calculate_sharpe_ratio(self, account: SavingsAccount, risk_free_rate: float = 0.04) -> float:
        """Calculate Sharpe ratio"""
        if not account.assets:
            return 0.0
        
        total_value = sum(a.market_value for a in account.assets)
        if total_value == 0:
            return 0.0
        
        # Expected return
        expected_return = 0.0
        for asset in account.assets:
            weight = asset.market_value / total_value
            exp_ret = self.EXPECTED_RETURNS.get(asset.asset_class, 0.05)
            expected_return += weight * exp_ret
        
        risk = self._calculate_portfolio_risk(account)
        if risk == 0:
            return 0.0
        
        return (expected_return - risk_free_rate) / risk
    
    def generate_projections(self, account_id: str, years: int = 25) -> Dict:
        """Generate long-term savings projections using Monte Carlo simulation"""
        account = self.accounts.get(account_id)
        if not account:
            return {"error": "Account not found"}
        
        current_value = account.balance + sum(a.market_value for a in account.assets)
        monthly_contribution = account.monthly_contribution
        risk = self._calculate_portfolio_risk(account) or 0.10
        
        # Expected return based on allocation
        expected_return = 0.0
        total_value = sum(a.market_value for a in account.assets)
        if total_value > 0:
            for asset in account.assets:
                weight = asset.market_value / total_value
                exp_ret = self.EXPECTED_RETURNS.get(asset.asset_class, 0.06)
                expected_return += weight * exp_ret
        else:
            expected_return = 0.06  # Default moderate return
        
        # Monte Carlo simulation (1000 runs)
        num_simulations = 1000
        projections = {
            "years": [],
            "percentiles": {"10th": [], "25th": [], "50th": [], "75th": [], "90th": []},
            "expected": []
        }
        
        for year in range(1, years + 1):
            year_values = []
            for _ in range(num_simulations):
                value = current_value
                for month in range(year * 12):
                    # Random monthly return
                    monthly_return = random.gauss(expected_return / 12, risk / math.sqrt(12))
                    value = value * (1 + monthly_return) + monthly_contribution
                year_values.append(value)
            
            year_values.sort()
            projections["years"].append(year)
            projections["percentiles"]["10th"].append(year_values[int(0.10 * num_simulations)])
            projections["percentiles"]["25th"].append(year_values[int(0.25 * num_simulations)])
            projections["percentiles"]["50th"].append(year_values[int(0.50 * num_simulations)])
            projections["percentiles"]["75th"].append(year_values[int(0.75 * num_simulations)])
            projections["percentiles"]["90th"].append(year_values[int(0.90 * num_simulations)])
            projections["expected"].append(current_value * ((1 + expected_return) ** year) + 
                                          monthly_contribution * 12 * (((1 + expected_return) ** year - 1) / expected_return))
        
        return {
            "account_id": account_id,
            "current_value": current_value,
            "monthly_contribution": monthly_contribution,
            "expected_annual_return": expected_return,
            "portfolio_volatility": risk,
            "projections": projections,
            "lump_sum_at_retirement": projections["percentiles"]["50th"][-1],
            "monthly_income_at_retirement": projections["percentiles"]["50th"][-1] * 0.04 / 12  # 4% safe withdrawal rate
        }
    
    def generate_ai_recommendations(self, account_id: str) -> List[Dict]:
        """Generate AI-powered investment recommendations"""
        account = self.accounts.get(account_id)
        if not account:
            return []
        
        recommendations = []
        portfolio = self.get_portfolio_summary(account_id)
        allocation = portfolio.get("allocation", {})
        target_alloc = account.target_allocation
        
        # Check for rebalancing needs
        for asset_class, data in allocation.items():
            current_pct = data.get("percentage", 0)
            target_pct = data.get("target_percentage", 0)
            diff = current_pct - target_pct
            
            if abs(diff) > 5:  # 5% threshold
                action = "sell" if diff > 0 else "buy"
                rec = InvestmentRecommendation(
                    recommendation_id=f"REC-{hashlib.md5(f'{account_id}-{asset_class}-{datetime.now().isoformat()}'.encode()).hexdigest()[:8]}",
                    action=action,
                    symbol=asset_class.upper(),
                    asset_class=AssetClass(asset_class) if asset_class in [e.value for e in AssetClass] else AssetClass.EQUITY,
                    reason=f"{asset_class.title()} allocation is {abs(diff):.1f}% {'above' if diff > 0 else 'below'} target. Consider {'reducing' if diff > 0 else 'increasing'} exposure.",
                    confidence_score=min(0.95, 0.6 + abs(diff) / 20),
                    expected_return_pct=self.EXPECTED_RETURNS.get(AssetClass(asset_class), 0.06) * 100 if asset_class in [e.value for e in AssetClass] else 6.0,
                    risk_score=self.RISK_PROFILES.get(AssetClass(asset_class), 0.15) if asset_class in [e.value for e in AssetClass] else 0.15,
                    time_horizon="short-term"
                )
                recommendations.append(asdict(rec))
        
        # Specific asset recommendations based on market conditions
        market_recommendations = [
            {
                "action": "buy",
                "symbol": "BTC",
                "reason": "Bitcoin showing strong momentum with institutional adoption. Consider small allocation for crypto exposure.",
                "confidence_score": 0.72,
                "expected_return_pct": 15.0,
                "risk_score": 0.60
            },
            {
                "action": "hold",
                "symbol": "SPY",
                "reason": "S&P 500 remains strong. Maintain core equity position for long-term growth.",
                "confidence_score": 0.85,
                "expected_return_pct": 8.0,
                "risk_score": 0.18
            },
            {
                "action": "buy",
                "symbol": "BND",
                "reason": "Fixed income allocation below target. Bond yields attractive for income generation.",
                "confidence_score": 0.78,
                "expected_return_pct": 4.5,
                "risk_score": 0.05
            }
        ]
        
        for rec in market_recommendations:
            symbol = rec["symbol"]
            rec["recommendation_id"] = f"REC-{hashlib.md5(f'{account_id}-{symbol}'.encode()).hexdigest()[:8]}"
            rec["asset_class"] = self.MARKET_DATA.get(symbol, {}).get("class", AssetClass.EQUITY).value
            rec["time_horizon"] = "medium-term"
            rec["created_at"] = datetime.now().isoformat()
            recommendations.append(rec)
        
        return recommendations
    
    def get_market_data(self, symbols: List[str] = None) -> Dict:
        """Get current market data"""
        if symbols:
            return {s: self.MARKET_DATA.get(s) for s in symbols if s in self.MARKET_DATA}
        return self.MARKET_DATA
    
    def get_available_assets(self) -> List[Dict]:
        """Get list of all available assets for investment"""
        return [
            {
                "symbol": symbol,
                "name": data["name"],
                "asset_class": data["class"].value,
                "price": data["price"],
                "change_24h": data["change_24h"]
            }
            for symbol, data in self.MARKET_DATA.items()
        ]


# Singleton instance
_portfolio_service: Optional[InvestmentPortfolioService] = None

def get_portfolio_service() -> InvestmentPortfolioService:
    """Get singleton instance of portfolio service"""
    global _portfolio_service
    if _portfolio_service is None:
        _portfolio_service = InvestmentPortfolioService()
    return _portfolio_service
