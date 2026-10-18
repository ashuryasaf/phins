"""Screenshot and copy deterrent for a document that was shown or sent.

A browser cannot make a screenshot impossible. This is the same barrier the
business-plan protected view already uses: no print, no copy, no context
menu, the common capture shortcuts are swallowed, and the page blurs when
it is not the focused window. A watermark names the recipient.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_JS = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "phins-capture-guard.js"


@lru_cache(maxsize=1)
def _script() -> str:
    return _JS.read_text(encoding="utf-8")


def markup(stamp: str, *, inline: bool = False) -> str:
    """Boot plus the guard. ``inline`` is for blob-opened signed copies."""
    payload = json.dumps({"stamp": str(stamp or "PHINS confidential")[:180]}, ensure_ascii=False)
    # json.dumps leaves "<" alone, so a recipient-supplied stamp could close
    # this script tag. The escapes stay valid inside the JSON string literal.
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    boot = f"<script>window.PHINS_CAPTURE_GUARD={payload};</script>"
    if inline:
        return boot + "<script>\n" + _script() + "\n</script>"
    return boot + '<script src="/phins-capture-guard.js"></script>'


def inject(html: str, stamp: str, *, inline: bool = False) -> str:
    if not html or "phins-capture-guard" in html or "PHINS_CAPTURE_GUARD" in html:
        return html
    block = markup(stamp, inline=inline)
    lower = html.lower()
    idx = lower.rfind("</body>")
    if idx < 0:
        return html + block
    return html[:idx] + block + "\n" + html[idx:]
