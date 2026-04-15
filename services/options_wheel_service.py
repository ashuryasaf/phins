"""
PHINS Options Wheel Strategy Service
======================================
Automated options wheel strategy implementation inspired by
alpacahq/options-wheel for insurance-linked investment portfolios.

The wheel strategy cycle:
1. Sell cash-secured puts on selected underlyings
2. If assigned, hold shares
3. Sell covered calls on held shares (strike >= cost basis)
4. If called away, return to step 1

Features:
- Options contract modeling with greeks and scoring
- Cash-secured put selection (delta/yield/OI/DTE filters)
- Covered call management on assigned stock
- Position state machine (short_put -> long_shares -> short_call -> repeat)
- Risk budgeting with MAX_RISK cap
- Symbol universe management
- Data integrity validation at every state transition
- Full audit trail for compliance

Integrates with PHINS algo trading and investment portfolio services.
"""

import math
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from copy import deepcopy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WheelPhase(str, Enum):
    """Where a symbol sits in the wheel lifecycle."""
    IDLE = "idle"
    SHORT_PUT = "short_put"
    LONG_SHARES = "long_shares"
    SHORT_CALL = "short_call"


class ContractType(str, Enum):
    PUT = "put"
    CALL = "call"


class WheelOrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    ASSIGNED = "assigned"
    EXERCISED = "exercised"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class WheelConfig:
    """Tuneable parameters for the wheel strategy (mirrors options-wheel params.py)."""
    max_risk: float = 80_000.0
    delta_min: float = 0.15
    delta_max: float = 0.30
    yield_min: float = 0.04
    yield_max: float = 1.00
    expiration_min_days: int = 0
    expiration_max_days: int = 21
    open_interest_min: int = 100
    score_min: float = 0.05
    max_contracts_per_symbol: int = 1
    max_symbols: int = 20

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.max_risk <= 0:
            errors.append("max_risk must be positive")
        if not (0 < self.delta_min < self.delta_max <= 1):
            errors.append("delta_min must be < delta_max and both in (0, 1]")
        if not (0 < self.yield_min < self.yield_max):
            errors.append("yield_min must be < yield_max and both positive")
        if self.expiration_min_days < 0:
            errors.append("expiration_min_days must be >= 0")
        if self.expiration_max_days <= self.expiration_min_days:
            errors.append("expiration_max_days must be > expiration_min_days")
        if self.open_interest_min < 0:
            errors.append("open_interest_min must be >= 0")
        if self.score_min < 0:
            errors.append("score_min must be >= 0")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WheelConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class OptionsContract:
    """Represents a single options contract with market data."""
    symbol: str
    underlying: str
    contract_type: ContractType
    strike: float
    expiration_date: str  # ISO date
    dte: int = 0

    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None

    bid_price: float = 0.0
    ask_price: float = 0.0
    last_price: float = 0.0
    open_interest: int = 0
    volume: int = 0

    underlying_price: float = 0.0
    score: float = 0.0

    def mid_price(self) -> float:
        if self.bid_price and self.ask_price:
            return (self.bid_price + self.ask_price) / 2.0
        return self.last_price or 0.0

    def annualized_yield(self) -> float:
        if self.strike <= 0 or self.dte < 0:
            return 0.0
        return (self.bid_price / self.strike) * (365 / max(self.dte + 1, 1))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["contract_type"] = self.contract_type.value
        d["mid_price"] = self.mid_price()
        d["annualized_yield"] = self.annualized_yield()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OptionsContract":
        data = dict(data)
        if "contract_type" in data and isinstance(data["contract_type"], str):
            data["contract_type"] = ContractType(data["contract_type"])
        data.pop("mid_price", None)
        data.pop("annualized_yield", None)
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.symbol:
            errors.append("symbol is required")
        if not self.underlying:
            errors.append("underlying is required")
        if self.strike <= 0:
            errors.append("strike must be positive")
        if self.dte < 0:
            errors.append("dte must be >= 0")
        if self.bid_price < 0:
            errors.append("bid_price must be >= 0")
        if self.ask_price < 0:
            errors.append("ask_price must be >= 0")
        return errors


