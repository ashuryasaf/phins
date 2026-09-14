/*
 * PHINS agent job polling (A3).
 *
 * When the server runs with PHINS_AGENT_ASYNC the agent routes (claims
 * probability report, underwriting AI assess, risk-report analyze/generate,
 * Mislaka import, video submit) answer
 *
 *     202 { job_id, status: "queued", poll_url: "/api/jobs/<id>" }
 *
 * instead of the synchronous body. phinsAwaitJob(response, options) follows
 * poll_url until the job is terminal and returns a Response-like object whose
 * json() is the job's result, so a caller written as
 *
 *     const response = await phinsAwaitJob(await fetch(url, init), { token });
 *     if (!response.ok) ...; const data = await response.json();
 *
 * behaves identically whether the flag is on or off. Anything other than a
 * 202 job envelope is returned untouched.
 *
 * Failure mapping: completed -> 200 + result; failed -> 500 + { error };
 * dead_letter -> 503 + { error }; poll timeout -> 504 + { error, poll_url }.
 */
(function (global) {
  'use strict';

  var TERMINAL = { completed: true, failed: true, dead_letter: true };
  var DEFAULTS = { intervalMs: 1000, maxIntervalMs: 5000, timeoutMs: 180000 };

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function resolveToken(options) {
    if (options && options.token) return options.token;
    try {
      return global.localStorage.getItem('phins_token') || '';
    } catch (_) {
      return '';
    }
  }

  function syntheticResponse(status, body, job) {
    var text = JSON.stringify(body === undefined ? {} : body);
    return {
      ok: status >= 200 && status < 300,
      status: status,
      statusText: '',
      headers: new Headers({ 'Content-Type': 'application/json' }),
      job: job || null,
      json: function () { return Promise.resolve(JSON.parse(text)); },
      text: function () { return Promise.resolve(text); },
      clone: function () { return syntheticResponse(status, body, job); }
    };
  }

  async function readJson(response) {
    try {
      return await response.clone().json();
    } catch (_) {
      return null;
    }
  }

  function isJobEnvelope(body) {
    return !!(body && typeof body === 'object' && body.job_id && body.poll_url &&
      typeof body.poll_url === 'string' && body.poll_url.indexOf('/api/jobs/') === 0);
  }

  async function phinsAwaitJob(response, options) {
    if (!response || response.status !== 202) return response;
    var envelope = await readJson(response);
    if (!isJobEnvelope(envelope)) return response;

    var opts = Object.assign({}, DEFAULTS, options || {});
    var token = resolveToken(opts);
    var headers = token ? { Authorization: 'Bearer ' + token } : {};
    var deadline = Date.now() + opts.timeoutMs;
    var delay = opts.intervalMs;

    for (;;) {
      var poll = await fetch(envelope.poll_url, { method: 'GET', headers: headers, cache: 'no-store' });
      if (!poll.ok) {
        var pollError = await readJson(poll);
        return syntheticResponse(poll.status,
          pollError || { error: 'Job poll failed (' + poll.status + ')', job_id: envelope.job_id });
      }
      var job = await poll.json();
      if (typeof opts.onProgress === 'function') {
        try { opts.onProgress(job); } catch (_) { /* progress hooks never break the wait */ }
      }
      if (job.status === 'completed') {
        return syntheticResponse(200, job.result === undefined || job.result === null ? {} : job.result, job);
      }
      if (TERMINAL[job.status]) {
        return syntheticResponse(job.status === 'dead_letter' ? 503 : 500, {
          error: job.error_message || ('Job ' + job.status),
          job_id: job.id,
          job_status: job.status
        }, job);
      }
      if (Date.now() >= deadline) {
        return syntheticResponse(504, {
          error: 'Timed out waiting for job ' + envelope.job_id + ' (still ' + job.status + ')',
          job_id: envelope.job_id,
          poll_url: envelope.poll_url
        }, job);
      }
      await sleep(delay);
      delay = Math.min(Math.round(delay * 1.5), opts.maxIntervalMs);
    }
  }

  global.phinsAwaitJob = phinsAwaitJob;
})(typeof window !== 'undefined' ? window : this);
