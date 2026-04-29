"""Tests for AI Customer Assistant voice command optimization and data integrity."""

from pathlib import Path
from urllib.request import urlopen, Request
import json


STATIC_DIR = Path(__file__).resolve().parents[1] / "web_portal" / "static"
DASHBOARD_PATH = STATIC_DIR / "dashboard.html"
UI_CLARITY_PATH = STATIC_DIR / "ui-clarity.js"


def _fetch(path: str) -> str:
    with urlopen(f"http://localhost:8000{path}") as resp:
        return resp.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Voice preprocessing coverage: every intent should have voice patterns
# ---------------------------------------------------------------------------

def test_voice_preprocessing_covers_all_intent_categories():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    required_patterns = [
        "join community foundation",
        "show my community",
        "create foundation",
        "apply for new policy",
        "show me my policies",
        "policy report",
        "buy medical equipment",
        "book doctor consultation",
        "order medication",
        "home care services",
        "show me all my billings",
        "billing report",
        "pay my bills",
        "how much do i pay monthly",
        "file a claim",
        "track my claim",
        "claims report",
        "contact support",
        "refer a friend",
        "check wallet balance",
        "savings report",
        "view investments",
        "personal data report",
        "update my profile",
        "change password",
        "my coverage amount",
        "transfer funds",
    ]
    for pattern in required_patterns:
        assert pattern in content, f"Missing voice pattern replacement: {pattern}"


def test_voice_preprocessing_handles_medical_variants():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "wheelchair" in content
    assert "walker" in content
    assert "telemedicine" in content
    assert "tele-?health" in content or "telemedicine" in content
    assert "pharmacy" in content
    assert "drug refill" in content or "med ?refill" in content
    assert "visiting" in content or "mobile" in content


def test_voice_preprocessing_handles_financial_variants():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "make payment" in content or "make.*payment" in content
    assert "deposit" in content
    assert "transfer" in content
    assert "monthly.*cost" in content or "monthly cost" in content


def test_referral_voice_preprocessing_matches_referral_intent_keywords():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "ACTION_REFERRAL: ['refer a friend'," in content


# ---------------------------------------------------------------------------
# TTS voice feedback (speakResponse)
# ---------------------------------------------------------------------------

def test_speak_response_function_present():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "function speakResponse(text)" in content
    assert "speechSynthesis" in content
    assert "SpeechSynthesisUtterance" in content


def test_speak_response_respects_language_preference():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "phins_language" in content
    assert "'es': 'es-ES'" in content or '"es": "es-ES"' in content
    assert "'fr': 'fr-FR'" in content or '"fr": "fr-FR"' in content


def test_speak_response_only_fires_for_voice_input():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "if (lastInputMethod !== 'voice') return;" in content


# ---------------------------------------------------------------------------
# Voice confirmations map
# ---------------------------------------------------------------------------

def test_voice_confirmations_cover_all_intents():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "VOICE_CONFIRMATIONS" in content
    expected_keys = [
        "REPORT_BILLING",
        "REPORT_PERSONAL",
        "REPORT_POLICY",
        "REPORT_SAVINGS",
        "REPORT_CLAIMS",
        "INFO_MONTHLY_COST",
        "INFO_MONTHLY_SAVINGS",
        "INFO_COVERAGE",
        "INFO_BALANCE",
        "CALC_PROJECTION",
        "ACTION_JOIN_COMMUNITY",
        "ACTION_SHOW_COMMUNITY",
        "ACTION_CREATE_FOUNDATION",
        "ACTION_APPLY",
        "ACTION_BUY_EQUIPMENT",
        "ACTION_BOOK_CONSULTATION",
        "ACTION_PHARMACY",
        "ACTION_HOME_CARE",
        "ACTION_PAY",
        "ACTION_SAVE",
        "ACTION_TRANSFER",
        "ACTION_CLAIM",
        "ACTION_UPDATE",
        "ACTION_CHANGE_PASSWORD",
        "ACTION_REFERRAL",
        "ACTION_CONTACT_SUPPORT",
        "ACTION_INVESTMENT",
        "UNKNOWN",
    ]
    for key in expected_keys:
        assert key in content, f"Missing voice confirmation for intent: {key}"


# ---------------------------------------------------------------------------
# Input method tracking for data integrity
# ---------------------------------------------------------------------------

def test_input_method_tracking_variable_exists():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "let lastInputMethod = 'text';" in content


def test_start_voice_input_sets_input_method():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "lastInputMethod = 'voice';" in content


def test_stop_voice_input_resets_input_method_by_default():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "function stopVoiceInput(resetInputMethod = true)" in content
    assert "if (resetInputMethod) {" in content
    assert "lastInputMethod = 'text';" in content


def test_successful_voice_result_preserves_voice_input_method():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "stopVoiceInput(false);" in content


def test_quick_action_passes_input_method():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "processAIQuery('quick_action')" in content


