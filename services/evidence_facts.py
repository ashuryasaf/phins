"""
Shared evidence pipeline for the Underwriting Bot and the Claims Bot (B1).

Both bots used to parse photos, PDFs, audio and video themselves. The
Document Intelligence pipeline already does that once per upload and records
what it found as :class:`~services.assessment_center_service.Fact` rows with
provenance (source snippet, char offsets, PDF page, audio/video timestamps).
This module is the read side of that store for the bots:

* :func:`facts_for` — every fact extracted from a set of document ids
  (indexed lookup, provenance untouched).
* :func:`bundle_for` — the same facts plus the cross-document
  ``contradiction`` facts among them and a content fingerprint over the
  documents' SHA-256 checksums.
* :func:`documents_for_entity` — the document ids attached to a claim /
  application through the document service (``entity_type``/``entity_id``).
* :class:`FeatureCache` — a bounded, process-wide LRU keyed by
  ``(namespace, sha256)`` so re-scoring a claim or an application whose
  evidence bytes have not changed is a cache hit instead of a re-parse.

Nothing here writes facts or documents. Contradictions are surfaced, never
resolved: a bundle reports them so the consuming bot can lower a score and
flag the file for a human, exactly as the pipeline recorded them.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, TypeVar

logger = logging.getLogger('phins.evidence_facts')

T = TypeVar('T')

#: Fact fields that constitute evidence provenance (spec: snippet, offsets,
#: page, timestamps). Kept as a tuple so consumers can project uniformly.
PROVENANCE_FIELDS = (
    'fact_id', 'fact_type', 'label', 'confidence', 'source_document_id',
    'source_document_sha256', 'source_text', 'char_start', 'char_end', 'page',
    'timestamp_start', 'timestamp_end', 'captured_at',
)


def _center(center=None):
    if center is not None:
        return center
    from services.assessment_center_service import get_assessment_center
    return get_assessment_center()


def _document_service(service=None):
    if service is not None:
        return service
    from services.document_processing_service import get_document_service
    return get_document_service()


def _fact_dict(fact: Any) -> Dict[str, Any]:
    if isinstance(fact, dict):
        return dict(fact)
    to_dict = getattr(fact, 'to_dict', None)
    if callable(to_dict):
        return to_dict()
    return dict(vars(fact))


def provenance_of(fact: Any) -> Dict[str, Any]:
    """Project a fact (dataclass or dict) onto its provenance fields."""
    data = _fact_dict(fact)
    return {key: data.get(key) for key in PROVENANCE_FIELDS}


# ---------------------------------------------------------------------------
# Facts by document
# ---------------------------------------------------------------------------

def facts_for(document_ids: Iterable[str], *, center=None) -> List[Any]:
    """All facts whose ``source_document_id`` is in ``document_ids``.

    Returns the store's :class:`Fact` objects (read-only view: callers must
    not mutate them). Unknown ids simply contribute nothing.
    """
    ids = [d for d in dict.fromkeys(document_ids) if d]
    if not ids:
        return []
    try:
        return list(_center(center).facts_for_documents(ids))
    except Exception as exc:  # the evidence store is advisory to the bots
        logger.warning("evidence facts unavailable for %d documents: %s", len(ids), exc)
        return []


def documents_for_entity(entity_type: str, entity_id: str, *, customer_id: Optional[str] = None,
                         service=None, limit: int = 200) -> List[Dict[str, Any]]:
    """Document records (without payload bytes) attached to an entity.

    ``entity_type``/``entity_id`` follow the document service's own linkage
    (``claim``/``CLM-…``, ``underwriting``/``UW-…``). Deleted documents are
    excluded. Returns ``[]`` when the document service is unavailable.
    """
    if not entity_type or not entity_id:
        return []
    try:
        listing = _document_service(service).list_documents(
            entity_type=entity_type, entity_id=entity_id, customer_id=customer_id,
            page=1, page_size=max(1, min(int(limit), 500)))
    except Exception as exc:
        logger.warning("document listing unavailable for %s/%s: %s", entity_type, entity_id, exc)
        return []
    items = listing.get('items') if isinstance(listing, dict) else listing
    return [d for d in (items or []) if isinstance(d, dict) and not d.get('is_deleted')]


def fingerprint(sha256s: Iterable[str]) -> str:
    """Order-independent content fingerprint over document checksums."""
    parts = sorted({str(s) for s in sha256s if s})
    if not parts:
        return ''
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()


@dataclass
class EvidenceBundle:
    """What the bots consume: facts + contradictions + a content fingerprint."""

    document_ids: List[str]
    sha256s: List[str]
    fingerprint: str
    facts: List[Dict[str, Any]] = field(default_factory=list)
    contradictions: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def document_count(self) -> int:
        return len(self.document_ids)

    @property
    def fact_count(self) -> int:
        return len(self.facts)

    def by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in self.facts:
            counts[f.get('fact_type', '')] = counts.get(f.get('fact_type', ''), 0) + 1
        return counts

    def provenance(self) -> List[Dict[str, Any]]:
        return [provenance_of(f) for f in self.facts]

    def extraction_incomplete(self) -> bool:
        """True when the pipeline recorded a no-text hint for any document."""
        return any(f.get('fact_type') == 'extraction_hint' for f in self.facts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'document_ids': list(self.document_ids),
            'document_count': self.document_count,
            'fingerprint': self.fingerprint,
            'fact_count': self.fact_count,
            'by_type': self.by_type(),
            'contradictions': len(self.contradictions),
            'extraction_incomplete': self.extraction_incomplete(),
        }


def bundle_for(document_ids: Iterable[str], *, sha256s: Optional[Iterable[str]] = None,
               center=None) -> EvidenceBundle:
    """Build an :class:`EvidenceBundle` for the given document ids.

    ``sha256s`` may be supplied by the caller (document listing already has
    them); otherwise the facts' ``source_document_sha256`` is used.
    Contradiction facts are included when they cite at least one of the
    requested documents — they are the pipeline's record of a conflict and
    are never dropped or merged here.
    """
    ids = [d for d in dict.fromkeys(document_ids) if d]
    raw_facts = facts_for(ids, center=center)
    facts = [_fact_dict(f) for f in raw_facts]
    plain = [f for f in facts if f.get('fact_type') != 'contradiction']
    shas = list(dict.fromkeys([s for s in (sha256s or []) if s] or
                              [f.get('source_document_sha256') for f in plain
                               if f.get('source_document_sha256')]))
    contradictions: List[Dict[str, Any]] = []
    if plain:
        # Contradiction facts have no source document of their own; they name
        # the documents in ``value.values[].document_ids``.
        wanted = set(ids)
        customer_ids = {f.get('customer_id') for f in plain if f.get('customer_id')}
        try:
            store = _center(center)
            for cust in customer_ids:
                for c in store.get_facts(cust, fact_type='contradiction'):
                    cited = {
                        d for v in ((c.get('value') or {}).get('values') or [])
                        for d in (v.get('document_ids') or [])
                    }
                    if cited & wanted:
                        contradictions.append(c)
        except Exception as exc:
            logger.warning("contradiction lookup skipped: %s", exc)
    return EvidenceBundle(document_ids=ids, sha256s=shas, fingerprint=fingerprint(shas),
                          facts=plain, contradictions=contradictions)


def bundle_for_entity(entity_type: str, entity_id: str, *, customer_id: Optional[str] = None,
                      center=None, service=None) -> EvidenceBundle:
    """``bundle_for`` over every document attached to ``entity_type/entity_id``."""
    docs = documents_for_entity(entity_type, entity_id, customer_id=customer_id, service=service)
    ids = [d.get('id') or d.get('document_id') for d in docs]
    shas = [d.get('sha256_checksum') or d.get('sha256') for d in docs]
    return bundle_for(ids, sha256s=shas, center=center)


# ---------------------------------------------------------------------------
# Feature cache
# ---------------------------------------------------------------------------

class FeatureCache:
    """Bounded LRU of derived features keyed by ``(namespace, sha256)``.

    The key is the content hash of the evidence the features were derived
    from, so a hit is only possible when the bytes are byte-identical; a
    changed document is a different key. Values are deep-copied on the way
    in and out so a consumer mutating its result cannot poison the cache.
    Thread-safe.
    """

    def __init__(self, max_entries: int = 4096):
        self.max_entries = max(0, int(max_entries))
        self._items: 'OrderedDict[Tuple[str, str], Any]' = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _copy(value: T) -> T:
        import copy
        return copy.deepcopy(value)

    def get(self, namespace: str, sha256: str) -> Tuple[Any, bool]:
        key = (str(namespace), str(sha256))
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                self.hits += 1
                return self._copy(self._items[key]), True
            self.misses += 1
            return None, False

    def put(self, namespace: str, sha256: str, value: Any) -> None:
        if self.max_entries <= 0 or not sha256:
            return
        key = (str(namespace), str(sha256))
        with self._lock:
            self._items[key] = self._copy(value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def get_or_compute(self, namespace: str, sha256: str, compute: Callable[[], T]) -> Tuple[T, bool]:
        """Return ``(value, hit)``; on a miss run ``compute`` and cache it.

        An empty ``sha256`` disables caching for that call (nothing to key on).
        """
        if sha256:
            value, hit = self.get(namespace, sha256)
            if hit:
                return value, True
        value = compute()
        if sha256:
            self.put(namespace, sha256, value)
        return value, False

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {'entries': len(self._items), 'hits': self.hits, 'misses': self.misses,
                    'max_entries': self.max_entries}

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self.hits = 0
            self.misses = 0


_feature_cache: Optional[FeatureCache] = None
_feature_cache_lock = threading.Lock()


def get_feature_cache() -> FeatureCache:
    global _feature_cache
    with _feature_cache_lock:
        if _feature_cache is None:
            import os
            _feature_cache = FeatureCache(
                max_entries=int(os.environ.get('PHINS_EVIDENCE_FEATURE_CACHE_MAX', '4096')))
        return _feature_cache


def reset_feature_cache() -> None:
    global _feature_cache
    with _feature_cache_lock:
        _feature_cache = None


__all__ = [
    'PROVENANCE_FIELDS', 'EvidenceBundle', 'FeatureCache', 'bundle_for', 'bundle_for_entity',
    'documents_for_entity', 'facts_for', 'fingerprint', 'get_feature_cache', 'provenance_of',
    'reset_feature_cache',
]
