"""A4 durable agent state: HydratedStore, codec, and the two new repositories.

Covers the design's test plan: TTL coalescing, forced refresh on write,
incremental hydration with periodic full resync, loader failure keeping the
cache, lossless dataclass round-trip, two store instances over one SQLite
file seeing each other's writes, checksum-verified artifact loads, DB-side
prune, and the video ``mark_terminal`` race (exactly one racer wins).
"""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import pytest

from services import hydrated_store as hs
from services.hydrated_store import HydratedStore, RefreshCoalescer, from_jsonable, to_jsonable


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class _FakeTable:
    """In-memory stand-in for a durable table with an updated_at clock."""

    def __init__(self):
        self.rows: Dict[str, Any] = {}
        self.updated: Dict[str, datetime] = {}
        self.load_calls: List[Optional[datetime]] = []
        self.clock = datetime(2026, 1, 1, 12, 0, 0)
        self.fail_loads = False

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def loader(self, since):
        self.load_calls.append(since)
        if self.fail_loads:
            raise RuntimeError("db down")
        for key, value in self.rows.items():
            ts = self.updated[key]
            if since is None or ts >= since:
                yield key, value, ts

    def saver(self, key, value):
        self.rows[key] = value
        self.updated[key] = self.tick()

    def deleter(self, key):
        self.rows.pop(key, None)
        self.updated.pop(key, None)


def _store(table: _FakeTable, *, enabled=True, ttl=1000.0, full_resync=1000.0, **kw):
    return HydratedStore(
        "t", loader=table.loader, saver=table.saver, deleter=table.deleter,
        ttl=ttl, full_resync_interval=full_resync, enabled=lambda: enabled, **kw)


# --------------------------------------------------------------------------
# RefreshCoalescer
# --------------------------------------------------------------------------
def test_coalescer_gates_by_ttl_and_force():
    c = RefreshCoalescer(ttl=1000.0)
    assert c.due() is True            # never refreshed
    c.mark()
    assert c.due() is False
    assert c.due(force=True) is True
    c.reset()
    assert c.due() is True


def test_ttl_env_parsing_defaults_on_garbage(monkeypatch):
    monkeypatch.setenv(hs.HYDRATE_TTL_ENV, "not-a-number")
    assert hs._env_float(hs.HYDRATE_TTL_ENV, 1.5) == 1.5
    monkeypatch.setenv(hs.HYDRATE_TTL_ENV, "-3")
    assert hs._env_float(hs.HYDRATE_TTL_ENV, 1.5) == 1.5
    monkeypatch.setenv(hs.HYDRATE_TTL_ENV, "0.25")
    assert hs._env_float(hs.HYDRATE_TTL_ENV, 1.5) == 0.25


# --------------------------------------------------------------------------
# HydratedStore: memory mode
# --------------------------------------------------------------------------
def test_memory_mode_is_a_plain_dict_and_never_touches_the_table():
    table = _FakeTable()
    store = _store(table, enabled=False)
    store["a"] = 1
    store.put("b", 2)
    assert store["a"] == 1 and store.get("b") == 2 and store.get("zz", 7) == 7
    assert len(store) == 2 and set(store) == {"a", "b"} and "a" in store
    assert dict(store.items()) == {"a": 1, "b": 2}
    assert store.pop("a") == 1 and store.pop("nope", None) is None
    with pytest.raises(KeyError):
        store.pop("nope")
    del store["b"]
    assert len(store) == 0
    assert table.load_calls == [] and table.rows == {}
    assert store.durable is False and store.snapshot()["cached"] == 0


# --------------------------------------------------------------------------
# HydratedStore: durable mode semantics
# --------------------------------------------------------------------------
def test_reads_coalesce_to_one_load_per_ttl():
    table = _FakeTable()
    table.saver("k1", {"v": 1})
    store = _store(table)
    for _ in range(5):
        assert store.get("k1") == {"v": 1}
        _ = len(store); _ = list(store.values())
    assert len(table.load_calls) == 1          # first read hydrates, rest coalesced
    store.coalescer.reset()
    assert "k1" in store
    assert len(table.load_calls) == 2


