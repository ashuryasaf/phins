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


def test_mobile_menu_buttons_use_menu_label():
    for name in ("admin.html", "accountant-dashboard.html"):
        html = _read(name)
        assert 'class="mobile-menu-btn"' in html
        assert ">☰<" not in html
        assert ">Menu</button>" in html
