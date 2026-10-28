"""Public link-preview cards for shared PHINS URLs.

Messaging apps (WhatsApp, iMessage, Telegram, Slack, and the other unfurl
bots) fetch a URL before and after send and render ``og:title`` plus
``og:image``. The card is a 1200×630 navy/gold banner: the shield logo and
the document name. It never includes document text.

The image route is public on purpose. Titles come from a fixed name or from
a file that actually exists under ``web_portal/static``. An unknown path
stays "PHINS", so a crafted query cannot put arbitrary words on the logo.
"""

from __future__ import annotations

import html
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

_STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
_LOGO = _STATIC / "phins-logo.png"
_FONT_BOLD = _STATIC / "fonts" / "DejaVuSans-Bold.ttf"
_FONT_REGULAR = _STATIC / "fonts" / "DejaVuSans.ttf"

CARD_WIDTH = 1200
CARD_HEIGHT = 630
TAGLINE = "Personal Health Insurance & Savings"
GENERIC_TITLE = "PHINS"

# Query keys that must not be echoed into og:url.
_SECRET_QUERY = frozenset({
    "access_token",
    "token",
    "access_key",
    "password",
})
# Browser-only cache escape. It is not a credential and must not become
# the URL WhatsApp stores as the card.
_DROPPED_QUERY = _SECRET_QUERY | frozenset({"phins_open"})

# Preview crawlers. A match receives the card only — never the document —
# so spoofing one of these names cannot open a confidential file.
_PREVIEW_CRAWLER = re.compile(
    r"whatsapp|facebookexternalhit|facebot|twitterbot|linkedinbot|"
    r"slackbot-linkexpanding|slackbot|telegrambot|discordbot|"
    r"skypeuripreview|vkshare|pinterestbot|redditbot|embedly|iframely|"
    r"quora link preview|bitlybot|snapchat|viber|kakaotalk|"
    r"google-pagerenderer|meta-externalagent|meta-externalfetcher",
    re.IGNORECASE,
)

_PATH_RE = re.compile(r"/[A-Za-z0-9._/\-]{0,180}\Z")

# Names a recipient should recognise. The Hebrew edition is labelled in
# Latin so the card does not depend on a right-to-left text shaper.
_KNOWN_TITLES = {
    "/": GENERIC_TITLE,
    "/index.html": GENERIC_TITLE,
    "/business-plan.html": "PHINS Unified Business Plan",
    "/business-plan.he.html": "PHINS Unified Business Plan (Hebrew)",
    "/pitch-dashboard.html": "PHINS Pitch Dashboard",
    "/phins-customer-150k-one-pager.html": "PHINS Customer Cover US$150,000",
    "/phins-customer-150k-one-pager.he.html": "PHINS Customer Cover US$150,000 (Hebrew)",
    "/investor-deck.html": "PHINS Investor Deck",
    "/investor-deck.he.html": "PHINS Investor Deck (Hebrew)",
    "/legal/nda.html": "PHINS Non-Disclosure Agreement",
    "/legal/cap-table.html": "PHINS Cap Table",
    "/legal/term-sheet.html": "PHINS Term Sheet",
    "/legal/shareholders-agreement.html": "PHINS Shareholders Agreement",
    "/legal/employment-agreement.html": "PHINS Employment Agreement",
    "/legal/founder-agreement.html": "PHINS Founder Agreement",
    "/legal/financial-model.html": "PHINS Financial Model",
    "/legal/offer-letter.html": "PHINS Offer Letter",
    "/legal/esop-agreement.html": "PHINS ESOP Agreement",
    "/legal/ip-assignment.html": "PHINS IP Assignment",
    "/legal/hr-policies.html": "PHINS HR Policies",
    "/legal/incorporation-delaware.html": "PHINS Incorporation",
    "/legal/legal-compliance.html": "PHINS Legal Compliance",
    "/legal/trademark-ip.html": "PHINS Trademark and IP",
    "/legal/cofounder-exit-clause.html": "PHINS Cofounder Exit Clause",
    "/internal/phins-investor-business-plan.html": "PHINS Investor Business Plan",
    "/internal/phins-investment-deck.html": "PHINS Investment Deck",
    "/internal/phins-insurer-mga-business-plan.html": "PHINS Insurer MGA Business Plan",
    "/internal/phins-ai-tech-partner-business-plan.html": "PHINS AI Tech Partner Business Plan",
    "/internal/exec-actuary-briefing.html": "PHINS Actuary Briefing",
    "/internal/exec-actuary-briefing.pdf": "PHINS Actuary Briefing",
    "/phins_business_plan_executive.pdf": "PHINS Executive Business Plan",
    "/phins_business_plan_executive.md": "PHINS Executive Business Plan",
    "/investor-docs/phins-unified-business-plan.pdf": "PHINS Unified Business Plan",
    "/investor-docs/phins-unified-business-plan.md": "PHINS Unified Business Plan",
    "/investor-docs/phins-unified-business-plan.he.pdf": "PHINS Unified Business Plan (Hebrew)",
    "/investor-docs/phins-unified-business-plan.he.md": "PHINS Unified Business Plan (Hebrew)",
}

