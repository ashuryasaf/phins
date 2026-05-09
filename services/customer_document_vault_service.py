"""
Customer Document Vault Service
================================
Per-customer "durable object" view over every document related to a customer
on the PHINS platform - regardless of where the file was originally uploaded
(general document upload, claim filing, underwriting application, registration,
or persistent disk-backed document service).

Why this exists
---------------
Documents arrive through many entry points:

* ``/api/documents/upload`` (general)              -> ``POLICY_DOCUMENTS``
* ``/api/doc-service/upload`` (persistent)         -> ``DocumentProcessingService`` + mirrored into ``POLICY_DOCUMENTS``
* New claim filing                                  -> ``CLAIM_FILES`` (+ links on the claim record)
* New underwriting application                      -> ``UNDERWRITING_FILES`` (+ links on the application)
* Risk reports / assessments / generated PDFs       -> ``POLICY_DOCUMENTS`` (system-uploaded)

Without an aggregating layer, BI / Customer 360 / future AI reports have to
walk every store, dedupe by content, and reason about which docs really
belong to a given customer. ``CustomerDocumentVault`` does this once,
preserves SHA-256 integrity, and exposes a single durable structure the
rest of the platform - and the ``/documents.html`` UI - can rely on.

Design highlights
-----------------
* Read-mostly, idempotent aggregator: it never overwrites file bytes; it
  only fills in ``uploaded_by_customer`` / ``customer_id`` on records that
  are missing it (using the same resolver the upload endpoints already use).
* Deduplicates by SHA-256 across stores - the same file uploaded through
  two different paths surfaces once with all sources listed.
* Verifies the in-memory checksum against the persistent ``DocumentProcessingService``
  copy on read, surfacing ``integrity_status`` = ``ok`` / ``mismatch`` / ``missing``.
* Customer-keyed: every method takes ``customer_id`` and only returns
  documents linked to that customer (directly or via policy / claim /
  underwriting / billing entity).
* Safe in tests and production: tolerates missing services, missing
  database, and partial seed data.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _norm_str(value: Any) -> str:
    return str(value or "").strip()


def _norm_lower(value: Any) -> str:
    return _norm_str(value).lower()


def _safe_size(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sha256_b64(data_b64: Optional[str]) -> str:
    """Compute SHA-256 of base64-encoded payload without raising."""
    if not data_b64:
        return ""
    try:
        import base64

        raw = base64.b64decode(data_b64, validate=False)
        return hashlib.sha256(raw).hexdigest()
    except Exception:
        return ""


def _coerce_iso(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# ── Service ──────────────────────────────────────────────────────────────────


class CustomerDocumentVault:
    """Aggregates every document on the platform that belongs to a customer.

    The service is intentionally stateless: each call walks the in-memory
    stores supplied by ``web_portal.server`` and the persistent
    ``DocumentProcessingService``. Holding state would risk drift between
    the vault and the underlying records.
    """

    # Logical "source" labels surfaced in the API and UI. Kept stable for BI
    # downstream consumers - do not rename without coordinating dashboards.
    SOURCE_GENERAL = "general_documents"          # POLICY_DOCUMENTS via /api/documents/upload
    SOURCE_PERSISTENT = "persistent_store"        # DocumentProcessingService disk records
    SOURCE_CLAIM = "claim_attachments"            # CLAIM_FILES
    SOURCE_UNDERWRITING = "underwriting_attachments"  # UNDERWRITING_FILES

    # Maximum documents returned in a single vault response. The intent is to
    # keep payloads bounded for the dashboard while still being useful for BI;
    # callers that need everything can paginate by entity_type.
    DEFAULT_LIMIT = 500

    def __init__(
        self,
        *,
        policy_documents: Optional[Dict[str, Dict[str, Any]]] = None,
        claim_files: Optional[Dict[str, Dict[str, Any]]] = None,
        underwriting_files: Optional[Dict[str, Dict[str, Any]]] = None,
        claims: Optional[Dict[str, Dict[str, Any]]] = None,
        policies: Optional[Dict[str, Dict[str, Any]]] = None,
        billing: Optional[Dict[str, Dict[str, Any]]] = None,
        underwriting_applications: Optional[Dict[str, Dict[str, Any]]] = None,
        owner_resolver: Optional[Callable[[Dict[str, Any]], str]] = None,
        document_service: Any = None,
    ) -> None:
        self._policy_documents = policy_documents if policy_documents is not None else {}
        self._claim_files = claim_files if claim_files is not None else {}
        self._underwriting_files = underwriting_files if underwriting_files is not None else {}
        self._claims = claims if claims is not None else {}
        self._policies = policies if policies is not None else {}
        self._billing = billing if billing is not None else {}
        self._underwriting_applications = underwriting_applications if underwriting_applications is not None else {}
        self._owner_resolver = owner_resolver
        self._document_service = document_service

    # ── Public API ────────────────────────────────────────────────────────

    def get_vault(
        self,
        customer_id: str,
        *,
        entity_type: Optional[str] = None,
        document_type: Optional[str] = None,
        limit: Optional[int] = None,
        verify_integrity: bool = True,
    ) -> Dict[str, Any]:
        """Return the customer's full durable document collection.

        The returned shape is intentionally compatible with the existing
        ``/api/documents/list`` payload so the front-end can reuse the same
        rendering helpers when displaying the durable view.
        """
        customer_id = _norm_str(customer_id)
        if not customer_id:
            return self._empty_vault("")

        records = self._collect_records(customer_id)
        records = self._dedupe_by_checksum(records)

        if entity_type:
            entity_type_l = _norm_lower(entity_type)
            records = [r for r in records if _norm_lower(r.get("entity_type")) == entity_type_l]
        if document_type:
            document_type_l = _norm_lower(document_type)
            records = [r for r in records if _norm_lower(r.get("document_type")) == document_type_l]

        records.sort(key=lambda r: r.get("uploaded_at") or "", reverse=True)

        if verify_integrity:
            for record in records:
                record["integrity_status"] = self._verify_record_integrity(record)
        else:
            for record in records:
                record.setdefault("integrity_status", "unverified")

        summary = self._build_summary(customer_id, records)
        total = len(records)

        if limit is not None and limit >= 0:
            records = records[:limit]

        return {
            "success": True,
            "customer_id": customer_id,
            "vault_type": "customer_document_vault",
            "vault_version": "v1",
            "generated_at": datetime.now().isoformat(),
            "summary": summary,
            "documents": records,
            "total": total,
        }

    def get_summary(self, customer_id: str) -> Dict[str, Any]:
        """Lightweight per-customer aggregate suitable for BI / AI reports."""
        vault = self.get_vault(customer_id, verify_integrity=False)
        return {
            "success": True,
            "customer_id": _norm_str(customer_id),
            "summary": vault["summary"],
            "generated_at": vault["generated_at"],
        }

    def backfill_customer_attribution(self) -> Dict[str, int]:
        """Walk POLICY_DOCUMENTS and CLAIM_FILES and assign missing customer_id.

        Idempotent. Returns counters useful for startup logging / health checks.
        Does not mutate file bytes - only fills in the ``uploaded_by_customer``
        / ``customer_id`` field when a deterministic owner can be inferred from
        the document's linked entity (policy, claim, underwriting, billing).
        """
        backfilled_general = 0
        backfilled_claims = 0
        backfilled_underwriting = 0

        for doc in self._policy_documents.values():
            if not isinstance(doc, dict):
                continue
            if _norm_str(doc.get("uploaded_by_customer") or doc.get("customer_id")):
                continue
            owner = self._resolve_owner(doc)
            if owner:
                doc["uploaded_by_customer"] = owner
                backfilled_general += 1

        for cf in self._claim_files.values():
            if not isinstance(cf, dict):
                continue
            if _norm_str(cf.get("customer_id")):
                continue
            claim_id = _norm_str(cf.get("claim_id"))
            if not claim_id:
                continue
            claim = self._claims.get(claim_id) or {}
            owner = _norm_str(claim.get("customer_id"))
            if owner:
                cf["customer_id"] = owner
                backfilled_claims += 1

        for uf in self._underwriting_files.values():
            if not isinstance(uf, dict):
                continue
            if _norm_str(uf.get("customer_id")):
                continue
            app_id = _norm_str(uf.get("application_id"))
            if not app_id:
                continue
            app = self._underwriting_applications.get(app_id) or {}
            owner = _norm_str(app.get("customer_id"))
            if owner:
                uf["customer_id"] = owner
                backfilled_underwriting += 1

        return {
            "policy_documents": backfilled_general,
            "claim_files": backfilled_claims,
            "underwriting_files": backfilled_underwriting,
        }

    # ── Collection ────────────────────────────────────────────────────────

    def _collect_records(self, customer_id: str) -> List[Dict[str, Any]]:
        """Pull customer-linked documents from every known store."""
        out: List[Dict[str, Any]] = []
        out.extend(self._collect_policy_documents(customer_id))
        out.extend(self._collect_claim_files(customer_id))
        out.extend(self._collect_underwriting_files(customer_id))
        out.extend(self._collect_persistent_documents(customer_id, out))
        return out

    def _collect_policy_documents(self, customer_id: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for doc_id, doc in self._policy_documents.items():
            if not isinstance(doc, dict):
                continue
            owner = _norm_str(doc.get("uploaded_by_customer") or doc.get("customer_id"))
            if not owner:
                owner = self._resolve_owner(doc)
            if owner != customer_id:
                continue
            out.append(self._normalize_general_doc(doc_id, doc, owner))
        return out

    def _collect_claim_files(self, customer_id: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for file_id, cf in self._claim_files.items():
            if not isinstance(cf, dict):
                continue
            owner = _norm_str(cf.get("customer_id"))
            claim_id = _norm_str(cf.get("claim_id"))
            if not owner and claim_id:
                claim = self._claims.get(claim_id) or {}
                owner = _norm_str(claim.get("customer_id"))
            if owner != customer_id:
                continue
            out.append(self._normalize_claim_file(file_id, cf, owner))
        return out

    def _collect_underwriting_files(self, customer_id: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for file_id, uf in self._underwriting_files.items():
            if not isinstance(uf, dict):
                continue
            owner = _norm_str(uf.get("customer_id"))
            app_id = _norm_str(uf.get("application_id"))
            if not owner and app_id:
                app = self._underwriting_applications.get(app_id) or {}
                owner = _norm_str(app.get("customer_id"))
            if owner != customer_id:
                continue
            out.append(self._normalize_underwriting_file(file_id, uf, owner))
        return out

    def _collect_persistent_documents(
        self, customer_id: str, already_collected: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Pull from DocumentProcessingService, skipping items already mirrored."""
        if self._document_service is None:
            return []

        # Build a lookup of persistent IDs we've already accounted for via
        # POLICY_DOCUMENTS so the same persistent record is not surfaced twice.
        seen_persistent_ids = {
            _norm_str(d.get("persistent_doc_id"))
            for d in already_collected
            if _norm_str(d.get("persistent_doc_id"))
        }

        try:
            page = self._document_service.list_documents(
                customer_id=customer_id,
                page=1,
                page_size=self.DEFAULT_LIMIT,
            )
        except Exception as exc:
            logger.warning("Persistent document list failed for %s: %s", customer_id, exc)
            return []

        out: List[Dict[str, Any]] = []
        for item in (page or {}).get("items", []) or []:
            if not isinstance(item, dict):
                continue
            persistent_id = _norm_str(item.get("id"))
            if persistent_id and persistent_id in seen_persistent_ids:
                continue
            owner = _norm_str(item.get("customer_id"))
            if owner != customer_id:
                continue
            out.append(self._normalize_persistent_doc(item, customer_id))
        return out

    # ── Normalization ─────────────────────────────────────────────────────

    def _normalize_general_doc(
        self, doc_id: str, doc: Dict[str, Any], owner_customer_id: str
    ) -> Dict[str, Any]:
        sha = _norm_str(doc.get("sha256")) or _sha256_b64(doc.get("data"))
        return {
            "id": _norm_str(doc.get("id") or doc_id),
            "name": _norm_str(doc.get("name")),
            "type": _norm_str(doc.get("type")) or "application/octet-stream",
            "size": _safe_size(doc.get("size")),
            "sha256": sha,
            "entity_type": _norm_lower(doc.get("entity_type")) or "general",
            "entity_id": _norm_str(doc.get("entity_id")),
            "document_type": _norm_lower(doc.get("document_type")) or "general",
            "description": _norm_str(doc.get("description")),
            "uploaded_at": _coerce_iso(doc.get("uploaded_at")),
            "uploaded_by": _norm_str(doc.get("uploaded_by")),
            "uploaded_by_customer": owner_customer_id,
            "has_data": bool(doc.get("data")) or bool(doc.get("persistent_doc_id")) or bool(doc.get("storage_path")),
            "ai_analysis": doc.get("ai_analysis"),
            "assessment_summary": doc.get("assessment_summary"),
            "persistent_doc_id": _norm_str(doc.get("persistent_doc_id")),
            "storage_path": _norm_str(doc.get("storage_path")),
            "source": self.SOURCE_GENERAL,
            "view_url": f"/api/documents/view?id={doc.get('id') or doc_id}",
        }

    def _normalize_claim_file(
        self, file_id: str, cf: Dict[str, Any], owner_customer_id: str
    ) -> Dict[str, Any]:
        sha = _sha256_b64(cf.get("data"))
        claim_id = _norm_str(cf.get("claim_id"))
        return {
            "id": _norm_str(cf.get("id") or file_id),
            "name": _norm_str(cf.get("name")),
            "type": _norm_str(cf.get("type")) or "application/octet-stream",
            "size": _safe_size(cf.get("size")),
            "sha256": sha,
            "entity_type": "claim",
            "entity_id": claim_id,
            "document_type": "general",
            "description": _norm_str(cf.get("note")),
            "uploaded_at": _coerce_iso(cf.get("uploaded_at")),
            "uploaded_by": _norm_str(cf.get("uploaded_by")) or "customer",
            "uploaded_by_customer": owner_customer_id,
            "has_data": bool(cf.get("data")),
            "ai_analysis": None,
            "assessment_summary": None,
            "persistent_doc_id": "",
            "storage_path": "",
            "source": self.SOURCE_CLAIM,
            # Browser-friendly query-style endpoint mirrors the
            # /api/documents/view?id=... convention so the "Open" link in the
            # durable-objects UI works without special-casing every store.
            "view_url": f"/api/claims/files/view?id={cf.get('id') or file_id}",
        }

    def _normalize_underwriting_file(
        self, file_id: str, uf: Dict[str, Any], owner_customer_id: str
    ) -> Dict[str, Any]:
        sha = _sha256_b64(uf.get("data"))
        app_id = _norm_str(uf.get("application_id"))
        return {
            "id": _norm_str(uf.get("id") or file_id),
            "name": _norm_str(uf.get("name")),
            "type": _norm_str(uf.get("type")) or "application/octet-stream",
            "size": _safe_size(uf.get("size")),
            "sha256": sha,
            "entity_type": "underwriting",
            "entity_id": app_id,
            "document_type": "general",
            "description": _norm_str(uf.get("note")),
            "uploaded_at": _coerce_iso(uf.get("uploaded_at")),
            "uploaded_by": _norm_str(uf.get("uploaded_by")) or "customer",
            "uploaded_by_customer": owner_customer_id,
            "has_data": bool(uf.get("data")),
            "ai_analysis": None,
            "assessment_summary": None,
            "persistent_doc_id": "",
            "storage_path": "",
            "source": self.SOURCE_UNDERWRITING,
            "view_url": f"/api/underwriting/files/view?id={uf.get('id') or file_id}",
        }

    def _normalize_persistent_doc(self, item: Dict[str, Any], owner_customer_id: str) -> Dict[str, Any]:
        return {
            "id": _norm_str(item.get("id")),
            "name": _norm_str(item.get("original_file_name") or item.get("file_name")),
            "type": _norm_str(item.get("mime_type")) or "application/octet-stream",
            "size": _safe_size(item.get("file_size")),
            "sha256": _norm_str(item.get("sha256_checksum")),
            "entity_type": _norm_lower(item.get("entity_type")) or "general",
            "entity_id": _norm_str(item.get("entity_id")),
            "document_type": _norm_lower(item.get("document_type")) or "general",
            "description": _norm_str(item.get("description")),
            "uploaded_at": _coerce_iso(item.get("created_date") or item.get("uploaded_at")),
            "uploaded_by": _norm_str(item.get("uploaded_by")),
            "uploaded_by_customer": owner_customer_id,
            "has_data": True,
            "ai_analysis": None,
            "assessment_summary": None,
            "persistent_doc_id": _norm_str(item.get("id")),
            "storage_path": _norm_str(item.get("storage_path")),
            "source": self.SOURCE_PERSISTENT,
            "view_url": f"/api/doc-service/view?id={_norm_str(item.get('id'))}",
        }

    # ── Dedupe / integrity ────────────────────────────────────────────────

    def _dedupe_by_checksum(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Combine records with identical SHA-256 - keep the richer entry, list all sources."""
        by_key: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for record in records:
            sha = _norm_str(record.get("sha256"))
            # When checksum is missing (legacy or unreadable file), fall back
            # to (name, size, source) so we don't accidentally collapse different
            # files into one.
            key = sha or f"{record.get('name')}|{record.get('size')}|{record.get('source')}"
            existing = by_key.get(key)
            if existing is None:
                record_copy = dict(record)
                record_copy["sources"] = [record.get("source")]
                by_key[key] = record_copy
                order.append(key)
                continue

            # Merge: keep the entry that has more useful data, append source.
            sources = existing.get("sources") or []
            if record.get("source") and record["source"] not in sources:
                sources.append(record["source"])
            existing["sources"] = sources

            # Promote richer fields if missing on the existing one.
            for field in ("ai_analysis", "assessment_summary", "persistent_doc_id", "storage_path"):
                if not existing.get(field) and record.get(field):
                    existing[field] = record[field]
            if not existing.get("has_data") and record.get("has_data"):
                existing["has_data"] = True
                if record.get("view_url"):
                    existing["view_url"] = record["view_url"]
            # Prefer earliest known upload time so the timeline is meaningful.
            existing_at = existing.get("uploaded_at") or ""
            record_at = record.get("uploaded_at") or ""
            if record_at and (not existing_at or record_at < existing_at):
                existing["uploaded_at"] = record_at

        return [by_key[k] for k in order]

    def _verify_record_integrity(self, record: Dict[str, Any]) -> str:
        """Cross-check the record's SHA-256 against the persistent store.

        Returns one of: ``ok``, ``mismatch``, ``unverified``, ``missing``.

        ``ok`` is only returned when the persistent ``DocumentProcessingService``
        was actually able to re-hash the file and the recomputed digest matched
        the recorded SHA-256. Records with no persistent counterpart - claim /
        underwriting attachments held in memory, or general docs where the
        persistent store is offline - return ``unverified`` so the UI doesn't
        misleadingly render a green "✅ OK" badge for something we never
        actually re-hashed. Never raises - integrity verification must not
        block reads.
        """
        sha = _norm_str(record.get("sha256"))
        persistent_id = _norm_str(record.get("persistent_doc_id"))
        if not sha and not persistent_id:
            return "unverified"
        if self._document_service is None or not persistent_id:
            # No way to cross-check the file bytes against a stored digest, so
            # we cannot honestly call this ``ok``. The presence of a SHA-256 on
            # the in-memory record only proves we hashed the upload payload
            # once; it doesn't re-verify the bytes are still intact.
            return "unverified"
        try:
            verification = self._document_service.verify_integrity(persistent_id)
        except Exception:
            return "unverified"
        if not verification.get("valid"):
            if "not found" in _norm_lower(verification.get("error")):
                return "missing"
            return "mismatch"
        return "ok"

    # ── Owner resolution / summary ────────────────────────────────────────

    def _resolve_owner(self, doc: Dict[str, Any]) -> str:
        if self._owner_resolver is not None:
            try:
                return _norm_str(self._owner_resolver(doc))
            except Exception:
                pass
        explicit = _norm_str(doc.get("uploaded_by_customer") or doc.get("customer_id"))
        if explicit:
            return explicit
        entity_type = _norm_lower(doc.get("entity_type"))
        entity_id = _norm_str(doc.get("entity_id"))
        if not entity_id:
            return ""
        if entity_type == "customer":
            return entity_id
        if entity_type == "policy":
            return _norm_str((self._policies.get(entity_id) or {}).get("customer_id"))
        if entity_type == "claim":
            return _norm_str((self._claims.get(entity_id) or {}).get("customer_id"))
        if entity_type == "underwriting":
            return _norm_str((self._underwriting_applications.get(entity_id) or {}).get("customer_id"))
        if entity_type == "billing":
            return _norm_str((self._billing.get(entity_id) or {}).get("customer_id"))
        return ""

    def _build_summary(self, customer_id: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        by_entity: Dict[str, int] = {}
        by_doc_type: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        integrity_counts: Dict[str, int] = {}
        total_bytes = 0
        last_upload = ""
        with_ai_analysis = 0
        with_assessment = 0

        for r in records:
            by_entity[r.get("entity_type") or "general"] = by_entity.get(r.get("entity_type") or "general", 0) + 1
            by_doc_type[r.get("document_type") or "general"] = (
                by_doc_type.get(r.get("document_type") or "general", 0) + 1
            )
            for src in r.get("sources") or [r.get("source")]:
                if not src:
                    continue
                by_source[src] = by_source.get(src, 0) + 1
            integrity_counts[r.get("integrity_status", "unverified")] = (
                integrity_counts.get(r.get("integrity_status", "unverified"), 0) + 1
            )
            total_bytes += _safe_size(r.get("size"))
            ts = r.get("uploaded_at") or ""
            if ts and ts > last_upload:
                last_upload = ts
            if r.get("ai_analysis"):
                with_ai_analysis += 1
            if r.get("assessment_summary"):
                with_assessment += 1

        return {
            "customer_id": customer_id,
            "document_count": len(records),
            "total_bytes": total_bytes,
            "by_entity_type": by_entity,
            "by_document_type": by_doc_type,
            "by_source": by_source,
            "integrity": integrity_counts,
            "with_ai_analysis": with_ai_analysis,
            "with_assessment_summary": with_assessment,
            "last_upload_at": last_upload,
        }

    def _empty_vault(self, customer_id: str) -> Dict[str, Any]:
        return {
            "success": True,
            "customer_id": customer_id,
            "vault_type": "customer_document_vault",
            "vault_version": "v1",
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "customer_id": customer_id,
                "document_count": 0,
                "total_bytes": 0,
                "by_entity_type": {},
                "by_document_type": {},
                "by_source": {},
                "integrity": {},
                "with_ai_analysis": 0,
                "with_assessment_summary": 0,
                "last_upload_at": "",
            },
            "documents": [],
            "total": 0,
        }


# ── Module-level helper that web_portal/server.py can call without
#    needing to import the class directly (keeps the handler thin). ───────────


def build_default_vault(
    *,
    policy_documents: Dict[str, Dict[str, Any]],
    claim_files: Dict[str, Dict[str, Any]],
    underwriting_files: Dict[str, Dict[str, Any]],
    claims: Dict[str, Dict[str, Any]],
    policies: Dict[str, Dict[str, Any]],
    billing: Dict[str, Dict[str, Any]],
    underwriting_applications: Dict[str, Dict[str, Any]],
    owner_resolver: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> CustomerDocumentVault:
    """Construct a vault wired up to the running portal's in-memory stores."""
    document_service = None
    try:
        from services.document_processing_service import get_document_service

        document_service = get_document_service()
    except Exception as exc:
        logger.info("CustomerDocumentVault running without persistent service: %s", exc)

    return CustomerDocumentVault(
        policy_documents=policy_documents,
        claim_files=claim_files,
        underwriting_files=underwriting_files,
        claims=claims,
        policies=policies,
        billing=billing,
        underwriting_applications=underwriting_applications,
        owner_resolver=owner_resolver,
        document_service=document_service,
    )
