"""
Versioned Prompt Templates
==========================
Central registry for every LLM prompt the platform uses (Phase 3 of the
multimodal document intelligence pipeline).

Rules:

* Prompts are **never** hard-coded inside route handlers or services — they
  live here, versioned, so every generated artefact can record exactly which
  prompt produced it (``prompt_version``) for auditability.
* Adding a new prompt version means adding a new module (e.g.
  ``onboarding_v2.py``) and registering it — existing versions are immutable
  so historical artefacts stay reproducible.
* Every template that produces structured output carries the JSON schema its
  responses must validate against (enforced by
  ``services.llm_providers.structured_completion``).
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class PromptTemplate:
    """An immutable, versioned prompt definition."""

    prompt_id: str            # e.g. "onboarding-v1" — recorded on artefacts
    assessment_type: str      # e.g. "onboarding"
    version: int
    system_prompt: str
    response_schema: Optional[Dict[str, Any]] = field(default=None)

    @property
    def sha256(self) -> str:
        """Content hash of the prompt text and its response schema.

        ``prompt_id`` names a version; the hash proves the text behind it.
        Recorded next to ``prompt_id`` on every artefact so an edit to a
        registered template (which the registry forbids but cannot detect at
        runtime) is visible in the audit trail and fails the golden set.
        """
        payload = json.dumps(
            {"system_prompt": self.system_prompt, "response_schema": self.response_schema},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def provenance(self) -> Dict[str, Any]:
        """The fields every generated artefact must carry.

        ``prompt_version`` keeps the platform-wide meaning it already has on
        artefacts and usage rows — the versioned id string (``narrative-v2``);
        ``prompt_version_number`` is the integer, ``prompt_sha256`` the text.
        """
        return {
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_id,
            "prompt_version_number": self.version,
            "prompt_sha256": self.sha256,
        }


_REGISTRY: Dict[str, PromptTemplate] = {}


def register_prompt(template: PromptTemplate) -> PromptTemplate:
    if template.prompt_id in _REGISTRY:
        raise ValueError(f"Prompt {template.prompt_id} already registered")
    _REGISTRY[template.prompt_id] = template
    return template


def get_prompt(assessment_type: str, version: Optional[int] = None) -> PromptTemplate:
    """Return the requested (or latest) prompt version for an assessment type."""
    candidates = [
        t for t in _REGISTRY.values() if t.assessment_type == assessment_type
    ]
    if not candidates:
        raise KeyError(f"No prompt registered for assessment type '{assessment_type}'")
    if version is not None:
        for template in candidates:
            if template.version == version:
                return template
        raise KeyError(f"No {assessment_type} prompt with version {version}")
    return max(candidates, key=lambda t: t.version)


def list_prompts() -> Dict[str, Dict[str, Any]]:
    return {
        prompt_id: {
            "assessment_type": t.assessment_type,
            "version": t.version,
            "has_schema": t.response_schema is not None,
            "sha256": t.sha256,
        }
        for prompt_id, t in sorted(_REGISTRY.items())
    }


# Import template modules for their registration side effects.
from prompts.assessment import narrative_v1  # noqa: E402,F401
from prompts.assessment import narrative_v2  # noqa: E402,F401
from prompts.assessment import onboarding_v1  # noqa: E402,F401
from prompts.assessment import service_v1  # noqa: E402,F401
from prompts.assessment import termination_v1  # noqa: E402,F401

__all__ = ["PromptTemplate", "register_prompt", "get_prompt", "list_prompts"]
