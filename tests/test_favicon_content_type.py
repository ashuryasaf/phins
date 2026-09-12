import os
from urllib.request import Request, urlopen


def test_favicon_serves_png_content_type():
    base = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
    req = Request(f"{base}/favicon.ico")
    with urlopen(req, timeout=5) as resp:
        body = resp.read()

    assert resp.status == 200
    assert resp.headers.get("Content-Type", "").startswith("image/png")
    assert body.startswith(b"\x89PNG\r\n\x1a\n")
