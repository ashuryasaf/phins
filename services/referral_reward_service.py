"""Referral acquisition-reward book.

A new customer who registers with another customer's invitation code is an
edge in a chain. When that customer pays a premium bill, PHINS recognizes one
customer-acquisition fee and divides it across up to three referrers above
them. The default fee is $650. Layer 1 (the direct affiliate) receives that
whole fee when nobody stands above them. Layer 2 takes $100 from the fee when
that affiliate's own invitation succeeded, and layer 3 takes $50. Whatever is
not taken by an upper layer stays with the direct affiliate. The total fee is
adjustable, and the program can instead use a percent of the annual premium
that affiliation sold. The same dollar schedule is then the proportion of the
computed fee. The fee is an expense on the general reserves the moment it is
earned. It is not moved into a personal balance until the referrer accepts it
and chooses a destination the program allows for that layer: premium credit,
health wallet, savings, or cash.

The fee stops at the third layer, so the cost of acquiring one paying customer
is capped and known before the invitation goes out. One paying customer
produces one settlement: a single acquisition expense for the layers that
exist. That amount is allocated immediately and blocked from the referrer
until a hold of ``hold_months`` (the default is 3, set by an admin or an
actuary) has elapsed and the affiliated customer is still paying. If the
paid balance lapses before anyone accepts, the settlement is reversed and
is not booked again. Agent commission (a percentage of premium, locked per
affiliation) is a different rail and is not paid again here.

Amounts are integer cents. A fixed fee pays the configured dollars exactly.
A premium-percent fee uses the largest-remainder method so the layers equal
the computed fee exactly. A later change to the program never rewrites a
reward that was already earned. Rewards sealed under the older
percentage-share program stay on that snapshot.
Every reward id is ``RWRD-{referee}-L{layer}``, so the same paying customer
cannot fund a layer twice. The durable copy is a checksummed JSON file when
the portal is in memory, and the ``referral_rewards`` tables when the
database is on. A checksum that does not match is quarantined and never paid.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode, urlsplit

logger = logging.getLogger("phins.referral_rewards")

DESTINATIONS: Tuple[str, ...] = ("premium", "health_wallet", "savings", "cash")
LAYERS = (1, 2, 3)
_LOCK = threading.RLock()
_STATE_ENV = "PHINS_REFERRAL_REWARDS_PATH"

CONFIG: Dict[str, Any] = {}
LINKS: Dict[str, Dict[str, Any]] = {}          # referee_customer_id -> link
REWARDS: Dict[str, Dict[str, Any]] = {}        # reward id -> reward
SETTLEMENTS: Dict[str, Dict[str, Any]] = {}    # referee_customer_id -> one settlement
REQUESTS: Dict[str, Dict[str, Any]] = {}       # request id -> professional request
QUARANTINE: List[Dict[str, Any]] = []
FLAGS: Dict[str, Any] = {}

_loaded = False
_LEGACY_REWARD_FIELDS = (
    "id", "referee_customer_id", "beneficiary_customer_id", "layer", "status",
    "fee_cents", "share_bps", "amount_cents", "currency", "program_shares",
    "policy", "allocation", "posted", "books_tx_id", "ledger_entry_id",
    "earned_at", "dispatched_at",
)
_CHECK_FIELDS = _LEGACY_REWARD_FIELDS + ("settlement_id", "hold_months", "release_at")
_SETTLEMENT_FIELDS = (
    "id", "referee_customer_id", "fee_cents", "allocated_cents", "retained_cents",
    "status", "hold_months", "paying_at", "release_at", "reversed_at",
    "books_tx_id", "reversal_tx_id", "ledger_entry_id",
    "released_ledger_id", "reversal_ledger_id",
)


class RewardError(ValueError):
    """A reward or program change the caller can correct."""

    def __init__(self, message: str, status: int = 400, code: str = "reward_error"):
        super().__init__(message)
        self.status = status
        self.code = code

    def to_dict(self) -> Dict[str, Any]:
        body = {"error": str(self), "code": self.code}
        release_at = getattr(self, "release_at", None)
        if release_at:
            body["release_at"] = release_at
        return body


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _add_months(stamp: str, months: int) -> str:
    """Calendar months after ``stamp``. The day clamps to the last day of the month."""
    text = str(stamp or "").replace("Z", "+00:00")
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    months = int(months)
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    if month == 12:
        following = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        following = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    last_day = (following - timedelta(days=1)).day
    shifted = moment.replace(year=year, month=month, day=min(moment.day, last_day))
    return shifted.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canon(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha(payload: Any) -> str:
    return hashlib.sha256(_canon(payload).encode("utf-8")).hexdigest()


def dollars(cents: int) -> float:
    return round(int(cents) / 100.0, 2)


def cents_from_dollars(value: Any) -> int:
    try:
        quantized = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise RewardError("Amount must be a number of dollars") from exc
    if quantized < 0:
        raise RewardError("Amount cannot be negative")
    return int(quantized * 100)


def percent_to_bps(value: Any) -> int:
    try:
        quantized = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise RewardError("Percent must be a number") from exc
    bps = int(quantized * 100)
    if bps < 0 or bps > 10000:
        raise RewardError("Percent must be between 0 and 100")
    return bps


def bps_to_percent(bps: int) -> float:
    return round(int(bps) / 100.0, 2)


def allocate_cents(total: int, weights_bps: Sequence[int]) -> List[int]:
    """Split ``total`` cents by basis-point weights that sum to 10000.

    Largest remainder, ties broken by the earlier index, so the parts sum
    back to ``total`` with no cent left over and no cent invented.
    """
    total = int(total)
    weights = [int(w) for w in weights_bps]
    if sum(weights) != 10000:
        raise RewardError("Shares must add up to 100%")
    if total < 0:
        raise RewardError("Amount cannot be negative")
    raw = [total * w for w in weights]
    floors = [r // 10000 for r in raw]
    leftover = total - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-(raw[i] % 10000), i))
    for k in range(leftover):
        floors[order[k]] += 1
    return floors


def _weights_to_bps(weights: Sequence[int], total: int) -> List[int]:
    """Express ``weights`` (which sum to ``total``) as basis points that sum to 10000."""
    weights = [int(w) for w in weights]
    total = int(total)
    if total <= 0 or sum(weights) != total:
        raise RewardError("Weights must add up to the total")
    raw = [w * 10000 for w in weights]
    floors = [r // total for r in raw]
    leftover = 10000 - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-(raw[i] % total), i))
    for k in range(leftover):
        floors[order[k]] += 1
    return floors


def waterfall_amounts(fee_cents: int, schedule_cents: Sequence[int],
                      filled_layers: Sequence[int]) -> List[int]:
    """Split one acquisition fee across the layers that actually exist.

    ``schedule_cents`` is ``[layer1_full, layer2, layer3]``. Layer 1's figure
    is the reference total (the direct affiliate's amount when nobody is above
    them). Layers 2 and 3 are taken from that total only when those affiliates
    are in the chain. The remainder stays with layer 1. When ``fee_cents``
    equals the reference, the configured dollars are paid exactly. Otherwise
    the same proportions are applied to the computed fee.
    """
    fee = int(fee_cents)
    schedule = [int(part) for part in schedule_cents]
    if len(schedule) != 3:
        raise RewardError("The layer schedule needs three amounts")
    if fee < 0 or any(part < 0 for part in schedule):
        raise RewardError("Amount cannot be negative")
    present = {int(layer) for layer in filled_layers}
    if fee == 0 or 1 not in present:
        return [0, 0, 0]
    reference = schedule[0]
    if reference <= 0:
        raise RewardError("The total fee must be positive")
    if schedule[1] + schedule[2] > reference:
        raise RewardError("Layer 2 and layer 3 together cannot exceed the total fee")
    layer2 = schedule[1] if 2 in present else 0
    layer3 = schedule[2] if 3 in present else 0
    if fee == reference:
        return [fee - layer2 - layer3, layer2, layer3]
    weights = [reference - layer2 - layer3, layer2, layer3]
    return allocate_cents(fee, _weights_to_bps(weights, reference))


DESTINATION_LINKS: Dict[str, Dict[str, str]] = {
    "premium": {
        "label": "Billing",
        "href": "/billing.html",
        "customer_href": "/dashboard.html#billing",
    },
    "health_wallet": {
        "label": "Health wallet",
        "href": "/dashboard.html#health-wallet",
        "customer_href": "/dashboard.html#health-wallet",
    },
    "savings": {
        "label": "Investments",
        "href": "/savings-portfolio.html",
        "customer_href": "/dashboard.html#investment-portfolio",
    },
    "cash": {
        "label": "Billing",
        "href": "/billing.html",
        "customer_href": "/dashboard.html#billing",
    },
}


def default_config() -> Dict[str, Any]:
    """$650 total. Layer 1 keeps it all when alone; layer 2 takes $100; layer 3 takes $50.

    Layer 1 may take cash. Layers 2 and 3 stay inside the platform (premium,
    health wallet, savings) unless an admin opens cash for them. The default
    split is a suggestion; the referrer chooses at acceptance. ``premium_rate_bps``
    is the percent of annual premium used when ``fee_mode`` is ``premium_percent``.
    """
    return {
        "version": 1,
        "enabled": True,
        "currency": "USD",
        "fee_mode": "fixed",
        "fee_cents": 65000,
        "premium_rate_bps": 1000,
        "max_layers": 3,
        "customer_invitation_cap": 10,
        "agent_invitation_cap": 100,
        "agent_default_rate_percent": 10,
        "hold_months": 3,
        "auto_dispatch": False,
        "layers": [
            {
                "layer": 1,
                "amount_cents": 65000,
                "allowed": ["premium", "health_wallet", "savings", "cash"],
                "cash_cap_bps": 10000,
                "default_bps": {"premium": 0, "health_wallet": 5000, "savings": 5000, "cash": 0},
            },
            {
                "layer": 2,
                "amount_cents": 10000,
                "allowed": ["premium", "health_wallet", "savings"],
                "cash_cap_bps": 0,
                "default_bps": {"premium": 4000, "health_wallet": 3000, "savings": 3000, "cash": 0},
            },
            {
                "layer": 3,
                "amount_cents": 5000,
                "allowed": ["premium", "health_wallet", "savings"],
                "cash_cap_bps": 0,
                "default_bps": {"premium": 10000, "health_wallet": 0, "savings": 0, "cash": 0},
            },
        ],
    }


def _blank_bps() -> Dict[str, int]:
    return {dest: 0 for dest in DESTINATIONS}


def _layer_amount_cents(item: Dict[str, Any]) -> Optional[int]:
    if item.get("amount_cents") is not None:
        return int(item.get("amount_cents") or 0)
    if item.get("amount") is not None:
        return cents_from_dollars(item.get("amount"))
    return None


def _validate_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise RewardError("Program config must be an object")
    fee = int(raw.get("fee_cents") or 0)
    if fee < 0 or fee > 10_000_000:
        raise RewardError("Fee must be between $0 and $100,000")
    fee_mode = str(raw.get("fee_mode") or "fixed").strip().lower()
    if fee_mode not in ("fixed", "premium_percent"):
        raise RewardError("Fee basis must be fixed or a percent of annual premium")
    if raw.get("premium_rate_bps") is not None:
        premium_rate = int(raw.get("premium_rate_bps") or 0)
    else:
        premium_rate = 1000
    if premium_rate < 0 or premium_rate > 10000:
        raise RewardError("Premium percent must be between 0 and 100")
    if fee_mode == "premium_percent" and premium_rate <= 0:
        raise RewardError("Percent of annual premium must be greater than 0")
    max_layers = int(raw.get("max_layers") or 3)
    if max_layers not in LAYERS:
        raise RewardError("max_layers must be 1, 2, or 3")
    customer_cap = int(raw.get("customer_invitation_cap") or 0)
    agent_cap = int(raw.get("agent_invitation_cap") or 0)
    if not 1 <= customer_cap <= 10000 or not 1 <= agent_cap <= 10000:
        raise RewardError("Invitation caps must be between 1 and 10000")
    if agent_cap < customer_cap:
        raise RewardError("The agent invitation cap cannot be below the customer cap")
    rate = int(raw.get("agent_default_rate_percent") or 0)
    if rate < 0 or rate > 100:
        raise RewardError("Agent default rate must be between 0 and 100 percent")
    if "hold_months" in raw and raw.get("hold_months") is not None:
        hold_months = int(raw.get("hold_months"))
    else:
        hold_months = 3
    if hold_months < 0 or hold_months > 60:
        raise RewardError("Hold must be between 0 and 60 months")
    incoming = raw.get("layers")
    if not isinstance(incoming, list) or len(incoming) != 3:
        raise RewardError("Exactly three layers are required")
    by_layer: Dict[int, Dict[str, Any]] = {}
    for item in incoming:
        if not isinstance(item, dict):
            raise RewardError("Each layer must be an object")
        layer = int(item.get("layer") or 0)
        if layer not in LAYERS or layer in by_layer:
            raise RewardError("Layers must be 1, 2 and 3 with no duplicates")
        allowed = [str(d) for d in (item.get("allowed") or [])]
        if any(d not in DESTINATIONS for d in allowed) or len(set(allowed)) != len(allowed):
            raise RewardError("A layer destination is not recognized")
        if not allowed:
            raise RewardError(f"Layer {layer} needs at least one destination")
        cash_cap = int(item.get("cash_cap_bps") or 0)
        if cash_cap < 0 or cash_cap > 10000:
            raise RewardError("Cash cap must be between 0 and 100 percent")
        if "cash" in allowed and cash_cap <= 0:
            raise RewardError(f"Layer {layer} allows cash but the cash cap is 0")
        if "cash" not in allowed and cash_cap > 0:
            raise RewardError(f"Layer {layer} sets a cash cap without allowing cash")
        default = _blank_bps()
        source = item.get("default_bps") or {}
        if not isinstance(source, dict):
            raise RewardError("Layer default must be an object")
        for key, value in source.items():
            if key not in DESTINATIONS:
                raise RewardError(f"Unknown destination '{key}'")
            default[key] = int(value or 0)
            if default[key] < 0:
                raise RewardError("A default share cannot be negative")
            if default[key] and key not in allowed:
                raise RewardError(f"Layer {layer} defaults to {key}, which it does not allow")
        if sum(default.values()) != 10000:
            raise RewardError(f"Layer {layer} default shares must add up to 100%")
        if default["cash"] > cash_cap:
            raise RewardError(f"Layer {layer} default cash exceeds the cash cap")
        by_layer[layer] = {
            "layer": layer,
            "amount_cents": _layer_amount_cents(item),
            "share_bps": int(item.get("share_bps") or 0),
            "allowed": allowed,
            "cash_cap_bps": cash_cap,
            "default_bps": default,
        }
    if any(by_layer[n]["amount_cents"] is None for n in LAYERS):
        shares = [by_layer[n]["share_bps"] for n in LAYERS]
        if fee <= 0 or any(part < 0 for part in shares) or sum(shares) != 10000:
            raise RewardError("Each layer needs a dollar amount, or legacy shares that add up to 100%")
        derived = allocate_cents(fee, shares)
        # A saved percentage program becomes a waterfall: the direct affiliate's
        # full amount is the fee, and the old upper shares are the carve-outs.
        by_layer[1]["amount_cents"] = fee
        by_layer[2]["amount_cents"] = derived[1]
        by_layer[3]["amount_cents"] = derived[2]
    amounts = [int(by_layer[n]["amount_cents"]) for n in LAYERS]
    if any(part < 0 for part in amounts):
        raise RewardError("A layer amount cannot be negative")
    if amounts[0] != fee:
        raise RewardError(
            "Layer 1 is the full fee when that affiliate has nobody above them, so it must equal the total fee"
        )
    if amounts[1] + amounts[2] > fee:
        raise RewardError("Layer 2 and layer 3 together cannot exceed the total fee")
    if fee > 0:
        display = waterfall_amounts(fee, amounts, LAYERS)
        shares = _weights_to_bps(display, fee)
    else:
        shares = [10000, 0, 0]
    for layer, share in zip(LAYERS, shares):
        by_layer[layer]["share_bps"] = share
        by_layer[layer]["amount_cents"] = amounts[layer - 1]
    return {
        "version": int(raw.get("version") or 1),
        "enabled": bool(raw.get("enabled", True)),
        "currency": "USD",
        "fee_mode": fee_mode,
        "fee_cents": fee,
        "premium_rate_bps": premium_rate,
        "max_layers": max_layers,
        "customer_invitation_cap": customer_cap,
        "agent_invitation_cap": agent_cap,
        "agent_default_rate_percent": rate,
        "hold_months": hold_months,
        "auto_dispatch": bool(raw.get("auto_dispatch", False)),
        "layers": [by_layer[n] for n in LAYERS],
    }


def _layer_policy(cfg: Dict[str, Any], layer: int) -> Dict[str, Any]:
    for item in cfg["layers"]:
        if int(item["layer"]) == int(layer):
            return item
    raise RewardError(f"Layer {layer} is not in the program")


def _schedule_cents(cfg: Dict[str, Any]) -> List[int]:
    return [int(item["amount_cents"]) for item in cfg["layers"]]


def _preview_amounts(cfg: Dict[str, Any]) -> Dict[str, List[float]]:
    schedule = _schedule_cents(cfg)
    fee = int(cfg.get("fee_cents") or 0)
    def pack(filled: Sequence[int]) -> List[float]:
        if fee <= 0:
            return [0.0, 0.0, 0.0]
        return [dollars(part) for part in waterfall_amounts(fee, schedule, filled)]
    return {
        "alone": pack((1,)),
        "two_layers": pack((1, 2)),
        "three_layers": pack((1, 2, 3)),
    }


def config_to_admin(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or CONFIG or default_config()
    return {
        "version": cfg["version"],
        "enabled": cfg["enabled"],
        "currency": cfg["currency"],
        "fee_mode": cfg.get("fee_mode") or "fixed",
        "fee": dollars(cfg["fee_cents"]),
        "fee_cents": cfg["fee_cents"],
        "premium_percent": bps_to_percent(int(cfg.get("premium_rate_bps") or 0)),
        "premium_rate_bps": int(cfg.get("premium_rate_bps") or 0),
        "max_layers": cfg["max_layers"],
        "customer_invitation_cap": cfg["customer_invitation_cap"],
        "agent_invitation_cap": cfg["agent_invitation_cap"],
        "agent_default_rate_percent": cfg["agent_default_rate_percent"],
        "hold_months": int(cfg.get("hold_months", 3)),
        "auto_dispatch": cfg["auto_dispatch"],
        "preview": _preview_amounts(cfg),
        "layers": [
            {
                "layer": item["layer"],
                "amount": dollars(int(item.get("amount_cents") or 0)),
                "amount_cents": int(item.get("amount_cents") or 0),
                "share_percent": bps_to_percent(int(item.get("share_bps") or 0)),
                "allowed": list(item["allowed"]),
                "cash_cap_percent": bps_to_percent(item["cash_cap_bps"]),
                "default": {k: bps_to_percent(v) for k, v in item["default_bps"].items()},
            }
            for item in cfg["layers"]
        ],
    }


def _admin_to_internal(raw: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    """Merge an admin patch (dollars and percents) onto the current program."""
    base = config_to_admin(previous)
    for key in ("enabled", "fee_mode", "max_layers", "customer_invitation_cap",
                "agent_invitation_cap", "agent_default_rate_percent", "hold_months",
                "auto_dispatch"):
        if key in raw and raw[key] is not None:
            base[key] = raw[key]
    fee_set = False
    if raw.get("fee") is not None:
        base["fee"] = raw["fee"]
        fee_set = True
    elif raw.get("fee_cents") is not None:
        base["fee"] = dollars(int(raw["fee_cents"]))
        fee_set = True
    if raw.get("premium_percent") is not None:
        base["premium_percent"] = raw["premium_percent"]
    elif raw.get("premium_rate_bps") is not None:
        base["premium_percent"] = bps_to_percent(int(raw["premium_rate_bps"]))
    layer1_set = False
    if isinstance(raw.get("layers"), list):
        by = {int(item["layer"]): dict(item) for item in base["layers"]}
        for patch in raw["layers"]:
            if not isinstance(patch, dict) or "layer" not in patch:
                raise RewardError("Each layer patch needs a layer number")
            layer = int(patch["layer"])
            current = dict(by.get(layer) or {"layer": layer})
            if patch.get("share_percent") is not None and patch.get("amount") is None and patch.get("amount_cents") is None:
                raise RewardError(
                    "Set each layer as a dollar amount. The acquisition schedule is no longer a set of shares that must add to 100%"
                )
            if patch.get("amount") is not None:
                current["amount"] = patch["amount"]
                if layer == 1:
                    layer1_set = True
            elif patch.get("amount_cents") is not None:
                current["amount"] = dollars(int(patch["amount_cents"]))
                if layer == 1:
                    layer1_set = True
            for key in ("allowed", "cash_cap_percent"):
                if key in patch and patch[key] is not None:
                    current[key] = patch[key]
            if isinstance(patch.get("default"), dict):
                merged_default = dict(current.get("default") or {})
                merged_default.update(patch["default"])
                current["default"] = merged_default
            by[layer] = current
        base["layers"] = [by[n] for n in LAYERS]
    if fee_set and not layer1_set:
        base["layers"][0]["amount"] = base["fee"]
    elif layer1_set and not fee_set:
        base["fee"] = base["layers"][0]["amount"]
    layers = []
    for item in base["layers"]:
        default = item.get("default") or {}
        layers.append({
            "layer": int(item["layer"]),
            "amount_cents": cents_from_dollars(item.get("amount", 0)),
            "allowed": list(item.get("allowed") or []),
            "cash_cap_bps": percent_to_bps(item.get("cash_cap_percent", 0)),
            "default_bps": {dest: percent_to_bps(default.get(dest, 0)) for dest in DESTINATIONS},
        })
    return _validate_config({
        "version": int(previous.get("version") or 1),
        "enabled": base["enabled"],
        "fee_mode": base.get("fee_mode") or "fixed",
        "fee_cents": cents_from_dollars(base["fee"]),
        "premium_rate_bps": percent_to_bps(base.get("premium_percent", 0)),
        "max_layers": base["max_layers"],
        "customer_invitation_cap": base["customer_invitation_cap"],
        "agent_invitation_cap": base["agent_invitation_cap"],
        "agent_default_rate_percent": base["agent_default_rate_percent"],
        "hold_months": base.get("hold_months", 3),
        "auto_dispatch": base["auto_dispatch"],
        "layers": layers,
    })


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _state_path() -> Path:
    override = os.environ.get(_STATE_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "database" / "referral_rewards_state.json"


def _db_enabled() -> bool:
    try:
        from services.hydrated_store import db_mode_enabled
        return bool(db_mode_enabled())
    except Exception:
        return False


def _repo():
    from database.manager import DatabaseManager
    return DatabaseManager()


def _reward_checksum(reward: Dict[str, Any]) -> str:
    # Rows sealed before the single-settlement hold have no settlement id.
    # Their checksum stays over the original field list.
    fields = _CHECK_FIELDS if reward.get("settlement_id") else _LEGACY_REWARD_FIELDS
    return _sha({key: reward.get(key) for key in fields})


def _settlement_checksum(settlement: Dict[str, Any]) -> str:
    return _sha({key: settlement.get(key) for key in _SETTLEMENT_FIELDS})


def _seal_settlement(settlement: Dict[str, Any]) -> Dict[str, Any]:
    settlement["checksum"] = _settlement_checksum(settlement)
    return settlement


def _settlement_intact(settlement: Dict[str, Any]) -> bool:
    stated = str(settlement.get("checksum") or "")
    if not stated or settlement.get("_quarantined"):
        return False
    return stated == _settlement_checksum(settlement)


def _seal(reward: Dict[str, Any]) -> Dict[str, Any]:
    reward["checksum"] = _reward_checksum(reward)
    return reward


def _reward_intact(reward: Dict[str, Any]) -> bool:
    stated = str(reward.get("checksum") or "")
    if not stated:
        return False
    return stated == _reward_checksum(reward)


def _envelope() -> Dict[str, Any]:
    return {
        "version": 1,
        "config": CONFIG,
        "links": list(LINKS.values()),
        "rewards": list(REWARDS.values()),
        "settlements": list(SETTLEMENTS.values()),
        "requests": list(REQUESTS.values()),
    }


def _save_file() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = _envelope()
    blob = {"checksum": _sha(state), "state": state}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(blob, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _persist_settlement(settlement: Dict[str, Any]) -> None:
    _seal_settlement(settlement)
    if _db_enabled():
        with _repo() as db:
            db.referral_rewards.upsert_settlement(settlement)
        return
    _save_file()


def _persist_reward(reward: Dict[str, Any]) -> None:
    _seal(reward)
    if _db_enabled():
        with _repo() as db:
            db.referral_rewards.upsert_reward(reward)
        return
    _save_file()


def _persist_link(link: Dict[str, Any]) -> None:
    if _db_enabled():
        with _repo() as db:
            db.referral_rewards.upsert_link(link)
        return
    _save_file()


def _persist_request(req: Dict[str, Any]) -> None:
    if _db_enabled():
        with _repo() as db:
            db.referral_rewards.upsert_request(req)
        return
    _save_file()


def _persist_config() -> None:
    if _db_enabled():
        with _repo() as db:
            db.referral_rewards.save_config(CONFIG, _sha(CONFIG), _now(), str(CONFIG.get("updated_by") or "system"))
        return
    _save_file()


def _apply_reward(reward: Dict[str, Any]) -> None:
    if not _reward_intact(reward):
        QUARANTINE.append({"id": reward.get("id"), "reason": "checksum_mismatch"})
        return
    REWARDS[str(reward["id"])] = reward


def _load_file() -> None:
    path = _state_path()
    if not path.exists():
        return
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        FLAGS["state_unreadable"] = True
        return
    state = blob.get("state")
    if not isinstance(state, dict) or _sha(state) != blob.get("checksum"):
        FLAGS["state_checksum_mismatch"] = True
        return
    try:
        loaded = _validate_config(state.get("config") or {})
    except RewardError:
        FLAGS["config_rejected"] = True
        loaded = default_config()
    CONFIG.clear()
    CONFIG.update(loaded)
    for link in state.get("links") or []:
        if isinstance(link, dict) and link.get("referee_customer_id"):
            LINKS[str(link["referee_customer_id"])] = link
    for reward in state.get("rewards") or []:
        if isinstance(reward, dict):
            _apply_reward(reward)
    for settlement in state.get("settlements") or []:
        if isinstance(settlement, dict):
            _apply_settlement(settlement)
    for req in state.get("requests") or []:
        if isinstance(req, dict) and req.get("id"):
            REQUESTS[str(req["id"])] = req


def _apply_settlement(settlement: Dict[str, Any]) -> None:
    referee = str(settlement.get("referee_customer_id") or "")
    if not referee:
        return
    if not _settlement_intact(settlement):
        QUARANTINE.append({"id": settlement.get("id"), "reason": "settlement_checksum_mismatch"})
        blocked = dict(settlement)
        blocked["_quarantined"] = True
        SETTLEMENTS[referee] = blocked
        return
    SETTLEMENTS[referee] = settlement


def _hydrate_db() -> None:
    try:
        with _repo() as db:
            stored = db.referral_rewards.get_config()
            links = db.referral_rewards.list_links()
            rewards = db.referral_rewards.list_rewards()
            settlements = db.referral_rewards.list_settlements()
            requests = db.referral_rewards.list_requests()
    except Exception:
        FLAGS["db_unreadable"] = True
        return
    if stored and isinstance(stored.get("payload"), dict):
        if _sha(stored["payload"]) != stored.get("checksum"):
            FLAGS["config_checksum_mismatch"] = True
        else:
            try:
                CONFIG.clear()
                CONFIG.update(_validate_config(stored["payload"]))
            except RewardError:
                FLAGS["config_rejected"] = True
    for link in links:
        LINKS[str(link["referee_customer_id"])] = link
    for reward in rewards:
        _apply_reward(reward)
    for settlement in settlements:
        _apply_settlement(settlement)
    for req in requests:
        REQUESTS[str(req["id"])] = req


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    CONFIG.clear()
    CONFIG.update(_validate_config(default_config()))
    if _db_enabled():
        _hydrate_db()
    else:
        _load_file()
    _loaded = True


def reset_referral_rewards() -> None:
    """Drop the in-memory book and the file copy. Used by tests."""
    global _loaded
    with _LOCK:
        CONFIG.clear()
        CONFIG.update(_validate_config(default_config()))
        LINKS.clear()
        REWARDS.clear()
        SETTLEMENTS.clear()
        REQUESTS.clear()
        QUARANTINE.clear()
        FLAGS.clear()
        _loaded = True
        if not _db_enabled():
            path = _state_path()
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Portal ports (lazy; the service never imports the server at module load)
# ---------------------------------------------------------------------------
def _portal():
    import sys
    return sys.modules.get("web_portal.server") or sys.modules.get("server")


def _customers() -> Dict[str, Any]:
    portal = _portal()
    if portal is None:
        return {}
    customers = getattr(portal, "CUSTOMERS", None)
    return customers if isinstance(customers, dict) else {}


def _billing() -> Dict[str, Any]:
    portal = _portal()
    if portal is None:
        return {}
    billing = getattr(portal, "BILLING", None)
    return billing if isinstance(billing, dict) else {}


def _first_name(customer_id: str) -> str:
    rec = _customers().get(customer_id) if customer_id else None
    name = str((rec or {}).get("name") or "").strip()
    if not name:
        return "A customer"
    return name.split()[0][:40]


def _customer_record(customer_id: str) -> Optional[Dict[str, Any]]:
    rec = _customers().get(customer_id)
    return rec if isinstance(rec, dict) else None


def _mapped_customer(customer_id: str) -> Optional[Dict[str, Any]]:
    """One customer row, including the database-backed store.

    ``CUSTOMERS`` is a ``DatabaseDict`` when the database is on. That store
    has ``get`` and is not a ``dict``. The reward book keeps the dict-only
    port above; identity and the inquiry address read this one.
    """
    portal = _portal()
    customers = getattr(portal, "CUSTOMERS", None) if portal else None
    if customers is None or not hasattr(customers, "get"):
        return None
    try:
        rec = customers.get(str(customer_id or ""))
    except Exception:
        return None
    return rec if isinstance(rec, dict) else None


def _policies() -> Dict[str, Any]:
    portal = _portal()
    if portal is None:
        return {}
    policies = getattr(portal, "POLICIES", None)
    return policies if isinstance(policies, dict) else {}


def _annual_premium_cents(customer_id: str) -> int:
    """Annual premium sold to this affiliated customer, in cents.

    Active policy rows win. A customer record is used only when no policy
    carries a premium, so the same premium is not counted twice.
    """
    customer_id = str(customer_id or "")
    closed = {"cancelled", "canceled", "void", "declined", "lapsed", "terminated"}
    total = Decimal("0")
    found = False
    for policy in _policies().values():
        if not isinstance(policy, dict):
            continue
        if str(policy.get("customer_id") or "") != customer_id:
            continue
        if str(policy.get("status") or "").lower() in closed:
            continue
        try:
            amount = Decimal(str(policy.get("annual_premium") or 0))
        except Exception:
            continue
        if amount > 0:
            total += amount
            found = True
    if not found:
        rec = _customer_record(customer_id) or {}
        try:
            total = Decimal(str(rec.get("annual_premium") or 0))
        except Exception:
            total = Decimal("0")
    if total < 0:
        return 0
    return cents_from_dollars(total)


def _percent_of_cents(total_cents: int, rate_bps: int) -> int:
    if int(total_cents) <= 0 or int(rate_bps) <= 0:
        return 0
    quantized = (Decimal(int(total_cents)) * Decimal(int(rate_bps)) / Decimal(10000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP,
    )
    return int(quantized)


def _fee_basis_for(customer_id: str, cfg: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """The fee for this paying customer, and the schedule snapshot that produced it."""
    schedule = _schedule_cents(cfg)
    mode = str(cfg.get("fee_mode") or "fixed")
    rate = int(cfg.get("premium_rate_bps") or 0)
    premium = 0
    if mode == "premium_percent":
        premium = _annual_premium_cents(customer_id)
        fee = _percent_of_cents(premium, rate)
    else:
        fee = int(cfg.get("fee_cents") or 0)
    return fee, {
        "fee_mode": mode,
        "schedule_cents": schedule,
        "premium_cents": premium,
        "premium_rate_bps": rate,
    }


def _is_paying(customer_id: str, billing: Optional[Dict[str, Any]] = None) -> bool:
    book = billing if isinstance(billing, dict) else _billing()
    for bill in book.values():
        if not isinstance(bill, dict):
            continue
        if str(bill.get("customer_id") or "") != str(customer_id):
            continue
        if str(bill.get("status") or "").lower() != "paid":
            continue
        amount = bill.get("amount_paid")
        if amount in (None, ""):
            amount = bill.get("amount", bill.get("amount_due", 0))
        try:
            if float(amount or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _parent_of(customer_id: str, customers: Dict[str, Any]) -> Optional[str]:
    rec = customers.get(customer_id)
    if isinstance(rec, dict) and rec.get("referred_by"):
        return str(rec["referred_by"])
    link = LINKS.get(str(customer_id))
    if link and link.get("referrer_customer_id"):
        return str(link["referrer_customer_id"])
    return None


def chain_of(referee_id: str, customers: Optional[Dict[str, Any]] = None,
             max_layers: Optional[int] = None) -> List[Tuple[int, str]]:
    """Referrers above ``referee_id``, nearest first. Stops on a cycle or a gap."""
    customers = customers if isinstance(customers, dict) else _customers()
    limit = int(max_layers if max_layers is not None else (CONFIG.get("max_layers") or 3))
    limit = max(0, min(3, limit))
    seen = {str(referee_id)}
    current = str(referee_id)
    found: List[Tuple[int, str]] = []
    for layer in range(1, limit + 1):
        parent = _parent_of(current, customers)
        if not parent or parent in seen or parent not in customers:
            break
        seen.add(parent)
        found.append((layer, parent))
        current = parent
    return found


def _sheet_transactions() -> List[Dict[str, Any]]:
    portal = _portal()
    sheet = getattr(portal, "PHINS_BALANCE_SHEET", None) if portal else None
    if not isinstance(sheet, dict):
        return []
    rows = sheet.get("transactions") or []
    return [row for row in rows if isinstance(row, dict)]


def _find_sheet_tx(kind: str, settlement_id: str) -> Optional[str]:
    for tx in _sheet_transactions():
        meta = tx.get("metadata") if isinstance(tx.get("metadata"), dict) else {}
        if meta.get("kind") == kind and meta.get("settlement_id") == settlement_id:
            return str(tx.get("tx_id") or "")
    return None


def _ensure_acquisition_category() -> None:
    portal = _portal()
    sheet = getattr(portal, "PHINS_BALANCE_SHEET", None) if portal else None
    if not isinstance(sheet, dict):
        return
    breakdown = sheet.setdefault("expense_breakdown", {})
    if isinstance(breakdown, dict):
        breakdown.setdefault("customer_acquisition", 0.0)


def _book_settlement(settlement: Dict[str, Any], reward_ids: Sequence[str]) -> Optional[str]:
    """Recognize the acquisition expense once for this settlement."""
    portal = _portal()
    if portal is None or not hasattr(portal, "record_balance_sheet_transaction"):
        return None
    _ensure_acquisition_category()
    existing = _find_sheet_tx("cac_settlement", settlement["id"])
    if existing:
        return existing
    posted = portal.record_balance_sheet_transaction(
        tx_type="expense",
        category="customer_acquisition",
        amount=dollars(settlement["allocated_cents"]),
        description=f"Referral acquisition settlement {settlement['id']}",
        actor="referral_rewards",
        customer_id=settlement["referee_customer_id"],
        metadata={
            "kind": "cac_settlement",
            "settlement_id": settlement["id"],
            "referee_customer_id": settlement["referee_customer_id"],
            "fee_cents": settlement["fee_cents"],
            "allocated_cents": settlement["allocated_cents"],
            "retained_cents": settlement["retained_cents"],
            "hold_months": settlement["hold_months"],
            "reward_ids": list(reward_ids),
            "fee_mode": settlement.get("fee_mode"),
            "premium_cents": settlement.get("premium_cents"),
            "premium_rate_bps": settlement.get("premium_rate_bps"),
            "schedule_cents": settlement.get("schedule_cents"),
        },
    )
    return str((posted or {}).get("tx_id") or "")


def _reverse_books(settlement: Dict[str, Any]) -> Optional[str]:
    """Back the single expense out. A second call finds the reversal already posted."""
    portal = _portal()
    if portal is None or not hasattr(portal, "record_balance_sheet_transaction"):
        return settlement.get("reversal_tx_id")
    _ensure_acquisition_category()
    existing = _find_sheet_tx("cac_settlement_reversal", settlement["id"])
    if existing:
        return existing
    posted = portal.record_balance_sheet_transaction(
        tx_type="expense",
        category="customer_acquisition",
        amount=-dollars(settlement["allocated_cents"]),
        description=f"Reversal of referral acquisition settlement {settlement['id']}",
        actor="referral_rewards",
        customer_id=settlement["referee_customer_id"],
        metadata={
            "kind": "cac_settlement_reversal",
            "settlement_id": settlement["id"],
            "referee_customer_id": settlement["referee_customer_id"],
            "reverses": settlement.get("books_tx_id"),
            "allocated_cents": settlement["allocated_cents"],
        },
    )
    return str((posted or {}).get("tx_id") or "")


def _anchor(reward: Dict[str, Any], event_type: str, entry_suffix: str) -> Optional[str]:
    portal = _portal()
    ledger = getattr(portal, "platform_event_ledger", None) if portal else None
    if ledger is None or not hasattr(ledger, "append_event"):
        return None
    entry_id = f"{entry_suffix}-{reward['id']}"
    try:
        entry = ledger.append_event(
            event_type=event_type,
            entity_type="referral_reward",
            entity_id=reward["id"],
            customer_id=reward["beneficiary_customer_id"],
            actor="referral_rewards",
            amount=dollars(reward["amount_cents"]),
            currency="USD",
            payload={
                "reward_id": reward["id"],
                "referee_customer_id": reward["referee_customer_id"],
                "layer": reward["layer"],
                "status": reward.get("status"),
                "allocation": reward.get("allocation"),
            },
            entry_id=entry_id,
        )
    except Exception:
        return None
    return str((entry or {}).get("id") or entry_id)


def _deliver(customer_id: str, subject: str, message: str) -> None:
    rec = _customer_record(customer_id)
    email = str((rec or {}).get("email") or "").strip()
    if not rec or not email:
        return
    try:
        from services.notification_service import create_notification_service, should_use_mock_notifications
        from services.customer_agent.communication import get_customer_communication_agent
        agent = get_customer_communication_agent(
            notification_service=create_notification_service(use_mock=should_use_mock_notifications())
        )
        agent.send_customer_outreach(
            customer_id=customer_id,
            customer_name=str(rec.get("name") or "PHINS Customer"),
            email=email,
            template="reward",
            channels="email",
            subject=subject,
            custom_message=message,
            login_url="/dashboard.html#referrals",
            actor="referral_rewards",
            customer_record=rec,
        )
    except Exception:
        return


def _sync_stats(reward: Dict[str, Any]) -> None:
    portal = _portal()
    stats_book = getattr(portal, "CUSTOMER_REFERRAL_STATS", None) if portal else None
    if not isinstance(stats_book, dict):
        return
    beneficiary = reward["beneficiary_customer_id"]
    stats = stats_book.setdefault(beneficiary, {
        "codes_generated": 0, "successful_referrals": 0, "codes": [],
        "referred_customers": [], "rewards": [], "total_reward_value": 0,
    })
    dispatched = sum(
        int(item.get("amount_cents") or 0)
        for item in REWARDS.values()
        if item.get("beneficiary_customer_id") == beneficiary and item.get("status") == "dispatched"
    )
    stats["total_reward_value"] = dollars(dispatched)
    if int(reward.get("layer") or 0) != 1:
        return
    for entry in stats.get("referred_customers") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("customer_id") or "") != str(reward["referee_customer_id"]):
            continue
        entry["reward_status"] = reward["status"]
        entry["reward_amount"] = dollars(reward["amount_cents"])
        entry["reward_claimed"] = reward["status"] == "dispatched"


def supplier_type_values() -> List[str]:
    try:
        from services.supply_chain_ecosystem_service import SupplierType
        return [item.value for item in SupplierType]
    except Exception:
        return ["doctor", "lawyer", "pharmacy", "delivery", "hospital", "clinic",
                "laboratory", "equipment", "wellness", "financial", "tech_provider", "other"]


def _approved_request(customer_id: str, role: str) -> Optional[Dict[str, Any]]:
    req = REQUESTS.get(f"PRO-{customer_id}-{role}")
    if req and req.get("status") == "approved":
        return req
    return None


_JOIN_CODE_RE = re.compile(r"^[A-Za-z0-9-]{1,80}$")


def affiliated_join_link(code: str) -> str:
    """The public intro page for one invitation code.

    The address is the same shape an admin invitation uses. The code is the
    only query value, so the reward chain is the customer who issued it and
    the layers already above that customer. A parent id is not written onto
    the link.
    """
    cleaned = str(code or "").strip()
    if not _JOIN_CODE_RE.fullmatch(cleaned):
        return ""
    origin = ""
    portal = _portal()
    getter = getattr(portal, "public_portal_base_url", None) if portal else None
    if callable(getter):
        try:
            origin = str(getter() or "").strip().rstrip("/")
        except Exception:
            origin = ""
    path = "/join.html?code=" + cleaned
    return f"{origin}{path}" if origin else path


def affiliation_for(customer_id: str) -> Dict[str, Any]:
    """Layers already above this customer.

    Someone who opens the join link is a new edge. This customer is layer 1
    for that person. The people above stay on the layers they already hold.
    """
    with _LOCK:
        _ensure_loaded()
        customer_id = str(customer_id or "").strip()
        above = []
        for layer, parent in chain_of(customer_id):
            above.append({
                "layer": layer,
                "customer_id": parent,
                "name": _first_name(parent),
            })
        return {
            "customer_id": customer_id,
            "layers_above": above,
            "invite_places_you_at_layer": 1,
        }


def invitation_cap_for(customer_id: str) -> int:
    """Customers share a small book of codes; an approved agent gets the larger one."""
    with _LOCK:
        _ensure_loaded()
        cfg = CONFIG or default_config()
        if _approved_request(customer_id, "agent"):
            return int(cfg["agent_invitation_cap"])
        rec = _customer_record(customer_id)
        if rec and rec.get("agent_id"):
            return int(cfg["agent_invitation_cap"])
        return int(cfg["customer_invitation_cap"])


# ---------------------------------------------------------------------------
# Join + earn
# ---------------------------------------------------------------------------
def on_customer_joined(*, referee_customer_id: str, referrer_customer_id: str,
                       invitation_code: str = "", referee_name: str = "") -> Dict[str, Any]:
    """Record the invitation edge and tell the sender. No money moves yet."""
    referee = str(referee_customer_id or "").strip()
    referrer = str(referrer_customer_id or "").strip()
    if not referee or not referrer or referee == referrer:
        return {"recorded": False}
    notify = False
    with _LOCK:
        _ensure_loaded()
        link = LINKS.get(referee)
        if link is None:
            link = {
                "id": f"REFL-{referee}",
                "referee_customer_id": referee,
                "referrer_customer_id": referrer,
                "invitation_code": str(invitation_code or ""),
                "referee_name": str(referee_name or "")[:120],
                "joined_at": _now(),
                "paying_at": None,
                "notified_join": False,
            }
            LINKS[referee] = link
            _persist_link(link)
        notify = not link.get("notified_join")
        if notify:
            link["notified_join"] = True
            _persist_link(link)
    if notify:
        _deliver(
            referrer,
            "Someone joined PHINS with your invitation",
            f"{_first_name(referee)} registered with your code {invitation_code or ''}. "
            "When they pay their first premium, your share of the acquisition reward "
            "is earned and you choose where it goes: premium, health wallet, savings, or cash.",
        )
    return {"recorded": True, "link": dict(LINKS.get(referee) or {})}


def _policy_snapshot(cfg: Dict[str, Any], layer: int, basis: Dict[str, Any]) -> Dict[str, Any]:
    item = _layer_policy(cfg, layer)
    return {
        "allowed": list(item["allowed"]),
        "cash_cap_bps": int(item["cash_cap_bps"]),
        "default_bps": dict(item["default_bps"]),
        "allocation_method": "waterfall",
        "fee_mode": basis.get("fee_mode") or "fixed",
        "schedule_cents": [int(part) for part in basis.get("schedule_cents") or []],
        "premium_cents": int(basis.get("premium_cents") or 0),
        "premium_rate_bps": int(basis.get("premium_rate_bps") or 0),
        "filled_layers": [int(layer_no) for layer_no in basis.get("filled_layers") or []],
    }


def on_customer_paying(customer_id: str, billing: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Allocate one settlement for this paying customer, split across the chain.

    Idempotent. A second call finds the same settlement and does not book
    the expense again. The layers stay blocked until ``release_at``. If the
    paid balance is gone before anyone accepts, the settlement is reversed.
    """
    referee = str(customer_id or "").strip()
    if not referee:
        return []
    created: List[Dict[str, Any]] = []
    with _LOCK:
        _ensure_loaded()
        existing = SETTLEMENTS.get(referee)
        if existing is not None:
            if existing.get("status") != "reversed" and not existing.get("_quarantined"):
                _refresh_settlement_locked(existing, billing)
            return []
        if not CONFIG.get("enabled", True):
            return []
        if not _is_paying(referee, billing):
            return []
        customers = _customers()
        if referee not in customers and referee not in LINKS:
            return []
        cfg = CONFIG
        found = chain_of(referee, customers, cfg["max_layers"])
        fee_cents, basis = _fee_basis_for(referee, cfg)
        filled = [layer for layer, _beneficiary in found]
        basis["filled_layers"] = filled
        if fee_cents <= 0 or not filled:
            return []
        try:
            amounts = waterfall_amounts(fee_cents, basis["schedule_cents"], filled)
        except RewardError:
            raise
        link = LINKS.get(referee)
        paying_at = _now()
        if link is not None and not link.get("paying_at"):
            link["paying_at"] = paying_at
            _persist_link(link)
        elif link is not None and link.get("paying_at"):
            paying_at = str(link["paying_at"])
        hold_months = int(cfg.get("hold_months", 3))
        release_at = _add_months(paying_at, hold_months)
        settlement_id = f"CACSET-{referee}"
        pending: List[Dict[str, Any]] = []
        paid_shares = _weights_to_bps(amounts, fee_cents) if sum(amounts) == fee_cents and fee_cents else [0, 0, 0]
        for layer, beneficiary in found:
            amount = amounts[layer - 1]
            if amount <= 0 or beneficiary == referee:
                continue
            direct = found[0][1] if found else ""
            code = ""
            if link and str(link.get("referrer_customer_id")) == str(direct):
                code = str(link.get("invitation_code") or "")
            reward_id = f"RWRD-{referee}-L{layer}"
            if REWARDS.get(reward_id) is not None:
                continue
            pending.append({
                "id": reward_id,
                "referee_customer_id": referee,
                "beneficiary_customer_id": beneficiary,
                "layer": layer,
                "invitation_code": code if layer == 1 else "",
                "status": "held",
                "fee_cents": fee_cents,
                "share_bps": paid_shares[layer - 1],
                "amount_cents": amount,
                "currency": "USD",
                "program_shares": paid_shares,
                "policy": _policy_snapshot(cfg, layer, basis),
                "allocation": None,
                "posted": {},
                "books_tx_id": None,
                "ledger_entry_id": None,
                "earned_at": paying_at,
                "dispatched_at": None,
                "settlement_id": settlement_id,
                "hold_months": hold_months,
                "release_at": release_at,
            })
        if not pending:
            return []
        allocated = sum(int(item["amount_cents"]) for item in pending)
        settlement = {
            "id": settlement_id,
            "referee_customer_id": referee,
            "fee_cents": fee_cents,
            "allocated_cents": allocated,
            "retained_cents": fee_cents - allocated,
            "fee_mode": basis.get("fee_mode") or "fixed",
            "premium_cents": int(basis.get("premium_cents") or 0),
            "premium_rate_bps": int(basis.get("premium_rate_bps") or 0),
            "schedule_cents": list(basis.get("schedule_cents") or []),
            "status": "held",
            "hold_months": hold_months,
            "paying_at": paying_at,
            "release_at": release_at,
            "reversed_at": None,
            "books_tx_id": None,
            "reversal_tx_id": None,
            "ledger_entry_id": None,
            "released_ledger_id": None,
            "reversal_ledger_id": None,
        }
        SETTLEMENTS[referee] = settlement
        for reward in pending:
            _seal(reward)
            REWARDS[reward["id"]] = reward
        try:
            settlement["books_tx_id"] = _book_settlement(settlement, [item["id"] for item in pending])
            settlement["ledger_entry_id"] = _anchor_settlement(
                settlement, "referral.settlement.allocated", settlement_id,
            )
            for reward in pending:
                reward["books_tx_id"] = settlement["books_tx_id"]
                reward["ledger_entry_id"] = settlement["ledger_entry_id"]
                _persist_reward(reward)
                _sync_stats(reward)
            _persist_settlement(settlement)
            _refresh_settlement_locked(settlement, billing)
            if cfg.get("auto_dispatch"):
                for reward in pending:
                    if reward.get("status") != "earned":
                        continue
                    try:
                        _dispatch_locked(reward, None)
                    except RewardError as exc:
                        reward["dispatch_error"] = str(exc)
                        _persist_reward(reward)
        except Exception:
            for reward in pending:
                REWARDS.pop(reward["id"], None)
            SETTLEMENTS.pop(referee, None)
            raise
        created = list(pending)
    for reward in created:
        amount = f"{dollars(reward['amount_cents']):.2f}"
        if reward.get("status") == "held":
            _deliver(
                reward["beneficiary_customer_id"],
                f"{amount} USD from a PHINS invitation is allocated and blocked",
                f"Layer {reward['layer']} (${amount}) is allocated and blocked until "
                f"{reward.get('release_at')}. It is released only if that customer is still paying.",
            )
        elif reward.get("status") != "dispatched":
            _deliver(
                reward["beneficiary_customer_id"],
                f"You earned {amount} USD from a PHINS invitation",
                f"A customer in your invitation chain is still paying. "
                f"Layer {reward['layer']} of your acquisition reward is ${amount}. "
                "Open Referrals and choose premium credit, health wallet, savings, or cash.",
            )
    return [dict(item) for item in created]


