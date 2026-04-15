"""
Test Suite for PHINS Options Wheel Strategy Service
=====================================================
Tests cover:
- Wheel configuration validation
- Options contract modelling and scoring
- Cash-secured put scanning and selling
- Covered call management
- Wheel state machine transitions (short_put -> long_shares -> short_call)
- Assignment and call-away lifecycle
- Data integrity validation
- Risk budgeting
- State persistence (export/import with checksum)
- API endpoints for wheel operations
- New algo strategy signals (options_wheel, covered_call, cash_secured_put, etc.)
"""

import json
import sys
import os
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def api_get(path):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def api_post(path, data=None):
    url = f"{BASE_URL}{path}"
    body = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


# ===================================================================
# Unit tests — service layer
# ===================================================================

class TestWheelConfig(unittest.TestCase):
    """Test WheelConfig validation and serialization."""

    def test_default_config_validates(self):
        from services.options_wheel_service import WheelConfig
        cfg = WheelConfig()
        errors = cfg.validate()
        self.assertEqual(errors, [])

    def test_invalid_delta_range(self):
        from services.options_wheel_service import WheelConfig
        cfg = WheelConfig(delta_min=0.5, delta_max=0.3)
        errors = cfg.validate()
        self.assertTrue(any("delta" in e for e in errors))

    def test_negative_max_risk(self):
        from services.options_wheel_service import WheelConfig
        cfg = WheelConfig(max_risk=-1000)
        errors = cfg.validate()
        self.assertTrue(any("max_risk" in e for e in errors))

    def test_roundtrip_dict(self):
        from services.options_wheel_service import WheelConfig
        cfg = WheelConfig(max_risk=50000, delta_min=0.10, delta_max=0.25)
        d = cfg.to_dict()
        cfg2 = WheelConfig.from_dict(d)
        self.assertEqual(cfg2.max_risk, 50000)
        self.assertEqual(cfg2.delta_min, 0.10)


class TestOptionsContract(unittest.TestCase):
    """Test OptionsContract data model."""

    def _make_contract(self, **overrides):
        from services.options_wheel_service import OptionsContract, ContractType
        defaults = dict(
            symbol="AAPL240419P00170000",
            underlying="AAPL",
            contract_type=ContractType.PUT,
            strike=170.0,
            expiration_date="2024-04-19",
            dte=14,
            delta=-0.25,
            bid_price=3.50,
            ask_price=3.80,
            last_price=3.65,
            open_interest=500,
            volume=120,
            underlying_price=175.0,
        )
        defaults.update(overrides)
        return OptionsContract(**defaults)

    def test_mid_price(self):
        c = self._make_contract()
        self.assertAlmostEqual(c.mid_price(), 3.65, places=2)

    def test_annualized_yield(self):
        c = self._make_contract()
        ann = c.annualized_yield()
        self.assertGreater(ann, 0)

    def test_validate_clean(self):
        c = self._make_contract()
        self.assertEqual(c.validate(), [])

    def test_validate_missing_symbol(self):
        c = self._make_contract(symbol="")
        errors = c.validate()
        self.assertTrue(any("symbol" in e for e in errors))

    def test_validate_negative_strike(self):
        c = self._make_contract(strike=-10)
        errors = c.validate()
        self.assertTrue(any("strike" in e for e in errors))

    def test_roundtrip_dict(self):
        from services.options_wheel_service import OptionsContract
        c = self._make_contract()
        d = c.to_dict()
        c2 = OptionsContract.from_dict(d)
        self.assertEqual(c.symbol, c2.symbol)
        self.assertEqual(c.strike, c2.strike)
        self.assertEqual(c.underlying, c2.underlying)


