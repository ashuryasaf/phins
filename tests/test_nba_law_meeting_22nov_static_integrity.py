"""NBA Law legal agenda, Sunday 22 November 2026, 12:00–13:00.

The bar, the brief, and the diary row state only canonical plan defaults and
platform defaults, and the diary keeps a browser's saved rows.
"""

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services.business_plan_model import compute_plan

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"
DOCS = STATIC / "investor-docs"
SECTION_ID = "nba-law-meeting-22nov"
STEM = "nba-law-meeting-22nov-brief"
COUNTERPARTY = (
    "NBA Law — Naschitz, Brandes, Amir & Co. (introduced by Adv. Keshet "
    "Sirota-Leviner, Partner, Head of Tax, at the 25 October 2026 introduction)"
)


def _html() -> str:
    return (STATIC / "pitch-dashboard.html").read_text(encoding="utf-8")


def _section(html: str) -> str:
    start = html.index(f'<section id="{SECTION_ID}"')
    end = html.index("</section>", start)
    return html[start:end]


def _brief() -> str:
    return (DOCS / f"{STEM}.md").read_text(encoding="utf-8")


def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_section_is_wired_into_the_dashboard():
    html = _html()
    assert f'<a href="#{SECTION_ID}" class="pitch-nav-link">NBA Law 22.11</a>' in html
    assert f'"{SECTION_ID}",' in html
    order = [
        html.index('<section id="reinsurer-ceo-assessment-nov2026"'),
        html.index(f'<section id="{SECTION_ID}"'),
        html.index('<section id="swissre-israel-meeting-8dec2026"'),
    ]
    assert order == sorted(order)
    card = html[html.index('id="unified-business-plan-card"'):]
    card = card[:card.index("</section>")]
    assert f'href="#{SECTION_ID}"' in card
    assert html.count(f'href="#{SECTION_ID}"') >= 4


def test_meeting_facts_and_the_five_issues():
    section = _section(_html())
    assert "Sunday 22 November 2026 · 12:00–13:00 · 60 minutes" in section
    assert "Naschitz, Brandes, Amir &amp; Co." in section
    assert "Keshet Sirota-Leviner" in section
    assert 'href="#nba-law-meeting-25oct"' in section
    for n in range(1, 6):
        assert f'id="nba-22nov-issue-{n}"' in section
    issue_1 = section[section.index('id="nba-22nov-issue-1"'):section.index('id="nba-22nov-issue-2"')]
    for topic in ("Founders", "Seed", "VC and Series A", "Investor NDAs", "Customers", "Employees", "Privacy"):
        assert topic in issue_1, topic
    issue_2 = section[section.index('id="nba-22nov-issue-2"'):section.index('id="nba-22nov-issue-3"')]
    for topic in ("Code ownership", "Policy and process", "Trademark", "NDA"):
        assert topic in issue_2, topic
    assert "Issue 3 · tax" in section
    assert "Issue 4 · Israeli and segmented regulation" in section
    assert "Issue 5 · commercial contracts with the insurer and the reinsurer" in section
    for slot in ("12:00–12:05", "12:05–12:17", "12:17–12:27", "12:27–12:37",
                 "12:37–12:47", "12:47–12:55", "12:55–13:00"):
        assert slot in section
    for href in (f"/investor-docs/{STEM}.html", f"/investor-docs/{STEM}.pdf",
                 "#unified-business-plan-card", "/business-plan.html",
                 "#swissre-israel-meeting-8dec2026", "#il-meeting-diary"):
        assert f'href="{href}"' in section, href


def test_every_cited_artefact_exists():
    section = _section(_html())
    brief = _brief()
    for path in set(re.findall(r'href="(/(?:legal/)?[a-z0-9-]+\.html)"', section)):
        assert (STATIC / path.lstrip("/")).is_file(), path
    for path in set(re.findall(r"`(/(?:legal/)?[a-z0-9-]+\.html)`", brief)):
        assert (STATIC / path.lstrip("/")).is_file(), path
    for anchor in ("nba-law-meeting-25oct", "regulatory-preruling-avi-ovadia",
                   "swissre-israel-meeting-8dec2026", "unified-business-plan-card"):
        assert f'id="{anchor}"' in _html()