_NAVY = (6, 13, 31)
_NAVY_MID = (14, 47, 99)
_NAVY_LIFT = (18, 63, 130)
_GOLD = (227, 191, 111)
_GOLD_DEEP = (201, 160, 78)
_INK = (244, 247, 251)
_MUTED = (183, 195, 214)


class PreviewPathError(ValueError):
    """The preview path is not a safe site path."""


def is_preview_crawler(user_agent: str) -> bool:
    """True for link-unfurl bots. Ordinary browsers are false."""
    if not user_agent:
        return False
    return _PREVIEW_CRAWLER.search(str(user_agent)) is not None


def normalize_preview_path(raw: str) -> str:
    """Return a same-site path, or raise ``PreviewPathError``.

    Only the path is accepted. A ``title`` query, a host, or ``..`` cannot
    change the words drawn on the card.
    """
    text = str(raw or "").strip()
    if not text:
        return "/"
    text = text.split("#", 1)[0].split("?", 1)[0].strip()
    if "\\" in text or "\x00" in text or ".." in text:
        raise PreviewPathError("invalid preview path")
    if not text.startswith("/"):
        text = "/" + text
    text = re.sub(r"/{2,}", "/", text)
    if len(text) > 1 and text.endswith("/"):
        text = text[:-1]
    if not _PATH_RE.fullmatch(text):
        raise PreviewPathError("invalid preview path")
    return text


def preview_title(path: str) -> str:
    """Public document name for ``path``. Unknown paths stay generic."""
    try:
        normalized = normalize_preview_path(path)
    except PreviewPathError:
        return GENERIC_TITLE
    known = _KNOWN_TITLES.get(normalized)
    if known:
        return known
    if not _static_file_exists(normalized):
        return GENERIC_TITLE
    return _humanize(normalized)


def image_path_for(path: str) -> str:
    """Root-relative URL of the card for ``path``.

    The path has no query string. WhatsApp's image fetch drops a card whose
    ``og:image`` carries ``?``. ``/link-preview.png?path=`` still resolves.
    """
    normalized = "/"
    try:
        normalized = normalize_preview_path(path)
    except PreviewPathError:
        normalized = "/"
    leaf = "/index" if normalized in ("/", "/index.html") else normalized
    return "/link-preview" + leaf + ".png"


def preview_target_from_image_route(path: str, query_path: str = "") -> str:
    """Document path named by a public card URL.

    ``/link-preview/business-plan.html.png`` and
    ``/link-preview.png?path=/business-plan.html`` are the same card.
    """
    raw = str(path or "")
    if raw == "/link-preview.png":
        return normalize_preview_path(query_path or "/")
    prefix = "/link-preview/"
    if raw.startswith(prefix) and raw.endswith(".png") and ".." not in raw:
        inner = raw[len(prefix):-len(".png")].strip("/")
        if inner in ("", "index"):
            return normalize_preview_path("/")
        return normalize_preview_path("/" + inner)
    raise PreviewPathError("invalid preview path")


def absolute_image_url(origin: str, path: str) -> str:
    rel = image_path_for(path)
    base = str(origin or "").strip().rstrip("/")
    if not base:
        return rel
    return base + rel