class TestScoringAndFiltering(unittest.TestCase):
    """Test options scoring/filtering logic ported from alpacahq/options-wheel."""

    def test_score_option_positive(self):
        from services.options_wheel_service import score_option, OptionsContract, ContractType
        c = OptionsContract(
            symbol="X", underlying="X", contract_type=ContractType.PUT,
            strike=100, expiration_date="2024-04-19", dte=14,
            delta=-0.25, bid_price=2.00, open_interest=200,
        )
        s = score_option(c)
        self.assertGreater(s, 0)

    def test_score_option_zero_strike(self):
        from services.options_wheel_service import score_option, OptionsContract, ContractType
        c = OptionsContract(
            symbol="X", underlying="X", contract_type=ContractType.PUT,
            strike=0, expiration_date="2024-04-19", dte=14,
            delta=-0.25, bid_price=2.00,
        )
        self.assertEqual(score_option(c), 0.0)

    def test_filter_options_respects_delta_range(self):
        from services.options_wheel_service import (
            filter_options, WheelConfig, OptionsContract, ContractType,
        )
        cfg = WheelConfig(delta_min=0.15, delta_max=0.30)
        contracts = [
            OptionsContract(
                symbol=f"X{i}", underlying="X", contract_type=ContractType.PUT,
                strike=100, expiration_date="2024-04-19", dte=14,
                delta=-d, bid_price=2.00, open_interest=200,
            )
            for i, d in enumerate([0.10, 0.20, 0.35, 0.25])
        ]
        filtered = filter_options(contracts, cfg)
        deltas = [abs(c.delta) for c in filtered]
        for d in deltas:
            self.assertGreaterEqual(d, 0.15)
            self.assertLessEqual(d, 0.30)

    def test_select_best_per_underlying(self):
        from services.options_wheel_service import (
            select_best_per_underlying, WheelConfig, OptionsContract, ContractType,
        )
        cfg = WheelConfig(score_min=0.01)
        contracts = [
            OptionsContract(symbol="A1", underlying="A", contract_type=ContractType.PUT,
                            strike=100, expiration_date="2024-04-19", dte=14,
                            delta=-0.20, bid_price=2.0, open_interest=200),
            OptionsContract(symbol="A2", underlying="A", contract_type=ContractType.PUT,
                            strike=100, expiration_date="2024-04-19", dte=14,
                            delta=-0.20, bid_price=4.0, open_interest=200),
            OptionsContract(symbol="B1", underlying="B", contract_type=ContractType.PUT,
                            strike=100, expiration_date="2024-04-19", dte=14,
                            delta=-0.20, bid_price=3.0, open_interest=200),
        ]
        scores = [0.05, 0.10, 0.08]
        best = select_best_per_underlying(contracts, scores, cfg)
        underlyings = [c.underlying for c, _ in best]
        self.assertEqual(len(best), 2)
        self.assertIn("A", underlyings)
        self.assertIn("B", underlyings)
        self.assertEqual(best[0][0].symbol, "A2")


class TestWheelRiskCalculation(unittest.TestCase):

    def test_short_put_risk(self):
        from services.options_wheel_service import calculate_wheel_risk, WheelPosition, WheelPhase
        positions = {
            "AAPL": WheelPosition(symbol="AAPL", phase=WheelPhase.SHORT_PUT,
                                  contract_strike=170),
        }
        risk = calculate_wheel_risk(positions)
        self.assertAlmostEqual(risk, 17000.0)

    def test_long_shares_risk(self):
        from services.options_wheel_service import calculate_wheel_risk, WheelPosition, WheelPhase
        positions = {
            "MSFT": WheelPosition(symbol="MSFT", phase=WheelPhase.LONG_SHARES,
                                  cost_basis=300, shares_qty=100),
        }
        risk = calculate_wheel_risk(positions)
        self.assertAlmostEqual(risk, 30000.0)


