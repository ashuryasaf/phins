"""Books-tied daily certificate (ERP/MGA integrity U6).

Once per UTC day, after Money Gate critical checks are green, append a sealed
``finance.books_tied`` event to the platform ledger. The certificate is
evidence only — it never rewrites books. Money Gate may refuse high-value
moves when no intact certificate is younger than
``PHINS_BOOKS_TIED_MAX_AGE_HOURS`` (default 36). Prefer today's seal; a
prior-day seal still counts while it is within that age window (covers the
UTC midnight → daily-clock gap). Set ``PHINS_BOOKS_TIED_REQUIRE=0`` to skip
the freshness gate (certificate issue still runs).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Optional, Sequence

from services.erp.money_gate import MoneyGateVerdict, digest_for, evaluate_money_gate

EVENT_TYPE = 'finance.books_tied'
ENTITY_TYPE = 'books_tied'
CERT_MISSING = 'books_tied_certificate_missing'
CERT_STALE = 'books_tied_certificate_stale'
CERT_TAMPERED = 'books_tied_certificate_tampered'

# Operations that need a fresh same-day certificate when the gate is on.
HIGH_VALUE_OPERATIONS = frozenset({
    'wallet_withdrawal.release',
    'agent_commission.settle',
    'agent_commission.clawback',
    'claim_payout',
})

DEFAULT_MAX_AGE_HOURS = 36.0


def books_tied_required() -> bool:
    """Whether high-value authorize must see a fresh books-tied cert.

    Production default is on (same posture as Money Gate). The serve path
    issues today's certificate at boot and arms an in-process daily timer
    so the gate is not stranded when ``PHINS_AGENT_ASYNC`` is off. Set
    ``PHINS_BOOKS_TIED_REQUIRE=0`` to skip the freshness check.
    """
    raw = str(os.environ.get('PHINS_BOOKS_TIED_REQUIRE') or '').strip().lower()
    if raw in ('0', 'false', 'off', 'no'):
        return False
    if raw in ('1', 'true', 'yes', 'on'):
        return True
    test = str(os.environ.get('PHINS_TEST_MODE') or '').strip().lower()
    if test in ('1', 'true', 'yes'):
        return False
    return True


def max_age_hours() -> float:
    try:
        value = float(os.environ.get('PHINS_BOOKS_TIED_MAX_AGE_HOURS', DEFAULT_MAX_AGE_HOURS))
    except (TypeError, ValueError):
        value = DEFAULT_MAX_AGE_HOURS
    return max(1.0, min(value, 168.0))


def utc_day(moment: Optional[datetime] = None) -> str:
    now = moment or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime('%Y-%m-%d')


def certificate_entry_id(day: str) -> str:
    return f'BOOKS-TIED-{day}'


def _canonical_cert_body(payload: Mapping[str, Any]) -> str:
    body = {
        'utc_day': str(payload.get('utc_day') or ''),
        'ok': bool(payload.get('ok')),
        'digest': str(payload.get('digest') or ''),
        'failed_checks': list(payload.get('failed_checks') or []),
        'evaluated_at': str(payload.get('evaluated_at') or ''),
        'schema': str(payload.get('schema') or 'phins.books_tied.v1'),
    }
    return json.dumps(body, sort_keys=True, separators=(',', ':'))


def seal_certificate_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy with ``certificate_sha256`` over the canonical body."""
    sealed = dict(payload)
    sealed.pop('certificate_sha256', None)
    sealed['schema'] = str(sealed.get('schema') or 'phins.books_tied.v1')
    sealed['certificate_sha256'] = hashlib.sha256(
        _canonical_cert_body(sealed).encode('utf-8')
    ).hexdigest()
    return sealed


_CERT_KEYS = (
    'schema', 'utc_day', 'ok', 'digest', 'failed_checks',
    'evaluated_at', 'certificate_sha256',
)


