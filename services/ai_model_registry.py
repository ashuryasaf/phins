"""
PHINS AI Model Registry (AI-3)
==============================
A minimal, dependency-light registry for named, versioned model artifacts. Lets
PHINS layer a transparent, trained model (e.g. a logistic/GLM scorer — the
actuarially-accepted family) *behind* the existing rule-based controller without
losing explainability or taking a hard ML dependency.

Reference: ``docs/INVESTOR_AI_BI_OPTIMIZATION_REVIEW.md`` §4 (AI-3) and the
``ModelVersion`` entity in ``docs/health_marketplace_architecture.md``.

Design / safety:
- **Rules stay authoritative by default.** No artifacts ship in the repo or the
  production image, so ``get_model`` returns ``None`` and the controller uses its
  deterministic rule scorer — behavior is byte-identical to today.
- **Optional heavy deps.** ``joblib`` is imported lazily; if it is absent the
  registry simply has no loadable models. Nothing in the runtime path imports a
  numeric/ML stack at module load.
- **Models score; they never post.** A model only influences a *score*; the
  decision, the money movement, and the audit record still flow through the
  controller + ledger under rule/human gates.
- **Integrity-gated loading (no unsafe deserialization).** ``joblib.load`` uses
  ``pickle``, so loading an untrusted artifact is RCE. Artifacts are loaded only
  when ``PHINS_MODEL_HMAC_KEY`` is set AND a sidecar ``<artifact>.sig``
  HMAC-SHA256 digest verifies. Missing key / bad signature ⇒ fall back to rules.
- Artifacts are discovered from ``PHINS_MODEL_DIR`` (default ``models/``) and are
  confined to that directory (no path traversal).
"""

import hashlib
import hmac
import io
import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger('phins.ai_model_registry')

# Env var holding the secret used to verify model-artifact integrity. Model
# files are only loaded when a matching ``<artifact>.sig`` HMAC-SHA256 digest
# verifies against this key — see ``_signature_valid``.
MODEL_HMAC_KEY_ENV = 'PHINS_MODEL_HMAC_KEY'


class ModelHandle:
    """Wraps a loaded model artifact + its metadata."""

    def __init__(self, name: str, version: str, model: Any, path: str):
        self.name = name
        self.version = version
        self.model = model
        self.path = path

    @property
    def registry_id(self) -> str:
        return f"{self.name}:{self.version}"

    def score(self, features: Dict[str, Any]) -> Optional[float]:
        """Best-effort scoring. Returns None on any failure (caller falls back).

        Supports either a scikit-learn-style ``predict_proba`` or a plain
        ``predict``/callable. Never raises into the caller.
        """
        try:
            vector = [
                features.get(k) for k in sorted(features.keys())
                if isinstance(features.get(k), (int, float))
            ]
            model = self.model
            if hasattr(model, 'predict_proba'):
                proba = model.predict_proba([vector])
                return float(proba[0][-1])
            if hasattr(model, 'predict'):
                return float(model.predict([vector])[0])
            if callable(model):
                return float(model(features))
        except Exception as exc:
            logger.warning("Model %s scoring failed (falling back to rules): %s",
                           self.registry_id, exc)
        return None


class ModelRegistry:
    """Loads and serves named model artifacts from a directory."""

    def __init__(self, model_dir: Optional[str] = None):
        self.model_dir = model_dir or os.environ.get('PHINS_MODEL_DIR', 'models')
        self._cache: Dict[str, Optional[ModelHandle]] = {}
        self._lock = threading.Lock()

    def get_model(self, name: str) -> Optional[ModelHandle]:
        """Return the latest loadable model for ``name``, or None if none exists.

        Returning None is the normal, expected case in demo/test/prod-today:
        the controller then uses its rule-based scorer.
        """
        with self._lock:
            if name in self._cache:
                return self._cache[name]
            handle = self._load(name)
            self._cache[name] = handle
            return handle

    @staticmethod
    def _signature_valid(path: str, data: bytes) -> bool:
        """Verify a model artifact's HMAC-SHA256 signature before deserializing.

        SECURITY: ``joblib.load`` uses ``pickle`` under the hood, so loading an
        untrusted artifact is remote code execution. We therefore refuse to load
        any model unless:
          1. ``PHINS_MODEL_HMAC_KEY`` is configured (operator opt-in), and
          2. a sidecar ``<artifact>.sig`` file contains the correct
             HMAC-SHA256 hex digest of the artifact bytes under that key.
        Missing key or missing/invalid signature ⇒ do not load (fall back to
        rules). This closes the deserialization RCE path while keeping the safe
        default (no artifacts, rules authoritative).
        """
        key = os.environ.get(MODEL_HMAC_KEY_ENV)
        if not key:
            logger.warning(
                "Model artifact present but %s is not set; refusing to load "
                "untrusted artifact (serving rules). %s",
                MODEL_HMAC_KEY_ENV, path,
            )
            return False
        sig_path = path + '.sig'
        if not os.path.isfile(sig_path):
            logger.warning(
                "Model artifact %s has no .sig signature file; refusing to load.",
                path,
            )
            return False
        try:
            with open(sig_path, 'r', encoding='utf-8') as fh:
                expected = fh.read().strip()
        except Exception as exc:
            logger.warning("Could not read signature for %s: %s", path, exc)
            return False
        computed = hmac.new(key.encode('utf-8'), data, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, expected):
            logger.error(
                "Model artifact %s failed HMAC integrity check; refusing to load.",
                path,
            )
            return False
        return True

    def _load(self, name: str) -> Optional[ModelHandle]:
        if not os.path.isdir(self.model_dir):
            return None
        # Convention: models/<name>-<version>.joblib ; pick the lexically latest.
        candidates = [
            f for f in os.listdir(self.model_dir)
            if f.startswith(f"{name}-") and f.endswith('.joblib')
        ]
        if not candidates:
            return None
        latest = sorted(candidates)[-1]
        version = latest[len(name) + 1:-len('.joblib')]
        path = os.path.join(self.model_dir, latest)

        # SECURITY: confine to the model dir (no traversal) and verify integrity
        # BEFORE any deserialization happens.
        abs_dir = os.path.abspath(self.model_dir)
        abs_path = os.path.abspath(path)
        if not abs_path.startswith(abs_dir + os.sep):
            logger.error("Model path %s escapes model dir; refusing to load.", abs_path)
            return None
        try:
            with open(abs_path, 'rb') as fh:
                data = fh.read()
        except Exception as exc:
            logger.warning("Failed to read model %s: %s", abs_path, exc)
            return None
        if not self._signature_valid(abs_path, data):
            return None

        try:
            import joblib  # lazy, optional
        except Exception:
            logger.info("joblib not installed; registry serving rules only for '%s'", name)
            return None
        try:
            # Load from the already-read, integrity-verified bytes.
            model = joblib.load(io.BytesIO(data))
        except Exception as exc:
            logger.warning("Failed to load model %s: %s", abs_path, exc)
            return None
        logger.info("Loaded verified model %s:%s from %s", name, version, abs_path)
        return ModelHandle(name, version, model, abs_path)

    def reload(self) -> None:
        with self._lock:
            self._cache.clear()


_model_registry: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    global _model_registry
    if _model_registry is None:
        _model_registry = ModelRegistry()
    return _model_registry


__all__ = ['ModelRegistry', 'ModelHandle', 'get_model_registry']
