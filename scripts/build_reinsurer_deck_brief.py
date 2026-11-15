#!/usr/bin/env python3
"""
Build the Swiss Re Israel meeting pack (8 December 2026) from the plan model.
============================================================================
Writes ``web_portal/static/investor-docs/swiss-re-israel-meeting-8dec2026-deck.md``
and its Hebrew edition ``…-deck.he.md`` from
``services/reinsurer_meeting_deck.render_markdown(compute_plan(), lang=…)``: the
twelve slides with every placeholder filled, the spoken paragraph of each
15-second scene, the ceded line for 2027–2031, the quota-share scenarios, the
adjustable reinsurance factors and the data-integrity statement. Both
editions bind to the same plan dict and the same content hash.
``scripts/generate_investor_pdfs.py`` renders each markdown into the branded
PDF and the designed HTML edition.

The output is deterministic for a given repository state, so the committed
copy can be checked against a fresh render (``--check``); the contract test
is ``tests/test_reinsurer_meeting_deck.py``. The script reads no platform
data, writes nothing but this file, and never writes the plan.

Usage:
    python3 scripts/build_reinsurer_deck_brief.py            # rewrite the file
    python3 scripts/build_reinsurer_deck_brief.py --check    # exit 1 when stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.business_plan_model import compute_plan  # noqa: E402
from services.reinsurer_meeting_deck import render_markdown  # noqa: E402

DOCS = ROOT / "web_portal" / "static" / "investor-docs"
MD_PATH = DOCS / "swiss-re-israel-meeting-8dec2026-deck.md"
MD_PATH_HE = DOCS / "swiss-re-israel-meeting-8dec2026-deck.he.md"


def outputs() -> dict[Path, str]:
    plan = compute_plan()
    return {
        MD_PATH: render_markdown(plan),
        MD_PATH_HE: render_markdown(plan, lang="he"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="report a stale output and exit non-zero without writing")
    args = parser.parse_args(argv)
    stale = 0
    for path, text in outputs().items():
        rel = path.relative_to(ROOT)
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == text:
            print(f"ok: {rel}")
            continue
        stale += 1
        if args.check:
            print(f"stale: {rel}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote: {rel} ({len(text.encode('utf-8')) / 1024:.0f} KB)")
    if args.check and stale:
        print(f"{stale} stale meeting-pack output(s); run scripts/build_reinsurer_deck_brief.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