@dataclass
class WheelPosition:
    """Tracks one symbol through the wheel lifecycle."""
    symbol: str
    phase: WheelPhase
    entry_date: str = ""
    cost_basis: float = 0.0
    shares_qty: int = 0
    contract_symbol: Optional[str] = None
    contract_strike: Optional[float] = None
    contract_expiry: Optional[str] = None
    contract_premium: float = 0.0
    total_premium_collected: float = 0.0
    cycles_completed: int = 0
    last_updated: str = ""

    def __post_init__(self):
        if not self.entry_date:
            self.entry_date = datetime.now().isoformat()
        if not self.last_updated:
            self.last_updated = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["phase"] = self.phase.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WheelPosition":
        data = dict(data)
        if "phase" in data and isinstance(data["phase"], str):
            data["phase"] = WheelPhase(data["phase"])
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.symbol:
            errors.append("symbol is required")
        if self.phase == WheelPhase.LONG_SHARES and self.shares_qty < 100:
            errors.append("long_shares phase requires >= 100 shares")
        if self.cost_basis < 0:
            errors.append("cost_basis must be >= 0")
        if self.total_premium_collected < 0:
            errors.append("total_premium_collected must be >= 0")
        return errors


@dataclass
class WheelOrder:
    """Audit record for every order placed by the wheel strategy."""
    order_id: str
    account_id: str
    symbol: str
    underlying: str
    contract_type: ContractType
    side: str
    strike: float
    premium: float
    quantity: int = 1
    status: WheelOrderStatus = WheelOrderStatus.PENDING
    strategy_score: float = 0.0
    created_at: str = ""
    executed_at: str = ""
    notes: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["contract_type"] = self.contract_type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WheelOrder":
        data = dict(data)
        if isinstance(data.get("contract_type"), str):
            data["contract_type"] = ContractType(data["contract_type"])
        if isinstance(data.get("status"), str):
            data["status"] = WheelOrderStatus(data["status"])
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# Strategy scoring (ported from alpacahq/options-wheel)
# ---------------------------------------------------------------------------

def filter_options(
    contracts: List[OptionsContract],
    config: WheelConfig,
    min_strike: float = 0.0,
) -> List[OptionsContract]:
    """Filter options by delta, yield, OI, DTE, and optional min strike."""
    result: List[OptionsContract] = []
    for c in contracts:
        if c.delta is None or abs(c.delta) < config.delta_min or abs(c.delta) > config.delta_max:
            continue
        ann_yield = c.annualized_yield()
        if ann_yield < config.yield_min or ann_yield > config.yield_max:
            continue
        if c.open_interest < config.open_interest_min:
            continue
        if c.dte < config.expiration_min_days or c.dte > config.expiration_max_days:
            continue
        if c.strike < min_strike:
            continue
        result.append(c)
    return result


def score_option(contract: OptionsContract) -> float:
    """
    Score = (1 - |delta|) * (250 / (dte + 5)) * (bid / strike)

    Higher score = better risk-adjusted annualized premium per dollar of capital.
    """
    if contract.strike <= 0:
        return 0.0
    delta_factor = 1.0 - abs(contract.delta or 0)
    time_factor = 250.0 / (contract.dte + 5)
    premium_factor = contract.bid_price / contract.strike
    return delta_factor * time_factor * premium_factor


def score_options(contracts: List[OptionsContract]) -> List[float]:
    return [score_option(c) for c in contracts]


def select_best_per_underlying(
    contracts: List[OptionsContract],
    scores: List[float],
    config: WheelConfig,
    top_n: Optional[int] = None,
) -> List[Tuple[OptionsContract, float]]:
    """Pick the highest-scoring contract per underlying, above score_min."""
    best: Dict[str, Tuple[OptionsContract, float]] = {}
    for contract, sc in zip(contracts, scores):
        if sc <= config.score_min:
            continue
        key = contract.underlying
        if key not in best or sc > best[key][1]:
            best[key] = (contract, sc)
    ranked = sorted(best.values(), key=lambda x: x[1], reverse=True)
    if top_n:
        ranked = ranked[:top_n]
    return ranked


# ---------------------------------------------------------------------------
# Risk calculator
# ---------------------------------------------------------------------------

def calculate_wheel_risk(positions: Dict[str, WheelPosition]) -> float:
    """Total capital at risk across all wheel positions."""
    risk = 0.0
    for pos in positions.values():
        if pos.phase == WheelPhase.SHORT_PUT:
            risk += 100 * (pos.contract_strike or 0)
        elif pos.phase in (WheelPhase.LONG_SHARES, WheelPhase.SHORT_CALL):
            risk += pos.cost_basis * pos.shares_qty
    return risk


