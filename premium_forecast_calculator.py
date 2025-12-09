#!/usr/bin/env python3
"""
PHINS Premium Forecast Calculator
Sales Division Tool for Premium Planning & Risk Hedging vs Savings Analysis
"""

from accounting_engine import InvestmentRoute, INVESTMENT_RATES
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from enum import Enum


class PaymentPeriod(Enum):
    """Payment period options"""
    MONTHLY = "Monthly"
    QUARTERLY = "Quarterly"
    SEMI_ANNUAL = "Semi-Annual"
    ANNUAL = "Annual"


class MarketIndex(Enum):
    """Market index options for forecasting"""
    CONSERVATIVE = "Conservative (3% growth)"
    MODERATE = "Moderate (5% growth)"
    AGGRESSIVE = "Aggressive (8% growth)"
    VOLATILE = "Volatile (±2-10% range)"


class RiskHedgeStrategy(Enum):
    """Risk hedging strategies"""
    NO_HEDGE = "No Hedge (100% risk)"
    LOW_HEDGE = "Low Hedge (70% risk, 30% savings)"
    BALANCED_HEDGE = "Balanced Hedge (50% risk, 50% savings)"
    HIGH_HEDGE = "High Hedge (30% risk, 70% savings)"
    PURE_SAVINGS = "Pure Savings (100% savings)"


@dataclass
class PremiumForecast:
    """Single premium forecast scenario"""
    scenario_name: str
    monthly_premium: Decimal
    payment_period: PaymentPeriod
    duration_years: int
    risk_percentage: Decimal
    savings_percentage: Decimal
    investment_route: InvestmentRoute
    market_index: MarketIndex
    capital_revenue_rate: Decimal
    
    # Calculated fields
    total_periods: int = field(default=0)
    period_payment: Decimal = field(default_factory=Decimal)
    total_risk_allocated: Decimal = field(default_factory=Decimal)
    total_savings_allocated: Decimal = field(default_factory=Decimal)
    investment_returns: Decimal = field(default_factory=Decimal)
    capital_revenue_liability: Decimal = field(default_factory=Decimal)
    net_customer_value: Decimal = field(default_factory=Decimal)
    projected_claim_reserve: Decimal = field(default_factory=Decimal)
    
    def __post_init__(self):
        """Calculate all forecast metrics"""
        self._calculate_periods()
        self._calculate_allocations()
        self._calculate_investment_returns()
        self._calculate_capital_revenue()
        self._calculate_reserves()
    
    def _calculate_periods(self):
        """Calculate number of payment periods"""
        period_multipliers = {
            PaymentPeriod.MONTHLY: 12,
            PaymentPeriod.QUARTERLY: 4,
            PaymentPeriod.SEMI_ANNUAL: 2,
            PaymentPeriod.ANNUAL: 1
        }
        periods_per_year = period_multipliers[self.payment_period]
        self.total_periods = periods_per_year * self.duration_years
        
        # Calculate period payment
        annual_premium = self.monthly_premium * 12
        self.period_payment = Decimal(annual_premium) / Decimal(periods_per_year)
    
    def _calculate_allocations(self):
        """Calculate risk vs savings allocations"""
        total_premium = self.period_payment * Decimal(self.total_periods)
        self.total_risk_allocated = total_premium * (Decimal(self.risk_percentage) / Decimal(100))
        self.total_savings_allocated = total_premium * (Decimal(self.savings_percentage) / Decimal(100))
    
    def _calculate_investment_returns(self):
        """Calculate investment returns with compound interest"""
        annual_rate = INVESTMENT_RATES.get(self.investment_route, INVESTMENT_RATES[InvestmentRoute.BASIC_SAVINGS])
        
        # Market index multiplier
        market_multipliers = {
            MarketIndex.CONSERVATIVE: Decimal('1.0'),
            MarketIndex.MODERATE: Decimal('1.5'),
            MarketIndex.AGGRESSIVE: Decimal('2.0'),
            MarketIndex.VOLATILE: Decimal('1.2')  # Conservative estimate for volatility
        }
        adjusted_rate = annual_rate * market_multipliers[self.market_index]
        
        # Compound investment growth (monthly compounding for accuracy)
        monthly_rate = adjusted_rate / Decimal(12) / Decimal(100)
        monthly_savings = self.period_payment * (Decimal(self.savings_percentage) / Decimal(100))
        
        balance = Decimal(0)
        for period in range(self.total_periods):
            balance = balance * (Decimal(1) + monthly_rate) + monthly_savings
        
        self.investment_returns = balance - self.total_savings_allocated
    
    def _calculate_capital_revenue(self):
        """Calculate capital revenue (tax) liability on investment returns"""
        self.capital_revenue_liability = self.investment_returns * (self.capital_revenue_rate / Decimal(100))
    
    def _calculate_reserves(self):
        """Calculate projected claim reserve from risk allocation"""
        # Assume 60% of risk premium goes to actual claims, 40% to operational costs
        claims_percentage = Decimal('0.60')
        self.projected_claim_reserve = self.total_risk_allocated * claims_percentage
    
    def get_customer_net_value(self) -> Decimal:
        """Net value to customer: savings + returns - capital revenue"""
        total_balance = self.total_savings_allocated + self.investment_returns
        return total_balance - self.capital_revenue_liability
    
    def get_roi(self) -> Decimal:
        """Return on investment percentage"""
        if self.total_savings_allocated == 0:
            return Decimal(0)
        return (self.investment_returns / self.total_savings_allocated) * Decimal(100)