def test_figures_are_canonical_plan_and_platform_defaults():
    plan = compute_plan()
    assert plan["plan_version"] == "unified-2026.10-v1" and plan["canonical"]
    funding = plan["funding"]
    factors = {f["id"]: f["default"] for f in plan["factors"]}
    y2027 = plan["anchor_book"]["rows"][0]
    carrier = plan["carrier_view"]["rows"][0]
    assert factors["annual_premium"] == 4518
    assert factors["cession_rate"] == 0.18 and factors["ceding_commission"] == 0.25
    assert y2027["risk_gwp"] == 54_216_000
    assert carrier["ceded_premium"] == 9_758_880 == round(54_216_000 * 0.18)
    assert (funding["seed"], funding["pre_money"], funding["post_money"]) == (6_000_000, 24_000_000, 30_000_000)
    assert funding["series_a_indicative"] == 18_000_000
    uses = [funding["use_of_funds"][k]["amount"] for k in (
        "product_technology", "regulatory_actuarial", "distribution_partnerships", "operations_reserve")]
    assert uses == [2_400_000, 1_200_000, 1_500_000, 900_000] and sum(uses) == 6_000_000

    from services.referral_reward_service import default_config
    from services.wallet_withdrawal_service import DEFAULT_RETENTION_DAYS

    referral = default_config()
    assert referral["fee_cents"] == 65_000 and referral["hold_months"] == 3 and referral["max_layers"] == 3
    assert DEFAULT_RETENTION_DAYS == 3

    section = _section(_html())
    brief = _brief()
    for text in (section, brief):
        for needle in ("unified-2026.10-v1", "4,518", "54,216,000", "6,000,000", "24,000,000",
                       "30,000,000", "18,000,000", "9,758,880", "$650", "3 days"):
            assert needle in text, needle
    for needle in ("2,400,000", "1,200,000", "1,500,000", "900,000"):
        assert needle in section and needle in brief


def test_no_tax_rate_or_outcome_is_stated():
    section = _section(_html())
    brief = _brief()
    visible = re.sub(r"<[^>]+>", " ", section)
    assert set(re.findall(r"\d+(?:\.\d+)?%", visible)) <= {"25%", "75%", "18%"}
    assert set(re.findall(r"\d+(?:\.\d+)?%", brief)) <= {"25%", "75%", "18%", "20%"}
    do_not_open = brief.index("## Do not open")
    claims_text = brief[:do_not_open] + brief[brief.index("## Decision outputs"):]
    assert "A claim that the Authority has approved the product or the MGA." in brief[do_not_open:]
    for text, checked in ((section, section), (brief, claims_text)):
        assert "No legal conclusion" in text
        assert "does not write the platform ledger" in text
        lowered = checked.lower()
        for claim in ("engagement is signed", "nba law is retained", "has approved", "approved the product"):
            assert claim not in lowered, claim


def test_brief_is_registered_and_rendered():
    mod = _generator()
    md_name = f"investor-docs/{STEM}.md"
    assert (md_name, f"investor-docs/{STEM}.pdf",
            "PHINS — NBA Law Legal Agenda (22 November 2026) · "
            "Naschitz Brandes Amir, introduced by Adv. Keshet Sirota-Leviner") in mod.DOCUMENTS
    meta = mod.DESIGNED_BRIEFS[md_name]
    assert meta["html"] == f"investor-docs/{STEM}.html"
    brief = _brief()
    assert "Sunday 22 November 2026" in brief and "12:00–13:00" in brief
    for heading in ("## Issue 1 — Association and contracts", "## Issue 2 — Intellectual property",
                    "## Issue 3 — Tax", "## Issue 4 — Israeli and segmented regulation",
                    "## Issue 5 — Commercial contracts with the insurer and the reinsurer"):
        assert heading in brief
    html_doc = (DOCS / f"{STEM}.html").read_text(encoding="utf-8")
    assert "linear-gradient(135deg, #060d1f 0%, #0e2f63 46%, #123f82 100%)" in html_doc
    assert 'class="phins-doc-logo"' in html_doc
    assert "Space Grotesk" in html_doc
    pdf = (DOCS / f"{STEM}.pdf").read_bytes()
    assert pdf[:5] == b"%PDF-" and b"%%EOF" in pdf[-2048:]