def canonical_page_url(origin: str, path: str, raw_target: str = "") -> str:
    """Absolute page URL with access secrets removed from the query."""
    try:
        normalized = normalize_preview_path(path)
    except PreviewPathError:
        normalized = "/"
    query = ""
    if raw_target:
        pairs = parse_qsl(urlsplit(str(raw_target)).query, keep_blank_values=False)
        kept = [(key, value) for key, value in pairs if key.lower() not in _DROPPED_QUERY]
        query = urlencode(kept)
    base = str(origin or "").strip().rstrip("/")
    url = f"{base}{normalized}" if base else normalized
    if query:
        url = f"{url}?{query}"
    return url


def open_graph_markup(*, path: str, origin: str = "", page_url: str = "") -> str:
    """Open Graph and Twitter card tags. Values are HTML-escaped."""
    title = preview_title(path)
    image = absolute_image_url(origin, path)
    page = page_url or canonical_page_url(origin, path)
    description = f"PHINS · {TAGLINE}"

    def attr(value: str) -> str:
        return html.escape(value, quote=True)

    lines = [
        '<meta property="og:site_name" content="PHINS">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{attr(title)}">',
        f'<meta property="og:description" content="{attr(description)}">',
        f'<meta property="og:image" content="{attr(image)}">',
        '<meta property="og:image:type" content="image/png">',
        f'<meta property="og:image:width" content="{CARD_WIDTH}">',
        f'<meta property="og:image:height" content="{CARD_HEIGHT}">',
        f'<meta property="og:image:alt" content="{attr(title)}">',
        f'<meta property="og:url" content="{attr(page)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{attr(title)}">',
        f'<meta name="twitter:description" content="{attr(description)}">',
        f'<meta name="twitter:image" content="{attr(image)}">',
    ]
    if image.startswith("https://"):
        lines.insert(5, f'<meta property="og:image:secure_url" content="{attr(image)}">')
    return "\n".join(lines)


def inject_preview_tags(html_text: str, *, path: str, origin: str = "", page_url: str = "") -> str:
    """Insert the card tags before ``</head>`` when the page has none yet."""
    if not html_text:
        return html_text
    lowered = html_text.lower()
    if 'property="og:image"' in lowered or "property='og:image'" in lowered:
        return html_text
    block = open_graph_markup(path=path, origin=origin, page_url=page_url)
    match = re.search(r"</head\s*>", html_text, flags=re.IGNORECASE)
    if not match:
        return block + "\n" + html_text
    return html_text[:match.start()] + block + "\n" + html_text[match.start():]


def preview_shell(*, path: str, origin: str = "", page_url: str = "") -> str:
    """Tiny public HTML document: the card, the file name, and nothing else.

    Returned with HTTP 200 to preview crawlers. It is not the document.
    There is no ``noindex`` tag: WhatsApp and Facebook treat that directive
    as "do not generate a card". Search engines are not preview crawlers, so
    they still receive the gated page, which keeps its own ``noindex``.

    A real browser that was handed this shell by a shared cache continues
    to the unlock page. Crawlers do not run the script, so the card stays.
    """
    title = preview_title(path)
    safe_title = html.escape(title, quote=True)
    image = html.escape(absolute_image_url(origin, path), quote=True)
    tags = open_graph_markup(path=path, origin=origin, page_url=page_url)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{safe_title}</title>\n"
        f"  {tags}\n"
        "</head>\n"
        '<body style="margin:0;background:#060d1f">\n'
        f'  <img src="{image}" alt="{safe_title}" width="{CARD_WIDTH}" height="{CARD_HEIGHT}">\n'
        "  <script>\n"
        "  (function () {\n"
        "    try {\n"
        "      if (/[?&]phins_open=/.test(location.search)) return;\n"
        "      var join = location.search ? '&' : '?';\n"
        "      location.replace(location.pathname + location.search + join + 'phins_open=1' + location.hash);\n"
        "    } catch (e) {}\n"
        "  })();\n"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
    )


def render_preview_png(path: str) -> bytes:
    """PNG bytes for the public card of ``path``."""
    return _png_for_title(preview_title(path))