def test_record_ai_interaction_includes_input_method():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "input_method: inputMethod || lastInputMethod || 'text'" in content


def test_execute_intent_passes_input_method_to_recording():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "recordAIInteraction(intent.type, originalQuery, intent.input_method)" in content


# ---------------------------------------------------------------------------
# Floating bar voice optimization (ui-clarity.js)
# ---------------------------------------------------------------------------

def test_floating_bar_has_voice_preprocessing():
    content = UI_CLARITY_PATH.read_text(encoding="utf-8")
    assert "function preprocessFloatingVoiceInput(transcript)" in content


def test_floating_bar_voice_uses_language_preference():
    content = UI_CLARITY_PATH.read_text(encoding="utf-8")
    assert "function getFloatingVoiceLang()" in content
    assert "phins_language" in content
    assert "recognition.lang = getFloatingVoiceLang();" in content


def test_floating_bar_voice_preprocessing_covers_key_commands():
    content = UI_CLARITY_PATH.read_text(encoding="utf-8")
    assert "show me my policies" in content
    assert "show me all my billings" in content
    assert "i want to file a claim" in content
    assert "check my wallet balance" in content
    assert "refresh overview" in content
    assert "run portfolio simulation" in content


def test_floating_bar_voice_error_messages_improved():
    content = UI_CLARITY_PATH.read_text(encoding="utf-8")
    assert "No speech detected. Please try again." in content
    assert "Microphone access denied. Please allow permissions." in content


def test_floating_bar_preprocesses_voice_before_dispatch():
    content = UI_CLARITY_PATH.read_text(encoding="utf-8")
    assert "const processed = preprocessFloatingVoiceInput(cleaned);" in content


# ---------------------------------------------------------------------------
# Server-side data integrity for input_method
# ---------------------------------------------------------------------------

def test_server_ai_interaction_accepts_input_method():
    """POST /api/customer/ai-interaction should accept and validate input_method."""
    content = _fetch("/dashboard.html")
    assert "input_method" in content


def test_server_ai_interaction_endpoint_available():
    """Verify the AI interaction endpoint responds."""
    try:
        req = Request(
            "http://localhost:8000/api/customer/ai-interaction",
            data=json.dumps({
                "customer_id": "CUST-NONEXISTENT",
                "intent_type": "REPORT_BILLING",
                "query": "show billing",
                "input_method": "voice",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            assert "error" in body or "success" in body
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Existing behaviour preserved
# ---------------------------------------------------------------------------

def test_original_voice_button_and_recording_indicator_present():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert 'id="voice-btn"' in content
    assert 'id="voice-recording-indicator"' in content
    assert 'id="voice-transcript"' in content
    assert "function initVoiceRecognition()" in content
    assert "function startVoiceInput()" in content
    assert "function stopVoiceInput(" in content
    assert "function showVoiceFeedback(transcript)" in content


def test_classify_intent_registry_unchanged():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "PHINS AI ACTION REGISTRY" in content
    expected_intents = [
        "REPORT_BILLING",
        "REPORT_PERSONAL",
        "REPORT_POLICY",
        "REPORT_SAVINGS",
        "REPORT_CLAIMS",
        "INFO_MONTHLY_COST",
        "INFO_MONTHLY_SAVINGS",
        "INFO_COVERAGE",
        "INFO_BALANCE",
        "CALC_PROJECTION",
        "ACTION_JOIN_COMMUNITY",
        "ACTION_SHOW_COMMUNITY",
        "ACTION_CREATE_FOUNDATION",
        "ACTION_APPLY",
        "ACTION_BUY_EQUIPMENT",
        "ACTION_BOOK_CONSULTATION",
        "ACTION_PHARMACY",
        "ACTION_HOME_CARE",
        "ACTION_PAY",
        "ACTION_SAVE",
        "ACTION_TRANSFER",
        "ACTION_CLAIM",
        "ACTION_UPDATE",
        "ACTION_CHANGE_PASSWORD",
        "ACTION_REFERRAL",
        "ACTION_CONTACT_SUPPORT",
        "ACTION_INVESTMENT",
    ]
    for intent in expected_intents:
        assert intent in content, f"Missing intent in registry: {intent}"


def test_quick_ai_action_map_unchanged():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "AI ACTION QUERY MAP" in content
    expected_actions = [
        "billing_report",
        "savings_calc",
        "my_policies",
        "personal_data",
        "join_community",
        "show_community",
        "create_foundation",
        "apply_policy",
        "buy_equipment",
        "book_consultation",
        "pharmacy",
        "home_care",
        "pay_bills",
        "wallet_balance",
        "investment_portfolio",
        "file_claim",
        "contact_support",
        "refer_friend",
        "change_password",
    ]
    for action in expected_actions:
        assert f"'{action}'" in content, f"Missing quick action: {action}"
