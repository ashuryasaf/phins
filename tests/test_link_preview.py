"""Public link-preview cards for shared URLs.

WhatsApp and the other unfurl bots need HTTP 200, an absolute og:image, and
the file name. The card is the shield on the navy/gold gradient. A normal
client still hits the confidential gate, and a spoofed crawler name does not
receive the document.
"""

import io
import os

import pytest
import requests
from PIL import Image

from services import link_preview as lp

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
WHATSAPP_UA = "WhatsApp/2.23.20.0"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def test_known_document_names_and_unknown_paths_stay_generic():
    assert lp.preview_title("/business-plan.html") == "PHINS Unified Business Plan"
    assert lp.preview_title("/business-plan.he.html") == "PHINS Unified Business Plan (Hebrew)"
    assert lp.preview_title("/phins-customer-150k-one-pager.html") == "PHINS Customer Cover US$150,000"
    assert lp.preview_title("/phins-customer-150k-one-pager.he.html") == "PHINS Customer Cover US$150,000 (Hebrew)"
    assert lp.preview_title("/legal/nda.html") == "PHINS Non-Disclosure Agreement"
    assert lp.preview_title("/no-such-wire-transfer.html") == "PHINS"
    assert lp.preview_title("/index.html") == "PHINS"


def test_preview_path_rejects_traversal_and_ignores_free_text():
    with pytest.raises(lp.PreviewPathError):
        lp.normalize_preview_path("/../../etc/passwd")
    with pytest.raises(lp.PreviewPathError):
        lp.normalize_preview_path("/wire<script>.html")
    # A title parameter is stripped. The card words come from the path only.
    assert lp.normalize_preview_path(
        "/business-plan.html?title=Wire+the+funds"
    ) == "/business-plan.html"
    assert lp.preview_title("/business-plan.html") == lp.preview_title(
        "/business-plan.html?title=Wire+the+funds"
    )


def test_crawler_detection_is_limited_to_unfurl_bots():
    assert lp.is_preview_crawler(WHATSAPP_UA)
    assert lp.is_preview_crawler("facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)")
    assert lp.is_preview_crawler("TelegramBot (like TwitterBot)")
    assert not lp.is_preview_crawler(BROWSER_UA)
    assert not lp.is_preview_crawler("")
    assert not lp.is_preview_crawler("Googlebot/2.1")


def test_card_is_a_branded_png_and_unknown_paths_share_one_image():
    png = lp.render_preview_png("/business-plan.html")
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    image = Image.open(io.BytesIO(png))
    assert image.size == (lp.CARD_WIDTH, lp.CARD_HEIGHT)
    # Top gold rail and the navy field under it.
    assert image.getpixel((24, 3))[0] > 180
    assert image.getpixel((24, 3))[1] > 140
    assert image.getpixel((80, 40))[2] > image.getpixel((80, 40))[0]
    # More than a flat fill: gradient, logo, and type.
    assert image.getcolors(8) is None
    generic = lp.render_preview_png("/no-such-wire-transfer.html")
    assert generic == lp.render_preview_png("/")
    assert generic != png


def test_page_url_drops_access_secrets_and_keeps_the_share():
    url = lp.canonical_page_url(
        "https://www.phins.ai",
        "/business-plan.html",
        "/business-plan.html?share=shr_abc&access_token=secret-value&password=nope",
    )
    assert url == "https://www.phins.ai/business-plan.html?share=shr_abc"
    tags = lp.open_graph_markup(
        path="/business-plan.html",
        origin="https://www.phins.ai",
        page_url=url,
    )
    assert 'property="og:title" content="PHINS Unified Business Plan"' in tags
    assert "og:image" in tags
    assert "/link-preview/business-plan.html.png" in tags
    assert "secret-value" not in tags
    assert "phins_open" not in tags
    opened = lp.canonical_page_url(
        "https://www.phins.ai",
        "/business-plan.html",
        "/business-plan.html?share=shr_abc&phins_open=1",
    )
    assert opened == "https://www.phins.ai/business-plan.html?share=shr_abc"
    shell = lp.preview_shell(path="/business-plan.html", origin="https://www.phins.ai", page_url=url)
    assert "id=\"plan-exec\"" not in shell
    assert "Pre-launch" not in shell
    assert "noindex" not in shell.lower()
    assert "PHINS Unified Business Plan" in shell
    assert "phins_open=1" in shell
    assert lp.preview_target_from_image_route(
        "/link-preview/business-plan.html.png"
    ) == "/business-plan.html"
    assert lp.preview_target_from_image_route(
        "/link-preview.png", "/business-plan.html"
    ) == "/business-plan.html"
    with pytest.raises(lp.PreviewPathError):
        lp.preview_target_from_image_route("/link-preview/../../etc/passwd.png")


def test_inject_is_idempotent():
    page = "<html><head><title>X</title></head><body>hello</body></html>"
    once = lp.inject_preview_tags(page, path="/login.html", origin="https://www.phins.ai")
    twice = lp.inject_preview_tags(once, path="/login.html", origin="https://www.phins.ai")
    assert once.count('property="og:image"') == 1
    assert twice == once
    assert "hello" in twice


@pytest.fixture
def gate_token(monkeypatch):
    monkeypatch.setenv("PHINS_CONFIDENTIAL_ACCESS_TOKEN", "t" * 40)
    return "t" * 40


