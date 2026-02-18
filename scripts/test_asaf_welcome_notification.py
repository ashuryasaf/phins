#!/usr/bin/env python3
"""
Send a branded PHINS welcome executive report notification.

Default target:
    asaf@assurance.co.il

Usage examples:
    python3 scripts/test_asaf_welcome_notification.py
    python3 scripts/test_asaf_welcome_notification.py --live
    python3 scripts/test_asaf_welcome_notification.py --email user@example.com --snapshot backups/20260112_222044/customers.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from services.customer_communication_agent import get_customer_communication_agent
from services.notification_service import create_notification_service


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _find_customer_snapshot(data: Any, email: str) -> Optional[Dict[str, Any]]:
    email = email.strip().lower()
    customers: List[Dict[str, Any]] = []

    if isinstance(data, dict):
        if isinstance(data.get("customers"), list):
            customers = [item for item in data.get("customers", []) if isinstance(item, dict)]
        elif isinstance(data.get("items"), list):
            customers = [item for item in data.get("items", []) if isinstance(item, dict)]
    elif isinstance(data, list):
        customers = [item for item in data if isinstance(item, dict)]

    for customer in customers:
        if str(customer.get("email", "")).strip().lower() == email:
            return customer
    return None


def _build_accounts(customer: Dict[str, Any]) -> List[Dict[str, Any]]:
    wallet_breakdown = customer.get("wallet_breakdown")
    accounts: List[Dict[str, Any]] = []
    if isinstance(wallet_breakdown, dict):
        for key, value in wallet_breakdown.items():
            if key == "total":
                continue
            try:
                numeric_value = float(value)
            except Exception:
                numeric_value = 0.0
            accounts.append({"name": key, "balance": numeric_value})

    if not accounts:
        accounts.append({"name": "wallet", "balance": float(customer.get("wallet_balance", 0.0) or 0.0)})
    return accounts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send PHINS welcome executive report notification")
    parser.add_argument("--email", default="asaf@assurance.co.il", help="Recipient email address")
    parser.add_argument(
        "--snapshot",
        default="backups/20260112_222044/customers.json",
        help="Path to customer snapshot JSON",
    )
    parser.add_argument("--name", default="", help="Override customer name")
    parser.add_argument("--customer-id", default="", help="Override customer ID")
    parser.add_argument("--phone", default="", help="Optional WhatsApp phone for companion brief")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use configured providers instead of mock providers",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot_path = args.snapshot

    if not os.path.exists(snapshot_path):
        print(json.dumps({"success": False, "error": f"Snapshot file not found: {snapshot_path}"}, indent=2))
        return 2

    data = _load_json(snapshot_path)
    customer = _find_customer_snapshot(data, args.email)
    if not customer:
        print(json.dumps({"success": False, "error": f"Customer {args.email} not found in snapshot"}, indent=2))
        return 3

    customer_name = args.name or customer.get("name") or "PHINS Customer"
    customer_id = args.customer_id or customer.get("id") or customer.get("customer_id") or args.email
    phone = args.phone or customer.get("phone") or ""
    policies = customer.get("policies", []) if isinstance(customer.get("policies"), list) else []
    bills = customer.get("bills", []) if isinstance(customer.get("bills"), list) else []
    accounts = _build_accounts(customer)

    notification_service = create_notification_service(use_mock=(not args.live))
    agent = get_customer_communication_agent(notification_service=notification_service)

    result = agent.send_welcome_package(
        customer_id=customer_id,
        customer_name=customer_name,
        email=args.email,
        policies=policies,
        bills=bills,
        accounts=accounts,
        communities=[],
        whatsapp_phone=phone if phone else None,
        login_url="/login.html",
    )

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("success") else 4


if __name__ == "__main__":
    sys.exit(main())