def recompute(customers: Optional[Dict[str, Any]] = None,
              billing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Backfill join edges and rewards from the customer and bill books."""
    customers = customers if isinstance(customers, dict) else _customers()
    billing = billing if isinstance(billing, dict) else _billing()
    joined = 0
    earned = 0
    for customer_id, rec in list(customers.items()):
        if not isinstance(rec, dict):
            continue
        parent = rec.get("referred_by")
        if parent:
            before = customer_id in LINKS
            on_customer_joined(
                referee_customer_id=str(customer_id),
                referrer_customer_id=str(parent),
                invitation_code=str(rec.get("invitation_code") or ""),
                referee_name=str(rec.get("name") or ""),
            )
            if not before and customer_id in LINKS:
                joined += 1
        if _is_paying(str(customer_id), billing) or str(customer_id) in SETTLEMENTS:
            earned += len(on_customer_paying(str(customer_id), billing))
    with _LOCK:
        _ensure_loaded()
        _refresh_all_locked(billing)
    anchored = _backfill_anchors()
    return {"links_recorded": joined, "rewards_created": earned, "anchors_written": anchored}


def _rewards_for(referee: str) -> List[Dict[str, Any]]:
    return [reward for reward in REWARDS.values() if str(reward.get("referee_customer_id")) == str(referee)]


def _anchor_settlement(settlement: Dict[str, Any], event_type: str, entry_id: str) -> Optional[str]:
    portal = _portal()
    ledger = getattr(portal, "platform_event_ledger", None) if portal else None
    if ledger is None or not hasattr(ledger, "append_event"):
        return None
    try:
        entry = ledger.append_event(
            event_type=event_type,
            entity_type="referral_settlement",
            entity_id=settlement["id"],
            customer_id=settlement["referee_customer_id"],
            actor="referral_rewards",
            amount=dollars(settlement.get("allocated_cents") or 0),
            currency="USD",
            payload={
                "settlement_id": settlement["id"],
                "referee_customer_id": settlement["referee_customer_id"],
                "status": settlement.get("status"),
                "hold_months": settlement.get("hold_months"),
                "release_at": settlement.get("release_at"),
                "allocated_cents": settlement.get("allocated_cents"),
                "retained_cents": settlement.get("retained_cents"),
                "books_tx_id": settlement.get("books_tx_id"),
                "reversal_tx_id": settlement.get("reversal_tx_id"),
            },
            entry_id=entry_id,
        )
    except Exception:
        return None
    return str((entry or {}).get("id") or entry_id)


def _reverse_settlement_locked(settlement: Dict[str, Any]) -> None:
    if settlement.get("status") == "reversed" or settlement.get("_quarantined"):
        return
    if any(reward.get("status") == "dispatched" for reward in _rewards_for(settlement["referee_customer_id"])):
        return
    settlement["reversal_tx_id"] = _reverse_books(settlement)
    settlement["status"] = "reversed"
    settlement["reversed_at"] = _now()
    settlement["reversal_ledger_id"] = _anchor_settlement(
        settlement, "referral.settlement.reversed", f"CACREV-{settlement['id']}",
    )
    for reward in _rewards_for(settlement["referee_customer_id"]):
        if reward.get("status") in ("held", "earned") and _reward_intact(reward):
            reward["status"] = "forfeited"
            _persist_reward(reward)
    _persist_settlement(settlement)


def _refresh_settlement_locked(settlement: Dict[str, Any],
                               billing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Release a held settlement, or reverse it when the paid balance is gone."""
    if settlement.get("_quarantined") or settlement.get("status") in ("settled", "reversed"):
        return settlement
    referee = str(settlement.get("referee_customer_id") or "")
    rewards = _rewards_for(referee)
    dispatched = any(reward.get("status") == "dispatched" for reward in rewards)
    paying = _is_paying(referee, billing)
    if not paying and not dispatched and settlement.get("status") in ("held", "releasable"):
        _reverse_settlement_locked(settlement)
        return settlement
    release_at = str(settlement.get("release_at") or "")
    if paying and release_at and _now() >= release_at and settlement.get("status") == "held":
        settlement["status"] = "releasable"
        for reward in rewards:
            if reward.get("status") == "held" and _reward_intact(reward):
                reward["status"] = "earned"
                _persist_reward(reward)
        _persist_settlement(settlement)
    return settlement


def _refresh_all_locked(billing: Optional[Dict[str, Any]] = None) -> None:
    for settlement in list(SETTLEMENTS.values()):
        _refresh_settlement_locked(settlement, billing)


def _maybe_settle_locked(settlement: Dict[str, Any]) -> None:
    if settlement.get("status") in ("settled", "reversed", None) or settlement.get("_quarantined"):
        return
    rewards = [
        reward for reward in _rewards_for(settlement["referee_customer_id"])
        if int(reward.get("amount_cents") or 0) > 0
    ]
    if not rewards or any(reward.get("status") != "dispatched" for reward in rewards):
        return
    settlement["status"] = "settled"
    settlement["released_ledger_id"] = _anchor_settlement(
        settlement, "referral.settlement.released", f"CACREL-{settlement['id']}",
    )
    _persist_settlement(settlement)


def _backfill_anchors() -> int:
    written = 0
    with _LOCK:
        _ensure_loaded()
        for settlement in list(SETTLEMENTS.values()):
            if settlement.get("_quarantined"):
                continue
            changed = False
            if not settlement.get("ledger_entry_id"):
                anchor = _anchor_settlement(
                    settlement, "referral.settlement.allocated", settlement["id"],
                )
                if anchor:
                    settlement["ledger_entry_id"] = anchor
                    changed = True
                    written += 1
            if settlement.get("status") == "reversed" and not settlement.get("reversal_ledger_id"):
                anchor = _anchor_settlement(
                    settlement, "referral.settlement.reversed", f"CACREV-{settlement['id']}",
                )
                if anchor:
                    settlement["reversal_ledger_id"] = anchor
                    changed = True
                    written += 1
            if settlement.get("status") == "settled" and not settlement.get("released_ledger_id"):
                anchor = _anchor_settlement(
                    settlement, "referral.settlement.released", f"CACREL-{settlement['id']}",
                )
                if anchor:
                    settlement["released_ledger_id"] = anchor
                    changed = True
                    written += 1
            if changed:
                _persist_settlement(settlement)
        for reward in list(REWARDS.values()):
            if reward.get("ledger_entry_id") or reward.get("settlement_id"):
                continue
            anchor = _anchor(reward, "referral.reward.earned", "CAC")
            if anchor:
                reward["ledger_entry_id"] = anchor
                _persist_reward(reward)
                written += 1
    return written


# ---------------------------------------------------------------------------
# Acceptance / dispatch
# ---------------------------------------------------------------------------
def _allocation_from_input(reward: Dict[str, Any], raw: Optional[Dict[str, Any]]) -> Dict[str, int]:
    policy = reward.get("policy") or {}
    allowed = set(policy.get("allowed") or [])
    cash_cap = int(policy.get("cash_cap_bps") or 0)
    if not raw:
        default = dict(policy.get("default_bps") or _blank_bps())
        return {dest: int(default.get(dest) or 0) for dest in DESTINATIONS}
    if not isinstance(raw, dict):
        raise RewardError("Allocation must be an object of destination → percent")
    unknown = [key for key in raw if key not in DESTINATIONS]
    if unknown:
        raise RewardError(f"Unknown destination: {unknown[0]}")
    bps = _blank_bps()
    for dest in DESTINATIONS:
        if dest not in raw or raw[dest] in (None, ""):
            continue
        bps[dest] = percent_to_bps(raw[dest])
        if bps[dest] and dest not in allowed:
            raise RewardError(f"Layer {reward['layer']} cannot use {dest}", code="destination_not_allowed")
    if sum(bps.values()) != 10000:
        raise RewardError("The destination split must add up to 100%")
    if bps["cash"] > cash_cap:
        raise RewardError(
            f"Cash on layer {reward['layer']} is capped at {bps_to_percent(cash_cap):.2f}%",
            code="cash_cap",
        )
    return bps


def _post_health_wallet(reward: Dict[str, Any], cents: int) -> Dict[str, Any]:
    portal = _portal()
    wallets = getattr(portal, "HEALTH_WALLETS", None) if portal else None
    if not isinstance(wallets, dict):
        raise RewardError("Health wallet store is unavailable", status=503, code="wallet_unavailable")
    customer_id = reward["beneficiary_customer_id"]
    wallet = wallets.get(customer_id)
    if not isinstance(wallet, dict):
        wallet = {
            "customer_id": customer_id, "balance": 0.0, "monthly_deposit": 0.0,
            "transactions": [], "created_at": _now(),
        }
        wallets[customer_id] = wallet
    tx_id = f"REFREWARD-{reward['id']}-health"
    txs = wallet.setdefault("transactions", [])
    for tx in txs:
        if isinstance(tx, dict) and tx.get("id") == tx_id:
            return {"id": tx_id, "amount": tx.get("amount")}
    amount = dollars(cents)
    previous = float(wallet.get("balance") or 0)
    wallet["balance"] = round(previous + amount, 2)
    txs.append({
        "id": tx_id,
        "type": "referral_reward",
        "amount": amount,
        "source": "PHINS_CAC",
        "reward_id": reward["id"],
        "description": f"Referral reward {reward['id']}",
        "previous_balance": previous,
        "balance_after": wallet["balance"],
        "timestamp": _now(),
    })
    return {"id": tx_id, "amount": amount}


def _post_savings(reward: Dict[str, Any], cents: int) -> Dict[str, Any]:
    portal = _portal()
    service = getattr(portal, "savings_pipeline_service", None) if portal else None
    enabled = bool(getattr(portal, "savings_pipeline_enabled", False)) if portal else False
    if not enabled or service is None or not hasattr(service, "deposit_to_pipeline"):
        raise RewardError("Savings pipeline is unavailable", status=503, code="savings_unavailable")
    result = service.deposit_to_pipeline(
        customer_id=reward["beneficiary_customer_id"],
        amount=dollars(cents),
        source="referral_reward",
        auto_allocate=True,
    )
    if not isinstance(result, dict) or not result.get("success", True):
        raise RewardError((result or {}).get("error") or "Savings deposit failed", code="savings_failed")
    return {"amount": dollars(cents), "ok": True}


def _post_premium(reward: Dict[str, Any], cents: int) -> Dict[str, Any]:
    portal = _portal()
    service = getattr(portal, "billing_credit_service", None) if portal else None
    if service is None or not hasattr(service, "create_credit"):
        raise RewardError("Premium credit store is unavailable", status=503, code="credit_unavailable")
    from services.billing_credit_service import CreditType
    credit = service.create_credit(
        customer_id=reward["beneficiary_customer_id"],
        amount=dollars(cents),
        credit_type=CreditType.LOYALTY,
        reason=f"Referral reward {reward['id']}",
        description=reward["id"],
    )
    credit_id = getattr(credit, "credit_id", None) or (credit.get("credit_id") if isinstance(credit, dict) else None)
    if not credit_id:
        raise RewardError("Premium credit was not created", code="credit_failed")
    return {"credit_id": credit_id, "amount": dollars(cents)}


def _post_cash(reward: Dict[str, Any], cents: int) -> Dict[str, Any]:
    """Cash leaves the company. The expense was already recognized at earn time."""
    portal = _portal()
    if portal is None or not hasattr(portal, "record_transaction"):
        raise RewardError("Ledger is unavailable", status=503, code="ledger_unavailable")
    tx = portal.record_transaction(
        customer_id=reward["beneficiary_customer_id"],
        tx_type="referral_reward_cash",
        amount=dollars(cents),
        description=f"Referral reward {reward['id']} paid as cash",
        metadata={"reward_id": reward["id"], "kind": "cac_reward_cash", "layer": reward["layer"]},
    )
    return {"id": str((tx or {}).get("id") or ""), "amount": dollars(cents)}


_POSTERS = {
    "health_wallet": _post_health_wallet,
    "savings": _post_savings,
    "premium": _post_premium,
    "cash": _post_cash,
}


def _release_guard(reward: Dict[str, Any]) -> None:
    """Block acceptance until the hold has elapsed and the affiliated balance holds."""
    settlement_id = reward.get("settlement_id")
    if not settlement_id:
        if reward.get("status") == "forfeited":
            raise RewardError("This reward was forfeited", status=409, code="forfeited")
        return
    settlement = SETTLEMENTS.get(str(reward.get("referee_customer_id")))
    if settlement is None or settlement.get("id") != settlement_id:
        raise RewardError("Settlement is missing; payout is blocked", status=409, code="settlement_missing")
    if not _settlement_intact(settlement):
        raise RewardError("Settlement checksum does not match; payout is blocked", status=409, code="checksum")
    _refresh_settlement_locked(settlement)
    status = reward.get("status")
    if status == "forfeited" or settlement.get("status") == "reversed":
        raise RewardError("This reward was forfeited because the affiliated customer is no longer paying",
                          status=409, code="forfeited")
    if status == "held" or settlement.get("status") == "held":
        exc = RewardError(
            f"This reward is blocked until {settlement.get('release_at')}",
            status=409, code="held",
        )
        exc.release_at = settlement.get("release_at")
        raise exc
    if not _is_paying(str(reward.get("referee_customer_id"))):
        if any(item.get("status") == "dispatched" for item in _rewards_for(reward["referee_customer_id"])):
            raise RewardError("The affiliated customer is no longer paying", status=409, code="balance_lapsed")
        _reverse_settlement_locked(settlement)
        raise RewardError("This reward was forfeited because the affiliated customer is no longer paying",
                          status=409, code="forfeited")


def _dispatch_locked(reward: Dict[str, Any], raw_allocation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if reward.get("status") == "dispatched":
        return reward
    _release_guard(reward)
    if reward.get("status") != "earned":
        raise RewardError(f"Reward is {reward.get('status')}", status=409, code="not_earned")
    if not _reward_intact(reward):
        raise RewardError("Reward checksum does not match; payout is blocked", status=409, code="checksum")
    allocation = _allocation_from_input(reward, raw_allocation)
    parts = allocate_cents(int(reward["amount_cents"]), [allocation[d] for d in DESTINATIONS])
    posted = reward.setdefault("posted", {})
    for dest, cents in zip(DESTINATIONS, parts):
        if cents <= 0 or dest in posted:
            continue
        posted[dest] = _POSTERS[dest](reward, cents)
        _persist_reward(reward)
    reward["allocation"] = allocation
    reward["status"] = "dispatched"
    reward["dispatched_at"] = _now()
    reward.pop("dispatch_error", None)
    _anchor(reward, "referral.reward.dispatched", "CACDISPATCH")
    _persist_reward(reward)
    _sync_stats(reward)
    settlement = SETTLEMENTS.get(str(reward.get("referee_customer_id")))
    if settlement is not None:
        _maybe_settle_locked(settlement)
    return reward


def accept_reward(reward_id: str, customer_id: str,
                  allocation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    with _LOCK:
        _ensure_loaded()
        reward = REWARDS.get(str(reward_id or ""))
        if reward is None or str(reward.get("beneficiary_customer_id")) != str(customer_id):
            raise RewardError("Reward not found", status=404, code="not_found")
        if reward.get("status") == "dispatched":
            raise RewardError("This reward was already accepted", status=409, code="already_dispatched")
        _dispatch_locked(reward, allocation)
        return public_reward(reward)


def accept_all(customer_id: str, allocation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Apply one destination split to every reward this customer has earned.

    Each reward is still checked against its own layer policy, so a cash split
    that layer 3 does not allow fails that reward and leaves the others.
    """
    with _LOCK:
        _ensure_loaded()
        ids = [
            reward["id"] for reward in REWARDS.values()
            if str(reward.get("beneficiary_customer_id")) == str(customer_id)
            and reward.get("status") in ("earned", "held")
        ]
    dispatched = []
    failed = []
    for reward_id in ids:
        try:
            dispatched.append(accept_reward(reward_id, customer_id, allocation))
        except RewardError as exc:
            failed.append({"id": reward_id, "error": str(exc), "code": exc.code})
    return {"dispatched": dispatched, "failed": failed}


# ---------------------------------------------------------------------------
# Professional roles. An agent is a role on one supplier record.
# The inquiry form writes onto this same request. It does not open a second book.
# ---------------------------------------------------------------------------
INQUIRY_DAYS = 14
INQUIRY_SESSION_COOKIE = "phins_inquiry"
INQUIRY_SESSION_SECONDS = 2 * 60 * 60
INQUIRY_OTP_WINDOW_SECONDS = 15 * 60
_INQUIRY_TOKEN_RE = re.compile(r"^inq_[0-9a-f]{32}$")
_INQUIRY_SESSION_RE = re.compile(r"^inqs_[0-9a-f]{32}$")
_CLOSED_SUPPLIER_STATUSES = ("rejected", "suspended", "terminated")
_PIPELINE_AUDIENCES = ("supplier", "agent", "customer", "tax", "regulator")
_INQUIRY_FORBIDDEN = {
    "national_id", "id_number", "national_id_number", "password", "tax_id", "ssn",
}


def _request_id(customer_id: str, role: str) -> str:
    return f"PRO-{customer_id}-{role}"


def _clip_text(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _reject_inquiry_secrets(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    for key in payload:
        if str(key).strip().lower() in _INQUIRY_FORBIDDEN:
            raise RewardError(
                "This form does not collect a personal ID, a tax number, or a password",
                code="field_not_accepted",
            )
    for nested in ("personal", "company"):
        child = payload.get(nested)
        if isinstance(child, dict):
            _reject_inquiry_secrets(child)


def _known_customer(customer_id: str) -> Dict[str, Any]:
    """Details the customer record already holds. The national ID stays in the vault."""
    rec = _mapped_customer(customer_id) or {}
    known = {
        "name": _clip_text(rec.get("name"), 120),
        "email": _clip_text(rec.get("email"), 254),
        "phone": _clip_text(rec.get("phone") or rec.get("mobile"), 40),
        "address": _clip_text(rec.get("address"), 160),
        "city": _clip_text(rec.get("city"), 80),
        "country": _clip_text(rec.get("country"), 80),
    }
    try:
        from services.customer_identity_service import identity_reference
        ref = identity_reference(rec)
    except Exception:
        ref = None
    if isinstance(ref, dict):
        known["nationality"] = ref.get("nationality")
        known["national_id_masked"] = ref.get("national_id_masked")
    return known


def _safe_origin(value: str) -> str:
    """Scheme and host only. A path on the configured origin is not kept.

    ``BASE_URL`` is an origin. Keeping a page path produced a link such as
    ``professional-inquiry-chat.html/?r=`` that a mail client cannot open.
    The query is attached later as ``.html?`` with nothing between them.
    """
    text = str(value or "").strip()
    if not text or any(ch in text for ch in ("\r", "\n", " ")):
        return ""
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    if parts.username or parts.password:
        return ""
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"


_PUBLIC_INQUIRY_ORIGIN = "https://www.phins.ai"
_PUBLIC_INQUIRY_HOSTS = frozenset({"phins.ai", "www.phins.ai"})


def _configured_origin() -> str:
    portal = _portal()
    getter = getattr(portal, "public_portal_base_url", None) if portal else None
    if not callable(getter):
        return ""
    try:
        return _safe_origin(str(getter() or ""))
    except Exception:
        return ""


def _trusted_request_origin(value: str) -> str:
    """The live site, unless the request host is phins.ai or www.phins.ai.

    The inquiry token is emailed. An arbitrary ``Host`` is not an origin:
    a spoofed header must not receive that link. A custom port is not kept.
    """
    origin = _safe_origin(value)
    if origin:
        parts = urlsplit(origin)
        host = str(parts.hostname or "").lower().rstrip(".")
        if host in _PUBLIC_INQUIRY_HOSTS and parts.port in (None, 443):
            return f"https://{host}"
    return _PUBLIC_INQUIRY_ORIGIN


def _inquiry_path(token: str, request_id: str, public_origin: str = "") -> str:
    """Absolute chat link. The token is the query value, never a log line.

    ``r`` is the request id, not a secret. ``t`` stays last. The origin is
    ``BASE_URL``, then ``WEBHOOK_BASE_URL`` (``TEST_BASE_URL`` under test).
    With neither set, the link is ``https://www.phins.ai`` unless the
    request host is exactly ``phins.ai`` or ``www.phins.ai``.
    """
    query = urlencode((("r", str(request_id or "")), ("t", token)))
    page = "/professional-inquiry-chat.html"
    origin = _configured_origin() or _trusted_request_origin(public_origin)
    return f"{origin}{page}?{query}"


def _arm_inquiry(req: Dict[str, Any], supplier_type: str, company_name: str) -> str:
    link_prefix = "inq_"
    token = link_prefix + secrets.token_hex(16)
    known = _known_customer(req["customer_id"])
    linked = _inquiry_email_for(req)
    if linked:
        known["email"] = linked
    has_company = bool(company_name and supplier_type)
    company = None
    if has_company:
        company = {
            "company_name": company_name[:160],
            "supplier_type": supplier_type,
            "registration_number": "",
            "city": known.get("city") or "",
            "country": known.get("country") or "",
            "phone": known.get("phone") or "",
            "address": known.get("address") or "",
            "description": "",
        }
    personal = {
        "name": known.get("name") or "",
        "phone": known.get("phone") or "",
        "address": known.get("address") or "",
        "city": known.get("city") or "",
        "country": known.get("country") or "",
    }
    previous = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    req["inquiry"] = {
        "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "expires_at": _add_days(_now(), INQUIRY_DAYS),
        "sent_at": _now(),
        "email_sent": False,
        "submitted_at": None,
        "has_company": has_company or bool(previous.get("has_company")),
        "personal": personal,
        "company": company if has_company else previous.get("company"),
        "known": known,
    }
    if has_company:
        req["supplier_type"] = supplier_type
        req["company_name"] = company_name[:160]
    return token


def _add_days(stamp: str, days: int) -> str:
    moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    shifted = moment + timedelta(days=int(days))
    return shifted.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _inquiry_expired(inquiry: Dict[str, Any]) -> bool:
    stamp = str(inquiry.get("expires_at") or "")
    if not stamp:
        return True
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        now = datetime.fromisoformat(_now().replace("Z", "+00:00"))
    except ValueError:
        return True
    return now > moment


def public_request(req: Dict[str, Any]) -> Dict[str, Any]:
    """Request fields safe to return. The inquiry token and its hash stay off the wire."""
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    personal = inquiry.get("personal") if isinstance(inquiry.get("personal"), dict) else {}
    company = inquiry.get("company") if inquiry.get("has_company") and isinstance(inquiry.get("company"), dict) else None
    return {
        "id": req.get("id"),
        "customer_id": req.get("customer_id"),
        "requested_role": req.get("requested_role"),
        "status": req.get("status"),
        "supplier_type": req.get("supplier_type"),
        "company_name": req.get("company_name"),
        "note": req.get("note"),
        "agent_id": req.get("agent_id"),
        "supplier_id": req.get("supplier_id"),
        "invitation_code": req.get("invitation_code"),
        "reviewed_by": req.get("reviewed_by"),
        "reviewed_at": req.get("reviewed_at"),
        "review_note": req.get("review_note"),
        "created_at": req.get("created_at"),
        "updated_at": req.get("updated_at"),
        "inquiry_sent": bool(inquiry.get("sent_at")),
        "inquiry_submitted": bool(inquiry.get("submitted_at")),
        "email_sent": bool(inquiry.get("email_sent")),
        "has_company": bool(inquiry.get("has_company")),
        "applicant_name": personal.get("name") or None,
        "company": company,
        "via": req.get("via"),
    }


def _looks_like_email(value: str) -> bool:
    text = str(value or "").strip()
    if not text or " " in text or text.count("@") != 1:
        return False
    local, _, domain = text.partition("@")
    return bool(local and "." in domain)


def _inquiry_recipient(customer_id: str, login_username: str = "") -> Tuple[str, str]:
    """Address and display name for the inquiry email.

    The customer record wins. The login username is used only when that record
    has no email: it is the authenticated account, not an address from the
    request body. Without this, a record that omitted email returned before
    NotificationService.send and the customer received nothing.
    """
    rec = _mapped_customer(customer_id) or {}
    email = str(rec.get("email") or "").strip()
    if not email:
        login = str(login_username or "").strip()
        if _looks_like_email(login):
            email = login
    name = _clip_text(rec.get("name") or "PHINS Customer", 80)
    return email, name


def _inquiry_email_for(req: Dict[str, Any]) -> str:
    """The address already known for this inquiry.

    Same resolution as the inquiry email and the identity code: the customer
    record, or the login stored when the request was opened. A form or chat
    body is never a source, and this does not write the customer master.
    """
    email, _name = _inquiry_recipient(
        str((req or {}).get("customer_id") or ""),
        str((req or {}).get("login_username") or ""),
    )
    return _clip_text(email, 254)


def _send_inquiry_email(customer_id: str, role: str, path: str,
                        login_username: str = "") -> Tuple[bool, str]:
    """Send the chat link through the same NotificationService the chats use for codes.

    ``otp_email`` and ``professional_inquiry_chat`` are templates on that one
    service. Delivery uses ``deliver_notification``, the same fresh-service
    plus configured-provider retry the identity code uses. This does not open
    a second mailer. The raw link stays in the email only; the chat transcript
    does not repeat it.
    """
    email, name = _inquiry_recipient(customer_id, login_username)
    if not email:
        return False, ""
    role_label = "supplier" if str(role or "").strip().lower() == "supplier" else "agent"
    try:
        from services.notification_service import (
            NotificationChannel,
            NotificationPriority,
            NotificationRequest,
            deliver_notification,
        )
        result = deliver_notification(NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient=email,
            template_id="professional_inquiry_chat",
            template_vars={
                "name": name,
                "role": role_label,
                "chat_url": path,
            },
            priority=NotificationPriority.HIGH,
            customer_id=str(customer_id),
            metadata={
                "purpose": "professional_inquiry",
                "template": "professional_inquiry_chat",
                "requested_role": role_label,
            },
        ))
    except Exception:
        logger.warning("professional inquiry email was not handed to the notification service")
        return False, ""
    sent = bool(getattr(result, "success", False))
    if not sent:
        logger.warning(
            "professional inquiry email was not delivered (%s)",
            getattr(result, "error_code", None) or "SEND_FAILED",
        )
    return sent, str(getattr(result, "notification_id", "") or "")


def request_professional(customer_id: str, role: str, login_username: str = "",
                         supplier_type: str = "", company_name: str = "",
                         note: str = "", public_origin: str = "") -> Dict[str, Any]:
    """Open or resend the inquiry. Review waits until the form is submitted."""
    role = str(role or "").strip().lower()
    if role not in ("agent", "supplier"):
        raise RewardError("Role must be agent or supplier")
    customer_id = str(customer_id or "").strip()
    if not customer_id:
        raise RewardError("Customer is required", status=400, code="customer_required")
    supplier_type = str(supplier_type or "").strip().lower()
    company_name = str(company_name or "").strip()
    if company_name or supplier_type:
        if supplier_type not in supplier_type_values():
            raise RewardError("Choose a supplier type such as clinic, pharmacy, or wellness")
        if len(company_name) < 2:
            raise RewardError("A company on the application needs a practice or company name")
    with _LOCK:
        _ensure_loaded()
        key = _request_id(customer_id, role)
        existing = REQUESTS.get(key)
        if existing and existing.get("status") == "approved":
            raise RewardError("This role is already open", status=409, code="already_approved")
        if existing and existing.get("status") == "pending":
            raise RewardError("This request is already waiting for review", status=409, code="already_pending")
        req = {
            "id": key,
            "customer_id": customer_id,
            "login_username": str(login_username or "")[:254],
            "requested_role": role,
            "status": "inquiry",
            "supplier_type": supplier_type or (existing or {}).get("supplier_type"),
            "company_name": (company_name[:160] if company_name else (existing or {}).get("company_name")),
            "note": str(note or (existing or {}).get("note") or "")[:500],
            "agent_id": (existing or {}).get("agent_id"),
            "supplier_id": (existing or {}).get("supplier_id"),
            "invitation_code": (existing or {}).get("invitation_code"),
            "reviewed_by": None,
            "reviewed_at": None,
            "review_note": None,
            "created_at": (existing or {}).get("created_at") or _now(),
            "updated_at": _now(),
            "inquiry": (existing or {}).get("inquiry") if isinstance((existing or {}).get("inquiry"), dict) else {},
        }
        token = _arm_inquiry(req, supplier_type, company_name)
        REQUESTS[key] = req
        _persist_request(req)
        path = _inquiry_path(token, key, public_origin)
    sent, notification_id = _send_inquiry_email(
        customer_id, role, path, login_username,
    )
    with _LOCK:
        current = REQUESTS.get(key) or req
        inquiry = current.setdefault("inquiry", {})
        inquiry["email_sent"] = bool(sent)
        if notification_id:
            inquiry["email_notification_id"] = notification_id
        _seed_chat_notice(current, bool(sent))
        current["updated_at"] = _now()
        _persist_request(current)
        view = public_request(current)
    view["inquiry_path"] = path
    return view


def _digest(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def inquiry_cookie_name(request_id: str) -> str:
    """One HttpOnly cookie per open inquiry. The name is not the secret."""
    suffix = hashlib.sha256(str(request_id or "").encode("utf-8")).hexdigest()[:16]
    return f"{INQUIRY_SESSION_COOKIE}_{suffix}"


def _request_for_browser_session(token: str) -> Optional[Dict[str, Any]]:
    """The short cookie minted from the email link. The raw value is not stored."""
    if not _INQUIRY_SESSION_RE.fullmatch(str(token or "")):
        return None
    digest = _digest(token)
    found = None
    for req in REQUESTS.values():
        inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
        browser = inquiry.get("browser_session") if isinstance(inquiry.get("browser_session"), dict) else {}
        stored = str(browser.get("token_sha256") or "")
        if len(stored) == len(digest) and hmac.compare_digest(stored, digest):
            found = req
            if _inquiry_expired(browser):
                raise RewardError(
                    "This application session has expired. Open the email link again.",
                    status=410,
                    code="inquiry_session_expired",
                )
    return found


def _request_for_inquiry_token(token: str) -> Optional[Dict[str, Any]]:
    raw = str(token or "")
    if _INQUIRY_SESSION_RE.fullmatch(raw):
        return _request_for_browser_session(raw)
    if not _INQUIRY_TOKEN_RE.fullmatch(raw):
        return None
    digest = _digest(raw)
    found = None
    for req in REQUESTS.values():
        inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
        stored = str(inquiry.get("token_sha256") or "")
        if len(stored) == len(digest) and hmac.compare_digest(stored, digest):
            found = req
    return found


def open_inquiry_session(token: str) -> Dict[str, Any]:
    """Exchange the email-link token for a short HttpOnly browser session.

    The email token stays the 14-day capability. Only its SHA-256 is stored,
    and the same is true of the session secret. Each request gets its own
    cookie name, so a second open inquiry does not replace the first. The
    response carries the session secret under ``_inquiry_session`` so the
    HTTP layer can set that cookie and then drop the field.
    """
    raw = str(token or "")
    if not _INQUIRY_TOKEN_RE.fullmatch(raw):
        raise RewardError("This inquiry link is not valid", status=404, code="inquiry_not_found")
    session_prefix = "inqs_"
    session_secret = session_prefix + secrets.token_hex(16)
    with _LOCK:
        _ensure_loaded()
        req = _request_for_inquiry_token(raw)
        if req is None:
            raise RewardError("This inquiry link is not valid", status=404, code="inquiry_not_found")
        inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
        if _inquiry_expired(inquiry):
            raise RewardError("This inquiry link has expired", status=410, code="inquiry_expired")
        link_expiry = str(inquiry.get("expires_at") or "")
        session_expiry = _add_seconds(_now(), INQUIRY_SESSION_SECONDS)
        if link_expiry and session_expiry > link_expiry:
            session_expiry = link_expiry
        inquiry["browser_session"] = {
            "token_sha256": _digest(session_secret),
            "expires_at": session_expiry,
        }
        req["inquiry"] = inquiry
        req["updated_at"] = _now()
        _persist_request(req)
    view = inquiry_prefill(raw)
    view["_inquiry_session"] = session_secret
    return view


def _identity_otp_fresh(req: Dict[str, Any], token: str = "") -> bool:
    """The code is fresh only for the browser session that verified it.

    The email link stays valid after the cookie is minted. A holder of that
    link does not inherit the 15-minute window.
    """
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    otp = inquiry.get("identity_otp") if isinstance(inquiry.get("identity_otp"), dict) else {}
    stamp = str(otp.get("verified_at") or "")
    bound = str(otp.get("session_sha256") or "")
    raw = str(token or "")
    if not stamp or not bound or not _INQUIRY_SESSION_RE.fullmatch(raw):
        return False
    presented = _digest(raw)
    if len(bound) != len(presented) or not hmac.compare_digest(bound, presented):
        return False
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        now = datetime.fromisoformat(_now().replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now - moment).total_seconds() <= INQUIRY_OTP_WINDOW_SECONDS


def inquiry_otp_context(token: str) -> Dict[str, Any]:
    """The address a code may be sent to.

    Same recipient as the inquiry email: the customer record, or the login
    stored when this request was opened, when that login looks like an email.
    The OTP request body cannot supply a different address.
    """
    with _LOCK:
        req = _open_chat_request(token)
        return {
            "request_id": req.get("id"),
            "email": _inquiry_email_for(req),
            "otp_verified": _identity_otp_fresh(req, token),
        }


def remember_identity_otp(token: str, verification_id: str) -> None:
    with _LOCK:
        req = _open_chat_request(token)
        inquiry = req.setdefault("inquiry", {})
        inquiry["identity_otp"] = {
            "verification_id": str(verification_id or ""),
            "verified_at": None,
        }
        req["updated_at"] = _now()
        _persist_request(req)


def confirm_identity_otp(token: str, verification_id: str) -> Dict[str, Any]:
    given = str(verification_id or "")
    with _LOCK:
        req = _open_chat_request(token)
        inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
        otp = inquiry.get("identity_otp") if isinstance(inquiry.get("identity_otp"), dict) else {}
        stored = str(otp.get("verification_id") or "")
        if not stored or not given or len(stored) != len(given) or not hmac.compare_digest(stored, given):
            raise RewardError(
                "That code does not belong to this application",
                code="otp_mismatch",
            )
        raw = str(token or "")
        if not _INQUIRY_SESSION_RE.fullmatch(raw):
            raise RewardError(
                "Verify the code in the browser that opened this application",
                status=403,
                code="otp_session_required",
            )
        presented = _digest(raw)
        browser = inquiry.get("browser_session") if isinstance(inquiry.get("browser_session"), dict) else {}
        session_digest = str(browser.get("token_sha256") or "")
        if not session_digest or len(session_digest) != len(presented) or not hmac.compare_digest(session_digest, presented):
            raise RewardError(
                "Verify the code in the browser that opened this application",
                status=403,
                code="otp_session_required",
            )
        otp["verified_at"] = _now()
        otp["session_sha256"] = presented
        inquiry["identity_otp"] = otp
        req["inquiry"] = inquiry
        chat = _ensure_chat(req)
        _say(chat, "bot", "Code verified. You can record your identity.")
        req["updated_at"] = otp["verified_at"]
        _persist_request(req)
        return {"otp_verified": True, "chat": _public_chat(req, token)}


def _add_seconds(stamp: str, seconds: int) -> str:
    moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    shifted = moment + timedelta(seconds=int(seconds))
    return shifted.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _inquiry_status_only(req: Dict[str, Any]) -> Dict[str, Any]:
    """A filed link may say where the request stands. It does not repeat contact details."""
    return {
        "request_id": req.get("id"),
        "role": req.get("requested_role"),
        "status": req.get("status"),
        "editable": False,
    }


def inquiry_prefill(token: str) -> Dict[str, Any]:
    """Form payload for the person who holds the email link. No national ID number.

    Once the request leaves ``inquiry``, the link returns status only. The
    14-day expiry applies in every status, so a filed link also stops answering
    after ``INQUIRY_DAYS``.
    """
    with _LOCK:
        _ensure_loaded()
        req = _request_for_inquiry_token(token)
        if req is None:
            raise RewardError("This inquiry link is not valid", status=404, code="inquiry_not_found")
        inquiry = req.get("inquiry") or {}
        if _inquiry_expired(inquiry):
            raise RewardError("This inquiry link has expired", status=410, code="inquiry_expired")
        if req.get("status") != "inquiry":
            return _inquiry_status_only(req)
        stored_known = inquiry.get("known") if isinstance(inquiry.get("known"), dict) else _known_customer(req["customer_id"])
        known = dict(stored_known)
        linked = _inquiry_email_for(req)
        if linked:
            known["email"] = linked
        personal = inquiry.get("personal") if isinstance(inquiry.get("personal"), dict) else {}
        company = inquiry.get("company") if isinstance(inquiry.get("company"), dict) else {}
        return {
            "request_id": req["id"],
            "role": req.get("requested_role"),
            "status": req.get("status"),
            "editable": req.get("status") == "inquiry",
            "agent_is_supplier": True,
            "known": {
                "name": known.get("name") or "",
                "email": known.get("email") or "",
                "phone": known.get("phone") or "",
                "address": known.get("address") or "",
                "city": known.get("city") or "",
                "country": known.get("country") or "",
                "nationality": known.get("nationality"),
                "national_id_masked": known.get("national_id_masked"),
            },
            "personal": {
                "name": personal.get("name") or known.get("name") or "",
                "phone": personal.get("phone") or known.get("phone") or "",
                "address": personal.get("address") or known.get("address") or "",
                "city": personal.get("city") or known.get("city") or "",
                "country": personal.get("country") or known.get("country") or "",
            },
            "has_company": bool(inquiry.get("has_company")),
            "company": {
                "company_name": company.get("company_name") or req.get("company_name") or "",
                "supplier_type": company.get("supplier_type") or req.get("supplier_type") or "",
                "registration_number": company.get("registration_number") or "",
                "city": company.get("city") or "",
                "country": company.get("country") or "",
                "phone": company.get("phone") or "",
                "address": company.get("address") or "",
                "description": company.get("description") or "",
            },
            "supplier_types": supplier_type_values(),
            "process": [dict(item) for item in INQUIRY_PROCESS],
            "chat": _public_chat(req, token),
            "agent": "Phin",
        }


def _clean_personal(personal_in: Dict[str, Any]) -> Dict[str, str]:
    personal = {
        "name": _clip_text(personal_in.get("name"), 120),
        "phone": _clip_text(personal_in.get("phone"), 40),
        "address": _clip_text(personal_in.get("address"), 160),
        "city": _clip_text(personal_in.get("city"), 80),
        "country": _clip_text(personal_in.get("country"), 80),
    }
    if len(personal["name"]) < 2:
        raise RewardError("Enter the name for this application")
    return personal


def _clean_company(company_in: Dict[str, Any]) -> Dict[str, str]:
    supplier_type = _clip_text(company_in.get("supplier_type"), 40).lower()
    company_name = _clip_text(company_in.get("company_name"), 160)
    if supplier_type not in supplier_type_values():
        raise RewardError("Choose a supplier type such as clinic, pharmacy, or wellness")
    if len(company_name) < 2:
        raise RewardError("A company on the application needs a practice or company name")
    return {
        "company_name": company_name,
        "supplier_type": supplier_type,
        "registration_number": _clip_text(company_in.get("registration_number"), 80),
        "city": _clip_text(company_in.get("city"), 80),
        "country": _clip_text(company_in.get("country"), 80),
        "phone": _clip_text(company_in.get("phone"), 40),
        "address": _clip_text(company_in.get("address"), 160),
        "description": _clip_text(company_in.get("description"), 500),
    }


def submit_inquiry(token: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Write the form onto the same request and hand it to review."""
    _reject_inquiry_secrets(body or {})
    body = body if isinstance(body, dict) else {}
    personal_in = body.get("personal") if isinstance(body.get("personal"), dict) else {}
    has_company = body.get("has_company") in (True, "true", "yes", 1, "1")
    company_in = body.get("company") if isinstance(body.get("company"), dict) else {}
    with _LOCK:
        _ensure_loaded()
        req = _request_for_inquiry_token(token)
        if req is None:
            raise RewardError("This inquiry link is not valid", status=404, code="inquiry_not_found")
        if req.get("status") == "pending":
            raise RewardError("This form was already submitted", status=409, code="inquiry_submitted")
        if req.get("status") == "approved":
            raise RewardError("This role is already open", status=409, code="already_approved")
        if req.get("status") != "inquiry":
            raise RewardError(f"Request is already {req.get('status')}", status=409, code="not_inquiry")
        inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
        if _inquiry_expired(inquiry):
            raise RewardError("This inquiry link has expired", status=410, code="inquiry_expired")
        personal = _clean_personal(personal_in)
        company = _clean_company(company_in) if has_company else None
        _assert_identity_ready(req)
        inquiry["personal"] = personal
        inquiry["has_company"] = has_company
        inquiry["company"] = company
        inquiry["submitted_at"] = _now()
        req["inquiry"] = inquiry
        req["updated_at"] = inquiry["submitted_at"]
        if has_company and company:
            req["company_name"] = company["company_name"]
            req["supplier_type"] = company["supplier_type"]
        else:
            req["company_name"] = None
            req["supplier_type"] = None
            inquiry["company"] = None
        # Stay on inquiry until the desk row exists. A staging error must
        # leave the form resubmittable instead of a pending request with no row.
        try:
            _stage_staff_application(req)
        except RewardError:
            req["status"] = "inquiry"
            raise
        except Exception as exc:
            req["status"] = "inquiry"
            raise RewardError(
                "The application could not be filed for staff review",
                status=503,
                code="application_not_staged",
            ) from exc
        req["status"] = "pending"
        req["updated_at"] = inquiry["submitted_at"]
        _link_staged_request(req)
        _persist_request(req)
        return public_request(req)


# The professional application is one disclosed chat. The steps are fixed.
# Phin does not invent a step, and nothing is filed until review is submitted.
INQUIRY_PROCESS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "confirm_person",
        "title": "Confirm your details",
        "optional": False,
        "detail": (
            "Name, phone, and address already on your customer record. "
            "You can correct them on this application. The customer master is not rewritten."
        ),
    },
    {
        "id": "identity",
        "title": "Identity",
        "optional": False,
        "detail": (
            "Nationality and personal ID. The number is stored only in the identity vault. "
            "This application keeps nationality and the last four digits. "
            "When an identity is already on file, you confirm it instead of typing it again. "
            "The number is required when the platform requires identity and none is on file."
        ),
    },
    {
        "id": "company",
        "title": "Company or practice",
        "optional": True,
        "detail": (
            "Say yes to add a company. That opens the company name, type, registration, and address. "
            "Say no to apply in your own name. An agent is still one supplier record."
        ),
    },
    {
        "id": "evidence",
        "title": "Documents, voice, or video",
        "optional": True,
        "detail": (
            "You may attach a document, a voice note, or a short video. "
            "Each file is sealed by SHA-256 and filed on this application. You can skip this step."
        ),
    },
    {
        "id": "review",
        "title": "Review and submit",
        "optional": False,
        "detail": (
            "You see the full application before it is filed. "
            "Filing uses this one request. Staff review it on Supplier Management."
        ),
    },
)
_INQUIRY_STEP_IDS = tuple(item["id"] for item in INQUIRY_PROCESS)
_INQUIRY_MEDIA_KINDS = ("voice", "video", "document", "image")
_INQUIRY_MEDIA_LIMIT = 3
_INQUIRY_MEDIA_BYTES = 4 * 1024 * 1024
_INQUIRY_OPENING = (
    "I'm Phin. This application has five steps, and all five are shown before you submit: "
    "your details, identity, a company only if you add one, optional documents or a voice note "
    "or a short video, then a review. An agent is a role on one supplier record. "
    "Nothing is filed until you submit."
)


def _identity_public(req: Dict[str, Any]) -> Dict[str, Any]:
    rec = _mapped_customer(req.get("customer_id")) or {}
    try:
        from services.customer_identity_service import identity_reference, is_complete, strict_mode
        ref = identity_reference(rec) or {}
        complete = bool(is_complete(rec))
        required = bool(strict_mode() and not complete)
    except Exception:
        ref, complete, required = {}, False, False
    return {
        "required": required,
        "complete": complete,
        "nationality": ref.get("nationality"),
        "national_id_masked": ref.get("national_id_masked"),
    }


def _step_prompt(step_id: str, req: Dict[str, Any], identity: Dict[str, Any]) -> str:
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    personal = inquiry.get("personal") if isinstance(inquiry.get("personal"), dict) else {}
    if step_id == "confirm_person":
        name = personal.get("name") or "there"
        address = _inquiry_email_for(req)
        linked = (
            f" Your email {address} is already linked to this application. You do not type it again."
            if address else ""
        )
        return (
            f"{name}, confirm the name, phone, and address for this application. "
            "They are already filled from your customer record. Correct anything that changed."
            + linked
        )
    if step_id == "identity":
        address = _inquiry_email_for(req) or "the email already linked to this application"
        if identity.get("complete"):
            masked = identity.get("national_id_masked") or "on file"
            nation = identity.get("nationality") or "your nationality"
            return (
                f"Your identity is already on file ({nation}, {masked}). "
                "Confirm it is yours. The number is not shown again and is not copied onto this application."
            )
        if identity.get("required"):
            return (
                "This application needs your nationality and personal ID before it can continue. "
                f"First enter the code sent to {address}. "
                "The number goes to the identity vault only. This application keeps the last four digits."
            )
        return (
            "Add your nationality and personal ID, or skip this step. "
            f"Recording a new ID needs the code sent to {address}. "
            "When the platform requires an identity and none is on file, this step cannot be skipped. "
            "The number goes to the identity vault only."
        )
    if step_id == "company":
        return (
            "Are you applying with a company or practice? "
            "Yes opens the company name, type, and registration. No keeps the application in your own name."
        )
    if step_id == "evidence":
        return (
            "You can add a document, a voice note, or a short video. "
            "Each file is sealed with SHA-256. This step is optional — skip it, or continue when you are done."
        )
    company = inquiry.get("company") if isinstance(inquiry.get("company"), dict) else {}
    chat = inquiry.get("chat") if isinstance(inquiry.get("chat"), dict) else {}
    media_count = len(chat.get("media") or [])
    who = personal.get("name") or "You"
    practice = company.get("company_name") if inquiry.get("has_company") else "in your own name"
    ident = identity.get("national_id_masked") or ("not confirmed" if not identity.get("complete") else "on file")
    return (
        f"Review before filing. {who}. Practice: {practice}. Identity: {ident}. "
        f"Files sealed on this application: {media_count}. "
        "Submit files this one request for staff review. Nothing else is created."
    )


def _step_input(step_id: str, req: Dict[str, Any], identity: Dict[str, Any], presented: str = "") -> Dict[str, Any]:
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    if step_id == "confirm_person":
        personal = inquiry.get("personal") if isinstance(inquiry.get("personal"), dict) else {}
        return {"type": "person", "prefill": personal, "email": _inquiry_email_for(req)}
    if step_id == "identity":
        return {
            "type": "identity",
            "can_skip": not identity.get("complete") and not identity.get("required"),
            "can_confirm": bool(identity.get("complete")),
            "nationality": identity.get("nationality"),
            "national_id_masked": identity.get("national_id_masked"),
            "otp_verified": _identity_otp_fresh(req, presented),
            "email": _inquiry_email_for(req),
        }
    if step_id == "company":
        company = inquiry.get("company") if isinstance(inquiry.get("company"), dict) else {}
        return {
            "type": "company",
            "supplier_types": supplier_type_values(),
            "prefill": company,
        }
    if step_id == "evidence":
        return {"type": "media", "kinds": list(_INQUIRY_MEDIA_KINDS), "optional": True}
    return {"type": "confirm", "options": ["submit"]}


def _blank_chat() -> Dict[str, Any]:
    return {
        "version": 1,
        "cursor": "confirm_person",
        "media": [],
        "transcript": [],
        "identity_confirmed": False,
        "identity_deferred": False,
    }


def _ensure_chat(req: Dict[str, Any]) -> Dict[str, Any]:
    inquiry = req.setdefault("inquiry", {})
    chat = inquiry.get("chat")
    if not isinstance(chat, dict):
        chat = _blank_chat()
        inquiry["chat"] = chat
    chat.setdefault("media", [])
    chat.setdefault("transcript", [])
    chat.setdefault("cursor", "confirm_person")
    return chat


def _say(chat: Dict[str, Any], role: str, text: str) -> None:
    chat.setdefault("transcript", []).append({"role": role, "text": _clip_text(text, 500)})
    chat["transcript"] = chat["transcript"][-40:]


_INQUIRY_EMAIL_UNSENT = (
    "This chat is open. The email could not be sent, so continue here."
)


def _inquiry_mail_line(req: Dict[str, Any], email_sent: bool) -> str:
    """Name the linked address in the chat. The link token stays out of the line."""
    if not email_sent:
        return _INQUIRY_EMAIL_UNSENT
    email = _inquiry_email_for(req)
    target = email or "the email on your customer record"
    return (
        f"I sent this chat to {target}. "
        "That address is already on this application, so you do not type it again. "
        "Open that message to come back to this application. "
        "A code for a new identity goes to that same email."
    )


def _seed_chat_notice(req: Dict[str, Any], email_sent: bool) -> None:
    """Open the disclosed chat with the email result. The link token stays out.

    A later successful send still records itself when an earlier attempt left
    only the failure line. The token is not written into either line.
    """
    chat = _ensure_chat(req)
    line = _inquiry_mail_line(req, email_sent)
    texts = [
        str(item.get("text") or "")
        for item in (chat.get("transcript") or [])
        if isinstance(item, dict)
    ]
    if texts:
        if email_sent and line not in texts:
            _say(chat, "bot", line)
        return
    _say(chat, "bot", _INQUIRY_OPENING)
    _say(chat, "bot", line)
    _say(chat, "bot", _step_prompt("confirm_person", req, _identity_public(req)))


def note_inquiry_delivery(token: str, text: str) -> Dict[str, Any]:
    """Record a notification in the disclosed chat. The text must not carry a secret."""
    with _LOCK:
        req = _open_chat_request(token)
        chat = _ensure_chat(req)
        _say(chat, "bot", text)
        req["updated_at"] = _now()
        _persist_request(req)
        return _chat_payload(req, token)


def _public_media(chat: Dict[str, Any]) -> List[Dict[str, Any]]:
    shown = []
    for item in chat.get("media") or []:
        if not isinstance(item, dict):
            continue
        shown.append({
            "id": item.get("id"),
            "kind": item.get("kind"),
            "name": item.get("name"),
            "sha256": item.get("sha256"),
            "size": item.get("size"),
            "document_id": item.get("document_id"),
        })
    return shown


def _public_chat(req: Dict[str, Any], presented: str = "") -> Dict[str, Any]:
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    chat = inquiry.get("chat") if isinstance(inquiry.get("chat"), dict) else _blank_chat()
    cursor = "filed" if req.get("status") != "inquiry" else str(chat.get("cursor") or "confirm_person")
    identity = _identity_public(req)
    step = None
    if cursor in _INQUIRY_STEP_IDS:
        step = {
            "id": cursor,
            "prompt": _step_prompt(cursor, req, identity),
            "input": _step_input(cursor, req, identity, presented),
        }
    messages = [dict(item) for item in (chat.get("transcript") or []) if isinstance(item, dict)]
    if not messages and step:
        messages = [
            {"role": "bot", "text": _INQUIRY_OPENING},
            {"role": "bot", "text": step["prompt"]},
        ]
    email = _inquiry_email_for(req)
    return {
        "agent": "Phin",
        "disclosed": True,
        "email": email,
        "process": [dict(item) for item in INQUIRY_PROCESS],
        "cursor": cursor,
        "step": step,
        "messages": messages,
        "media": _public_media(chat),
        "identity": identity,
        "editable": req.get("status") == "inquiry",
        "notification": {
            "template": "professional_inquiry_chat",
            "sent": bool(inquiry.get("email_sent")),
            "notification_id": inquiry.get("email_notification_id") or None,
        },
    }


def _chat_payload(req: Dict[str, Any], presented: str = "") -> Dict[str, Any]:
    return {
        "request_id": req.get("id"),
        "role": req.get("requested_role"),
        "status": req.get("status"),
        "agent_is_supplier": True,
        "agent": "Phin",
        "chat": _public_chat(req, presented),
    }


def _open_chat_request(token: str) -> Dict[str, Any]:
    _ensure_loaded()
    req = _request_for_inquiry_token(token)
    if req is None:
        raise RewardError("This inquiry link is not valid", status=404, code="inquiry_not_found")
    if req.get("status") == "pending":
        raise RewardError("This application was already submitted", status=409, code="inquiry_submitted")
    if req.get("status") != "inquiry":
        raise RewardError(f"Request is already {req.get('status')}", status=409, code="not_inquiry")
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    if _inquiry_expired(inquiry):
        raise RewardError("This inquiry link has expired", status=410, code="inquiry_expired")
    req["inquiry"] = inquiry
    return req


def _next_cursor(step_id: str) -> str:
    index = _INQUIRY_STEP_IDS.index(step_id)
    if index + 1 >= len(_INQUIRY_STEP_IDS):
        return "filed"
    return _INQUIRY_STEP_IDS[index + 1]


def _body_from_inquiry(req: Dict[str, Any]) -> Dict[str, Any]:
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    body = {
        "personal": dict(inquiry.get("personal") or {}),
        "has_company": bool(inquiry.get("has_company")),
    }
    if body["has_company"] and isinstance(inquiry.get("company"), dict):
        body["company"] = dict(inquiry["company"])
    return body


def _assert_identity_ready(req: Dict[str, Any]) -> None:
    identity = _identity_public(req)
    if identity.get("complete"):
        return
    try:
        from services.customer_identity_service import strict_mode
        required = bool(strict_mode())
    except Exception:
        required = False
    if required:
        raise RewardError(
            "Identity is required before this application can be filed",
            code="identity_required",
        )


def _advance_saved(req: Dict[str, Any], chat: Dict[str, Any], step_id: str, user_text: str, bot_text: str,
                   presented: str = "") -> Dict[str, Any]:
    _say(chat, "user", user_text)
    if bot_text:
        _say(chat, "bot", bot_text)
    chat["cursor"] = _next_cursor(step_id)
    if chat["cursor"] in _INQUIRY_STEP_IDS:
        identity = _identity_public(req)
        _say(chat, "bot", _step_prompt(chat["cursor"], req, identity))
    req["updated_at"] = _now()
    _persist_request(req)
    return _chat_payload(req, presented)


def _identity_write_stores():
    """The same customer store the other Phin chats write identity through.

    In database mode ``CUSTOMERS`` is a ``DatabaseDict``, not a ``dict``.
    Treating that as a missing vault stopped "Record my identity" after the
    code had already been verified. A form body is not a store.
    """
    portal = _portal()
    customers = getattr(portal, "CUSTOMERS", None) if portal else None
    if customers is None or not hasattr(customers, "__getitem__") or not hasattr(customers, "__setitem__"):
        raise RewardError("Identity vault is unavailable", status=503, code="identity_vault_unavailable")
    mirrors = []
    registered = getattr(portal, "REGISTERED_CUSTOMERS", None) if portal else None
    if isinstance(registered, dict) and registered is not customers:
        mirrors.append(registered)
    return (
        customers,
        tuple(mirrors),
        getattr(portal, "audit", None) if portal else None,
        getattr(portal, "platform_event_ledger", None) if portal else None,
    )


def _advance_identity(token: str, value: Any) -> Dict[str, Any]:
    action = ""
    provided: Dict[str, Any] = {}
    if isinstance(value, str):
        action = value.strip().lower()
    elif isinstance(value, dict):
        action = str(value.get("action") or "").strip().lower()
        if value.get("national_id"):
            action = "provide"
            provided = value
    if action not in ("confirm", "skip", "provide"):
        raise RewardError("Confirm your identity, skip it, or provide nationality and a personal ID")
    with _LOCK:
        req = _open_chat_request(token)
        chat = _ensure_chat(req)
        if chat.get("cursor") != "identity":
            raise RewardError("Finish the step that is open", status=409, code="step_mismatch")
        customer_id = str(req.get("customer_id") or "")
        identity = _identity_public(req)
    deferred = False
    if action == "confirm":
        if not identity.get("complete"):
            raise RewardError("There is no identity on file to confirm", code="identity_required")
        note = "Identity confirmed from the record already on file. The number stays in the vault."
    elif action == "skip":
        if identity.get("complete"):
            raise RewardError("Confirm the identity already on file", code="identity_required")
        if identity.get("required"):
            raise RewardError(
                "Identity is required before this application can continue",
                code="identity_required",
            )
        deferred = True
        note = "Identity was not confirmed on this application."
    else:
        nationality = provided.get("nationality")
        national_id = provided.get("national_id")
        for key in provided:
            if str(key).strip().lower() in _INQUIRY_FORBIDDEN and str(key).strip().lower() != "national_id":
                raise RewardError(
                    "This application does not collect a tax number or a password",
                    code="field_not_accepted",
                )
        with _LOCK:
            gate = _open_chat_request(token)
            if _ensure_chat(gate).get("cursor") != "identity":
                raise RewardError("Finish the step that is open", status=409, code="step_mismatch")
            if not _identity_otp_fresh(gate, token):
                raise RewardError(
                    "Verify the code sent to your email before recording an identity",
                    status=403,
                    code="otp_required",
                )
        try:
            from services.customer_identity_service import set_identity
            customers, mirrors, audit, ledger = _identity_write_stores()
            set_identity(
                customers, customer_id, national_id, nationality,
                source="chat", actor="professional_inquiry",
                mirrors=mirrors, audit=audit, ledger=ledger,
            )
        except RewardError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None) or "identity_rejected"
            status = getattr(exc, "status", None) or 400
            raise RewardError(str(exc), status=int(status), code=str(code))
        finally:
            if isinstance(provided, dict):
                provided.pop("national_id", None)
        note = "Identity recorded. This application keeps nationality and the last four digits only."
    with _LOCK:
        req = _open_chat_request(token)
        chat = _ensure_chat(req)
        if chat.get("cursor") != "identity":
            raise RewardError("Finish the step that is open", status=409, code="step_mismatch")
        known = _known_customer(customer_id)
        linked = _inquiry_email_for(req)
        if linked:
            known["email"] = linked
        req["inquiry"]["known"] = known
        chat["identity_confirmed"] = not deferred
        chat["identity_deferred"] = deferred
        if not deferred:
            otp = req["inquiry"].get("identity_otp") if isinstance(req["inquiry"].get("identity_otp"), dict) else {}
            otp["verified_at"] = None
            otp["session_sha256"] = None
            req["inquiry"]["identity_otp"] = otp
        if not chat.get("transcript"):
            _say(chat, "bot", _INQUIRY_OPENING)
        return _advance_saved(req, chat, "identity", "Identity step completed", note, token)


def advance_inquiry_chat(token: str, step: str, value: Any) -> Dict[str, Any]:
    """Move one disclosed step. The personal ID never lands on the request."""
    step = str(step or "").strip()
    if step not in _INQUIRY_STEP_IDS:
        raise RewardError("That step is not part of this application", code="step_unknown")
    if step == "identity":
        return _advance_identity(token, value)
    filing_body = None
    with _LOCK:
        req = _open_chat_request(token)
        chat = _ensure_chat(req)
        if chat.get("cursor") != step:
            raise RewardError("Finish the step that is open", status=409, code="step_mismatch")
        if not chat.get("transcript"):
            _say(chat, "bot", _INQUIRY_OPENING)
        if step == "confirm_person":
            incoming = value if isinstance(value, dict) else {}
            _reject_inquiry_secrets(incoming)
            personal_in = incoming.get("personal") if isinstance(incoming.get("personal"), dict) else incoming
            personal = _clean_personal(personal_in)
            req["inquiry"]["personal"] = personal
            saved = _advance_saved(req, chat, step, personal["name"], "", token)
        elif step == "company":
            has_company = True
            if isinstance(value, str) and value.strip().lower() in ("no", "skip"):
                has_company = False
            elif isinstance(value, dict) and str(value.get("has_company")).strip().lower() in ("false", "no", "0"):
                has_company = False
            elif not isinstance(value, dict):
                raise RewardError("Say no, or send the company name and type")
            _reject_inquiry_secrets(value if isinstance(value, dict) else {})
            if has_company:
                company_in = value.get("company") if isinstance(value.get("company"), dict) else value
                company = _clean_company(company_in)
                req["inquiry"]["has_company"] = True
                req["inquiry"]["company"] = company
                req["company_name"] = company["company_name"]
                req["supplier_type"] = company["supplier_type"]
                user_text = company["company_name"]
            else:
                req["inquiry"]["has_company"] = False
                req["inquiry"]["company"] = None
                req["company_name"] = None
                req["supplier_type"] = None
                user_text = "No company"
            saved = _advance_saved(req, chat, step, user_text, "", token)
        elif step == "evidence":
            choice = str(value or "").strip().lower()
            if isinstance(value, dict):
                choice = str(value.get("action") or "").strip().lower()
            if choice not in ("skip", "done"):
                raise RewardError("Choose skip or done")
            count = len(chat.get("media") or [])
            user_text = "Skip evidence" if choice == "skip" else f"Continue with {count} file(s)"
            saved = _advance_saved(req, chat, step, user_text, "", token)
        else:
            if str(value or "").strip().lower() not in ("submit",):
                if not (isinstance(value, dict) and str(value.get("action") or "").lower() == "submit"):
                    raise RewardError("Confirm with submit")
            _assert_identity_ready(req)
            filing_body = _body_from_inquiry(req)
            saved = None
    if filing_body is None:
        return saved
    filed = submit_inquiry(token, filing_body)
    with _LOCK:
        req = _request_for_inquiry_token(token)
        if req is None:
            return {"request": filed, "agent": "Phin"}
        chat = _ensure_chat(req)
        chat["cursor"] = "filed"
        _say(chat, "user", "Submit this application")
        _say(chat, "bot", "Filed. This one request is waiting for review on Supplier Management.")
        req["updated_at"] = _now()
        _persist_request(req)
        payload = _chat_payload(req, token)
    payload["request"] = filed
    return payload


def _safe_media_name(kind: str, name: str) -> str:
    defaults = {
        "voice": "voice-note.webm",
        "video": "video-note.webm",
        "document": "document.txt",
        "image": "image.png",
    }
    raw = re.sub(r"[^A-Za-z0-9._-]", "", str(name or "").replace("\\", "/").split("/")[-1])[:80]
    if "." not in raw:
        return defaults[kind]
    ext = "." + raw.rsplit(".", 1)[-1].lower()
    try:
        from services.document_processing_service import ALLOWED_EXTENSIONS
        allowed = ALLOWED_EXTENSIONS
    except Exception:
        allowed = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".webm", ".mp4", ".wav", ".mp3"}
    if ext not in allowed:
        return defaults[kind]
    return raw


