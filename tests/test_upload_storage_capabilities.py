import json
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal


class ServerThread(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _json_request(url, method="GET", payload=None, token=None, extra_headers=None):
    headers = dict(extra_headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    else:
        data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


def _upload_raw(url, payload: bytes, filename: str, token: str):
    req = Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "video/mp4",
            "X-Upload-Filename": filename,
        },
        method="POST",
    )
    with urlopen(req) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else {}


def _download_bytes(url, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.status, resp.read(), dict(resp.headers)


def _init_port(base):
    try:
        _json_request(base + "/api/media")
    except Exception:
        pass


def _inject_session(token, username="admin", role="admin", customer_id=""):
    portal.SESSIONS[token] = {
        "username": username,
        "role": role,
        "customer_id": customer_id,
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    if username not in portal.USERS:
        portal.USERS[username] = {"role": role, "username": username, "customer_id": customer_id}


def test_raw_upload_endpoint_persists_large_binary_and_streams_back():
    port = 8294
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_raw_upload_token"
    _inject_session(token, "raw_uploader", "admin")

    try:
        payload = b"video-bytes-" * 1024
        status, resp = _upload_raw(base + "/api/uploads/raw", payload, "clip.mp4", token)
        assert status == 201
        assert resp["success"] is True
        uploaded = resp["uploaded_file"]
        assert uploaded["stored_externally"] is True
        assert uploaded["size"] == len(payload)
        assert uploaded["file_analysis"]["category"] == "video"

        status_dl, body, headers = _download_bytes(base + uploaded["url"], token=token)
        assert status_dl == 200
        assert body == payload
        assert headers["Content-Type"].startswith("video/mp4")
    finally:
        srv.stop()