@lru_cache(maxsize=64)
def _png_for_title(title: str) -> bytes:
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    image = _gradient()
    draw = ImageDraw.Draw(image)
    # Gold rails. A crawler crops the outer few pixels, so the mark sits inset.
    draw.rectangle((0, 0, CARD_WIDTH, 8), fill=_GOLD)
    draw.rectangle((0, CARD_HEIGHT - 8, CARD_WIDTH, CARD_HEIGHT), fill=_GOLD_DEEP)
    draw.rectangle((0, 0, 8, CARD_HEIGHT), fill=_GOLD_DEEP)
    draw.rectangle((CARD_WIDTH - 8, 0, CARD_WIDTH, CARD_HEIGHT), fill=_GOLD_DEEP)

    logo = _logo_image()
    if logo is not None:
        image.paste(logo, (72, (CARD_HEIGHT - logo.size[1]) // 2), logo)

    bold = _font(_FONT_BOLD, 28)
    regular = _font(_FONT_REGULAR, 22)
    headline_size = 58
    headline_font = _font(_FONT_BOLD, headline_size)
    text_x = 360
    max_width = CARD_WIDTH - text_x - 72
    main, subtitle = _card_lines(title)
    while headline_size > 34:
        headline_font = _font(_FONT_BOLD, headline_size)
        lines = _wrap(draw, main, headline_font, max_width)
        if len(lines) <= 3:
            break
        headline_size -= 4
    lines = _wrap(draw, main, headline_font, max_width)[:3]
    line_h = headline_size + 10
    block_h = 36 + 18 + len(lines) * line_h + 16 + 28
    top = max(78, (CARD_HEIGHT - block_h) // 2)

    _draw_tracked(draw, "PHINS", text_x, top, bold, _GOLD, tracking=6)
    y = top + 36 + 18
    for line in lines:
        draw.text((text_x, y), line, font=headline_font, fill=_INK)
        y += line_h
    draw.text((text_x, y + 12), subtitle, font=regular, fill=_MUTED)

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _card_lines(title: str) -> tuple[str, str]:
    if str(title or "").strip().upper() == GENERIC_TITLE:
        return "Safe Assurance", TAGLINE
    return str(title or GENERIC_TITLE), TAGLINE


def _gradient():
    from PIL import Image

    small = Image.new("RGB", (64, 32))
    px = small.load()
    for y in range(32):
        for x in range(64):
            t = (x / 63) * 0.62 + (y / 31) * 0.38
            if t < 0.5:
                color = _lerp(_NAVY, _NAVY_MID, t / 0.5)
            else:
                color = _lerp(_NAVY_MID, _NAVY_LIFT, (t - 0.5) / 0.5)
            px[x, y] = color
    return small.resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.BICUBIC)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _logo_image():
    from PIL import Image

    if not _LOGO.is_file():
        return None
    logo = Image.open(_LOGO).convert("RGBA")
    return logo.resize((248, 248), Image.Resampling.LANCZOS)


def _font(path: Path, size: int):
    from PIL import ImageFont

    if path.is_file():
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: float) -> list[str]:
    words = str(text or "").split()
    if not words:
        return [GENERIC_TITLE]
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines or [GENERIC_TITLE]


def _draw_tracked(draw, text: str, x: int, y: int, font, fill, tracking: int = 0) -> None:
    cursor = x
    for char in text:
        draw.text((cursor, y), char, font=font, fill=fill)
        cursor += int(draw.textlength(char, font=font)) + tracking


def _humanize(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    for ext in (".html", ".htm", ".pdf", ".md", ".png", ".jpg", ".jpeg", ".svg"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    name = name.replace(".", " ").replace("-", " ").replace("_", " ")
    name = " ".join(name.split())
    if not name or name.lower() == "index":
        return GENERIC_TITLE
    titled = name.title()
    if len(titled) > 80:
        titled = titled[:80].rstrip()
    return titled


def _static_file_exists(path: str) -> bool:
    rel = path.lstrip("/")
    if not rel:
        return False
    candidate = (_STATIC / rel).resolve()
    try:
        candidate.relative_to(_STATIC.resolve())
    except ValueError:
        return False
    return candidate.is_file()

