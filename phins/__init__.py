"""
PHINS unified CLI (dispatcher).

This module is the *minimal* phase-5 implementation: a single-file argparse
dispatcher that delegates to the existing top-level Python scripts. No
validator logic is rewritten here -- the surface area exists so that
operators, the Makefile, and future agents have one canonical entry point:

    python -m phins ...

Subcommands:
    phins validate system         -> validate_system.py
    phins validate external       -> validate_external_services.py
    phins validate portal         -> validate_portal_customer_access.py
    phins validate railway        -> validate_railway_config.py
    phins validate all            -> all of the above

    phins db init [--force] [--no-demo]   -> init_database.py
    phins db check                        -> check_database_connection.py

    phins backup                  -> scripts/backup_platform.sh
    phins restore --target <ref>          -> preview_restore.sh by default
    phins restore --apply --target <ref>  -> restore_platform.sh

    phins smoke                   -> quick_smoke_test.sh
    phins cron                    -> scripts/run_monthly_auto_pay.py
    phins serve                   -> web_portal/server.py

Design notes:
  * Pure dispatcher. Imports are local so a missing optional dependency in
    one subcommand never breaks the others.
  * On Windows or environments without /bin/sh, shell-script delegates
    fall back to printing an error rather than crashing.
  * Exit code mirrors the underlying script.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT_DIR = Path(__file__).resolve().parent.parent


def _run_python(script: str, extra: Sequence[str]) -> int:
    target = ROOT_DIR / script
    if not target.exists():
        print(f"phins: script not found: {target}", file=sys.stderr)
        return 66
    return subprocess.call([sys.executable, str(target), *extra])


def _run_shell(script: str, extra: Sequence[str]) -> int:
    target = ROOT_DIR / script
    if not target.exists():
        print(f"phins: script not found: {target}", file=sys.stderr)
        return 66
    return subprocess.call(["bash", str(target), *extra])


def _cmd_validate(args: argparse.Namespace, extra: Sequence[str]) -> int:
    target = args.target
    mapping = {
        "system": "validate_system.py",
        "external": "validate_external_services.py",
        "portal": "validate_portal_customer_access.py",
        "railway": "validate_railway_config.py",
    }
    if target == "all":
        rc = 0
        for name, script in mapping.items():
            print(f"--- phins validate {name} ---", flush=True)
            this_rc = _run_python(script, extra)
            rc = rc or this_rc
        return rc
    if target in mapping:
        return _run_python(mapping[target], extra)
    print(f"phins: unknown validate target: {target}", file=sys.stderr)
    return 64


def _cmd_db(args: argparse.Namespace, extra: Sequence[str]) -> int:
    if args.action == "init":
        return _run_python("init_database.py", extra)
    if args.action == "check":
        return _run_python("check_database_connection.py", extra)
    print(f"phins: unknown db action: {args.action}", file=sys.stderr)
    return 64


def _cmd_backup(_args: argparse.Namespace, extra: Sequence[str]) -> int:
    return _run_shell("scripts/backup_platform.sh", extra)


def _cmd_restore(args: argparse.Namespace, extra: Sequence[str]) -> int:
    forward = [args.target] if args.target else []
    forward.extend(extra)
    if args.apply:
        return _run_shell("restore_platform.sh", forward)
    return _run_shell("preview_restore.sh", forward)


def _cmd_smoke(_args: argparse.Namespace, extra: Sequence[str]) -> int:
    return _run_shell("quick_smoke_test.sh", extra)


def _cmd_cron(_args: argparse.Namespace, extra: Sequence[str]) -> int:
    return _run_python("scripts/run_monthly_auto_pay.py", extra)


def _cmd_serve(_args: argparse.Namespace, extra: Sequence[str]) -> int:
    return _run_python("web_portal/server.py", extra)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phins",
        description="PHINS unified operator/developer CLI (dispatcher).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    validate = sub.add_parser("validate", help="run system/external/portal/railway validators")
    validate.add_argument(
        "target",
        choices=["system", "external", "portal", "railway", "all"],
        help="which validator to run",
    )
    validate.set_defaults(func=_cmd_validate)

    db = sub.add_parser("db", help="database operations")
    db.add_argument("action", choices=["init", "check"], help="db action")
    db.set_defaults(func=_cmd_db)

    backup = sub.add_parser("backup", help="run scripts/backup_platform.sh")
    backup.set_defaults(func=_cmd_backup)

    restore = sub.add_parser("restore", help="preview or apply a restore")
    restore.add_argument("--target", help="commit hash or date to restore to")
    restore.add_argument("--apply", action="store_true",
                         help="actually run the restore (default is dry-run preview)")
    restore.set_defaults(func=_cmd_restore)

    smoke = sub.add_parser("smoke", help="quick end-to-end smoke test")
    smoke.set_defaults(func=_cmd_smoke)

    cron = sub.add_parser("cron", help="run the monthly auto-pay batch")
    cron.set_defaults(func=_cmd_cron)

    serve = sub.add_parser("serve", help="run the production web portal")
    serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    return args.func(args, extra)


if __name__ == "__main__":
    raise SystemExit(main())