def attach_inquiry_media(token: str, kind: str, name: str, mime_type: str,
                         data_b64: str) -> Dict[str, Any]:
    """Seal an optional voice note, video, or document onto the same request."""
    kind = str(kind or "").strip().lower()
    if kind not in _INQUIRY_MEDIA_KINDS:
        raise RewardError("Attachment kind must be voice, video, document, or image")
    raw_b64 = str(data_b64 or "")
    if "," in raw_b64 and raw_b64.strip().lower().startswith("data:"):
        raw_b64 = raw_b64.split(",", 1)[1]
    try:
        blob = base64.b64decode(raw_b64, validate=True)
    except Exception:
        raise RewardError("The attachment is not valid base64")
    if not blob:
        raise RewardError("The attachment is empty")
    if len(blob) > _INQUIRY_MEDIA_BYTES:
        raise RewardError("Attachment exceeds 4MB")
    file_name = _safe_media_name(kind, name)
    digest = hashlib.sha256(blob).hexdigest()
    with _LOCK:
        req = _open_chat_request(token)
        chat = _ensure_chat(req)
        if chat.get("cursor") != "evidence":
            raise RewardError(
                "Documents, voice, and video are accepted on that step",
                status=409, code="media_not_open",
            )
        if len(chat.get("media") or []) >= _INQUIRY_MEDIA_LIMIT:
            raise RewardError(f"Maximum {_INQUIRY_MEDIA_LIMIT} attachments")
        customer_id = str(req.get("customer_id") or "")
        request_id = str(req.get("id") or "")
    try:
        from services.document_processing_service import get_document_service
        stored = get_document_service().upload_document(
            file_name=file_name,
            file_data_b64=base64.b64encode(blob).decode("ascii"),
            mime_type=str(mime_type or "")[:120] or None,
            category="professional_inquiry",
            description="Professional application evidence",
            entity_type="professional_request",
            entity_id=request_id,
            customer_id=customer_id,
            uploaded_by=customer_id,
            uploaded_by_role="customer",
            skip_processing=True,
        )
    except ValueError as exc:
        raise RewardError(str(exc))
    except RewardError:
        raise
    except Exception:
        raise RewardError(
            "The attachment could not be sealed",
            status=503, code="media_not_stored",
        )
    item = {
        "id": "INQMED-" + secrets.token_hex(4).upper(),
        "kind": kind,
        "name": file_name,
        "mime_type": str(getattr(stored, "mime_type", "") or mime_type or "")[:120],
        "size": len(blob),
        "sha256": digest,
        "document_id": getattr(stored, "document_id", None),
        "uploaded_at": _now(),
    }
    if item["sha256"] != getattr(stored, "sha256", item["sha256"]):
        raise RewardError("The attachment checksum did not match", status=503, code="media_not_stored")
    label = {"voice": "voice note", "video": "video", "document": "document", "image": "image"}[kind]
    with _LOCK:
        req = _open_chat_request(token)
        chat = _ensure_chat(req)
        if chat.get("cursor") != "evidence":
            raise RewardError(
                "Documents, voice, and video are accepted on that step",
                status=409, code="media_not_open",
            )
        chat.setdefault("media", []).append(item)
        if not chat.get("transcript"):
            _say(chat, "bot", _INQUIRY_OPENING)
        _say(chat, "user", f"Sent a {label}: {file_name}")
        _say(chat, "bot", f"Sealed that {label}. Fingerprint {digest[:12]}. You can add another or continue.")
        req["updated_at"] = _now()
        _persist_request(req)
        payload = _chat_payload(req, token)
    payload["media"] = {key: item[key] for key in ("id", "kind", "name", "sha256", "size", "document_id")}
    return payload


