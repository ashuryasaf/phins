"""Tests for password-reset OTP delivery channel resolution.

These cover ``_resolve_password_reset_channel``, which routes the reset OTP
onto a channel that can actually deliver in the current deployment. The key
production scenario: SMTP is unconfigured (NoOp email) but Telesign SMS is
configured on Railway, so an ``email`` request for an account with a phone on
file should fall back to SMS instead of failing with
"Delivery issue detected.".

SMS in this flow is always bound to the account's registered phone, so an
email -> SMS fallback still targets the account owner (no cross-account
exposure).
"""

from __future__ import annotations

import web_portal.server as portal


def _resolve(channel, has_phone, email_ok, sms_ok):
    return portal._resolve_password_reset_channel(
        channel,
        has_phone=has_phone,
        email_deliverable=email_ok,
        sms_deliverable=sms_ok,
    )


def test_email_stays_email_when_email_deliverable():
    assert _resolve('email', has_phone=True, email_ok=True, sms_ok=True) == 'email'
    assert _resolve('email', has_phone=False, email_ok=True, sms_ok=False) == 'email'


def test_email_falls_back_to_sms_when_email_unconfigured_and_phone_on_file():
    # The Railway case: SMTP NoOp, Telesign SMS configured, phone on file.
    assert _resolve('email', has_phone=True, email_ok=False, sms_ok=True) == 'sms'


def test_email_stays_email_when_no_phone_even_if_email_unconfigured():
    # Without a registered phone there is nowhere to fall back to; keep email
    # so the failure is surfaced rather than silently misrouted.
    assert _resolve('email', has_phone=False, email_ok=False, sms_ok=True) == 'email'


def test_sms_request_requires_phone():
    assert _resolve('sms', has_phone=False, email_ok=True, sms_ok=True) == 'email'
    assert _resolve('sms', has_phone=True, email_ok=True, sms_ok=True) == 'sms'


def test_sms_falls_back_to_email_when_sms_provider_unconfigured():
    assert _resolve('sms', has_phone=True, email_ok=True, sms_ok=False) == 'email'


def test_both_drops_to_email_without_phone():
    assert _resolve('both', has_phone=False, email_ok=True, sms_ok=True) == 'email'


def test_both_preserved_when_phone_present():
    assert _resolve('both', has_phone=True, email_ok=True, sms_ok=True) == 'both'


def test_unknown_channel_defaults_to_email():
    assert _resolve('carrier-pigeon', has_phone=True, email_ok=True, sms_ok=True) == 'email'


def test_no_deliverable_channel_keeps_requested_channel():
    # Nothing can deliver: keep 'email' so the caller reports the failure
    # (notification_sent False) rather than misrouting to a dead SMS provider.
    assert _resolve('email', has_phone=True, email_ok=False, sms_ok=False) == 'email'
    assert _resolve('sms', has_phone=True, email_ok=False, sms_ok=False) == 'sms'


def test_provider_deliverability_returns_bool_pair():
    email_ok, sms_ok = portal._password_reset_provider_deliverability()
    assert isinstance(email_ok, bool)
    assert isinstance(sms_ok, bool)
