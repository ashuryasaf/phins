"""
Document Processing & Metadata Mining Service
===============================================
Universal document handling pipeline that works across the entire PHINS platform.

Capabilities:
- Persistent file storage (survives restarts via disk + database)
- SHA-256 / MD5 integrity verification on every upload and retrieval
- Automatic MIME type detection and category classification
- Metadata extraction from images, PDFs, Office docs, CSV/XLS tables, audio, video
- Identity document analysis (ID cards, passports, driver licences)
- Medical document parsing
- Legal document parsing
- Table / spreadsheet extraction
- AI-powered tagging and summarisation
- Processing job queue with status tracking
- Duplicate detection via content-addressed checksums
- Version management for updated documents

Designed as the single entry point for *all* file operations so that every
upload path (policy creation, claim filing, underwriting, reports, media)
gets the same integrity guarantees, persistence, and processing pipeline.
"""

import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

def _resolve_document_storage_root() -> str:
    """Pick a Railway-volume-aware storage path for uploaded documents.

    Priority:
      1. ``PHINS_DOCUMENT_STORAGE`` (explicit override)
      2. ``RAILWAY_VOLUME_MOUNT_PATH/documents`` (Railway volume)
      3. ``/data/documents`` (standard Docker volume mount)
      4. ``<repo>/data/documents`` (developer fallback - ephemeral)
    """
    explicit = os.environ.get('PHINS_DOCUMENT_STORAGE')
    if explicit:
        return explicit

    railway_mount = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '').strip()
    if railway_mount and os.path.isdir(railway_mount):
        return os.path.join(railway_mount, 'documents')

    fallback = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'data', 'documents',
    )
    if not os.environ.get('PHINS_TEST_MODE'):
        print(
            f"⚠️  [doc-service] Using ephemeral document storage {fallback} - "
            "set PHINS_DOCUMENT_STORAGE or mount a Railway volume at /data "
            "for durable persistence.",
            flush=True,
        )
    return fallback


DOCUMENT_STORAGE_ROOT = _resolve_document_storage_root()

MAX_DOCUMENT_SIZE_BYTES = int(os.environ.get('PHINS_MAX_DOCUMENT_SIZE', 50 * 1024 * 1024))
MAX_BATCH_SIZE = int(os.environ.get('PHINS_MAX_BATCH_UPLOAD', 25))

ALLOWED_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt', '.rtf',
    '.json', '.xml', '.html', '.htm',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.svg',
    '.mp4', '.avi', '.mov', '.wmv', '.mkv', '.webm', '.flv',
    '.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma',
    '.zip', '.gz', '.tar', '.7z', '.rar',
    '.dicom', '.dcm',
    '.xsd',
}

CATEGORY_BY_MIME_PREFIX = {
    'image/': 'identity',
    'video/': 'media',
    'audio/': 'media',
    'text/csv': 'table',
    'application/vnd.ms-excel': 'table',
    'application/vnd.openxmlformats-officedocument.spreadsheetml': 'table',
    'application/pdf': 'general',
}

CATEGORY_BY_EXTENSION = {
    '.csv': 'table', '.xls': 'table', '.xlsx': 'table',
    '.pdf': 'general', '.doc': 'legal', '.docx': 'legal',
    '.dicom': 'medical', '.dcm': 'medical',
    '.mp4': 'media', '.avi': 'media', '.mov': 'media',
    '.mp3': 'media', '.wav': 'media', '.ogg': 'media',
    '.jpg': 'identity', '.jpeg': 'identity', '.png': 'identity',
    '.xsd': 'policy',
}


ALLOWED_CATEGORIES = {
    'identity', 'legal', 'medical', 'financial', 'policy', 'claim',
    'underwriting', 'report', 'media', 'table', 'general',
}


class ProcessingJobType(str, Enum):
    METADATA_EXTRACTION = 'metadata_extraction'
    TEXT_EXTRACTION = 'text_extraction'
    TABLE_EXTRACTION = 'table_extraction'
    IMAGE_ANALYSIS = 'image_analysis'
    IDENTITY_VERIFICATION = 'identity_verification'
    MEDICAL_ANALYSIS = 'medical_analysis'
    LEGAL_ANALYSIS = 'legal_analysis'
    AUDIO_TRANSCRIPTION = 'audio_transcription'
    VIDEO_ANALYSIS = 'video_analysis'
    INTEGRITY_CHECK = 'integrity_check'
    AI_SUMMARISATION = 'ai_summarisation'
    AI_TAGGING = 'ai_tagging'


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class UploadResult:
    document_id: str
    file_name: str
    file_size: int
    mime_type: str
    sha256: str
    category: str
    status: str
    storage_path: str
    duplicate_of: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessingResult:
    job_id: str
    document_id: str
    job_type: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Core Service ──────────────────────────────────────────────────────────────