def _supply():
    portal = _portal()
    service = getattr(portal, "supply_chain_service", None) if portal else None
    if service is None:
        raise RewardError("Supplier service is unavailable", status=503, code="supplier_unavailable")
    return service


def _find_supplier(customer_id: str) -> Optional[Dict[str, Any]]:
    service = _supply()
    suppliers = getattr(service, "suppliers", {}) or {}
    rec = _customer_record(customer_id) or {}
    sid = str(rec.get("supplier_id") or "")
    if sid and isinstance(suppliers.get(sid), dict):
        return suppliers[sid]
    for item in REQUESTS.values():
        if str(item.get("customer_id")) != str(customer_id):
            continue
        existing = str(item.get("supplier_id") or "")
        if existing and isinstance(suppliers.get(existing), dict):
            return suppliers[existing]
    for sup in suppliers.values():
        if isinstance(sup, dict) and str(sup.get("customer_id") or "") == str(customer_id):
            return sup
    return None


def _company_from_request(req: Dict[str, Any]) -> Tuple[str, str, bool]:
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    company = inquiry.get("company") if isinstance(inquiry.get("company"), dict) else {}
    personal = inquiry.get("personal") if isinstance(inquiry.get("personal"), dict) else {}
    rec = _customer_record(req["customer_id"]) or {}
    declined = inquiry.get("has_company") is False
    if not declined and (inquiry.get("has_company") or (req.get("company_name") and req.get("supplier_type"))):
        name = _clip_text(company.get("company_name") or req.get("company_name"), 160)
        stype = _clip_text(company.get("supplier_type") or req.get("supplier_type"), 40).lower()
        if name and stype in supplier_type_values():
            return name, stype, True
    placeholder = _clip_text(personal.get("name") or rec.get("name") or "PHINS Professional", 160)
    return placeholder or "PHINS Professional", "other", False


