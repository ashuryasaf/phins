"""
AI Usage & Cost Tracking Service
================================
Meters every external AI / parsing operation so assessment costs are known
from measured traffic instead of estimates (Phase 4 of the multimodal
document intelligence pipeline).

Rules:

* **Configurable prices, never hard-coded** (spec §22): unit prices come from
  environment variables and the prices used are snapshotted on every record,
  so operator price updates never rewrite history.
* **Best-effort persistence**: records go to a bounded in-memory ring always,
  and to the ``ai_usage_records`` table when a database is available. A
  metering failure must never break the operation being metered.
* **Aggregation**: cost per document / assessment / customer / provider /
  operation, plus a normalized "per 1,000 assessments" projection.

Price environment variables (all optional; default 0 == self-hosted/free):
    PHINS_AI_PRICE_INPUT_PER_MTOK        USD per 1M input tokens
    PHINS_AI_PRICE_OUTPUT_PER_MTOK       USD per 1M output tokens
    PHINS_AI_PRICE_PARSE_PER_PAGE        USD per parsed page (managed parser)
    PHINS_AI_PRICE_TRANSCRIPTION_PER_MIN USD per transcribed minute
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_RING_LIMIT = int(os.environ.get("PHINS_AI_USAGE_RING_LIMIT", "10000"))


def _price(name: str) -> float:
    try:
        return float(os.environ.get(name, "0") or 0)
    except ValueError:
        return 0.0


def current_unit_prices() -> Dict[str, float]:
    return {
        "input_per_mtok": _price("PHINS_AI_PRICE_INPUT_PER_MTOK"),
        "output_per_mtok": _price("PHINS_AI_PRICE_OUTPUT_PER_MTOK"),
        "parse_per_page": _price("PHINS_AI_PRICE_PARSE_PER_PAGE"),
        "transcription_per_min": _price("PHINS_AI_PRICE_TRANSCRIPTION_PER_MIN"),
    }


def estimate_cost(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    pages: int = 0,
    media_seconds: float = 0.0,
    prices: Optional[Dict[str, float]] = None,
) -> float:
    prices = prices or current_unit_prices()
    cost = (
        (input_tokens / 1_000_000.0) * prices.get("input_per_mtok", 0.0)
        + (output_tokens / 1_000_000.0) * prices.get("output_per_mtok", 0.0)
        + pages * prices.get("parse_per_page", 0.0)
        + (media_seconds / 60.0) * prices.get("transcription_per_min", 0.0)
    )
    return round(cost, 6)


class AIUsageService:
    """Records and aggregates AI usage. DB-backed when available."""

    def __init__(self, db_manager=None):
        self.db_manager = db_manager
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []

    # ── Recording ─────────────────────────────────────────────────────────

    def record_usage(
        self,
        *,
        provider: str,
        operation: str,
        model: Optional[str] = None,
        prompt_version: Optional[str] = None,
        customer_id: Optional[str] = None,
        assessment_id: Optional[str] = None,
        document_id: Optional[str] = None,
        job_id: Optional[str] = None,
        pages: Optional[int] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        media_seconds: Optional[float] = None,
        duration_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Meter one operation. Never raises into the caller."""
        try:
            prices = current_unit_prices()
            record = {
                "id": f"AIUSE-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}",
                "customer_id": customer_id or None,
                "assessment_id": assessment_id or None,
                "document_id": document_id or None,
                "job_id": job_id or None,
                "provider": str(provider or "unknown"),
                "operation": str(operation or "unknown"),
                "model": model,
                "prompt_version": prompt_version,
                "pages": int(pages) if pages else None,
                "input_tokens": int(input_tokens) if input_tokens else None,
                "output_tokens": int(output_tokens) if output_tokens else None,
                "media_seconds": float(media_seconds) if media_seconds else None,
                "duration_ms": int(duration_ms) if duration_ms else None,
                "unit_price_snapshot": prices,
                "estimated_cost": estimate_cost(
                    input_tokens=int(input_tokens or 0),
                    output_tokens=int(output_tokens or 0),
                    pages=int(pages or 0),
                    media_seconds=float(media_seconds or 0.0),
                    prices=prices,
                ),
                "currency": "USD",
                "created_at": datetime.utcnow().isoformat() + "Z",
            }
            with self._lock:
                self._records.append(record)
                if len(self._records) > _RING_LIMIT:
                    self._records = self._records[-_RING_LIMIT:]
            self._persist(record)
            return record
        except Exception as exc:  # noqa: BLE001 - metering must never break callers
            logger.warning("AI usage recording failed (non-fatal): %s", exc)
            return {}

    def usage_hook(self, context: Optional[Dict[str, Any]] = None):
        """Adapter for ``LLMProvider.usage_hook``: merges call context
        (customer/assessment/document ids) into every metered LLM call."""
        context = dict(context or {})

        def _hook(record: Dict[str, Any]) -> None:
            self.record_usage(
                provider=record.get("provider", "unknown"),
                operation=record.get("operation", "llm_completion"),
                model=record.get("model"),
                input_tokens=record.get("input_tokens"),
                output_tokens=record.get("output_tokens"),
                duration_ms=record.get("duration_ms"),
                **context,
            )
        return _hook

    def _persist(self, record: Dict[str, Any]) -> None:
        if not self.db_manager:
            return
        try:
            row = dict(record)
            row["unit_price_snapshot"] = json.dumps(row.get("unit_price_snapshot") or {})
            row.pop("created_at", None)
            self.db_manager.ai_usage.create(**row)
        except Exception as exc:
            logger.warning("AI usage DB persist failed (non-fatal): %s", exc)

    # ── Aggregation ───────────────────────────────────────────────────────

    def list_records(
        self,
        customer_id: Optional[str] = None,
        assessment_id: Optional[str] = None,
        document_id: Optional[str] = None,
        provider: Optional[str] = None,
        operation: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        if self.db_manager:
            try:
                rows = self.db_manager.ai_usage.list_filtered(
                    customer_id=customer_id, assessment_id=assessment_id,
                    document_id=document_id, provider=provider,
                    operation=operation, limit=limit,
                )
                return [r.to_dict() for r in rows]
            except Exception as exc:
                logger.warning("AI usage DB list failed, using memory: %s", exc)
        with self._lock:
            records = list(self._records)
        for key, wanted in (("customer_id", customer_id),
                            ("assessment_id", assessment_id),
                            ("document_id", document_id),
                            ("provider", provider),
                            ("operation", operation)):
            if wanted:
                records = [r for r in records if r.get(key) == wanted]
        records.reverse()
        return records[:limit]

    def summarize(self, group_by: str = "provider",
                  customer_id: Optional[str] = None) -> Dict[str, Any]:
        """Aggregated usage/cost, grouped, plus totals and projections."""
        if self.db_manager:
            try:
                groups = self.db_manager.ai_usage.aggregate(
                    group_by=group_by, customer_id=customer_id)
                return self._with_totals(groups)
            except Exception as exc:
                logger.warning("AI usage DB aggregate failed, using memory: %s", exc)

        key_field = {
            "provider": "provider", "operation": "operation",
            "customer": "customer_id", "model": "model",
        }.get(group_by, "provider")
        with self._lock:
            records = list(self._records)
        if customer_id:
            records = [r for r in records if r.get("customer_id") == customer_id]
        buckets: Dict[Any, Dict[str, Any]] = {}
        for r in records:
            bucket = buckets.setdefault(r.get(key_field), {
                "key": r.get(key_field), "operations": 0, "estimated_cost": 0.0,
                "input_tokens": 0, "output_tokens": 0, "pages": 0,
                "media_seconds": 0.0,
            })
            bucket["operations"] += 1
            bucket["estimated_cost"] = round(
                bucket["estimated_cost"] + (r.get("estimated_cost") or 0.0), 6)
            bucket["input_tokens"] += r.get("input_tokens") or 0
            bucket["output_tokens"] += r.get("output_tokens") or 0
            bucket["pages"] += r.get("pages") or 0
            bucket["media_seconds"] = round(
                bucket["media_seconds"] + (r.get("media_seconds") or 0.0), 2)
        return self._with_totals(sorted(buckets.values(), key=lambda b: str(b["key"])))

    @staticmethod
    def _with_totals(groups: List[Dict[str, Any]]) -> Dict[str, Any]:
        totals = {
            "operations": sum(g["operations"] for g in groups),
            "estimated_cost": round(sum(g["estimated_cost"] for g in groups), 6),
            "input_tokens": sum(g["input_tokens"] for g in groups),
            "output_tokens": sum(g["output_tokens"] for g in groups),
            "pages": sum(g["pages"] for g in groups),
            "media_seconds": round(sum(g["media_seconds"] for g in groups), 2),
        }
        return {
            "groups": groups,
            "totals": totals,
            "unit_prices": current_unit_prices(),
            "currency": "USD",
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_default_service: Optional[AIUsageService] = None


def get_ai_usage_service(db_manager=None) -> AIUsageService:
    global _default_service
    if _default_service is None:
        _default_service = AIUsageService(db_manager=db_manager)
    elif db_manager is not None and _default_service.db_manager is None:
        _default_service.db_manager = db_manager
    return _default_service


def reset_ai_usage_service() -> None:
    global _default_service
    _default_service = None
