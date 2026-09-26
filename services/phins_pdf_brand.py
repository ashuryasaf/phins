"""
Unified PHINS PDF chrome for actuarial / research downloads.

Matches the dashboard report bar and the investor/risk-report letterhead:
shield emblem, PHINS wordmark, platform tagline, deep-navy gradient,
gold-to-cyan accent, and gold / navy (#c9a04e / #0e2f63) rules.

Chrome only — callers keep their own figures and narrative.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional, Tuple

# Brand tokens — keep in sync with phins-pdf-brand.js and generate_investor_pdfs.py
PHINS_NAVY = '#0e2f63'
PHINS_NAVY_DEEP = '#060d1f'
PHINS_NAVY_MID = '#123f82'
PHINS_NAVY_TAIL = '#0a1f4a'
PHINS_GOLD = '#c9a04e'
PHINS_GOLD_STRONG = '#f7e2a0'
PHINS_GOLD_SOFT = '#e3bf6f'
PHINS_GOLD_DEEP = '#b8893b'
PHINS_CYAN = '#4fd8ff'
PHINS_INK = '#eaf1ff'
PHINS_GREY = '#5b6b82'
PHINS_WASH = '#eef3fb'

BRAND_NAME = 'PHINS'
BRAND_TAGLINE = 'Personal Health Insurance & Savings · AI-Operated Insurance Platform'
BRAND_TAGLINE_HE = 'פלטפורמת ביטוח מופעלת־AI · ביטוח בריאות אישי וחיסכון'

_STATIC_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'web_portal', 'static'))
HEADER_BAND = 56.0
ACCENT_BAND = 3.6
RUNNING_BAND = 28.0


def logo_png_path() -> Optional[str]:
    png = os.path.join(_STATIC_DIR, 'phins-logo.png')
    return png if os.path.isfile(png) else None


def _hex(value: str):
    from reportlab.lib import colors
    return colors.HexColor(value)


def draw_phins_emblem(canvas, x: float, y: float, size: float) -> None:
    """Draw the PHINS shield (navy fill, gold rim, cyan fin) at bottom-left x,y."""
    scale = size / 120.0
    canvas.saveState()
    canvas.translate(x, y)
    canvas.scale(scale, scale)
    path = canvas.beginPath()
    path.moveTo(60, 114)
    path.lineTo(106, 98)
    path.lineTo(106, 63)
    path.curveTo(106, 32, 86, 12, 60, 4)
    path.curveTo(34, 12, 14, 32, 14, 63)
    path.lineTo(14, 98)
    path.close()
    canvas.setFillColor(_hex(PHINS_NAVY))
    canvas.setStrokeColor(_hex(PHINS_GOLD))
    canvas.setLineWidth(4)
    canvas.setLineJoin(1)
    canvas.drawPath(path, fill=1, stroke=1)
    star = canvas.beginPath()
    star.moveTo(60, 98)
    star.lineTo(62.2, 91.8)
    star.lineTo(68.5, 91.6)
    star.lineTo(63.5, 87.8)
    star.lineTo(65.3, 81.7)
    star.lineTo(60, 85.3)
    star.lineTo(54.7, 81.7)
    star.lineTo(56.5, 87.8)
    star.lineTo(51.5, 91.6)
    star.lineTo(57.8, 91.8)
    star.close()
    canvas.setFillColor(_hex(PHINS_GOLD_STRONG))
    canvas.drawPath(star, fill=1, stroke=0)
    fin = canvas.beginPath()
    fin.moveTo(40, 44)
    fin.curveTo(44.5, 63, 57, 76, 80, 81.5)
    fin.curveTo(72.5, 69.5, 70.5, 59, 73, 46.5)
    fin.curveTo(61.5, 53.5, 49, 51, 40, 44)
    fin.close()
    canvas.setFillColor(_hex(PHINS_CYAN))
    canvas.drawPath(fin, fill=1, stroke=0)
    canvas.restoreState()


def _draw_logo(canvas, x: float, y: float, size: float) -> None:
    logo = logo_png_path()
    if logo:
        canvas.drawImage(logo, x, y, width=size, height=size, mask='auto', preserveAspectRatio=True)
        return
    draw_phins_emblem(canvas, x, y, size)


def _paint_navy_gradient(canvas, x: float, y: float, width: float, height: float) -> None:
    canvas.saveState()
    clip = canvas.beginPath()
    clip.rect(x, y, width, height)
    canvas.clipPath(clip, stroke=0, fill=0)
    try:
        canvas.linearGradient(
            x, y, x + width, y + height,
            [_hex(PHINS_NAVY_DEEP), _hex(PHINS_NAVY), _hex(PHINS_NAVY_MID), _hex(PHINS_NAVY_TAIL)],
            extend=False,
        )
    except Exception:
        canvas.setFillColor(_hex(PHINS_NAVY))
        canvas.rect(x, y, width, height, fill=1, stroke=0)
    canvas.restoreState()


def _paint_accent(canvas, x: float, y: float, width: float, height: float) -> None:
    canvas.saveState()
    clip = canvas.beginPath()
    clip.rect(x, y, width, height)
    canvas.clipPath(clip, stroke=0, fill=0)
    try:
        canvas.linearGradient(
            x, y, x + width, y,
            [_hex(PHINS_GOLD_DEEP), _hex(PHINS_GOLD_STRONG), _hex(PHINS_GOLD_SOFT), _hex(PHINS_CYAN)],
            extend=False,
        )
    except Exception:
        canvas.setFillColor(_hex(PHINS_GOLD))
        canvas.rect(x, y, width, height, fill=1, stroke=0)
    canvas.restoreState()


def _visual(text: str, rtl: bool, bidi_fn: Optional[Callable[[str], str]] = None) -> str:
    value = str(text or '')
    if not rtl or not value:
        return value
    if bidi_fn is not None:
        return bidi_fn(value)
    return value


def _text_width(text: str, font_name: str, size: float) -> float:
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        return float(stringWidth(str(text or ''), font_name, size))
    except Exception:
        return len(str(text or '')) * size * 0.5


def _fit_text(text: str, font_name: str, size: float, max_width: float) -> str:
    """Truncate with an ellipsis so header lines stay inside a portrait A4 bar."""
    value = str(text or '')
    if max_width <= 4 or not value:
        return ''
    if _text_width(value, font_name, size) <= max_width:
        return value
    ellipsis = '…'
    lo, hi = 0, len(value)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        trial = value[:mid].rstrip() + ellipsis
        if _text_width(trial, font_name, size) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    trimmed = value[:lo].rstrip()
    return (trimmed + ellipsis) if trimmed else ellipsis


def draw_report_bar(
    canvas,
    pagesize: Tuple[float, float],
    *,
    title: str,
    rtl: bool = False,
    font: str = 'Helvetica',
    bold: str = 'Helvetica-Bold',
    first_page: bool = True,
    badge: str = 'Research & Audit',
    bidi_fn: Optional[Callable[[str], str]] = None,
) -> None:
    """Dashboard-matching header: gradient bar, emblem, wordmark, gold/cyan accent."""
    width, height = pagesize
    band = HEADER_BAND if first_page else RUNNING_BAND
    top = height - band
    _paint_navy_gradient(canvas, 0, top, width, band)
    _paint_accent(canvas, 0, top - ACCENT_BAND, width, ACCENT_BAND)

    inset = 16
    emblem = 28 if first_page else 14
    emblem_y = top + (band - emblem) / 2.0
    title_text = _visual(title, rtl, bidi_fn)
    tagline = _visual(BRAND_TAGLINE_HE if rtl else BRAND_TAGLINE, rtl, bidi_fn)
    badge_text = _visual(badge, rtl, bidi_fn)

    canvas.saveState()
    if rtl:
        _draw_logo(canvas, width - inset - emblem, emblem_y, emblem)
        text_x = width - inset - emblem - 10
        canvas.setFillColor(_hex(PHINS_GOLD_STRONG))
        canvas.setFont(bold, 15 if first_page else 8)
        canvas.drawRightString(text_x, emblem_y + (16 if first_page else 3), BRAND_NAME)
        name_size = 15 if first_page else 8
        name_w = _text_width(BRAND_NAME, bold, name_size)
        if first_page:
            badge_size = 7
            title_size = 9
            tag_size = 6.6
            title_room = max(24.0, text_x - name_w - 12 - inset)
            badge_room = max(24.0, text_x - name_w - 12 - inset)
            title_draw = _fit_text(title_text, bold, title_size, title_room)
            badge_draw = _fit_text(badge_text, font, badge_size, badge_room)
            badge_w = _text_width(badge_draw, font, badge_size)
            tag_room = max(24.0, text_x - inset - badge_w - 14)
            tag_draw = _fit_text(tagline, font, tag_size, tag_room)
            canvas.setFillColor(_hex(PHINS_INK))
            canvas.setFont(font, tag_size)
            canvas.drawRightString(text_x, emblem_y + 4, tag_draw)
            canvas.setFillColor(_hex(PHINS_INK))
            canvas.setFont(bold, title_size)
            canvas.drawString(inset, emblem_y + 16, title_draw)
            canvas.setFillColor(_hex(PHINS_CYAN))
            canvas.setFont(font, badge_size)
            canvas.drawString(inset, emblem_y + 4, badge_draw)
        else:
            run_size = 7.5
            run_room = max(24.0, (text_x - 52) - inset)
            canvas.setFillColor(_hex(PHINS_INK))
            canvas.setFont(font, run_size)
            canvas.drawRightString(text_x - 52, emblem_y + 3, _fit_text(title_text, font, run_size, run_room))
    else:
        _draw_logo(canvas, inset, emblem_y, emblem)
        text_x = inset + emblem + 10
        name_size = 15 if first_page else 8
        canvas.setFillColor(_hex(PHINS_GOLD_STRONG))
        canvas.setFont(bold, name_size)
        canvas.drawString(text_x, emblem_y + (16 if first_page else 3), BRAND_NAME)
        name_w = _text_width(BRAND_NAME, bold, name_size)
        if first_page:
            badge_size = 7
            title_size = 9
            tag_size = 6.6
            title_room = max(24.0, (width - inset) - (text_x + name_w + 12))
            badge_room = max(24.0, (width - inset) - (text_x + name_w + 12))
            title_draw = _fit_text(title_text, bold, title_size, title_room)
            badge_draw = _fit_text(badge_text, font, badge_size, badge_room)
            badge_w = _text_width(badge_draw, font, badge_size)
            tag_room = max(24.0, (width - inset - badge_w - 14) - text_x)
            tag_draw = _fit_text(tagline, font, tag_size, tag_room)
            canvas.setFillColor(_hex(PHINS_INK))
            canvas.setFont(font, tag_size)
            canvas.drawString(text_x, emblem_y + 4, tag_draw)
            canvas.setFillColor(_hex(PHINS_INK))
            canvas.setFont(bold, title_size)
            canvas.drawRightString(width - inset, emblem_y + 16, title_draw)
            canvas.setFillColor(_hex(PHINS_CYAN))
            canvas.setFont(font, badge_size)
            canvas.drawRightString(width - inset, emblem_y + 4, badge_draw)
        else:
            run_size = 7.5
            run_x = text_x + 52
            run_room = max(24.0, (width - inset) - run_x)
            canvas.setFillColor(_hex(PHINS_INK))
            canvas.setFont(font, run_size)
            canvas.drawString(run_x, emblem_y + 3, _fit_text(title_text, font, run_size, run_room))
    canvas.restoreState()


def draw_report_footer(
    canvas,
    doc,
    pagesize: Tuple[float, float],
    *,
    rtl: bool = False,
    font: str = 'Helvetica',
    note: str = '',
    page_label: str = 'Page',
    bidi_fn: Optional[Callable[[str], str]] = None,
) -> None:
    width, _height = pagesize
    inset = 16
    canvas.saveState()
    canvas.setStrokeColor(_hex(PHINS_GOLD))
    canvas.setLineWidth(0.9)
    canvas.line(inset, 22, width - inset, 22)
    _draw_logo(canvas, inset if not rtl else width - inset - 12, 8, 12)
    canvas.setFillColor(_hex(PHINS_GREY))
    canvas.setFont(font, 7)
    note_text = _visual(note or f'{BRAND_NAME} — Confidential actuarial document', rtl, bidi_fn)
    page_text = _visual(f'{page_label} {doc.page}', rtl, bidi_fn)
    if rtl:
        canvas.drawRightString(width - inset - 16, 11, note_text[:120])
        canvas.drawString(inset, 11, page_text)
    else:
        canvas.drawString(inset + 16, 11, note_text[:120])
        canvas.drawRightString(width - inset, 11, page_text)
    canvas.restoreState()


def page_callbacks(
    pagesize: Tuple[float, float],
    *,
    title: str,
    rtl: bool = False,
    font: str = 'Helvetica',
    bold: str = 'Helvetica-Bold',
    badge: str = 'Research & Audit',
    footer_note: str = '',
    page_label: str = 'Page',
    bidi_fn: Optional[Callable[[str], str]] = None,
) -> Tuple[Any, Any]:
    def on_first(canvas, doc):
        draw_report_bar(
            canvas, pagesize, title=title, rtl=rtl, font=font, bold=bold,
            first_page=True, badge=badge, bidi_fn=bidi_fn,
        )
        draw_report_footer(
            canvas, doc, pagesize, rtl=rtl, font=font,
            note=footer_note, page_label=page_label, bidi_fn=bidi_fn,
        )

    def on_later(canvas, doc):
        draw_report_bar(
            canvas, pagesize, title=title, rtl=rtl, font=font, bold=bold,
            first_page=False, badge=badge, bidi_fn=bidi_fn,
        )
        draw_report_footer(
            canvas, doc, pagesize, rtl=rtl, font=font,
            note=footer_note, page_label=page_label, bidi_fn=bidi_fn,
        )

    return on_first, on_later
