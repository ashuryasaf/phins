"""Static integrity checks for the restyled Apply for PHINS Coverage flow.

The apply flow was restyled to the navy/gold brand language (shield emblem
logo, gradient chrome, no emoji icons). These tests guard two things:

1. Branding: the shield logo and themed chrome are present and decorative
   emoji icons stay removed.
2. Data integrity: every form field id/name the submission pipeline in
   apply.js depends on is still present in the markup.
"""

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "web_portal" / "static"
APPLY_HTML = (STATIC_DIR / "apply.html").read_text(encoding="utf-8")
APPLY_JS = (STATIC_DIR / "apply.js").read_text(encoding="utf-8")
APPLY_CSS = (STATIC_DIR / "apply-styles.css").read_text(encoding="utf-8")

EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2705\u274C\u2757\u2B50\u23F0\u23F3\u26A0]"
)


class TestApplyPageBranding:
    def test_shield_logo_in_header_hero_and_success_modal(self):
        assert APPLY_HTML.count("/phins-logo.svg") >= 4  # favicon, header, hero, success
        assert "apply-brand-text" in APPLY_HTML
        assert 'class="auth-backdrop"' in APPLY_HTML

    def test_no_decorative_emoji_icons_remain(self):
        assert not EMOJI_PATTERN.search(APPLY_HTML), "apply.html should not contain emoji icons"
        assert not EMOJI_PATTERN.search(APPLY_JS), "apply.js should not inject emoji icons"

    def test_navy_gold_theme_palette_present(self):
        assert "--apply-gold" in APPLY_CSS
        assert "#060d1f" in APPLY_CSS  # deep navy base
        assert "Space Grotesk" in APPLY_CSS

    def test_card_type_badges_are_text_labels(self):
        for label in ("'VISA'", "'MC'", "'AMEX'", "'DISC'"):
            assert label in APPLY_JS

    def test_legal_links_preserved(self):
        assert "/privacy-policy.html" in APPLY_HTML
        assert "/terms-of-use.html" in APPLY_HTML


class TestApplyPageDataIntegrity:
    """Every field read by saveStepData()/handleSubmit() must still exist."""

    REQUIRED_IDS = [
        # step 1 — personal
        "first-name", "last-name", "email", "phone", "dob", "gender",
        "address", "city", "state", "zip", "occupation",
        # step 2 — coverage/allocation
        "policy-type", "coverage-slider", "coverage-amount-display",
        "allocation-slider", "protection-pct", "savings-pct",
        "wallet-pct", "investment-pct", "algo-pct",
        "wallet-bar", "investment-bar", "algo-bar", "total-allocation",
        "protection-monthly", "savings-monthly",
        "wallet-monthly", "investment-monthly", "algo-monthly",
        "monthly-premium", "quarterly-premium", "annual-premium",
        "premium-quote-meta", "savings-addon-breakdown",
        "savings-distribution-section",
        "summary-coverage", "summary-years",
        # step 3 — health
        "conditions-list", "surgery-list", "height", "weight",
        "medications", "bmi-value", "bmi-category",
        "file-drop-zone", "application-files", "uploaded-files-list",
        # step 4 — payment
        "card-number", "card-type-icon", "card-validation-msg",
        "cardholder-name", "expiry-month", "expiry-year", "cvv",
        "enable-health-wallet", "health-wallet-options",
        "monthly-deposit", "custom-deposit-group", "custom-deposit",
        # step 5 — review/submit
        "review-personal", "review-coverage", "review-health", "review-payment",
        "final-premium-amount", "final-period", "final-monthly", "final-quarterly",
        "health-wallet-summary", "final-wallet-deposit",
        "terms-agree", "accuracy-agree", "billing-agree",
        # navigation/success
        "customer-application-form", "prev-btn", "next-btn", "submit-btn",
        "success-message", "app-id", "policy-id", "success-premium",
    ]

    REQUIRED_NAMES = [
        "coverage-years", "savings-addon", "tobacco", "medical-conditions", "surgery",
        "hazardous", "family-history", "billing-frequency", "auto-pay",
    ]

    def test_all_form_ids_present(self):
        missing = [i for i in self.REQUIRED_IDS if f'id="{i}"' not in APPLY_HTML]
        assert not missing, f"apply.html is missing form ids: {missing}"

    def test_all_radio_checkbox_names_present(self):
        missing = [n for n in self.REQUIRED_NAMES if f'name="{n}"' not in APPLY_HTML]
        assert not missing, f"apply.html is missing input names: {missing}"

    def test_policy_type_default_unchanged(self):
        assert 'id="policy-type" value="phins_unified"' in APPLY_HTML

    def test_five_steps_and_progress_markers_present(self):
        for step in range(1, 6):
            assert f'data-step="{step}"' in APPLY_HTML

    def test_submission_endpoint_unchanged(self):
        assert "/api/policies/create" in APPLY_JS
        assert "/api/policies/quote" in APPLY_JS
        assert "application_channel: 'classic'" in APPLY_JS
        assert "savings_rate: currentSavingsRate()" in APPLY_JS
        assert "savings_formula: 'risk_premium_markup'" in APPLY_JS

    def test_scripts_still_wired(self):
        assert 'src="apply.js"' in APPLY_HTML
        assert "/unified-payment.js" in APPLY_HTML
        assert "/i18n.js" in APPLY_HTML

    def test_review_uses_kernel_amounts_without_rediscouning(self):
        assert "function applyKernelQuote(" in APPLY_JS
        assert "premiums.quarterly * 0.97" not in APPLY_JS
        assert "premiums.annual * 0.90" not in APPLY_JS
