#!/usr/bin/env python3
"""Run the ERP/MGA integrity 1–100 scorecard and print a review report.

Usage:
  python3 scripts/run_erp_integrity_scorecard.py
  python3 scripts/run_erp_integrity_scorecard.py --json /tmp/scorecard.json
  python3 scripts/run_erp_integrity_scorecard.py --markdown /tmp/scorecard.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.erp.integrity_scorecard import (  # noqa: E402
    compute_integrity_scorecard,
    render_scorecard_markdown,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT))
    parser.add_argument('--json', dest='json_path', default='')
    parser.add_argument('--markdown', dest='md_path', default='')
    args = parser.parse_args(argv)

    report = compute_integrity_scorecard(repo_root=args.repo_root)
    md = render_scorecard_markdown(report)
    print(md)
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        print(f'Wrote JSON → {path}', file=sys.stderr)
    if args.md_path:
        path = Path(args.md_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md, encoding='utf-8')
        print(f'Wrote Markdown → {path}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
