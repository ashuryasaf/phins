"""
Regression tests for API extension handler exceptions.

When an extension dispatcher raises, the request handler must terminate with a
JSON 500 response instead of falling through to unrelated route logic.
"""

import json
import threading
import time
import urllib.parse
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal


class ServerThread(threading.Thread):
    """Run the portal handler in a background thread for live HTTP assertions."""

    def __init__(self):
        super().__init__(daemon=True)
        self.httpd = HTTPServer(("127.0.0.1", 0), portal.PortalHandler)

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def run(self) -> None:
        self.httpd.serve_forever()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _request(method: str, url: str, data: bytes | None = None) -> tuple[int, str, dict]:
    request = Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urlopen(request, timeout=10) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                json.loads(response.read().decode("utf-8")),
            )
    except HTTPError as exc:
        return (
            exc.code,
            exc.headers.get("Content-Type", ""),
            json.loads(exc.read().decode("utf-8")),
        )


@pytest.fixture
def live_server():
    server = ServerThread()
    server.start()
    time.sleep(0.2)
    try:
        yield server
    finally:
        server.stop()
        server.join(timeout=2)


@pytest.mark.parametrize(
    ("method", "path", "dispatcher_name", "data"),
    [
        ("GET", "/api/foundations", "api_ext_get", None),
        ("POST", "/api/security/captcha", "api_ext_post", b"{}"),
        ("PUT", "/api/admin/foundations/foundation-1/members/member-1", "api_ext_put", b"{}"),
    ],
)
def test_extension_dispatch_exceptions_return_json_500(
    monkeypatch, live_server, method, path, dispatcher_name, data
):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(portal, "api_extensions_enabled", True)
    monkeypatch.setattr(portal, dispatcher_name, boom)
    if method == "PUT":
        monkeypatch.setattr(portal, "urlparse", urllib.parse.urlparse)

    status, content_type, body = _request(
        method,
        f"http://127.0.0.1:{live_server.port}{path}",
        data=data,
    )

    assert status == 500
    assert content_type.startswith("application/json")
    assert body == {"error": "Internal server error"}
