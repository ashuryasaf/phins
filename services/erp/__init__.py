"""ERP integrity package (CoA, period close, money gate, books-tied cert).

U4 lands the Money Gate Agent and Books Integrity job. U5 adds the durable
accounting journal. U6 seals the daily ``finance.books_tied`` certificate.
U7 (agent commission clawback) lives on AgentOS +
``services.jobs.commission_clawback_job`` and gates through Money Gate op
``agent_commission.clawback``. The integrity scorecard reports plan maturity
58→100 and is imported lazily (CLI/tests) so boot money paths do not load
it. Later units add CoA and period close. Callers go through
``services.erp.money_gate`` / ``accounting_journal`` / ``books_tied`` — this
package never invents a second money store or pricing writer.
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
    'issue_certificate',
    'status_report',
    'verify_certificate',
    'compute_integrity_scorecard',
    'render_scorecard_markdown',
]


def __getattr__(name: str):
    """Lazy-load offline helpers so serve boot stays on money modules."""
    if name in ('compute_integrity_scorecard', 'render_scorecard_markdown'):
        from services.erp import integrity_scorecard as _scorecard

        return getattr(_scorecard, name)
    if name in ('issue_certificate', 'status_report', 'verify_certificate'):
        from services.erp import books_tied as _books_tied

        return getattr(_books_tied, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
