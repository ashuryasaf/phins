"""Money Gate Agent (ERP/MGA integrity U4).

Fail-closed middleware for payout / settle / release / remittance. Reads
``reconcile_financial_books`` and the unified cash-flow statement, never
mutates those books. A red critical check returns 409
``{error, failed_checks[]}``. Operator override is admin-only break-glass
with a forensic platform-ledger event written *before* the money move.

Enforcement defaults on outside ``PHINS_TEST_MODE``. Set ``PHINS_MONEY_GATE=1``
to force on under tests, or ``PHINS_MONEY_GATE=0`` to disable explicitly.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

# Fail-closed when the gate cannot read the books at all.
BOOKS_UNREADABLE = 'books_unreadable'

# Unified-statement checks that block money moves (AE3 names claims_counted_once).
CRITICAL_UNIFIED_CHECKS = frozenset({
    'claims_counted_once',
    'claims_posted',
    'claim_cash_has_a_claim',
    'premium_waterfall_ties',
    'kernel_risk_not_saved',
    'balance_sheet_ties',
    'withdrawals_tie',
    'seals_intact',
    BOOKS_UNREADABLE,
})

# Reconcile discrepancies that mean cash identity is broken.
CRITICAL_RECONCILE_CHECKS = frozenset({
    'bills_vs_ledger_premiums',
    'paid_claims_missing_customer_ledger',
    'paid_bills_missing_customer_ledger',
    'investment_allocations_exceed_savings_premium',
    'savings_cash_not_landed_in_portfolios',
    'accounting_book_split_vs_kernel_pins',
})

BREAK_GLASS_EVENT = 'finance.money_gate_break_glass'
GATE_REFUSED_ERROR = 'money_gate_refused'

BooksProvider = Callable[[], Dict[str, Any]]

# Sentinel: omit ``platform_ledger`` to try the portal ledger; pass ``None``
# explicitly to fail closed without a journal (tests / callers that refuse fallback).
_LEDGER_UNSET = object()


def money_gate_enforced() -> bool:
    """Whether authorize must refuse on red critical checks."""
    raw = str(os.environ.get('PHINS_MONEY_GATE') or '').strip().lower()
    if raw in ('0', 'false', 'off', 'no'):
        return False
    if raw in ('1', 'true', 'yes', 'on'):
        return True
    test = str(os.environ.get('PHINS_TEST_MODE') or '').strip().lower()
    if test in ('1', 'true', 'yes'):
        return False
    return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def critical_failures(
    *,
    unified_failed: Optional[Iterable[str]] = None,
    reconcile_discrepancies: Optional[Iterable[Mapping[str, Any]]] = None,
) -> List[str]:
    """Sorted critical check ids that are red in the two reports."""
    failed: List[str] = []
    for name in unified_failed or ():
        key = str(name or '').strip()
        if key in CRITICAL_UNIFIED_CHECKS:
            failed.append(key)
    for row in reconcile_discrepancies or ():
        if not isinstance(row, Mapping):
            continue
        key = str(row.get('check') or '').strip()
        if key in CRITICAL_RECONCILE_CHECKS:
            failed.append(key)
    return sorted(set(failed))


def digest_for(failed_checks: Sequence[str], *, ok: bool) -> str:
    """Stable SHA-256 over the critical outcome (never authorises from cache alone)."""
    payload = {
        'ok': bool(ok),
        'failed_checks': list(failed_checks),
        'unified_critical': sorted(CRITICAL_UNIFIED_CHECKS),
        'reconcile_critical': sorted(CRITICAL_RECONCILE_CHECKS),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class MoneyGateVerdict:
    """Read-only gate result. ``authorize_money_move`` may set ``break_glass``."""

    ok: bool
    failed_checks: List[str] = field(default_factory=list)
    digest: str = ''
    enforced: bool = True
    operation: str = ''
    evaluated_at: str = ''
    break_glass: bool = False
    source: str = 'reconcile+unified'

    def as_dict(self) -> Dict[str, Any]:
        return {
            'ok': self.ok,
            'failed_checks': list(self.failed_checks),
            'digest': self.digest,
            'enforced': self.enforced,
            'operation': self.operation,
            'evaluated_at': self.evaluated_at,
            'break_glass': self.break_glass,
            'source': self.source,
        }


class MoneyGateError(Exception):
    """Raised when a money move is refused. Map to HTTP 409."""

    def __init__(self, verdict: MoneyGateVerdict, message: str = GATE_REFUSED_ERROR):
        super().__init__(message)
        self.verdict = verdict
        self.failed_checks = list(verdict.failed_checks)
        self.digest = verdict.digest

    def as_response(self) -> Dict[str, Any]:
        return {
            'error': GATE_REFUSED_ERROR,
            'failed_checks': list(self.failed_checks),
            'digest': self.digest,
            'operation': self.verdict.operation,
        }


def evaluate_from_reports(
    *,
    unified_report: Optional[Mapping[str, Any]] = None,
    reconcile_report: Optional[Mapping[str, Any]] = None,
    operation: str = '',
) -> MoneyGateVerdict:
    """Compute the critical-check digest from two already-built reports.

    Both reports missing → ``books_unreadable`` (fail closed). An empty but
    present report is green for that side; callers must not substitute ``{}``
    for a failed book read (see ``_unavailable_books``).
    """
    if unified_report is None and reconcile_report is None:
        failed = [BOOKS_UNREADABLE]
        ok = False
        return MoneyGateVerdict(
            ok=ok,
            failed_checks=failed,
            digest=digest_for(failed, ok=ok),
            enforced=money_gate_enforced(),
            operation=str(operation or ''),
            evaluated_at=_utc_now(),
            source='books_unreadable',
        )
    unified = unified_report if isinstance(unified_report, Mapping) else {}
    integrity = unified.get('integrity') if isinstance(unified.get('integrity'), Mapping) else {}
    unified_failed = integrity.get('failed') if isinstance(integrity.get('failed'), list) else []
    discrepancies = []
    if isinstance(reconcile_report, Mapping):
        raw = reconcile_report.get('discrepancies')
        if isinstance(raw, list):
            discrepancies = raw
    failed = critical_failures(
        unified_failed=unified_failed,
        reconcile_discrepancies=discrepancies,
    )
    ok = not failed
    return MoneyGateVerdict(
        ok=ok,
        failed_checks=failed,
        digest=digest_for(failed, ok=ok),
        enforced=money_gate_enforced(),
        operation=str(operation or ''),
        evaluated_at=_utc_now(),
    )


def _unavailable_books() -> Dict[str, Any]:
    """Synthetic red books when the live portal stores cannot be read."""
    return {
        'unified': {
            'integrity': {'ok': False, 'failed': [BOOKS_UNREADABLE]},
        },
        'reconcile': {'discrepancies': []},
        '_books_error': BOOKS_UNREADABLE,
    }


def evaluate_money_gate(
    *,
    books: Optional[Mapping[str, Any]] = None,
    books_provider: Optional[BooksProvider] = None,
    operation: str = '',
) -> MoneyGateVerdict:
    """Evaluate critical checks. Never writes. Prefer explicit ``books`` in tests.

    A missing portal module, a provider exception, or a payload without both
    report keys fails closed as ``books_unreadable`` — never as an empty green.
    """
    try:
        if books is not None:
            payload = dict(books)
        elif books_provider is not None:
            payload = dict(books_provider() or {})
        else:
            payload = _default_portal_books()
    except Exception:
        payload = _unavailable_books()
    if payload.get('_books_error') or (
        'unified' not in payload and 'reconcile' not in payload
    ):
        # Empty ``{}`` from a failed default used to look green — refuse.
        if 'unified' not in payload and 'reconcile' not in payload:
            payload = _unavailable_books()
    return evaluate_from_reports(
        unified_report=payload.get('unified') if 'unified' in payload else None,
        reconcile_report=payload.get('reconcile') if 'reconcile' in payload else None,
        operation=operation,
    )


def _default_portal_books() -> Dict[str, Any]:
    """Live portal books when the web process (or worker with same stores) is up.

    Fail closed: portal missing, builder missing, or any exception →
    ``books_unreadable`` (never an empty green payload).
    """
    try:
        import sys
        portal = sys.modules.get('web_portal.server') or sys.modules.get('server')
        if portal is None:
            return _unavailable_books()
        from services.financial_unification_service import reconcile_financial_books

        policies = getattr(portal, 'POLICIES', {}) or {}
        claims = getattr(portal, 'CLAIMS', {}) or {}
        billing = getattr(portal, 'BILLING', {}) or {}
        ledger = getattr(portal, 'TRANSACTION_LEDGER', {}) or {}
        exclude = getattr(portal, 'is_suspended_account', None)
        reconcile = reconcile_financial_books(
            policies=policies,
            claims=claims,
            billing=billing,
            transactions=ledger.values() if hasattr(ledger, 'values') else ledger,
            balance_sheet=getattr(portal, 'PHINS_BALANCE_SHEET', None),
            exclude_customer=exclude,
            investment_accounts=getattr(portal, 'INVESTMENT_ACCOUNTS', None),
        )
        build_unified = getattr(portal, 'build_cashflow_unified_report', None)
        if not callable(build_unified):
            return _unavailable_books()
        unified = build_unified()
        if not isinstance(unified, Mapping):
            return _unavailable_books()
        if not isinstance(reconcile, Mapping):
            return _unavailable_books()
        return {'unified': unified, 'reconcile': reconcile}
    except Exception:
        return _unavailable_books()


def _record_break_glass(
    *,
    operation: str,
    actor: str,
    reason: str,
    verdict: MoneyGateVerdict,
    platform_ledger: Any = _LEDGER_UNSET,
    audit: Any = None,
) -> None:
    """Forensic journal first (fail closed). Ledger event then audit trail."""
    payload = {
        'operation': operation,
        'reason': reason,
        'failed_checks': list(verdict.failed_checks),
        'digest': verdict.digest,
        'evaluated_at': verdict.evaluated_at,
    }
    ledger = platform_ledger
    if ledger is _LEDGER_UNSET:
        ledger = None
        try:
            import sys
            portal = sys.modules.get('web_portal.server') or sys.modules.get('server')
            ledger = getattr(portal, 'PLATFORM_EVENT_LEDGER', None) if portal else None
            if ledger is None and portal is not None:
                ledger = getattr(portal, 'platform_event_ledger', None)
        except Exception:
            ledger = None
    if ledger is not None and hasattr(ledger, 'append_event'):
        ledger.append_event(
            event_type=BREAK_GLASS_EVENT,
            entity_type='money_gate',
            entity_id=operation or 'money_move',
            actor=actor or 'admin',
            amount=0.0,
            status='recorded',
            payload=payload,
        )
    else:
        # No durable journal → refuse break-glass (fail closed).
        raise MoneyGateError(
            MoneyGateVerdict(
                ok=False,
                failed_checks=list(verdict.failed_checks) or ['break_glass_journal_unavailable'],
                digest=verdict.digest,
                enforced=True,
                operation=operation,
                evaluated_at=_utc_now(),
            ),
            message='money_gate_break_glass_journal_unavailable',
        )
    if audit is not None and hasattr(audit, 'log'):
        try:
            audit.log(
                actor=actor or 'admin',
                action=BREAK_GLASS_EVENT,
                entity='money_gate',
                entity_id=operation or 'money_move',
                details=payload,
            )
        except Exception:
            pass


def authorize_money_move(
    operation: str,
    *,
    books: Optional[Mapping[str, Any]] = None,
    books_provider: Optional[BooksProvider] = None,
    break_glass: bool = False,
    break_glass_reason: str = '',
    actor: str = '',
    role: str = '',
    platform_ledger: Any = _LEDGER_UNSET,
    audit: Any = None,
) -> MoneyGateVerdict:
    """Authorize a money-moving operation or raise ``MoneyGateError``.

    When enforcement is off the verdict is returned with ``ok`` reflecting
    the books but the move is allowed. Break-glass requires ``role=admin``,
    a non-empty reason, and a successful forensic ledger append first.
    High-value ops also need today's sealed ``finance.books_tied`` cert
    (U6) unless ``PHINS_BOOKS_TIED_REQUIRE=0``.
    """
    verdict = evaluate_money_gate(
        books=books, books_provider=books_provider, operation=operation,
    )
    # U6: fold certificate freshness into the same critical-check list.
    ledger = platform_ledger
    if ledger is _LEDGER_UNSET:
        ledger = None
        try:
            import sys
            portal = sys.modules.get('web_portal.server') or sys.modules.get('server')
            ledger = getattr(portal, 'platform_event_ledger', None) if portal else None
        except Exception:
            ledger = None
    try:
        from services.erp.books_tied import freshness_failures

        cert_failed = freshness_failures(ledger, operation=operation)
    except Exception:
        cert_failed = []
    if cert_failed:
        merged = sorted(set(list(verdict.failed_checks) + list(cert_failed)))
        verdict = MoneyGateVerdict(
            ok=False,
            failed_checks=merged,
            digest=digest_for(merged, ok=False),
            enforced=verdict.enforced,
            operation=verdict.operation,
            evaluated_at=verdict.evaluated_at,
            source=verdict.source,
        )
    if verdict.ok or not verdict.enforced:
        return verdict
    if break_glass:
        if str(role or '').strip().lower() != 'admin':
            raise MoneyGateError(verdict, message='money_gate_break_glass_admin_required')
        reason = str(break_glass_reason or '').strip()
        if len(reason) < 8:
            raise MoneyGateError(verdict, message='money_gate_break_glass_reason_required')
        _record_break_glass(
            operation=operation,
            actor=actor or 'admin',
            reason=reason,
            verdict=verdict,
            platform_ledger=platform_ledger,
            audit=audit,
        )
        return MoneyGateVerdict(
            ok=True,
            failed_checks=list(verdict.failed_checks),
            digest=verdict.digest,
            enforced=True,
            operation=operation,
            evaluated_at=verdict.evaluated_at,
            break_glass=True,
        )
    raise MoneyGateError(verdict)


def http_refuse(exc: MoneyGateError) -> Dict[str, Any]:
    """JSON body for a 409 money-gate refusal (and break-glass precondition errors)."""
    body = exc.as_response()
    msg = str(exc)
    if msg and msg != GATE_REFUSED_ERROR:
        body['error'] = msg
    return body
