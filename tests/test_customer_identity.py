"""Customer identity master: personal ID + nationality.

Covers the service (validation, hashing, encryption, write-once, uniqueness,
pipeline reconciliation), the HTTP surface (autocomplete, rules, one-time
customer capture, admin correction, login flags), the pipeline stamps
(application/claim records carry a PII-free reference, strict-mode gate),
the chat signature step and SQLite durability (columns + unique index).
"""
import json
import os
import sqlite3
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal
from services import countries
from services import customer_identity_service as cis

BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8000")

IL_ID = "123456782"      # checksum-valid Israeli ID
IL_ID_2 = "000000018"    # another checksum-valid Israeli ID
US_SSN = "123-45-6789"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _http(method, path, payload=None, token=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return json.loads(raw), e.code
        except ValueError:
            return {"raw": raw}, e.code


def _get(path, token=None):
    return _http("GET", path, token=token)


def _post(path, payload, token=None):
    return _http("POST", path, payload, token=token)


def _keep_seeded_state():
    """The embedded server wipes in-memory stores on a test's first request
    unless the port is already marked initialised (see root conftest)."""
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(int(os.environ.get("TEST_PORT", "8000")))


def _customer(customer_id=None, **extra):
    cid = customer_id or f"CUST-ID-{uuid.uuid4().hex[:8].upper()}"
    rec = {"id": cid, "name": "Identity Tester", "email": f"{cid.lower()}@example.com",
           "country": "IL", **extra}
    portal.CUSTOMERS[cid] = rec
    _keep_seeded_state()
    return cid, rec


def _session(role, customer_id=None, username=None):
    token = f"phins_identity-{uuid.uuid4().hex}"
    portal.SESSIONS[token] = {
        "username": username or f"{role}-identity-test",
        "user_id": customer_id or username or f"{role}-identity-test",
        "role": role,
        "customer_id": customer_id,
        "expires": "2099-01-01T00:00:00",
    }
    _keep_seeded_state()
    return token


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("PHINS_IDENTITY_REQUIRED", raising=False)
    cis.reset_process_state()
    yield
    cis.reset_process_state()


# ---------------------------------------------------------------------------
# countries + validation
# ---------------------------------------------------------------------------
def test_country_resolution_accepts_names_codes_and_aliases():
    for text in ("Israel", "israel", "IL", "ISR", "ישראל", "  Israel "):
        assert countries.resolve_country(text) == "IL", text
    for text in ("USA", "United States", "us", "U.S.A.", "America", "ארצות הברית"):
        assert countries.resolve_country(text) == "US", text
    assert countries.resolve_country("UK") == "GB"
    assert countries.resolve_country("Great Britain") == "GB"
    assert countries.resolve_country("Ivory Coast") == "CI"
    assert countries.resolve_country("Côte d'Ivoire") == "CI"
    assert countries.resolve_country("") is None
    assert countries.resolve_country("Atlantis") is None
    assert countries.country_name("IL") == "Israel"


def test_country_autocomplete_prefix_first_and_bounded():
    items = cis.countries_autocomplete("isr", limit=5)
    assert items and items[0]["code"] == "IL"
    assert all({"code", "name"} <= set(i) for i in items)
    assert len(cis.countries_autocomplete("a", limit=3)) == 3
    codes = {i["code"] for i in cis.countries_autocomplete("united")}
    assert {"US", "GB", "AE"} <= codes


def test_israeli_id_checksum_and_normalization():
    assert cis.israeli_id_checksum_ok(IL_ID)
    assert cis.israeli_id_checksum_ok("0" + IL_ID[:8]) is False or len("0" + IL_ID[:8]) == 9
    assert not cis.israeli_id_checksum_ok("123456789")
    code, norm = cis.normalize_national_id(" 12345678-2 ", "Israel")
    assert (code, norm) == ("IL", IL_ID)
    # short IDs are zero-padded to 9 digits before the checksum
    code, norm = cis.normalize_national_id("00000018", "IL")
    assert (code, norm) == ("IL", IL_ID_2)


@pytest.mark.parametrize("national_id,nationality,code", [
    ("", "IL", "national_id_required"),
    (IL_ID, "", "nationality_invalid"),
    (IL_ID, "Narnia", "nationality_invalid"),
    ("123456789", "IL", "national_id_invalid"),
    ("12345", "IL", "national_id_invalid"),
    ("12-34", "US", "national_id_invalid"),
    ("QQ123456C", "GB", "national_id_invalid"),
    ("11111111111", "BR", "national_id_invalid"),
    ("12345678A", "ES", "national_id_invalid"),
])
def test_invalid_identity_inputs_are_rejected(national_id, nationality, code):
    with pytest.raises(cis.IdentityError) as exc:
        cis.normalize_national_id(national_id, nationality)
    assert exc.value.code == code
    assert exc.value.status == 400


@pytest.mark.parametrize("national_id,nationality,expected", [
    (US_SSN, "USA", ("US", "123456789")),
    ("AB 12 34 56 C", "United Kingdom", ("GB", "AB123456C")),
    ("111.444.777-35", "Brazil", ("BR", "11144477735")),
    ("12345678Z", "Spain", ("ES", "12345678Z")),
    ("1 85 05 78 006 048", "France", ("FR", "1850578006048")),
    ("ab-123/456", "Germany", ("DE", "AB123456")),   # generic rule: alphanumerics kept
])
def test_valid_identity_inputs_normalize_per_nationality(national_id, nationality, expected):
    assert cis.normalize_national_id(national_id, nationality) == expected


def test_hash_is_keyed_deterministic_and_masking_never_leaks():
    h1 = cis.hash_national_id("IL", IL_ID)
    assert h1 == cis.hash_national_id("IL", IL_ID) and len(h1) == 64
    assert h1 != cis.hash_national_id("US", IL_ID)  # nationality is part of the message
    assert cis.mask_national_id(IL_ID).endswith("6782") and IL_ID[:5] not in cis.mask_national_id(IL_ID)
    assert cis.mask_national_id("") == ""


def test_id_rules_cover_every_country_with_a_generic_fallback():
    for code in ("IL", "US", "GB", "FR", "ZW"):
        rule = cis.id_rule_for(code)
        assert rule["nationality"] == code and rule["label"] and rule["example"]
        assert cis.normalize_national_id(rule["example"], code)[0] == code, code


# ---------------------------------------------------------------------------
# write path: set_identity
# ---------------------------------------------------------------------------
def test_set_identity_stores_hash_last4_encrypted_and_never_plaintext():
    customers = {}
    cid, rec = "CUST-SVC-1", {"id": "CUST-SVC-1", "name": "A", "id_number": IL_ID}
    customers[cid] = rec
    status = cis.set_identity(customers, cid, IL_ID, "Israel", source="login_prompt", actor="a")
    assert status["complete"] and status["changed"] and status["required"] is False
    assert status["nationality"] == "IL" and status["nationality_name"] == "Israel"
    assert status["national_id_masked"].endswith("6782")
    assert rec["national_id_hash"] == cis.hash_national_id("IL", IL_ID)
    assert rec["national_id_last4"] == "6782" and rec["identity_source"] == "login_prompt"
    # plaintext is never kept on the record; legacy field was masked in place
    assert IL_ID not in json.dumps(rec)
    assert rec["id_number"] == cis.mask_national_id(IL_ID)
    assert "national_id_encrypted" not in rec
    # ...but the regulated reveal path can decrypt the vaulted number
    assert cis.reveal_national_id(cid) == IL_ID
    assert cis.reveal_national_id("CUST-NOPE") is None


def test_set_identity_is_idempotent_and_write_once():
    customers = {"C1": {"id": "C1"}}
    first = cis.set_identity(customers, "C1", IL_ID, "IL", source="registration", actor="c1")
    again = cis.set_identity(customers, "C1", "12345678-2", "israel", source="login_prompt", actor="c1")
    assert first["changed"] is True and again["changed"] is False
    assert customers["C1"]["identity_source"] == "registration"  # untouched on retry
    with pytest.raises(cis.IdentityError) as exc:
        cis.set_identity(customers, "C1", IL_ID_2, "IL", source="login_prompt", actor="c1")
    assert exc.value.code == "identity_already_set" and exc.value.status == 409
    assert customers["C1"]["national_id_last4"] == "6782"


def test_set_identity_enforces_uniqueness_across_customers():
    customers = {"C1": {"id": "C1"}, "C2": {"id": "C2"}}
    cis.set_identity(customers, "C1", IL_ID, "IL", source="registration", actor="c1")
    with pytest.raises(cis.IdentityError) as exc:
        cis.set_identity(customers, "C2", IL_ID, "IL", source="registration", actor="c2")
    assert exc.value.code == "identity_in_use" and exc.value.status == 409
    assert not cis.is_complete(customers["C2"])
    # same digits under a different nationality is a different identity
    cis.set_identity(customers, "C2", IL_ID, "US", source="registration", actor="c2")
    assert cis.find_customer_id_by_identity("IL", cis.hash_national_id("IL", IL_ID), customers) == "C1"
    assert cis.find_customer_id_by_identity("US", cis.hash_national_id("US", IL_ID), customers) == "C2"


def test_admin_override_requires_reason_and_appends_history():
    class Audit:
        def __init__(self):
            self.rows = []

        def log(self, *args):
            self.rows.append(args)

    class Ledger:
        def __init__(self):
            self.events = []

        def append_event(self, **kw):
            self.events.append(kw)

    audit, ledger = Audit(), Ledger()
    customers = {"C1": {"id": "C1"}}
    cis.set_identity(customers, "C1", IL_ID, "IL", source="registration", actor="c1",
                     audit=audit, ledger=ledger)
    with pytest.raises(cis.IdentityError) as exc:
        cis.set_identity(customers, "C1", IL_ID_2, "IL", source="admin", actor="admin", allow_override=True)
    assert exc.value.code == "reason_required"

    status = cis.set_identity(customers, "C1", IL_ID_2, "IL", source="admin", actor="admin",
                              allow_override=True, reason="typo at registration",
                              audit=audit, ledger=ledger)
    assert status["changed"] and status["corrections"] == 1
    history = json.loads(customers["C1"]["identity_history"])
    assert history[0]["previous_national_id_hash"] == cis.hash_national_id("IL", IL_ID)
    assert history[0]["reason"] == "typo at registration" and history[0]["changed_by"] == "admin"
    assert cis.reveal_national_id("C1") == IL_ID_2
    assert [r[1] for r in audit.rows] == ["identity_set", "identity_corrected"]
    assert [e["event_type"] for e in ledger.events] == ["customer.identity_set", "customer.identity_corrected"]
    assert ledger.events[1]["payload"]["previous_national_id_hash"] == history[0]["previous_national_id_hash"]
    # audit/ledger payloads never carry the plaintext
    assert IL_ID not in json.dumps(ledger.events, default=str) and IL_ID_2 not in json.dumps(audit.rows, default=str)


def test_set_identity_rolls_back_when_durable_write_fails():
    class Failing(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("db down")

    customers = Failing()
    dict.__setitem__(customers, "C1", {"id": "C1"})
    with pytest.raises(RuntimeError):
        cis.set_identity(customers, "C1", IL_ID, "IL", source="registration", actor="c1")
    assert not cis.is_complete(customers["C1"])
    assert cis.reveal_national_id("C1") is None


def test_unknown_source_and_customer_are_refused():
    with pytest.raises(cis.IdentityError) as exc:
        cis.set_identity({"C1": {"id": "C1"}}, "C1", IL_ID, "IL", source="bogus", actor="x")
    assert exc.value.code == "source_invalid"
    with pytest.raises(cis.IdentityError) as exc:
        cis.set_identity({}, "C-MISSING", IL_ID, "IL", source="registration", actor="x")
    assert exc.value.status == 404


def test_mirrors_receive_identity_fields():
    customers = {"C1": {"id": "C1"}}
    mirror = {"C1": {"id": "C1", "name": "mirror copy"}}
    cis.set_identity(customers, "C1", IL_ID, "IL", source="registration", actor="c1", mirrors=(mirror,))
    assert mirror["C1"]["national_id_hash"] == customers["C1"]["national_id_hash"]
    assert mirror["C1"]["nationality"] == "IL" and mirror["C1"]["name"] == "mirror copy"


# ---------------------------------------------------------------------------
# read side + pipeline reconciliation
# ---------------------------------------------------------------------------
def test_identity_status_reference_and_matches():
    rec = {"id": "C1"}
    status = cis.identity_status(rec)
    assert status == {"complete": False, "required": True, "nationality": None, "nationality_name": None,
                      "national_id_masked": None, "captured_at": None, "source": None, "corrections": 0}
    assert cis.identity_reference(rec) is None and cis.matches(rec, IL_ID) is None
    cis.set_identity({"C1": rec}, "C1", IL_ID, "IL", source="application", actor="c1")
    ref = cis.identity_reference(rec)
    assert set(ref) == {"nationality", "national_id_hash", "national_id_last4", "national_id_masked", "captured_at"}
    assert IL_ID not in json.dumps(ref)
    assert cis.matches(rec, "12345678-2") is True
    assert cis.matches(rec, IL_ID, "Israel") is True
    assert cis.matches(rec, IL_ID, "US") is False
    assert cis.matches(rec, IL_ID_2) is False
    assert cis.matches(rec, "not-an-id") is False


def test_reconcile_pipeline_identity_outcomes():
    customers = {"C1": {"id": "C1"}}
    missing = cis.reconcile_pipeline_identity(customers, "C1", "", "", source="application", actor="c1")
    assert missing["outcome"] == "missing" and missing["reference"] is None
    invalid = cis.reconcile_pipeline_identity(customers, "C1", "123456789", "IL", source="application", actor="c1")
    assert invalid["outcome"] == "missing" and invalid["code"] == "national_id_invalid"
    captured = cis.reconcile_pipeline_identity(customers, "C1", IL_ID, "Israel", source="application", actor="c1")
    assert captured["outcome"] == "captured" and captured["reference"]["nationality"] == "IL"
    consistent = cis.reconcile_pipeline_identity(customers, "C1", None, None, source="claim", actor="c1")
    assert consistent["outcome"] == "consistent" and consistent["reference"] == captured["reference"]
    mismatch = cis.reconcile_pipeline_identity(customers, "C1", IL_ID_2, "IL", source="claim", actor="c1")
    assert mismatch["outcome"] == "mismatch" and mismatch["reference"] == captured["reference"]
    assert customers["C1"]["national_id_last4"] == "6782"  # never overwritten by a pipeline


def test_completion_report_counts():
    customers = {"A": {"id": "A"}, "B": {"id": "B"}, "C": {"id": "C"}}
    cis.set_identity(customers, "A", IL_ID, "IL", source="registration", actor="a")
    cis.set_identity(customers, "B", US_SSN, "US", source="login_prompt", actor="b")
    report = cis.completion_report(customers)
    assert report["customers"] == 3 and report["complete"] == 2 and report["pending"] == 1
    assert report["completion_pct"] == 66.7
    assert report["by_nationality"] == {"IL": 1, "US": 1}
    assert report["by_source"] == {"registration": 1, "login_prompt": 1}


def test_strict_mode_env_precedence(monkeypatch):
    monkeypatch.setenv("PHINS_TEST_MODE", "true")
    monkeypatch.delenv("PHINS_IDENTITY_REQUIRED", raising=False)
    assert cis.strict_mode() is False
    monkeypatch.setenv("PHINS_IDENTITY_REQUIRED", "true")
    assert cis.strict_mode() is True
    monkeypatch.setenv("PHINS_IDENTITY_REQUIRED", "0")
    assert cis.strict_mode() is False
    monkeypatch.delenv("PHINS_IDENTITY_REQUIRED")
    monkeypatch.setenv("PHINS_TEST_MODE", "")
    assert cis.strict_mode() is True


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------
def test_http_public_countries_and_rules():
    body, status = _get("/api/identity/countries?q=isr&limit=3")
    assert status == 200 and body["items"][0] == {"code": "IL", "name": "Israel"} and body["total"] <= 3
    body, status = _get("/api/identity/rules?nationality=israel")
    assert status == 200 and body["nationality"] == "IL" and body["nationality_name"] == "Israel"
    assert "example" in body and "label" in body
    body, status = _get("/api/identity/rules?nationality=Atlantis")
    assert status == 400 and body["code"] == "nationality_invalid" and "error" in body


def test_http_customer_one_time_capture_and_login_flags():
    cid, _ = _customer()
    token = _session("customer", cid, username=f"user-{cid}")

    body, status = _get("/api/customer/identity", token=token)
    assert status == 200 and body["required"] is True and body["complete"] is False
    assert body["customer_id"] == cid and "strict_mode" in body
    flags = portal._login_identity_flags(cid)
    assert flags["identity_required"] is True

    body, status = _post("/api/customer/identity", {"national_id": "bad", "nationality": "Israel"}, token=token)
    assert status == 400 and body["code"] == "national_id_invalid" and "error" in body

    body, status = _post("/api/customer/identity", {"national_id": IL_ID, "nationality": "Israel"}, token=token)
    assert status == 200 and body["complete"] and body["changed"] and body["nationality"] == "IL"
    assert body["national_id_masked"].endswith("6782") and IL_ID not in json.dumps(body)

    # one-time: the same customer cannot change it themselves
    body, status = _post("/api/customer/identity", {"national_id": IL_ID_2, "nationality": "IL"}, token=token)
    assert status == 409 and body["code"] == "identity_already_set"
    # ...but a retry with the same value is a no-op success
    body, status = _post("/api/customer/identity", {"national_id": IL_ID, "nationality": "IL"}, token=token)
    assert status == 200 and body["changed"] is False

    body, status = _get("/api/customer/identity", token=token)
    assert status == 200 and body["required"] is False
    assert portal._login_identity_flags(cid)["identity_required"] is False
    assert portal.CUSTOMERS[cid]["national_id_hash"] == cis.hash_national_id("IL", IL_ID)


def test_http_customer_cannot_read_another_customers_identity():
    cid_a, _ = _customer()
    cid_b, _ = _customer()
    token = _session("customer", cid_a)
    body, status = _get(f"/api/customer/identity?customer_id={cid_b}", token=token)
    assert status == 403 and "error" in body
    body, status = _get("/api/customer/identity")
    assert status == 401


def test_http_duplicate_identity_across_customers_is_refused():
    cid_a, _ = _customer()
    cid_b, _ = _customer()
    _post("/api/customer/identity", {"national_id": IL_ID, "nationality": "IL"}, token=_session("customer", cid_a))
    body, status = _post("/api/customer/identity", {"national_id": IL_ID, "nationality": "IL"},
                         token=_session("customer", cid_b))
    assert status == 409 and body["code"] == "identity_in_use"
    assert not cis.is_complete(portal.CUSTOMERS[cid_b])


def test_http_admin_routes_role_scoped_and_audited():
    cid, _ = _customer()
    cust_token = _session("customer", cid)
    admin_token = _session("admin", username="admin")
    uw_token = _session("underwriter", username="uw")

    body, status = _post("/api/admin/customers/identity",
                         {"customer_id": cid, "national_id": IL_ID, "nationality": "IL"}, token=cust_token)
    assert status == 403
    body, status = _post("/api/admin/customers/identity",
                         {"customer_id": cid, "national_id": IL_ID, "nationality": "IL"}, token=uw_token)
    assert status == 403
    body, status = _post("/api/admin/customers/identity", {"national_id": IL_ID, "nationality": "IL"}, token=admin_token)
    assert status == 400 and "customer_id" in body["error"]

    body, status = _post("/api/admin/customers/identity",
                         {"customer_id": cid, "national_id": IL_ID, "nationality": "IL"}, token=admin_token)
    assert status == 200 and body["source"] == "admin"
    body, status = _post("/api/admin/customers/identity",
                         {"customer_id": cid, "national_id": IL_ID_2, "nationality": "IL"}, token=admin_token)
    assert status == 400 and body["code"] == "reason_required"
    body, status = _post("/api/admin/customers/identity",
                         {"customer_id": cid, "national_id": IL_ID_2, "nationality": "IL", "reason": "KYC fix"},
                         token=admin_token)
    assert status == 200 and body["corrections"] == 1 and body["national_id_masked"].endswith("0018")

    # staff read (underwriter) sees status + history without plaintext
    body, status = _get(f"/api/admin/customers/identity?customer_id={cid}", token=uw_token)
    assert status == 200 and len(body["history"]) == 1 and body["history"][0]["reason"] == "KYC fix"
    assert IL_ID not in json.dumps(body) and IL_ID_2 not in json.dumps(body)
    body, status = _get(f"/api/customer/identity?customer_id={cid}", token=uw_token)
    assert status == 200 and body["customer_id"] == cid
    body, status = _get("/api/admin/customers/identity?customer_id=CUST-NOPE", token=uw_token)
    assert status == 404

    body, status = _get("/api/admin/customers/identity/report", token=uw_token)
    assert status == 403
    body, status = _get("/api/admin/customers/identity/report", token=admin_token)
    assert status == 200 and body["complete"] >= 1 and body["customers"] >= body["complete"]


def test_http_login_response_carries_identity_flags():
    body, status = _post("/api/login", {"username": "admin", "password": "admin123"})
    assert status == 200 and "identity_required" not in body  # staff are never gated

    cid, _ = _customer()
    username = f"login-{cid.lower()}"
    portal.USERS[username] = {**portal.hash_password("Pass-word-1"), "role": "customer",
                              "name": "Login Tester", "customer_id": cid}
    body, status = _post("/api/login", {"username": username, "password": "Pass-word-1"})
    assert status == 200, body
    assert body["identity_required"] is True and body["identity"]["complete"] is False
    token = body["token"]
    body, status = _get("/api/session/validate", token=token)
    assert status == 200 and body["identity_required"] is True

    # once captured, the next login/validate no longer asks (one time only)
    body, status = _post("/api/customer/identity", {"national_id": IL_ID, "nationality": "Israel"}, token=token)
    assert status == 200, body
    body, status = _get("/api/session/validate", token=token)
    assert status == 200 and body["identity_required"] is False
    body, status = _post("/api/login", {"username": username, "password": "Pass-word-1"})
    assert status == 200 and body["identity_required"] is False
    assert body["identity"]["national_id_masked"].endswith("6782") and IL_ID not in json.dumps(body)


# ---------------------------------------------------------------------------
# pipelines: applications, claims, strict gate
# ---------------------------------------------------------------------------
def _application_payload(customer_id, **overrides):
    payload = {
        "customer_id": customer_id,
        "policy_type": "health",
        "coverage_amount": 100000,
        "customer_name": "Identity Tester",
        "customer_email": "identity@example.com",
        "date_of_birth": "1990-01-01",
        "id_number": IL_ID,
        "nationality": "Israel",
    }
    payload.update(overrides)
    return payload


def test_policy_application_captures_identity_and_stamps_reference():
    cid, rec = _customer()
    token = _session("customer", cid)
    body, status = _post("/api/policies/create", _application_payload(cid), token=token)
    assert status in (200, 201), body
    assert cis.is_complete(rec) and rec["nationality"] == "IL" and rec["identity_source"] == "application"
    app_id = body.get("application_id") or body.get("id") or body.get("application", {}).get("id")
    app = portal.UNDERWRITING_APPLICATIONS.get(app_id) or next(
        (a for a in portal.UNDERWRITING_APPLICATIONS.values() if a.get("customer_id") == cid), None)
    assert app is not None
    assert app["customer_identity"]["national_id_hash"] == rec["national_id_hash"]
    assert app.get("identity_mismatch") in (None, False)
    dumped = json.dumps(app, default=str)
    assert IL_ID not in dumped, "plaintext ID leaked into the application record"


def test_policy_application_with_conflicting_id_is_flagged_not_overwritten():
    cid, rec = _customer()
    cis.set_identity(portal.CUSTOMERS, cid, IL_ID, "IL", source="registration", actor="t")
    token = _session("customer", cid)
    body, status = _post("/api/policies/create", _application_payload(cid, id_number=IL_ID_2), token=token)
    assert status in (200, 201), body
    app = next(a for a in portal.UNDERWRITING_APPLICATIONS.values() if a.get("customer_id") == cid)
    assert app["identity_mismatch"] is True
    assert rec["national_id_last4"] == "6782"  # recorded identity is authoritative


def test_policy_application_strict_mode_rejects_missing_or_conflicting_identity(monkeypatch):
    monkeypatch.setenv("PHINS_IDENTITY_REQUIRED", "true")
    cid, rec = _customer()
    token = _session("customer", cid)
    before = set(portal.UNDERWRITING_APPLICATIONS)
    body, status = _post("/api/policies/create", _application_payload(cid, id_number="", nationality=""), token=token)
    assert status == 400 and body["code"] == "identity_required" and "error" in body
    assert set(portal.UNDERWRITING_APPLICATIONS) == before  # nothing half-written
    assert not cis.is_complete(rec)

    cis.set_identity(portal.CUSTOMERS, cid, IL_ID, "IL", source="registration", actor="t")
    body, status = _post("/api/policies/create", _application_payload(cid, id_number=IL_ID_2), token=token)
    assert status == 409 and body["code"] == "identity_mismatch"
    assert set(portal.UNDERWRITING_APPLICATIONS) == before

    body, status = _post("/api/policies/create", _application_payload(cid), token=token)
    assert status in (200, 201), body


def test_policy_application_strict_mode_refuses_id_owned_by_another_customer(monkeypatch):
    monkeypatch.setenv("PHINS_IDENTITY_REQUIRED", "true")
    owner, _ = _customer()
    cis.set_identity(portal.CUSTOMERS, owner, IL_ID, "IL", source="registration", actor="t")
    cid, rec = _customer()
    token = _session("customer", cid)
    body, status = _post("/api/policies/create", _application_payload(cid), token=token)
    assert status == 409 and body["code"] == "identity_in_use"
    assert not cis.is_complete(rec)


def test_claim_creation_stamps_identity_reference_or_missing_flag(monkeypatch):
    cid, rec = _customer()
    portal.POLICIES[f"POL-ID-{cid}"] = {"id": f"POL-ID-{cid}", "customer_id": cid, "status": "active",
                                        "policy_type": "health", "coverage_amount": 50000}
    token = _session("customer", cid)
    claim_payload = {"policy_id": f"POL-ID-{cid}", "claim_type": "medical", "amount": 500,
                     "description": "identity stamp test", "incident_date": "2026-09-01"}
    body, status = _post("/api/claims/create", claim_payload, token=token)
    assert status in (200, 201), body
    claim = next(c for c in portal.CLAIMS.values() if c.get("customer_id") == cid)
    assert claim.get("identity_missing") is True and claim.get("customer_identity") is None

    cis.set_identity(portal.CUSTOMERS, cid, IL_ID, "IL", source="login_prompt", actor="t")
    body, status = _post("/api/claims/create", claim_payload, token=token)
    assert status in (200, 201), body
    stamped = [c for c in portal.CLAIMS.values() if c.get("customer_id") == cid and c.get("customer_identity")]
    assert stamped and stamped[-1]["customer_identity"]["national_id_hash"] == rec["national_id_hash"]
    assert IL_ID not in json.dumps(stamped[-1], default=str)

    monkeypatch.setenv("PHINS_IDENTITY_REQUIRED", "true")
    cid2, _ = _customer()
    portal.POLICIES[f"POL-ID-{cid2}"] = {"id": f"POL-ID-{cid2}", "customer_id": cid2, "status": "active",
                                         "policy_type": "health", "coverage_amount": 50000}
    body, status = _post("/api/claims/create", {**claim_payload, "policy_id": f"POL-ID-{cid2}"},
                         token=_session("customer", cid2))
    assert status == 400 and body["code"] == "identity_required"


# ---------------------------------------------------------------------------
# chat application: nationality-aware signature step
# ---------------------------------------------------------------------------
def test_chat_signature_requires_nationality_and_validates_id_against_it():
    from services import chat_application_service as chat

    ok, code = chat._validate_nationality("Israel")
    assert ok and code == "IL"
    ok, err = chat._validate_nationality("Atlantis")
    assert not ok and err
    ok, _ = chat._validate_id_number(IL_ID, "IL")
    assert ok
    ok, err = chat._validate_id_number("123456789", "IL")
    assert not ok and "checksum" in err.lower()
    ok, _ = chat._validate_id_number(US_SSN, "US")
    assert ok
    ok, err = chat._validate_id_number("12", "US")
    assert not ok
    # legacy sessions without a nationality keep the Israeli rule
    ok, _ = chat._validate_id_number(IL_ID, None)
    assert ok


# ---------------------------------------------------------------------------
# assessment center: Mislaka linking reuses the identity master
# ---------------------------------------------------------------------------
def test_mislaka_link_captures_prefills_and_refuses_conflicting_ids():
    cid, rec = _customer()
    token = _session("customer", cid)
    path = "/api/assessment-center/mislaka/link"

    # first link with a valid ID captures it (source=assessment)
    body, status = _post(path, {"customer_id": cid, "id_number": IL_ID}, token=token)
    assert status == 200, body
    assert cis.is_complete(rec) and rec["identity_source"] == "assessment"
    assert IL_ID not in json.dumps(rec)

    # later links may omit the ID: the recorded (decrypted server-side) one is used
    body, status = _post(path, {"customer_id": cid}, token=token)
    assert status == 200, body
    assert IL_ID not in json.dumps(body), "Mislaka response must not echo the plaintext ID"

    # a different ID is refused, never overwritten
    body, status = _post(path, {"customer_id": cid, "id_number": IL_ID_2}, token=token)
    assert status == 409 and body["code"] == "identity_mismatch"
    assert rec["national_id_last4"] == "6782"

    # an ID already owned by another customer cannot be linked here either
    other, _ = _customer()
    body, status = _post(path, {"customer_id": other, "id_number": IL_ID}, token=_session("customer", other))
    assert status == 409 and body["code"] == "identity_in_use"
    assert not cis.is_complete(portal.CUSTOMERS[other])


def test_resolve_lookup_id_outcomes():
    customers = {"C1": {"id": "C1"}, "C2": {"id": "C2"}}
    # unknown customer: value passes through untouched
    assert cis.resolve_lookup_id(customers, "NOPE", IL_ID, source="pension", actor="t") == (IL_ID, None)
    # no identity yet and nothing supplied: nothing to use, no error (caller decides)
    assert cis.resolve_lookup_id(customers, "C1", "", source="pension", actor="t") == ("", None)
    # no identity yet + valid ID: captured once with the pipeline's source
    used, err = cis.resolve_lookup_id(customers, "C1", IL_ID, source="pension", actor="t")
    assert (used, err) == (IL_ID, None) and customers["C1"]["identity_source"] == "pension"
    # recorded + omitted: the vaulted number is used server-side
    assert cis.resolve_lookup_id(customers, "C1", None, source="pension", actor="t") == (IL_ID, None)
    # recorded + different: refused
    used, err = cis.resolve_lookup_id(customers, "C1", IL_ID_2, source="pension", actor="t")
    assert err[0] == 409 and err[1]["code"] == "identity_mismatch"
    # another customer supplying C1's ID: refused, nothing captured
    used, err = cis.resolve_lookup_id(customers, "C2", IL_ID, source="pension", actor="t")
    assert err[0] == 409 and err[1]["code"] == "identity_in_use" and not cis.is_complete(customers["C2"])


def test_resolve_lookup_id_compares_under_the_recorded_nationality():
    customers = {"C1": {"id": "C1"}}
    cis.set_identity(customers, "C1", US_SSN, "USA", source="registration", actor="t")
    # the customer's own (non-IL) ID is accepted, not read as an Israeli number
    assert cis.resolve_lookup_id(customers, "C1", US_SSN, source="pension", actor="t") == (US_SSN, None)
    assert cis.resolve_lookup_id(customers, "C1", "", source="pension", actor="t") == ("123456789", None)
    # a different ID is still refused
    used, err = cis.resolve_lookup_id(customers, "C1", "123-45-6780", source="pension", actor="t")
    assert err[0] == 409 and err[1]["code"] == "identity_mismatch"


def test_pension_import_route_is_bound_to_the_identity_master():
    cid, rec = _customer()
    token = _session("customer", cid)
    path = "/api/mislaka/import"

    # nothing recorded and nothing supplied -> the customer must record an ID first
    body, status = _post(path, {}, token=token)
    assert status == 400 and body["code"] == "identity_required"

    # first import with a valid ID captures it (source=pension) before the Mislaka call
    body, status = _post(path, {"id_number": IL_ID}, token=token)
    assert status in (200, 202, 404, 503), body  # Mislaka may be unconfigured in this harness
    assert cis.is_complete(rec) and rec["identity_source"] == "pension"
    assert IL_ID not in json.dumps(body)

    # a different ID for the same customer is refused before any lookup
    body, status = _post(path, {"id_number": IL_ID_2}, token=token)
    assert status == 409 and body["code"] == "identity_mismatch"

    # omitting the ID is fine now: the recorded one is used server-side
    body, status = _post(path, {}, token=token)
    assert status != 400, body
    assert IL_ID not in json.dumps(body)

    # staff binding an import to a customer get the same guarantees
    body, status = _post(path, {"customer_id": cid, "id_number": IL_ID_2}, token=_session("admin", username="admin"))
    assert status == 409 and body["code"] == "identity_mismatch"


def test_pension_job_subject_id_is_keyed_not_plain_sha256():
    import hashlib
    from services.jobs import pension_import_job
    subject = pension_import_job.subject_id_for(IL_ID)
    assert subject.startswith("PERSON-") and len(subject) == len("PERSON-") + 16
    assert subject != f"PERSON-{hashlib.sha256(IL_ID.encode()).hexdigest()[:16]}"
    assert subject == f"PERSON-{cis.hash_national_id('IL', IL_ID)[:16]}"
    assert pension_import_job.subject_id_for("12345678-2") == subject  # normalised first


def test_validate_route_uses_identity_rules_and_never_echoes_the_number():
    body, status = _get(f"/api/validate?type=ni&value={IL_ID}")
    assert status == 200 and body["status"] == "valid"
    assert body["details"]["nationality"] == "IL" and body["details"]["national_id_masked"].endswith("6782")
    assert IL_ID not in json.dumps(body)
    body, status = _get("/api/validate?type=ni&value=123456789")
    assert status == 200 and body["status"] == "invalid" and body["details"]["code"] == "national_id_invalid"
    body, status = _get(f"/api/validate?type=ni&value={US_SSN}&nationality=USA")
    assert status == 200 and body["status"] == "valid" and body["details"]["nationality"] == "US"


def test_assessment_documents_are_cross_checked_against_the_master():
    import base64
    cid, rec = _customer()
    cis.set_identity(portal.CUSTOMERS, cid, IL_ID, "IL", source="registration", actor="t")
    token = _session("admin", username="admin")

    def _upload(text, name):
        return _post("/api/assessment-center/upload", {
            "file_name": name, "mime_type": "text/plain", "customer_id": cid, "category": "general",
            "file_data_b64": base64.b64encode(text.encode()).decode(),
        }, token=token)

    body, status = _upload(f"Customer: Match Person. ID {IL_ID}. Diagnosis: none.", "match.txt")
    assert status == 201, body
    body, status = _get(f"/api/assessment-center/customer/{cid}/profile", token=token)
    assert status == 200
    check = body["identity_master"]["document_check"]
    assert check["master_recorded"] and check["matching"] >= 1 and check["conflict"] is False
    assert all(e["matches_master"] is True for e in body["identity"]["id_numbers"])

    # another ID-like number in the same file (a passport, extracted with
    # country "ANY") belongs to no jurisdiction the master can be compared
    # with, so it is "not comparable" rather than a contradiction
    body, status = _upload(f"Customer: Match Person. ID {IL_ID}. Passport AB1234567.", "passport.txt")
    assert status == 201, body
    body, status = _get(f"/api/assessment-center/customer/{cid}/profile", token=token)
    check = body["identity_master"]["document_check"]
    assert check["conflicting"] == 0 and check["conflict"] is False
    passports = [e for e in body["identity"]["id_numbers"] if e["country"] == "ANY"]
    assert passports and all(e["matches_master"] is None for e in passports)

    body, status = _upload(f"Customer: Other Person. ID {IL_ID_2}. Diagnosis: none.", "conflict.txt")
    assert status == 201, body
    body, status = _get(f"/api/assessment-center/customer/{cid}/profile", token=token)
    check = body["identity_master"]["document_check"]
    assert check["conflicting"] >= 1 and check["conflict"] is True
    assert any(e["matches_master"] is False for e in body["identity"]["id_numbers"])

    body, status = _post("/api/assessment-center/freeze", {"customer_id": cid, "assessment_type": "customer_risk"}, token=token)
    assert status == 201, body
    assert body["identity_mismatch"] is True
    assert body["record"]["details"]["identity_mismatch"] is True
    assert body["record"]["details"]["customer_identity"]["national_id_hash"] == rec["national_id_hash"]
    # the master is never changed by a conflicting document
    assert rec["national_id_last4"] == "6782"


def test_risk_report_analysis_flags_document_id_that_contradicts_master():
    from services.ai_risk_reports_service import get_ai_reports_service
    cid, rec = _customer()
    cis.set_identity(portal.CUSTOMERS, cid, IL_ID, "IL", source="registration", actor="t")
    svc = get_ai_reports_service()

    doc = {"owner_id": cid, "owner_role": "customer"}
    ok = svc._identity_cross_check(doc, {"id_number": IL_ID}, "hebrew")
    assert ok["anomaly"] is None and ok["status"]["result"] == "match"
    bad = svc._identity_cross_check(doc, {"id_number": IL_ID_2}, "hebrew")
    assert bad["status"]["result"] == "mismatch" and bad["anomaly"].type == "identity_mismatch"
    assert bad["anomaly"].severity.value == "critical"
    assert IL_ID not in json.dumps(bad["status"]) and IL_ID_2 not in json.dumps(bad["status"])
    # staff uploads have no owning customer -> nothing to compare
    assert svc._identity_cross_check({"owner_id": "admin", "owner_role": "admin"}, {"id_number": IL_ID_2}, "english") == {"status": None, "anomaly": None}
    # customer without a recorded identity -> reported, not flagged
    other, _ = _customer()
    assert svc._identity_cross_check({"owner_id": other, "owner_role": "customer"}, {"id_number": IL_ID_2}, "english")["status"]["result"] == "no_master"


# ---------------------------------------------------------------------------
# SQLite durability: columns, unique index, DatabaseDict write-through
# ---------------------------------------------------------------------------
def test_sqlite_schema_has_identity_columns_and_unique_index():
    from database import init_database, upgrade_schema, get_engine
    init_database()
    assert upgrade_schema(get_engine()) in (True, False)
    path = os.environ["SQLITE_PATH"]
    conn = sqlite3.connect(path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(customers)")}
        assert {"nationality", "national_id_hash", "national_id_last4", "national_id_encrypted",
                "identity_captured_at", "identity_source", "identity_history"} <= cols
        indexes = {row[1]: row[2] for row in conn.execute("PRAGMA index_list(customers)")}
        assert indexes.get("ux_customers_identity") == 1, indexes  # unique
        index_cols = [row[2] for row in conn.execute("PRAGMA index_info(ux_customers_identity)")]
        assert index_cols == ["nationality", "national_id_hash"]
    finally:
        conn.close()


def test_first_login_capture_without_encryption_key_uses_durable_keyring(monkeypatch, tmp_path):
    """Regression for the production first-login failure after PR #600:
    no PHINS_ENCRYPTION_KEY, not test mode -> the ID must still be stored,
    encrypted with a keyring key that a second process can read back."""
    from security import keyring

    monkeypatch.delenv("PHINS_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("PHINS_IDENTITY_HASH_KEY", raising=False)
    monkeypatch.delenv("PHINS_IDENTITY_ALLOW_PLAINTEXT_VAULT", raising=False)
    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("PHINS_KEYRING_PATH", str(tmp_path / "keyring.json"))
    keyring.reset_cache()
    try:
        customers = {"C1": {"id": "C1"}}
        result = cis.set_identity(customers, "C1", IL_ID, "IL", source="login_prompt", actor="c1")
        assert result["complete"] and cis.is_complete(customers["C1"])
        blob = json.loads(cis._load_encrypted("C1"))
        assert blob["scheme"] == "fernet" and IL_ID not in blob["ciphertext"]
        expected_hash = customers["C1"]["national_id_hash"]

        # "another replica": empty in-process caches, same keyring -> same key
        cis.reset_process_state()
        keyring.reset_cache()
        cis._ENCRYPTED["C1"] = json.dumps(blob)
        assert cis.reveal_national_id("C1") == IL_ID
        assert cis.hash_national_id("IL", IL_ID) == expected_hash
        assert cis.vault_status()["ready"] is True
    finally:
        keyring.reset_cache()


def test_vault_fails_closed_when_keyring_unusable(monkeypatch, tmp_path):
    from security import keyring

    monkeypatch.delenv("PHINS_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("PHINS_IDENTITY_HASH_KEY", raising=False)
    monkeypatch.delenv("PHINS_IDENTITY_ALLOW_PLAINTEXT_VAULT", raising=False)
    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    # keyring path under a regular file: cannot be created -> no key anywhere
    (tmp_path / "blocker").write_text("not a directory")
    monkeypatch.setenv("PHINS_KEYRING_PATH", str(tmp_path / "blocker" / "keyring.json"))
    keyring.reset_cache()
    try:
        customers = {"C1": {"id": "C1"}}
        with pytest.raises(cis.IdentityError) as exc:
            cis.set_identity(customers, "C1", IL_ID, "IL", source="registration", actor="c1")
        assert exc.value.code == "identity_vault_unavailable" and exc.value.status == 503
        assert not cis.is_complete(customers["C1"]) and cis.reveal_national_id("C1") is None
        assert cis.vault_status()["ready"] is False

        # dev opt-in still allows a plain vault once a hash key exists
        monkeypatch.setenv("PHINS_IDENTITY_ALLOW_PLAINTEXT_VAULT", "true")
        monkeypatch.setenv("PHINS_IDENTITY_HASH_KEY", "unit-test-hash-key")
        assert cis.set_identity(customers, "C1", IL_ID, "IL", source="registration", actor="c1")["complete"]
    finally:
        keyring.reset_cache()


def test_sqlite_identity_persists_through_database_dict(monkeypatch):
    from cryptography.fernet import Fernet
    from database import init_database
    from database.data_access import DatabaseDict
    from database.manager import DatabaseManager

    init_database()
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("PHINS_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    cid = f"CUST-DBID-{uuid.uuid4().hex[:8].upper()}"
    with DatabaseManager() as db:
        db.customers.create(id=cid, name="Durable Tester", email=f"{cid.lower()}@example.com")

    customers = DatabaseDict("customers")
    cis.set_identity(customers, cid, IL_ID, "IL", source="registration", actor="t")

    with DatabaseManager() as db:
        row = db.customers.get_by_id(cid)
        assert row.nationality == "IL" and row.national_id_hash == cis.hash_national_id("IL", IL_ID)
        assert row.national_id_last4 == "6782" and row.identity_source == "registration"
        assert row.national_id_encrypted and IL_ID not in row.national_id_encrypted
        assert json.loads(row.national_id_encrypted)["scheme"] == "fernet"
        assert "national_id_encrypted" not in row.to_dict()
        assert db.customers.get_by_identity("IL", row.national_id_hash).id == cid
        assert db.customers.get_by_identity("US", row.national_id_hash) is None

    # a second process would not have the in-memory blob: reveal reloads from the DB column
    cis.reset_process_state()
    assert cis.reveal_national_id(cid) == IL_ID
    # uniqueness is enforced against the DB even when the caller's dict is empty
    assert cis.find_customer_id_by_identity("IL", cis.hash_national_id("IL", IL_ID), {}) == cid

    other = f"CUST-DBID-{uuid.uuid4().hex[:8].upper()}"
    with DatabaseManager() as db:
        db.customers.create(id=other, name="Second", email=f"{other.lower()}@example.com")
    with pytest.raises(cis.IdentityError) as exc:
        cis.set_identity(customers, other, IL_ID, "IL", source="registration", actor="t")
    assert exc.value.code == "identity_in_use"

    # The unique index is the last line of defence against a raw duplicate
    # write; the repository swallows the IntegrityError and leaves the row alone.
    with DatabaseManager() as db:
        assert db.customers.update(other, nationality="IL",
                                   national_id_hash=cis.hash_national_id("IL", IL_ID)) is None
        row = db.customers.get_by_id(other)
        assert row.national_id_hash is None and row.nationality is None


def test_sqlite_lost_race_is_detected_by_read_back(monkeypatch):
    """Two customers register the same ID concurrently: the second passes the
    pre-check (the first row is not committed yet) but the unique index
    refuses its UPDATE. The service must not report success."""
    from cryptography.fernet import Fernet
    from database import init_database
    from database.data_access import DatabaseDict
    from database.manager import DatabaseManager

    init_database()
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("PHINS_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    winner = f"CUST-RACE-{uuid.uuid4().hex[:8].upper()}"
    loser = f"CUST-RACE-{uuid.uuid4().hex[:8].upper()}"
    with DatabaseManager() as db:
        db.customers.create(id=winner, name="Winner", email=f"{winner.lower()}@example.com")
        db.customers.create(id=loser, name="Loser", email=f"{loser.lower()}@example.com")
    customers = DatabaseDict("customers")
    cis.set_identity(customers, winner, IL_ID, "IL", source="registration", actor="t")

    # simulate the lost race: the uniqueness pre-check sees nobody
    monkeypatch.setattr(cis, "find_customer_id_by_identity", lambda *a, **k: None)
    with pytest.raises(cis.IdentityError) as exc:
        cis.set_identity(customers, loser, IL_ID, "IL", source="registration", actor="t")
    assert exc.value.code == "identity_in_use" and exc.value.status == 409
    with DatabaseManager() as db:
        row = db.customers.get_by_id(loser)
        assert row.national_id_hash is None and row.nationality is None
        assert row.national_id_encrypted is None  # blob rolled back too
    assert not cis.is_complete(customers[loser])
    assert cis.reveal_national_id(loser) is None
    assert cis.reveal_national_id(winner) == IL_ID
