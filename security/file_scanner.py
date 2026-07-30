"""File upload security scanner for PHINS.

Provides multi-layered defence against malicious file uploads:

1. **Magic-byte validation** — rejects files whose content does not match the
   declared MIME type (e.g. an EXE renamed to ``.pdf``).
2. **Dangerous-content heuristics** — scans raw bytes for embedded scripts,
   executable stubs, macro signatures, and polyglot attack patterns.
3. **Filename sanitisation** — strips path components, null bytes, double
   extensions, and unicode trickery.
4. **Size enforcement** — per-type configurable caps.
5. **Quarantine helpers** — move suspect files to a quarantine directory
   instead of serving them.

The module is deliberately dependency-free (stdlib only) so it loads before
any third-party package and cannot be bypassed by a missing ``pip install``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import struct
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = [
    "ScanVerdict",
    "scan_file_bytes",
    "scan_base64_payload",
    "sanitize_filename",
    "is_allowed_extension",
    "quarantine_file",
    "get_quarantine_log",
]

LOGGER = logging.getLogger("phins.security.file_scanner")

# ── configurable limits ──────────────────────────────────────────────────────

MAX_UPLOAD_SIZE = int(os.environ.get("PHINS_MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
MAX_FILENAME_LENGTH = 255
QUARANTINE_DIR = os.environ.get(
    "PHINS_QUARANTINE_DIR",
    os.path.join(tempfile.gettempdir(), "phins_quarantine"),
)

# ── allowed file types with magic bytes ──────────────────────────────────────

MAGIC_SIGNATURES: Dict[str, List[bytes]] = {
    "application/pdf": [b"%PDF"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # RIFF header; actual "WEBP" at offset 8
    "image/bmp": [b"BM"],
    "image/tiff": [b"II\x2a\x00", b"MM\x00\x2a"],
    "application/zip": [b"PK\x03\x04", b"PK\x05\x06"],
    "text/csv": [],  # no reliable magic; allow if extension matches
    "text/plain": [],
    "application/json": [],
    "application/xml": [b"<?xml"],
}

ALLOWED_EXTENSIONS: Set[str] = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".csv", ".txt", ".json", ".xml", ".doc", ".docx",
    ".xls", ".xlsx", ".zip",
    # Media module core formats (admin-media / video-agents uploads)
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mp3", ".wav", ".m4a",
}

DANGEROUS_EXTENSIONS: Set[str] = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".pif", ".vbs",
    ".vbe", ".js", ".jse", ".wsf", ".wsh", ".ps1", ".psm1", ".psd1",
    ".sh", ".bash", ".csh", ".ksh", ".elf", ".dll", ".so", ".dylib",
    ".app", ".deb", ".rpm", ".dmg", ".iso", ".img", ".bin",
    ".class", ".jar", ".war", ".py", ".pyc", ".pyo", ".rb", ".php",
    ".asp", ".aspx", ".jsp", ".cgi", ".pl", ".htaccess", ".reg",
    ".inf", ".lnk", ".sys", ".drv",
}

# ── dangerous content patterns ───────────────────────────────────────────────

_EXECUTABLE_HEADERS = [
    b"MZ",          # DOS/PE (Windows EXE/DLL)
    b"\x7fELF",     # Linux ELF
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit
    b"\xca\xfe\xba\xbe",  # Java class / universal Mach-O
    b"\xd0\xcf\x11\xe0",  # OLE2 (older Office with macros)
]

_SCRIPT_PATTERNS: List[re.Pattern[bytes]] = [
    re.compile(rb"<\s*script[\s>]", re.IGNORECASE),
    re.compile(rb"<\s*iframe[\s>]", re.IGNORECASE),
    re.compile(rb"<\s*object[\s>]", re.IGNORECASE),
    re.compile(rb"<\s*embed[\s>]", re.IGNORECASE),
    re.compile(rb"<\s*applet[\s>]", re.IGNORECASE),
    re.compile(rb"javascript\s*:", re.IGNORECASE),
    re.compile(rb"vbscript\s*:", re.IGNORECASE),
    re.compile(rb"on(load|error|click|mouse)\s*=", re.IGNORECASE),
    re.compile(rb"eval\s*\(", re.IGNORECASE),
    re.compile(rb"document\.(cookie|write|location)", re.IGNORECASE),
]

_MACRO_SIGNATURES: List[bytes] = [
    b"AutoOpen",
    b"AutoExec",
    b"Document_Open",
    b"Auto_Open",
    b"Workbook_Open",
    b"\\x00VBA",
    b"ThisDocument",
    b"powershell",
    b"cmd.exe",
    b"/bin/sh",
    b"/bin/bash",
]

_ARCHIVE_BOMBS_HEURISTIC_RATIO = 100  # compressed-to-raw ratio

# ── quarantine registry (in-memory, bounded) ─────────────────────────────────

_quarantine_lock = threading.Lock()
_quarantine_log: List[Dict[str, Any]] = []
_QUARANTINE_LOG_MAX = 500


# ── data classes ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScanVerdict:
    """Result of scanning an uploaded file."""

    safe: bool
    threats: Tuple[str, ...] = ()
    file_hash: str = ""
    detected_type: str = ""
    filename_sanitized: str = ""

    @property
    def threat_summary(self) -> str:
        return "; ".join(self.threats) if self.threats else "clean"


# ── public API ───────────────────────────────────────────────────────────────

def scan_file_bytes(
    data: bytes,
    *,
    filename: str = "",
    declared_content_type: str = "",
    max_size: int = 0,
) -> ScanVerdict:
    """Scan raw file bytes and return a verdict.

    Parameters
    ----------
    data : bytes
        The raw upload payload.
    filename : str
        Original client-supplied filename (used for extension checks).
    declared_content_type : str
        The MIME type declared by the client or multipart header.
    max_size : int
        Override the global ``MAX_UPLOAD_SIZE`` for this scan (0 = use global).
    """
    threats: List[str] = []
    effective_max = max_size if max_size > 0 else MAX_UPLOAD_SIZE

    # 1) Size check
    if len(data) > effective_max:
        threats.append(f"file_too_large ({len(data)} > {effective_max})")

    if len(data) == 0:
        threats.append("empty_file")

    # 2) Filename sanitisation
    clean_name = sanitize_filename(filename) if filename else ""

    # 3) Extension checks
    ext = _extract_extension(clean_name)
    if ext and ext.lower() in DANGEROUS_EXTENSIONS:
        threats.append(f"dangerous_extension ({ext})")
    if ext and not is_allowed_extension(ext):
        threats.append(f"disallowed_extension ({ext})")

    # 4) Double-extension attack
    if _has_double_extension(filename):
        threats.append("double_extension_attack")

    # 5) Magic-byte validation
    detected_type = _detect_type_by_magic(data)
    if declared_content_type and detected_type:
        if not _types_compatible(declared_content_type, detected_type):
            threats.append(
                f"content_type_mismatch (declared={declared_content_type}, "
                f"detected={detected_type})"
            )

    # 6) Executable header detection
    for sig in _EXECUTABLE_HEADERS:
        if data[:len(sig)] == sig:
            threats.append(f"executable_header ({sig[:4]!r})")
            break

    # 7) Embedded script / HTML injection detection
    scan_window = data[:8192] + (data[-4096:] if len(data) > 8192 else b"")
    for pattern in _SCRIPT_PATTERNS:
        if pattern.search(scan_window):
            threats.append(f"embedded_script ({pattern.pattern[:40]})")
            break

    # 8) Macro / shell command signatures
    data_lower = data[:32768].lower() if len(data) > 0 else b""
    for sig in _MACRO_SIGNATURES:
        if sig.lower() in data_lower:
            threats.append(f"macro_or_shell_signature ({sig!r})")
            break

    # 9) Null-byte injection in content (polyglot attacks)
    if filename and b"\x00" in filename.encode("utf-8", errors="replace"):
        threats.append("null_byte_in_filename")

    # 10) Zip/archive bomb heuristic (very basic — ratio check)
    if data[:2] == b"PK" and len(data) < 1024:
        threats.append("suspicious_tiny_archive")

    # Compute hash for audit trail
    file_hash = hashlib.sha256(data).hexdigest()

    verdict = ScanVerdict(
        safe=len(threats) == 0,
        threats=tuple(threats),
        file_hash=file_hash,
        detected_type=detected_type or declared_content_type or "unknown",
        filename_sanitized=clean_name,
    )

    if not verdict.safe:
        LOGGER.warning(
            "[FILE_SCAN] BLOCKED upload — file=%s hash=%s threats=%s",
            clean_name or "(unnamed)",
            file_hash[:16],
            verdict.threat_summary,
        )

    return verdict


def scan_base64_payload(
    b64_data: str,
    *,
    filename: str = "",
    declared_content_type: str = "",
    max_size: int = 0,
) -> ScanVerdict:
    """Decode a base64 payload and scan the resulting bytes."""
    threats: List[str] = []
    try:
        raw = base64.b64decode(b64_data, validate=True)
    except Exception:
        try:
            raw = base64.b64decode(b64_data)
        except Exception:
            return ScanVerdict(
                safe=False,
                threats=("invalid_base64_encoding",),
                file_hash="",
                detected_type="",
                filename_sanitized=sanitize_filename(filename) if filename else "",
            )

    return scan_file_bytes(
        raw,
        filename=filename,
        declared_content_type=declared_content_type,
        max_size=max_size,
    )


def sanitize_filename(name: str) -> str:
    """Return a safe, flat filename stripped of path traversal and special chars."""
    if not name:
        return "unnamed_upload"

    name = name.replace("\x00", "")

    name = unicodedata.normalize("NFKC", name)

    name = PurePosixPath(name).name
    name = name.replace("\\", "/").split("/")[-1]

    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)

    name = re.sub(r"\.{2,}", ".", name)

    if len(name) > MAX_FILENAME_LENGTH:
        base, ext = os.path.splitext(name)
        name = base[: MAX_FILENAME_LENGTH - len(ext)] + ext

    if not name or name.startswith("."):
        name = "upload_" + name

    return name


def is_allowed_extension(ext: str) -> bool:
    """Check whether *ext* (with leading dot) is in the allow-list."""
    return ext.lower() in ALLOWED_EXTENSIONS


def quarantine_file(
    data: bytes,
    *,
    filename: str = "",
    reason: str = "",
    client_ip: str = "",
) -> str:
    """Move suspicious file data to the quarantine directory.

    Returns the quarantine path.  The original bytes are written as-is so
    forensic analysis is possible; they are **never** served to clients.
    """
    os.makedirs(QUARANTINE_DIR, exist_ok=True)

    file_hash = hashlib.sha256(data).hexdigest()[:16]
    ts = int(time.time())
    safe_name = sanitize_filename(filename) if filename else "unnamed"
    quarantine_name = f"quarantine_{ts}_{file_hash}_{safe_name}"
    quarantine_path = os.path.join(QUARANTINE_DIR, quarantine_name)

    with open(quarantine_path, "wb") as fh:
        fh.write(data)

    entry = {
        "timestamp": ts,
        "filename": filename,
        "sanitized": safe_name,
        "reason": reason,
        "client_ip": client_ip,
        "hash": file_hash,
        "quarantine_path": quarantine_path,
        "size": len(data),
    }
    with _quarantine_lock:
        _quarantine_log.append(entry)
        if len(_quarantine_log) > _QUARANTINE_LOG_MAX:
            _quarantine_log[:] = _quarantine_log[-_QUARANTINE_LOG_MAX:]

    LOGGER.warning(
        "[QUARANTINE] file=%s reason=%s ip=%s hash=%s",
        filename, reason, client_ip, file_hash,
    )
    return quarantine_path


def get_quarantine_log(limit: int = 50) -> List[Dict[str, Any]]:
    """Return the most recent quarantine entries (for admin dashboard)."""
    with _quarantine_lock:
        return list(_quarantine_log[-limit:])


# ── internal helpers ─────────────────────────────────────────────────────────

def _extract_extension(filename: str) -> str:
    if not filename:
        return ""
    _, ext = os.path.splitext(filename)
    return ext.lower()


def _has_double_extension(filename: str) -> bool:
    """Detect ``payload.pdf.exe`` style double-extension tricks."""
    if not filename:
        return False
    parts = filename.rsplit(".", maxsplit=3)
    if len(parts) >= 3:
        suspected_real_ext = "." + parts[-1].lower()
        hidden_ext = "." + parts[-2].lower()
        if suspected_real_ext in DANGEROUS_EXTENSIONS:
            return True
        if hidden_ext in DANGEROUS_EXTENSIONS and suspected_real_ext in ALLOWED_EXTENSIONS:
            return True
    return False


def _detect_type_by_magic(data: bytes) -> str:
    """Best-effort MIME detection from leading bytes."""
    if not data:
        return ""
    for mime, signatures in MAGIC_SIGNATURES.items():
        for sig in signatures:
            if data[:len(sig)] == sig:
                if mime == "image/webp" and len(data) >= 12:
                    if data[8:12] != b"WEBP":
                        continue
                return mime
    return ""


def _types_compatible(declared: str, detected: str) -> bool:
    """Loose compatibility check between declared and detected MIME types."""
    d1 = declared.lower().split(";")[0].strip()
    d2 = detected.lower().split(";")[0].strip()
    if d1 == d2:
        return True
    compat_groups = [
        {"application/zip", "application/x-zip-compressed", "application/octet-stream"},
        {"text/plain", "text/csv", "application/csv"},
        {"image/jpeg", "image/jpg"},
        {"image/tiff", "image/tif"},
        {"application/xml", "text/xml"},
    ]
    for group in compat_groups:
        if d1 in group and d2 in group:
            return True
    if d1 == "application/octet-stream":
        return True
    return False
