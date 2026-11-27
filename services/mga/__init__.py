"""MGA cash package — remittance, bordereaux (U9+), later trust/cession/tax.

Carrier remittance and premium/claims bordereaux are generated from kernel
pins + ledger cash. This package never invents a second pricing writer or
reads analytical ``_EXPENSE_WEIGHTS`` as cash truth (plan KTD5).
"""

from __future__ import annotations

__all__ = [
    'build_bordereau',
    'verify_bordereau',
    'create_remittance_run',
    'settle_remittance_run',
    'DEFAULT_BINDER_ID',
]


def __getattr__(name: str):
    if name in ('build_bordereau', 'verify_bordereau', 'DEFAULT_BINDER_ID'):
        from services.mga import bordereaux as _b

        return getattr(_b, name)
    if name in ('create_remittance_run', 'settle_remittance_run'):
        from services.mga import remittance as _r

        return getattr(_r, name)
    raise AttributeError(name)