def test_http_public_page_and_card_are_reachable(gate_token):
    page = requests.get(f"{BASE_URL}/index.html", timeout=10, headers={"User-Agent": BROWSER_UA})
    assert page.status_code == 200
    assert 'property="og:image"' in page.text
    assert "/link-preview/index.png" in page.text
    card = requests.get(
        f"{BASE_URL}/link-preview/business-plan.html.png",
        timeout=10,
        headers={"User-Agent": BROWSER_UA},
    )
    assert card.status_code == 200
    assert card.headers["Content-Type"].startswith("image/png")
    image = Image.open(io.BytesIO(card.content))
    assert image.size == (1200, 630)
    robots = requests.get(f"{BASE_URL}/robots.txt", timeout=10)
    assert "Allow: /link-preview.png" in robots.text
    assert "Allow: /link-preview/" in robots.text
    legacy = requests.get(
        f"{BASE_URL}/link-preview.png",
        params={"path": "/business-plan.html"},
        timeout=10,
        headers={"User-Agent": BROWSER_UA},
    )
    assert legacy.status_code == 200
    assert legacy.headers["Content-Type"].startswith("image/png")
    assert legacy.content == card.content


def test_http_whatsapp_gets_the_card_and_a_browser_stays_gated(gate_token):
    browser = requests.get(
        f"{BASE_URL}/business-plan.html",
        params={"share": "shr_preview"},
        timeout=15,
        headers={"User-Agent": BROWSER_UA},
        allow_redirects=False,
    )
    assert browser.status_code == 401
    assert "Access restricted" in browser.text
    assert 'property="og:title" content="PHINS Unified Business Plan"' in browser.text
    assert 'id="plan-exec"' not in browser.text

    crawler = requests.get(
        f"{BASE_URL}/business-plan.html",
        params={"share": "shr_preview"},
        timeout=15,
        headers={"User-Agent": WHATSAPP_UA},
        allow_redirects=False,
    )
    assert crawler.status_code == 200
    # WhatsApp keeps a public 200 and drops noindex / private / Vary: User-Agent.
    # s-maxage=0 tells a shared cache not to store the shell for the next visitor.
    cache = crawler.headers.get("Cache-Control", "")
    assert "public" in cache
    assert "s-maxage=0" in cache
    assert "no-store" not in cache
    assert "User-Agent" not in crawler.headers.get("Vary", "")
    assert "noindex" not in crawler.headers.get("X-Robots-Tag", "").lower()
    assert "noindex" not in crawler.text.lower()
    assert "phins_open=1" in crawler.text
    assert 'property="og:image"' in crawler.text
    assert "/link-preview/business-plan.html.png" in crawler.text
    assert "PHINS Unified Business Plan" in crawler.text
    assert 'id="plan-exec"' not in crawler.text
    assert "Pre-launch build budget" not in crawler.text
    assert "signer_name" not in crawler.text
    assert "shr_preview" in crawler.text

    # The image named by the card is public and is the branded banner.
    image_url = crawler.text.split('property="og:image" content="', 1)[1].split('"', 1)[0]
    fetched = requests.get(image_url, timeout=10, headers={"User-Agent": WHATSAPP_UA})
    assert fetched.status_code == 200
    assert fetched.headers["Content-Type"].startswith("image/png")
    assert Image.open(io.BytesIO(fetched.content)).size == (1200, 630)
    assert "cross-origin" in fetched.headers.get("Cross-Origin-Resource-Policy", "")

    # The recovery URL is the unlock page for a browser, still only the card
    # for a crawler, and it never becomes the URL stored on the card.
    opened = requests.get(
        f"{BASE_URL}/business-plan.html",
        params={"share": "shr_preview", "phins_open": "1"},
        timeout=15,
        headers={"User-Agent": BROWSER_UA},
        allow_redirects=False,
    )
    assert opened.status_code == 401
    assert "Access restricted" in opened.text
    assert 'id="plan-exec"' not in opened.text
    assert "phins_open" not in crawler.text.split('property="og:url"', 1)[-1].split(">", 1)[0]
    crawler_open = requests.get(
        f"{BASE_URL}/business-plan.html",
        params={"share": "shr_preview", "phins_open": "1"},
        timeout=15,
        headers={"User-Agent": WHATSAPP_UA},
        allow_redirects=False,
    )
    assert crawler_open.status_code == 200
    assert 'id="plan-exec"' not in crawler_open.text
    og_url = crawler_open.text.split('property="og:url"', 1)[-1].split(">", 1)[0]
    assert "phins_open" not in og_url
    assert "shr_preview" in og_url


def test_http_spoofed_crawler_does_not_receive_a_download(gate_token):
    r = requests.get(
        f"{BASE_URL}/investor-docs/phins-unified-business-plan.pdf",
        timeout=15,
        headers={"User-Agent": "facebookexternalhit/1.1"},
        allow_redirects=False,
    )
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/html")
    assert r.content[:5] != b"%PDF-"
    assert "PHINS Unified Business Plan" in r.text
    bad = requests.get(
        f"{BASE_URL}/link-preview.png",
        params={"path": "/../../etc/passwd"},
        timeout=10,
    )
    assert bad.status_code == 400
    assert b"passwd" not in bad.content
