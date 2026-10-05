"""Shared PHINS letterhead for generated HTML documents.

Claim notices, processing records, and risk reports use one emblem, type,
and navy/gold gradient so a downloaded file matches the on-screen document.

Every generated document also carries a Go back / Close bar
(``document_return_markup``). That bar is chrome only: it never changes
body HTML, checksums, or stored records. Future documents must call
``render_phins_document`` (server) or ``PhinsDocument.printReport`` /
``PhinsDocument.render`` (browser). Standalone HTML pages include
``/phins-doc-return.js``.
"""

from __future__ import annotations

import html
from functools import lru_cache
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
TAGLINE = "Personal Health Insurance & Savings"

# Where each role returns when a document tab has no history and no referrer.
# Keep the keys and paths aligned with PHINS_DOCUMENT_HOMES in
# web_portal/static/phins-doc-return.js.
PIPELINE_DOCUMENT_HOMES = {
    "admin": "/admin.html",
    "manager": "/admin.html",
    "underwriter": "/underwriter-dashboard.html",
    "claims": "/claims-adjuster-dashboard.html",
    "claims_adjuster": "/claims-adjuster-dashboard.html",
    "adjuster": "/claims-adjuster-dashboard.html",
    "accountant": "/accountant-dashboard.html",
    "actuary": "/actuary-dashboard.html",
    "supplier": "/supplier-dashboard.html",
    "regulator": "/regulator-dashboard.html",
    "customer": "/dashboard.html",
    "foundation": "/foundation-dashboard.html",
    "community": "/foundation-dashboard.html",
}


@lru_cache(maxsize=1)
def document_css() -> str:
    return (_STATIC / "phins-document.css").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def logo_svg() -> str:
    return (_STATIC / "phins-logo.svg").read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def document_return_script() -> str:
    return (_STATIC / "phins-doc-return.js").read_text(encoding="utf-8")


def document_return_markup() -> str:
    """Sticky Go back / Close chrome plus the return script.

    Safe to prepend to a document body. Hidden when the file is framed and
    hidden in print. Does not wrap or alter the caller's body HTML.
    """
    return (
        '<nav class="phins-doc-return" aria-label="Leave this document">'
        '<span class="phins-doc-return-note">PHINS document</span>'
        '<span class="phins-doc-return-actions">'
        '<button type="button" class="phins-doc-back">Go back</button>'
        '<button type="button" class="phins-doc-close">Close</button>'
        "</span></nav>\n<script>\n"
        + document_return_script()
        + "\n</script>\n"
    )


def render_phins_document(*, title: str, eyebrow: str, subtitle: str,
                          body_html: str, footer: str = "") -> str:
    """Return a self-contained HTML document. body_html is trusted markup."""
    safe_title = html.escape(title, quote=True)
    safe_eyebrow = html.escape(eyebrow, quote=True)
    safe_subtitle = html.escape(subtitle, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&amp;family=Space+Grotesk:wght@500;600;700&amp;display=swap" rel="stylesheet">
<style>
{document_css()}
</style>
</head>
<body>
{document_return_markup()}<article class="phins-doc">
  <header class="phins-doc-banner">
    <div class="phins-doc-brand">
      <div class="phins-doc-logo">{logo_svg()}</div>
      <div>
        <div class="phins-doc-wordmark">PHINS</div>
        <div class="phins-doc-tagline">{html.escape(TAGLINE)}</div>
      </div>
    </div>
    <div class="phins-doc-kicker">{safe_eyebrow}<span>{safe_subtitle}</span></div>
  </header>
  <div class="phins-doc-gold"></div>
  <div class="phins-doc-body">
{body_html}
  </div>
  <footer class="phins-doc-foot">{footer}</footer>
</article>
</body>
</html>
"""