def test_write_goes_to_table_first_then_forces_refresh():
    table = _FakeTable()
    table.saver("seed", 0)
    store = _store(table)
    _ = store.get("x")                          # initial full hydrate
    assert len(table.load_calls) == 1
    store["k"] = {"v": 42}
    assert table.rows["k"] == {"v": 42}         # durable write happened
    assert len(table.load_calls) == 2           # forced refresh after write
    assert table.load_calls[1] is not None      # ... and it was incremental
    assert store["k"] == {"v": 42}
    assert store.stats["writes"] == 1


def test_incremental_hydration_then_periodic_full_resync_sees_peer_deletes():
    table = _FakeTable()
    table.saver("old", 1)
    store = _store(table, full_resync=1000.0)
    assert store.get("old") == 1
    assert table.load_calls == [None]
    # Peer writes a new row; our incremental pull picks it up.
    table.saver("new", 2)
    store.coalescer.reset()
    assert store.get("new") == 2
    assert table.load_calls[-1] is not None and store.stats["full_hydrations"] == 1
    # Peer deletes a row: invisible to incremental pulls ...
    table.deleter("old")
    store.coalescer.reset()
    assert store.get("old") == 1
    # ... but the next full resync removes it.
    store._last_full = -1e9
    store.coalescer.reset()
    assert store.get("old") is None and store.get("new") == 2
    assert store.stats["full_hydrations"] == 2


def test_loader_failure_keeps_serving_current_cache():
    table = _FakeTable()
    table.saver("k", "v")
    errors = []
    store = _store(table, on_error=lambda what, exc: errors.append(what))
    assert store["k"] == "v"
    table.fail_loads = True
    table.rows["k"] = "changed"
    store.coalescer.reset()
    assert store.get("k") == "v"                # stale but intact, not emptied
    assert errors == ["hydrate"] and store.stats["errors"] == 1
    table.fail_loads = False
    store.coalescer.reset()
    assert store.get("k") == "changed"


def test_saver_failure_is_reported_and_value_still_cached():
    table = _FakeTable()
    errors = []

    def bad_saver(key, value):
        raise RuntimeError("disk full")

    store = HydratedStore("t", loader=table.loader, saver=bad_saver, ttl=1000.0,
                          enabled=lambda: True, on_error=lambda w, e: errors.append(w))
    store["k"] = 1
    assert store.get("k") == 1                  # survives the first (full) hydrate
    store._last_full = -1e9
    store.coalescer.reset()
    assert store.get("k") == 1                  # ... and later full resyncs
    assert errors == ["save k"] and store.snapshot()["unsaved"] == 1


def test_delete_and_reset_and_put_persist_false():
    table = _FakeTable()
    store = _store(table)
    store["a"] = 1
    store.pop("a")
    assert "a" not in table.rows and store.stats["deletes"] == 1
    store.set_local("ghost", 9)
    assert "ghost" not in table.rows and store.get("ghost") == 9
    store.put("local", 5, persist=False)
    assert "local" not in table.rows
    store.reset()
    assert store.get("ghost") is None           # fresh process view == table


def test_enabled_is_reevaluated_per_operation():
    table = _FakeTable()
    flag = {"on": False}
    store = HydratedStore("t", loader=table.loader, saver=table.saver, ttl=1000.0,
                          enabled=lambda: flag["on"])
    store["a"] = 1
    assert table.rows == {}
    flag["on"] = True
    store["b"] = 2
    assert table.rows == {"b": 2}


# --------------------------------------------------------------------------
# Codec
# --------------------------------------------------------------------------
class Colour(Enum):
    RED = "red"
    BLUE = "blue"


@dataclass
class Inner:
    name: str
    when: Optional[datetime]
    tag: Colour = Colour.RED


@dataclass
class Outer:
    id: str
    score: float
    items: List[Inner] = field(default_factory=list)
    lookup: Dict[str, Inner] = field(default_factory=dict)
    colour: Colour = Colour.BLUE
    started: datetime = field(default_factory=datetime.now)
    finished: Optional[datetime] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    anything: Any = None


