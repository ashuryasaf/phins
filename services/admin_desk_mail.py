"""GoDaddy attribution and the one-time mailbox password for the Admin Desk.

The domain token (``GODADDY_API_TOKEN`` or ``GODADDY_PAT``, otherwise
``GODADDY_API_KEY`` + ``GODADDY_API_SECRET``) is read from the environment.
This module only sends GET requests: mailbox list, eligibility, and domain
ownership. It never provisions a mailbox.

The mailbox password is a separate secret. An admin submits it once. It is
Fernet-encrypted and written to the vault file (mode 0600). The desk record
stores that it was saved, never the password and never the ciphertext. A
vault that would store the password in the clear is refused.

Microsoft 365 mail (the current ``phins.ai`` MX) does not accept that
password for IMAP. The password stays in the vault and is not transmitted.
GoDaddy Email / Titan (``imap.secureserver.net``) is the path that logs in
with the saved password.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

_LOCK = threading.Lock()
_FILE_VERSION = 1
_API_BASE = "https://api.godaddy.com"
_MX = 15
_NS = 2
_TXT = 16

_CONNECTION_NOTES = {
    "connected": "Password saved, and the mailbox accepted it.",
    "auth_failed": "Password saved for email use. The mailbox refused the login.",
    "probe_failed": "Password saved for email use. The mail host could not be reached.",
    "mail_host_unconfirmed": "Password saved for email use. The mail host is not confirmed, so the password stays in the vault.",
    "microsoft_365_basic_auth_disabled": (
        "Password saved for email use. This mailbox is Microsoft 365. "
        "Microsoft accepts modern sign-in for IMAP, so the password stays in the vault."
    ),
}


class MailVaultError(Exception):
    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.message = message
        self.status = status


def connection_note(code: str) -> str:
    return _CONNECTION_NOTES.get(str(code or ""), "")


def vault_path() -> str:
    explicit = (os.environ.get("PHINS_ADMIN_DESK_MAIL_VAULT_PATH") or "").strip()
    if explicit:
        return explicit
    for directory in (os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ""), "/data"):
        if directory and os.path.isdir(directory):
            return os.path.join(directory, "phins_admin_desk_mail_vault.json")
    return os.path.join(tempfile.gettempdir(), "phins_admin_desk_mail_vault.json")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_book() -> Dict[str, Any]:
    path = vault_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"version": _FILE_VERSION, "entries": {}}
    except (OSError, json.JSONDecodeError) as exc:
        raise MailVaultError("mail_vault_unavailable") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        raise MailVaultError("mail_vault_unavailable")
    return data


def _write_book(data: Dict[str, Any]) -> None:
    path = vault_path()
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".phins_mail_vault.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _entry_password(entry: Any) -> str:
    if not isinstance(entry, dict) or entry.get("scheme") != "fernet":
        return ""
    from security.vault import decrypt_json

    loaded = decrypt_json(json.dumps({
        "scheme": entry.get("scheme"),
        "ciphertext": entry.get("ciphertext") or "",
    }))
    if not isinstance(loaded, dict):
        return ""
    password = loaded.get("password")
    if not isinstance(password, str) or not password:
        return ""
    return password


def password_saved(mailbox_id: str) -> bool:
    try:
        entry = _read_book()["entries"].get(mailbox_id)
    except MailVaultError:
        return False
    return bool(_entry_password(entry))


def save_password(mailbox_id: str, password: str) -> None:
    """Encrypt ``password`` for this mailbox. The clear value is not written."""
    clean_id = str(mailbox_id or "").strip()
    if not clean_id:
        raise MailVaultError("Mailbox not found", 404)
    if not isinstance(password, str) or not password.strip():
        raise MailVaultError("Enter the mailbox password", 400)
    if len(password) > 256:
        raise MailVaultError("Enter the mailbox password", 400)
    from security.vault import encrypt_json

    blob = encrypt_json({"password": password})
    if blob.scheme != "fernet":
        raise MailVaultError("mail_vault_unavailable", 503)
    with _LOCK:
        book = _read_book()
        book["entries"][clean_id] = {
            "scheme": "fernet",
            "ciphertext": blob.ciphertext,
            "saved_at": _now(),
        }
        book["version"] = _FILE_VERSION
        _write_book(book)


def load_password(mailbox_id: str) -> str:
    with _LOCK:
        entry = _read_book()["entries"].get(mailbox_id)
    return _entry_password(entry)


def _auth_header() -> str:
    token = (os.environ.get("GODADDY_API_TOKEN") or os.environ.get("GODADDY_PAT") or "").strip()
    if token:
        return "Bearer " + token
    key = (os.environ.get("GODADDY_API_KEY") or "").strip()
    secret = (os.environ.get("GODADDY_API_SECRET") or "").strip()
    if key and secret:
        return "sso-key " + key + ":" + secret
    return ""


def godaddy_configured() -> bool:
    return bool(_auth_header())


def _api_base() -> str:
    raw = (os.environ.get("GODADDY_API_BASE") or _API_BASE).strip().rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        return _API_BASE
    return raw


def _default_transport(method: str, url: str, headers: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    if method != "GET":
        return 0, {}
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(1_000_000)
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            raw = exc.read(1_000_000)
        except Exception:
            raw = b""
    except Exception:
        return 0, {}
    try:
        parsed = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return status, {}
    if isinstance(parsed, dict):
        return status, parsed
    if isinstance(parsed, list):
        return status, {"items": parsed}
    return status, {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _issue_codes(body: Dict[str, Any]) -> List[str]:
    codes = []
    for item in body.get("details") or []:
        if isinstance(item, dict) and item.get("issue"):
            codes.append(str(item["issue"])[:80])
    return codes


def _nameservers() -> List[str]:
    found = []
    try:
        with open("/etc/resolv.conf", "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    found.append(parts[1])
    except OSError:
        pass
    return found or ["8.8.8.8"]


def _encode_name(name: str) -> bytes:
    out = b""
    for label in name.rstrip(".").split("."):
        raw = label.encode("idna")
        if not raw or len(raw) > 63:
            raise ValueError("label")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def _decode_name(packet: bytes, offset: int) -> Tuple[str, int]:
    labels: List[str] = []
    jumped = False
    cursor = offset
    hops = 0
    while True:
        if cursor >= len(packet):
            raise ValueError("truncated")
        length = packet[cursor]
        if length == 0:
            cursor += 1
            break
        if length & 0xC0 == 0xC0:
            if cursor + 1 >= len(packet):
                raise ValueError("truncated")
            pointer = ((length & 0x3F) << 8) | packet[cursor + 1]
            if pointer >= len(packet):
                raise ValueError("pointer")
            if not jumped:
                offset = cursor + 2
            cursor = pointer
            jumped = True
            hops += 1
            if hops > 8:
                raise ValueError("pointer")
            continue
        cursor += 1
        if cursor + length > len(packet):
            raise ValueError("truncated")
        labels.append(packet[cursor:cursor + length].decode("ascii", "replace"))
        cursor += length
    if not jumped:
        offset = cursor
    return ".".join(labels), offset


def parse_dns(packet: bytes, expect_id: Optional[int] = None) -> Dict[str, List[str]]:
    """Pull NS, MX, and TXT names out of one DNS response."""
    if len(packet) < 12:
        raise ValueError("short")
    tid, _flags, qd, an, _ns, _ar = struct.unpack(">HHHHHH", packet[:12])
    if expect_id is not None and tid != expect_id:
        raise ValueError("id")
    offset = 12
    for _ in range(qd):
        _name, offset = _decode_name(packet, offset)
        offset += 4
    found: Dict[str, List[str]] = {"NS": [], "MX": [], "TXT": []}
    for _ in range(an):
        _name, offset = _decode_name(packet, offset)
        if offset + 10 > len(packet):
            break
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", packet[offset:offset + 10])
        offset += 10
        end = offset + rdlen
        if end > len(packet):
            break
        rdata = packet[offset:end]
        if rtype == _NS:
            host, _ = _decode_name(packet, offset)
            found["NS"].append(host)
        elif rtype == _MX and len(rdata) >= 2:
            host, _ = _decode_name(packet, offset + 2)
            found["MX"].append(host)
        elif rtype == _TXT:
            texts = []
            cursor = 0
            while cursor < len(rdata):
                size = rdata[cursor]
                cursor += 1
                texts.append(rdata[cursor:cursor + size].decode("utf-8", "replace"))
                cursor += size
            found["TXT"].append("".join(texts))
        offset = end
    return found


def _query(server: str, name: str, qtype: int) -> Dict[str, List[str]]:
    tid = int.from_bytes(os.urandom(2), "big")
    packet = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    packet += _encode_name(name) + struct.pack(">HH", qtype, 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    try:
        sock.sendto(packet, (server, 53))
        data, _addr = sock.recvfrom(4096)
    finally:
        sock.close()
    return parse_dns(data, tid)


def lookup_dns(domain: str) -> Dict[str, Any]:
    """Public DNS for the domain. Failure is reported; the password is not involved."""
    empty = {
        "available": False,
        "error": "dns_lookup_failed",
        "nameservers": [],
        "nameservers_at_godaddy": False,
        "mx": [],
        "txt": [],
        "mail_product": "unknown",
        "imap_host": "",
        "imap_port": 993,
        "spf_includes_godaddy": False,
        "tenant_name": "",
    }
    collected = {"NS": [], "MX": [], "TXT": []}
    try:
        servers = _nameservers()
        for qtype, key in ((_NS, "NS"), (_MX, "MX"), (_TXT, "TXT")):
            last_error = ""
            for server in servers[:2]:
                try:
                    answer = _query(server, domain, qtype)
                    collected[key] = answer.get(key) or []
                    last_error = ""
                    break
                except Exception as exc:
                    last_error = exc.__class__.__name__
            if last_error and not collected[key]:
                empty["error"] = "dns_lookup_failed"
    except Exception:
        return empty
    if not any(collected.values()):
        return empty
    return classify_dns(collected["NS"], collected["MX"], collected["TXT"])


def classify_dns(nameservers: List[str], mx_hosts: List[str], txt_records: List[str]) -> Dict[str, Any]:
    ns = [item.rstrip(".").lower() for item in nameservers if item]
    mx = [item.rstrip(".").lower() for item in mx_hosts if item]
    txt = [str(item).strip().strip('"') for item in txt_records if str(item).strip()]
    product = "unknown"
    imap_host = ""
    if any(host.endswith("mail.protection.outlook.com") or host.endswith("protection.outlook.com") for host in mx):
        product = "microsoft_365"
        imap_host = "outlook.office365.com"
    elif any(host.endswith("secureserver.net") or host.endswith("titan.email") for host in mx):
        product = "godaddy_email"
        imap_host = "imap.secureserver.net"
    tenant = ""
    for record in txt:
        if record.lower().endswith(".onmicrosoft.com"):
            tenant = record
            break
    return {
        "available": True,
        "error": "",
        "nameservers": ns,
        "nameservers_at_godaddy": any(host.endswith("domaincontrol.com") for host in ns),
        "mx": mx,
        "txt": txt,
        "mail_product": product,
        "imap_host": imap_host,
        "imap_port": 993,
        "spf_includes_godaddy": any("include:secureserver.net" in record.lower() for record in txt),
        "tenant_name": tenant,
    }


def _same_host(url: str, base: str) -> bool:
    target = urllib.parse.urlparse(url)
    root = urllib.parse.urlparse(base)
    return target.scheme == "https" and target.hostname == root.hostname


def _get_json(url: str, header: str, transport: Callable, base: str) -> Tuple[int, Dict[str, Any]]:
    if not _same_host(url, base):
        return 0, {}
    try:
        status, body = transport("GET", url, {"Authorization": header, "Accept": "application/json"})
    except Exception:
        return 0, {}
    if not isinstance(body, dict):
        return status, {}
    return status, body


def attribute_mailbox(
    address: str,
    *,
    transport: Optional[Callable] = None,
    dns_lookup: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Read-only check: is this address on the GoDaddy account that holds the domain?"""
    clean = str(address or "").strip().lower()
    domain = clean.split("@", 1)[1] if "@" in clean else ""
    lookup = dns_lookup or lookup_dns
    try:
        dns = lookup(domain) if domain else classify_dns([], [], [])
    except Exception:
        dns = classify_dns([], [], [])
        dns["available"] = False
        dns["error"] = "dns_lookup_failed"
    if not isinstance(dns, dict):
        dns = classify_dns([], [], [])
    if not dns.get("available") and domain:
        dns = dict(dns)
        dns.setdefault("error", "dns_lookup_failed")
    api: Dict[str, Any] = {
        "configured": godaddy_configured(),
        "checked": False,
        "reason": "",
        "domain_on_account": None,
        "mailbox_on_account": None,
        "mailbox_type": "",
        "mailbox_status": "",
        "eligible": None,
        "issues": [],
    }
    report: Dict[str, Any] = {
        "address": clean,
        "domain": domain,
        "dns": {key: value for key, value in dns.items() if key != "txt"},
        "godaddy_api": api,
        "same_account": None,
        "same_account_basis": "",
        "verdict": "token_not_configured",
    }
    # SPF and the tenant name are the TXT facts the desk shows. The rest of
    # the TXT set can carry unrelated records, so it stays out of the report.
    report["dns"]["spf_includes_godaddy"] = bool(dns.get("spf_includes_godaddy"))
    report["dns"]["tenant_name"] = dns.get("tenant_name") or ""
    header = _auth_header()
    if not header or not domain:
        api["reason"] = "godaddy_token_not_configured"
        report["mail_product"] = dns.get("mail_product") or "unknown"
        report["imap_host"] = dns.get("imap_host") or ""
        report["password_login"] = _password_login(report)
        return report

    caller = transport or _default_transport
    base = _api_base()
    domain_status, _domain_body = _get_json(
        base + "/v1/domains/" + urllib.parse.quote(domain), header, caller, base,
    )
    if domain_status == 200:
        api["domain_on_account"] = True
    elif domain_status == 404:
        api["domain_on_account"] = False
    else:
        api["reason"] = "domain_lookup_" + str(domain_status or "failed")

    listed = None
    list_url = (
        base + "/v1/email/mailboxes?field=mailboxId,emailAddress,mailboxType,status&pageSize=100"
    )
    for _page in range(10):
        status, body = _get_json(list_url, header, caller, base)
        if status != 200:
            api["reason"] = api["reason"] or ("mailbox_list_" + str(status or "failed"))
            listed = None
            break
        listed = False if listed is None else listed
        for item in body.get("items") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("emailAddress") or "").strip().lower() == clean:
                listed = True
                api["mailbox_type"] = str(item.get("mailboxType") or "")
                api["mailbox_status"] = str(item.get("status") or "")
                break
        if listed:
            break
        nxt = ""
        for link in body.get("links") or []:
            if isinstance(link, dict) and link.get("rel") == "next" and link.get("href"):
                href = str(link["href"])
                nxt = href if href.startswith("https://") else base + href
        if not nxt:
            break
        list_url = nxt
    api["mailbox_on_account"] = listed

    elig_url = base + "/v1/email/check-mailbox-eligibility?email=" + urllib.parse.quote(clean)
    elig_status, elig_body = _get_json(elig_url, header, caller, base)
    if elig_status == 200:
        api["eligible"] = bool(elig_body.get("isEligible"))
        if not api["mailbox_type"]:
            accounts = elig_body.get("eligibleAccounts") or []
            if accounts and isinstance(accounts[0], dict):
                api["mailbox_type"] = str(accounts[0].get("mailboxType") or "")
    elif elig_status == 422:
        api["eligible"] = False
        api["issues"] = _issue_codes(elig_body)
    elif elig_status:
        api["reason"] = api["reason"] or ("eligibility_" + str(elig_status))

    api["checked"] = True
    exists = "EMAIL_ADDRESS_ALREADY_EXISTS" in api["issues"]
    if listed:
        report["same_account"] = True
        report["same_account_basis"] = "mailbox_list"
        report["verdict"] = "listed_on_account"
    elif api["domain_on_account"] is False:
        report["same_account"] = False
        report["verdict"] = "different_account"
    elif exists and api["domain_on_account"] is True:
        report["same_account"] = True
        report["same_account_basis"] = "eligibility_already_exists"
        report["verdict"] = "exists_on_owned_domain"
    elif api["eligible"] is True and api["domain_on_account"] is True:
        report["same_account"] = False
        report["verdict"] = "eligible_on_account"
    elif api["checked"]:
        report["same_account"] = False if listed is False else None
        report["verdict"] = "not_listed"
    if not api["reason"] and report["verdict"] == "token_not_configured":
        api["reason"] = ""
    report["mail_product"] = _product(dns, api.get("mailbox_type") or "")
    report["imap_host"] = _imap_host(report["mail_product"], dns)
    report["password_login"] = _password_login(report)
    return report