# ---------------------------------------------------------------------------
# State integrity validator
# ---------------------------------------------------------------------------

class IntegrityError(Exception):
    """Raised when position data fails integrity checks."""
    pass


def validate_state_integrity(positions: Dict[str, WheelPosition]) -> List[str]:
    """
    Validate wheel state for consistency and data integrity.
    Returns a list of warnings/errors found (empty = clean).
    """
    issues: List[str] = []
    for sym, pos in positions.items():
        if sym != pos.symbol:
            issues.append(f"Key mismatch: dict key '{sym}' != position.symbol '{pos.symbol}'")

        errs = pos.validate()
        if errs:
            issues.extend(f"[{sym}] {e}" for e in errs)

        if pos.phase == WheelPhase.SHORT_PUT:
            if not pos.contract_symbol:
                issues.append(f"[{sym}] SHORT_PUT with no contract_symbol")
            if (pos.contract_strike or 0) <= 0:
                issues.append(f"[{sym}] SHORT_PUT with non-positive strike")

        elif pos.phase == WheelPhase.LONG_SHARES:
            if pos.shares_qty < 100:
                issues.append(f"[{sym}] LONG_SHARES with only {pos.shares_qty} shares (need >= 100)")
            if pos.cost_basis <= 0:
                issues.append(f"[{sym}] LONG_SHARES with non-positive cost_basis")

        elif pos.phase == WheelPhase.SHORT_CALL:
            if pos.shares_qty < 100:
                issues.append(f"[{sym}] SHORT_CALL with only {pos.shares_qty} shares (need >= 100)")
            if not pos.contract_symbol:
                issues.append(f"[{sym}] SHORT_CALL with no contract_symbol")
            if (pos.contract_strike or 0) <= 0:
                issues.append(f"[{sym}] SHORT_CALL with non-positive strike")

    return issues


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS = [
    "AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA", "JPM",
    "V", "UNH", "JNJ", "WMT", "PG", "HD", "BAC", "XOM", "COST",
    "ABBV", "KO", "PEP",
]


