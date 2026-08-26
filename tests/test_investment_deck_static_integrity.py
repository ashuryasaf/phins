"""Static integrity for the general investment deck.

The general deck is a counterpart-facing sibling of the detailed business plan:
same canonical ₪ book, but no ask / valuation / MOIC hero strip, no quarterly
forecast table, and no deal-structure section.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
DECK = STATIC / "internal" / "phins-investment-deck.html"
PITCH = STATIC / "pitch-dashboard.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_general_investment_deck_exists_and_is_branded():
    assert DECK.is_file()
    deck = _read(DECK)
    assert 'class="phins-letterhead"' in deck
    assert "/phins-logo.svg" in deck
    assert "Personal Health Insurance &amp; Savings · AI-Operated Insurance Platform" in deck
    assert "#c9a04e" in deck and "#0e2f63" in deck
    assert "print-color-adjust: exact" in deck
    assert "ui-clarity.js" in deck
    assert "Admin AI Mic" not in deck


def test_general_deck_omits_investment_hero_and_deal_section():
    deck = _read(DECK)
    assert "The ask (seed / build)" not in deck
    assert "Pre-money" not in deck
    assert "Post-money" not in deck
    assert "Investor stake" not in deck
    assert "Base-case investor MOIC" not in deck
    assert "Quarterly forecast" not in deck
    assert "The ask &amp; deal structures" not in deck
    assert 'id="bp-q-table"' not in deck
    assert 'id="bp-deal-body"' not in deck
    assert 'id="bp-kpi-ask"' not in deck
    assert 'id="bp-kpi-moic"' not in deck


def test_general_deck_shows_objectives_israel_launch_and_cash_flow():
    deck = _read(DECK)
    assert "Platform objectives" in deck
    assert "Israel launch" in deck
    assert "Annual cash flow" in deck
    assert "1 Jan 2027" in deck or "1 January 2027" in deck
    assert "Digital MGA" in deck
    assert 'id="deck-cf-table"' in deck
    assert 'id="deck-uof-table"' in deck
    assert 'id="deck-pnl-table"' in deck
    assert 'id="deck-chart-burn"' in deck


def test_general_deck_keeps_canonical_israel_book():
    deck = _read(DECK)
    assert "phins.investor.cfg.v1" in deck
    assert "/api/fx/rates" in deck
    assert "4518" in deck
    assert "0.25" in deck
    assert "24000" in deck and "94080" in deck and "230554" in deck
    assert "356110" in deck and "471621" in deck
    assert "32400000" in deck and "66420000" in deck
    # grouped use-of-funds still sums to the canonical shares
    assert "0.403333" in deck
    assert "0.233334" in deck
    assert "0.180000" in deck
    assert "0.066667" in deck
    assert "₪3.70" not in deck
    assert "1 USD = ₪3.70" not in deck


def test_general_deck_reads_configurator_presentation_controls():
    deck = _read(DECK)
    assert "deckHorizon" in deck
    assert "deckTableDetail" in deck
    assert "investor summary" in deck.lower() or "summary" in deck
    assert 'id="inv-deck-horizon"' not in deck  # controls live on the dashboard


def test_general_deck_hebrew_locale_for_ils():
    deck = _read(DECK)
    assert "I18N_HE" in deck
    assert "applyStaticI18n" in deck
    assert 'html[dir="rtl"]' in deck
    assert "יעדי הפלטפורמה" in deck
    assert "השקה בישראל" in deck
    assert "תזרים שנתי" in deck


def test_pitch_dashboard_wires_general_deck_configurator():
    pd = _read(PITCH)
    assert "/internal/phins-investment-deck.html" in pd
    assert 'id="investor-deck-config"' in pd
    assert 'id="inv-deck-horizon"' in pd
    assert 'id="inv-deck-detail"' in pd
    meeting = pd.split('id="investor-meeting-section"', 1)[1].split('id="partner-meetings-13jul"', 1)[0]
    assert "Open General Investment Deck" in meeting or "Open general deck" in meeting
    assert "no ask · no deal terms" in meeting
    assert "deckHorizon" in pd
    assert "deckTableDetail" in pd
    assert '"investor-deck-config": "investor-meeting-section"' in pd