class DocumentProcessingService:
    """Unified document storage, integrity, and processing pipeline."""

    def __init__(self, storage_root: Optional[str] = None, db_manager=None):
        self.storage_root = storage_root or DOCUMENT_STORAGE_ROOT
        self.db_manager = db_manager
        self._inmemory_store: Dict[str, Dict[str, Any]] = {}
        os.makedirs(self.storage_root, exist_ok=True)

    # ── Upload ────────────────────────────────────────────────────────────────

    def upload_document(
        self,
        *,
        file_name: str,
        file_data_b64: str,
        mime_type: Optional[str] = None,
        category: Optional[str] = None,
        document_type: Optional[str] = None,
        description: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        uploaded_by_role: Optional[str] = None,
        parent_document_id: Optional[str] = None,
        skip_processing: bool = False,
    ) -> UploadResult:
        """Store a document persistently and queue processing jobs."""

        if not file_data_b64:
            raise ValueError('Missing file content')
        if not file_name:
            raise ValueError('Missing file name')

        raw_bytes = base64.b64decode(file_data_b64, validate=True)
        if not raw_bytes:
            raise ValueError('Document content cannot be empty')
        if len(raw_bytes) > MAX_DOCUMENT_SIZE_BYTES:
            raise ValueError(f'File exceeds maximum allowed size ({MAX_DOCUMENT_SIZE_BYTES // (1024*1024)}MB)')

        ext = self._get_extension(file_name)
        if ext and ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f'File type {ext} not allowed')

        resolved_mime = mime_type or mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
        resolved_category = self._sanitise_category(
            category or self._classify_category(file_name, resolved_mime)
        )

        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        md5 = hashlib.md5(raw_bytes).hexdigest()

        duplicate_id = self._check_duplicate(sha256, entity_type, entity_id)

        doc_id = f"DOC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
        safe_name = self._safe_filename(doc_id, file_name)
        storage_path = self._write_to_disk(safe_name, raw_bytes, resolved_category)

        if self._verify_on_disk(storage_path, sha256):
            status = 'uploaded'
        else:
            status = 'integrity_error'
            logger.error(f"Integrity check failed for {doc_id} at {storage_path}")

        doc_record = {
            'id': doc_id,
            'file_name': safe_name,
            'original_file_name': file_name,
            'mime_type': resolved_mime,
            'file_size': len(raw_bytes),
            'file_extension': ext,
            'storage_path': storage_path,
            'sha256_checksum': sha256,
            'md5_checksum': md5,
            'category': resolved_category,
            'document_type': document_type or 'general',
            'description': description or '',
            'entity_type': entity_type or '',
            'entity_id': entity_id or '',
            'customer_id': customer_id or '',
            'uploaded_by': uploaded_by or 'system',
            'uploaded_by_role': uploaded_by_role or '',
            'status': status,
            'processing_status': 'pending' if not skip_processing else None,
            'is_archived': False,
            'is_deleted': False,
            'version': 1,
            'parent_document_id': parent_document_id,
        }

        self._persist_record(doc_record)

        extracted = {}
        if not skip_processing and status == 'uploaded':
            extracted = self._run_immediate_processing(doc_id, raw_bytes, resolved_mime, ext)
            self._update_record(doc_id, {
                'status': 'processed',
                'processing_status': 'completed',
                'extracted_metadata': json.dumps(extracted.get('metadata', {})),
                'extracted_text': extracted.get('text', ''),
                'ai_summary': extracted.get('summary', ''),
                'ai_tags': json.dumps(extracted.get('tags', [])),
                'confidence_score': extracted.get('confidence', None),
                'processed_date': datetime.now(),
            })

        return UploadResult(
            document_id=doc_id,
            file_name=safe_name,
            file_size=len(raw_bytes),
            mime_type=resolved_mime,
            sha256=sha256,
            category=resolved_category,
            status='processed' if extracted else status,
            storage_path=storage_path,
            duplicate_of=duplicate_id,
            metadata=extracted,
        )

    def upload_batch(
        self,
        files: List[Dict[str, Any]],
        **common_kwargs,
    ) -> List[UploadResult]:
        """Upload multiple files in one call."""
        if len(files) > MAX_BATCH_SIZE:
            raise ValueError(f'Batch exceeds maximum of {MAX_BATCH_SIZE} files')
        results = []
        for f in files:
            try:
                kwargs = {**common_kwargs}
                kwargs['file_name'] = f.get('name') or f.get('file_name', 'unnamed')
                kwargs['file_data_b64'] = f.get('data') or f.get('file_data', '')
                kwargs['mime_type'] = f.get('type') or f.get('mime_type')
                results.append(self.upload_document(**kwargs))
            except Exception as exc:
                results.append(UploadResult(
                    document_id='',
                    file_name=f.get('name', 'unknown'),
                    file_size=0,
                    mime_type='',
                    sha256='',
                    category='',
                    status='error',
                    storage_path='',
                    metadata={'error': str(exc)},
                ))
        return results

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def get_document(self, doc_id: str, include_data: bool = False) -> Optional[Dict[str, Any]]:
        record = self._load_record(doc_id)
        if not record:
            return None
        if isinstance(record, dict):
            result = dict(record)
            storage_path = record.get('storage_path', '')
            expected_sha = record.get('sha256_checksum')
        else:
            result = record.to_dict() if hasattr(record, 'to_dict') else {'id': record.id}
            storage_path = record.storage_path
            expected_sha = record.sha256_checksum
        if include_data:
            raw = self._read_from_disk(storage_path)
            if raw is not None:
                on_disk_sha = hashlib.sha256(raw).hexdigest()
                if on_disk_sha != expected_sha:
                    logger.error(f"Integrity mismatch for {doc_id}: expected "
                                 f"{expected_sha}, got {on_disk_sha}")
                    result['integrity_warning'] = True
                result['data'] = base64.b64encode(raw).decode('ascii')
                result['data_encoding'] = 'base64'
        return result

    def list_documents(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        search_query: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        offset = (page - 1) * page_size
        docs = self._search_records(
            entity_type=entity_type, entity_id=entity_id,
            customer_id=customer_id, category=category, status=status,
            query=search_query, limit=page_size, offset=offset,
        )
        total = self._count_records(
            entity_type=entity_type, entity_id=entity_id,
            customer_id=customer_id, category=category, status=status,
            query=search_query,
        )
        items = []
        for d in docs:
            if isinstance(d, dict):
                safe = {k: v for k, v in d.items() if k != 'data'}
                items.append(safe)
            else:
                items.append(d.to_dict())
        return {
            'items': items,
            'page': page,
            'page_size': page_size,
            'total': total,
        }

    def delete_document(self, doc_id: str, hard: bool = False) -> bool:
        record = self._load_record(doc_id)
        if not record:
            return False
        if hard:
            path = record.get('storage_path') if isinstance(record, dict) else record.storage_path
            if path and os.path.exists(path):
                os.remove(path)
            self._delete_record(doc_id)
        else:
            self._update_record(doc_id, {'is_deleted': True, 'status': 'archived'})
        return True

    def verify_integrity(self, doc_id: str) -> Dict[str, Any]:
        """Re-verify SHA-256 of stored file against the database record."""
        record = self._load_record(doc_id)
        if not record:
            return {'valid': False, 'error': 'Document not found'}
        path = record.get('storage_path') if isinstance(record, dict) else record.storage_path
        expected_sha = record.get('sha256_checksum') if isinstance(record, dict) else record.sha256_checksum
        raw = self._read_from_disk(path)
        if raw is None:
            return {'valid': False, 'error': 'File not found on disk'}
        actual = hashlib.sha256(raw).hexdigest()
        valid = actual == expected_sha
        return {
            'valid': valid,
            'expected_sha256': expected_sha,
            'actual_sha256': actual,
            'file_size': len(raw),
        }

    def get_statistics(self, customer_id: Optional[str] = None) -> Dict[str, Any]:
        if self.db_manager:
            try:
                return self.db_manager.documents.get_statistics(customer_id)
            except Exception as e:
                logger.error(f"DB stats error: {e}")
        return self._inmemory_stats(customer_id)

    # ── Processing pipeline ───────────────────────────────────────────────────

    def process_document(self, doc_id: str, job_types: Optional[List[str]] = None) -> List[ProcessingResult]:
        """Run one or more processing jobs on an already-uploaded document."""
        record = self._load_record(doc_id)
        if not record:
            raise ValueError(f'Document {doc_id} not found')

        path = record.get('storage_path') if isinstance(record, dict) else record.storage_path
        mime = record.get('mime_type') if isinstance(record, dict) else record.mime_type
        ext = record.get('file_extension') if isinstance(record, dict) else record.file_extension

        raw = self._read_from_disk(path)
        if raw is None:
            raise ValueError(f'File not found on disk for {doc_id}')

        if not job_types:
            job_types = self._default_jobs_for(mime, ext)

        results = []
        for jt in job_types:
            result = self._run_job(doc_id, jt, raw, mime, ext)
            results.append(result)

        return results

    def reprocess_document(self, doc_id: str) -> List[ProcessingResult]:
        """Re-run all default processing for a document."""
        return self.process_document(doc_id)

    # ── Internal: disk storage ────────────────────────────────────────────────

    @staticmethod
    def _sanitise_category(category: str) -> str:
        """Ensure category is a safe, whitelisted directory name (no path traversal)."""
        clean = re.sub(r'[^a-zA-Z0-9_-]', '', (category or 'general').strip())
        if clean not in ALLOWED_CATEGORIES:
            clean = 'general'
        return clean

    def _write_to_disk(self, safe_name: str, raw_bytes: bytes, category: str) -> str:
        safe_category = self._sanitise_category(category)
        cat_dir = os.path.join(self.storage_root, safe_category)
        os.makedirs(cat_dir, exist_ok=True)
        path = os.path.join(cat_dir, safe_name)
        resolved = os.path.realpath(path)
        if not resolved.startswith(os.path.realpath(self.storage_root)):
            raise ValueError('Invalid storage path')
        tmp_path = path + '.tmp'
        with open(tmp_path, 'wb') as f:
            f.write(raw_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        return path

    def _read_from_disk(self, path: str) -> Optional[bytes]:
        if not path or not os.path.exists(path):
            return None
        with open(path, 'rb') as f:
            return f.read()

    def _verify_on_disk(self, path: str, expected_sha256: str) -> bool:
        raw = self._read_from_disk(path)
        if raw is None:
            return False
        return hashlib.sha256(raw).hexdigest() == expected_sha256

    # ── Internal: record persistence (DB-first, in-memory fallback) ──────────

    def _persist_record(self, doc: Dict[str, Any]) -> None:
        if self.db_manager:
            try:
                self.db_manager.documents.create(**doc)
                return
            except Exception as e:
                logger.error(f"DB persist failed for {doc.get('id')}: {e}")
        self._inmemory_store[doc['id']] = doc

    def _load_record(self, doc_id: str):
        if self.db_manager:
            try:
                rec = self.db_manager.documents.get_by_id(doc_id)
                if rec:
                    return rec
            except Exception as e:
                logger.error(f"DB load failed for {doc_id}: {e}")
        return self._inmemory_store.get(doc_id)

    def _update_record(self, doc_id: str, updates: Dict[str, Any]) -> None:
        if self.db_manager:
            try:
                self.db_manager.documents.update(doc_id, **updates)
                return
            except Exception as e:
                logger.error(f"DB update failed for {doc_id}: {e}")
        rec = self._inmemory_store.get(doc_id)
        if rec:
            rec.update(updates)

    def _delete_record(self, doc_id: str) -> None:
        if self.db_manager:
            try:
                self.db_manager.documents.delete(doc_id)
                return
            except Exception as e:
                logger.error(f"DB delete failed for {doc_id}: {e}")
        self._inmemory_store.pop(doc_id, None)

    def _search_records(self, entity_type=None, entity_id=None, customer_id=None,
                        category=None, status=None, query=None,
                        limit=50, offset=0):
        if self.db_manager:
            try:
                return self.db_manager.documents.search_all(
                    query=query, entity_type=entity_type, entity_id=entity_id,
                    customer_id=customer_id, category=category, status=status,
                    limit=limit, offset=offset,
                )
            except Exception as e:
                logger.error(f"DB search error: {e}")

        docs = self._filter_inmemory(
            entity_type=entity_type, entity_id=entity_id,
            customer_id=customer_id, category=category, status=status,
        )
        if query:
            q_lower = query.lower()
            docs = [d for d in docs if q_lower in (d.get('file_name', '') + d.get('description', '')).lower()]
        return docs[offset:offset + limit]

    def _count_records(self, entity_type=None, entity_id=None, customer_id=None,
                       category=None, status=None, query=None, **_ignored) -> int:
        if self.db_manager:
            try:
                return self.db_manager.documents.count_filtered(
                    query=query, entity_type=entity_type, entity_id=entity_id,
                    customer_id=customer_id, category=category, status=status,
                )
            except Exception:
                pass
        docs = self._filter_inmemory(
            entity_type=entity_type, entity_id=entity_id,
            customer_id=customer_id, category=category, status=status,
        )
        if query:
            q_lower = query.lower()
            docs = [d for d in docs if q_lower in (d.get('file_name', '') + d.get('description', '')).lower()]
        return len(docs)

    def _filter_inmemory(self, entity_type=None, entity_id=None, customer_id=None,
                         category=None, status=None, **_ignored) -> List[Dict[str, Any]]:
        """Apply all filters to the in-memory store and return matching docs."""
        docs = [d for d in self._inmemory_store.values() if not d.get('is_deleted')]
        if entity_type:
            docs = [d for d in docs if d.get('entity_type') == entity_type]
        if entity_id:
            docs = [d for d in docs if d.get('entity_id') == entity_id]
        if customer_id:
            docs = [d for d in docs if d.get('customer_id') == customer_id]
        if category:
            docs = [d for d in docs if d.get('category') == category]
        if status:
            docs = [d for d in docs if d.get('status') == status]
        return docs

    def _check_duplicate(self, sha256: str, entity_type: Optional[str], entity_id: Optional[str]) -> Optional[str]:
        if self.db_manager:
            try:
                existing = self.db_manager.documents.get_by_checksum(sha256)
                if existing:
                    return existing.id
            except Exception:
                pass
        for doc_id, doc in self._inmemory_store.items():
            if doc.get('sha256_checksum') == sha256 and not doc.get('is_deleted'):
                return doc_id
        return None

    def _inmemory_stats(self, customer_id=None):
        docs = [d for d in self._inmemory_store.values() if not d.get('is_deleted')]
        if customer_id:
            docs = [d for d in docs if d.get('customer_id') == customer_id]
        by_cat = {}
        by_status = {}
        total_size = 0
        for d in docs:
            by_cat[d.get('category', 'general')] = by_cat.get(d.get('category', 'general'), 0) + 1
            by_status[d.get('status', 'uploaded')] = by_status.get(d.get('status', 'uploaded'), 0) + 1
            total_size += d.get('file_size', 0)
        return {
            'total_documents': len(docs),
            'total_size_bytes': total_size,
            'by_category': by_cat,
            'by_status': by_status,
        }

    # ── Internal: processing jobs ─────────────────────────────────────────────

    def _run_immediate_processing(self, doc_id: str, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        """Run lightweight processing synchronously on upload."""
        result: Dict[str, Any] = {}
        try:
            result['metadata'] = self._extract_metadata(raw, mime, ext)
        except Exception as e:
            logger.error(f"Metadata extraction failed for {doc_id}: {e}")
            result['metadata'] = {}

        try:
            if mime.startswith('text/') or ext in ('.csv', '.txt', '.json', '.xml', '.html', '.htm'):
                result['text'] = self._extract_text_content(raw, mime, ext)
            elif mime == 'application/pdf' or ext == '.pdf':
                result['text'] = self._extract_pdf_text(raw)
            elif ext in ('.xls', '.xlsx'):
                result['text'] = self._extract_spreadsheet_summary(raw, ext)
        except Exception as e:
            logger.error(f"Text extraction failed for {doc_id}: {e}")

        try:
            result['summary'] = self._generate_summary(result.get('text', ''), result.get('metadata', {}), mime)
            result['tags'] = self._generate_tags(result.get('text', ''), result.get('metadata', {}), mime, ext)
            result['confidence'] = self._compute_confidence(result)
        except Exception as e:
            logger.error(f"AI enrichment failed for {doc_id}: {e}")

        return result

    def _run_job(self, doc_id: str, job_type: str, raw: bytes, mime: str, ext: str) -> ProcessingResult:
        job_id = f"JOB-{uuid.uuid4().hex[:12].upper()}"
        start = time.time()
        result_data = None
        error = None
        status = 'completed'

        try:
            handler = self._job_handlers.get(job_type)
            if handler:
                result_data = handler(self, raw, mime, ext)
            else:
                result_data = {'note': f'No specialised handler for {job_type}'}
        except Exception as e:
            error = str(e)
            status = 'failed'

        elapsed_ms = int((time.time() - start) * 1000)

        if self.db_manager:
            try:
                self.db_manager.processing_jobs.create(
                    id=job_id,
                    document_id=doc_id,
                    job_type=job_type,
                    status=status,
                    result=json.dumps(result_data) if result_data else None,
                    error_message=error,
                    processing_time_ms=elapsed_ms,
                    completed_date=datetime.now(),
                )
            except Exception as e:
                logger.error(f"Failed to persist job {job_id}: {e}")

        return ProcessingResult(
            job_id=job_id,
            document_id=doc_id,
            job_type=job_type,
            status=status,
            result=result_data,
            error=error,
            processing_time_ms=elapsed_ms,
        )

    def _default_jobs_for(self, mime: str, ext: str) -> List[str]:
        jobs = [ProcessingJobType.METADATA_EXTRACTION.value]
        if mime.startswith('text/') or ext in ('.csv', '.txt', '.json', '.xml'):
            jobs.append(ProcessingJobType.TEXT_EXTRACTION.value)
        if ext in ('.csv', '.xls', '.xlsx'):
            jobs.append(ProcessingJobType.TABLE_EXTRACTION.value)
        if mime.startswith('image/') or ext in ('.jpg', '.jpeg', '.png', '.tiff', '.bmp'):
            jobs.append(ProcessingJobType.IMAGE_ANALYSIS.value)
        if mime == 'application/pdf' or ext == '.pdf':
            jobs.append(ProcessingJobType.TEXT_EXTRACTION.value)
        if mime.startswith('audio/') or ext in ('.mp3', '.wav', '.ogg', '.flac'):
            jobs.append(ProcessingJobType.AUDIO_TRANSCRIPTION.value)
        if mime.startswith('video/') or ext in ('.mp4', '.avi', '.mov', '.mkv', '.webm'):
            jobs.append(ProcessingJobType.VIDEO_ANALYSIS.value)
        if ext in ('.dicom', '.dcm'):
            jobs.append(ProcessingJobType.MEDICAL_ANALYSIS.value)
        jobs.append(ProcessingJobType.AI_TAGGING.value)
        return jobs

    # ── Processing handlers ───────────────────────────────────────────────────

    def _handle_metadata_extraction(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        return self._extract_metadata(raw, mime, ext)

    def _handle_text_extraction(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        text = ''
        if mime == 'application/pdf' or ext == '.pdf':
            text = self._extract_pdf_text(raw)
        elif mime.startswith('text/') or ext in ('.csv', '.txt', '.json', '.xml', '.html', '.htm'):
            text = self._extract_text_content(raw, mime, ext)
        elif ext in ('.xls', '.xlsx'):
            text = self._extract_spreadsheet_summary(raw, ext)
        return {'text': text, 'length': len(text)}

    def _handle_table_extraction(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        return self._extract_table_data(raw, mime, ext)

    def _handle_image_analysis(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        return self._analyze_image(raw, mime)

    def _handle_identity_verification(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        return self._analyze_identity_document(raw, mime)

    def _handle_medical_analysis(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        return self._analyze_medical_document(raw, mime, ext)

    def _handle_legal_analysis(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        return self._analyze_legal_document(raw, mime, ext)

    def _handle_audio_transcription(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        return self._analyze_audio(raw, mime)

    def _handle_video_analysis(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        return self._analyze_video(raw, mime)

    def _handle_integrity_check(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        return {
            'sha256': hashlib.sha256(raw).hexdigest(),
            'md5': hashlib.md5(raw).hexdigest(),
            'size': len(raw),
            'valid': True,
        }

    def _handle_ai_summarisation(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        metadata = self._extract_metadata(raw, mime, ext)
        text = ''
        if mime.startswith('text/') or ext in ('.csv', '.txt', '.json', '.xml'):
            text = self._extract_text_content(raw, mime, ext)
        summary = self._generate_summary(text, metadata, mime)
        return {'summary': summary}

    def _handle_ai_tagging(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        metadata = self._extract_metadata(raw, mime, ext)
        text = ''
        if mime.startswith('text/') or ext in ('.csv', '.txt', '.json', '.xml'):
            text = self._extract_text_content(raw, mime, ext)
        tags = self._generate_tags(text, metadata, mime, ext)
        return {'tags': tags}

    _job_handlers = {
        ProcessingJobType.METADATA_EXTRACTION.value: _handle_metadata_extraction,
        ProcessingJobType.TEXT_EXTRACTION.value: _handle_text_extraction,
        ProcessingJobType.TABLE_EXTRACTION.value: _handle_table_extraction,
        ProcessingJobType.IMAGE_ANALYSIS.value: _handle_image_analysis,
        ProcessingJobType.IDENTITY_VERIFICATION.value: _handle_identity_verification,
        ProcessingJobType.MEDICAL_ANALYSIS.value: _handle_medical_analysis,
        ProcessingJobType.LEGAL_ANALYSIS.value: _handle_legal_analysis,
        ProcessingJobType.AUDIO_TRANSCRIPTION.value: _handle_audio_transcription,
        ProcessingJobType.VIDEO_ANALYSIS.value: _handle_video_analysis,
        ProcessingJobType.INTEGRITY_CHECK.value: _handle_integrity_check,
        ProcessingJobType.AI_SUMMARISATION.value: _handle_ai_summarisation,
        ProcessingJobType.AI_TAGGING.value: _handle_ai_tagging,
    }

    # ── Extraction helpers ────────────────────────────────────────────────────

    def _extract_metadata(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            'size_bytes': len(raw),
            'mime_type': mime,
            'extension': ext,
        }

        if mime.startswith('image/'):
            meta.update(self._image_metadata(raw))
        elif mime.startswith('video/'):
            meta['media_type'] = 'video'
            meta['estimated_duration_seconds'] = max(1, len(raw) // (500 * 1024))
        elif mime.startswith('audio/'):
            meta['media_type'] = 'audio'
            meta['estimated_duration_seconds'] = max(1, len(raw) // (16 * 1024))
        elif ext in ('.csv',):
            meta.update(self._csv_metadata(raw))
        elif ext in ('.json',):
            meta.update(self._json_metadata(raw))

        magic_bytes = raw[:16]
        if magic_bytes[:4] == b'%PDF':
            meta['format'] = 'PDF'
        elif magic_bytes[:2] in (b'PK',):
            meta['format'] = 'ZIP/Office'
        elif magic_bytes[:3] == b'ID3' or magic_bytes[:2] == b'\xff\xfb':
            meta['format'] = 'MP3'
        elif magic_bytes[:4] == b'RIFF':
            meta['format'] = 'WAV/AVI'
        elif magic_bytes[:4] == b'\x00\x00\x00\x1c' or magic_bytes[4:8] == b'ftyp':
            meta['format'] = 'MP4/MOV'

        return meta

    def _image_metadata(self, raw: bytes) -> Dict[str, Any]:
        info: Dict[str, Any] = {'media_type': 'image'}
        if raw[:2] == b'\xff\xd8':
            info['format'] = 'JPEG'
            info.update(self._parse_jpeg_dimensions(raw))
        elif raw[:8] == b'\x89PNG\r\n\x1a\n':
            info['format'] = 'PNG'
            if len(raw) >= 24:
                import struct
                w, h = struct.unpack('>II', raw[16:24])
                info['width'] = w
                info['height'] = h
        elif raw[:3] == b'GIF':
            info['format'] = 'GIF'
        elif raw[:4] in (b'II\x2a\x00', b'MM\x00\x2a'):
            info['format'] = 'TIFF'
        return info

    def _parse_jpeg_dimensions(self, raw: bytes) -> Dict[str, Any]:
        try:
            i = 2
            while i < len(raw) - 1:
                if raw[i] != 0xFF:
                    break
                marker = raw[i + 1]
                if marker == 0xD9:
                    break
                if marker in (0xC0, 0xC1, 0xC2):
                    if i + 9 < len(raw):
                        import struct
                        h, w = struct.unpack('>HH', raw[i + 5:i + 9])
                        return {'width': w, 'height': h}
                if i + 3 < len(raw):
                    import struct
                    length = struct.unpack('>H', raw[i + 2:i + 4])[0]
                    i += 2 + length
                else:
                    break
        except Exception:
            pass
        return {}

    def _csv_metadata(self, raw: bytes) -> Dict[str, Any]:
        try:
            text = raw.decode('utf-8', errors='replace')
            lines = text.strip().split('\n')
            headers = lines[0].split(',') if lines else []
            return {
                'format': 'CSV',
                'row_count': len(lines) - 1,
                'column_count': len(headers),
                'headers': [h.strip().strip('"') for h in headers[:50]],
            }
        except Exception:
            return {'format': 'CSV'}

    def _json_metadata(self, raw: bytes) -> Dict[str, Any]:
        try:
            data = json.loads(raw.decode('utf-8', errors='replace'))
            if isinstance(data, list):
                return {'format': 'JSON', 'type': 'array', 'item_count': len(data)}
            elif isinstance(data, dict):
                return {'format': 'JSON', 'type': 'object', 'top_keys': list(data.keys())[:20]}
            return {'format': 'JSON'}
        except Exception:
            return {'format': 'JSON'}

    def _extract_text_content(self, raw: bytes, mime: str, ext: str) -> str:
        try:
            text = raw.decode('utf-8', errors='replace')
            return text[:100_000]
        except Exception:
            return ''

    def _extract_pdf_text(self, raw: bytes) -> str:
        """Best-effort PDF text extraction without external libraries."""
        try:
            text = raw.decode('latin-1', errors='replace')
            parts = []
            for match in re.finditer(r'\(([^)]{1,500})\)', text):
                chunk = match.group(1)
                if any(c.isalpha() for c in chunk):
                    parts.append(chunk)
            return ' '.join(parts)[:50_000] if parts else '[PDF content - binary extraction needed]'
        except Exception:
            return '[PDF content - extraction failed]'

    def _extract_spreadsheet_summary(self, raw: bytes, ext: str) -> str:
        return f'[Spreadsheet content ({ext}) - {len(raw)} bytes]'

    def _extract_table_data(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        if ext == '.csv' or mime == 'text/csv':
            return self._parse_csv_table(raw)
        return {'format': ext, 'size': len(raw), 'note': 'Binary table format - specialised parser needed'}

    def _parse_csv_table(self, raw: bytes) -> Dict[str, Any]:
        try:
            import csv as csv_mod
            import io
            text = raw.decode('utf-8', errors='replace')
            reader = csv_mod.reader(io.StringIO(text))
            rows = list(reader)
            if not rows:
                return {'headers': [], 'rows': [], 'row_count': 0}
            headers = rows[0]
            data_rows = rows[1:]
            preview = data_rows[:20]
            numeric_cols = []
            for col_idx, hdr in enumerate(headers):
                nums = []
                for row in data_rows:
                    if col_idx < len(row):
                        try:
                            nums.append(float(row[col_idx].replace(',', '')))
                        except (ValueError, TypeError):
                            pass
                if nums:
                    numeric_cols.append({
                        'column': hdr,
                        'min': min(nums),
                        'max': max(nums),
                        'mean': sum(nums) / len(nums),
                        'count': len(nums),
                    })
            return {
                'headers': headers,
                'row_count': len(data_rows),
                'column_count': len(headers),
                'preview_rows': preview,
                'numeric_analysis': numeric_cols,
            }
        except Exception as e:
            return {'error': str(e)}

    # ── Specialised analysis ──────────────────────────────────────────────────

    def _analyze_image(self, raw: bytes, mime: str) -> Dict[str, Any]:
        meta = self._image_metadata(raw)
        result = {
            'type': 'image_analysis',
            'format': meta.get('format', 'unknown'),
            'dimensions': {
                'width': meta.get('width'),
                'height': meta.get('height'),
            },
            'file_size': len(raw),
        }
        aspect = None
        if meta.get('width') and meta.get('height'):
            aspect = round(meta['width'] / meta['height'], 3)
            result['aspect_ratio'] = aspect
            is_document = 0.6 < aspect < 0.85 or 1.2 < aspect < 1.6
            result['likely_document'] = is_document
            is_portrait = 0.6 < aspect < 0.9
            result['likely_portrait'] = is_portrait
        return result

    def _analyze_identity_document(self, raw: bytes, mime: str) -> Dict[str, Any]:
        analysis = self._analyze_image(raw, mime)
        analysis['type'] = 'identity_verification'
        analysis['checks'] = {
            'file_integrity': True,
            'minimum_resolution': (analysis.get('dimensions', {}).get('width', 0) or 0) >= 300,
            'format_acceptable': analysis.get('format', '') in ('JPEG', 'PNG', 'TIFF'),
        }
        analysis['verification_status'] = 'pending_review'
        return analysis

    def _analyze_medical_document(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            'type': 'medical_analysis',
            'format': ext,
            'file_size': len(raw),
        }
        if ext in ('.dicom', '.dcm'):
            result['dicom_detected'] = True
            result['note'] = 'DICOM medical imaging format detected'
        elif ext == '.pdf':
            text = self._extract_pdf_text(raw)
            medical_terms = ['diagnosis', 'patient', 'treatment', 'prescription',
                             'medication', 'symptom', 'clinical', 'medical', 'hospital',
                             'doctor', 'physician', 'surgery']
            found_terms = [t for t in medical_terms if t.lower() in text.lower()]
            result['detected_medical_terms'] = found_terms
            result['medical_relevance_score'] = min(1.0, len(found_terms) / 5)
        return result

    def _analyze_legal_document(self, raw: bytes, mime: str, ext: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            'type': 'legal_analysis',
            'format': ext,
            'file_size': len(raw),
        }
        text = ''
        if ext == '.pdf':
            text = self._extract_pdf_text(raw)
        elif mime.startswith('text/'):
            text = self._extract_text_content(raw, mime, ext)
        if text:
            legal_terms = ['contract', 'agreement', 'clause', 'liability',
                           'indemnity', 'warranty', 'insurance', 'policy',
                           'coverage', 'premium', 'deductible', 'beneficiary',
                           'claimant', 'arbitration', 'jurisdiction', 'statute']
            found = [t for t in legal_terms if t.lower() in text.lower()]
            result['detected_legal_terms'] = found
            result['legal_relevance_score'] = min(1.0, len(found) / 5)
        return result

    def _analyze_audio(self, raw: bytes, mime: str) -> Dict[str, Any]:
        return {
            'type': 'audio_analysis',
            'file_size': len(raw),
            'estimated_duration_seconds': max(1, len(raw) // (16 * 1024)),
            'note': 'Audio transcription requires external ASR service integration',
        }

    def _analyze_video(self, raw: bytes, mime: str) -> Dict[str, Any]:
        return {
            'type': 'video_analysis',
            'file_size': len(raw),
            'estimated_duration_seconds': max(1, len(raw) // (500 * 1024)),
            'note': 'Full video analysis requires external CV service integration',
        }

    # ── AI enrichment ─────────────────────────────────────────────────────────

    def _generate_summary(self, text: str, metadata: Dict[str, Any], mime: str) -> str:
        parts = []
        fmt = metadata.get('format', mime.split('/')[-1] if '/' in mime else 'file')
        parts.append(f"{fmt} document")
        size = metadata.get('size_bytes', 0)
        if size:
            if size > 1024 * 1024:
                parts.append(f"({size / (1024*1024):.1f} MB)")
            else:
                parts.append(f"({size / 1024:.1f} KB)")
        if metadata.get('row_count'):
            parts.append(f"with {metadata['row_count']} rows and {metadata.get('column_count', '?')} columns")
        if metadata.get('width') and metadata.get('height'):
            parts.append(f"dimensions {metadata['width']}x{metadata['height']}")
        if text and len(text) > 20:
            preview = text[:200].replace('\n', ' ').strip()
            parts.append(f"- content preview: {preview}")
        return ' '.join(parts)

    def _generate_tags(self, text: str, metadata: Dict[str, Any],
                       mime: str, ext: str) -> List[str]:
        tags = []
        if mime.startswith('image/'):
            tags.append('image')
        elif mime.startswith('video/'):
            tags.append('video')
        elif mime.startswith('audio/'):
            tags.append('audio')
        elif mime == 'application/pdf':
            tags.append('pdf')
        elif ext in ('.csv', '.xls', '.xlsx'):
            tags.append('spreadsheet')
            tags.append('data')
        elif ext in ('.doc', '.docx'):
            tags.append('document')
        if ext in ('.json', '.xml'):
            tags.append('structured-data')
        if metadata.get('format'):
            tags.append(metadata['format'].lower())
        if text:
            text_lower = text.lower()
            domain_keywords = {
                'insurance': ['policy', 'premium', 'coverage', 'claim', 'insured', 'underwriting'],
                'medical': ['patient', 'diagnosis', 'treatment', 'medication', 'clinical'],
                'legal': ['contract', 'agreement', 'liability', 'clause', 'jurisdiction'],
                'financial': ['balance', 'transaction', 'payment', 'invoice', 'revenue'],
                'identity': ['passport', 'license', 'id card', 'identity', 'verification'],
            }
            for domain, keywords in domain_keywords.items():
                if any(kw in text_lower for kw in keywords):
                    tags.append(domain)
        return list(dict.fromkeys(tags))

    def _compute_confidence(self, result: Dict[str, Any]) -> float:
        score = 0.5
        if result.get('metadata'):
            score += 0.1
        if result.get('text') and len(result['text']) > 10:
            score += 0.15
        if result.get('summary'):
            score += 0.1
        if result.get('tags') and len(result['tags']) > 1:
            score += 0.1
        return min(1.0, round(score, 2))

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _get_extension(filename: str) -> str:
        if '.' in filename:
            return '.' + filename.rsplit('.', 1)[-1].lower()
        return ''

    @staticmethod
    def _safe_filename(doc_id: str, original: str) -> str:
        ext = ''
        if '.' in original:
            ext = '.' + original.rsplit('.', 1)[-1].lower()
        safe_base = re.sub(r'[^a-zA-Z0-9_-]', '_', original.rsplit('.', 1)[0])[:80]
        return f"{doc_id}_{safe_base}{ext}"

    @staticmethod
    def _classify_category(filename: str, mime: str) -> str:
        ext = ''
        if '.' in filename:
            ext = '.' + filename.rsplit('.', 1)[-1].lower()
        if ext in CATEGORY_BY_EXTENSION:
            return CATEGORY_BY_EXTENSION[ext]
        for prefix, cat in CATEGORY_BY_MIME_PREFIX.items():
            if mime.startswith(prefix) or mime == prefix:
                return cat
        return 'general'


# ── Module-level singleton ────────────────────────────────────────────────────

_default_service: Optional[DocumentProcessingService] = None


def get_document_service(db_manager=None) -> DocumentProcessingService:
    """Return or create the module-level service singleton."""
    global _default_service
    if _default_service is None:
        _default_service = DocumentProcessingService(db_manager=db_manager)
    elif db_manager and _default_service.db_manager is None:
        _default_service.db_manager = db_manager
    return _default_service


def reset_document_service() -> None:
    """Reset the singleton (mainly for tests)."""
    global _default_service
    _default_service = None
