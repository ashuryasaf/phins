"""
Parity tests for services/agent_helpers.py.

Every private helper copy that an agent module replaces must produce
identical results on the edge-value fixture below, so adoption can never
change a stored number or a status comparison.
"""

import math

import pytest

from services import agent_helpers as h

EDGE_VALUES = [
    None, "", "   ", 0, 1, -1, 1.5, "1", "1.5", " 2.5 ", "1,234.5", "1,000",
    "abc", "1e3", "inf", "-inf", "nan", True, False, [], {}, object(),
    float("nan"), float("inf"), 10**20, "0x10", b"12", "12.0",
]

STATUS_VALUES = [
    None, "", "Approved", "approved ", "UNDER REVIEW", "under_review",
    "Under Review", " paid", 0, 1, "Pending  Review",
]


def _same(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def _legacy(fn, *args):
    """Call a legacy helper; legacy copies that only catch (TypeError,
    ValueError) raise OverflowError on ``"inf"``. The canonical helper returns
    the default there instead of crashing, so the parity check treats a
    legacy exception as "expect default"."""
    try:
        return fn(*args), False
    except OverflowError:
        return None, True


def _assert_parity(canonical_value, legacy_fn, *args, default):
    legacy_value, raised = _legacy(legacy_fn, *args)
    if raised:
        assert canonical_value == default, repr(args)
    else:
        assert _same(canonical_value, legacy_value), repr(args)


# ---------------------------------------------------------------------------
# safe_float parity
# ---------------------------------------------------------------------------

def test_parity_customer_communication_safe_float():
    from services.customer_communication_agent import _safe_float as legacy
    for v in EDGE_VALUES:
        assert _same(h.safe_float(v), legacy(v)), repr(v)
        assert _same(h.safe_float(v, 7.5), legacy(v, 7.5)), repr(v)


def test_parity_marketing_safe_float_and_int():
    from services.marketing_sales_agent_service import (
        _safe_float as legacy_float, _safe_int as legacy_int,
    )
    for v in EDGE_VALUES:
        assert _same(h.safe_float(v, strip_commas=False), legacy_float(v)), repr(v)
        _assert_parity(h.safe_int(v), legacy_int, v, default=0)
        _assert_parity(h.safe_int(v, 9), legacy_int, v, 9, default=9)


def test_parity_server_safe_float_and_int():
    import web_portal.server as server
    for v in EDGE_VALUES:
        assert _same(h.safe_float(v, strip_commas=False), server.safe_float(v)), repr(v)
        _assert_parity(h.safe_int(v), server.safe_int, v, default=0)


def test_parity_trading_engine_sf():
    from services.ai_trading_engine import _sf as legacy
    for v in EDGE_VALUES:
        assert _same(h.safe_float(v, strip_commas=False, finite_only=True), legacy(v)), repr(v)


# ---------------------------------------------------------------------------
# status parity
# ---------------------------------------------------------------------------

def test_parity_customer_communication_status():
    from services.customer_communication_agent import _status as legacy
    for v in STATUS_VALUES:
        assert h.status_lower(v) == legacy(v), repr(v)


def test_parity_marketing_status():
    from services.marketing_sales_agent_service import _status as legacy
    for v in STATUS_VALUES:
        assert h.status_lower(v, underscore_spaces=True, falsy_as_empty=True) == legacy(v), repr(v)


def _status_parity(canonical_fn, legacy_fn, *args):
    """Legacy status helpers call ``.lower()`` on the raw value and crash on
    non-string statuses (``1 -> AttributeError``). The canonical helper
    stringifies instead, so a legacy crash only requires the canonical call
    to succeed; otherwise results must be identical."""
    try:
        expected = legacy_fn(*args)
    except AttributeError:
        canonical_fn(*args)
        return
    assert canonical_fn(*args) == expected, repr(args)


def test_parity_server_status_helpers():
    import web_portal.server as server
    for v in STATUS_VALUES:
        item = {"status": v}
        _status_parity(h.get_status_lower, server.get_status_lower, item)
        for targets in (("approved",), ("Under Review", "paid"), ("under_review",)):
            _status_parity(h.status_eq, server.status_eq, item, *targets)
            _status_parity(h.status_in, server.status_in, item, list(targets))


def test_parity_metrics_service_status_helpers():
    from services import metrics_service as ms
    for v in STATUS_VALUES:
        item = {"status": v}
        for targets in (("approved",), ("Under Review", "paid")):
            _status_parity(h.status_eq, ms._status_eq, item, *targets)
            _status_parity(h.status_in, ms._status_in, item, list(targets))


# ---------------------------------------------------------------------------
# Own semantics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("1,234.5", 1234.5), (" 3 ", 3.0), (True, 1.0), (False, 0.0), (None, 0.0),
])
def test_safe_float_canonical(value, expected):
    assert h.safe_float(value) == expected


def test_safe_float_finite_only():
    assert h.safe_float("inf", finite_only=True) == 0.0
    assert math.isinf(h.safe_float("inf"))


def test_status_lower_accepts_dict_or_scalar():
    assert h.status_lower({"status": " Paid "}) == "paid"
    assert h.status_lower("Under Review", underscore_spaces=True) == "under_review"
    assert h.status_lower({}) == ""
    assert h.status_lower(0) == "0"
    assert h.status_lower(0, falsy_as_empty=True) == ""
    assert h.status_lower(" x ", strip=False) == " x "


def test_utc_now_iso_formats():
    plain = h.utc_now_iso()
    assert plain.endswith("+00:00")
    assert h.utc_now_iso(zulu=True).endswith("Z")
    assert len(h.utc_now_iso(timespec="seconds")) == len("2026-01-01T00:00:00+00:00")