class OptionsWheelService:
    """
    End-to-end options wheel strategy manager.

    Manages the full lifecycle: put scanning -> put selling -> assignment
    tracking -> call selling -> call-away detection -> cycle restart.
    """

    def __init__(
        self,
        config: Optional[WheelConfig] = None,
        symbol_universe: Optional[List[str]] = None,
        portfolio_service: Optional[Any] = None,
    ):
        self.config = config or WheelConfig()
        self.symbols = list(symbol_universe or DEFAULT_SYMBOLS)
        self.portfolio_service = portfolio_service

        self.positions: Dict[str, WheelPosition] = {}
        self.order_history: List[WheelOrder] = []
        self.audit_log: List[Dict[str, Any]] = []
        self._order_seq = 0

    # ------------------------------------------------------------------
    # Symbol universe management
    # ------------------------------------------------------------------

    def get_symbols(self) -> List[str]:
        return list(self.symbols)

    def add_symbol(self, symbol: str) -> Dict[str, Any]:
        s = symbol.upper().strip()
        if not s:
            return {"error": "Symbol cannot be empty"}
        if s in self.symbols:
            return {"error": f"{s} already in universe"}
        if len(self.symbols) >= self.config.max_symbols:
            return {"error": f"Universe capped at {self.config.max_symbols} symbols"}
        self.symbols.append(s)
        self._audit("add_symbol", {"symbol": s})
        return {"status": "added", "symbol": s, "total": len(self.symbols)}

    def remove_symbol(self, symbol: str) -> Dict[str, Any]:
        s = symbol.upper().strip()
        if s not in self.symbols:
            return {"error": f"{s} not in universe"}
        if s in self.positions:
            return {"error": f"Cannot remove {s} while it has an active position"}
        self.symbols.remove(s)
        self._audit("remove_symbol", {"symbol": s})
        return {"status": "removed", "symbol": s, "total": len(self.symbols)}

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def get_config(self) -> Dict[str, Any]:
        return self.config.to_dict()

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        old = self.config.to_dict()
        merged = {**old, **updates}
        new_cfg = WheelConfig.from_dict(merged)
        errors = new_cfg.validate()
        if errors:
            return {"error": "Invalid configuration", "details": errors}
        self.config = new_cfg
        self._audit("update_config", {"old": old, "new": new_cfg.to_dict()})
        return {"status": "updated", "config": new_cfg.to_dict()}

    # ------------------------------------------------------------------
    # Market data simulation (demo mode)
    # ------------------------------------------------------------------

    def _generate_demo_contracts(
        self, symbol: str, contract_type: ContractType, underlying_price: float,
    ) -> List[OptionsContract]:
        """Generate realistic-looking demo option contracts for a symbol."""
        import random
        contracts: List[OptionsContract] = []
        now = datetime.now()

        step = max(1.0, round(underlying_price * 0.01, 2))
        for dte_offset in range(
            max(self.config.expiration_min_days, 7),
            self.config.expiration_max_days + 1,
            7,
        ):
            expiry = (now + timedelta(days=dte_offset)).strftime("%Y-%m-%d")
            for pct in [-0.15, -0.12, -0.10, -0.08, -0.06, -0.04, -0.02,
                        0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15]:
                strike = round(underlying_price * (1 + pct), 2)
                if strike <= 0:
                    continue

                otm_pct = abs(pct)
                if contract_type == ContractType.PUT:
                    raw_delta = -(0.50 - otm_pct * 3.0) if pct <= 0 else -(0.50 + otm_pct * 3.0)
                    raw_delta = max(-0.95, min(-0.02, raw_delta))
                else:
                    raw_delta = (0.50 + pct * 3.0) if pct >= 0 else (0.50 - abs(pct) * 3.0)
                    raw_delta = max(0.02, min(0.95, raw_delta))

                noise = random.uniform(-0.03, 0.03)
                delta = round(raw_delta + noise, 4)
                if contract_type == ContractType.PUT:
                    delta = min(-0.02, delta)
                else:
                    delta = max(0.02, delta)

                iv = 0.20 + 0.10 * otm_pct + random.uniform(-0.02, 0.02)
                time_val = math.sqrt(max(dte_offset, 1) / 365.0)
                premium = max(0.10,
                              underlying_price * iv * time_val * 0.3
                              * (1 - otm_pct * 2)
                              + random.uniform(-0.3, 0.3))

                oi = max(50, int(600 * (1 - otm_pct * 3) + random.randint(-30, 150)))

                opt_symbol = (
                    f"{symbol}{now.strftime('%y%m%d')}"
                    f"{contract_type.value[0].upper()}{int(strike*1000):08d}"
                )

                contracts.append(OptionsContract(
                    symbol=opt_symbol,
                    underlying=symbol,
                    contract_type=contract_type,
                    strike=strike,
                    expiration_date=expiry,
                    dte=dte_offset,
                    delta=delta,
                    gamma=round(abs(delta) * 0.05, 5),
                    theta=round(-premium / max(dte_offset, 1) * 0.8, 4),
                    vega=round(underlying_price * 0.01 * time_val, 4),
                    iv=round(iv, 4),
                    bid_price=round(max(0.05, premium * 0.95), 2),
                    ask_price=round(premium * 1.05, 2),
                    last_price=round(premium, 2),
                    open_interest=oi,
                    volume=max(0, oi // 3 + random.randint(-10, 30)),
                    underlying_price=underlying_price,
                ))
        return contracts

    def _demo_price(self, symbol: str) -> float:
        """Deterministic demo price for a symbol."""
        import random
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        return round(rng.uniform(30, 500), 2)

    # ------------------------------------------------------------------
    # Core wheel operations
    # ------------------------------------------------------------------

    def scan_puts(self, account_id: str = "WHEEL") -> Dict[str, Any]:
        """
        Scan for cash-secured puts to sell across the symbol universe.
        Returns scored candidates.
        """
        current_risk = calculate_wheel_risk(self.positions)
        buying_power = self.config.max_risk - current_risk
        active_syms = set(self.positions.keys())
        allowed = [s for s in self.symbols if s not in active_syms]
        if buying_power <= 0:
            return {
                "candidates": [],
                "buying_power": 0,
                "allowed_symbols": allowed,
                "current_risk": round(current_risk, 2),
                "max_risk": self.config.max_risk,
                "message": "No buying power available",
            }

        all_candidates: List[Dict[str, Any]] = []
        for sym in allowed:
            price = self._demo_price(sym)
            if 100 * price > buying_power:
                continue
            contracts = self._generate_demo_contracts(sym, ContractType.PUT, price)
            filtered = filter_options(contracts, self.config)
            if not filtered:
                continue
            scores = score_options(filtered)
            for c, sc in zip(filtered, scores):
                c.score = sc
            best = select_best_per_underlying(filtered, scores, self.config, top_n=1)
            for contract, sc in best:
                all_candidates.append({**contract.to_dict(), "score": round(sc, 6)})

        all_candidates.sort(key=lambda x: x["score"], reverse=True)

        return {
            "candidates": all_candidates,
            "buying_power": round(buying_power, 2),
            "allowed_symbols": allowed,
            "current_risk": round(current_risk, 2),
            "max_risk": self.config.max_risk,
        }

    def sell_put(
        self, account_id: str, underlying: str,
        contract_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sell a cash-secured put (enter the wheel for a symbol).
        If contract_data is None, auto-select the best put.
        """
        underlying = underlying.upper().strip()
        if underlying in self.positions:
            return {"error": f"{underlying} already has an active wheel position"}

        current_risk = calculate_wheel_risk(self.positions)
        buying_power = self.config.max_risk - current_risk

        if contract_data:
            contract = OptionsContract.from_dict(contract_data)
        else:
            price = self._demo_price(underlying)
            contracts = self._generate_demo_contracts(underlying, ContractType.PUT, price)
            filtered = filter_options(contracts, self.config)
            if not filtered:
                return {"error": f"No viable put contracts found for {underlying}"}
            scores = score_options(filtered)
            best = select_best_per_underlying(filtered, scores, self.config, top_n=1)
            if not best:
                return {"error": f"No contracts above score minimum for {underlying}"}
            contract, _ = best[0]

        required_bp = 100 * contract.strike
        if required_bp > buying_power:
            return {
                "error": "Insufficient buying power",
                "required": round(required_bp, 2),
                "available": round(buying_power, 2),
            }

        contract_errors = contract.validate()
        if contract_errors:
            return {"error": "Invalid contract data", "details": contract_errors}

        order = self._create_order(
            account_id=account_id,
            symbol=contract.symbol,
            underlying=underlying,
            contract_type=ContractType.PUT,
            side="sell",
            strike=contract.strike,
            premium=contract.bid_price,
            score=contract.score or score_option(contract),
        )
        order.status = WheelOrderStatus.FILLED
        order.executed_at = datetime.now().isoformat()

        position = WheelPosition(
            symbol=underlying,
            phase=WheelPhase.SHORT_PUT,
            contract_symbol=contract.symbol,
            contract_strike=contract.strike,
            contract_expiry=contract.expiration_date,
            contract_premium=contract.bid_price,
            total_premium_collected=contract.bid_price * 100,
        )
        self.positions[underlying] = position

        self._audit("sell_put", {
            "account_id": account_id,
            "underlying": underlying,
            "contract": contract.to_dict(),
            "order_id": order.order_id,
            "premium_collected": contract.bid_price * 100,
        })

        return {
            "status": "put_sold",
            "order": order.to_dict(),
            "position": position.to_dict(),
            "buying_power_remaining": round(buying_power - required_bp, 2),
        }

    def record_assignment(self, underlying: str, cost_basis: Optional[float] = None) -> Dict[str, Any]:
        """
        Record that a short put was assigned (we now own 100 shares).
        Transitions SHORT_PUT -> LONG_SHARES.
        """
        underlying = underlying.upper().strip()
        pos = self.positions.get(underlying)
        if not pos:
            return {"error": f"No active position for {underlying}"}
        if pos.phase != WheelPhase.SHORT_PUT:
            return {"error": f"{underlying} is in {pos.phase.value}, not short_put"}

        effective_cost = cost_basis if cost_basis is not None else (pos.contract_strike or 0)
        if effective_cost <= 0:
            return {"error": "cost_basis must be positive"}

        pos.phase = WheelPhase.LONG_SHARES
        pos.cost_basis = effective_cost
        pos.shares_qty = 100
        pos.contract_symbol = None
        pos.contract_strike = None
        pos.contract_expiry = None
        pos.contract_premium = 0
        pos.last_updated = datetime.now().isoformat()

        integrity = pos.validate()
        if integrity:
            raise IntegrityError(f"Post-assignment integrity failure for {underlying}: {integrity}")

        self._audit("assignment", {
            "underlying": underlying,
            "cost_basis": effective_cost,
            "shares": 100,
        })

        return {"status": "assigned", "position": pos.to_dict()}

    def sell_call(
        self, account_id: str, underlying: str,
        contract_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sell a covered call on assigned shares.
        Transitions LONG_SHARES -> SHORT_CALL.
        """
        underlying = underlying.upper().strip()
        pos = self.positions.get(underlying)
        if not pos:
            return {"error": f"No active position for {underlying}"}
        if pos.phase != WheelPhase.LONG_SHARES:
            return {"error": f"{underlying} is in {pos.phase.value}, expected long_shares"}
        if pos.shares_qty < 100:
            return {"error": f"Only {pos.shares_qty} shares held; need >= 100 for covered call"}

        if contract_data:
            contract = OptionsContract.from_dict(contract_data)
        else:
            price = self._demo_price(underlying)
            contracts = self._generate_demo_contracts(underlying, ContractType.CALL, price)
            filtered = filter_options(contracts, self.config, min_strike=pos.cost_basis)
            if not filtered:
                return {"error": f"No viable call contracts above cost basis ${pos.cost_basis:.2f} for {underlying}"}
            scores = score_options(filtered)
            best = select_best_per_underlying(filtered, scores, self.config, top_n=1)
            if not best:
                return {"error": f"No calls above score minimum for {underlying}"}
            contract, _ = best[0]

        contract_errors = contract.validate()
        if contract_errors:
            return {"error": "Invalid contract data", "details": contract_errors}

        if contract.strike < pos.cost_basis:
            return {
                "error": "Call strike below cost basis",
                "strike": contract.strike,
                "cost_basis": pos.cost_basis,
            }

        order = self._create_order(
            account_id=account_id,
            symbol=contract.symbol,
            underlying=underlying,
            contract_type=ContractType.CALL,
            side="sell",
            strike=contract.strike,
            premium=contract.bid_price,
            score=contract.score or score_option(contract),
        )
        order.status = WheelOrderStatus.FILLED
        order.executed_at = datetime.now().isoformat()

        pos.phase = WheelPhase.SHORT_CALL
        pos.contract_symbol = contract.symbol
        pos.contract_strike = contract.strike
        pos.contract_expiry = contract.expiration_date
        pos.contract_premium = contract.bid_price
        pos.total_premium_collected += contract.bid_price * 100
        pos.last_updated = datetime.now().isoformat()

        integrity = pos.validate()
        if integrity:
            raise IntegrityError(f"Post-sell-call integrity failure for {underlying}: {integrity}")

        self._audit("sell_call", {
            "account_id": account_id,
            "underlying": underlying,
            "contract": contract.to_dict(),
            "order_id": order.order_id,
            "premium_collected": contract.bid_price * 100,
        })

        return {
            "status": "call_sold",
            "order": order.to_dict(),
            "position": pos.to_dict(),
        }

    def record_call_away(self, underlying: str) -> Dict[str, Any]:
        """
        Record that shares were called away (covered call exercised).
        Completes the wheel cycle: SHORT_CALL -> IDLE (position removed).
        """
        underlying = underlying.upper().strip()
        pos = self.positions.get(underlying)
        if not pos:
            return {"error": f"No active position for {underlying}"}
        if pos.phase != WheelPhase.SHORT_CALL:
            return {"error": f"{underlying} is in {pos.phase.value}, not short_call"}

        pos.cycles_completed += 1
        summary = {
            "underlying": underlying,
            "cycles_completed": pos.cycles_completed,
            "total_premium_collected": round(pos.total_premium_collected, 2),
            "cost_basis": pos.cost_basis,
            "call_strike": pos.contract_strike,
            "capital_gain": round(((pos.contract_strike or 0) - pos.cost_basis) * pos.shares_qty, 2),
        }

        del self.positions[underlying]
        self._audit("call_away", summary)

        return {"status": "called_away", "cycle_summary": summary}

    def record_put_expiry(self, underlying: str) -> Dict[str, Any]:
        """Record that a short put expired worthless. Premium kept, position removed."""
        underlying = underlying.upper().strip()
        pos = self.positions.get(underlying)
        if not pos:
            return {"error": f"No active position for {underlying}"}
        if pos.phase != WheelPhase.SHORT_PUT:
            return {"error": f"{underlying} is in {pos.phase.value}, not short_put"}

        premium = pos.total_premium_collected
        del self.positions[underlying]

        self._audit("put_expiry", {
            "underlying": underlying,
            "premium_kept": round(premium, 2),
        })

        return {"status": "expired_worthless", "premium_kept": round(premium, 2)}

    def record_call_expiry(self, underlying: str) -> Dict[str, Any]:
        """Record that a short call expired worthless. Shares kept, return to LONG_SHARES."""
        underlying = underlying.upper().strip()
        pos = self.positions.get(underlying)
        if not pos:
            return {"error": f"No active position for {underlying}"}
        if pos.phase != WheelPhase.SHORT_CALL:
            return {"error": f"{underlying} is in {pos.phase.value}, not short_call"}

        pos.phase = WheelPhase.LONG_SHARES
        pos.contract_symbol = None
        pos.contract_strike = None
        pos.contract_expiry = None
        pos.contract_premium = 0
        pos.last_updated = datetime.now().isoformat()

        self._audit("call_expiry", {
            "underlying": underlying,
            "shares_retained": pos.shares_qty,
            "total_premium": round(pos.total_premium_collected, 2),
        })

        return {"status": "call_expired", "position": pos.to_dict()}

    # ------------------------------------------------------------------
    # Portfolio view
    # ------------------------------------------------------------------

    def get_positions(self) -> Dict[str, Any]:
        return {
            sym: pos.to_dict() for sym, pos in self.positions.items()
        }

    def get_position(self, underlying: str) -> Dict[str, Any]:
        underlying = underlying.upper().strip()
        pos = self.positions.get(underlying)
        if not pos:
            return {"error": f"No position for {underlying}"}
        return pos.to_dict()

    def get_dashboard(self, account_id: str = "WHEEL") -> Dict[str, Any]:
        """Comprehensive wheel strategy dashboard."""
        total_risk = calculate_wheel_risk(self.positions)
        total_premium = sum(p.total_premium_collected for p in self.positions.values())
        total_cycles = sum(p.cycles_completed for p in self.positions.values())

        by_phase: Dict[str, int] = {}
        for pos in self.positions.values():
            by_phase[pos.phase.value] = by_phase.get(pos.phase.value, 0) + 1

        return {
            "account_id": account_id,
            "strategy": "options_wheel",
            "config": self.config.to_dict(),
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "positions_by_phase": by_phase,
            "total_positions": len(self.positions),
            "total_risk": round(total_risk, 2),
            "buying_power": round(self.config.max_risk - total_risk, 2),
            "total_premium_collected": round(total_premium, 2),
            "total_cycles_completed": total_cycles,
            "symbol_universe": self.symbols,
            "available_symbols": [s for s in self.symbols if s not in self.positions],
            "integrity_check": validate_state_integrity(self.positions),
            "order_count": len(self.order_history),
            "timestamp": datetime.now().isoformat(),
        }

    def get_order_history(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        orders = self.order_history
        if account_id:
            orders = [o for o in orders if o.account_id == account_id]
        return [o.to_dict() for o in orders]

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.audit_log[-limit:]

    # ------------------------------------------------------------------
    # Run full cycle (demo / simulation)
    # ------------------------------------------------------------------

    def run_wheel_cycle(self, account_id: str = "WHEEL") -> Dict[str, Any]:
        """
        Run one complete wheel cycle iteration:
        1. For SHORT_CALL positions, simulate expiry/call-away
        2. For LONG_SHARES positions, sell covered calls
        3. For available symbols, sell puts
        """
        import random
        results: Dict[str, Any] = {"actions": [], "errors": []}

        short_calls = [
            (sym, pos) for sym, pos in list(self.positions.items())
            if pos.phase == WheelPhase.SHORT_CALL
        ]
        for sym, pos in short_calls:
            outcome = random.choice(["expire", "called_away"])
            if outcome == "called_away":
                r = self.record_call_away(sym)
            else:
                r = self.record_call_expiry(sym)
            results["actions"].append({"symbol": sym, "action": outcome, "result": r})

        long_shares = [
            (sym, pos) for sym, pos in list(self.positions.items())
            if pos.phase == WheelPhase.LONG_SHARES
        ]
        for sym, pos in long_shares:
            r = self.sell_call(account_id, sym)
            if "error" in r:
                results["errors"].append({"symbol": sym, "error": r["error"]})
            else:
                results["actions"].append({"symbol": sym, "action": "sell_call", "result": r})

        short_puts = [
            (sym, pos) for sym, pos in list(self.positions.items())
            if pos.phase == WheelPhase.SHORT_PUT
        ]
        for sym, pos in short_puts:
            outcome = random.choice(["expire", "assigned"])
            if outcome == "assigned":
                r = self.record_assignment(sym)
            else:
                r = self.record_put_expiry(sym)
            results["actions"].append({"symbol": sym, "action": outcome, "result": r})

        scan = self.scan_puts(account_id)
        candidates = scan.get("candidates", [])[:3]
        for cand in candidates:
            r = self.sell_put(account_id, cand["underlying"], cand)
            if "error" in r:
                results["errors"].append({"symbol": cand["underlying"], "error": r["error"]})
            else:
                results["actions"].append({
                    "symbol": cand["underlying"],
                    "action": "sell_put",
                    "result": r,
                })

        results["dashboard"] = self.get_dashboard(account_id)
        results["integrity"] = validate_state_integrity(self.positions)
        return results

    # ------------------------------------------------------------------
    # Persistence helpers (JSON serialization)
    # ------------------------------------------------------------------

    def export_state(self) -> Dict[str, Any]:
        """Export full service state for persistence."""
        return {
            "config": self.config.to_dict(),
            "symbols": self.symbols,
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "order_history": [o.to_dict() for o in self.order_history],
            "audit_log": self.audit_log,
            "exported_at": datetime.now().isoformat(),
            "checksum": self._compute_checksum(),
        }

    def import_state(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Import state from persisted data with integrity checks."""
        errors: List[str] = []

        if "checksum" in data:
            stored_cs = data["checksum"]
            data_copy = {k: v for k, v in data.items() if k not in ("checksum", "exported_at")}
            actual_cs = hashlib.md5(json.dumps(data_copy, sort_keys=True, default=str).encode()).hexdigest()
            if stored_cs != actual_cs:
                errors.append("Checksum mismatch — data may have been tampered with")
                return {"status": "rejected", "warnings": errors}

        if "config" in data:
            cfg = WheelConfig.from_dict(data["config"])
            cfg_errors = cfg.validate()
            if cfg_errors:
                errors.extend(f"Config: {e}" for e in cfg_errors)
            else:
                self.config = cfg

        if "symbols" in data:
            self.symbols = list(data["symbols"])

        if "positions" in data:
            self.positions = {
                k: WheelPosition.from_dict(v) for k, v in data["positions"].items()
            }
            integrity = validate_state_integrity(self.positions)
            if integrity:
                errors.extend(integrity)

        if "order_history" in data:
            self.order_history = [WheelOrder.from_dict(o) for o in data["order_history"]]

        if "audit_log" in data:
            self.audit_log = list(data["audit_log"])

        return {"status": "imported", "warnings": errors}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_order(
        self, account_id: str, symbol: str, underlying: str,
        contract_type: ContractType, side: str, strike: float,
        premium: float, score: float = 0.0,
    ) -> WheelOrder:
        self._order_seq += 1
        order = WheelOrder(
            order_id=f"WHL-{self._order_seq:06d}",
            account_id=account_id,
            symbol=symbol,
            underlying=underlying,
            contract_type=contract_type,
            side=side,
            strike=strike,
            premium=premium,
            strategy_score=score,
        )
        self.order_history.append(order)
        return order

    def _audit(self, action: str, details: Dict[str, Any]) -> None:
        self.audit_log.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
        })

    def _compute_checksum(self) -> str:
        data = {
            "config": self.config.to_dict(),
            "symbols": self.symbols,
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "order_history": [o.to_dict() for o in self.order_history],
            "audit_log": self.audit_log,
        }
        return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_wheel_service: Optional[OptionsWheelService] = None


def get_options_wheel_service(
    portfolio_service: Optional[Any] = None,
) -> OptionsWheelService:
    global _wheel_service
    if _wheel_service is None:
        _wheel_service = OptionsWheelService(portfolio_service=portfolio_service)
    return _wheel_service


def reset_options_wheel_service() -> None:
    """Reset the singleton (useful for tests)."""
    global _wheel_service
    _wheel_service = None
