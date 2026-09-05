"""Operational dashboards keep unified PHINS chrome and no decorative emoji."""

from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"

OPERATIONAL = [
    "dashboard.html",
    "admin.html",
    "accountant-dashboard.html",
    "actuary-dashboard.html",
    "billing.html",
    "claims-adjuster-dashboard.html",
    "documents.html",
]

# Decorative leftovers that the unified design removes. Hamburger ☰ is
# converted to the word Menu, so it must not remain either.
DINGBAT = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u23F0-\u23F3\u25B6\u21A9\u2630]"
)


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_operational_pages_use_phins_chrome():
    for name in OPERATIONAL:
        html = _read(name)
        assert 'href="/phins-theme.css"' in html, name
        assert "/phins-logo.svg" in html, name


def test_operational_pages_have_no_decorative_dingbats():
    leftovers = []
    for name in OPERATIONAL:
        for line_no, line in enumerate(_read(name).splitlines(), 1):
            if DINGBAT.search(line):
                leftovers.append(f"{name}:{line_no}: {line.strip()[:140]}")
    assert leftovers == [], "decorative symbols remain:\n" + "\n".join(leftovers)


def test_shared_payment_and_voice_scripts_have_no_decorative_emoji():
    leftovers = []
    for name in ("unified-payment.js", "ui-clarity.js"):
        for line_no, line in enumerate(_read(name).splitlines(), 1):
            if DINGBAT.search(line):
                leftovers.append(f"{name}:{line_no}: {line.strip()[:140]}")
    assert leftovers == [], "decorative symbols remain:\n" + "\n".join(leftovers)


def test_mobile_menu_buttons_use_menu_label():
    for name in ("admin.html", "accountant-dashboard.html"):
        html = _read(name)
        assert 'class="mobile-menu-btn"' in html
        assert ">☰<" not in html
        assert ">Menu</button>" in html


AUTH_AND_LANDING = [
    "login.html",
    "register.html",
    "index.html",
    "apply.html",
    "apply-chat.html",
    "agent-portal.html",
    "forgot-password.html",
    "cyber-security.html",
    "nda.html",
    "phins-risk-1pager-fefferman.html",
    "phins-risk-1pager-goldsobel.html",
]


def test_auth_and_landing_pages_use_phins_logo_and_fonts():
    for name in AUTH_AND_LANDING:
        html = _read(name)
        assert "/phins-logo.svg" in html, name
        assert "Inter" in html, name
        assert ("Space Grotesk" in html) or ("Space+Grotesk" in html), name


def test_auth_and_landing_pages_have_no_decorative_dingbats():
    leftovers = []
    for name in AUTH_AND_LANDING:
        for line_no, line in enumerate(_read(name).splitlines(), 1):
            if DINGBAT.search(line):
                leftovers.append(f"{name}:{line_no}: {line.strip()[:140]}")
    assert leftovers == [], "decorative symbols remain:\n" + "\n".join(leftovers)


def test_copilot_chrome_nits_remove_empty_icons_and_variation_selectors():
    """Operational leftovers from emoji stripping: no dead icon helpers or VS16."""
    cyber = _read("cyber-security.html")
    assert "function findingIcon" not in cyber
    assert "ai-finding-icon" not in cyber

    register = _read("register.js")
    assert "Invitation code detected!" in register
    assert "\ufe0f Invitation code detected" not in register
    assert "Unable to validate code" in register
    assert "\ufe0f Unable to validate code" not in register

    trading = _read("trading-terminal.html")
    assert "statusIcon" not in trading

    unicorn = _read("unicorn-executive-summary.html")
    assert ">Print / PDF</button>" in unicorn
    assert "\ufe0f Print / PDF" not in unicorn

    video = _read("video-agents.html")
    assert "const dot =" not in video
    assert "connected" in video
    assert "unavailable" in video