class TestIntegrityValidation(unittest.TestCase):

    def test_clean_state_no_issues(self):
        from services.options_wheel_service import validate_state_integrity, WheelPosition, WheelPhase
        positions = {
            "AAPL": WheelPosition(
                symbol="AAPL", phase=WheelPhase.SHORT_PUT,
                contract_symbol="AAPL240419P00170000", contract_strike=170,
            ),
        }
        issues = validate_state_integrity(positions)
        self.assertEqual(issues, [])

    def test_key_mismatch_detected(self):
        from services.options_wheel_service import validate_state_integrity, WheelPosition, WheelPhase
        positions = {
            "WRONG": WheelPosition(
                symbol="AAPL", phase=WheelPhase.SHORT_PUT,
                contract_symbol="X", contract_strike=170,
            ),
        }
        issues = validate_state_integrity(positions)
        self.assertTrue(any("mismatch" in i.lower() for i in issues))

    def test_short_put_missing_contract(self):
        from services.options_wheel_service import validate_state_integrity, WheelPosition, WheelPhase
        positions = {
            "AAPL": WheelPosition(
                symbol="AAPL", phase=WheelPhase.SHORT_PUT,
                contract_symbol=None, contract_strike=0,
            ),
        }
        issues = validate_state_integrity(positions)
        self.assertGreater(len(issues), 0)

    def test_long_shares_insufficient(self):
        from services.options_wheel_service import validate_state_integrity, WheelPosition, WheelPhase
        positions = {
            "AAPL": WheelPosition(
                symbol="AAPL", phase=WheelPhase.LONG_SHARES,
                cost_basis=170, shares_qty=50,
            ),
        }
        issues = validate_state_integrity(positions)
        self.assertTrue(any("100" in i or "shares" in i.lower() for i in issues))