def _stamp_supplier_details(supplier: Dict[str, Any], req: Dict[str, Any],
                            name: str, stype: str, from_company: bool) -> None:
    conflict = False
    source = str(supplier.get("company_name_source") or "")
    current = str(supplier.get("company_name") or "").strip()
    if name:
        if not current or source == "placeholder":
            supplier["company_name"] = name
            supplier["company_name_source"] = "inquiry" if from_company else "placeholder"
        elif current != name:
            conflict = True
    current_type = str(supplier.get("supplier_type") or "").strip()
    if stype and from_company:
        if not current_type or (current_type == "other" and stype != "other"):
            supplier["supplier_type"] = stype
        elif current_type != stype:
            conflict = True
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    company = inquiry.get("company") if isinstance(inquiry.get("company"), dict) else {}
    personal = inquiry.get("personal") if isinstance(inquiry.get("personal"), dict) else {}

    def fill(field: str, value: Any) -> None:
        nonlocal conflict
        text = _clip_text(value, 160)
        if not text:
            return
        current_value = str(supplier.get(field) or "").strip()
        if not current_value:
            supplier[field] = text
        elif current_value != text:
            conflict = True

    if from_company:
        fill("business_registration_number", company.get("registration_number"))
        fill("city", company.get("city") or personal.get("city"))
        fill("country", company.get("country") or personal.get("country"))
        fill("contact_phone", company.get("phone") or personal.get("phone"))
        fill("description", company.get("description"))
        fill("address", company.get("address") or personal.get("address"))
    else:
        fill("contact_phone", personal.get("phone"))
        fill("city", personal.get("city"))
        fill("country", personal.get("country"))
        fill("address", personal.get("address"))
    fill("contact_name", personal.get("name"))
    rec = _customer_record(req["customer_id"]) or {}
    email = _clip_text(rec.get("email"), 254).lower()
    supplier_email = str(supplier.get("contact_email") or "").strip().lower()
    if email and supplier_email and supplier_email != email:
        conflict = True
    elif email and not supplier_email:
        supplier["contact_email"] = email
    supplier["customer_id"] = req["customer_id"]
    roles = {str(item) for item in (supplier.get("roles") or []) if item}
    roles.add("supplier")
    supplier["roles"] = sorted(roles)
    if conflict:
        supplier["pipeline_detail_conflict"] = True


def _supplier_is_closed(supplier: Dict[str, Any]) -> bool:
    """A supplier staff already closed. A withdrawn application is not one.

    ``withdrawn`` is this application's own pending row after a decline. The
    same person can file again on that record. ``rejected``, ``suspended``,
    and ``terminated`` were closed before this application and stay closed.
    """
    supplier_status = str(supplier.get("status") or "").strip().lower()
    if supplier_status == "withdrawn":
        return False
    if supplier_status in _CLOSED_SUPPLIER_STATUSES:
        return True
    if supplier_status == "approved" and supplier.get("portal_active") is False:
        return True
    return supplier_status not in ("approved", "pending", "under_review")


def _link_professional_request(supplier: Dict[str, Any], req: Dict[str, Any]) -> None:
    """Remember this request on the one supplier. The inquiry token is not stored."""
    ids = [str(item) for item in (supplier.get("professional_request_ids") or []) if item]
    request_id = str(req.get("id") or "")
    if request_id and request_id not in ids:
        ids.append(request_id)
    supplier["professional_request_ids"] = ids
    supplier_req = REQUESTS.get(_request_id(req.get("customer_id"), "supplier"))
    if supplier_req and supplier_req.get("status") == "pending":
        supplier["professional_request_id"] = supplier_req.get("id")
    elif request_id:
        supplier["professional_request_id"] = request_id


def _pending_role_request(customer_id: str, role: str) -> Optional[Dict[str, Any]]:
    req = REQUESTS.get(_request_id(customer_id, role))
    if req and req.get("status") == "pending":
        return req
    return None


