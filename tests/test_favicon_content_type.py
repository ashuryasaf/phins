from urllib.request import Request, urlopen


def test_favicon_serves_png_content_type():
    req = Request("http://127.0.0.1:8000/favicon.ico")
    with urlopen(req, timeout=5) as resp:
        body = resp.read()

    assert resp.status == 200
    assert resp.headers.get("Content-Type", "").startswith("image/png")
    assert body.startswith(b"\x89PNG\r\n\x1a\n")
