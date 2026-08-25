"""Static integrity for the algo-trading dashboard redesign.

Locks unified PHINS chrome (shield emblem, navy/gold tokens, Space Grotesk)
and the data-binding contract used by bots, signals, positions, pipeline
allocation, and balance transfers — so a visual restyle cannot drop IDs,
APIs, option values, or allocation defaults.
"""

from pathlib import Path
import re


PAGE = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "algo-trading.html"

# Decorative "simple emoji" chrome that the unified design removes.
# Status dots, refresh glyphs, and hamburger remain allowed.
SIMPLE_EMOJI = re.compile(
    r"[🤖📈📉💰📊⚡🧠🌐🛡⚖🔥🏆🚀📡🟢🔴🏥🔄📜₿🛢💱➕➖💡💵📋💹💎🎯🔀🎉✅❌⏳💸💊🖥]"
)


def _html() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_algo_trading_uses_unified_phins_chrome():
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
    assert "Algorithmic Trading System" in html
    # Legacy indigo/purple chrome and emoji logo must stay gone
    assert 'class="logo-icon"' not in html
    assert "PHINS Algo Trading" not in html
    assert "#6366f1" not in html
    assert "#8b5cf6" not in html
    assert "#1e1b4b" not in html
    assert "#312e81" not in html


def test_algo_trading_removes_simple_emojis():
    leftovers = []
    for line_no, line in enumerate(_html().splitlines(), 1):
        if SIMPLE_EMOJI.search(line):
            leftovers.append(f"{line_no}: {line.strip()[:140]}")
    assert leftovers == [], "decorative emojis remain:\n" + "\n".join(leftovers)


def test_algo_trading_preserves_data_binding_ids():
    html = _html()
    for element_id in (
        "totalPnl",
        "pnlChange",
        "winRate",
        "winRateChange",
        "sharpeRatio",
        "maxDrawdown",
        "activeBots",
        "botsChange",
        "sortinoRatio",
        "calmarRatio",
        "profitFactor",
        "bestTrade",
        "worstTrade",
        "winStreak",
        "profitToday",
        "tradesToday",
        "profitWeek",
        "profitMonth",
        "profitAllTime",
        "totalWinRate",
        "recentProfitableTrades",
        "riskFilter",
        "smartBotTemplates",
        "extendedMarketData",
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
        "botGrid",
        "signalUpdateTime",
        "signalLiveIndicator",
        "signalsTable",
        "buySignalCount",
        "sellSignalCount",
        "avgConfidence",
        "highConfidenceCount",
        "positionsTable",
        "positionsBody",
        "totalUnrealizedPnl",
        "totalRealizedPnl",
        "winRateDisplay",
        "totalPortfolioValue",
        "orderHistory",
        "marketGrid",
        "indicatorSymbol",
        "indicatorGrid",
        "dataSourceBadge",
        "quickTradeClass",
        "quickTradeSymbol",
        "quickTradeAmount",
        "algoAvailableBalance",
        "algoPositionsBalance",
        "algoTotalPnl",
        "unifiedBalanceDisplay",
        "walletBalanceDisplay",
        "investmentBalanceDisplay",
        "algoBalanceDisplay",
        "totalAssetsDisplay",
        "createBotModal",
        "botPreview",
        "botPreviewName",
        "botPreviewStrategy",
        "botName",
        "botRiskLevel",
        "botStrategy",
        "botSymbols",
        "botMaxPosition",
        "botStopLoss",
        "botTakeProfit",
        "botAutoStart",
        "createBotBtn",
        "fundModal",
        "fundModalTitle",
        "fundSourceLabel",
        "fundSource",
        "fundAmount",
        "fundAvailableInfo",
        "fundAvailableAmount",
        "fundActionBtn",
        "toastContainer",
    ):
        assert f'id="{element_id}"' in html, f"missing #{element_id}"


def test_algo_trading_preserves_live_apis():
    html = _html()
    for endpoint in (
        "/api/savings/accounts",
        "/api/algo/market-overview",
        "/api/algo/prices",
        "/api/algo/bots",
        "/api/algo/signals",
        "/api/algo/orders",
        "/api/portfolio/positions",
        "/api/portfolio/summary",
        "/api/portfolio/sell",
        "/api/algo/indicators",
        "/api/algo/stats",
        "/api/algo/smart-bots/templates",
        "/api/algo/smart-bots/create",
        "/api/algo/bots/simulate",
        "/api/algo/market/extended",
        "/api/algo/activate-demo",
        "/api/algo/bots/create",
        "/api/algo/bots/start",
        "/api/algo/bots/stop",
        "/api/algo/bots/run-cycle",
        "/api/algo/bots/delete",
        "/api/portfolio/trade",
        "/api/algo/rebalance",
        "/api/algo/trade",
        "/api/pipeline/analytics",
        "/api/pipeline/ai-recommendation",
        "/api/investment/unified",
        "/api/balance/unified",
        "/api/balance/algo-trading",
        "/api/balance/transfer-to-algo",
        "/api/balance/withdraw-from-algo",
        "/api/algo/profits/realtime",
        "/api/algo/profits/summary",
        "/api/algo/run-profit-cycle",
        "/api/algo/activate-profits",
    ):
        assert endpoint in html, f"missing API {endpoint}"


def test_algo_trading_preserves_transfer_and_strategy_values():
    html = _html()
    assert 'value="investment_account"' in html
    assert 'value="health_wallet"' in html
    assert "type=algo_trading" in html
    for strategy in (
        "momentum",
        "mean_reversion",
        "trend_following",
        "breakout",
        "rsi_strategy",
        "macd_crossover",
        "dollar_cost_averaging",
        "grid_trading",
        "scalping",
        "swing_trading",
        "arbitrage",
        "ai_adaptive",
    ):
        assert f'value="{strategy}"' in html, f"missing strategy value {strategy}"
    for risk in ("conservative", "moderate", "aggressive"):
        assert f'value="{risk}"' in html, f"missing risk value {risk}"
    for asset_class in ("equity", "crypto", "commodity", "forex", "bond", "index"):
        assert f'data-class="{asset_class}"' in html or f'data-asset-class="{asset_class}"' in html


def test_algo_trading_preserves_pipeline_allocation_defaults():
    html = _html()
    assert 'id="pipelineWalletPct">15%</div>' in html
    assert 'id="pipelineInvestPct">60%</div>' in html
    assert 'id="pipelineAlgoPct">25%</div>' in html
    assert 'id="actuarialRiskPct"' in html and ">50%</div>" in html
    assert 'id="actuarialSavingsPct"' in html and ">50%</div>" in html
    assert "(analytics.allocation.wallet || 15)" in html
    assert "alloc.savings_pct != null ? alloc.savings_pct : 50" in html
    assert "localStorage.getItem('phins_token')" in html
    assert "sessionStorage.getItem('phins_token')" in html
    assert "botMaxPosition\" value=\"1000\"" in html or 'id="botMaxPosition" value="1000"' in html
    assert 'id="botStopLoss" value="5"' in html
    assert 'id="botTakeProfit" value="10"' in html
