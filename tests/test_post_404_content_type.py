"""
Regression tests for POST 404 response content types.

Unknown API POST routes must return the standard JSON error payload so
clients do not receive HTML and fail while parsing the response.
"""

import json
import threading
import time
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal


class ServerThread(threading.Thread):
    """Thread to run the HTTP server in the background."""

    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self) -> None:
        self.httpd.serve_forever()

    def stop(self) -> None:
        self.httpd.shutdown()


def _post(url: str) -> tuple[int, str, str]:
    req = Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode("utf-8")
    except HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read().decode("utf-8")


def test_unknown_api_post_returns_json_404():
    port = 8095
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    try:
        status, content_type, body = _post(f"http://127.0.0.1:{port}/api/does-not-exist")
        assert status == 404
        assert content_type.startswith("application/json")
        assert json.loads(body) == {"error": "Not Found"}
    finally:
        srv.stop()


def test_unknown_non_api_post_returns_html_404():
    port = 8096
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    try:
        status, content_type, body = _post(f"http://127.0.0.1:{port}/does-not-exist")
        assert status == 404
        assert content_type.startswith("text/html")
        assert "<!DOCTYPE HTML>" in body
    finally:
        srv.stop()