def _product(dns: Dict[str, Any], mailbox_type: str) -> str:
    kind = str(mailbox_type or "").strip().upper()
    dns_product = str(dns.get("mail_product") or "unknown")
    if kind == "TITAN" and dns_product == "microsoft_365":
        return "conflict"
    if kind == "TITAN":
        return "godaddy_email"
    if dns_product == "microsoft_365":
        return "microsoft_365"
    if dns_product == "godaddy_email":
        return "godaddy_email"
    return "unknown"


def _imap_host(product: str, dns: Dict[str, Any]) -> str:
    if product == "godaddy_email":
        return "imap.secureserver.net"
    if product == "microsoft_365":
        return dns.get("imap_host") or "outlook.office365.com"
    return ""


def _password_login(report: Dict[str, Any]) -> bool:
    return report.get("mail_product") == "godaddy_email"


def probe_imap(
    host: str,
    port: int,
    username: str,
    password: str,
    factory: Optional[Callable] = None,
) -> str:
    """Log in once. Returns a connection code. The password is not part of the code."""
    import imaplib

    client_cls = factory or imaplib.IMAP4_SSL
    client = None
    try:
        try:
            client = client_cls(host, port, timeout=15)
        except TypeError:
            client = client_cls(host, port)
        client.login(username, password)
        return "connected"
    except Exception as exc:
        text = str(exc).replace(password, "") if password else str(exc)
        lowered = text.lower()
        if "basic" in lowered or "authenticate failed" in lowered or "auth" in lowered:
            return "auth_failed"
        return "probe_failed"
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def connect_saved_password(
    mailbox_id: str,
    address: str,
    report: Dict[str, Any],
    *,
    imap_factory: Optional[Callable] = None,
) -> str:
    """Use the vault password only when the mail host accepts a password login."""
    product = report.get("mail_product") or "unknown"
    if product == "microsoft_365":
        return "microsoft_365_basic_auth_disabled"
    if product != "godaddy_email":
        return "mail_host_unconfirmed"
    password = load_password(mailbox_id)
    if not password:
        return "mail_host_unconfirmed"
    try:
        return probe_imap(
            "imap.secureserver.net",
            993,
            address,
            password,
            factory=imap_factory,
        )
    finally:
        del password
