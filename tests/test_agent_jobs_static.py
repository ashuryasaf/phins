"""
A3 dashboards: every caller of a migrated agent route wraps its fetch in
``phinsAwaitJob`` and loads ``/agent-jobs.js`` so a 202 job envelope is
followed to completion transparently. The helper itself is exercised under
node (when available) against a fake ``fetch``.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
HELPER = STATIC / "agent-jobs.js"

MIGRATED_ROUTES = (
    "/api/claims/probability-report",
    "/api/risk-dashboard/ai-assess",
    "/api/reports/analyze",
    "/api/reports/generate",
    "/api/mislaka/import",
)


def _pages_calling(route: str):
    for page in STATIC.glob("*.html"):
        if f"fetch('{route}'" in page.read_text(encoding="utf-8"):
            yield page


def test_every_dashboard_caller_of_a_migrated_route_awaits_the_job():
    seen = 0
    for route in MIGRATED_ROUTES:
        for page in _pages_calling(route):
            html = page.read_text(encoding="utf-8")
            assert '<script src="/agent-jobs.js"></script>' in html, page.name
            bare = re.findall(rf"(?<!phinsAwaitJob\()await fetch\('{re.escape(route)}'", html)
            assert not bare, f"{page.name}: fetch('{route}') not wrapped in phinsAwaitJob"
            seen += html.count(f"phinsAwaitJob(await fetch('{route}'")
    # claims x2 (admin, adjuster), analyze x2, generate x2, mislaka x1
    assert seen == 7


def test_helper_is_served_from_static_root_and_is_self_contained():
    src = HELPER.read_text(encoding="utf-8")
    assert "global.phinsAwaitJob = phinsAwaitJob" in src
    assert "'/api/jobs/'" in src
    assert "localStorage.getItem('phins_token')" in src


NODE_HARNESS = r"""
const src = require('fs').readFileSync(process.env.HELPER, 'utf8');
global.window = global; global.Headers = class { constructor(h) { this.h = h; } };
global.localStorage = { getItem: () => 'stored-token' };
eval(src);
const calls = [];
const jobs = process.env.JOBS.split(',');
let i = 0;
global.fetch = async (url, init) => {
  calls.push({ url, auth: (init.headers || {}).Authorization });
  const status = jobs[Math.min(i++, jobs.length - 1)];
  const job = { id: 'JOB-1', status, result: { success: true, n: 1 }, error_message: status === 'failed' ? 'boom' : null };
  return { ok: true, status: 200, json: async () => job, clone() { return this; } };
};
const mk = (status, body) => ({ status, clone() { return this; }, json: async () => body, ok: status < 300 });
(async () => {
  const out = {};
  // Non-202 responses pass straight through, untouched.
  const plain = mk(200, { a: 1 });
  out.passthrough = (await phinsAwaitJob(plain)) === plain;
  const other202 = mk(202, { message: 'not a job' });
  out.non_job_202 = (await phinsAwaitJob(other202)) === other202;
  // A job envelope is followed to completion.
  const env = mk(202, { job_id: 'JOB-1', status: 'queued', poll_url: '/api/jobs/JOB-1' });
  const res = await phinsAwaitJob(env, { token: process.env.TOKEN || undefined, intervalMs: 1, timeoutMs: 2000 });
  out.status = res.status; out.ok = res.ok; out.body = await res.json(); out.calls = calls;
  out.job_status = res.job && res.job.status;
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


def _run_node(jobs, token=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    env = {"JOBS": ",".join(jobs), "HELPER": str(HELPER), "PATH": "/usr/bin:/bin"}
    if token:
        env["TOKEN"] = token
    proc = subprocess.run([node, "-e", NODE_HARNESS], env=env,
                          capture_output=True, text=True, timeout=30, check=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_helper_polls_until_completed_and_returns_result():
    out = _run_node(["pending", "claimed", "completed"], token="tok-x")
    assert out["passthrough"] is True and out["non_job_202"] is True
    assert out["status"] == 200 and out["ok"] is True
    assert out["body"] == {"success": True, "n": 1}
    assert out["job_status"] == "completed"
    assert [c["url"] for c in out["calls"]] == ["/api/jobs/JOB-1"] * 3
    assert {c["auth"] for c in out["calls"]} == {"Bearer tok-x"}


def test_helper_falls_back_to_stored_token_and_maps_failures():
    out = _run_node(["failed"])
    assert out["status"] == 500 and out["ok"] is False
    assert out["body"]["error"] == "boom" and out["body"]["job_status"] == "failed"
    assert out["calls"][0]["auth"] == "Bearer stored-token"
    out = _run_node(["dead_letter"])
    assert out["status"] == 503 and out["body"]["job_status"] == "dead_letter"