class TestOptionsWheelServiceLifecycle(unittest.TestCase):
    """Test the full wheel lifecycle through the service."""

    def setUp(self):
        from services.options_wheel_service import OptionsWheelService, WheelConfig
        self.svc = OptionsWheelService(
            config=WheelConfig(max_risk=100_000),
            symbol_universe=["AAPL", "MSFT", "GOOG"],
        )

    def test_sell_put(self):
        result = self.svc.sell_put("TEST", "AAPL")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "put_sold")
        self.assertIn("AAPL", self.svc.positions)
        self.assertEqual(self.svc.positions["AAPL"].phase.value, "short_put")

    def test_sell_put_duplicate_blocked(self):
        self.svc.sell_put("TEST", "AAPL")
        result = self.svc.sell_put("TEST", "AAPL")
        self.assertIn("error", result)

    def test_assignment_transitions_to_long_shares(self):
        self.svc.sell_put("TEST", "AAPL")
        result = self.svc.record_assignment("AAPL", cost_basis=170.0)
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "assigned")
        self.assertEqual(self.svc.positions["AAPL"].phase.value, "long_shares")
        self.assertEqual(self.svc.positions["AAPL"].shares_qty, 100)

    def test_sell_call_after_assignment(self):
        self.svc.sell_put("TEST", "AAPL")
        self.svc.record_assignment("AAPL", cost_basis=170.0)
        result = self.svc.sell_call("TEST", "AAPL")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "call_sold")
        self.assertEqual(self.svc.positions["AAPL"].phase.value, "short_call")

    def test_call_away_completes_cycle(self):
        self.svc.sell_put("TEST", "AAPL")
        self.svc.record_assignment("AAPL", cost_basis=170.0)
        self.svc.sell_call("TEST", "AAPL")
        result = self.svc.record_call_away("AAPL")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "called_away")
        self.assertNotIn("AAPL", self.svc.positions)
        self.assertEqual(result["cycle_summary"]["cycles_completed"], 1)

    def test_put_expiry_removes_position(self):
        self.svc.sell_put("TEST", "MSFT")
        result = self.svc.record_put_expiry("MSFT")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "expired_worthless")
        self.assertNotIn("MSFT", self.svc.positions)

    def test_call_expiry_returns_to_long_shares(self):
        self.svc.sell_put("TEST", "AAPL")
        self.svc.record_assignment("AAPL", cost_basis=50.0)
        result = self.svc.sell_call("TEST", "AAPL")
        self.assertNotIn("error", result, f"sell_call failed: {result}")
        result = self.svc.record_call_expiry("AAPL")
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "call_expired")
        self.assertEqual(self.svc.positions["AAPL"].phase.value, "long_shares")

    def test_wrong_phase_transitions_blocked(self):
        self.svc.sell_put("TEST", "AAPL")
        result = self.svc.sell_call("TEST", "AAPL")
        self.assertIn("error", result)
        result = self.svc.record_call_away("AAPL")
        self.assertIn("error", result)

    def test_dashboard_returns_all_fields(self):
        self.svc.sell_put("TEST", "AAPL")
        dash = self.svc.get_dashboard("TEST")
        self.assertIn("total_risk", dash)
        self.assertIn("buying_power", dash)
        self.assertIn("total_premium_collected", dash)
        self.assertIn("positions", dash)
        self.assertIn("integrity_check", dash)
        self.assertIsInstance(dash["integrity_check"], list)

    def test_scan_puts_returns_candidates(self):
        result = self.svc.scan_puts("TEST")
        self.assertIn("candidates", result)
        self.assertIn("buying_power", result)
        self.assertGreater(result["buying_power"], 0)

    def test_scan_puts_no_buying_power_preserves_response_shape(self):
        self.svc.config.max_risk = 0
        result = self.svc.scan_puts("TEST")
        self.assertEqual(result["buying_power"], 0)
        self.assertEqual(result["current_risk"], 0)
        self.assertEqual(result["max_risk"], 0)
        self.assertIn("allowed_symbols", result)
        self.assertEqual(result["allowed_symbols"], ["AAPL", "MSFT", "GOOG"])

    def test_run_wheel_cycle(self):
        result = self.svc.run_wheel_cycle("TEST")
        self.assertIn("actions", result)
        self.assertIn("dashboard", result)
        self.assertIn("integrity", result)

    def test_symbol_management(self):
        result = self.svc.add_symbol("NVDA")
        self.assertEqual(result["status"], "added")
        self.assertIn("NVDA", self.svc.symbols)

        result = self.svc.remove_symbol("NVDA")
        self.assertEqual(result["status"], "removed")
        self.assertNotIn("NVDA", self.svc.symbols)

    def test_cannot_remove_symbol_with_position(self):
        self.svc.sell_put("TEST", "AAPL")
        result = self.svc.remove_symbol("AAPL")
        self.assertIn("error", result)

    def test_config_update_valid(self):
        result = self.svc.update_config({"max_risk": 50000})
        self.assertNotIn("error", result)
        self.assertEqual(self.svc.config.max_risk, 50000)

    def test_config_update_invalid(self):
        result = self.svc.update_config({"max_risk": -1})
        self.assertIn("error", result)

    def test_order_history(self):
        self.svc.sell_put("TEST", "AAPL")
        orders = self.svc.get_order_history("TEST")
        self.assertGreater(len(orders), 0)
        self.assertEqual(orders[0]["account_id"], "TEST")

    def test_audit_log(self):
        self.svc.sell_put("TEST", "AAPL")
        log = self.svc.get_audit_log()
        self.assertGreater(len(log), 0)
        self.assertEqual(log[-1]["action"], "sell_put")