def _ensure_supplier(req: Dict[str, Any], admin: str, *, approve: bool = True,
                     write_customer: bool = True) -> Dict[str, Any]:
    """One supplier for this customer. A second approval reuses it.

    ``approve`` is false while the application is only waiting on the staff
    desk. That leaves the record pending and does not write the customer master.
    """
    name, stype, from_company = _company_from_request(req)
    existing = _find_supplier(req["customer_id"])
    service = _supply()
    if existing:
        if _supplier_is_closed(existing):
            raise RewardError(
                "This supplier is closed and is not reopened from the application",
                status=409,
                code="supplier_closed",
            )
        _stamp_supplier_details(existing, req, name, stype, from_company)
        supplier_status = str(existing.get("status") or "").strip().lower()
        if supplier_status == "withdrawn":
            existing["status"] = "pending"
            existing["portal_active"] = False
            supplier_status = "pending"
        if approve and supplier_status in ("pending", "under_review"):
            service.approve_supplier(existing["id"], admin or "admin", notes=f"Approved with {req['id']}")
        existing["customer_id"] = req["customer_id"]
        if write_customer:
            rec = _customer_record(req["customer_id"])
            if isinstance(rec, dict):
                rec["supplier_id"] = existing["id"]
        req["supplier_id"] = existing["id"]
        if not req.get("invitation_code"):
            req["invitation_code"] = existing.get("invitation_code")
        _link_professional_request(existing, req)
        return existing
    rec = _customer_record(req["customer_id"]) or {}
    issued = service.generate_invitation_code(
        created_by=admin or "admin",
        supplier_type=stype,
        max_uses=1,
        expires_days=90,
        referrer_id=req["customer_id"],
        notes=f"Professional request {req['id']}",
    )
    code = ((issued or {}).get("invitation") or {}).get("code")
    if not code:
        raise RewardError("Could not issue a supplier invitation", code="supplier_invite_failed")
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    personal = inquiry.get("personal") if isinstance(inquiry.get("personal"), dict) else {}
    company = inquiry.get("company") if from_company and isinstance(inquiry.get("company"), dict) else {}
    registered = service.register_supplier({
        "invitation_code": code,
        "company_name": name,
        "contact_email": rec.get("email") or f"{req['customer_id'].lower()}@phins.local",
        "contact_name": personal.get("name") or rec.get("name") or "PHINS Customer",
        "contact_phone": company.get("phone") or personal.get("phone") or rec.get("phone") or "",
        "supplier_type": stype,
        "password": secrets.token_urlsafe(24),
        "description": company.get("description") or "Opened from a PHINS customer professional request",
        "city": company.get("city") or personal.get("city") or "",
        "country": company.get("country") or personal.get("country") or "",
        "address": company.get("address") or personal.get("address") or "",
        "business_registration_number": company.get("registration_number") or "",
    })
    supplier_id = (registered or {}).get("supplier_id")
    if not supplier_id:
        raise RewardError("Supplier registration did not return an id", code="supplier_failed")
    if approve:
        service.approve_supplier(supplier_id, admin or "admin", notes=f"Approved with {req['id']}")
    supplier = service.suppliers.get(supplier_id)
    if not isinstance(supplier, dict):
        raise RewardError("Supplier registration did not return a record", code="supplier_failed")
    supplier["customer_id"] = req["customer_id"]
    if approve:
        supplier["portal_active"] = True
    supplier["company_name_source"] = "inquiry" if from_company else "placeholder"
    supplier["roles"] = ["supplier"]
    _stamp_supplier_details(supplier, req, name, stype, from_company)
    if write_customer and isinstance(rec, dict):
        rec["supplier_id"] = supplier_id
    req["invitation_code"] = code
    req["supplier_id"] = supplier_id
    _link_professional_request(supplier, req)
    return supplier


def _stage_staff_application(req: Dict[str, Any]) -> None:
    """Show this filed request on the staff desks. Do not approve it.

    A closed supplier is left closed. The request stays pending and is not
    copied onto a second supplier. The customer master is not written.
    """
    existing = _find_supplier(req["customer_id"])
    if existing and _supplier_is_closed(existing):
        req["supplier_id"] = existing.get("id")
        req["staff_hold"] = "supplier_closed"
        return
    _ensure_supplier(req, "professional_inquiry", approve=False, write_customer=False)


def _supplier_application_still_open(req: Dict[str, Any]) -> bool:
    other = REQUESTS.get(_request_id(req.get("customer_id"), "supplier"))
    return bool(
        other
        and other.get("status") == "pending"
        and other.get("id") != req.get("id")
    )


def _approved_role_on_supplier(supplier: Dict[str, Any], req: Dict[str, Any]) -> bool:
    """Another professional role is already approved on this same supplier."""
    customer_id = str(supplier.get("customer_id") or req.get("customer_id") or "")
    sid = str(supplier.get("id") or "")
    for role in ("supplier", "agent"):
        other = REQUESTS.get(_request_id(customer_id, role))
        if not other or other.get("id") == req.get("id"):
            continue
        if other.get("status") == "approved" and str(other.get("supplier_id") or "") == sid:
            return True
    return False


def _unlink_professional_request(supplier: Dict[str, Any], request_id: str) -> None:
    declined = str(request_id or "")
    ids = [str(item) for item in (supplier.get("professional_request_ids") or []) if item and str(item) != declined]
    supplier["professional_request_ids"] = ids
    if str(supplier.get("professional_request_id") or "") == declined:
        supplier["professional_request_id"] = ids[-1] if ids else None


def _link_staged_request(req: Dict[str, Any]) -> None:
    """Point the staged supplier at this request once it is actually pending.

    A supplier that was already closed is not rewritten. The request only
    remembers that id.
    """
    if req.get("staff_hold") == "supplier_closed":
        return
    sid = str(req.get("supplier_id") or "")
    if not sid:
        return
    try:
        supplier = _supply().suppliers.get(sid)
    except RewardError:
        return
    if isinstance(supplier, dict):
        _link_professional_request(supplier, req)


def _supplier_was_approved(supplier: Dict[str, Any]) -> bool:
    """The supplier itself was approved, not only a professional request.

    The portal is on, or a ``supplier_approval`` ledger row already exists.
    A request marked approved while the row is still staged is not enough.
    """
    if supplier.get("portal_active") is True:
        return True
    sid = str(supplier.get("id") or "")
    if not sid:
        return False
    try:
        ledger = getattr(_supply(), "ledger", {}) or {}
    except RewardError:
        return False
    for entry in ledger.values():
        if not isinstance(entry, dict):
            continue
        if entry.get("supplier_id") == sid and entry.get("entry_type") == "supplier_approval":
            return True
    return False


def _usable_agent_id(req: Dict[str, Any]) -> str:
    """An agent grant role-switch can still open."""
    if str(req.get("requested_role") or "") != "agent":
        return ""
    agent_id = str(req.get("agent_id") or "")
    if not agent_id:
        return ""
    from services.agent_ecosystem_service import get_agent
    agent = get_agent(agent_id)
    return agent_id if isinstance(agent, dict) else ""


def _agent_still_referenced(customer_id: str, agent_id: str, ignore_request_id: str = "") -> bool:
    """A real grant or the customer pointer still names this agent.

    The request being reset is not a grant. The customer master is only
    read. Decline does not clear ``agent_id``.
    """
    skipped = str(ignore_request_id or "")
    for item in REQUESTS.values():
        if not isinstance(item, dict):
            continue
        if skipped and str(item.get("id") or "") == skipped:
            continue
        if item.get("status") == "approved" and str(item.get("agent_id") or "") == agent_id:
            return True
    rec = _customer_record(customer_id) or {}
    return str(rec.get("agent_id") or "") == agent_id


def _drop_unreachable_agent(customer_id: str, dangling: str, ignore_request_id: str = "") -> None:
    """Remove the agent id this request just detached, when nothing live names it.

    The id is the only candidate. Login, email, and customer id are not
    searched. An agent the customer record still points at stays, so the
    next approval reuses it. A failed delete raises before any request is
    stored.
    """
    aid = str(dangling or "").strip()
    if not aid or _agent_still_referenced(customer_id, aid, ignore_request_id):
        return
    from services.agent_ecosystem_service import discard_agent
    discard_agent(aid)


def _sibling_fields(req: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": req.get("status"),
        "had_supplier_id": "supplier_id" in req,
        "supplier_id": req.get("supplier_id"),
        "had_agent_id": "agent_id" in req,
        "agent_id": req.get("agent_id"),
    }


