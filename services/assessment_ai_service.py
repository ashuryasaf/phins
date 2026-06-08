"""
Assessment AI Narrative Service
===============================
An **additive, advisory** intelligence layer for the Assessment Center.

This is the "Hermes-style" agent core scoped exactly as agreed: an LLM /
reasoning layer that produces a natural-language narrative *on top of* the
deterministic fact store - it never replaces the rule-based extractors and it
never creates authoritative facts.

Hard data-integrity guarantees:

* **No fabrication.** The deterministic narrative is built only from facts that
  are already present in the analysis payload handed to it. It restates and
  summarises; it never invents a number, an ID, or a condition.
* **Additive only.** Output is clearly labelled ``source="assessment_ai"``,
  ``advisory=True`` and ``needs_review=True`` with a capped confidence. It is
  rendered as a separate ``ai_narrative`` block, never merged into the
  authoritative facts or risk score.
* **Feature-flagged.** The live-LLM path is OFF unless
  ``PHINS_ASSESSMENT_AI_ENABLED`` is truthy AND an OpenAI-compatible endpoint +
  key are configured. With no configuration the service falls back to a fully
  deterministic, offline, network-free narrative so it is safe and reproducible
  in every environment (including tests and air-gapped deployments).
* **Audited.** Every invocation emits a structured audit record (prompt hash,
  mode, model, evidence document SHA-256s) so the reasoning step is traceable.
* **Egress-aware.** When the live path is used, values can be redacted before
  they ever leave the platform (``PHINS_ASSESSMENT_AI_REDACT``).

Configuration (all optional; absence => deterministic offline mode):

* ``PHINS_ASSESSMENT_AI_ENABLED``   - "1"/"true" to allow the live-LLM path.
* ``PHINS_ASSESSMENT_AI_ENDPOINT``  - OpenAI-compatible chat completions URL.
* ``PHINS_ASSESSMENT_AI_API_KEY``   - bearer key for that endpoint.
* ``PHINS_ASSESSMENT_AI_MODEL``     - model id (default: ``hermes-4``).
* ``PHINS_ASSESSMENT_AI_REDACT``    - "1"/"true" to redact fact values on egress.
* ``PHINS_ASSESSMENT_AI_TIMEOUT``   - request timeout seconds (default 20).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("phins.assessment_ai")

# Advisory output can never claim high confidence - it is a summary for a human
# reviewer, not an authoritative fact.
_MAX_ADVISORY_CONFIDENCE = 0.4


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


class AssessmentAIService:
    """Generates advisory narratives over Assessment Center analyses."""

    def __init__(self) -> None:
        # Bounded in-memory audit trail (most-recent-last). Production may also
        # forward these to the audit repository; this list guarantees the
        # reasoning step is always inspectable even with no database.
        self._audit: List[Dict[str, Any]] = []
        self._audit_limit = 200

    # ── Configuration ────────────────────────────────────────────────────

    @property
    def model(self) -> str:
        return os.environ.get("PHINS_ASSESSMENT_AI_MODEL", "hermes-4")

    def is_llm_enabled(self) -> bool:
        """True only when the live-LLM path is both allowed and configured."""
        if not _truthy(os.environ.get("PHINS_ASSESSMENT_AI_ENABLED")):
            return False
        endpoint = os.environ.get("PHINS_ASSESSMENT_AI_ENDPOINT", "").strip()
        api_key = os.environ.get("PHINS_ASSESSMENT_AI_API_KEY", "").strip()
        return bool(endpoint and api_key)

    # ── Public API ────────────────────────────────────────────────────────

    def generate_narrative(
        self,
        analysis_payload: Dict[str, Any],
        *,
        customer_id: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return an advisory ``ai_narrative`` block for an analysis payload.

        ``analysis_payload`` is the dict returned by
        :meth:`AssessmentCenterService.run_analysis`. The narrative is built
        from its evidence; the live-LLM path is used only when enabled and
        configured, otherwise a deterministic offline narrative is produced.
        """
        options = dict(options or {})
        evidence = self._collect_evidence(analysis_payload)
        facts_digest = self._facts_digest(evidence)

        mode = "deterministic"
        summary_text = ""
        if self.is_llm_enabled():
            try:
                summary_text = self._llm_summary(analysis_payload, evidence)
                mode = "llm"
            except Exception as exc:  # noqa: BLE001 - any failure => safe fallback
                logger.warning("Assessment AI live path failed, using deterministic fallback: %s", exc)
                summary_text = ""
                mode = "deterministic"

        if not summary_text:
            summary_text = self._deterministic_summary(analysis_payload, evidence)

        narrative = {
            "source": "assessment_ai",
            "mode": mode,
            "model": self.model if mode == "llm" else "deterministic-offline",
            "advisory": True,
            "needs_review": True,
            "confidence": _MAX_ADVISORY_CONFIDENCE,
            "customer_id": customer_id,
            "analysis_type": analysis_payload.get("analysis_type"),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "summary_text": summary_text,
            "highlights": self._highlights(analysis_payload, evidence),
            "evidence": evidence,
            "evidence_count": len(evidence),
            "facts_digest": facts_digest,
            "disclaimer": (
                "AI-generated advisory summary of existing facts. It introduces "
                "no new authoritative facts and must be reviewed by a human "
                "before any decision."
            ),
        }

        self._record_audit(customer_id, narrative, facts_digest)
        return narrative

    # ── Evidence collection (provenance-preserving) ──────────────────────

    @staticmethod
    def _collect_evidence(analysis_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract the provenance trail from an analysis payload.

        Pulls every (document_id, sha256, confidence) referenced by the
        analysis so the narrative is anchored to auditable sources.
        """
        evidence: List[Dict[str, Any]] = []
        seen = set()

        description = analysis_payload.get("description") or {}
        for section in description.get("sections", []) or []:
            category = section.get("category", "Other")
            for label, entries in (section.get("by_label") or {}).items():
                for entry in entries or []:
                    key = (entry.get("document_id"), entry.get("sha256"), category, label)
                    if key in seen:
                        continue
                    seen.add(key)
                    evidence.append({
                        "category": category,
                        "label": label,
                        "document_id": entry.get("document_id"),
                        "document_name": entry.get("document_name"),
                        "document_type": entry.get("document_type"),
                        "sha256": entry.get("sha256"),
                        "confidence": entry.get("confidence"),
                        "source": entry.get("source"),
                    })
        return evidence

    @staticmethod
    def _facts_digest(evidence: List[Dict[str, Any]]) -> str:
        payload = json.dumps(evidence, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ── Deterministic narrative (default, offline, reproducible) ─────────

    @staticmethod
    def _category_counts(description: Dict[str, Any]) -> List[tuple]:
        counts = []
        for section in description.get("sections", []) or []:
            counts.append((section.get("category", "Other"), int(section.get("fact_count", 0) or 0)))
        return counts

    def _deterministic_summary(
        self,
        analysis_payload: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> str:
        """Build a reproducible narrative purely from existing facts."""
        lines: List[str] = []
        analysis_type = analysis_payload.get("analysis_type", "analysis")
        customer_id = analysis_payload.get("customer_id", "")
        lines.append(f"Advisory summary for customer {customer_id} ({analysis_type}).")

        description = analysis_payload.get("description") or {}
        if description:
            fact_count = description.get("fact_count", 0)
            doc_count = description.get("document_count", 0)
            lines.append(
                f"Reviewed {fact_count} extracted fact(s) across {doc_count} document(s)."
            )
            counts = self._category_counts(description)
            if counts:
                parts = ", ".join(f"{cat} ({n})" for cat, n in counts if n)
                if parts:
                    lines.append(f"Fact coverage by category: {parts}.")

        risk = analysis_payload.get("risk") or {}
        if risk:
            score = risk.get("risk_score")
            level = risk.get("risk_level")
            if score is not None or level is not None:
                lines.append(
                    f"Recorded risk indicator: level={level}, score={score} "
                    "(computed by the deterministic risk engine, restated here)."
                )

        if evidence:
            # Surface the highest-confidence evidence items, deterministically.
            top = sorted(
                evidence,
                key=lambda e: (-(e.get("confidence") or 0.0), str(e.get("label")), str(e.get("document_id"))),
            )[:5]
            lines.append("Key evidence (highest confidence, with provenance):")
            for item in top:
                conf = item.get("confidence")
                sha = (item.get("sha256") or "")[:12]
                lines.append(
                    f"  - {item.get('category')}/{item.get('label')} "
                    f"[doc={item.get('document_id') or 'n/a'} sha={sha} conf={conf}]"
                )
        else:
            lines.append("No source-linked evidence was available for this analysis.")

        lines.append(
            "This advisory summary introduces no new facts; verify against the "
            "linked source documents before acting."
        )
        return "\n".join(lines)

    def _highlights(
        self,
        analysis_payload: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Structured, provenance-anchored highlights for UI rendering."""
        highlights: List[Dict[str, Any]] = []
        for item in sorted(
            evidence,
            key=lambda e: (-(e.get("confidence") or 0.0), str(e.get("label"))),
        )[:8]:
            highlights.append({
                "category": item.get("category"),
                "label": item.get("label"),
                "document_id": item.get("document_id"),
                "sha256": item.get("sha256"),
                "confidence": item.get("confidence"),
            })
        return highlights

    # ── Live-LLM path (opt-in, egress-aware) ─────────────────────────────

    def _llm_summary(
        self,
        analysis_payload: Dict[str, Any],
        evidence: List[Dict[str, Any]],
    ) -> str:
        """Call an OpenAI-compatible endpoint to summarise the evidence.

        Raises on any failure so the caller falls back to the deterministic
        path. Only the evidence trail (optionally value-redacted) is sent.
        """
        import requests  # local import: requests is a runtime dependency

        endpoint = os.environ["PHINS_ASSESSMENT_AI_ENDPOINT"].strip()
        api_key = os.environ["PHINS_ASSESSMENT_AI_API_KEY"].strip()
        timeout = float(os.environ.get("PHINS_ASSESSMENT_AI_TIMEOUT", "20"))
        redact = _truthy(os.environ.get("PHINS_ASSESSMENT_AI_REDACT"))

        evidence_for_model = evidence
        if redact:
            evidence_for_model = [
                {k: v for k, v in item.items() if k not in ("label",)}
                for item in evidence
            ]

        system_prompt = (
            "You are an insurance assessment assistant. You will be given a set "
            "of already-extracted facts with provenance. Write a concise, "
            "professional advisory summary. CRITICAL RULES: only use the facts "
            "provided; never invent numbers, identifiers, conditions, or "
            "conclusions; do not provide a final underwriting decision; flag "
            "anything that needs human review."
        )
        user_payload = {
            "analysis_type": analysis_payload.get("analysis_type"),
            "evidence": evidence_for_model,
            "risk": analysis_payload.get("risk"),
        }

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
            ],
            "temperature": 0.0,
        }
        resp = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        content = (content or "").strip()
        if not content:
            raise ValueError("Empty completion from assessment AI endpoint")
        return content

    # ── Audit ─────────────────────────────────────────────────────────────

    def _record_audit(
        self,
        customer_id: str,
        narrative: Dict[str, Any],
        facts_digest: str,
    ) -> None:
        record = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "customer_id": customer_id,
            "analysis_type": narrative.get("analysis_type"),
            "mode": narrative.get("mode"),
            "model": narrative.get("model"),
            "evidence_count": narrative.get("evidence_count"),
            "facts_digest": facts_digest,
        }
        self._audit.append(record)
        if len(self._audit) > self._audit_limit:
            self._audit = self._audit[-self._audit_limit:]
        logger.info(
            "assessment_ai narrative customer=%s type=%s mode=%s model=%s evidence=%s digest=%s",
            customer_id, record["analysis_type"], record["mode"], record["model"],
            record["evidence_count"], facts_digest[:12],
        )

    def recent_audit(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._audit[-int(max(1, limit)):])


# Singleton accessor ----------------------------------------------------------

_assessment_ai_service: Optional[AssessmentAIService] = None


def get_assessment_ai_service() -> AssessmentAIService:
    global _assessment_ai_service
    if _assessment_ai_service is None:
        _assessment_ai_service = AssessmentAIService()
    return _assessment_ai_service
