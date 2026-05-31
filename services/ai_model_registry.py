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
- Artifacts are discovered from ``PHINS_MODEL_DIR`` (default ``models/``).
"""

import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger('phins.ai_model_registry')


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
        try:
            import joblib  # lazy, optional
        except Exception:
            logger.info("joblib not installed; registry serving rules only for '%s'", name)
            return None
        latest = sorted(candidates)[-1]
        version = latest[len(name) + 1:-len('.joblib')]
        path = os.path.join(self.model_dir, latest)
        try:
            model = joblib.load(path)
        except Exception as exc:
            logger.warning("Failed to load model %s: %s", path, exc)
            return None
        logger.info("Loaded model %s:%s from %s", name, version, path)
        return ModelHandle(name, version, model, path)

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
