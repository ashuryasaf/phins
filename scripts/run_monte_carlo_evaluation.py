#!/usr/bin/env python3
"""
Run the PHINS Monte Carlo methodology evaluation from the command line.

    python3 scripts/run_monte_carlo_evaluation.py --lives 20000 --trials 2000 \
        --seed 20260911 --out /tmp/mc_report.json

The run is read-only: it reads the live actuarial tables / underwriting
config / claims-bot constants / AI thresholds, generates a synthetic
population, and writes a JSON report (hash-sealed ``integrity`` block).
Nothing in the platform is modified. Use ``--summary`` to print the findings
table instead of the full JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument("--lives", type=int, default=5000)
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--horizon-years", type=int, default=5)
    parser.add_argument("--bootstrap", type=int, default=300)
    parser.add_argument("--modules", default="risk,underwriting,actuarial,claims,sales,ai")
    parser.add_argument("--world", action="append", default=[],
                        help="override a WorldAssumptions field, e.g. --world smoker_mortality_rr=1.5")
    parser.add_argument("--out", help="write the full JSON report to this path")
    parser.add_argument("--summary", action="store_true", help="print findings instead of JSON")
    args = parser.parse_args()

    from services.monte_carlo_evaluation_service import (
        EvaluationParams, WorldAssumptions, run_evaluation,
    )

    world = WorldAssumptions()
    for item in args.world:
        name, _, value = item.partition("=")
        if not hasattr(world, name):
            parser.error(f"unknown world assumption: {name}")
        setattr(world, name, float(value))

    params = EvaluationParams(
        seed=args.seed, lives=args.lives, trials=args.trials,
        horizon_years=args.horizon_years, bootstrap_samples=args.bootstrap,
        modules=tuple(m.strip() for m in args.modules.split(",") if m.strip()),
        world=world,
    )
    report = run_evaluation(params)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
    if args.summary or args.out:
        integrity = report["integrity"]
        print(f"engine={report['engine_version']} seed={integrity['deterministic_seed']} "
              f"duration={integrity['duration_seconds']}s results_sha256={integrity['results_sha256']}")
        for finding in report["findings"]:
            print(f"[{finding['severity']:>8}] {finding['area']:<12} {finding['statement']}")
        if args.out:
            print(f"report written to {args.out}")
    else:
        print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
