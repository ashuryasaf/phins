"""Shared JSON schema for lifecycle assessment responses (spec §14).

Every lifecycle prompt (onboarding / service / termination) must return an
object matching this schema; responses are validated before anything is
persisted, and invalid responses are retried then rejected.
"""

LIFECYCLE_RESPONSE_SCHEMA = {
    "type": "object",
    "required": [
        "summary",
        "risk_level",
        "findings",
        "missing_information",
        "contradictions",
        "recommendations",
        "confidence",
        "requires_human_review",
    ],
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "risk_level": {"enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "detail": {"type": "string"},
                    "evidence_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "requires_human_review": {"type": "boolean"},
    },
}

LIFECYCLE_RULES = (
    "CRITICAL RULES: base every statement only on the evidence provided; "
    "never invent numbers, identifiers, conditions, or documents; reference "
    "evidence by its document_id in findings.evidence_refs; report "
    "contradictions rather than resolving them; do not make an underwriting, "
    "claims, or termination decision — a human decides; set "
    "requires_human_review=true whenever evidence is missing, contradictory, "
    "or materially uncertain."
)