@dataclass
class ForecastComparison:
    """Comparison between multiple forecast scenarios"""
    forecasts: List[PremiumForecast]
    
    def get_best_for_customer(self) -> PremiumForecast:
        """Find scenario with highest net customer value"""
        return max(self.forecasts, key=lambda f: f.get_customer_net_value())
    
    def get_best_for_risk_mitigation(self) -> PremiumForecast:
        """Find scenario with highest claim reserve"""
        return max(self.forecasts, key=lambda f: f.projected_claim_reserve)
    
    def get_best_balanced(self) -> PremiumForecast:
        """Find most balanced scenario"""
        # Score based on balance between ROI and reserves
        def balance_score(f: PremiumForecast) -> Decimal:
            roi = f.get_roi()
            reserve_ratio = f.projected_claim_reserve / f.total_risk_allocated if f.total_risk_allocated > 0 else Decimal(0)
            return roi * (reserve_ratio / Decimal(100))
        
        return max(self.forecasts, key=balance_score)


class PremiumForecastCalculator:
    """Main calculator for premium forecasting"""
    
    def __init__(self):
        self.forecasts: List[PremiumForecast] = []
    
    def create_forecast(
        self,
        scenario_name: str,
        monthly_premium: Decimal,
        payment_period: PaymentPeriod,
        duration_years: int,
        risk_hedge: RiskHedgeStrategy,
        investment_route: InvestmentRoute,
        market_index: MarketIndex,
        capital_revenue_rate: Decimal = Decimal('15.0')
    ) -> PremiumForecast:
        """Create a forecast scenario"""
        
        # Extract risk/savings split from hedge strategy
        hedge_splits = {
            RiskHedgeStrategy.NO_HEDGE: (100, 0),
            RiskHedgeStrategy.LOW_HEDGE: (70, 30),
            RiskHedgeStrategy.BALANCED_HEDGE: (50, 50),
            RiskHedgeStrategy.HIGH_HEDGE: (30, 70),
            RiskHedgeStrategy.PURE_SAVINGS: (0, 100)
        }
        
        risk_pct, savings_pct = hedge_splits[risk_hedge]
        
        forecast = PremiumForecast(
            scenario_name=scenario_name,
            monthly_premium=monthly_premium,
            payment_period=payment_period,
            duration_years=duration_years,
            risk_percentage=Decimal(risk_pct),
            savings_percentage=Decimal(savings_pct),
            investment_route=investment_route,
            market_index=market_index,
            capital_revenue_rate=capital_revenue_rate
        )
        
        self.forecasts.append(forecast)
        return forecast
    
    def clear_forecasts(self):
        """Clear all forecasts"""
        self.forecasts = []
    
    def print_forecast_summary(self, forecast: PremiumForecast):
        """Print detailed forecast summary"""
        print(f"\n{'='*80}")
        print(f"  PREMIUM FORECAST: {forecast.scenario_name}")
        print(f"{'='*80}")
        
        print(f"\n📋 SCENARIO PARAMETERS:")
        print(f"  Monthly Premium: ${forecast.monthly_premium:,.2f}")
        print(f"  Payment Period: {forecast.payment_period.value}")
        print(f"  Duration: {forecast.duration_years} years")
        print(f"  Total Periods: {forecast.total_periods}")
        print(f"  Period Payment: ${forecast.period_payment:,.2f}")
        
        print(f"\n🛡️ RISK HEDGING STRATEGY:")
        print(f"  Risk Allocation: {forecast.risk_percentage:.0f}% (${forecast.total_risk_allocated:,.2f})")
        print(f"  Savings Allocation: {forecast.savings_percentage:.0f}% (${forecast.total_savings_allocated:,.2f})")
        print(f"  Total Premium: ${forecast.total_risk_allocated + forecast.total_savings_allocated:,.2f}")
        
        print(f"\n📈 INVESTMENT GROWTH:")
        print(f"  Investment Route: {forecast.investment_route.value}")
        print(f"  Market Index: {forecast.market_index.value}")
        print(f"  Base Annual Rate: {INVESTMENT_RATES.get(forecast.investment_route, Decimal('0.5')):.2f}%")
        print(f"  Investment Returns: ${forecast.investment_returns:,.2f}")
        print(f"  Return on Investment (ROI): {forecast.get_roi():.2f}%")
        
        print(f"\n💰 FINANCIAL SUMMARY:")
        print(f"  Total Savings Contributed: ${forecast.total_savings_allocated:,.2f}")
        print(f"  Investment Earnings: ${forecast.investment_returns:,.2f}")
        print(f"  Savings + Returns: ${forecast.total_savings_allocated + forecast.investment_returns:,.2f}")
        
        print(f"\n📊 CAPITAL REVENUE (TAX) IMPACT:")
        print(f"  Capital Revenue Rate: {forecast.capital_revenue_rate:.2f}%")
        print(f"  Capital Revenue Liability: ${forecast.capital_revenue_liability:,.2f}")
        print(f"  Net Customer Savings: ${forecast.get_customer_net_value():,.2f}")
        
        print(f"\n🏥 RISK RESERVES:")
        print(f"  Total Risk Premium Allocated: ${forecast.total_risk_allocated:,.2f}")
        print(f"  Projected Claims Reserve: ${forecast.projected_claim_reserve:,.2f}")
        print(f"  Operational Costs (40%): ${forecast.total_risk_allocated - forecast.projected_claim_reserve:,.2f}")
        
        print(f"\n📌 KEY METRICS:")
        print(f"  Risk-to-Savings Ratio: {forecast.total_risk_allocated / forecast.total_savings_allocated:.2f}:1" if forecast.total_savings_allocated > 0 else "  Risk-to-Savings Ratio: ∞ (no savings)")
        print(f"  Customer Lifetime Value: ${forecast.get_customer_net_value() + forecast.total_savings_allocated:,.2f}")
        print(f"  Premium Efficiency: {float(forecast.projected_claim_reserve / (forecast.total_risk_allocated + forecast.total_savings_allocated)) * 100:.1f}%")
    
    def print_comparison_table(self):
        """Print comparison table of all scenarios"""
        if not self.forecasts:
            print("No forecasts to compare")
            return
        
        print(f"\n{'='*140}")
        print(f"  PREMIUM FORECAST COMPARISON - ALL SCENARIOS")
        print(f"{'='*140}\n")
        
        print(f"{'Scenario':<25} | {'Period':<10} | {'Risk':<8} | {'Savings':<8} | {'Investment':<12} | {'Returns':<12} | {'ROI':<7} | {'Cap Rev':<12} | {'Net Value':<12}")
        print(f"{'-'*140}")
        
        for forecast in self.forecasts:
            print(f"{forecast.scenario_name:<25} | {forecast.payment_period.value:<10} | "
                  f"{forecast.risk_percentage:>6.0f}% | {forecast.savings_percentage:>6.0f}% | "
                  f"${forecast.total_savings_allocated:>10,.0f} | ${forecast.investment_returns:>10,.0f} | "
                  f"{forecast.get_roi():>5.2f}% | ${forecast.capital_revenue_liability:>10,.0f} | "
                  f"${forecast.get_customer_net_value():>10,.0f}")
        
        print(f"\n{'='*140}")
    
    def print_detailed_comparison(self):
        """Print detailed multi-scenario analysis"""
        if not self.forecasts:
            print("No forecasts to compare")
            return
        
        print(f"\n{'='*80}")
        print(f"  DETAILED SCENARIO COMPARISON & RECOMMENDATIONS")
        print(f"{'='*80}\n")
        
        best_customer = self.get_best_for_customer()
        best_risk = self.get_best_for_risk_mitigation()
        best_balanced = self.get_best_balanced()
        
        print(f"🏆 BEST FOR CUSTOMER (Highest Net Value):")
        print(f"   {best_customer.scenario_name}")
        print(f"   Net Customer Value: ${best_customer.get_customer_net_value():,.2f}")
        print(f"   ROI: {best_customer.get_roi():.2f}%\n")
        
        print(f"🛡️ BEST FOR RISK MITIGATION (Highest Claims Reserve):")
        print(f"   {best_risk.scenario_name}")
        print(f"   Claims Reserve: ${best_risk.projected_claim_reserve:,.2f}")
        print(f"   Risk Allocation: ${best_risk.total_risk_allocated:,.2f}\n")
        
        print(f"⚖️ BEST BALANCED APPROACH:")
        print(f"   {best_balanced.scenario_name}")
        print(f"   Risk Allocation: {best_balanced.risk_percentage:.0f}%")
        print(f"   Savings Allocation: {best_balanced.savings_percentage:.0f}%")
        print(f"   Net Customer Value: ${best_balanced.get_customer_net_value():,.2f}")
        print(f"   ROI: {best_balanced.get_roi():.2f}%\n")
        
        print(f"💡 SALES RECOMMENDATIONS:")
        print(f"   • For price-sensitive customers: Recommend {best_customer.scenario_name}")
        print(f"   • For risk-averse customers: Recommend {best_risk.scenario_name}")
        print(f"   • For balanced approach: Recommend {best_balanced.scenario_name}")
    
    def get_best_for_customer(self) -> PremiumForecast:
        """Get best scenario for customer"""
        return max(self.forecasts, key=lambda f: f.get_customer_net_value())
    
    def get_best_for_risk_mitigation(self) -> PremiumForecast:
        """Get best scenario for risk mitigation"""
        return max(self.forecasts, key=lambda f: f.projected_claim_reserve)
    
    def get_best_balanced(self) -> PremiumForecast:
        """Get most balanced scenario"""
        def balance_score(f: PremiumForecast) -> Decimal:
            roi = f.get_roi()
            reserve_ratio = f.projected_claim_reserve / f.total_risk_allocated if f.total_risk_allocated > 0 else Decimal(0)
            return roi * (reserve_ratio / Decimal(100))
        
        return max(self.forecasts, key=balance_score) if self.forecasts else None


