"""OTP gate, address-after-OTP, and shared apply typeahead integrity."""

from pathlib import Path

from services.chat_application_service import (
    STEPS,
    _OTP_GATE_AFTER,
    _validate_phone,
    _validate_place,
)


STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
APPLY_HTML = (STATIC / "apply.html").read_text(encoding="utf-8")
APPLY_CHAT_HTML = (STATIC / "apply-chat.html").read_text(encoding="utf-8")
APPLY_JS = (STATIC / "apply.js").read_text(encoding="utf-8")
APPLY_CHAT_JS = (STATIC / "apply-chat.js").read_text(encoding="utf-8")
SUGGEST_JS = (STATIC / "apply-suggest.js").read_text(encoding="utf-8")


def _step(step_id):
    return next(step for step in STEPS if step["id"] == step_id)


class TestChatAddressAfterOtp:
    def test_country_and_city_follow_phone_otp_gate(self):
        ids = [step["id"] for step in STEPS]
        assert ids.index("phone") < ids.index("country") < ids.index("city") < ids.index("dob")
        assert _OTP_GATE_AFTER == "phone"

    def test_address_steps_expose_suggest_hints(self):
        assert _step("country")["input"]["suggest"] == "country"
        assert _step("city")["input"]["suggest"] == "city"
        assert _step("phone")["input"]["suggest"] == "phone"
        assert _step("occupation")["input"]["suggest"] == "occupation"
        assert _step("medications")["input"]["suggest"] == "medication"

    def test_country_rejects_dates_and_blank(self):
        validate = _validate_place("country")
        ok, err = validate("1990-05-14", {})
        assert ok is False
        assert "date" in err.lower()
        ok, err = validate("x", {})
        assert ok is False
        ok, cleaned = validate("Israel", {})
        assert ok is True
        assert cleaned == "Israel"

    def test_phone_keeps_submitted_international_value(self):
        ok, cleaned = _validate_phone("+972 50-123-4567", {})
        assert ok is True
        assert cleaned == "+972 50-123-4567"
        assert _validate_phone("12", {})[0] is False


class TestClassicApplyOtpAndSuggestMarkup:
    def test_otp_panel_is_on_personal_info_step(self):
        start = APPLY_HTML.find('<div class="form-step active" data-step="1">')
        end = APPLY_HTML.find('<div class="form-step" data-step="2">')
        step1 = APPLY_HTML[start:end]
        assert start != -1 and end != -1
        assert 'id="apply-otp-panel"' in step1
        assert "Verify your contact details" in step1
        assert 'id="apply-otp-verify"' in step1

    def test_classic_form_wires_suggest_and_blocks_step2_without_otp(self):
        assert 'src="apply-suggest.js"' in APPLY_HTML
        assert "function requestApplyOtp(" in APPLY_JS
        assert "function verifyApplyOtp(" in APPLY_JS
        assert "applyOtpStillValid()" in APPLY_JS
        assert "otp_verification_id" in APPLY_JS
        assert "customer_country" in APPLY_JS
        assert "customer_occupation" in APPLY_JS

    def test_chat_form_wires_suggest_and_phone_combo(self):
        assert 'src="apply-suggest.js"' in APPLY_CHAT_HTML
        assert "function renderPhoneInput(" in APPLY_CHAT_JS
        assert "PhinsApplySuggest" in APPLY_CHAT_JS

    def test_shared_catalogs_include_requested_examples(self):
        assert "dial: '972'" in SUGGEST_JS
        assert "United Kingdom" in SUGGEST_JS
        assert "dial: '44'" in SUGGEST_JS
        assert "Software Engineer" in SUGGEST_JS
        assert "Tel Aviv" in SUGGEST_JS
        assert "Metformin" in SUGGEST_JS
        assert "function composePhone(" in SUGGEST_JS
        assert "kind === 'medication'" in SUGGEST_JS
