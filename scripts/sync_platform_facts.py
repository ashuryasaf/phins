#!/usr/bin/env python3
"""
Reconcile the static module-count fallbacks on investor surfaces with the
live ``services/*.py`` count.

Investor / partner pages bind ``<span data-live-modules>N</span>`` to
``GET /api/platform/facts`` through ``web_portal/static/platform-facts.js``,
but the ``N`` written in the HTML is the print / no-JS fallback and drifts
every time a service module is added or removed. This script rewrites every
such fallback (plus ``FALLBACK_MODULES`` in ``platform-facts.js`` and the
"**N deployed modules** (live count ...)" line of the investor-docs briefs)
to the same number ``web_portal/server.py:count_service_modules()`` reports.

Usage:

    python3 scripts/sync_platform_facts.py           # rewrite drifted files
    python3 scripts/sync_platform_facts.py --check   # exit 1 when drift exists

Contract tests: ``tests/test_platform_facts.py``,
``tests/test_document_branding.py::test_deck_module_count_claims_match_service_layer``,
``tests/test_partner_meetings_13jul_static_integrity.py``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "web_portal" / "static"

# Static surfaces that carry a data-live-modules fallback.
SURFACES = [
    "pitch-dashboard.html",
    "unicorn-investor-deck.html",
    "unicorn-executive-summary.html",
    "seed-investor-deck.html",
    "legal/term-sheet.html",
    "internal/phins-ai-tech-partner-business-plan.html",
    "internal/phins-insurer-mga-business-plan.html",
]
BRIEFS = [
    "investor-docs/regulatory-meeting-27jul-brief.md",
    "investor-docs/regulatory-preruling-avi-ovadia-brief.md",
]
FACTS_JS = "platform-facts.js"

# `data-live-modules>100<` and `data-live-modules ...>100<` (attribute may not
# be last, e.g. `style="..." data-live-modules>100</div>`).
LIVE_MODULES_RE = re.compile(r"(data-live-modules(?:\s+[^>]*)?>)(\d+)(<)")
FALLBACK_JS_RE = re.compile(r"(var FALLBACK_MODULES = )(\d+)(;)")
BRIEF_RE = re.compile(r"(\*\*)(\d+)( deployed modules\*\* \(live count)")


def count_service_modules(root: Path | None = None) -> int:
    """Same rule as ``web_portal.server.count_service_modules``."""
    services_dir = (root or ROOT_DIR) / "services"
    try:
        names = os.listdir(services_dir)
    except OSError:
        return 0
    return sum(1 for n in names if n.endswith(".py") and not n.startswith("."))


def _rewrite(text: str, pattern: re.Pattern[str], count: int) -> tuple[str, int]:
    changed = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal changed
        if int(m.group(2)) != count:
            changed += 1
        return f"{m.group(1)}{count}{m.group(3)}"

    return pattern.sub(repl, text), changed


def targets() -> list[tuple[Path, re.Pattern[str]]]:
    out = [(STATIC_DIR / rel, LIVE_MODULES_RE) for rel in SURFACES]
    out.append((STATIC_DIR / FACTS_JS, FALLBACK_JS_RE))
    out += [(STATIC_DIR / rel, BRIEF_RE) for rel in BRIEFS]
    return out


def sync(check: bool = False, root: Path | None = None) -> int:
    count = count_service_modules(root)
    if count <= 0:
        print("error: no service modules found under services/", file=sys.stderr)
        return 2
    drift = 0
    for path, pattern in targets():
        if not path.is_file():
            print(f"warning: missing {path.relative_to(ROOT_DIR)}", file=sys.stderr)
            continue
        original = path.read_text(encoding="utf-8")
        updated, changed = _rewrite(original, pattern, count)
        if not pattern.search(original):
            print(f"warning: no module-count fallback in {path.relative_to(ROOT_DIR)}",
                  file=sys.stderr)
            continue
        if changed:
            drift += changed
            rel = path.relative_to(ROOT_DIR)
            if check:
                print(f"drift: {rel} ({changed} fallback(s) != {count})")
            else:
                path.write_text(updated, encoding="utf-8")
                print(f"updated: {rel} ({changed} fallback(s) -> {count})")
    if check:
        if drift:
            print(f"{drift} stale module-count fallback(s); run "
                  "scripts/sync_platform_facts.py to rewrite them")
            return 1
        print(f"ok: all module-count fallbacks match services/ ({count})")
        return 0
    print(f"service modules: {count}; rewrote {drift} fallback(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="report drift and exit non-zero without writing")
    args = parser.parse_args(argv)
    return sync(check=args.check)


if __name__ == "__main__":
    sys.exit(main())
