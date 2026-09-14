#!/usr/bin/env python3
"""
Agent evaluation CLI (A6) — golden sets and decision replay.

Read-only: runs the agents on committed fixtures and/or replays the logged
decisions an operator points it at. It never promotes thresholds; that is the
audited ``POST /api/admin/ai-agents/thresholds/promote`` route.

Usage:
    ./scripts/entrypoint.sh exec python3 scripts/run_agent_eval.py golden
        Run every ``tests/golden/<agent>/*.json`` fixture; exit 1 on any diff.
        ``--agent <id>`` restricts to one agent; ``--update`` rewrites the
        fixtures' ``expected`` from the live output (an intentional, reviewed
        change — commit the diff); ``--json`` prints the full report.

    python3 scripts/run_agent_eval.py replay ai_automation_controller \\
        [--decisions decisions.json] [--min-samples 20] [--target-precision 0.95]
        Replay ``underwrite`` decisions (from a JSON export of the decision
        log, or the in-process log when running inside the server) under the
        live ``ThresholdConfig`` and print the per-segment report + proposal.

    python3 scripts/run_agent_eval.py replay claims_bot [--records records.json]
        The Claims Bot authenticity calibration over ``claims_fraud``
        assessment records.

Exit codes: 0 ok, 1 golden diff / evaluation error, 2 usage.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('USE_DATABASE', 'false')
os.environ.setdefault('PHINS_TEST_MODE', 'true')


def _load_json(path):
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        for key in ('items', 'decisions', 'records'):
            if isinstance(data.get(key), list):
                return data[key]
    if not isinstance(data, list):
        raise SystemExit(f'{path}: expected a JSON list (or an object with items/decisions/records)')
    return data


def cmd_golden(args):
    from services import agent_eval
    if args.agent:
        report = {'agents': {args.agent: agent_eval.run_golden(args.agent, update=args.update)}}
        report['ok'] = report['agents'][args.agent]['ok']
        report['total'] = report['agents'][args.agent]['total']
        report['failed'] = (report['agents'][args.agent]['failed']
                            + report['agents'][args.agent]['errored'])
    else:
        report = agent_eval.run_all_golden(update=args.update)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        for agent_id, agent_report in sorted(report['agents'].items()):
            print(f"[{agent_id}] {agent_report['passed']} passed, {agent_report['failed']} failed, "
                  f"{agent_report['errored']} errored, {agent_report['updated']} updated "
                  f"({agent_report['total']} fixtures in {agent_report['fixtures_dir']})")
            for case in agent_report['cases']:
                if case['status'] in ('failed', 'error'):
                    print(f"  - {case['name']}: {case['status']}")
                    for diff in case.get('diffs', []):
                        print(f"      {diff['path']}: expected {diff['expected']!r}, got {diff['actual']!r}")
                    if case.get('error'):
                        print(f"      {case['error']}")
        verdict = 'OK' if report['ok'] else 'FAILED'
        print(f"golden sets: {verdict} ({report['total']} fixtures, {report['failed']} failing)")
    return 0 if report['ok'] else 1


def cmd_replay(args):
    from services import agent_eval
    kwargs = {}
    if args.agent == 'ai_automation_controller':
        if args.decisions:
            kwargs['decisions'] = _load_json(args.decisions)
        kwargs['min_samples'] = args.min_samples
        kwargs['target_precision'] = args.target_precision
        kwargs['include_implicit'] = not args.explicit_only
    elif args.agent == 'claims_bot':
        if args.records:
            kwargs['assessment_records'] = _load_json(args.records)
        if args.min_samples is not None:
            kwargs['min_labelled'] = args.min_samples
    try:
        report = agent_eval.evaluate(args.agent, **kwargs)
    except KeyError:
        print(f"no evaluator for {args.agent!r}; available: {', '.join(sorted(agent_eval.EVALUATORS))}",
              file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, default=str))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    golden = sub.add_parser('golden', help='run golden-set fixtures')
    golden.add_argument('--agent', help='restrict to one agent id')
    golden.add_argument('--update', action='store_true', help='rewrite fixtures from live output')
    golden.add_argument('--json', action='store_true', help='print the full JSON report')
    golden.set_defaults(func=cmd_golden)

    replay = sub.add_parser('replay', help='replay logged decisions against human outcomes')
    replay.add_argument('agent', help='agent id (ai_automation_controller | claims_bot)')
    replay.add_argument('--decisions', help='JSON export of decision-log records')
    replay.add_argument('--records', help='JSON export of claims_fraud assessment records')
    replay.add_argument('--min-samples', type=int, default=None)
    replay.add_argument('--target-precision', type=float, default=0.95)
    replay.add_argument('--explicit-only', action='store_true', help='count only human overrides as labels')
    replay.set_defaults(func=cmd_replay)

    args = parser.parse_args(argv)
    if args.command == 'replay' and args.agent == 'ai_automation_controller' and args.min_samples is None:
        args.min_samples = 20
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
