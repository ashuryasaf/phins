"""
LLM Provider Abstraction
========================
Vendor-neutral access to large-language-model completions for advisory
assessment features (Phase 3 of the multimodal document intelligence
pipeline).

Design rules (docs/multimodal_assessment_pipeline_plan.md and
docs/ai_surface_design_principles.md):

* The LLM **explains, it never decides** — consumers must keep outputs
  advisory and route decisions through the deterministic engines.
* **No SDK dependencies** — plain OpenAI-compatible HTTP like the rest of the
  platform (``services/media_generation_service.py`` pattern), so OpenAI,
  Anthropic-compatible gateways, Groq, Azure, or self-hosted endpoints are all
  reachable by changing two environment variables.
* **Structured output is validated** against a JSON schema before it is
  returned; invalid responses are retried with error feedback, then rejected.
  Unvalidated model text is never handed to callers as structured data.
* **Escalation** — a more capable model can be configured for low-confidence /
  conflicting cases (``PHINS_LLM_ESCALATION_MODEL``); routine calls stay on
  the cost-efficient default.
* **Usage-metered** — every call reports token usage and duration through an
  optional ``usage_hook`` so cost tracking (Phase 4) sees every external call.

Environment:
    PHINS_ASSESSMENT_AI_ENABLED    master gate for any live-LLM path
    PHINS_ASSESSMENT_AI_ENDPOINT   OpenAI-compatible chat completions URL
    PHINS_ASSESSMENT_AI_API_KEY    bearer key
    PHINS_ASSESSMENT_AI_MODEL      default model id
    PHINS_LLM_ESCALATION_MODEL     optional stronger model for escalation
    PHINS_ASSESSMENT_AI_TIMEOUT    request timeout seconds (default 20)
    PHINS_LLM_VALIDATION_RETRIES   schema-validation retries (default 2)
    PHINS_AI_ACCEPT_THRESHOLD      >= auto-accept confidence (default 0.90)
    PHINS_AI_REVIEW_THRESHOLD      <  human-review confidence (default 0.70)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """No live LLM is configured/enabled for this deployment."""


class LLMValidationError(ValueError):
    """The model response failed JSON-schema validation after retries."""


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


# ── Minimal JSON-schema validation (stdlib-only) ──────────────────────────────

def validate_json_schema(instance: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """Validate ``instance`` against a JSON-schema subset; returns error list.

    Supports the keywords the assessment schemas use: type, required,
    properties, items, enum, minimum, maximum, minLength, maxLength and
    boolean additionalProperties. Deliberately small — no new dependency.
    """
    errors: List[str] = []

    expected_type = schema.get("type")
    if expected_type:
        type_map = {
            "object": dict, "array": list, "string": str,
            "boolean": bool, "null": type(None),
        }
        if expected_type == "number":
            ok = isinstance(instance, (int, float)) and not isinstance(instance, bool)
        elif expected_type == "integer":
            ok = isinstance(instance, int) and not isinstance(instance, bool)
        else:
            ok = isinstance(instance, type_map.get(expected_type, object))
        if not ok:
            errors.append(f"{path}: expected {expected_type}, got {type(instance).__name__}")
            return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} above maximum {schema['maximum']}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: string shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: string longer than maxLength {schema['maxLength']}")

    if isinstance(instance, dict):
        for required_key in schema.get("required", []):
            if required_key not in instance:
                errors.append(f"{path}: missing required property '{required_key}'")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                errors.extend(validate_json_schema(value, properties[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property '{key}'")

    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors.extend(validate_json_schema(item, schema["items"], f"{path}[{index}]"))

    return errors


# ── Confidence disposition (spec §17, configurable) ───────────────────────────

def review_disposition(confidence: Optional[float]) -> str:
    """Map a confidence value onto accepted / flagged / needs_review."""
    accept = float(os.environ.get("PHINS_AI_ACCEPT_THRESHOLD", "0.90"))
    review = float(os.environ.get("PHINS_AI_REVIEW_THRESHOLD", "0.70"))
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return "needs_review"
    if value >= accept:
        return "accepted"
    if value >= review:
        return "flagged"
    return "needs_review"


# ── Providers ─────────────────────────────────────────────────────────────────

class LLMProvider:
    """Provider interface. Implementations must be side-effect free besides
    the network call and the optional ``usage_hook`` notification."""

    #: set by consumers (e.g. ai_usage_service) to meter every call.
    usage_hook: Optional[Callable[[Dict[str, Any]], None]] = None

    def completion(self, system_prompt: str, user_content: str, *,
                   escalate: bool = False) -> str:
        raise NotImplementedError

    def structured_completion(self, system_prompt: str, user_content: str,
                              schema: Dict[str, Any], *,
                              escalate: bool = False) -> Dict[str, Any]:
        raise NotImplementedError

    def describe(self) -> Dict[str, Any]:
        return {"provider": type(self).__name__}


class DisabledLLMProvider(LLMProvider):
    """Explicit no-LLM provider: every call raises so callers use their
    deterministic offline paths."""

    def completion(self, system_prompt, user_content, *, escalate=False):
        raise LLMUnavailableError("No LLM provider configured")

    def structured_completion(self, system_prompt, user_content, schema, *, escalate=False):
        raise LLMUnavailableError("No LLM provider configured")

    def describe(self):
        return {"provider": "disabled"}


class OpenAICompatibleProvider(LLMProvider):
    """Chat-completions over any OpenAI-compatible HTTP endpoint."""

    def __init__(self, endpoint: str, api_key: str, model: str,
                 timeout: float = 20.0, escalation_model: Optional[str] = None):
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.escalation_model = escalation_model or model
        self.validation_retries = int(os.environ.get("PHINS_LLM_VALIDATION_RETRIES", "2"))

    def describe(self) -> Dict[str, Any]:
        return {
            "provider": "openai_compatible",
            "model": self.model,
            "escalation_model": self.escalation_model,
        }

    # ── HTTP core ─────────────────────────────────────────────────────────

    def _chat(self, messages: List[Dict[str, str]], model: str) -> str:
        import requests

        start = time.time()
        response = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "messages": messages, "temperature": 0.0},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        duration_ms = int((time.time() - start) * 1000)

        usage = data.get("usage") or {}
        self._notify_usage({
            "provider": "openai_compatible",
            "operation": "llm_completion",
            "model": model,
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
            "duration_ms": duration_ms,
        })

        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
        )
        content = (content or "").strip()
        if not content:
            raise ValueError("Empty completion from LLM endpoint")
        return content

    def _notify_usage(self, record: Dict[str, Any]) -> None:
        if not self.usage_hook:
            return
        try:
            self.usage_hook(record)
        except Exception as exc:
            logger.debug("LLM usage hook failed: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────

    def completion(self, system_prompt: str, user_content: str, *,
                   escalate: bool = False) -> str:
        model = self.escalation_model if escalate else self.model
        return self._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            model,
        )

    def structured_completion(self, system_prompt: str, user_content: str,
                              schema: Dict[str, Any], *,
                              escalate: bool = False) -> Dict[str, Any]:
        """Completion that must satisfy ``schema``.

        Invalid JSON / schema violations are retried with the validation
        errors appended so the model can correct itself; after the retry
        budget the call fails with :class:`LLMValidationError` — invalid
        model output is never returned to callers.
        """
        model = self.escalation_model if escalate else self.model
        schema_text = json.dumps(schema, ensure_ascii=False)
        messages = [
            {"role": "system", "content": (
                f"{system_prompt}\n\nRespond with a single JSON object that "
                f"validates against this JSON schema — no prose, no code "
                f"fences:\n{schema_text}"
            )},
            {"role": "user", "content": user_content},
        ]

        last_errors: List[str] = []
        for attempt in range(1 + max(0, self.validation_retries)):
            content = self._chat(messages, model)
            parsed = _parse_json_lenient(content)
            if parsed is None:
                last_errors = ["response is not valid JSON"]
            else:
                last_errors = validate_json_schema(parsed, schema)
                if not last_errors:
                    return parsed
            logger.warning(
                "LLM structured output invalid (attempt %d): %s",
                attempt + 1, "; ".join(last_errors[:5]),
            )
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": (
                "The previous response was invalid: "
                + "; ".join(last_errors[:10])
                + ". Return ONLY a corrected JSON object that validates "
                  "against the schema."
            )})
        raise LLMValidationError(
            "LLM response failed schema validation after retries: "
            + "; ".join(last_errors[:10])
        )


def _parse_json_lenient(content: str) -> Optional[Any]:
    """Parse model output as JSON, tolerating code fences and prose margins."""
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    # Last resort: outermost braces.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except (ValueError, TypeError):
            return None
    return None


# ── Factory ───────────────────────────────────────────────────────────────────

def get_llm_provider() -> LLMProvider:
    """Provider selected from environment; DisabledLLMProvider when unset.

    Reuses the existing ``PHINS_ASSESSMENT_AI_*`` configuration so operators
    configure one endpoint for every advisory LLM feature.
    """
    if not _truthy(os.environ.get("PHINS_ASSESSMENT_AI_ENABLED")):
        return DisabledLLMProvider()
    endpoint = os.environ.get("PHINS_ASSESSMENT_AI_ENDPOINT", "").strip()
    api_key = os.environ.get("PHINS_ASSESSMENT_AI_API_KEY", "").strip()
    if not endpoint or not api_key:
        return DisabledLLMProvider()
    return OpenAICompatibleProvider(
        endpoint=endpoint,
        api_key=api_key,
        model=os.environ.get("PHINS_ASSESSMENT_AI_MODEL", "hermes-4"),
        timeout=float(os.environ.get("PHINS_ASSESSMENT_AI_TIMEOUT", "20")),
        escalation_model=os.environ.get("PHINS_LLM_ESCALATION_MODEL") or None,
    )
