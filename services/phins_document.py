"""Shared PHINS letterhead for generated HTML documents.

Claim notices, processing records, and risk reports use one emblem, type,
and navy/gold gradient so a downloaded file matches the on-screen document.
"""

from __future__ import annotations

import html
from functools import lru_cache
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
TAGLINE = "Personal Health Insurance & Savings"


@lru_cache(maxsize=1)
def document_css() -> str:
    return (_STATIC / "phins-document.css").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def logo_svg() -> str:
    return (_STATIC / "phins-logo.svg").read_text(encoding="utf-8").strip()


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
<style>
{document_css()}
</style>
</head>
<body>
<article class="phins-doc">
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
