"""ERP integrity package (CoA, period close, money gate, books-tied cert).

U4 lands the Money Gate Agent and Books Integrity job. Later units add CoA
and period close. Callers go through ``services.erp.money_gate`` — this
package never invents a second money store or pricing writer.
"""

from services.erp.money_gate import (
    MoneyGateError,
    MoneyGateVerdict,
    authorize_money_move,
    evaluate_money_gate,
    money_gate_enforced,
)

__all__ = [
    'MoneyGateError',
    'MoneyGateVerdict',
    'authorize_money_move',
    'evaluate_money_gate',
    'money_gate_enforced',
]
