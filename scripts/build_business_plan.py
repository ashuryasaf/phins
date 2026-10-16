#!/usr/bin/env python3
"""
Build the unified PHINS business plan surfaces from the one planning model.
==========================================================================
Writes, from ``services/business_plan_model.py`` through
``services/business_plan_document.py``:

* ``web_portal/static/business-plan.html`` — the live, adjustable edition
  (PHINS letterhead, factor panel, ``data-bp`` bindings to
  ``GET /api/business-plan/model``), with every figure baked in as the
  print / no-JS fallback at default factors;
* ``web_portal/static/investor-docs/phins-unified-business-plan.md`` — the
  portable edition that ``scripts/generate_investor_pdfs.py`` renders into
  the branded PDF.

Both outputs are deterministic for a given repository state, so a committed
copy can be checked against a fresh render (``--check``); the contract test is
``tests/test_business_plan.py``. The script reads no platform data and writes
nothing but these two files.

Usage:
    python3 scripts/build_business_plan.py            # rewrite both files
    python3 scripts/build_business_plan.py --check    # exit 1 when stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.business_plan_document import render_html, render_markdown  # noqa: E402
from services.business_plan_model import compute_plan  # noqa: E402

STATIC = ROOT / "web_portal" / "static"
HTML_PATH = STATIC / "business-plan.html"
MD_PATH = STATIC / "investor-docs" / "phins-unified-business-plan.md"


def outputs() -> dict[Path, str]:
    plan = compute_plan()
    return {HTML_PATH: render_html(plan), MD_PATH: render_markdown(plan)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="report stale outputs and exit non-zero without writing")
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
        print(f"{stale} stale business-plan output(s); run scripts/build_business_plan.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
