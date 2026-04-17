#!/usr/bin/env python3
"""
PHINS public-domain connectivity diagnostic.

Checks connectivity to the public PHINS site (default: https://www.phins.ai)
and classifies the failure when it is not reachable. This is designed to
diagnose the exact situation we hit when the Railway deployment behind the
custom domain is not live and Railway's edge returns
``{"status":"error","code":404,"message":"Application not found"}``.

Usage:
    python3 scripts/check_phins_ai_connection.py
    python3 scripts/check_phins_ai_connection.py --url https://www.phins.ai
    python3 scripts/check_phins_ai_connection.py --json

Exit codes:
    0 - site reachable and healthy
    1 - site reachable but returned an unexpected HTTP status
    2 - site not reachable (timeout, TLS error, or origin-not-found)
    3 - DNS resolution failed
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import time
from http.client import HTTPSConnection, HTTPConnection
from typing import Any, Dict, Optional
from urllib.parse import urlparse

DEFAULT_URL = os.environ.get("PHINS_PUBLIC_URL", "https://www.phins.ai")
DEFAULT_TIMEOUT = 10.0
HEALTH_PATH = "/api/health"

RAILWAY_APP_NOT_FOUND = "Application not found"


def _resolve(host: str) -> Dict[str, Any]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return {"ok": False, "error": f"DNS resolution failed: {exc}"}
    addresses = sorted({info[4][0] for info in infos})
    canonical = None
    try:
        canonical = socket.gethostbyname_ex(host)[0]
    except socket.gaierror:
        pass
    return {"ok": True, "addresses": addresses, "canonical": canonical}


def _request(url: str, timeout: float) -> Dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": f"Unsupported scheme: {parsed.scheme!r}"}
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    started = time.monotonic()
    try:
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            conn = HTTPSConnection(host, port, timeout=timeout, context=context)
        else:
            conn = HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", path, headers={"User-Agent": "phins-connectivity-check/1.0"})
        response = conn.getresponse()
        body = response.read(2048)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        conn.close()
    except socket.timeout:
        return {
            "ok": False,
            "error": f"Timed out after {timeout:.1f}s waiting for HTTP response",
            "classification": "timeout",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except ssl.SSLError as exc:
        return {"ok": False, "error": f"TLS error: {exc}", "classification": "tls"}
    except (ConnectionRefusedError, OSError) as exc:
        return {"ok": False, "error": f"Connection error: {exc}", "classification": "network"}

    try:
        text_body = body.decode("utf-8", errors="replace")
    except Exception:
        text_body = ""

    classification = "ok"
    parsed_body: Optional[Dict[str, Any]] = None
    try:
        parsed_body = json.loads(text_body)
    except ValueError:
        parsed_body = None

    if (
        response.status == 404
        and parsed_body
        and parsed_body.get("message") == RAILWAY_APP_NOT_FOUND
    ):
        classification = "railway_application_not_found"

    return {
        "ok": response.status == 200,
        "status": response.status,
        "reason": response.reason,
        "elapsed_ms": elapsed_ms,
        "headers": {k.lower(): v for k, v in response.getheaders()},
        "body_preview": text_body[:512],
        "body_json": parsed_body,
        "classification": classification,
    }


def classify_result(dns_result: Dict[str, Any], http_result: Dict[str, Any]) -> Dict[str, Any]:
    if not dns_result.get("ok"):
        return {
            "severity": "critical",
            "summary": "DNS resolution failed for the public hostname.",
            "remediation": [
                "Verify the domain is still registered and the nameservers are correct.",
                "Check the DNS provider's dashboard for the expected CNAME record.",
            ],
            "exit_code": 3,
        }
    if not http_result.get("ok"):
        cls = http_result.get("classification")
        if cls == "railway_application_not_found":
            return {
                "severity": "critical",
                "summary": (
                    "Railway edge returned 'Application not found'. The Railway "
                    "service behind the custom domain is not running."
                ),
                "remediation": [
                    "Open the PHINS project in the Railway dashboard.",
                    "Check the web service: it is most likely crashed, removed, "
                    "or unlinked from the custom domain.",
                    "If the service exists, trigger a redeploy of the latest build.",
                    "If the service was deleted, create a new service from this "
                    "repo (Dockerfile build) and re-add the www.phins.ai custom "
                    "domain.",
                    "Verify DATABASE_URL, USE_DATABASE, and other env vars listed "
                    "in RAILWAY_POSTGRES_FIX.md are present on the web service.",
                ],
                "exit_code": 2,
            }
        if cls == "timeout":
            return {
                "severity": "critical",
                "summary": (
                    "TLS handshake completed but no HTTP response was received "
                    "before timeout. The upstream origin is accepting TLS but not "
                    "serving HTTP — typically a crashed container or proxy with "
                    "no active backend."
                ),
                "remediation": [
                    "Check the Railway web service status and recent deploy logs.",
                    "Trigger a redeploy if the service is not in a healthy state.",
                ],
                "exit_code": 2,
            }
        return {
            "severity": "critical",
            "summary": http_result.get("error", "HTTP request failed"),
            "remediation": [
                "Check hosting provider status and recent deploy logs.",
            ],
            "exit_code": 2,
        }
    return {
        "severity": "ok",
        "summary": "Public endpoint is reachable.",
        "remediation": [],
        "exit_code": 0,
    }


def run(url: str, timeout: float) -> Dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.hostname or ""

    dns_result = _resolve(host)
    http_health = _request(url.rstrip("/") + HEALTH_PATH, timeout=timeout) if dns_result.get("ok") else {"ok": False, "skipped": True}
    http_root = _request(url, timeout=timeout) if dns_result.get("ok") else {"ok": False, "skipped": True}

    verdict = classify_result(
        dns_result,
        http_health if http_health.get("ok") else http_root,
    )

    return {
        "url": url,
        "host": host,
        "dns": dns_result,
        "http_health": http_health,
        "http_root": http_root,
        "verdict": verdict,
    }


def _print_human(report: Dict[str, Any]) -> None:
    print("=" * 72)
    print(f"PHINS connectivity check: {report['url']}")
    print("=" * 72)

    dns = report["dns"]
    print("\nDNS:")
    if dns.get("ok"):
        if dns.get("canonical") and dns["canonical"] != report["host"]:
            print(f"  {report['host']} -> {dns['canonical']}")
        for addr in dns.get("addresses", []):
            print(f"  A/AAAA: {addr}")
    else:
        print(f"  FAILED: {dns.get('error')}")

    for label, key in (("GET /api/health", "http_health"), ("GET /", "http_root")):
        section = report[key]
        print(f"\n{label}:")
        if section.get("skipped"):
            print("  skipped (DNS failed)")
            continue
        if section.get("ok"):
            print(f"  HTTP {section['status']} ({section['elapsed_ms']} ms)")
            preview = (section.get("body_preview") or "").strip().replace("\n", " ")
            if preview:
                print(f"  body: {preview[:200]}")
        else:
            if "status" in section:
                print(
                    f"  HTTP {section['status']} {section.get('reason', '')} "
                    f"({section.get('elapsed_ms', '?')} ms)"
                )
                preview = (section.get("body_preview") or "").strip().replace("\n", " ")
                if preview:
                    print(f"  body: {preview[:200]}")
            else:
                print(f"  FAILED: {section.get('error')}")

    verdict = report["verdict"]
    print("\nVerdict:")
    print(f"  severity: {verdict['severity']}")
    print(f"  summary:  {verdict['summary']}")
    if verdict["remediation"]:
        print("  remediation:")
        for step in verdict["remediation"]:
            print(f"    - {step}")
    print()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Public URL to probe")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds (default: 10)",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report")
    args = parser.parse_args(argv)

    report = run(args.url, args.timeout)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    return int(report["verdict"]["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
