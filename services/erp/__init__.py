"""ERP integrity package (CoA, period close, money gate, books-tied cert).

U4 lands the Money Gate Agent and Books Integrity job. U5 adds the durable
accounting journal. Later units add CoA and period close. Callers go through
``services.erp.money_gate`` / ``accounting_journal`` — this package never
invents a second money store or pricing writer.
"""

from services.erp.money_gate import (
    MoneyGateError,
    MoneyGateVerdict,
    authorize_money_move,
    evaluate_money_gate,
    money_gate_enforced,
)
from services.erp.accounting_journal import (
    accounting_journal_mode,
    append_journal_entry,
    hydrate_accounting_engine_from_journal,
    journal_enabled,
)

__all__ = [
    'MoneyGateError',
    'MoneyGateVerdict',
    'authorize_money_move',
    'evaluate_money_gate',
    'money_gate_enforced',
    'accounting_journal_mode',
    'append_journal_entry',
    'hydrate_accounting_engine_from_journal',
    'journal_enabled',
]