def certificate_payload_from_entry(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Pull cert fields from a nested ``payload`` or flattened ledger entry.

    ``PlatformEventLedgerService.append_event`` merges the supplied payload
    onto the top level of the entry, so production rows carry
    ``utc_day`` / ``certificate_sha256`` at the root. Unit-test mocks may
    still nest under ``payload``.
    """
    nested = entry.get('payload') if isinstance(entry.get('payload'), Mapping) else None
    source: Mapping[str, Any] = nested if nested and (
        'utc_day' in nested or 'certificate_sha256' in nested or 'digest' in nested
    ) else entry
    out: Dict[str, Any] = {}
    for key in _CERT_KEYS:
        if key in source:
            out[key] = source[key]
    if 'failed_checks' in out and not isinstance(out['failed_checks'], list):
        out['failed_checks'] = list(out['failed_checks'] or [])
    return out


def verify_certificate(entry: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Re-seal the payload; refuse when missing, wrong type, or tampered."""
    if not isinstance(entry, Mapping):
        return {'ok': False, 'reason': CERT_MISSING, 'entry': None}
    event_type = str(entry.get('event_type') or entry.get('type') or '')
    if event_type != EVENT_TYPE:
        return {'ok': False, 'reason': CERT_MISSING, 'entry': dict(entry)}
    payload = certificate_payload_from_entry(entry)
    expected = str(payload.get('certificate_sha256') or '')
    resealed = seal_certificate_payload(payload)
    actual = resealed['certificate_sha256']
    if not expected or expected != actual:
        return {
            'ok': False,
            'reason': CERT_TAMPERED,
            'entry': dict(entry),
            'expected': expected,
            'actual': actual,
        }
    return {
        'ok': True,
        'reason': '',
        'entry': dict(entry),
        'payload': resealed,
        'utc_day': str(payload.get('utc_day') or ''),
        'digest': str(payload.get('digest') or ''),
        'evaluated_at': str(payload.get('evaluated_at') or ''),
    }


def _iter_ledger_entries(ledger: Any) -> Sequence[Mapping[str, Any]]:
    store = getattr(ledger, 'transaction_ledger', None)
    if isinstance(store, Mapping):
        return list(store.values())
    if hasattr(ledger, 'values') and callable(ledger.values):
        return list(ledger.values())
    if isinstance(ledger, Mapping):
        return list(ledger.values())
    return []


def find_certificate(
    ledger: Any,
    *,
    day: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the ledger entry for ``day`` (default today UTC), if present."""
    target = day or utc_day()
    wanted_id = certificate_entry_id(target)
    for entry in _iter_ledger_entries(ledger):
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get('id') or entry.get('tx_id') or '') == wanted_id:
            return dict(entry)
        payload = certificate_payload_from_entry(entry)
        if (
            str(entry.get('event_type') or entry.get('type') or '') == EVENT_TYPE
            and str(payload.get('utc_day') or '') == target
        ):
            return dict(entry)
    return None


def latest_verified_certificate(ledger: Any) -> Dict[str, Any]:
    """Newest intact ``finance.books_tied`` entry (by evaluated_at / timestamp)."""
    best: Optional[Dict[str, Any]] = None
    best_key = ''
    for entry in _iter_ledger_entries(ledger):
        check = verify_certificate(entry)
        if not check.get('ok'):
            continue
        payload = check.get('payload') or {}
        key = str(
            payload.get('evaluated_at')
            or entry.get('timestamp')
            or entry.get('recorded_at')
            or ''
        )
        if key >= best_key:
            best_key = key
            best = check
    if best is None:
        return {'ok': False, 'reason': CERT_MISSING, 'entry': None}
    return best


def certificate_age_hours(
    entry_or_check: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Optional[float]:
    """Hours since ``evaluated_at``; None when the stamp cannot be parsed."""
    payload: Mapping[str, Any]
    if isinstance(entry_or_check.get('payload'), Mapping) and (
        'evaluated_at' in entry_or_check['payload'] or 'utc_day' in entry_or_check['payload']
    ):
        payload = entry_or_check['payload']  # type: ignore[index]
    elif 'evaluated_at' in entry_or_check or 'utc_day' in entry_or_check:
        payload = entry_or_check
    else:
        payload = certificate_payload_from_entry(entry_or_check)
    stamp = str(payload.get('evaluated_at') or '')
    if not stamp:
        stamp = str(entry_or_check.get('timestamp') or entry_or_check.get('recorded_at') or '')
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0.0, (moment - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0)


def issue_certificate(
    ledger: Any,
    *,
    books: Optional[Mapping[str, Any]] = None,
    verdict: Optional[MoneyGateVerdict] = None,
    actor: str = 'books_integrity',
    day: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Append today's sealed cert when critical checks are green (idempotent).

    Red books → ``issued=False`` and no ledger write. A prior same-day entry
    is returned as-is (or refused if tampered unless ``force``).
    """
    if ledger is None or not hasattr(ledger, 'append_event'):
        return {'issued': False, 'reason': 'ledger_unavailable'}

    if verdict is None:
        verdict = evaluate_money_gate(books=books, operation='books_tied.issue')
    if not verdict.ok:
        return {
            'issued': False,
            'reason': 'books_red',
            'failed_checks': list(verdict.failed_checks),
            'digest': verdict.digest,
        }

    target_day = day or utc_day()
    existing = find_certificate(ledger, day=target_day)
    if existing is not None and not force:
        check = verify_certificate(existing)
        if check.get('ok'):
            return {
                'issued': False,
                'reason': 'already_issued',
                'entry': existing,
                'verification': check,
            }
        return {
            'issued': False,
            'reason': check.get('reason') or CERT_TAMPERED,
            'entry': existing,
            'verification': check,
        }

    payload = seal_certificate_payload({
        'schema': 'phins.books_tied.v1',
        'utc_day': target_day,
        'ok': True,
        'digest': verdict.digest or digest_for([], ok=True),
        'failed_checks': [],
        'evaluated_at': verdict.evaluated_at or datetime.now(timezone.utc).isoformat(),
    })
    entry = ledger.append_event(
        event_type=EVENT_TYPE,
        entity_type=ENTITY_TYPE,
        entity_id=target_day,
        actor=actor or 'books_integrity',
        status='sealed',
        payload=payload,
        entry_id=certificate_entry_id(target_day),
        ledger_type='event',
    )
    return {
        'issued': True,
        'reason': 'issued',
        'entry': entry,
        'verification': verify_certificate(entry),
    }


def usable_certificate(
    ledger: Any,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Today's intact cert, else the newest intact cert still within max age.

    Prefer the current UTC day so a fresh issue wins. Fall back to the
    latest verified seal so the midnight→clock gap does not refuse payouts
    while yesterday's cert is still younger than ``max_age_hours``.
    """
    day = utc_day(now)
    today = find_certificate(ledger, day=day)
    check = verify_certificate(today)
    if check.get('ok'):
        age = certificate_age_hours(check, now=now)
        if age is not None and age <= max_age_hours():
            check = dict(check)
            check['age_hours'] = age
            check['source_day'] = day
            return check
        return {
            'ok': False,
            'reason': CERT_STALE,
            'entry': check.get('entry'),
            'age_hours': age,
        }
    today_reason = str(check.get('reason') or CERT_MISSING)
    if today is not None and today_reason == CERT_TAMPERED:
        return {'ok': False, 'reason': CERT_TAMPERED, 'entry': today}

    latest = latest_verified_certificate(ledger)
    if not latest.get('ok'):
        return {'ok': False, 'reason': CERT_MISSING, 'entry': None}
    age = certificate_age_hours(latest, now=now)
    if age is None or age > max_age_hours():
        return {
            'ok': False,
            'reason': CERT_STALE,
            'entry': latest.get('entry'),
            'age_hours': age,
        }
    out = dict(latest)
    out['age_hours'] = age
    out['source_day'] = str(latest.get('utc_day') or '')
    return out


def freshness_failures(
    ledger: Any,
    *,
    operation: str,
    now: Optional[datetime] = None,
) -> list:
    """Critical-check ids when a high-value op lacks a fresh certificate."""
    if not books_tied_required():
        return []
    if str(operation or '') not in HIGH_VALUE_OPERATIONS:
        return []
    check = usable_certificate(ledger, now=now)
    if check.get('ok'):
        return []
    reason = str(check.get('reason') or CERT_MISSING)
    if reason == CERT_TAMPERED:
        return [CERT_TAMPERED]
    if reason == CERT_STALE:
        return [CERT_STALE]
    return [CERT_MISSING]


def status_report(ledger: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Accountant-facing badge payload.

    ``intact`` means the seal verifies (checksum OK). ``fresh`` means intact
    and still within ``max_age_hours``. An intact but aged seal reports
    ``fresh=False`` / ``reason=books_tied_certificate_stale`` so the badge
    can show "stale" instead of "tampered".
    """
    day = utc_day(now)
    today_entry = find_certificate(ledger, day=day)
    today_check = verify_certificate(today_entry)
    latest = latest_verified_certificate(ledger)
    usable = usable_certificate(ledger, now=now)

    if usable.get('ok'):
        entry = usable.get('entry')
        payload = usable.get('payload') or {}
        age = usable.get('age_hours')
        if age is None:
            age = certificate_age_hours(usable, now=now)
        intact = True
        fresh = True
        reason = ''
        source_day = str(usable.get('source_day') or day)
    elif today_check.get('ok'):
        entry = today_entry
        payload = today_check.get('payload') or {}
        age = certificate_age_hours(today_check, now=now)
        intact = True
        fresh = False
        reason = CERT_STALE
        source_day = day
    elif latest.get('ok'):
        entry = latest.get('entry')
        payload = latest.get('payload') or {}
        age = certificate_age_hours(latest, now=now)
        intact = True
        fresh = False
        reason = CERT_STALE
        source_day = str(latest.get('utc_day') or '')
    elif today_entry is not None:
        entry = today_entry
        payload = certificate_payload_from_entry(today_entry)
        age = certificate_age_hours(today_check, now=now)
        intact = False
        fresh = False
        reason = str(today_check.get('reason') or CERT_TAMPERED)
        source_day = day
    else:
        entry = None
        payload = {}
        age = None
        intact = False
        fresh = False
        reason = CERT_MISSING
        source_day = ''

    return {
        'schema': 'phins.books_tied_status.v1',
        'utc_day': day,
        'present': entry is not None or today_entry is not None,
        'intact': intact,
        'reason': reason,
        'age_hours': age,
        'max_age_hours': max_age_hours(),
        'fresh': fresh,
        'required': books_tied_required(),
        'digest': str(payload.get('digest') or ''),
        'evaluated_at': str(payload.get('evaluated_at') or ''),
        'entry_id': str((entry or {}).get('id') or '') if entry else '',
        'source_day': source_day,
        'event_type': EVENT_TYPE,
    }


def seconds_until_next_utc_midnight(now: Optional[datetime] = None) -> float:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    tomorrow = (moment + timedelta(days=1)).replace(
        hour=0, minute=5, second=0, microsecond=0,
    )
    return max(60.0, (tomorrow - moment).total_seconds())