class TestWheelStatePersistence(unittest.TestCase):
    """Test export/import with integrity checksums."""

    def test_export_import_roundtrip(self):
        from services.options_wheel_service import OptionsWheelService, WheelConfig
        svc = OptionsWheelService(config=WheelConfig(), symbol_universe=["AAPL"])
        svc.sell_put("TEST", "AAPL")
        state = svc.export_state()
        self.assertIn("checksum", state)
        self.assertIn("positions", state)

        svc2 = OptionsWheelService()
        result = svc2.import_state(state)
        self.assertEqual(result["status"], "imported")
        self.assertIn("AAPL", svc2.positions)

    def test_import_detects_tampered_data(self):
        from services.options_wheel_service import OptionsWheelService, WheelConfig
        svc = OptionsWheelService(config=WheelConfig(), symbol_universe=["AAPL"])
        svc.sell_put("TEST", "AAPL")
        state = svc.export_state()
        state["symbols"] = ["TAMPERED"]

        svc2 = OptionsWheelService(symbol_universe=["MSFT"])
        result = svc2.import_state(state)
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(any("checksum" in w.lower() or "tamper" in w.lower()
                            for w in result.get("warnings", [])))
        self.assertEqual(svc2.symbols, ["MSFT"])
        self.assertEqual(svc2.positions, {})


# ===================================================================
# API endpoint tests
# ===================================================================

class TestWheelAPIEndpoints(unittest.TestCase):
    """Test wheel API endpoints via HTTP."""

    def test_get_dashboard(self):
        resp = api_get("/api/wheel/dashboard")
        self.assertIn("strategy", resp)
        self.assertEqual(resp["strategy"], "options_wheel")
        self.assertIn("total_risk", resp)

    def test_get_config(self):
        resp = api_get("/api/wheel/config")
        self.assertIn("config", resp)
        cfg = resp["config"]
        self.assertIn("max_risk", cfg)
        self.assertIn("delta_min", cfg)

    def test_get_symbols(self):
        resp = api_get("/api/wheel/symbols")
        self.assertIn("symbols", resp)
        self.assertIn("count", resp)
        self.assertGreater(resp["count"], 0)

    def test_scan_puts(self):
        resp = api_get("/api/wheel/scan-puts")
        self.assertIn("candidates", resp)
        self.assertIn("buying_power", resp)

    def test_get_positions_empty(self):
        resp = api_get("/api/wheel/positions")
        self.assertIn("positions", resp)

    def test_sell_put_via_api(self):
        resp = api_post("/api/wheel/sell-put", {"underlying": "AAPL"})
        self.assertIn("status", resp)
        if "error" not in resp:
            self.assertEqual(resp["status"], "put_sold")

    def test_sell_put_missing_underlying(self):
        resp = api_post("/api/wheel/sell-put", {})
        self.assertIn("error", resp)

    def test_integrity_check(self):
        resp = api_get("/api/wheel/integrity-check")
        self.assertIn("status", resp)
        self.assertIn(resp["status"], ["clean", "issues_found"])

    def test_orders_empty(self):
        resp = api_get("/api/wheel/orders")
        self.assertIn("orders", resp)
        self.assertIn("count", resp)

    def test_audit_log_empty(self):
        resp = api_get("/api/wheel/audit-log")
        self.assertIn("audit_log", resp)

    def test_update_config_via_api(self):
        resp = api_post("/api/wheel/update-config", {"max_risk": 60000})
        if "error" not in resp:
            self.assertEqual(resp["status"], "updated")

    def test_add_remove_symbol_via_api(self):
        resp = api_post("/api/wheel/remove-symbol", {"symbol": "PEP"})
        self.assertNotIn("error", resp)
        resp = api_post("/api/wheel/add-symbol", {"symbol": "PLTR"})
        self.assertNotIn("error", resp)

    def test_run_cycle_via_api(self):
        resp = api_post("/api/wheel/run-cycle", {"account_id": "TEST"})
        self.assertIn("actions", resp)
        self.assertIn("dashboard", resp)

    def test_export_state_via_api(self):
        resp = api_post("/api/wheel/export-state")
        self.assertIn("checksum", resp)
        self.assertIn("config", resp)

    def test_full_lifecycle_via_api(self):
        """Test complete wheel cycle: sell put -> assign -> sell call -> call away."""
        r1 = api_post("/api/wheel/sell-put", {"underlying": "AAPL"})
        if "error" in r1:
            self.skipTest(f"Sell put failed: {r1['error']}")

        r2 = api_post("/api/wheel/record-assignment", {"underlying": "AAPL", "cost_basis": 50.0})
        self.assertNotIn("error", r2)
        self.assertEqual(r2["status"], "assigned")

        r3 = api_post("/api/wheel/sell-call", {"underlying": "AAPL"})
        self.assertNotIn("error", r3, f"sell-call failed: {r3}")
        self.assertEqual(r3["status"], "call_sold")

        r4 = api_post("/api/wheel/record-call-away", {"underlying": "AAPL"})
        self.assertNotIn("error", r4)
        self.assertEqual(r4["status"], "called_away")


