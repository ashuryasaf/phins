"""MGA cash package — remittance, bordereaux, trust, cession, premium tax.

Carrier remittance and premium/claims bordereaux are generated from kernel
pins + ledger cash. Trust holds carrier risk until settle; cession is a
treaty cash book. Premium tax accrues additively. This package never invents
a second pricing writer or reads analytical ``_EXPENSE_WEIGHTS`` as cash
truth (plan KTD5).
"""

from __future__ import annotations

__all__ = [
    'build_bordereau',
    'verify_bordereau',
    'create_remittance_run',
    'settle_remittance_run',
    'DEFAULT_BINDER_ID',
    'reconcile_trust',
    'post_cession_from_bordereau',
    'accrue_from_bordereau',
]


def __getattr__(name: str):
    if name in ('build_bordereau', 'verify_bordereau', 'DEFAULT_BINDER_ID'):
        from services.mga import bordereaux as _b
        return getattr(_b, name)
    if name in ('create_remittance_run', 'settle_remittance_run'):
        from services.mga import remittance as _r
        return getattr(_r, name)
    if name in ('reconcile_trust', 'trust_balance', 'trial_balance'):
        from services.mga import trust as _t
        return getattr(_t, name)
    if name in ('post_cession_from_bordereau', 'analytical_divergence_report'):
        from services.mga import cession as _c
        return getattr(_c, name)
    if name in ('accrue_from_bordereau', 'remittance_schedule', 'list_jurisdictions'):
        from services.mga import premium_tax as _p
        return getattr(_p, name)
    raise AttributeError(name)
