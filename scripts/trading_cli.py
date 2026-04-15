#!/usr/bin/env python3
"""
PHINS Trading CLI
==================
Command-line interface for managing trading strategies, the options wheel,
and investment portfolio operations.

Usage:
    python scripts/trading_cli.py [command] [options]

Commands:
    wheel-dashboard     Show options wheel strategy dashboard
    wheel-scan          Scan for put candidates
    wheel-sell-put      Sell a cash-secured put
    wheel-sell-call     Sell a covered call
    wheel-assign        Record a put assignment
    wheel-call-away     Record shares called away
    wheel-cycle         Run one full wheel cycle
    wheel-config        Show or update wheel configuration
    wheel-positions     Show current wheel positions
    wheel-integrity     Run data integrity check
    wheel-export        Export wheel state to JSON
    wheel-import        Import wheel state from JSON
    strategies          List available trading strategies
    signal              Generate a trading signal
    bot-create          Create a new trading bot
    bot-list            List all trading bots
    portfolio           Show investment portfolio summary
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_wheel_service():
    from services.options_wheel_service import get_options_wheel_service
    return get_options_wheel_service()


def get_algo_service():
    from services.algo_trading_service import get_algo_trading_service
    from services.investment_portfolio_service import get_portfolio_service
    portfolio = get_portfolio_service()
    return get_algo_trading_service(portfolio)


def fmt_json(data):
    return json.dumps(data, indent=2, default=str)


def fmt_table(rows, headers):
    if not rows:
        print("  (no data)")
        return
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("  ".join("-" * w for w in col_widths))
    for row in rows:
        print("  ".join(str(v).ljust(col_widths[i]) for i, v in enumerate(row)))


# ---------------------------------------------------------------------------
# Wheel commands
# ---------------------------------------------------------------------------

def cmd_wheel_dashboard(args):
    svc = get_wheel_service()
    dash = svc.get_dashboard(args.account_id)
    print(f"\n{'='*60}")
    print(f"  OPTIONS WHEEL DASHBOARD — {dash['account_id']}")
    print(f"{'='*60}")
    print(f"  Positions:     {dash['total_positions']}")
    print(f"  Total Risk:    ${dash['total_risk']:,.2f}")
    print(f"  Buying Power:  ${dash['buying_power']:,.2f}")
    print(f"  Premium:       ${dash['total_premium_collected']:,.2f}")
    print(f"  Cycles Done:   {dash['total_cycles_completed']}")
    print(f"  Orders:        {dash['order_count']}")
    print()

    if dash['positions']:
        print("  Positions:")
        rows = []
        for sym, pos in dash['positions'].items():
            rows.append([sym, pos['phase'], f"${pos.get('cost_basis', 0):,.2f}",
                         pos.get('shares_qty', 0),
                         f"${pos.get('total_premium_collected', 0):,.2f}"])
        fmt_table(rows, ["Symbol", "Phase", "Cost Basis", "Shares", "Premium"])
    else:
        print("  No active positions.")

    integrity = dash.get('integrity_check', [])
    if integrity:
        print(f"\n  INTEGRITY ISSUES ({len(integrity)}):")
        for issue in integrity:
            print(f"    ! {issue}")
    else:
        print("\n  Data integrity: CLEAN")
    print()


def cmd_wheel_scan(args):
    svc = get_wheel_service()
    result = svc.scan_puts(args.account_id)
    print(f"\n  Buying Power: ${result['buying_power']:,.2f}")
    print(f"  Current Risk: ${result['current_risk']:,.2f}")
    print(f"  Allowed Symbols: {len(result['allowed_symbols'])}")
    print()

    candidates = result['candidates'][:args.top]
    if candidates:
        rows = []
        for c in candidates:
            rows.append([
                c['underlying'], f"${c['strike']:,.2f}",
                f"${c['bid_price']:.2f}", f"{abs(c.get('delta', 0)):.3f}",
                c.get('dte', '?'), f"{c.get('annualized_yield', 0):.2%}",
                f"{c['score']:.5f}",
            ])
        fmt_table(rows, ["Symbol", "Strike", "Bid", "Delta", "DTE", "Ann.Yield", "Score"])
    else:
        print("  No put candidates found.")
    print()


def cmd_wheel_sell_put(args):
    svc = get_wheel_service()
    result = svc.sell_put(args.account_id, args.underlying)
    if "error" in result:
        print(f"  ERROR: {result['error']}")
    else:
        o = result['order']
        print(f"  Put sold: {o['symbol']} (strike ${o['strike']:,.2f}, premium ${o['premium']:.2f})")
        print(f"  Buying power remaining: ${result['buying_power_remaining']:,.2f}")


def cmd_wheel_sell_call(args):
    svc = get_wheel_service()
    result = svc.sell_call(args.account_id, args.underlying)
    if "error" in result:
        print(f"  ERROR: {result['error']}")
    else:
        o = result['order']
        print(f"  Call sold: {o['symbol']} (strike ${o['strike']:,.2f}, premium ${o['premium']:.2f})")


def cmd_wheel_assign(args):
    svc = get_wheel_service()
    cost = float(args.cost_basis) if args.cost_basis else None
    result = svc.record_assignment(args.underlying, cost)
    if "error" in result:
        print(f"  ERROR: {result['error']}")
    else:
        print(f"  Assignment recorded for {args.underlying}")
        print(f"  Now holding {result['position']['shares_qty']} shares at ${result['position']['cost_basis']:,.2f}")


def cmd_wheel_call_away(args):
    svc = get_wheel_service()
    result = svc.record_call_away(args.underlying)
    if "error" in result:
        print(f"  ERROR: {result['error']}")
    else:
        s = result['cycle_summary']
        print(f"  Shares of {args.underlying} called away!")
        print(f"  Cycles completed: {s['cycles_completed']}")
        print(f"  Total premium: ${s['total_premium_collected']:,.2f}")
        print(f"  Capital gain: ${s['capital_gain']:,.2f}")


def cmd_wheel_cycle(args):
    svc = get_wheel_service()
    result = svc.run_wheel_cycle(args.account_id)
    actions = result.get('actions', [])
    errors = result.get('errors', [])
    print(f"\n  Wheel cycle completed: {len(actions)} actions, {len(errors)} errors")
    for a in actions:
        print(f"    {a['symbol']}: {a['action']}")
    for e in errors:
        print(f"    ERROR {e['symbol']}: {e['error']}")
    d = result.get('dashboard', {})
    print(f"  Positions: {d.get('total_positions', 0)}")
    print(f"  Total Risk: ${d.get('total_risk', 0):,.2f}")
    print(f"  Buying Power: ${d.get('buying_power', 0):,.2f}")
    print()


def cmd_wheel_config(args):
    svc = get_wheel_service()
    if args.set:
        updates = {}
        for item in args.set:
            k, v = item.split("=", 1)
            try:
                v = float(v) if "." in v else int(v)
            except ValueError:
                pass
            updates[k.strip()] = v
        result = svc.update_config(updates)
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            if "details" in result:
                for d in result["details"]:
                    print(f"    {d}")
        else:
            print("  Config updated.")
    config = svc.get_config()
    print("\n  Wheel Configuration:")
    for k, v in config.items():
        print(f"    {k}: {v}")
    print()


def cmd_wheel_positions(args):
    svc = get_wheel_service()
    positions = svc.get_positions()
    if not positions:
        print("  No active wheel positions.")
        return
    rows = []
    for sym, pos in positions.items():
        rows.append([
            sym, pos['phase'],
            f"${pos.get('cost_basis', 0):,.2f}",
            pos.get('shares_qty', 0),
            pos.get('contract_symbol', '-'),
            f"${pos.get('total_premium_collected', 0):,.2f}",
            pos.get('cycles_completed', 0),
        ])
    print()
    fmt_table(rows, ["Symbol", "Phase", "Cost", "Shares", "Contract", "Premium", "Cycles"])
    print()


def cmd_wheel_integrity(args):
    svc = get_wheel_service()
    from services.options_wheel_service import validate_state_integrity
    issues = validate_state_integrity(svc.positions)
    if issues:
        print(f"\n  INTEGRITY ISSUES FOUND ({len(issues)}):")
        for issue in issues:
            print(f"    ! {issue}")
    else:
        print(f"\n  All {len(svc.positions)} positions pass integrity checks.")
    print()


def cmd_wheel_export(args):
    svc = get_wheel_service()
    state = svc.export_state()
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        print(f"  State exported to {args.output}")
    else:
        print(fmt_json(state))


def cmd_wheel_import(args):
    svc = get_wheel_service()
    with open(args.input, 'r') as f:
        data = json.load(f)
    result = svc.import_state(data)
    print(f"  Import status: {result['status']}")
    if result.get('warnings'):
        for w in result['warnings']:
            print(f"    WARNING: {w}")


# ---------------------------------------------------------------------------
# Strategy commands
# ---------------------------------------------------------------------------

def cmd_strategies(args):
    from services.algo_trading_service import TradingStrategy
    print("\n  Available Trading Strategies:")
    print("  " + "-" * 40)
    for s in TradingStrategy:
        print(f"    {s.value}")
    print()


def cmd_signal(args):
    svc = get_algo_service()
    from services.algo_trading_service import TradingStrategy
    try:
        strategy = TradingStrategy(args.strategy)
    except ValueError:
        print(f"  ERROR: Unknown strategy '{args.strategy}'")
        print(f"  Available: {', '.join(s.value for s in TradingStrategy)}")
        return
    signal = svc.generate_signal(args.symbol.upper(), strategy)
    print(f"\n  Signal for {signal.symbol} ({signal.strategy.value}):")
    print(f"    Type:       {signal.signal_type.value}")
    print(f"    Confidence: {signal.confidence*100:.1f}%")
    print(f"    Target:     ${signal.price_target:,.2f}")
    print(f"    Stop Loss:  ${signal.stop_loss:,.2f}")
    print(f"    Take Profit:${signal.take_profit:,.2f}")
    print(f"    Reasoning:  {signal.reasoning}")
    print()


def cmd_bot_create(args):
    svc = get_algo_service()
    from services.algo_trading_service import TradingStrategy
    try:
        strategy = TradingStrategy(args.strategy)
    except ValueError:
        print(f"  ERROR: Unknown strategy '{args.strategy}'")
        return
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    bot = svc.create_bot(
        account_id=args.account_id,
        name=args.name,
        strategy=strategy,
        symbols=symbols,
        max_position_size=args.max_position,
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
    )
    print(f"\n  Bot created: {bot.bot_id}")
    print(f"    Name:     {bot.name}")
    print(f"    Strategy: {bot.strategy.value}")
    print(f"    Symbols:  {', '.join(bot.symbols)}")
    print(f"    Max pos:  ${bot.max_position_size:,.2f}")
    print()


def cmd_bot_list(args):
    svc = get_algo_service()
    bots = svc.bots
    if not bots:
        print("  No trading bots configured.")
        return
    rows = []
    for bid, bot in bots.items():
        rows.append([
            bid, bot.name, bot.strategy.value,
            "Active" if bot.is_active else "Stopped",
            bot.total_trades, f"${bot.total_pnl:,.2f}",
        ])
    print()
    fmt_table(rows, ["ID", "Name", "Strategy", "Status", "Trades", "PnL"])
    print()


def cmd_portfolio(args):
    from services.investment_portfolio_service import get_portfolio_service
    svc = get_portfolio_service()
    summary = svc.get_portfolio_summary(args.customer_id)
    print(f"\n  Portfolio Summary — {args.customer_id}")
    print(f"  {'='*50}")
    if isinstance(summary, dict):
        for k, v in summary.items():
            if isinstance(v, (int, float)):
                print(f"    {k}: ${v:,.2f}" if 'value' in k.lower() or 'balance' in k.lower() else f"    {k}: {v}")
            elif isinstance(v, str):
                print(f"    {k}: {v}")
    print()


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="PHINS Trading CLI — manage strategies, wheel, and investments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # Wheel commands
    p = sub.add_parser("wheel-dashboard", help="Show wheel dashboard")
    p.add_argument("--account-id", default="WHEEL")

    p = sub.add_parser("wheel-scan", help="Scan for put candidates")
    p.add_argument("--account-id", default="WHEEL")
    p.add_argument("--top", type=int, default=10, help="Show top N candidates")

    p = sub.add_parser("wheel-sell-put", help="Sell a cash-secured put")
    p.add_argument("underlying", help="Underlying symbol (e.g. AAPL)")
    p.add_argument("--account-id", default="WHEEL")

    p = sub.add_parser("wheel-sell-call", help="Sell a covered call")
    p.add_argument("underlying", help="Underlying symbol")
    p.add_argument("--account-id", default="WHEEL")

    p = sub.add_parser("wheel-assign", help="Record put assignment")
    p.add_argument("underlying", help="Underlying symbol")
    p.add_argument("--cost-basis", default=None, help="Override cost basis")

    p = sub.add_parser("wheel-call-away", help="Record shares called away")
    p.add_argument("underlying", help="Underlying symbol")

    p = sub.add_parser("wheel-cycle", help="Run one full wheel cycle")
    p.add_argument("--account-id", default="WHEEL")

    p = sub.add_parser("wheel-config", help="Show/update wheel config")
    p.add_argument("--set", nargs="*", metavar="KEY=VALUE", help="Set config values")

    p = sub.add_parser("wheel-positions", help="Show wheel positions")

    p = sub.add_parser("wheel-integrity", help="Run data integrity check")

    p = sub.add_parser("wheel-export", help="Export wheel state to JSON")
    p.add_argument("--output", "-o", help="Output file path")

    p = sub.add_parser("wheel-import", help="Import wheel state from JSON")
    p.add_argument("input", help="Input JSON file path")

    # Strategy commands
    sub.add_parser("strategies", help="List available strategies")

    p = sub.add_parser("signal", help="Generate a trading signal")
    p.add_argument("symbol", help="Symbol (e.g. SPY)")
    p.add_argument("--strategy", default="options_wheel", help="Strategy name")

    p = sub.add_parser("bot-create", help="Create a trading bot")
    p.add_argument("--name", required=True, help="Bot name")
    p.add_argument("--strategy", default="momentum", help="Strategy name")
    p.add_argument("--symbols", required=True, help="Comma-separated symbols")
    p.add_argument("--account-id", default="CLI-001")
    p.add_argument("--max-position", type=float, default=1000)
    p.add_argument("--stop-loss", type=float, default=5.0)
    p.add_argument("--take-profit", type=float, default=10.0)

    sub.add_parser("bot-list", help="List trading bots")

    p = sub.add_parser("portfolio", help="Show portfolio summary")
    p.add_argument("--customer-id", default="CUST-001")

    return parser


COMMAND_MAP = {
    "wheel-dashboard": cmd_wheel_dashboard,
    "wheel-scan": cmd_wheel_scan,
    "wheel-sell-put": cmd_wheel_sell_put,
    "wheel-sell-call": cmd_wheel_sell_call,
    "wheel-assign": cmd_wheel_assign,
    "wheel-call-away": cmd_wheel_call_away,
    "wheel-cycle": cmd_wheel_cycle,
    "wheel-config": cmd_wheel_config,
    "wheel-positions": cmd_wheel_positions,
    "wheel-integrity": cmd_wheel_integrity,
    "wheel-export": cmd_wheel_export,
    "wheel-import": cmd_wheel_import,
    "strategies": cmd_strategies,
    "signal": cmd_signal,
    "bot-create": cmd_bot_create,
    "bot-list": cmd_bot_list,
    "portfolio": cmd_portfolio,
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    handler = COMMAND_MAP.get(args.command)
    if handler:
        handler(args)
    else:
        print(f"Unknown command: {args.command}")
        parser.print_help()


if __name__ == "__main__":
    main()
