"""Static integrity for the savings-portfolio dashboard redesign.

Locks unified PHINS chrome and the two-stage money-flow contract:

1. Actuarial premium split from get_customer_allocation()
   (risk 50 / savings 50, then wallet 30 / investment 65 / algo 5)
2. Savings pipeline HW / INV / ALGO defaults (15 / 60 / 25)

A visual restyle cannot drop IDs, APIs, option values, or allocation fallbacks.
"""

from pathlib import Path
import re


PAGE = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "savings-portfolio.html"

# Decorative "simple emoji" chrome that the unified design removes.
# Status dots, refresh glyphs, and hamburger remain allowed.
SIMPLE_EMOJI = re.compile(
    r"[🤖📈📉💰📊⚡🧠🌐🛡⚖🔥🏆🚀📡🟢🔴🏥🔄📜₿🛢💱➕➖💡💵📋💹💎🎯🔀🎉✅❌⏳💸💊🖥]"
)


def _html() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_savings_portfolio_uses_unified_phins_chrome():
    html = _html()
    assert 'href="/phins-theme.css"' in html
    assert 'src="/phins-logo.svg"' in html
    assert html.count("/phins-logo.svg") >= 3  # favicon + header + brand banner
    assert 'class="phins-header"' in html
    assert 'class="phins-logo-text"' in html
    assert 'class="page-brand-banner"' in html
    assert "Space Grotesk" in html
    assert "--phins-navy" in html
    assert "--phins-gold" in html
    assert "Savings &amp; Investment Portfolio" in html
    assert 'class="logo-icon"' not in html
    assert "#6366f1" not in html
    assert "#1e1b4b" not in html
    assert "#312e81" not in html


def test_savings_portfolio_removes_simple_emojis():
    leftovers = []
    for line_no, line in enumerate(_html().splitlines(), 1):
        if SIMPLE_EMOJI.search(line):
            leftovers.append(f"{line_no}: {line.strip()[:140]}")
    assert leftovers == [], "decorative emojis remain:\n" + "\n".join(leftovers)


def test_savings_portfolio_preserves_data_binding_ids():
    html = _html()
    for element_id in (
        "unifiedPipelineSection",
        "actuarialSourceBadge",
        "actuarialPremium",
        "actuarialRiskPct",
        "actuarialRiskAmt",
        "actuarialSavingsPct",
        "actuarialSavingsAmt",
        "actuarialPolicyMeta",
        "pipelineHealth",
        "pipelineCashBalance",
        "pipelineWalletPct",
        "pipelineWalletBal",
        "pipelineInvestPct",
        "pipelineInvestBal",
        "pipelineAlgoPct",
        "pipelineAlgoBal",
        "aiRecommendation",
        "aiConfBadge",
        "aiRecommendationText",
        "totalValue",
        "totalChange",
        "cashBalance",
        "cashLabel",
        "investedValue",
        "unrealizedGain",
        "investmentCashBalance",
        "investmentCashLabel",
        "monthlyContribution",
        "monthlyBreakdown",
        "distributionTooltip",
        "distributionDetails",
        "algoPortfolioValue",
        "algoPnl",
        "openTerminalBtn",
        "integrityPanel",
        "integrityIcon",
        "integrityStatus",
        "integrityScore",
        "integrityHash",
        "integritySeq",
        "integrityIssues",
        "integrityIssuesList",
        "resetModal",
        "preserveHistoryCheck",
        "transferAvailableInfo",
        "transferAvailableAmount",
        "algoTransferAmount",
        "algoTransferBtn",
        "quickInvestAsset",
        "quickInvestAmount",
        "quickInvestBtn",
        "quickInvestAvailable",
        "totalInvestedAmount",
        "currentValueAmount",
        "unrealizedPnL",
        "returnPctDisplay",
        "allocationPie",
        "allocationTotal",
        "allocationLegend",
        "assetsTableBody",
        "projectionYears",
        "projectionChart",
        "projectedLumpSum",
        "projectedMonthlyIncome",
        "riskSlider",
        "currentRisk",
        "recommendationsList",
        "transactionList",
        "toastContainer",
        "investModal",
        "modalInvestAsset",
        "modalInvestAmount",
        "modalEstimatedShares",
        "marketTicker",
        "mobile-nav",
    ):
        assert f'id="{element_id}"' in html, f"missing #{element_id}"


def test_savings_portfolio_preserves_live_apis():
    html = _html()
    for endpoint in (
        "/api/savings/market-data",
        "/api/integrity/verified-total",
        "/api/investment/unified",
        "/api/savings/accounts",
        "/api/savings/portfolio",
        "/api/pipeline/analytics",
        "/api/pipeline/ai-recommendation",
        "/api/savings/invest",
        "/api/savings/recommendations",
        "/api/savings/transactions",
        "/api/savings/projections",
        "/api/savings/update-risk-profile",
        "/api/savings/sell",
        "/api/balance/algo-trading",
        "/api/balance/transfer-to-algo",
        "/api/savings/deposit",
        "/api/integrity/check",
        "/api/portfolio/display-data",
        "/api/portfolio/validate-integrity",
        "/api/portfolio/reset",
    ):
        assert endpoint in html, f"missing API {endpoint}"


def test_savings_portfolio_preserves_pipeline_and_allocation_defaults():
    html = _html()
    # Savings-pipeline HW / INV / ALGO defaults (AllocationConfig)
    assert 'id="pipelineWalletPct">15%</div>' in html
    assert 'id="pipelineInvestPct">60%</div>' in html
    assert 'id="pipelineAlgoPct">25%</div>' in html
    assert "(analytics.allocation.wallet || 15)" in html
    assert "(analytics.allocation.investment || 60)" in html
    assert "(analytics.allocation.algo_trading || 25)" in html
    # Customer-allocation premium + savings-destination fallbacks
    assert 'id="actuarialRiskPct"' in html and ">50%</div>" in html
    assert 'id="actuarialSavingsPct"' in html and ">50%</div>" in html
    assert "alloc.savings_pct != null ? alloc.savings_pct : 50" in html
    assert "alloc.risk_pct != null ? alloc.risk_pct : 50" in html
    assert "alloc.savings_pct || 50" in html
    assert "alloc.risk_pct || 50" in html
    assert "alloc.wallet_pct || 30" in html
    assert "alloc.investment_pct || 65" in html
    assert "alloc.algo_pct || 5" in html
    assert "if (!unified || unified.error || (!unified.monthly_distribution && !unified.customer_id))" in html
    assert "if (unifiedRes.ok)" in html
    assert "localStorage.getItem('phins_token')" in html
    assert "/api/savings/create-account" not in html
    assert "POL-001" not in html
    assert "|| 1000" not in html
    assert "Allocation is optimized for your" not in html
    assert "function applyPipelineHealth(health)" in html
    assert "health.status === 'no_activity'" in html
    assert "Awaiting live data" in html
    assert "No live AI recommendation yet." in html
    assert "data.is_live === false" in html
    assert "Awaiting live quotes" in html
    assert "#0066cc 0deg 216deg" not in html
    assert "sessionStorage.getItem('phins_token')" in html
    assert 'value="SPY"' in html
    assert 'value="QQQ"' in html
    assert 'value="BTC"' in html
    assert 'value="ETH"' in html
    assert 'value="BONDS"' in html
    assert 'id="riskSlider" min="1" max="5" value="3"' in html or 'min="1" max="5" value="3" id="riskSlider"' in html