def demo_premium_forecast_calculator():
    """Demonstrate the premium forecast calculator"""
    
    print(f"\n{'='*80}")
    print(f"  PHINS PREMIUM FORECAST CALCULATOR")
    print(f"  Sales Division - Risk Hedging vs Savings Analysis")
    print(f"{'='*80}\n")
    
    calculator = PremiumForecastCalculator()
    
    base_monthly_premium = Decimal('800')
    
    # Scenario 1: Conservative approach (Low risk tolerance, save more)
    print("Creating Scenario 1: Conservative (HIGH_HEDGE) with Moderate Growth...")
    calc1 = calculator.create_forecast(
        scenario_name="Conservative (High Savings)",
        monthly_premium=base_monthly_premium,
        payment_period=PaymentPeriod.MONTHLY,
        duration_years=5,
        risk_hedge=RiskHedgeStrategy.HIGH_HEDGE,
        investment_route=InvestmentRoute.BONDS,
        market_index=MarketIndex.MODERATE,
        capital_revenue_rate=Decimal('15.0')
    )
    
    # Scenario 2: Balanced approach
    print("Creating Scenario 2: Balanced approach...")
    calc2 = calculator.create_forecast(
        scenario_name="Balanced (50/50 Split)",
        monthly_premium=base_monthly_premium,
        payment_period=PaymentPeriod.MONTHLY,
        duration_years=5,
        risk_hedge=RiskHedgeStrategy.BALANCED_HEDGE,
        investment_route=InvestmentRoute.MIXED_PORTFOLIO,
        market_index=MarketIndex.MODERATE,
        capital_revenue_rate=Decimal('15.0')
    )
    
    # Scenario 3: Aggressive approach (High risk tolerance, more returns)
    print("Creating Scenario 3: Aggressive (LOW_HEDGE) with Aggressive Growth...")
    calc3 = calculator.create_forecast(
        scenario_name="Aggressive (High Growth)",
        monthly_premium=base_monthly_premium,
        payment_period=PaymentPeriod.MONTHLY,
        duration_years=5,
        risk_hedge=RiskHedgeStrategy.LOW_HEDGE,
        investment_route=InvestmentRoute.EQUITIES,
        market_index=MarketIndex.AGGRESSIVE,
        capital_revenue_rate=Decimal('15.0')
    )
    
    # Scenario 4: Premium protection focus
    print("Creating Scenario 4: Premium Protection (NO_HEDGE) for maximum claims reserve...")
    calc4 = calculator.create_forecast(
        scenario_name="Protection Focused (100% Risk)",
        monthly_premium=base_monthly_premium,
        payment_period=PaymentPeriod.MONTHLY,
        duration_years=5,
        risk_hedge=RiskHedgeStrategy.NO_HEDGE,
        investment_route=InvestmentRoute.BASIC_SAVINGS,
        market_index=MarketIndex.CONSERVATIVE,
        capital_revenue_rate=Decimal('15.0')
    )
    
    # Scenario 5: Quarterly payments
    print("Creating Scenario 5: Quarterly Payment Option...")
    calc5 = calculator.create_forecast(
        scenario_name="Quarterly Payments (Balanced)",
        monthly_premium=base_monthly_premium,
        payment_period=PaymentPeriod.QUARTERLY,
        duration_years=5,
        risk_hedge=RiskHedgeStrategy.BALANCED_HEDGE,
        investment_route=InvestmentRoute.MIXED_PORTFOLIO,
        market_index=MarketIndex.MODERATE,
        capital_revenue_rate=Decimal('15.0')
    )
    
    # Print individual summaries
    for forecast in calculator.forecasts:
        calculator.print_forecast_summary(forecast)
    
    # Print comparison tables
    calculator.print_comparison_table()
    calculator.print_detailed_comparison()
    
    # ========================================================================
    # SCENARIO-SPECIFIC SALES PITCH
    # ========================================================================
    print(f"\n{'='*80}")
    print(f"  SALES DIVISION PITCH TEMPLATES")
    print(f"{'='*80}\n")
    
    print("🎯 PITCH 1: Conservative Customer")
    print("   'With our HIGH_HEDGE option, your premium is split so that 70% protects")
    print("    your family with comprehensive claims coverage, while 30% grows in our")
    print("    BONDS portfolio at 3.5% annually. Over 5 years, you'll accumulate")
    print(f"    ${calc1.total_savings_allocated + calc1.investment_returns:,.2f} in savings!")
    print(f"    After capital revenue, you keep ${calc1.get_customer_net_value():,.2f}. ROI: {calc1.get_roi():.2f}%\n")
    
    print("🎯 PITCH 2: Balanced Customer")
    print("   'Looking for the sweet spot? Our 50/50 approach is perfect. Half your")
    print("    premium goes to protecting you and your family with comprehensive claims")
    print("    coverage. The other half goes into our MIXED_PORTFOLIO earning 4.5%")
    print(f"    annually. In 5 years, you'll have ${calc2.total_savings_allocated + calc2.investment_returns:,.2f}")
    print(f"    in accumulated savings. Net value: ${calc2.get_customer_net_value():,.2f}. ROI: {calc2.get_roi():.2f}%\n")
    
    print("🎯 PITCH 3: Growth-Focused Customer")
    print("   'If you're looking to maximize returns, our AGGRESSIVE option puts 70%")
    print("    into EQUITIES at 7% annual growth while keeping solid 30% protection.")
    print("    With aggressive market conditions, your savings could grow to")
    print(f"    ${calc3.total_savings_allocated + calc3.investment_returns:,.2f} over 5 years!")
    print(f"    Net value after capital revenue: ${calc3.get_customer_net_value():,.2f}. ROI: {calc3.get_roi():.2f}%\n")
    
    print("🎯 PITCH 4: Protection-First Customer")
    print("   'Your family's security comes first. With our 100% RISK coverage, every")
    print("    dollar of your premium goes directly to building a claims reserve.")
    print(f"    Over 5 years, we'll have ${calc4.projected_claim_reserve:,.2f} reserved")
    print("    to cover your family's needs when they need it most. Pure peace of mind.\n")
    
    print("🎯 PITCH 5: Convenience Preference")
    print("   'Prefer quarterly payments? No problem! Our QUARTERLY option spreads")
    print(f"    your payments to ${calc5.period_payment:,.2f} four times a year.")
    print("    You still get the same balanced 50/50 split and 4.5% growth on your")
    print(f"    savings, accumulating to ${calc5.total_savings_allocated + calc5.investment_returns:,.2f}")
    print(f"    over 5 years with ${calc5.get_customer_net_value():,.2f} net value.\n")
    
    print(f"{'='*80}\n")


if __name__ == "__main__":
    demo_premium_forecast_calculator()