def _restore_sibling_fields(req: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    req["status"] = snapshot.get("status")
    if snapshot.get("had_supplier_id"):
        req["supplier_id"] = snapshot.get("supplier_id")
    else:
        req.pop("supplier_id", None)
    if snapshot.get("had_agent_id"):
        req["agent_id"] = snapshot.get("agent_id")
    else:
        req.pop("agent_id", None)


def _detach_withdrawn_supplier(supplier: Dict[str, Any]) -> None:
    """A withdrawn row is not a live supplier.

    A granted agent keeps ``agent_id`` so role-switch still works, and stops
    pointing ``supplier_id`` at this row. An approved stamp with no usable
    agent goes back to inquiry. Only that detached agent id is removed, and
    only when no grant and no customer pointer still name it. The delete
    runs before either request is stored. A failed delete leaves those
    requests unchanged. When there is nothing to delete, both requests are
    stored together. If storing a sibling fails, that sibling is put back
    before the error returns, and the withdrawn supplier snapshot is restored
    with it. The direct review route and both desks reach this through
    ``review_professional``.
    """
    sid = str(supplier.get("id") or "")
    customer_id = str(supplier.get("customer_id") or "")
    planned: List[Tuple[Dict[str, Any], str]] = []
    for role in ("supplier", "agent"):
        other = REQUESTS.get(_request_id(customer_id, role))
        if not isinstance(other, dict) or other.get("status") != "approved":
            continue
        if not (sid and str(other.get("supplier_id") or "") == sid):
            continue
        kept = _usable_agent_id(other)
        if kept:
            planned.append((other, kept))
            continue
        dangling = str(other.get("agent_id") or "")
        _drop_unreachable_agent(
            str(other.get("customer_id") or customer_id),
            dangling,
            str(other.get("id") or ""),
        )
        planned.append((other, ""))
    snapshots = [(other, _sibling_fields(other)) for other, _kept in planned]
    try:
        supplier.pop("agent_id", None)
        for other, kept in planned:
            if kept:
                other.pop("supplier_id", None)
                other["agent_id"] = kept
            else:
                other.pop("supplier_id", None)
                other.pop("agent_id", None)
                other["status"] = "inquiry"
            _persist_request(other)
    except Exception:
        for other, snapshot in snapshots:
            _restore_sibling_fields(other, snapshot)
        for other, _snapshot in snapshots:
            try:
                _persist_request(other)
            except Exception:
                continue
        raise


def _restore_supplier_snapshot(supplier: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    supplier["status"] = snapshot.get("status")
    supplier["portal_active"] = snapshot.get("portal_active")
    supplier["rejection_reason"] = snapshot.get("rejection_reason")
    supplier["professional_request_ids"] = list(snapshot.get("professional_request_ids") or [])
    supplier["professional_request_id"] = snapshot.get("professional_request_id")
    if snapshot.get("had_agent_id"):
        supplier["agent_id"] = snapshot.get("agent_id")
    else:
        supplier.pop("agent_id", None)


def _withdraw_staged_supplier(supplier: Dict[str, Any], request_id: str) -> None:
    snapshot = {
        "status": supplier.get("status"),
        "portal_active": supplier.get("portal_active"),
        "rejection_reason": supplier.get("rejection_reason"),
        "had_agent_id": "agent_id" in supplier,
        "agent_id": supplier.get("agent_id"),
        "professional_request_ids": list(supplier.get("professional_request_ids") or []),
        "professional_request_id": supplier.get("professional_request_id"),
    }
    try:
        _unlink_professional_request(supplier, request_id)
        supplier["status"] = "withdrawn"
        supplier["portal_active"] = False
        supplier["rejection_reason"] = None
        _detach_withdrawn_supplier(supplier)
    except Exception:
        _restore_supplier_snapshot(supplier, snapshot)
        raise


def _release_staged_supplier(req: Dict[str, Any], _admin: str, _note: str) -> None:
    """Take a declined application off the desk without closing the person.

    A staged row that was never activated becomes ``withdrawn``. A request
    that says approved is not an activation, so it is detached from that
    row. ``approved`` is kept only when this supplier was already approved:
    the portal is on, or a ``supplier_approval`` ledger row already exists.
    This does not call ``approve_supplier`` or ``reject_supplier``, and it
    does not turn the portal on, write a ledger row, or write the customer.
    A supplier that was already rejected, suspended, or terminated is not
    touched here.
    """
    try:
        supplier = _find_supplier(req["customer_id"])
    except RewardError:
        return
    if not isinstance(supplier, dict):
        return
    request_id = str(req.get("id") or "")
    status = str(supplier.get("status") or "").strip().lower()
    if status in _CLOSED_SUPPLIER_STATUSES:
        return
    if status == "approved" and supplier.get("portal_active") is False:
        if _supplier_was_approved(supplier):
            _unlink_professional_request(supplier, request_id)
        return
    for role in ("supplier", "agent"):
        other = _pending_role_request(req.get("customer_id"), role)
        if other and other.get("id") != req.get("id"):
            _unlink_professional_request(supplier, request_id)
            return
    if _supplier_was_approved(supplier):
        if status in ("pending", "under_review"):
            supplier["status"] = "approved"
        _unlink_professional_request(supplier, request_id)
        return
    if status not in ("pending", "under_review"):
        return
    _withdraw_staged_supplier(supplier, request_id)


def _ledger_agent_link(service: Any, supplier_id: str, agent_id: str) -> None:
    if not agent_id:
        return
    ledger = getattr(service, "ledger", {}) or {}
    for entry in ledger.values():
        if not isinstance(entry, dict):
            continue
        meta = entry.get("metadata") or {}
        if (entry.get("entry_type") == "agent_role_linked"
                and entry.get("supplier_id") == supplier_id
                and meta.get("agent_id") == agent_id):
            return
    service._record_ledger_entry(
        entry_type="agent_role_linked",
        supplier_id=supplier_id,
        amount=0,
        commission=0,
        supplier_payout=0,
        description="Agent role linked on this supplier",
        metadata={"agent_id": agent_id, "cash_event": False},
    )


def _attach_agent_role(supplier: Dict[str, Any], agent: Dict[str, Any], req: Dict[str, Any]) -> None:
    roles = {str(item) for item in (supplier.get("roles") or []) if item}
    roles.update(("supplier", "agent"))
    supplier["roles"] = sorted(roles)
    new_id = str(agent.get("id") or "")
    current = str(supplier.get("agent_id") or "")
    if current and new_id and current != new_id:
        supplier["pipeline_detail_conflict"] = True
    elif new_id:
        supplier["agent_id"] = new_id
    rec = _customer_record(req["customer_id"])
    if isinstance(rec, dict) and new_id:
        if rec.get("agent_id") and rec.get("agent_id") != new_id:
            supplier["pipeline_detail_conflict"] = True
        else:
            rec["agent_id"] = new_id
    _ledger_agent_link(_supply(), supplier.get("id"), new_id)
    req["agent_id"] = new_id or req.get("agent_id")
    req["supplier_id"] = supplier.get("id")


def _open_agent(req: Dict[str, Any], admin: str, default_rate: Any = None) -> Dict[str, Any]:
    from services.agent_ecosystem_service import create_agent
    supplier = _ensure_supplier(
        req, admin, approve=not _supplier_application_still_open(req),
    )
    rec = _customer_record(req["customer_id"]) or {}
    username = req.get("login_username") or rec.get("email") or req["customer_id"]
    rate = default_rate
    if rate is None:
        rate = int(CONFIG.get("agent_default_rate_percent") or 0)
    agent = create_agent(
        username=str(username),
        display_name=str((req.get("inquiry") or {}).get("personal", {}).get("name") or rec.get("name") or username),
        email=str(rec.get("email") or ""),
        default_rate=rate,
        created_by="referral_rewards",
    )
    _attach_agent_role(supplier, agent, req)
    return agent


def review_professional(request_id: str, decision: str, admin: str, note: str = "",
                        default_rate: Any = None) -> Dict[str, Any]:
    decision = str(decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise RewardError("Decision must be approve or reject")
    with _LOCK:
        _ensure_loaded()
        req = REQUESTS.get(str(request_id or ""))
        if req is None:
            raise RewardError("Request not found", status=404, code="not_found")
        if req.get("status") == "inquiry":
            raise RewardError("The inquiry form has not been submitted", status=409, code="inquiry_open")
        if req.get("status") != "pending":
            raise RewardError(f"Request is already {req.get('status')}", status=409, code="not_pending")
        if decision == "approve":
            try:
                if req["requested_role"] == "agent":
                    agent = _open_agent(req, admin, default_rate)
                    req["agent_id"] = agent.get("id")
                else:
                    supplier = _ensure_supplier(req, admin)
                    req["supplier_id"] = supplier.get("id")
            except RewardError:
                raise
            except Exception as exc:
                raise RewardError(str(exc), status=400, code="professional_open_failed") from exc
            req["status"] = "approved"
        else:
            _release_staged_supplier(req, admin, str(note or ""))
            req["status"] = "rejected"
        req["reviewed_by"] = str(admin or "admin")[:80]
        req["reviewed_at"] = _now()
        req["review_note"] = str(note or "")[:500]
        req["updated_at"] = req["reviewed_at"]
        _persist_request(req)
        _audit(f"professional_{req['status']}", "professional_request", req["id"], {
            "customer_id": req["customer_id"], "role": req["requested_role"],
            "agent_id": req.get("agent_id"), "supplier_id": req.get("supplier_id"),
        })
        return public_request(req)


def pending_agent_desk_rows() -> List[Dict[str, Any]]:
    """Agent applications waiting on the agents dashboard.

    The code is the request id ``PRO-{customer}-agent``. That is the same
    request the desk approves. The inquiry token is not included.
    """
    with _LOCK:
        _ensure_loaded()
        rate_percent = int((CONFIG or default_config()).get("agent_default_rate_percent") or 0)
        proposed = round(rate_percent / 100.0, 6)
        rows = []
        for req in REQUESTS.values():
            if req.get("requested_role") != "agent" or req.get("status") != "pending":
                continue
            rows.append({
                "code": req.get("id"),
                "agent_id": req.get("supplier_id") or req.get("customer_id"),
                "invitee_type": "agent",
                "proposed_rate": proposed,
                "commission_rate": None,
                "status": "pending_approval",
                "professional_request_id": req.get("id"),
                "notes": "Professional application",
                "created_at": ((req.get("inquiry") or {}).get("submitted_at") if isinstance(req.get("inquiry"), dict) else None)
                or req.get("updated_at"),
            })
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return rows


def _desk_supplier_row(req: Dict[str, Any]) -> Dict[str, Any]:
    name, stype, from_company = _company_from_request(req)
    inquiry = req.get("inquiry") if isinstance(req.get("inquiry"), dict) else {}
    personal = inquiry.get("personal") if isinstance(inquiry.get("personal"), dict) else {}
    return {
        "id": req.get("id"),
        "professional_request_id": req.get("id"),
        "professional_request_ids": [req.get("id")],
        "customer_id": req.get("customer_id"),
        "company_name": name if from_company else (personal.get("name") or name),
        "supplier_type": stype if from_company else "other",
        "contact_name": personal.get("name") or "",
        "contact_email": _inquiry_email_for(req),
        "application_date": inquiry.get("submitted_at") or req.get("updated_at"),
        "status": "pending",
        "ai_trust_score": 0,
        "ai_recommendation": "review",
        "staff_hold": req.get("staff_hold"),
    }


def pending_supplier_desk_rows(visible_supplier_ids: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """Filed requests that are not already a pending supplier row.

    A live pending supplier is the application. This adds a request the desk
    would otherwise miss, including one held because the supplier is closed.
    """
    visible = {str(item) for item in visible_supplier_ids if item}
    with _LOCK:
        _ensure_loaded()
        rows = []
        seen = set()
        for req in list(REQUESTS.values()):
            if req.get("status") != "pending":
                continue
            if req.get("requested_role") not in ("supplier", "agent"):
                continue
            customer_id = str(req.get("customer_id") or "")
            if customer_id in seen:
                continue
            sid = str(req.get("supplier_id") or "")
            if sid and sid in visible:
                continue
            supplier = None
            if sid:
                try:
                    supplier = _supply().suppliers.get(sid)
                except RewardError:
                    supplier = None
            if isinstance(supplier, dict) and str(supplier.get("status") or "").lower() in ("pending", "under_review"):
                continue
            chosen = req
            if req.get("requested_role") != "supplier":
                supplier_req = _pending_role_request(customer_id, "supplier")
                if supplier_req:
                    chosen = supplier_req
            seen.add(customer_id)
            rows.append(_desk_supplier_row(chosen))
        return rows


def continue_agent_application(code: str, decision: str, admin: str,
                               note: str = "") -> Optional[Dict[str, Any]]:
    """Approve or reject the agent request whose id is the desk code.

    A normal agent-invitation code is not a professional request and returns
    None so that invitation stays on its own path. The agent's default rate
    stays the program default. The invitation body's commission rate is not
    copied onto the agent.
    """
    key = str(code or "").strip()
    with _LOCK:
        _ensure_loaded()
        req = REQUESTS.get(key)
        if req is None or req.get("requested_role") != "agent":
            return None
        request_id = req.get("id")
    return review_professional(request_id, decision, admin, note)


def _pending_request_on_supplier(supplier: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pending professional request staged on this supplier.

    Sharing a customer id is not enough. The request must name this supplier,
    or this supplier must name that request. The supplier role wins when both
    roles were staged here, so the agents desk still reviews the agent request.
    """
    sid = str(supplier.get("id") or "")
    if not sid:
        return None
    linked = {str(item) for item in (supplier.get("professional_request_ids") or []) if item}
    primary = str(supplier.get("professional_request_id") or "")
    if primary:
        linked.add(primary)
    customer_id = str(supplier.get("customer_id") or "")
    chosen = None
    for role in ("supplier", "agent"):
        req = _pending_role_request(customer_id, role)
        if not req:
            continue
        request_id = str(req.get("id") or "")
        staged_here = request_id in linked or str(req.get("supplier_id") or "") == sid
        if not staged_here:
            continue
        if role == "supplier":
            return req
        chosen = chosen or req
    return chosen


def continue_supplier_application(supplier_or_request_id: str, decision: str, admin: str,
                                  note: str = "") -> Optional[Dict[str, Any]]:
    """Continue the professional request staged on this supplier.

    A request id continues that request (the closed-supplier row uses the
    request id). Any other supplier stays on approve_supplier / reject_supplier.
    """
    key = str(supplier_or_request_id or "").strip()
    with _LOCK:
        _ensure_loaded()
        target_id = ""
        direct = REQUESTS.get(key)
        if (
            direct
            and direct.get("status") == "pending"
            and direct.get("requested_role") in ("supplier", "agent")
        ):
            target_id = str(direct.get("id") or "")
        else:
            supplier = None
            try:
                supplier = _supply().suppliers.get(key)
            except RewardError:
                supplier = None
            if not isinstance(supplier, dict):
                return None
            target = _pending_request_on_supplier(supplier)
            if target is None:
                return None
            target_id = str(target.get("id") or "")
    if not target_id:
        return None
    return review_professional(target_id, decision, admin, note)


def _audit(action: str, entity: str, entity_id: str, details: Dict[str, Any]) -> None:
    portal = _portal()
    audit = getattr(portal, "audit", None) if portal else None
    if audit is None or not hasattr(audit, "log"):
        return
    try:
        audit.log("referral_rewards", action, entity, entity_id, details)
    except Exception:
        return


def professional_status(customer_id: str) -> Dict[str, Any]:
    """Desks follow the supplier record.

    A professional request marked approved is not a supplier approval. The
    supplier desk is approved only when that supplier was activated. Until
    then neither desk is reported as approved, and a withdrawn row is not
    presented as a live ``supplier_id`` or ``agent_id``.
    """
    with _LOCK:
        _ensure_loaded()
        try:
            supplier = _find_supplier(customer_id)
        except RewardError:
            supplier = None
        live = isinstance(supplier, dict) and _supplier_was_approved(supplier)
        record_status = str((supplier or {}).get("status") or "").strip().lower()
        out: Dict[str, Any] = {}
        for role in ("agent", "supplier"):
            req = REQUESTS.get(_request_id(customer_id, role))
            view = public_request(req) if req else {"status": "none", "requested_role": role}
            if not live and view.get("status") == "approved":
                view = dict(view)
                view["status"] = record_status or "none"
                if record_status == "withdrawn":
                    view["supplier_id"] = None
                    view["agent_id"] = None
            out[role] = view
        if isinstance(supplier, dict):
            desk = dict(out.get("supplier") or {})
            desk["requested_role"] = "supplier"
            desk["customer_id"] = customer_id
            if live:
                desk["status"] = "approved"
                desk["supplier_id"] = supplier.get("id")
            else:
                desk["status"] = record_status or desk.get("status") or "none"
                if record_status == "withdrawn":
                    desk["supplier_id"] = None
                    desk["agent_id"] = None
            desk.pop("via", None)
            out["supplier"] = desk
        return out


def supplier_access(customer_id: str) -> Optional[Dict[str, Any]]:
    """Supplier desk for this customer. An approved agent already has one."""
    supplier = (professional_status(customer_id).get("supplier") or {})
    if supplier.get("status") == "approved" and supplier.get("supplier_id"):
        return supplier
    return None


def _money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _order_sales_fee(order: Dict[str, Any]) -> float:
    """One sales fee per order. platform_fee wins when the order carries it."""
    if order.get("platform_fee") is not None:
        return _money(order.get("platform_fee"))
    return _money(order.get("commission"))


def _supplier_orders() -> List[Dict[str, Any]]:
    service = None
    try:
        service = _supply()
    except RewardError:
        service = None
    orders = getattr(service, "orders", None) if service else None
    if not isinstance(orders, dict):
        portal = _portal()
        orders = getattr(portal, "SUPPLIER_ORDERS", {}) if portal else {}
    if not isinstance(orders, dict):
        return []
    return [order for order in orders.values() if isinstance(order, dict)]


def _acquisition_for(customer_id: str) -> Tuple[float, List[str]]:
    cents = 0
    ids: List[str] = []
    for reward in REWARDS.values():
        if str(reward.get("beneficiary_customer_id")) != str(customer_id):
            continue
        if reward.get("status") == "forfeited" or not _reward_intact(reward):
            continue
        cents += int(reward.get("amount_cents") or 0)
        if reward.get("id"):
            ids.append(str(reward["id"]))
    return dollars(cents), ids


def _commission_for(agent_id: str) -> Tuple[float, List[str]]:
    if not agent_id:
        return 0.0, []
    try:
        from services.agent_ecosystem_service import list_commissions
        rows = list_commissions(agent_id)
    except Exception:
        return 0.0, []
    total = 0.0
    ids: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        total += _money(row.get("amount"))
        if row.get("id"):
            ids.append(str(row["id"]))
    return round(total, 2), ids


def _pipeline_rows_locked() -> List[Dict[str, Any]]:
    orders = _supplier_orders()
    by_supplier: Dict[str, List[Dict[str, Any]]] = {}
    for order in orders:
        sid = str(order.get("supplier_id") or "")
        if sid:
            by_supplier.setdefault(sid, []).append(order)
    try:
        suppliers = [item for item in (_supply().suppliers or {}).values() if isinstance(item, dict)]
    except RewardError:
        suppliers = []
    rows = []
    for supplier in suppliers:
        sid = str(supplier.get("id") or "")
        customer_id = str(supplier.get("customer_id") or "")
        agent_id = str(supplier.get("agent_id") or "")
        roles = [str(role) for role in (supplier.get("roles") or []) if role]
        is_agent = "agent" in roles or bool(agent_id)
        mine = by_supplier.get(sid, [])
        acquisition, reward_ids = _acquisition_for(customer_id) if customer_id else (0.0, [])
        commissions, commission_ids = _commission_for(agent_id) if is_agent else (0.0, [])
        sales = round(sum(_order_sales_fee(order) for order in mine), 2)
        payouts = round(sum(_money(order.get("supplier_payout")) for order in mine), 2)
        rows.append({
            "supplier_id": sid,
            "customer_id": customer_id or None,
            "company_name": supplier.get("company_name"),
            "roles": roles or ["supplier"],
            "is_agent": is_agent,
            "agent_id": agent_id or None,
            "sales_fees": sales,
            "supplier_payouts": payouts,
            "acquisition_rewards": acquisition,
            "agent_commissions": commissions,
            "order_ids": [str(order.get("id")) for order in mine if order.get("id")],
            "reward_ids": reward_ids,
            "commission_ids": commission_ids,
            "pipeline_detail_conflict": bool(supplier.get("pipeline_detail_conflict")),
            "statement_sha256": None,
        })
    rows.sort(key=lambda item: item.get("company_name") or item.get("supplier_id") or "")
    return rows


def _booked_acquisition_expense() -> float:
    portal = _portal()
    sheet = getattr(portal, "PHINS_BALANCE_SHEET", {}) if portal else {}
    if not isinstance(sheet, dict):
        return 0.0
    return _money((sheet.get("expense_breakdown") or {}).get("customer_acquisition"))


def _ledger_summary() -> Dict[str, Any]:
    try:
        service = _supply()
        report = service.verify_ledger_integrity()
    except Exception:
        return {"ok": False, "issue_count": None}
    issues = report.get("issues") or []
    return {
        "ok": not issues and int(report.get("valid_entries") or 0) == int(report.get("total_entries") or 0),
        "issue_count": len(issues),
        "total_entries": report.get("total_entries"),
    }


def _sum_rows(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    return {
        "sales_fees": round(sum(_money(row.get("sales_fees")) for row in rows), 2),
        "supplier_payouts": round(sum(_money(row.get("supplier_payouts")) for row in rows), 2),
        "acquisition_rewards": round(sum(_money(row.get("acquisition_rewards")) for row in rows), 2),
        "agent_commissions": round(sum(_money(row.get("agent_commissions")) for row in rows), 2),
    }


def pipeline_report(audience: str = "supplier") -> Dict[str, Any]:
    """Read sales fees, acquisition rewards, and agent commissions. Do not add them."""
    audience = str(audience or "supplier").strip().lower()
    if audience not in _PIPELINE_AUDIENCES:
        raise RewardError("Audience must be supplier, agent, customer, tax, or regulator")
    with _LOCK:
        _ensure_loaded()
        rows = _pipeline_rows_locked()
        expense = _booked_acquisition_expense()
        ledger = _ledger_summary()
        requests = list(REQUESTS.values())
        customer_rows = _customer_rows_locked(rows)
    if audience == "tax":
        return {
            "audience": "tax",
            "currency": "USD",
            "rails_are_separate": True,
            "personal_data": False,
            "sales_fees": _sum_rows(rows)["sales_fees"],
            "supplier_payouts": _sum_rows(rows)["supplier_payouts"],
            "acquisition_rewards_on_suppliers": _sum_rows(rows)["acquisition_rewards"],
            "acquisition_expense_booked": expense,
            "agent_commissions": _sum_rows(rows)["agent_commissions"],
            "businesses": [
                {
                    "supplier_id": row["supplier_id"],
                    "company_name": row["company_name"],
                    "sales_fees": row["sales_fees"],
                    "supplier_payouts": row["supplier_payouts"],
                    "acquisition_rewards": row["acquisition_rewards"],
                    "agent_commissions": row["agent_commissions"],
                }
                for row in rows
            ],
        }
    if audience == "regulator":
        return {
            "audience": "regulator",
            "currency": "USD",
            "rails_are_separate": True,
            "personal_data": False,
            "suppliers": len(rows),
            "agents_on_suppliers": sum(1 for row in rows if row.get("is_agent")),
            "inquiries_open": sum(1 for item in requests if item.get("status") == "inquiry"),
            "applications_pending": sum(1 for item in requests if item.get("status") == "pending"),
            "sales_fees": _sum_rows(rows)["sales_fees"],
            "acquisition_expense_booked": expense,
            "agent_commissions": _sum_rows(rows)["agent_commissions"],
            "ledger_integrity_ok": bool(ledger.get("ok")),
            "ledger_issue_count": ledger.get("issue_count"),
        }
    if audience == "customer":
        return {
            "audience": "customer",
            "currency": "USD",
            "rails_are_separate": True,
            "rows": customer_rows,
            "totals": {
                "acquisition_rewards": round(sum(_money(row.get("acquisition_rewards")) for row in customer_rows), 2),
                "sales_fees_on_orders": round(sum(_money(row.get("sales_fees_on_orders")) for row in customer_rows), 2),
            },
        }
    shown = [row for row in rows if row.get("is_agent")] if audience == "agent" else rows
    return {
        "audience": audience,
        "currency": "USD",
        "rails_are_separate": True,
        "rows": shown,
        "totals": _sum_rows(shown),
        "acquisition_expense_booked": expense,
    }


def _customer_rows_locked(supplier_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}

    def slot(customer_id: Any) -> Optional[Dict[str, Any]]:
        cid = str(customer_id or "")
        if not cid:
            return None
        row = by_id.get(cid)
        if row is None:
            row = {
                "customer_id": cid,
                "name": _first_name(cid),
                "acquisition_rewards": 0.0,
                "sales_fees_on_orders": 0.0,
                "supplier_id": None,
                "is_agent": False,
            }
            by_id[cid] = row
        return row

    for reward in REWARDS.values():
        if reward.get("status") == "forfeited" or not _reward_intact(reward):
            continue
        row = slot(reward.get("beneficiary_customer_id"))
        if row is not None:
            row["acquisition_rewards"] = round(
                row["acquisition_rewards"] + dollars(int(reward.get("amount_cents") or 0)), 2,
            )
    for order in _supplier_orders():
        row = slot(order.get("customer_id"))
        if row is not None:
            row["sales_fees_on_orders"] = round(row["sales_fees_on_orders"] + _order_sales_fee(order), 2)
    for supplier_row in supplier_rows:
        row = slot(supplier_row.get("customer_id"))
        if row is not None:
            row["supplier_id"] = supplier_row.get("supplier_id")
            row["is_agent"] = bool(supplier_row.get("is_agent"))
    return sorted(by_id.values(), key=lambda item: item["customer_id"])


def _find_statement(service: Any, supplier_id: str, digest: str) -> Optional[Dict[str, Any]]:
    ledger = getattr(service, "ledger", {}) or {}
    for entry in ledger.values():
        if not isinstance(entry, dict):
            continue
        meta = entry.get("metadata") or {}
        if (entry.get("entry_type") == "pipeline_statement"
                and entry.get("supplier_id") == supplier_id
                and meta.get("statement_sha256") == digest):
            return entry
    return None


def seal_pipeline_statements(supplier_id: str = "") -> Dict[str, Any]:
    """Anchor the current read of existing fees and rewards. Amount posted is zero."""
    report = pipeline_report("supplier")
    service = _supply()
    wanted = str(supplier_id or "").strip()
    sealed = []
    for row in report.get("rows") or []:
        sid = str(row.get("supplier_id") or "")
        if not sid or (wanted and sid != wanted):
            continue
        snapshot = {
            "supplier_id": sid,
            "sales_fees": row.get("sales_fees"),
            "supplier_payouts": row.get("supplier_payouts"),
            "acquisition_rewards": row.get("acquisition_rewards"),
            "agent_commissions": row.get("agent_commissions"),
            "order_ids": list(row.get("order_ids") or []),
            "reward_ids": list(row.get("reward_ids") or []),
            "commission_ids": list(row.get("commission_ids") or []),
        }
        digest = _sha(snapshot)
        existing = _find_statement(service, sid, digest)
        if existing:
            sealed.append({
                "supplier_id": sid,
                "entry_id": existing.get("entry_id"),
                "reused": True,
                "statement_sha256": digest,
            })
            continue
        entry = service._record_ledger_entry(
            entry_type="pipeline_statement",
            supplier_id=sid,
            customer_id=row.get("customer_id"),
            amount=0,
            commission=0,
            supplier_payout=0,
            description="Supplier pipeline statement from existing fees and rewards",
            metadata={
                "statement_sha256": digest,
                "sales_fees": snapshot["sales_fees"],
                "supplier_payouts": snapshot["supplier_payouts"],
                "acquisition_rewards": snapshot["acquisition_rewards"],
                "agent_commissions": snapshot["agent_commissions"],
                "order_ids": snapshot["order_ids"],
                "reward_ids": snapshot["reward_ids"],
                "commission_ids": snapshot["commission_ids"],
                "cash_event": False,
            },
        )
        sealed.append({
            "supplier_id": sid,
            "entry_id": getattr(entry, "entry_id", None),
            "reused": False,
            "statement_sha256": digest,
        })
    if wanted and not sealed:
        raise RewardError("Supplier not found", status=404, code="not_found")
    return {"sealed": sealed, "cash_event": False}


def grant_for(customer_id: str, role: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        _ensure_loaded()
        return dict(_approved_request(customer_id, role) or {}) or None


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def _distribution_choice(reward: Dict[str, Any]) -> Optional[str]:
    allocation = reward.get("allocation") or {}
    active = [dest for dest in DESTINATIONS if int(allocation.get(dest) or 0) > 0]
    if not active:
        return None
    if len(active) == 1:
        return active[0]
    return "split"


def _surface_links(destinations: Iterable[str]) -> List[Dict[str, str]]:
    chosen = set(destinations)
    links = []
    for dest in DESTINATIONS:
        if dest not in chosen:
            continue
        spec = DESTINATION_LINKS[dest]
        links.append({
            "destination": dest,
            "label": spec["label"],
            "href": spec["customer_href"],
            "staff_href": spec["href"],
        })
    return links


def _links_for_reward(reward: Dict[str, Any]) -> List[Dict[str, str]]:
    allocation = reward.get("allocation") or {}
    active = [dest for dest in DESTINATIONS if int(allocation.get(dest) or 0) > 0]
    if active:
        return _surface_links(active)
    policy = reward.get("policy") or {}
    return _surface_links(policy.get("allowed") or [])


def public_reward(reward: Dict[str, Any]) -> Dict[str, Any]:
    policy = reward.get("policy") or {}
    allocation = reward.get("allocation") or {}
    status = reward.get("status")
    return {
        "id": reward["id"],
        "layer": reward["layer"],
        "status": status,
        "amount": dollars(reward["amount_cents"]),
        "amount_cents": reward["amount_cents"],
        "currency": reward.get("currency") or "USD",
        "referee_customer_id": reward["referee_customer_id"],
        "referee_name": _first_name(reward["referee_customer_id"]),
        "beneficiary_customer_id": reward.get("beneficiary_customer_id"),
        "beneficiary_name": _first_name(str(reward.get("beneficiary_customer_id") or "")),
        "earned_at": reward.get("earned_at"),
        "dispatched_at": reward.get("dispatched_at"),
        "release_at": reward.get("release_at"),
        "hold_months": reward.get("hold_months"),
        "blocked": status == "held",
        "available": status == "earned",
        "settlement_id": reward.get("settlement_id"),
        "allowed": list(policy.get("allowed") or []),
        "cash_cap_percent": bps_to_percent(int(policy.get("cash_cap_bps") or 0)),
        "default": {k: bps_to_percent(v) for k, v in (policy.get("default_bps") or {}).items()},
        "allocation": {k: bps_to_percent(v) for k, v in allocation.items()} if allocation else None,
        "distribution": _distribution_choice(reward),
        "links": _links_for_reward(reward),
        "fee_mode": policy.get("fee_mode") or "fixed",
        "posted": sorted((reward.get("posted") or {}).keys()),
    }


def _book_row(reward: Dict[str, Any], *, booked: bool = True,
              projected_cents: int = 0) -> Dict[str, Any]:
    status = reward.get("status")
    cents = int(reward.get("amount_cents") or 0) if booked else 0
    return {
        "reward_id": reward.get("id"),
        "referee_customer_id": reward.get("referee_customer_id"),
        "referee_name": _first_name(str(reward.get("referee_customer_id") or "")),
        "beneficiary_customer_id": reward.get("beneficiary_customer_id"),
        "beneficiary_name": _first_name(str(reward.get("beneficiary_customer_id") or "")),
        "layer": int(reward.get("layer") or 0),
        "amount": dollars(cents),
        "projected_amount": dollars(projected_cents) if not booked else None,
        "booked": booked,
        "status": status,
        "blocked_amount": dollars(cents) if status == "held" else 0,
        "available_amount": dollars(cents) if status == "earned" else 0,
        "dispatched_amount": dollars(cents) if status == "dispatched" else 0,
        "release_at": reward.get("release_at"),
        "distribution": _distribution_choice(reward) if booked else None,
        "allocation": public_reward(reward).get("allocation") if booked else None,
        "links": _links_for_reward(reward) if booked else _surface_links(DESTINATIONS[:3]),
    }


def _empty_layer_bucket() -> Dict[str, Any]:
    return {"customers": 0, "amount_cents": 0, "blocked_cents": 0, "available_cents": 0, "dispatched_cents": 0}


def _layer_buckets(rewards: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    buckets = {str(layer): _empty_layer_bucket() for layer in LAYERS}
    for reward in rewards:
        if reward.get("status") == "forfeited":
            continue
        slot = buckets.get(str(reward.get("layer")))
        if slot is None:
            continue
        cents = int(reward.get("amount_cents") or 0)
        slot["customers"] += 1
        slot["amount_cents"] += cents
        status = reward.get("status")
        if status == "held":
            slot["blocked_cents"] += cents
        elif status == "earned":
            slot["available_cents"] += cents
        elif status == "dispatched":
            slot["dispatched_cents"] += cents
    return {
        key: {
            "customers": val["customers"],
            "amount": dollars(val["amount_cents"]),
            "blocked": dollars(val["blocked_cents"]),
            "available": dollars(val["available_cents"]),
            "dispatched": dollars(val["dispatched_cents"]),
        }
        for key, val in buckets.items()
    }


def _affiliate_book_locked(customer_id: str) -> Dict[str, Any]:
    """One affiliate's acquisition book: layer counts, blocked versus ready, and where it went."""
    mine = [reward for reward in REWARDS.values()
            if str(reward.get("beneficiary_customer_id")) == customer_id]
    booked = [reward for reward in mine if reward.get("status") != "forfeited"]
    rows = [_book_row(reward) for reward in mine]
    seen = {str(reward.get("referee_customer_id")) for reward in mine}
    cfg = CONFIG or default_config()
    awaiting = 0
    customers = _customers()
    candidates = set(LINKS) | {str(cid) for cid, rec in customers.items()
                               if isinstance(rec, dict) and rec.get("referred_by")}
    for referee in candidates:
        if referee in seen or referee == customer_id:
            continue
        chain = chain_of(referee, customers, cfg.get("max_layers"))
        hit = next(((layer, parent) for layer, parent in chain if parent == customer_id), None)
        if hit is None:
            continue
        if SETTLEMENTS.get(referee) and not SETTLEMENTS[referee].get("_quarantined"):
            continue
        layer = hit[0]
        filled = [item[0] for item in chain]
        projected = 0
        try:
            projected_fee, projected_basis = _fee_basis_for(referee, cfg)
            if projected_fee > 0:
                projected = waterfall_amounts(
                    projected_fee, projected_basis["schedule_cents"], filled,
                )[layer - 1]
        except RewardError:
            projected = 0
        rows.append(_book_row({
            "id": None,
            "referee_customer_id": referee,
            "beneficiary_customer_id": customer_id,
            "layer": layer,
            "status": "awaiting_payment",
            "amount_cents": 0,
            "policy": {"allowed": list(DESTINATIONS)},
        }, booked=False, projected_cents=projected))
        awaiting += 1
        seen.add(referee)
    rows.sort(key=lambda item: (item.get("layer") or 0, item.get("referee_name") or ""))
    return {
        "affiliated_customers": len(booked),
        "awaiting_customers": awaiting,
        "blocked": dollars(sum(int(r.get("amount_cents") or 0) for r in booked if r.get("status") == "held")),
        "available": dollars(sum(int(r.get("amount_cents") or 0) for r in booked if r.get("status") == "earned")),
        "dispatched": dollars(sum(int(r.get("amount_cents") or 0) for r in booked if r.get("status") == "dispatched")),
        "by_layer": _layer_buckets(booked),
        "rows": rows,
        "surfaces": {
            "billing": "/billing.html",
            "premium": "/dashboard.html#billing",
            "health_wallet": "/dashboard.html#health-wallet",
            "investments": "/savings-portfolio.html",
        },
    }


def _tools(customer_id: str) -> Dict[str, Any]:
    portal = _portal()
    settings = getattr(portal, "DESIGN_SETTINGS", {}) if portal else {}
    assets = getattr(portal, "MEDIA_ASSETS", {}) if portal else {}
    if not isinstance(settings, dict):
        settings = {}
    if not isinstance(assets, dict):
        assets = {}
    videos = []
    direct = str(settings.get("video_url") or "").strip()
    if direct:
        videos.append({"label": "Platform film", "url": direct})
    for key, label in (
        ("login_hero_video_id", "Login film"),
        ("solutions_hero_video_id", "Solutions film"),
        ("apply_disclosure_video_id", "Application disclaimer"),
        ("claims_chat_disclaimer_video_id", "Claims disclaimer"),
    ):
        asset = assets.get(settings.get(key) or "")
        url = asset.get("url") if isinstance(asset, dict) else ""
        if url:
            videos.append({"label": label, "url": url})
    agent = _approved_request(customer_id, "agent")
    supplier = _approved_request(customer_id, "supplier")
    supplier_href = "/supplier-register.html"
    if supplier and supplier.get("invitation_code") and not supplier.get("supplier_id"):
        supplier_href = f"/supplier-register.html?code={supplier['invitation_code']}"
    return {
        "videos": videos,
        "links": [
            {"id": "invite", "label": "Invite a customer", "href": "/dashboard.html#referrals", "enabled": True},
            {"id": "agent", "label": "Agent portal", "href": "/agent-portal.html", "enabled": bool(agent)},
            {"id": "supplier", "label": "Supplier portal", "href": "/supplier-login.html", "enabled": bool(supplier)},
            {"id": "supplier_register", "label": "Supplier registration", "href": supplier_href, "enabled": True},
            {"id": "solutions", "label": "Solution theaters", "href": "/solutions.html", "enabled": True},
            {"id": "admin_agents", "label": "Agent administration", "href": "/admin-agents.html", "enabled": False},
        ],
    }


def customer_dashboard(customer_id: str) -> Dict[str, Any]:
    with _LOCK:
        _ensure_loaded()
        _refresh_all_locked()
        customer_id = str(customer_id or "")
        mine = [reward for reward in REWARDS.values()
                if str(reward.get("beneficiary_customer_id")) == customer_id
                and reward.get("status") != "forfeited"]
        rewards = [public_reward(reward) for reward in mine]
        rewards.sort(key=lambda item: item.get("earned_at") or "", reverse=True)
        outgoing = [link for link in LINKS.values() if str(link.get("referrer_customer_id")) == customer_id]
        earned = sum(int(r["amount_cents"]) for r in mine)
        blocked = sum(int(r["amount_cents"]) for r in mine if r.get("status") == "held")
        waiting = sum(int(r["amount_cents"]) for r in mine if r.get("status") == "earned")
        dispatched = sum(int(r["amount_cents"]) for r in mine if r.get("status") == "dispatched")
        program = config_to_admin()
        return {
            "enabled": bool(CONFIG.get("enabled", True)),
            "currency": "USD",
            "fee_mode": program["fee_mode"],
            "fee": program["fee"],
            "premium_percent": program["premium_percent"],
            "preview": program["preview"],
            "hold_months": program["hold_months"],
            "max_layers": program["max_layers"],
            "invitation_cap": invitation_cap_for(customer_id),
            "layers": program["layers"],
            "destinations": list(DESTINATIONS),
            "rewards": rewards,
            "totals": {
                "earned": dollars(earned),
                "blocked": dollars(blocked),
                "dispatched": dollars(dispatched),
                "pending_choice": dollars(waiting),
                "count": len(rewards),
            },
            "direct_referrals": len(outgoing),
            "paying_referrals": sum(1 for link in outgoing if link.get("paying_at")),
            "affiliation_book": _affiliate_book_locked(customer_id),
            "professional": professional_status(customer_id),
            "supplier_types": supplier_type_values(),
            "tools": _tools(customer_id),
            "affiliation": affiliation_for(customer_id),
        }


_PLAN_FIELDS = ("fee_mode", "fee", "fee_cents", "premium_percent", "premium_rate_bps", "layers")


def update_plan(patch: Dict[str, Any], updated_by: str = "actuary") -> Dict[str, Any]:
    """Adjust the fee basis and the three layer amounts. Destination rules stay as they are.

    An admin or an actuary uses this from the affiliated-customer acquisition
    plan. Invitation caps, cash rules, and the enabled flag stay on the admin
    program route. A saved plan applies to fees earned after the change.
    """
    if not isinstance(patch, dict):
        raise RewardError("Plan must be an object")
    narrowed: Dict[str, Any] = {}
    for key in _PLAN_FIELDS:
        if key in patch:
            narrowed[key] = patch[key]
    if isinstance(narrowed.get("layers"), list):
        layers = []
        for item in narrowed["layers"]:
            if not isinstance(item, dict):
                raise RewardError("Each layer must be an object")
            kept: Dict[str, Any] = {"layer": item.get("layer")}
            if item.get("amount") is not None:
                kept["amount"] = item["amount"]
            if item.get("amount_cents") is not None:
                kept["amount_cents"] = item["amount_cents"]
            layers.append(kept)
        narrowed["layers"] = layers
    if not narrowed:
        raise RewardError("Nothing to update on the acquisition plan")
    return update_config(narrowed, updated_by)


def update_config(patch: Dict[str, Any], updated_by: str = "admin") -> Dict[str, Any]:
    with _LOCK:
        _ensure_loaded()
        updated = _admin_to_internal(patch or {}, CONFIG)
        updated["version"] = int(CONFIG.get("version") or 1) + 1
        updated["updated_by"] = str(updated_by or "admin")[:80]
        CONFIG.clear()
        CONFIG.update(updated)
        _persist_config()
        _audit("program_updated", "referral_program", "active", {
            "version": updated["version"], "fee_cents": updated["fee_cents"],
            "fee_mode": updated.get("fee_mode"),
            "premium_rate_bps": updated.get("premium_rate_bps"),
            "layer_amounts": [int(item["amount_cents"]) for item in updated["layers"]],
            "hold_months": updated["hold_months"], "by": updated_by,
        })
        return config_to_admin()


def set_hold_months(months: Any, updated_by: str = "actuary") -> Dict[str, Any]:
    """Change only the hold. Fee and layer shares stay on the admin path."""
    try:
        parsed = int(months)
    except (TypeError, ValueError) as exc:
        raise RewardError("hold_months must be a whole number of months") from exc
    return update_config({"hold_months": parsed}, updated_by)


def get_config() -> Dict[str, Any]:
    with _LOCK:
        _ensure_loaded()
        return config_to_admin()


def list_requests(status: Optional[str] = None) -> List[Dict[str, Any]]:
    with _LOCK:
        _ensure_loaded()
        items = list(REQUESTS.values())
        if status:
            items = [item for item in items if item.get("status") == status]
        items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return [public_request(item) for item in items]


def _measure_referee_cents(referee_id: str) -> Dict[str, Any]:
    """One affiliated customer's settlement, in cents.

    Allocated, blocked, releasable, settled, and reversed use the same
    rules as the planning view. A reversed settlement is not also allocated.
    Held rewards are blocked. Earned rewards are releasable. Commission is
    not read here.
    """
    referee_id = str(referee_id or "")
    allocated = blocked = releasable = settled = reversed_cents = projected = 0
    settlement = SETTLEMENTS.get(referee_id) if referee_id else None
    status = "none"
    settlement_id = None
    if isinstance(settlement, dict):
        cents = int(settlement.get("allocated_cents") or 0)
        status = str(settlement.get("status") or "none")
        settlement_id = settlement.get("id")
        if status == "reversed":
            reversed_cents += cents
        else:
            allocated += cents
            if status == "settled":
                settled += cents
    paying = _is_paying(referee_id) if referee_id else False
    for reward in REWARDS.values():
        if str(reward.get("referee_customer_id") or "") != referee_id:
            continue
        cents = int(reward.get("amount_cents") or 0)
        reward_status = reward.get("status")
        if reward_status == "held":
            blocked += cents
            if paying:
                projected += cents
        elif reward_status == "earned":
            releasable += cents
    return {
        "settlement_id": settlement_id,
        "status": status,
        "allocated_cents": allocated,
        "blocked_cents": blocked,
        "releasable_cents": releasable,
        "settled_cents": settled,
        "reversed_cents": reversed_cents,
        "projected_cents": projected,
    }


def _public_acquisition(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "settlement_id": raw.get("settlement_id"),
        "status": raw.get("status") or "none",
        "allocated": dollars(raw.get("allocated_cents") or 0),
        "blocked": dollars(raw.get("blocked_cents") or 0),
        "releasable": dollars(raw.get("releasable_cents") or 0),
        "settled": dollars(raw.get("settled_cents") or 0),
        "reversed": dollars(raw.get("reversed_cents") or 0),
    }


def _empty_acquisition() -> Dict[str, Any]:
    return _public_acquisition({
        "settlement_id": None,
        "status": "none",
        "allocated_cents": 0,
        "blocked_cents": 0,
        "releasable_cents": 0,
        "settled_cents": 0,
        "reversed_cents": 0,
    })


def _acquisition_totals(rows: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    keys = ("allocated", "blocked", "releasable", "settled", "reversed")
    return {
        key: round(sum(_money((row.get("acquisition") or {}).get(key)) for row in rows), 2)
        for key in keys
    }


def _viewer_share_cents(viewer_id: str, referee_id: str) -> Dict[str, Any]:
    """This viewer's own layer on one settlement. Other layers are not included."""
    viewer_id = str(viewer_id or "")
    referee_id = str(referee_id or "")
    allocated = blocked = releasable = settled = reversed_cents = 0
    layer = None
    settlement_id = None
    status = "none"
    for reward in REWARDS.values():
        if str(reward.get("referee_customer_id") or "") != referee_id:
            continue
        if str(reward.get("beneficiary_customer_id") or "") != viewer_id:
            continue
        cents = int(reward.get("amount_cents") or 0)
        layer = int(reward.get("layer") or 0) or layer
        settlement_id = reward.get("settlement_id") or settlement_id
        reward_status = str(reward.get("status") or "none")
        status = reward_status
        if reward_status == "forfeited":
            reversed_cents += cents
        elif reward_status == "held":
            allocated += cents
            blocked += cents
        elif reward_status == "earned":
            allocated += cents
            releasable += cents
        elif reward_status == "dispatched":
            allocated += cents
            settled += cents
    return {
        "settlement_id": settlement_id,
        "status": status,
        "layer": layer,
        "allocated_cents": allocated,
        "blocked_cents": blocked,
        "releasable_cents": releasable,
        "settled_cents": settled,
        "reversed_cents": reversed_cents,
    }


def _public_share(raw: Dict[str, Any]) -> Dict[str, Any]:
    share = _public_acquisition(raw)
    share["layer"] = raw.get("layer")
    return share


def _viewer_referred(viewer_id: str, referee_id: str) -> bool:
    viewer_id = str(viewer_id or "")
    referee_id = str(referee_id or "")
    if not viewer_id or not referee_id:
        return False
    link = LINKS.get(referee_id)
    if isinstance(link, dict) and str(link.get("referrer_customer_id") or "") == viewer_id:
        return True
    rec = _customers().get(referee_id)
    return isinstance(rec, dict) and str(rec.get("referred_by") or "") == viewer_id


def _referred_row(customer_id: str, name: Any, referred_at: Any, code_used: Any,
                  viewer_id: str) -> Dict[str, Any]:
    measure = _public_acquisition(_measure_referee_cents(customer_id))
    share = _public_share(_viewer_share_cents(viewer_id, customer_id))
    return {
        "customer_id": customer_id,
        "name": name or _first_name(customer_id) or "PHINS Customer",
        "referred_at": referred_at,
        "code_used": str(code_used or ""),
        "reward_status": measure["status"],
        "acquisition": measure,
        "viewer_share": share,
    }


def _referred_acquisition_locked(referrer_customer_id: str, listed: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Direct referrals with the settlement the book actually holds.

    The stored invitation stats are not rewritten. Email and national ID
    are not copied onto the report.
    """
    referrer = str(referrer_customer_id or "")
    rows: List[Dict[str, Any]] = []
    seen = set()
    for entry in listed or []:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("customer_id") or "")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        rows.append(_referred_row(
            cid, entry.get("name"), entry.get("referred_at"), entry.get("code_used"), referrer,
        ))
    for referee, link in LINKS.items():
        if not isinstance(link, dict):
            continue
        if str(link.get("referrer_customer_id") or "") != referrer:
            continue
        cid = str(referee or "")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        rows.append(_referred_row(
            cid, link.get("referee_name"), link.get("joined_at"), link.get("invitation_code"), referrer,
        ))
    for cid, rec in _customers().items():
        if not isinstance(rec, dict):
            continue
        if str(rec.get("referred_by") or "") != referrer:
            continue
        key = str(cid or "")
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(_referred_row(key, rec.get("name"), None, "", referrer))
    share_rows = [{"acquisition": row.get("viewer_share") or {}} for row in rows]
    return {
        "referred_customers": rows,
        "acquisition_totals": _acquisition_totals(rows),
        "viewer_share_totals": _acquisition_totals(share_rows),
    }


def referred_acquisition(referrer_customer_id: str, listed: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Read acquisition for the customers this person referred.

    Does not refresh or persist the book. Callers that already hold the
    reward lock use ``_referred_acquisition_locked``.
    """
    with _LOCK:
        _ensure_loaded()
        return _referred_acquisition_locked(referrer_customer_id, listed or [])


def acquisition_for_customers(customer_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Read each customer's stored settlement. Do not refresh or persist it."""
    with _LOCK:
        _ensure_loaded()
        found: Dict[str, Dict[str, Any]] = {}
        for customer_id in customer_ids:
            key = str(customer_id or "")
            if not key or key in found:
                continue
            found[key] = _public_acquisition(_measure_referee_cents(key))
        return found


def network_acquisition(viewer_customer_id: str, customer_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """The agent's own layer, and only for customers that agent referred.

    A customer this agent did not refer contributes no acquisition dollars.
    The full multi-layer settlement is not attached. This read does not
    refresh or persist the book.
    """
    with _LOCK:
        _ensure_loaded()
        viewer = str(viewer_customer_id or "")
        found: Dict[str, Dict[str, Any]] = {}
        for customer_id in customer_ids:
            key = str(customer_id or "")
            if not key or key in found:
                continue
            if viewer and _viewer_referred(viewer, key):
                found[key] = _public_share(_viewer_share_cents(viewer, key))
            else:
                found[key] = _empty_acquisition()
        return found


def _plan_locked() -> Dict[str, Any]:
    """Affiliated-customer CAC plan: what is booked, blocked, and still conditional.

    Totals stay on the global settlement and reward loops. A per-customer
    report does not replace them.
    """
    allocated = blocked = releasable = settled = reversed_cents = projected = 0
    referees = set(LINKS) | set(SETTLEMENTS)
    paying = sum(1 for referee in referees if _is_paying(referee))
    for settlement in SETTLEMENTS.values():
        cents = int(settlement.get("allocated_cents") or 0)
        status = settlement.get("status")
        if status == "reversed":
            reversed_cents += cents
            continue
        allocated += cents
        if status == "settled":
            settled += cents
    for reward in REWARDS.values():
        cents = int(reward.get("amount_cents") or 0)
        if reward.get("status") == "held":
            blocked += cents
            if _is_paying(str(reward.get("referee_customer_id") or "")):
                projected += cents
        elif reward.get("status") == "earned":
            releasable += cents
    cfg = CONFIG or default_config()
    fee = int(cfg.get("fee_cents") or 0)
    program = config_to_admin(cfg)
    live = [reward for reward in REWARDS.values() if reward.get("status") != "forfeited"]
    by_dest = {dest: 0 for dest in DESTINATIONS}
    for reward in live:
        if reward.get("status") != "dispatched":
            continue
        allocation = reward.get("allocation") or {}
        cents = int(reward.get("amount_cents") or 0)
        if not allocation or cents <= 0:
            continue
        weights = [int(allocation.get(dest) or 0) for dest in DESTINATIONS]
        if sum(weights) != 10000:
            continue
        parts = allocate_cents(cents, weights)
        for dest, part in zip(DESTINATIONS, parts):
            by_dest[dest] += part
    rows = [_book_row(reward) for reward in REWARDS.values()]
    rows.sort(key=lambda item: ((item.get("release_at") or ""), item.get("reward_id") or ""), reverse=True)
    return {
        "affiliated_customers": len(referees),
        "paying": paying,
        "hold_months": int(cfg.get("hold_months", 3)),
        "settlements": len(SETTLEMENTS),
        "allocated": dollars(allocated),
        "blocked": dollars(blocked),
        "releasable": dollars(releasable),
        "settled": dollars(settled),
        "reversed": dollars(reversed_cents),
        "projected_release": dollars(projected),
        "per_paying_customer": dollars(fee),
        "fee_cents": fee,
        "fee_mode": program["fee_mode"],
        "fee": program["fee"],
        "premium_percent": program["premium_percent"],
        "schedule": [
            {"layer": item["layer"], "amount": item["amount"], "amount_cents": item["amount_cents"]}
            for item in program["layers"]
        ],
        "preview": program["preview"],
        "by_layer": _layer_buckets(live),
        "by_destination": {key: dollars(val) for key, val in by_dest.items()},
        "rows": rows,
        "surfaces": {
            "billing": "/billing.html",
            "health_wallet": "/dashboard.html#health-wallet",
            "investments": "/savings-portfolio.html",
            "plan": "/actuary-dashboard.html#cac-hold-card",
        },
    }


def affiliated_cac_plan() -> Dict[str, Any]:
    """Planning view of acquisition cost across affiliated customers."""
    with _LOCK:
        _ensure_loaded()
        _refresh_all_locked()
        return _plan_locked()


def book_summary() -> Dict[str, Any]:
    """Admin view: the acquisition expense, where it went, and whether it ties."""
    with _LOCK:
        _ensure_loaded()
        _refresh_all_locked()
        integrity = verify_integrity()
        by_layer = {str(n): {"count": 0, "amount_cents": 0} for n in LAYERS}
        by_dest = {dest: 0 for dest in DESTINATIONS}
        earned = dispatched = blocked = 0
        for reward in REWARDS.values():
            if reward.get("status") == "forfeited":
                continue
            cents = int(reward.get("amount_cents") or 0)
            earned += cents
            slot = by_layer.get(str(reward.get("layer")))
            if slot is not None:
                slot["count"] += 1
                slot["amount_cents"] += cents
            if reward.get("status") == "held":
                blocked += cents
            if reward.get("status") == "dispatched":
                dispatched += cents
                allocation = reward.get("allocation") or {}
                if allocation:
                    parts = allocate_cents(cents, [int(allocation.get(d) or 0) for d in DESTINATIONS])
                    for dest, part in zip(DESTINATIONS, parts):
                        by_dest[dest] += part
        retained = 0
        referees = {r["referee_customer_id"] for r in REWARDS.values()}
        for referee in referees:
            sample = next(r for r in REWARDS.values() if r["referee_customer_id"] == referee)
            retained += int(sample.get("fee_cents") or 0) - sum(
                int(r.get("amount_cents") or 0) for r in REWARDS.values()
                if r["referee_customer_id"] == referee
            )
        requests = list(REQUESTS.values())
        portal = _portal()
        sheet = getattr(portal, "PHINS_BALANCE_SHEET", {}) if portal else {}
        booked = 0.0
        if isinstance(sheet, dict):
            booked = float((sheet.get("expense_breakdown") or {}).get("customer_acquisition") or 0)
        return {
            "config": config_to_admin(),
            "totals": {
                "joined": len(LINKS),
                "paying": sum(1 for link in LINKS.values() if link.get("paying_at")),
                "rewards": len(REWARDS),
                "earned": dollars(earned),
                "blocked": dollars(blocked),
                "dispatched": dollars(dispatched),
                "pending_choice": dollars(earned - dispatched - blocked),
                "retained": dollars(retained),
                "expense_booked": round(booked, 2),
                "by_layer": {
                    key: {"count": val["count"], "amount": dollars(val["amount_cents"])}
                    for key, val in by_layer.items()
                },
                "by_destination": {key: dollars(val) for key, val in by_dest.items()},
            },
            "professional_requests": {
                "inquiry": sum(1 for item in requests if item.get("status") == "inquiry"),
                "pending": sum(1 for item in requests if item.get("status") == "pending"),
                "approved": sum(1 for item in requests if item.get("status") == "approved"),
                "rejected": sum(1 for item in requests if item.get("status") == "rejected"),
            },
            "integrity": integrity,
            "affiliated_plan": _plan_locked(),
            "quarantine": list(QUARANTINE),
            "flags": dict(FLAGS),
        }


def verify_integrity() -> Dict[str, Any]:
    """Recompute the book. ``ok`` is false when a cent does not tie out."""
    issues: List[Dict[str, str]] = []
    seen: Dict[Tuple[str, int], str] = {}
    expected_expense = 0
    for reward in REWARDS.values():
        if not _reward_intact(reward):
            issues.append({"code": "checksum", "detail": reward.get("id") or ""})
            continue
        key = (str(reward.get("referee_customer_id")), int(reward.get("layer") or 0))
        if key in seen:
            issues.append({"code": "duplicate_layer", "detail": reward["id"]})
        seen[key] = reward["id"]
        if reward.get("beneficiary_customer_id") == reward.get("referee_customer_id"):
            issues.append({"code": "self_reward", "detail": reward["id"]})
        if int(reward.get("layer") or 0) not in LAYERS:
            issues.append({"code": "bad_layer", "detail": reward["id"]})
        policy = reward.get("policy") or {}
        if policy.get("allocation_method") == "waterfall":
            try:
                expected_rows = waterfall_amounts(
                    int(reward.get("fee_cents") or 0),
                    policy.get("schedule_cents") or [],
                    policy.get("filled_layers") or [],
                )
            except RewardError:
                issues.append({"code": "schedule", "detail": reward["id"]})
            else:
                layer_no = int(reward.get("layer") or 0)
                expected = expected_rows[layer_no - 1] if layer_no in LAYERS else -1
                if expected != int(reward.get("amount_cents") or 0):
                    issues.append({"code": "amount_drift", "detail": reward["id"]})
                filled = [int(item) for item in (policy.get("filled_layers") or [])]
                if layer_no not in filled:
                    issues.append({"code": "filled_layers", "detail": reward["id"]})
        else:
            shares = [int(x) for x in (reward.get("program_shares") or [])]
            if len(shares) == 3 and sum(shares) == 10000:
                expected = allocate_cents(int(reward.get("fee_cents") or 0), shares)[int(reward["layer"]) - 1]
                if expected != int(reward.get("amount_cents") or 0):
                    issues.append({"code": "amount_drift", "detail": reward["id"]})
            else:
                issues.append({"code": "shares", "detail": reward["id"]})
        status = reward.get("status")
        if status == "forfeited":
            posted = reward.get("posted") or {}
            if posted:
                issues.append({"code": "forfeited_posted", "detail": reward["id"]})
        else:
            expected_expense += int(reward.get("amount_cents") or 0)
        if status == "dispatched":
            allocation = reward.get("allocation") or {}
            if sum(int(allocation.get(d) or 0) for d in DESTINATIONS) != 10000:
                issues.append({"code": "allocation", "detail": reward["id"]})
            else:
                parts = allocate_cents(int(reward["amount_cents"]), [int(allocation.get(d) or 0) for d in DESTINATIONS])
                posted = reward.get("posted") or {}
                for dest, cents in zip(DESTINATIONS, parts):
                    if cents > 0 and dest not in posted:
                        issues.append({"code": "missing_leg", "detail": f"{reward['id']}:{dest}"})
                    if cents == 0 and dest in posted:
                        issues.append({"code": "extra_leg", "detail": f"{reward['id']}:{dest}"})
        elif status == "held":
            if reward.get("posted"):
                issues.append({"code": "held_posted", "detail": reward["id"]})
        elif status not in ("earned", "forfeited"):
            issues.append({"code": "bad_status", "detail": reward["id"]})
        if reward.get("settlement_id"):
            settlement = SETTLEMENTS.get(str(reward.get("referee_customer_id")))
            if settlement is None or settlement.get("id") != reward.get("settlement_id"):
                issues.append({"code": "settlement_missing", "detail": reward["id"]})
    # One fee per paying referee: paid layers + retained == snapshotted fee.
    by_referee: Dict[str, List[Dict[str, Any]]] = {}
    for reward in REWARDS.values():
        by_referee.setdefault(str(reward["referee_customer_id"]), []).append(reward)
    for referee, group in by_referee.items():
        fee = int(group[0].get("fee_cents") or 0)
        paid = sum(int(item.get("amount_cents") or 0) for item in group)
        if any(int(item.get("fee_cents") or 0) != fee for item in group):
            issues.append({"code": "fee_snapshot_mismatch", "detail": referee})
        waterfall_group = [item for item in group if (item.get("policy") or {}).get("allocation_method") == "waterfall"]
        if waterfall_group and len(waterfall_group) != len(group):
            issues.append({"code": "schedule_mismatch", "detail": referee})
        elif waterfall_group:
            first = waterfall_group[0].get("policy") or {}
            signature = (
                list(first.get("schedule_cents") or []),
                list(first.get("filled_layers") or []),
                first.get("fee_mode"),
            )
            for item in waterfall_group[1:]:
                policy = item.get("policy") or {}
                other = (
                    list(policy.get("schedule_cents") or []),
                    list(policy.get("filled_layers") or []),
                    policy.get("fee_mode"),
                )
                if other != signature:
                    issues.append({"code": "schedule_mismatch", "detail": referee})
                    break
            else:
                try:
                    expected_rows = waterfall_amounts(fee, signature[0], signature[1])
                except RewardError:
                    issues.append({"code": "schedule", "detail": referee})
                else:
                    present = {int(item.get("layer") or 0) for item in group}
                    for layer_no, cents in enumerate(expected_rows, start=1):
                        if cents > 0 and layer_no not in present:
                            issues.append({"code": "missing_layer", "detail": f"{referee}:L{layer_no}"})
        if paid > fee:
            issues.append({"code": "over_fee", "detail": referee})
        settlement = SETTLEMENTS.get(referee)
        live = [item for item in group if item.get("status") != "forfeited"]
        if settlement is None:
            if any(item.get("settlement_id") for item in group):
                issues.append({"code": "settlement_missing", "detail": referee})
        else:
            if not _settlement_intact(settlement):
                issues.append({"code": "settlement_checksum", "detail": settlement.get("id") or referee})
            else:
                live_cents = sum(int(item.get("amount_cents") or 0) for item in live)
                if settlement.get("status") == "reversed":
                    if live_cents:
                        issues.append({"code": "reversed_still_live", "detail": referee})
                    if not settlement.get("reversal_tx_id"):
                        issues.append({"code": "reversal_missing", "detail": referee})
                elif int(settlement.get("allocated_cents") or 0) != sum(int(item.get("amount_cents") or 0) for item in group):
                    issues.append({"code": "settlement_amount", "detail": referee})
                if int(settlement.get("allocated_cents") or 0) + int(settlement.get("retained_cents") or 0) != int(settlement.get("fee_cents") or 0):
                    issues.append({"code": "settlement_fee", "detail": referee})
                if settlement.get("status") == "settled" and any(item.get("status") != "dispatched" for item in group):
                    issues.append({"code": "settled_open", "detail": referee})
    for referee, settlement in SETTLEMENTS.items():
        if referee not in by_referee and not settlement.get("_quarantined"):
            issues.append({"code": "orphan_settlement", "detail": settlement.get("id") or referee})
    portal = _portal()
    sheet = getattr(portal, "PHINS_BALANCE_SHEET", None) if portal else None
    if isinstance(sheet, dict):
        booked_cents = int(round(float((sheet.get("expense_breakdown") or {}).get("customer_acquisition") or 0) * 100))
        tx_cents = 0
        settlement_hits: Dict[str, int] = {}
        for tx in sheet.get("transactions") or []:
            if not isinstance(tx, dict):
                continue
            meta = tx.get("metadata") if isinstance(tx.get("metadata"), dict) else {}
            kind = meta.get("kind")
            if kind in ("cac_reward", "cac_settlement", "cac_settlement_reversal") and tx.get("category") == "customer_acquisition":
                tx_cents += int(round(float(tx.get("amount") or 0) * 100))
                if kind == "cac_settlement" and meta.get("settlement_id"):
                    key = str(meta["settlement_id"])
                    settlement_hits[key] = settlement_hits.get(key, 0) + 1
        for settlement_id, hits in settlement_hits.items():
            if hits != 1:
                issues.append({"code": "duplicate_settlement_expense", "detail": settlement_id})
        for settlement in SETTLEMENTS.values():
            if settlement.get("_quarantined") or settlement.get("status") == "reversed":
                continue
            if settlement["id"] not in settlement_hits:
                issues.append({"code": "books_missing", "detail": settlement["id"]})
        if tx_cents != expected_expense:
            issues.append({"code": "books_vs_rewards", "detail": f"transactions={tx_cents} rewards={expected_expense}"})
        if booked_cents != tx_cents:
            issues.append({"code": "books_counter", "detail": f"counter={booked_cents} transactions={tx_cents}"})
    for flag in FLAGS:
        issues.append({"code": flag, "detail": "state was not applied"})
    if QUARANTINE:
        issues.append({"code": "quarantine", "detail": str(len(QUARANTINE))})
    return {"ok": not issues, "issues": issues, "rewards": len(REWARDS), "expense_cents": expected_expense}


def recent_rewards(limit: int = 20) -> List[Dict[str, Any]]:
    with _LOCK:
        _ensure_loaded()
        rows = sorted(REWARDS.values(), key=lambda item: item.get("earned_at") or "", reverse=True)
        return [public_reward(item) for item in rows[: max(0, int(limit))]]


# Validate the shipped default so a bad edit fails at import, not at payout.
CONFIG.update(_validate_config(default_config()))