def test_codec_round_trips_nested_dataclasses_enums_and_datetimes():
    obj = Outer(
        id="X1", score=0.75,
        items=[Inner("a", datetime(2026, 2, 3, 4, 5, 6, 7)), Inner("b", None, Colour.BLUE)],
        lookup={"k": Inner("c", datetime(2026, 1, 1))},
        started=datetime(2026, 9, 14, 10, 0, 0), finished=None,
        extra={"nested": {"n": [1, 2, {"deep": True}]}},
        anything={"free": "form"},
    )
    encoded = to_jsonable(obj)
    assert encoded["colour"] == "blue" and encoded["items"][0]["when"] == "2026-02-03T04:05:06.000007"
    import json
    json.dumps(encoded)                          # JSON-safe
    decoded = from_jsonable(Outer, encoded)
    assert decoded == obj
    assert isinstance(decoded.items[0].when, datetime) and decoded.items[1].tag is Colour.BLUE


def test_codec_ignores_unknown_keys_and_uses_defaults_for_missing():
    data = {"id": "X", "score": 1.0, "removed_field": 1, "colour": "red"}
    decoded = from_jsonable(Outer, data)
    assert decoded.id == "X" and decoded.colour is Colour.RED and decoded.items == []
    assert from_jsonable(Outer, None) is None
    assert from_jsonable(Any, {"x": 1}) == {"x": 1}


# --------------------------------------------------------------------------
# Repositories over one SQLite file
# --------------------------------------------------------------------------
def _db():
    from database import init_database
    from database.manager import DatabaseManager
    init_database()
    return DatabaseManager()


def _artifact_store(db, agent_id, kind, **kw):
    def loader(since):
        for aid, payload, updated, _meta in db.agent_artifacts.iter_payloads(agent_id, kind, since):
            yield aid, payload, updated

    def saver(key, value):
        db.agent_artifacts.upsert(key, agent_id=agent_id, kind=kind, payload=value)

    return HydratedStore(f"{agent_id}.{kind}", loader=loader, saver=saver,
                         deleter=db.agent_artifacts.delete_artifact, ttl=1000.0,
                         enabled=lambda: True, **kw)


def test_db_mode_cross_instance_visibility_over_agent_artifacts():
    db1, db2 = _db(), _db()
    agent = f"test_agent_{datetime.utcnow().timestamp():.0f}"
    a = _artifact_store(db1, agent, "thing")
    b = _artifact_store(db2, agent, "thing")
    a["r1"] = {"n": 1}
    # b is a cold instance: its first read hydrates from the shared table.
    assert b.get("r1") == {"n": 1}
    b["r2"] = {"n": 2}
    a.coalescer.reset()
    assert a.get("r2") == {"n": 2}
    a.pop("r1")
    b.coalescer.reset()
    b._last_full = -1e9
    assert "r1" not in b and len(b) == 1
    # Restart simulation: wipe the cache only; the row is still there.
    a.reset()
    assert a.get("r2") == {"n": 2}
    db1.agent_artifacts.delete_artifact("r2")