def test_designed_html_is_a_fresh_render_of_the_markdown(tmp_path):
    mod = _generator()
    md_name = f"investor-docs/{STEM}.md"
    title = next(t for src, _pdf, t in mod.DOCUMENTS if src == md_name)
    out = tmp_path / "brief.html"
    mod.write_designed_brief(str(DOCS / f"{STEM}.md"), str(out), mod.DESIGNED_BRIEFS[md_name], title)
    assert out.read_text(encoding="utf-8") == (DOCS / f"{STEM}.html").read_text(encoding="utf-8")


def test_diary_row_on_v11():
    html = _html()
    assert 'var STORAGE_ID = "phins.il.meeting.diary.v11"' in html
    assert 'var PREVIOUS_STORAGE_ID = "phins.il.meeting.diary.v10"' in html
    assert f'var NBA_22NOV_COUNTERPARTY = "{COUNTERPARTY}"' in html
    assert 'date: "2026-11-22", time: "12:00–13:00 · 60 min", counterparty: NBA_22NOV_COUNTERPARTY' in html
    assert 'localStorage.getItem("phins.il.meeting.diary.v11") || localStorage.getItem("phins.il.meeting.diary.v10")' in html


def _run_diary_load(saved: dict) -> list:
    """Run the diary's own buildDefaults / carryForward / load against a fake localStorage."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    html = _html()
    start = html.index('var STORAGE_ID = "phins.il.meeting.diary.v11"')
    end = html.index("function save(rows)", start)
    script = (
        "var store = " + json.dumps(saved) + ";\n"
        "var localStorage = { getItem: function (k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; } };\n"
        "var document = { getElementById: function () { return null; } };\n"
        + html[start:end]
        + "\nprocess.stdout.write(JSON.stringify(load()));\n"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def test_saved_v10_rows_carry_forward_with_only_the_new_row():
    edited = [
        {"date": "2026-11-12", "time": "10:00", "counterparty": "Mr. Yosi Ben Zvi — CEO, D.N.R. Insurance Agency",
         "location": "Edited", "purpose": "Edited by the user", "status": "Held"},
        {"date": "2026-12-08", "time": "TBC · 60 min", "counterparty": "Mr. Hillel Damelin — Regional CEO Israel, Swiss Re",
         "location": "TBC", "purpose": "kept", "status": "Scheduled"},
    ]
    rows = _run_diary_load({"phins.il.meeting.diary.v10": json.dumps(edited)})
    assert len(rows) == 3
    assert rows[0] == edited[0] and rows[2] == edited[1]
    assert rows[1]["date"] == "2026-11-22" and rows[1]["counterparty"] == COUNTERPARTY
    assert rows[1]["time"] == "12:00–13:00 · 60 min" and rows[1]["status"] == "Scheduled"

    again = _run_diary_load({"phins.il.meeting.diary.v10": json.dumps(rows)})
    assert again == rows

    v11 = [edited[0]]
    assert _run_diary_load({
        "phins.il.meeting.diary.v11": json.dumps(v11),
        "phins.il.meeting.diary.v10": json.dumps(edited),
    }) == v11


def test_fresh_browser_gets_the_full_seed():
    rows = _run_diary_load({})
    dates = [r["date"] for r in rows]
    assert dates.count("2026-11-22") == 1
    assert dates.index("2026-11-12") < dates.index("2026-11-22") < dates.index("2026-12-08")
    nba_25 = next(r for r in rows if r["date"] == "2026-10-25")
    assert nba_25["status"] == "Held"
