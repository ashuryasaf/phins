"""
Platform keyring (``security/keyring.py``): durable data keys without
hand-configured secrets.

Covers the production incident behind PR #600's follow-up: a deployment with no
``PHINS_ENCRYPTION_KEY`` refused to store a customer's ID on first login. The
keyring must mint one key per purpose, store it durably (``platform_keys``
table in DB mode, ``PHINS_KEYRING_PATH`` file otherwise), reuse it from every
process/replica, never replace it, and keep an operator-supplied key as the
primary while older blobs stay readable.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid

import pytest

from security import keyring
from security.vault import decrypt_json, encrypt_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _isolated_keyring(monkeypatch, tmp_path):
    monkeypatch.delenv("PHINS_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("PHINS_IDENTITY_HASH_KEY", raising=False)
    monkeypatch.setenv("USE_DATABASE", "false")
    monkeypatch.setenv("PHINS_KEYRING_PATH", str(tmp_path / "keyring.json"))
    keyring.reset_cache()
    yield
    keyring.reset_cache()


# ---------------------------------------------------------------------------
# file backend
# ---------------------------------------------------------------------------
def test_file_backend_mints_once_and_reuses(tmp_path):
    first = keyring.resolve(keyring.PURPOSE_VAULT)
    assert first["source"] == "generated" and keyring.is_valid_fernet_key(first["material"])
    path = tmp_path / "keyring.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"

    keyring.reset_cache()  # a fresh process
    again = keyring.resolve(keyring.PURPOSE_VAULT)
    assert again["material"] == first["material"] and again["fingerprint"] == first["fingerprint"]

    on_disk = json.loads(path.read_text())
    assert set(on_disk["keys"]) == {"vault"}
    # each purpose has its own key
    hash_key = keyring.resolve(keyring.PURPOSE_IDENTITY_HASH)
    assert hash_key["material"] != first["material"]
    assert set(json.loads(path.read_text())["keys"]) == {"vault", "identity-hash"}


def test_existing_key_is_never_replaced(tmp_path):
    path = tmp_path / "keyring.json"
    from cryptography.fernet import Fernet
    pinned = Fernet.generate_key().decode("ascii")
    path.write_text(json.dumps({"version": 1, "keys": {"vault": {"material": pinned, "fingerprint": "x"}}}))
    assert keyring.resolve(keyring.PURPOSE_VAULT)["material"] == pinned
    blob = encrypt_json({"v": 1})
    assert blob.scheme == "fernet"
    assert Fernet(pinned.encode()).decrypt(blob.ciphertext.encode()) == b'{"v":1}'


def test_env_key_is_primary_and_ring_key_still_decrypts(monkeypatch):
    from cryptography.fernet import Fernet

    ring_blob = encrypt_json({"written": "under-ring-key"})
    ring_fp = keyring.resolve(keyring.PURPOSE_VAULT)["fingerprint"]

    explicit = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("PHINS_ENCRYPTION_KEY", explicit)
    keyring.reset_cache()
    assert keyring.resolve(keyring.PURPOSE_VAULT) == {
        "material": explicit, "fingerprint": keyring.fingerprint(explicit), "source": "env"}
    assert keyring.vault_keys()[0] == explicit and len(keyring.vault_keys()) == 2
    # old data is still readable, new data is written under the env key
    assert decrypt_json(ring_blob.to_json()) == {"written": "under-ring-key"}
    new_blob = encrypt_json({"written": "under-env-key"})
    assert Fernet(explicit.encode()).decrypt(new_blob.ciphertext.encode())
    assert keyring.describe()["keys"]["vault"]["fingerprint"] != ring_fp


def test_invalid_env_key_is_ignored_not_used(monkeypatch):
    monkeypatch.setenv("PHINS_ENCRYPTION_KEY", "not-a-fernet-key")
    keyring.reset_cache()
    assert keyring.resolve(keyring.PURPOSE_VAULT)["source"] == "generated"
    assert encrypt_json({"a": 1}).scheme == "fernet"


def test_identity_hash_keeps_pre_keyring_values_under_legacy_encryption_key(monkeypatch, tmp_path):
    """Before the keyring, national_id_hash was HMAC'd with the raw bytes of
    PHINS_ENCRYPTION_KEY. A deployment upgraded with that variable set must
    produce byte-identical hashes, and must never copy the env key into the
    keyring store."""
    import hashlib
    import hmac

    from cryptography.fernet import Fernet
    from services import customer_identity_service as cis

    legacy = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("PHINS_ENCRYPTION_KEY", legacy)
    keyring.reset_cache()
    resolved = keyring.resolve(keyring.PURPOSE_IDENTITY_HASH)
    assert resolved["source"] == "legacy-encryption-key" and resolved["material"] == legacy
    pre_keyring_hash = hmac.new(legacy.encode("utf-8"), b"IL:123456782", hashlib.sha256).hexdigest()
    assert cis.hash_national_id("IL", "123456782") == pre_keyring_hash

    # nothing about the hash key was written to the ring (vault key may be)
    ring_file = tmp_path / "keyring.json"
    stored = json.loads(ring_file.read_text())["keys"] if ring_file.exists() else {}
    assert "identity-hash" not in stored
    assert legacy not in ring_file.read_text() if ring_file.exists() else True

    # an explicit hash key always wins
    monkeypatch.setenv("PHINS_IDENTITY_HASH_KEY", "operator-hash-key")
    assert keyring.identity_hash_key() == b"operator-hash-key"
    assert cis.hash_national_id("IL", "123456782") != pre_keyring_hash


def test_existing_ring_hash_key_outranks_a_later_encryption_key(monkeypatch):
    """A deployment that ran without any key minted a ring hash key and hashed
    customers under it; introducing PHINS_ENCRYPTION_KEY afterwards must not
    move the join key."""
    from cryptography.fernet import Fernet
    from services import customer_identity_service as cis

    minted = keyring.resolve(keyring.PURPOSE_IDENTITY_HASH)
    assert minted["source"] == "generated"
    h1 = cis.hash_national_id("IL", "123456782")

    monkeypatch.setenv("PHINS_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    keyring.reset_cache()
    assert keyring.resolve(keyring.PURPOSE_IDENTITY_HASH)["material"] == minted["material"]
    assert cis.hash_national_id("IL", "123456782") == h1


def test_unusable_keyring_fails_closed(tmp_path, monkeypatch):
    (tmp_path / "blocker").write_text("file")
    monkeypatch.setenv("PHINS_KEYRING_PATH", str(tmp_path / "blocker" / "k.json"))
    keyring.reset_cache()
    with pytest.raises(keyring.KeyringError):
        keyring.resolve(keyring.PURPOSE_VAULT)
    assert keyring.vault_keys() == []
    assert encrypt_json({"a": 1}).scheme == "plain"
    status = keyring.describe()
    assert status["keys"]["vault"]["available"] is False and "error" in status["keys"]["vault"]


def test_file_write_does_not_follow_a_planted_symlink(tmp_path, monkeypatch):
    """A pre-planted symlink at the old predictable temp name must be ignored:
    the write goes through mkstemp (O_EXCL, random name) and only the final
    rename touches the keyring path."""
    victim = tmp_path / "victim.txt"
    victim.write_text("do not overwrite")
    planted = tmp_path / f"keyring.json.{os.getpid()}.tmp"
    planted.symlink_to(victim)
    keyring.resolve(keyring.PURPOSE_VAULT)
    assert victim.read_text() == "do not overwrite"
    assert planted.is_symlink()  # untouched
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".phins_keyring.")]  # no temp litter
    assert oct((tmp_path / "keyring.json").stat().st_mode & 0o777) == "0o600"


def test_concurrent_mints_of_different_purposes_keep_both_keys(tmp_path):
    """Two processes minting different purposes at once must not overwrite each
    other: a key that only ever existed in the loser's memory cannot decrypt or
    rematch anything after a restart."""
    ring = tmp_path / "keyring.json"
    env = dict(os.environ, USE_DATABASE="false", PHINS_KEYRING_PATH=str(ring), PYTHONPATH=ROOT)
    env.pop("PHINS_ENCRYPTION_KEY", None)
    env.pop("PHINS_IDENTITY_HASH_KEY", None)
    code = ("import sys, time\n"
            "from security import keyring\n"
            "time.sleep(max(0.0, float(sys.argv[2]) - time.time()))\n"
            "print(keyring.resolve(sys.argv[1])['fingerprint'])\n")
    start = time.time() + 2.0
    procs = [subprocess.Popen([sys.executable, "-c", code, purpose, str(start)], env=env, cwd=ROOT,
                              stdout=subprocess.PIPE, text=True)
             for purpose in ("vault", "identity-hash")]
    minted = [proc.communicate()[0].strip() for proc in procs]
    assert all(proc.returncode == 0 for proc in procs)

    stored = json.loads(ring.read_text())["keys"]
    assert set(stored) == {"vault", "identity-hash"}
    assert [stored["vault"]["fingerprint"], stored["identity-hash"]["fingerprint"]] == minted


def test_malformed_keyring_file_is_rejected_not_overwritten(tmp_path):
    path = tmp_path / "keyring.json"
    path.write_text('{"version": 1, "keys": "oops"}')
    with pytest.raises(keyring.KeyringError):
        keyring.resolve(keyring.PURPOSE_VAULT)
    assert path.read_text() == '{"version": 1, "keys": "oops"}'


# ---------------------------------------------------------------------------
# database backend
# ---------------------------------------------------------------------------
def _fresh_sqlite(monkeypatch, tmp_path):
    db_path = tmp_path / f"keyring_{uuid.uuid4().hex[:6]}.db"
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    from database import init_database, reset_connection
    reset_connection()
    init_database()
    keyring.reset_cache()
    return db_path


def test_db_backend_persists_row_and_is_shared_across_processes(monkeypatch, tmp_path):
    db_path = _fresh_sqlite(monkeypatch, tmp_path)
    try:
        first = keyring.resolve(keyring.PURPOSE_VAULT)
        assert first["source"] == "generated"
        con = sqlite3.connect(str(db_path))
        rows = con.execute("SELECT id, purpose, material, fingerprint FROM platform_keys").fetchall()
        con.close()
        assert rows == [("KEY-VAULT", "vault", first["material"], first["fingerprint"])]

        env = dict(os.environ, USE_DATABASE="true", USE_SQLITE="true", SQLITE_PATH=str(db_path),
                   PHINS_TEST_MODE="false", PYTHONPATH=ROOT)
        env.pop("PHINS_ENCRYPTION_KEY", None)
        code = ("from security import keyring; "
                "print(keyring.resolve('vault')['fingerprint'], keyring.resolve('identity-hash')['fingerprint'])")
        outs = [subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT, capture_output=True,
                               text=True, check=True).stdout.strip() for _ in range(2)]
        assert outs[0] == outs[1]
        assert outs[0].split()[0] == first["fingerprint"]
        keyring.reset_cache()
        assert keyring.resolve(keyring.PURPOSE_IDENTITY_HASH)["fingerprint"] == outs[0].split()[1]
    finally:
        from database import reset_connection
        reset_connection()


def test_unset_use_database_selects_the_shared_database_backend(monkeypatch, tmp_path):
    """The portal defaults USE_DATABASE to on; reading an unset variable as file
    mode would mint per-replica keys beside data that lives in the database."""
    monkeypatch.delenv("USE_DATABASE", raising=False)
    monkeypatch.setenv("USE_SQLITE", "true")
    db_path = tmp_path / "default_mode.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    from database import init_database, reset_connection
    reset_connection()
    init_database()
    keyring.reset_cache()
    try:
        assert keyring.resolve(keyring.PURPOSE_VAULT)["source"] == "generated"
        assert not (tmp_path / "keyring.json").exists()
        con = sqlite3.connect(str(db_path))
        assert con.execute("SELECT purpose FROM platform_keys").fetchall() == [("vault",)]
        con.close()
        assert keyring.describe()["backend"] == "database"
    finally:
        reset_connection()


def test_db_backend_lost_insert_race_uses_winner_key(monkeypatch, tmp_path):
    _fresh_sqlite(monkeypatch, tmp_path)
    try:
        from cryptography.fernet import Fernet
        winner = Fernet.generate_key().decode("ascii")

        original = keyring._generate_material

        def racing_generate(purpose):
            # another replica commits its key between our read and our insert
            from sqlalchemy.orm import Session
            from database import get_engine
            from database.models import PlatformKey
            with Session(get_engine()) as s:
                s.add(PlatformKey(id="KEY-VAULT", purpose="vault", material=winner,
                                  fingerprint=keyring.fingerprint(winner), source="generated"))
                s.commit()
            return original(purpose)

        monkeypatch.setattr(keyring, "_generate_material", racing_generate)
        assert keyring.resolve(keyring.PURPOSE_VAULT)["material"] == winner
    finally:
        from database import reset_connection
        reset_connection()


def test_db_backend_never_falls_back_to_file(monkeypatch, tmp_path):
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "missing-dir" / "x.db"))
    from database import reset_connection
    reset_connection()
    keyring.reset_cache()
    try:
        with pytest.raises(keyring.KeyringError):
            keyring.resolve(keyring.PURPOSE_VAULT)
        assert not (tmp_path / "keyring.json").exists()
    finally:
        reset_connection()


def test_platform_key_to_dict_never_exposes_material():
    from database.models import PlatformKey
    row = PlatformKey(id="KEY-VAULT", purpose="vault", material="secret", fingerprint="abc", source="generated")
    assert "material" not in row.to_dict() and row.to_dict()["fingerprint"] == "abc"


# ---------------------------------------------------------------------------
# the incident end-to-end: DB mode, no env key, real (non-test) runtime
# ---------------------------------------------------------------------------
def test_first_login_identity_capture_in_db_mode_without_env_key(monkeypatch, tmp_path):
    db_path = _fresh_sqlite(monkeypatch, tmp_path)
    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.delenv("PHINS_IDENTITY_ALLOW_PLAINTEXT_VAULT", raising=False)
    from database.data_access import DatabaseDict
    from database.manager import DatabaseManager
    from services import customer_identity_service as cis
    cis.reset_process_state()
    cid = f"CUST-KR-{uuid.uuid4().hex[:8].upper()}"
    try:
        with DatabaseManager() as db:
            db.customers.create(id=cid, name="First Login", email=f"{cid.lower()}@example.com")
        customers = DatabaseDict("customers")
        result = cis.set_identity(customers, cid, "123456782", "IL", source="login_prompt", actor=cid)
        assert result["complete"]

        con = sqlite3.connect(str(db_path))
        row = con.execute("SELECT national_id_hash, national_id_encrypted, nationality FROM customers WHERE id=?",
                          (cid,)).fetchone()
        keys = {r[0] for r in con.execute("SELECT purpose FROM platform_keys")}
        con.close()
        assert row[2] == "IL" and row[0] == cis.hash_national_id("IL", "123456782")
        assert json.loads(row[1])["scheme"] == "fernet" and "123456782" not in row[1]
        assert keys == {"vault", "identity-hash"}

        # a second replica: no in-process state at all, reads everything from the DB
        cis.reset_process_state()
        keyring.reset_cache()
        assert cis.reveal_national_id(cid) == "123456782"
        assert cis.find_customer_id_by_identity("IL", cis.hash_national_id("IL", "123456782"), {}) == cid
        assert cis.vault_status()["backend"] == "database" and cis.vault_status()["ready"]
    finally:
        cis.reset_process_state()
        from database import reset_connection
        reset_connection()
