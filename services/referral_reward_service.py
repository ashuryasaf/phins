"""Referral acquisition-reward book.

A new customer who registers with another customer's invitation code is an
edge in a chain. When that customer pays a premium bill, PHINS recognizes a
fixed customer-acquisition fee (the admin default is $650) and splits it
across up to three referrers above them. The fee is an expense on the general
reserves the moment it is earned. It is not moved into a personal balance
until the referrer accepts it and chooses a destination the program allows
for that layer: premium credit, health wallet, savings, or cash.

The fee does not grow with the premium and it does not continue past the
third layer, so the cost of acquiring one paying customer is capped and known
before the invitation goes out. A layer with nobody standing on it is retained
by the company and is not expensed. Agent commission (a percentage of premium,
locked per affiliation) is a different rail and is not paid again here.

Amounts are integer cents. The layer split uses the largest-remainder method
so the three shares plus the retained remainder equal the fee exactly, and a
later change to the program never rewrites a reward that was already earned.
Every reward id is ``RWRD-{referee}-L{layer}``, so the same paying customer
cannot fund a layer twice. The durable copy is a checksummed JSON file when
the portal is in memory, and the ``referral_rewards`` tables when the
database is on. A checksum that does not match is quarantined and never paid.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DESTINATIONS: Tuple[str, ...] = ("premium", "health_wallet", "savings", "cash")
LAYERS = (1, 2, 3)
_LOCK = threading.RLock()
_STATE_ENV = "PHINS_REFERRAL_REWARDS_PATH"

CONFIG: Dict[str, Any] = {}
LINKS: Dict[str, Dict[str, Any]] = {}          # referee_customer_id -> link
REWARDS: Dict[str, Dict[str, Any]] = {}        # reward id -> reward
REQUESTS: Dict[str, Dict[str, Any]] = {}       # request id -> professional request
QUARANTINE: List[Dict[str, Any]] = []
FLAGS: Dict[str, Any] = {}

_loaded = False
_CHECK_FIELDS = (
    "id", "referee_customer_id", "beneficiary_customer_id", "layer", "status",
    "fee_cents", "share_bps", "amount_cents", "currency", "program_shares",
    "policy", "allocation", "posted", "books_tx_id", "ledger_entry_id",
    "earned_at", "dispatched_at",
)


class RewardError(ValueError):
    """A reward or program change the caller can correct."""

    def __init__(self, message: str, status: int = 400, code: str = "reward_error"):
        super().__init__(message)
        self.status = status
        self.code = code

    def to_dict(self) -> Dict[str, Any]:
        return {"error": str(self), "code": self.code}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def default_config() -> Dict[str, Any]:
    """$650, paid 60% / 25% / 15% across the three layers above the new customer.

    Layer 1 may take cash. Layers 2 and 3 stay inside the platform (premium,
    health wallet, savings) unless an admin opens cash for them. The default
    split is a suggestion; the referrer chooses at acceptance.
    """
    return {
        "version": 1,
        "enabled": True,
        "currency": "USD",
        "fee_cents": 65000,
        "max_layers": 3,
        "customer_invitation_cap": 10,
        "agent_invitation_cap": 100,
        "agent_default_rate_percent": 10,
        "auto_dispatch": False,
        "layers": [
            {
                "layer": 1,
                "share_bps": 6000,
                "allowed": ["premium", "health_wallet", "savings", "cash"],
                "cash_cap_bps": 10000,
                "default_bps": {"premium": 0, "health_wallet": 5000, "savings": 5000, "cash": 0},
            },
            {
                "layer": 2,
                "share_bps": 2500,
                "allowed": ["premium", "health_wallet", "savings"],
                "cash_cap_bps": 0,
                "default_bps": {"premium": 4000, "health_wallet": 3000, "savings": 3000, "cash": 0},
            },
            {
                "layer": 3,
                "share_bps": 1500,
                "allowed": ["premium", "health_wallet", "savings"],
                "cash_cap_bps": 0,
                "default_bps": {"premium": 10000, "health_wallet": 0, "savings": 0, "cash": 0},
            },
        ],
    }


def _blank_bps() -> Dict[str, int]:
    return {dest: 0 for dest in DESTINATIONS}


def _validate_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise RewardError("Program config must be an object")
    fee = int(raw.get("fee_cents") or 0)
    if fee < 0 or fee > 10_000_000:
        raise RewardError("Fee must be between $0 and $100,000")
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
            "share_bps": int(item.get("share_bps") or 0),
            "allowed": allowed,
            "cash_cap_bps": cash_cap,
            "default_bps": default,
        }
    shares = [by_layer[n]["share_bps"] for n in LAYERS]
    if any(s < 0 or s > 10000 for s in shares) or sum(shares) != 10000:
        raise RewardError("Layer shares must be non-negative and add up to 100%")
    return {
        "version": int(raw.get("version") or 1),
        "enabled": bool(raw.get("enabled", True)),
        "currency": "USD",
        "fee_cents": fee,
        "max_layers": max_layers,
        "customer_invitation_cap": customer_cap,
        "agent_invitation_cap": agent_cap,
        "agent_default_rate_percent": rate,
        "auto_dispatch": bool(raw.get("auto_dispatch", False)),
        "layers": [by_layer[n] for n in LAYERS],
    }


def _layer_policy(cfg: Dict[str, Any], layer: int) -> Dict[str, Any]:
    for item in cfg["layers"]:
        if int(item["layer"]) == int(layer):
            return item
    raise RewardError(f"Layer {layer} is not in the program")


def config_to_admin(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or CONFIG or default_config()
    return {
        "version": cfg["version"],
        "enabled": cfg["enabled"],
        "currency": cfg["currency"],
        "fee": dollars(cfg["fee_cents"]),
        "fee_cents": cfg["fee_cents"],
        "max_layers": cfg["max_layers"],
        "customer_invitation_cap": cfg["customer_invitation_cap"],
        "agent_invitation_cap": cfg["agent_invitation_cap"],
        "agent_default_rate_percent": cfg["agent_default_rate_percent"],
        "auto_dispatch": cfg["auto_dispatch"],
        "layers": [
            {
                "layer": item["layer"],
                "share_percent": bps_to_percent(item["share_bps"]),
                "amount": dollars(allocate_cents(cfg["fee_cents"], [i["share_bps"] for i in cfg["layers"]])[item["layer"] - 1]),
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
    for key in ("enabled", "max_layers", "customer_invitation_cap", "agent_invitation_cap",
                "agent_default_rate_percent", "auto_dispatch"):
        if key in raw and raw[key] is not None:
            base[key] = raw[key]
    if raw.get("fee") is not None:
        base["fee"] = raw["fee"]
    elif raw.get("fee_cents") is not None:
        base["fee"] = dollars(int(raw["fee_cents"]))
    if isinstance(raw.get("layers"), list):
        by = {int(item["layer"]): dict(item) for item in base["layers"]}
        for patch in raw["layers"]:
            if not isinstance(patch, dict) or "layer" not in patch:
                raise RewardError("Each layer patch needs a layer number")
            layer = int(patch["layer"])
            current = dict(by.get(layer) or {"layer": layer})
            for key in ("share_percent", "allowed", "cash_cap_percent"):
                if key in patch and patch[key] is not None:
                    current[key] = patch[key]
            if isinstance(patch.get("default"), dict):
                merged_default = dict(current.get("default") or {})
                merged_default.update(patch["default"])
                current["default"] = merged_default
            by[layer] = current
        base["layers"] = [by[n] for n in LAYERS]
    layers = []
    for item in base["layers"]:
        default = item.get("default") or {}
        layers.append({
            "layer": int(item["layer"]),
            "share_bps": percent_to_bps(item.get("share_percent", 0)),
            "allowed": list(item.get("allowed") or []),
            "cash_cap_bps": percent_to_bps(item.get("cash_cap_percent", 0)),
            "default_bps": {dest: percent_to_bps(default.get(dest, 0)) for dest in DESTINATIONS},
        })
    return _validate_config({
        "version": int(previous.get("version") or 1),
        "enabled": base["enabled"],
        "fee_cents": cents_from_dollars(base["fee"]),
        "max_layers": base["max_layers"],
        "customer_invitation_cap": base["customer_invitation_cap"],
        "agent_invitation_cap": base["agent_invitation_cap"],
        "agent_default_rate_percent": base["agent_default_rate_percent"],
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
    return _sha({key: reward.get(key) for key in _CHECK_FIELDS})


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
    for req in state.get("requests") or []:
        if isinstance(req, dict) and req.get("id"):
            REQUESTS[str(req["id"])] = req


def _hydrate_db() -> None:
    try:
        with _repo() as db:
            stored = db.referral_rewards.get_config()
            links = db.referral_rewards.list_links()
            rewards = db.referral_rewards.list_rewards()
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
    for req in requests:
        REQUESTS[str(req["id"])] = req


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    CONFIG.clear()
    CONFIG.update(default_config())
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
        CONFIG.update(default_config())
        LINKS.clear()
        REWARDS.clear()
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


def _book_expense(reward: Dict[str, Any]) -> Optional[str]:
    """Recognize the CAC expense once. A retry finds the existing entry."""
    portal = _portal()
    if portal is None or not hasattr(portal, "record_balance_sheet_transaction"):
        return None
    sheet = getattr(portal, "PHINS_BALANCE_SHEET", None)
    if isinstance(sheet, dict):
        breakdown = sheet.setdefault("expense_breakdown", {})
        if isinstance(breakdown, dict):
            breakdown.setdefault("customer_acquisition", 0.0)
        for tx in sheet.get("transactions") or []:
            meta = tx.get("metadata") if isinstance(tx, dict) else None
            if isinstance(meta, dict) and meta.get("reward_id") == reward["id"] and meta.get("kind") == "cac_reward":
                return str(tx.get("tx_id") or "")
    posted = portal.record_balance_sheet_transaction(
        tx_type="expense",
        category="customer_acquisition",
        amount=dollars(reward["amount_cents"]),
        description=f"Referral acquisition reward {reward['id']} layer {reward['layer']}",
        actor="referral_rewards",
        customer_id=reward["beneficiary_customer_id"],
        metadata={
            "reward_id": reward["id"],
            "kind": "cac_reward",
            "referee_customer_id": reward["referee_customer_id"],
            "layer": reward["layer"],
            "fee_cents": reward["fee_cents"],
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


def _policy_snapshot(cfg: Dict[str, Any], layer: int) -> Dict[str, Any]:
    item = _layer_policy(cfg, layer)
    return {
        "allowed": list(item["allowed"]),
        "cash_cap_bps": int(item["cash_cap_bps"]),
        "default_bps": dict(item["default_bps"]),
    }


def on_customer_paying(customer_id: str, billing: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Earn one reward per referrer layer once this customer has a paid premium.

    Idempotent. A second call, a second bill, or a second app instance finds
    the same ids and does not book the expense again.
    """
    referee = str(customer_id or "").strip()
    if not referee:
        return []
    created: List[Dict[str, Any]] = []
    with _LOCK:
        _ensure_loaded()
        if not CONFIG.get("enabled", True):
            return []
        if not _is_paying(referee, billing):
            return []
        customers = _customers()
        if referee not in customers and referee not in LINKS:
            return []
        cfg = CONFIG
        shares = [int(item["share_bps"]) for item in cfg["layers"]]
        amounts = allocate_cents(int(cfg["fee_cents"]), shares)
        found = chain_of(referee, customers, cfg["max_layers"])
        link = LINKS.get(referee)
        if link is not None and not link.get("paying_at"):
            link["paying_at"] = _now()
            _persist_link(link)
        for layer, beneficiary in found:
            reward_id = f"RWRD-{referee}-L{layer}"
            existing = REWARDS.get(reward_id)
            if existing is not None:
                continue
            amount = amounts[layer - 1]
            if amount <= 0 or beneficiary == referee:
                continue
            direct = found[0][1] if found else ""
            code = ""
            if link and str(link.get("referrer_customer_id")) == str(direct):
                code = str(link.get("invitation_code") or "")
            reward = {
                "id": reward_id,
                "referee_customer_id": referee,
                "beneficiary_customer_id": beneficiary,
                "layer": layer,
                "invitation_code": code if layer == 1 else "",
                "status": "earned",
                "fee_cents": int(cfg["fee_cents"]),
                "share_bps": shares[layer - 1],
                "amount_cents": amount,
                "currency": "USD",
                "program_shares": shares,
                "policy": _policy_snapshot(cfg, layer),
                "allocation": None,
                "posted": {},
                "books_tx_id": None,
                "ledger_entry_id": None,
                "earned_at": _now(),
                "dispatched_at": None,
            }
            _seal(reward)
            REWARDS[reward_id] = reward
            try:
                reward["books_tx_id"] = _book_expense(reward)
                reward["ledger_entry_id"] = _anchor(reward, "referral.reward.earned", "CAC")
                _persist_reward(reward)
            except Exception:
                REWARDS.pop(reward_id, None)
                raise
            _sync_stats(reward)
            created.append(reward)
            if cfg.get("auto_dispatch"):
                try:
                    _dispatch_locked(reward, None)
                except RewardError as exc:
                    reward["dispatch_error"] = str(exc)
                    _persist_reward(reward)
    for reward in created:
        if reward.get("status") == "dispatched":
            continue
        _deliver(
            reward["beneficiary_customer_id"],
            f"You earned {dollars(reward['amount_cents']):.2f} USD from a PHINS invitation",
            f"A customer in your invitation chain started paying. "
            f"Layer {reward['layer']} of your acquisition reward is "
            f"${dollars(reward['amount_cents']):.2f}. Open Referrals and choose "
            "premium credit, health wallet, savings, or cash.",
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
        if _is_paying(str(customer_id), billing):
            earned += len(on_customer_paying(str(customer_id), billing))
    anchored = _backfill_anchors()
    return {"links_recorded": joined, "rewards_created": earned, "anchors_written": anchored}


def _backfill_anchors() -> int:
    written = 0
    with _LOCK:
        _ensure_loaded()
        for reward in list(REWARDS.values()):
            if reward.get("ledger_entry_id"):
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


def _dispatch_locked(reward: Dict[str, Any], raw_allocation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if reward.get("status") == "dispatched":
        return reward
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
            and reward.get("status") == "earned"
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
# Professional roles (agent / supplier) on the same person
# ---------------------------------------------------------------------------
def _request_id(customer_id: str, role: str) -> str:
    return f"PRO-{customer_id}-{role}"


def request_professional(customer_id: str, role: str, login_username: str = "",
                         supplier_type: str = "", company_name: str = "",
                         note: str = "") -> Dict[str, Any]:
    role = str(role or "").strip().lower()
    if role not in ("agent", "supplier"):
        raise RewardError("Role must be agent or supplier")
    customer_id = str(customer_id or "").strip()
    if not customer_id:
        raise RewardError("Customer is required", status=400, code="customer_required")
    supplier_type = str(supplier_type or "").strip().lower()
    company_name = str(company_name or "").strip()
    if role == "supplier":
        if supplier_type not in supplier_type_values():
            raise RewardError("Choose a supplier type such as clinic, pharmacy, or wellness")
        if len(company_name) < 2:
            raise RewardError("A supplier request needs a practice or company name")
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
            "status": "pending",
            "supplier_type": supplier_type if role == "supplier" else None,
            "company_name": company_name[:160] if role == "supplier" else None,
            "note": str(note or "")[:500],
            "agent_id": None,
            "supplier_id": None,
            "invitation_code": None,
            "reviewed_by": None,
            "reviewed_at": None,
            "review_note": None,
            "created_at": (existing or {}).get("created_at") or _now(),
            "updated_at": _now(),
        }
        REQUESTS[key] = req
        _persist_request(req)
        return dict(req)


def _open_agent(req: Dict[str, Any]) -> Dict[str, Any]:
    from services.agent_ecosystem_service import create_agent
    rec = _customer_record(req["customer_id"]) or {}
    username = req.get("login_username") or rec.get("email") or req["customer_id"]
    agent = create_agent(
        username=str(username),
        display_name=str(rec.get("name") or username),
        email=str(rec.get("email") or ""),
        default_rate=int(CONFIG.get("agent_default_rate_percent") or 0),
        created_by="referral_rewards",
    )
    if isinstance(rec, dict):
        rec["agent_id"] = agent.get("id")
    return agent


def _open_supplier(req: Dict[str, Any], admin: str) -> Dict[str, Any]:
    portal = _portal()
    service = getattr(portal, "supply_chain_service", None) if portal else None
    if service is None:
        raise RewardError("Supplier service is unavailable", status=503, code="supplier_unavailable")
    rec = _customer_record(req["customer_id"]) or {}
    issued = service.generate_invitation_code(
        created_by=admin or "admin",
        supplier_type=req.get("supplier_type"),
        max_uses=1,
        expires_days=90,
        referrer_id=req["customer_id"],
        notes=f"Professional request {req['id']}",
    )
    code = ((issued or {}).get("invitation") or {}).get("code")
    if not code:
        raise RewardError("Could not issue a supplier invitation", code="supplier_invite_failed")
    registered = service.register_supplier({
        "invitation_code": code,
        "company_name": req.get("company_name") or "PHINS Professional",
        "contact_email": rec.get("email") or f"{req['customer_id'].lower()}@phins.local",
        "contact_name": rec.get("name") or "PHINS Customer",
        "contact_phone": rec.get("phone") or "",
        "supplier_type": req.get("supplier_type"),
        "password": secrets.token_urlsafe(24),
        "description": "Opened from a PHINS customer professional request",
    })
    supplier_id = (registered or {}).get("supplier_id")
    if not supplier_id:
        raise RewardError("Supplier registration did not return an id", code="supplier_failed")
    service.approve_supplier(supplier_id, admin or "admin", notes=f"Approved with {req['id']}")
    supplier = service.suppliers.get(supplier_id)
    if isinstance(supplier, dict):
        supplier["customer_id"] = req["customer_id"]
        supplier["portal_active"] = True
    if isinstance(rec, dict):
        rec["supplier_id"] = supplier_id
    req["invitation_code"] = code
    return {"id": supplier_id}


def review_professional(request_id: str, decision: str, admin: str, note: str = "") -> Dict[str, Any]:
    decision = str(decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise RewardError("Decision must be approve or reject")
    with _LOCK:
        _ensure_loaded()
        req = REQUESTS.get(str(request_id or ""))
        if req is None:
            raise RewardError("Request not found", status=404, code="not_found")
        if req.get("status") != "pending":
            raise RewardError(f"Request is already {req.get('status')}", status=409, code="not_pending")
        if decision == "approve":
            try:
                if req["requested_role"] == "agent":
                    agent = _open_agent(req)
                    req["agent_id"] = agent.get("id")
                else:
                    supplier = _open_supplier(req, admin)
                    req["supplier_id"] = supplier.get("id")
            except RewardError:
                raise
            except Exception as exc:
                raise RewardError(str(exc), status=400, code="professional_open_failed") from exc
            req["status"] = "approved"
        else:
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
        return dict(req)


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
    with _LOCK:
        _ensure_loaded()
        out = {}
        for role in ("agent", "supplier"):
            req = REQUESTS.get(_request_id(customer_id, role))
            out[role] = dict(req) if req else {"status": "none", "requested_role": role}
        return out


def grant_for(customer_id: str, role: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        _ensure_loaded()
        return dict(_approved_request(customer_id, role) or {}) or None


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def public_reward(reward: Dict[str, Any]) -> Dict[str, Any]:
    policy = reward.get("policy") or {}
    allocation = reward.get("allocation") or {}
    return {
        "id": reward["id"],
        "layer": reward["layer"],
        "status": reward["status"],
        "amount": dollars(reward["amount_cents"]),
        "amount_cents": reward["amount_cents"],
        "currency": reward.get("currency") or "USD",
        "referee_customer_id": reward["referee_customer_id"],
        "referee_name": _first_name(reward["referee_customer_id"]),
        "earned_at": reward.get("earned_at"),
        "dispatched_at": reward.get("dispatched_at"),
        "allowed": list(policy.get("allowed") or []),
        "cash_cap_percent": bps_to_percent(int(policy.get("cash_cap_bps") or 0)),
        "default": {k: bps_to_percent(v) for k, v in (policy.get("default_bps") or {}).items()},
        "allocation": {k: bps_to_percent(v) for k, v in allocation.items()} if allocation else None,
        "posted": sorted((reward.get("posted") or {}).keys()),
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
        customer_id = str(customer_id or "")
        rewards = [
            public_reward(reward) for reward in REWARDS.values()
            if str(reward.get("beneficiary_customer_id")) == customer_id
        ]
        rewards.sort(key=lambda item: item.get("earned_at") or "", reverse=True)
        outgoing = [link for link in LINKS.values() if str(link.get("referrer_customer_id")) == customer_id]
        earned = sum(int(r["amount_cents"]) for r in REWARDS.values()
                     if str(r.get("beneficiary_customer_id")) == customer_id)
        dispatched = sum(int(r["amount_cents"]) for r in REWARDS.values()
                         if str(r.get("beneficiary_customer_id")) == customer_id and r.get("status") == "dispatched")
        program = config_to_admin()
        return {
            "enabled": bool(CONFIG.get("enabled", True)),
            "currency": "USD",
            "fee": program["fee"],
            "max_layers": program["max_layers"],
            "invitation_cap": invitation_cap_for(customer_id),
            "layers": program["layers"],
            "destinations": list(DESTINATIONS),
            "rewards": rewards,
            "totals": {
                "earned": dollars(earned),
                "dispatched": dollars(dispatched),
                "pending_choice": dollars(earned - dispatched),
                "count": len(rewards),
            },
            "direct_referrals": len(outgoing),
            "paying_referrals": sum(1 for link in outgoing if link.get("paying_at")),
            "professional": professional_status(customer_id),
            "supplier_types": supplier_type_values(),
            "tools": _tools(customer_id),
        }


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
            "version": updated["version"], "fee_cents": updated["fee_cents"], "by": updated_by,
        })
        return config_to_admin()


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
        return [dict(item) for item in items]


def book_summary() -> Dict[str, Any]:
    """Admin view: the acquisition expense, where it went, and whether it ties."""
    with _LOCK:
        _ensure_loaded()
        integrity = verify_integrity()
        by_layer = {str(n): {"count": 0, "amount_cents": 0} for n in LAYERS}
        by_dest = {dest: 0 for dest in DESTINATIONS}
        earned = dispatched = 0
        for reward in REWARDS.values():
            cents = int(reward.get("amount_cents") or 0)
            earned += cents
            slot = by_layer.get(str(reward.get("layer")))
            if slot is not None:
                slot["count"] += 1
                slot["amount_cents"] += cents
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
                "dispatched": dollars(dispatched),
                "pending_choice": dollars(earned - dispatched),
                "retained": dollars(retained),
                "expense_booked": round(booked, 2),
                "by_layer": {
                    key: {"count": val["count"], "amount": dollars(val["amount_cents"])}
                    for key, val in by_layer.items()
                },
                "by_destination": {key: dollars(val) for key, val in by_dest.items()},
            },
            "professional_requests": {
                "pending": sum(1 for item in requests if item.get("status") == "pending"),
                "approved": sum(1 for item in requests if item.get("status") == "approved"),
                "rejected": sum(1 for item in requests if item.get("status") == "rejected"),
            },
            "integrity": integrity,
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
        shares = [int(x) for x in (reward.get("program_shares") or [])]
        if len(shares) == 3 and sum(shares) == 10000:
            expected = allocate_cents(int(reward.get("fee_cents") or 0), shares)[int(reward["layer"]) - 1]
            if expected != int(reward.get("amount_cents") or 0):
                issues.append({"code": "amount_drift", "detail": reward["id"]})
        else:
            issues.append({"code": "shares", "detail": reward["id"]})
        expected_expense += int(reward.get("amount_cents") or 0)
        if reward.get("status") == "dispatched":
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
        elif reward.get("status") != "earned":
            issues.append({"code": "bad_status", "detail": reward["id"]})
    # One fee per paying referee: paid layers + retained == snapshotted fee.
    by_referee: Dict[str, List[Dict[str, Any]]] = {}
    for reward in REWARDS.values():
        by_referee.setdefault(str(reward["referee_customer_id"]), []).append(reward)
    for referee, group in by_referee.items():
        fee = int(group[0].get("fee_cents") or 0)
        paid = sum(int(item.get("amount_cents") or 0) for item in group)
        if any(int(item.get("fee_cents") or 0) != fee for item in group):
            issues.append({"code": "fee_snapshot_mismatch", "detail": referee})
        if paid > fee:
            issues.append({"code": "over_fee", "detail": referee})
    portal = _portal()
    sheet = getattr(portal, "PHINS_BALANCE_SHEET", None) if portal else None
    if isinstance(sheet, dict):
        booked_cents = int(round(float((sheet.get("expense_breakdown") or {}).get("customer_acquisition") or 0) * 100))
        tx_cents = 0
        for tx in sheet.get("transactions") or []:
            if not isinstance(tx, dict):
                continue
            meta = tx.get("metadata") if isinstance(tx.get("metadata"), dict) else {}
            if meta.get("kind") == "cac_reward" and tx.get("category") == "customer_acquisition":
                tx_cents += int(round(float(tx.get("amount") or 0) * 100))
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
_validate_config(default_config())
CONFIG.update(default_config())