def test_artifact_repository_checksum_guard_and_prune():
    db = _db()
    agent = f"chk_{datetime.utcnow().timestamp():.0f}"
    repo = db.agent_artifacts
    for i in range(4):
        repo.upsert(f"{agent}-{i}", agent_id=agent, kind="rep", payload={"i": i},
                    subject_type="claim", subject_id=f"CLM{i}")
    # identical upsert is a no-op (updated_date untouched); a change bumps it
    from database.models import AgentArtifact
    session = repo.session
    before = session.get(AgentArtifact, f"{agent}-0").updated_date
    assert repo.upsert(f"{agent}-0", agent_id=agent, kind="rep", payload={"i": 0}) is True
    session.expire_all()
    assert session.get(AgentArtifact, f"{agent}-0").updated_date == before
    assert repo.upsert(f"{agent}-0", agent_id=agent, kind="rep", payload={"i": 0, "v": 2}) is True
    session.expire_all()
    assert session.get(AgentArtifact, f"{agent}-0").updated_date >= before
    assert repo.upsert(f"{agent}-0", agent_id=agent, kind="rep", payload={"i": 0}) is True
    rows = list(repo.iter_payloads(agent, "rep"))
    assert sorted(r[1]["i"] for r in rows) == [0, 1, 2, 3]
    assert rows[-1][0] == f"{agent}-0"          # ordered by updated_date: the rewritten row is last
    assert {r[3]["subject_id"] for r in rows} == {"CLM0", "CLM1", "CLM2", "CLM3"}
    # Tamper with one row: it is skipped on load, never served.
    row = session.get(AgentArtifact, f"{agent}-1")
    row.payload_json = '{"i": 999}'
    session.commit()
    loaded = {r[0]: r[1] for r in repo.iter_payloads(agent, "rep")}
    assert f"{agent}-1" not in loaded and repo.get_payload(f"{agent}-1") is None
    # DB-side prune keeps the newest N by created_date.
    victims = repo.prune(agent, "rep", keep=2)
    assert sorted(victims) == [f"{agent}-0", f"{agent}-1"]
    assert repo.count_for(agent, "rep") == 2
    assert repo.prune(agent, "rep", keep=5) == []
    for i in (2, 3):
        repo.delete_artifact(f"{agent}-{i}")
    assert repo.count_for(agent) == 0


def test_video_job_repository_terminal_transition_wins_exactly_once():
    db = _db()
    repo = db.video_jobs
    job_id = f"VJ-{datetime.utcnow().timestamp():.0f}"
    job = {"id": job_id, "campaign_id": "CMP-1", "submitted_by": "u1", "status": "processing",
           "provider": "mock", "provider_job_id": "p-1", "pipeline_type": "explainer",
           "created_at": datetime.utcnow().date().isoformat() + "T00:00:00+00:00",
           "progress": 10}
    repo.upsert(job)
    assert repo.get_job(job_id)["progress"] == 10
    assert repo.update_fields(job_id, {"progress": 50})["progress"] == 50
    assert repo.count_by_campaign("CMP-1") >= 1
    assert repo.count_created_on(datetime.utcnow().date().isoformat(), "u1") >= 1

    # Two racers (webhook + poller) on separate sessions, released together.
    from database.manager import DatabaseManager
    barrier = threading.Barrier(2)
    results = {}

    def racer(name, status):
        other = DatabaseManager()
        barrier.wait()
        results[name] = other.video_jobs.mark_terminal(job_id, {"status": status, "who": name})

    threads = [threading.Thread(target=racer, args=("webhook", "completed")),
               threading.Thread(target=racer, args=("poller", "failed"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    winners = [k for k, v in results.items() if v is not None]
    assert len(winners) == 1, results
    final = repo.get_job(job_id)
    assert final["who"] == winners[0] and final["status"] == results[winners[0]]["status"]
    # A later terminal attempt is refused; missing job is None.
    assert repo.mark_terminal(job_id, {"status": "cancelled"}) is None
    assert repo.mark_terminal("VJ-nope", {"status": "failed"}) is None
    assert repo.update_fields("VJ-nope", {"x": 1}) is None
    assert repo.delete_job(job_id) is True


def test_video_job_iter_since_is_incremental():
    db = _db()
    repo = db.video_jobs
    stamp = f"{datetime.utcnow().timestamp():.0f}"
    repo.upsert({"id": f"VJ-a-{stamp}", "status": "queued", "created_at": "2026-01-01T00:00:00"})
    rows = {jid: upd for jid, _job, upd in repo.iter_jobs()}
    mark = rows[f"VJ-a-{stamp}"]
    repo.upsert({"id": f"VJ-b-{stamp}", "status": "queued", "created_at": "2026-01-01T00:00:00"})
    later = [jid for jid, _job, _upd in repo.iter_jobs(since=mark)]
    assert f"VJ-b-{stamp}" in later
    for jid in (f"VJ-a-{stamp}", f"VJ-b-{stamp}"):
        repo.delete_job(jid)