# ===================================================================
# Strategy signal tests for new strategies
# ===================================================================

class TestNewTradingStrategies(unittest.TestCase):
    """Test new trading strategy signals added to AlgoTradingService."""

    @classmethod
    def setUpClass(cls):
        from services.algo_trading_service import get_algo_trading_service, TradingStrategy
        from services.investment_portfolio_service import get_portfolio_service
        cls.portfolio_service = get_portfolio_service()
        cls.algo_service = get_algo_trading_service(cls.portfolio_service)
        cls.TradingStrategy = TradingStrategy

    def test_options_wheel_signal(self):
        signal = self.algo_service.generate_signal("SPY", self.TradingStrategy.OPTIONS_WHEEL)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.symbol, "SPY")
        self.assertTrue(0 <= signal.confidence <= 1)
        self.assertIn("Wheel", signal.reasoning)

    def test_options_wheel_strong_sell_branch_reachable(self):
        from services.algo_trading_service import AlgoTradingService, SignalType, TechnicalIndicators

        signal_type, confidence, reasoning = AlgoTradingService._options_wheel_strategy(
            AlgoTradingService.__new__(AlgoTradingService),
            TechnicalIndicators(
                symbol="SPY",
                timestamp="2026-04-15T00:00:00",
                current_price=108.5,
                support_level=100.0,
                resistance_level=110.0,
                rsi_14=80.0,
                volatility=0.20,
            ),
        )

        self.assertEqual(signal_type, SignalType.STRONG_SELL)
        self.assertGreater(confidence, 0.70)
        self.assertIn("Strong covered call", reasoning)

    def test_covered_call_signal(self):
        signal = self.algo_service.generate_signal("AAPL", self.TradingStrategy.COVERED_CALL)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.symbol, "AAPL")
        self.assertIn("Covered call", signal.reasoning)

    def test_cash_secured_put_signal(self):
        signal = self.algo_service.generate_signal("MSFT", self.TradingStrategy.CASH_SECURED_PUT)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.symbol, "MSFT")
        self.assertIn("CSP", signal.reasoning)

    def test_iron_condor_signal(self):
        signal = self.algo_service.generate_signal("SPY", self.TradingStrategy.IRON_CONDOR)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.symbol, "SPY")
        self.assertIn("Iron condor", signal.reasoning)

    def test_protective_put_signal(self):
        signal = self.algo_service.generate_signal("QQQ", self.TradingStrategy.PROTECTIVE_PUT)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.symbol, "QQQ")
        self.assertIn("Protective put", signal.reasoning)

    def test_all_new_strategies_generate_valid_signals(self):
        new_strategies = [
            "options_wheel", "covered_call", "cash_secured_put",
            "iron_condor", "protective_put",
        ]
        for name in new_strategies:
            strategy = self.TradingStrategy(name)
            signal = self.algo_service.generate_signal("SPY", strategy)
            self.assertIsNotNone(signal, f"Signal was None for {name}")
            self.assertTrue(0 <= signal.confidence <= 1, f"Confidence out of range for {name}")
            self.assertGreater(len(signal.reasoning), 0, f"Empty reasoning for {name}")


if __name__ == "__main__":
    unittest.main()
