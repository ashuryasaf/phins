from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "web_portal" / "static"
ADMIN_PATH = STATIC_DIR / "admin.html"
DASHBOARD_PATH = STATIC_DIR / "dashboard.html"
BILLING_PATH = STATIC_DIR / "billing.html"
AI_REPORT_PATH = STATIC_DIR / "customer-ai-report.html"

NAVY_GRADIENT = "linear-gradient(135deg, #060d1f 0%, #0d1b3e 100%)"


def test_admin_voice_input_primes_mic_permission_and_maps_not_allowed():
    content = ADMIN_PATH.read_text(encoding="utf-8")

    # Permission is requested via getUserMedia before recognition.start(), so
    # the browser prompts instead of silently failing with "not-allowed".
    assert "async function ensureAdminAssistantMicPermission()" in content
    assert "navigator.mediaDevices.getUserMedia({ audio: true })" in content
    assert "async function startAdminAssistantVoiceInput()" in content
    assert "const micAllowed = await ensureAdminAssistantMicPermission();" in content

    # "not-allowed" (and its variants) render actionable guidance, never the
    # raw error string.
    assert "event.error === 'not-allowed' || event.error === 'service-not-allowed'" in content
    assert "Microphone blocked — click the padlock/mic icon in the address bar" in content
    assert "event.error === 'audio-capture'" in content
    assert "event.error !== 'aborted'" in content


def test_customer_voice_input_primes_mic_permission_and_maps_not_allowed():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "async function ensureMicPermission()" in content
    assert "navigator.mediaDevices.getUserMedia({ audio: true })" in content
    assert "async function startVoiceInput()" in content
    assert "const micAllowed = await ensureMicPermission();" in content

    assert "event.error === 'not-allowed' || event.error === 'service-not-allowed'" in content
    assert "Microphone blocked — click the padlock/mic icon in the address bar" in content
    assert "event.error === 'audio-capture'" in content
    assert "event.error !== 'aborted'" in content

    # Voice errors surface even when the assistant panel is minimized: the
    # response renderer auto-expands the panel before writing feedback.
    assert (
        "if (panel && panel.dataset.minimized === 'true' && typeof toggleAIPanel === 'function') {"
        in content
    )


def test_customer_dashboard_uses_brand_navy_and_clean_labels():
    content = DASHBOARD_PATH.read_text(encoding="utf-8")

    # Hero info panel and referral program carry the deep-navy brand gradient.
    assert content.count(NAVY_GRADIENT) >= 2
    assert "#ff6b35 0%, #f7931e 100%" not in content   # orange referrals gone
    assert "#1a237e 0%, #283593 50%" not in content    # indigo info panel gone
    assert "#667eea" not in content                    # purple accents gone

    # Brand display type for headings.
    assert "font-family: 'Space Grotesk', 'Inter', sans-serif;" in content

    # Nav operational tabs read as clean text.
    assert '<a href="/savings-portfolio.html">Investments</a>' in content
    assert '<a href="/dashboard.html#referrals">Referrals</a>' in content
    assert '<a href="/foundation-dashboard.html">Community</a>' in content
    assert "Welcome back, <span id=\"username\">Customer</span></h1>" in content


def test_other_customer_pages_dropped_offbrand_purple_and_indigo():
    billing = BILLING_PATH.read_text(encoding="utf-8")
    assert "#667eea" not in billing
    assert "#764ba2" not in billing

    report = AI_REPORT_PATH.read_text(encoding="utf-8")
    assert NAVY_GRADIENT in report
    assert "#1a237e 0%, #283593 50%" not in report
