#!/usr/bin/env python3
"""
Generate downloadable PDF reports for PHINS investor / pitch documents.
=======================================================================
Converts served investor markdown documents (under
``web_portal/static/investor-docs/`` and the Business Plan at the static root)
into clean, print-ready PDFs alongside their markdown sources, so the pitch
dashboard can offer "⬇ PDF" downloads (e.g. for the Israel pitch, the AI/BI
optimization review, and the executive Business Plan).

Design / data-integrity notes:
- **Deterministic, content-faithful rendering.** PDFs are generated *from* the
  canonical markdown so they cannot drift in content; regenerating reproduces
  the same document. No platform data (policies, claims, ledgers) is read or
  written — this only renders static documentation.
- **No new runtime dependency.** Uses ``reportlab``, already in
  ``requirements.txt``. The PHINS web server does not import this module; it is a
  build/ops script (run manually or in CI) and the resulting PDFs are committed.
  Rendering right-to-left (Hebrew) documents additionally requires the
  build-time-only ``python-bidi`` package (see ``requirements-dev.txt``);
  reportlab's own RTL word wrap is a silent no-op without the proprietary
  ``rlbidi`` package, so this script runs the Unicode bidi algorithm itself.
- Supports a pragmatic markdown subset: ATX headings, paragraphs, bold/inline
  code, bullet and numbered lists, blockquotes, fenced code blocks, and pipe
  tables. Anything unrecognized is rendered as a paragraph, so output is always
  readable even for constructs outside the subset.

Usage:
    python3 scripts/generate_investor_pdfs.py
    python3 scripts/generate_investor_pdfs.py --check   # verify outputs exist
"""

import argparse
import html
import os
import re
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily, stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, Image as RLImage, ListFlowable, ListItem, Paragraph,
    Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle,
)

try:
    # Required only to render right-to-left (Hebrew) documents. reportlab's
    # own ``wordWrap='RTL'`` silently does nothing without the proprietary
    # ``rlbidi`` package, so we run the Unicode bidi algorithm ourselves.
    from bidi.algorithm import get_display as _bidi_get_display
except ImportError:  # pragma: no cover - exercised only on hosts without bidi
    _bidi_get_display = None

STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'web_portal', 'static',
)
# Kept for backwards compatibility / readers that import this constant.
INVESTOR_DOCS_DIR = os.path.join(STATIC_DIR, 'investor-docs')

# (markdown path, output pdf path, document title) — paths are relative to
# ``STATIC_DIR`` so a document can live in the investor-docs library or, like
# the executive Business Plan, directly at the served static root.
DOCUMENTS = [
    ('investor-docs/israel-pitch-executive-summary.md',
     'investor-docs/israel-pitch-executive-summary.pdf',
     'PHINS — Israel (IL) Pitch: Executive Summary'),
    ('investor-docs/ai-bi-optimization-review.md',
     'investor-docs/ai-bi-optimization-review.pdf',
     'PHINS — AI & BI Optimization Review'),
    ('investor-docs/ai-bi-implementation-summary.md',
     'investor-docs/ai-bi-implementation-summary.pdf',
     'PHINS — AI & BI Optimization: Implementation Summary'),
    ('investor-docs/platform-data-architecture.md',
     'investor-docs/platform-data-architecture.pdf',
     'PHINS — Platform Data Architecture'),
    ('investor-docs/health-marketplace-architecture.md',
     'investor-docs/health-marketplace-architecture.pdf',
     'PHINS — Global Health Marketplace Architecture'),
    ('PHINS_Business_Plan_Executive.md',
     'PHINS_Business_Plan_Executive.pdf',
     'PHINS — Business Plan (Executive) 2026–2029'),
    ('investor-docs/israel-regulatory-application-en.md',
     'investor-docs/israel-regulatory-application-en.pdf',
     'PHINS — Regulatory Application Memorandum (Israel) · '
     'Life Insurance with Disability Mechanism (1:4)'),
    ('investor-docs/israel-regulatory-application-he.md',
     'investor-docs/israel-regulatory-application-he.pdf',
     'פינס — תזכיר בקשה רגולטורית (ישראל) · ביטוח חיים עם מנגנון נכות (1:4)'),
]

# Sources rendered right-to-left (Hebrew). RTL documents use a Hebrew-capable
# font, right-aligned paragraph styles with reportlab's RTL word wrap, and
# mirrored table columns so the logical first column sits on the right.
RTL_DOCUMENTS = {
    'investor-docs/israel-regulatory-application-he.md',
}

# Candidate Hebrew-capable fonts (first hit wins). DejaVu Sans covers the
# Hebrew block and ships with most Linux build hosts.
HEBREW_FONT_CANDIDATES = [
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
     '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf',
     '/usr/share/fonts/truetype/noto/NotoSansHebrew-Bold.ttf'),
    ('/usr/share/fonts/truetype/noto/NotoSerifHebrew-Regular.ttf',
     '/usr/share/fonts/truetype/noto/NotoSerifHebrew-Bold.ttf'),
]

# Hebrew letter runs (letters plus intra-run spacing/punctuation) embedded in
# LTR documents. Helvetica has no Hebrew glyphs and reportlab applies no bidi
# outside ``wordWrap='RTL'``, so these runs are reversed to visual order and
# wrapped in the registered Hebrew-capable font.
_HEBREW_RUN = re.compile(
    r'[\u0590-\u05FF](?:[\u0590-\u05FF\u05F3\u05F4 ,·—\-]*[\u0590-\u05FF])?'
)
_HEBREW_FONT = {'name': None}  # populated once a Hebrew font is registered


def _register_hebrew_font() -> str:
    """Register a Hebrew-capable TTF family; return its family name.

    Falls back to Helvetica (Hebrew glyphs missing) if no candidate font is
    installed, so ``--check`` and English-only regeneration keep working on
    hosts without the fonts.
    """
    if _HEBREW_FONT['name']:
        return _HEBREW_FONT['name']
    for regular, bold in HEBREW_FONT_CANDIDATES:
        if os.path.isfile(regular) and os.path.isfile(bold):
            pdfmetrics.registerFont(TTFont('PHINSHebrew', regular))
            pdfmetrics.registerFont(TTFont('PHINSHebrew-Bold', bold))
            registerFontFamily('PHINSHebrew', normal='PHINSHebrew',
                               bold='PHINSHebrew-Bold',
                               italic='PHINSHebrew',
                               boldItalic='PHINSHebrew-Bold')
            _HEBREW_FONT['name'] = 'PHINSHebrew'
            return 'PHINSHebrew'
    print('  ! no Hebrew-capable font found; Hebrew text will use Helvetica')
    _HEBREW_FONT['name'] = 'Helvetica'
    return 'Helvetica'

PHINS_BLUE = colors.HexColor('#0d47a1')
PHINS_BLUE_MID = colors.HexColor('#1565c0')
PHINS_NAVY = colors.HexColor('#0e2f63')     # shield navy from phins-logo.svg
PHINS_GOLD = colors.HexColor('#c9a04e')     # gold rim from phins-logo.svg
PHINS_GREY = colors.HexColor('#5b6b82')
CODE_BG = colors.HexColor('#f3f4f6')
QUOTE_BG = colors.HexColor('#eef3fb')

# Raster of web_portal/static/phins-logo.svg (committed alongside it) used
# for the PDF letterhead and page headers. Rendering falls back gracefully
# when the file is missing so --check / CI never break on the asset.
LOGO_PATH = os.path.join(STATIC_DIR, 'phins-logo.png')
BRAND_NAME = 'PHINS'
BRAND_TAGLINE = 'Personal Health Insurance & Savings · AI-Operated Insurance Platform'
BRAND_TAGLINE_HE = 'פלטפורמת ביטוח מופעלת-AI · ביטוח בריאות אישי וחיסכון'


def _styles():
    base = getSampleStyleSheet()
    styles = {
        'title': ParagraphStyle('PhinsTitle', parent=base['Title'], fontSize=18.5,
                                 textColor=PHINS_NAVY, spaceAfter=12, leading=23,
                                 alignment=TA_LEFT),
        'h1': ParagraphStyle('PhinsH1', parent=base['Heading1'], fontSize=15,
                              textColor=PHINS_NAVY, spaceBefore=14, spaceAfter=6, leading=18),
        'h2': ParagraphStyle('PhinsH2', parent=base['Heading2'], fontSize=12.5,
                              textColor=PHINS_BLUE_MID, spaceBefore=12, spaceAfter=5, leading=15),
        'h3': ParagraphStyle('PhinsH3', parent=base['Heading3'], fontSize=11,
                              textColor=PHINS_BLUE_MID, spaceBefore=10, spaceAfter=4, leading=14),
        'body': ParagraphStyle('PhinsBody', parent=base['BodyText'], fontSize=9.5,
                               leading=14, spaceAfter=6, alignment=TA_LEFT),
        'bullet': ParagraphStyle('PhinsBullet', parent=base['BodyText'], fontSize=9.5,
                                 leading=13, spaceAfter=2),
        'quote': ParagraphStyle('PhinsQuote', parent=base['BodyText'], fontSize=9.5,
                                leading=14, leftIndent=10, textColor=colors.HexColor('#33425a'),
                                backColor=QUOTE_BG, borderPadding=6, spaceAfter=6,
                                borderColor=PHINS_GOLD, borderWidth=0),
        'code': ParagraphStyle('PhinsCode', parent=base['Code'], fontSize=8,
                               leading=10.5, backColor=CODE_BG, borderPadding=6,
                               textColor=colors.HexColor('#1a202c')),
        'cell': ParagraphStyle('PhinsCell', parent=base['BodyText'], fontSize=8,
                               leading=10.5),
        'cellhdr': ParagraphStyle('PhinsCellHdr', parent=base['BodyText'], fontSize=8,
                                  leading=10.5, textColor=colors.white),
    }
    styles['_rtl'] = False
    return styles


def _rtl_styles():
    """Right-to-left (Hebrew) variants of the document styles.

    Every text style is right-aligned and uses a Hebrew-capable font family.
    NOTE: reportlab's ``wordWrap='RTL'`` is intentionally NOT used — without
    the proprietary ``rlbidi`` package it is a silent no-op, which renders
    Hebrew mirrored (left-to-right). Instead, RTL text is line-broken
    manually and each line is reordered to visual order with ``python-bidi``
    (see :func:`_rtl_paragraph`).
    """
    font = _register_hebrew_font()
    bold = font + '-Bold' if font == 'PHINSHebrew' else 'Helvetica-Bold'
    styles = _styles()
    rtl = {}
    for key, style in styles.items():
        if key == '_rtl':
            continue
        if key == 'code':
            # Formulas / code stay LTR but adopt a size-compatible look.
            rtl[key] = style
            continue
        clone = ParagraphStyle(style.name + 'RTL', parent=style,
                               alignment=TA_RIGHT,
                               fontName=bold if key in ('title', 'h1', 'h2', 'h3', 'cellhdr') else font)
        if key == 'quote':
            # Mirror the blockquote inset: indent from the right margin.
            clone.leftIndent, clone.rightIndent = 0, 10
        rtl[key] = clone
    rtl['_rtl'] = True
    return rtl


# Usable frame width shared by the document template in :func:`generate_one`
# (A4 minus the 2cm left/right margins). RTL text is line-broken manually
# against this width so each visual line can be bidi-reordered as a unit.
FRAME_WIDTH = A4[0] - 4 * cm


def _bidi_line(line: str) -> str:
    """Reorder one logical RTL line to visual order (Unicode bidi)."""
    if _bidi_get_display is None:
        raise RuntimeError(
            'python-bidi is required to render right-to-left documents: '
            'pip install python-bidi'
        )
    return _bidi_get_display(line, base_dir='R')


def _rtl_break_lines(text: str, font: str, size: float, max_width: float):
    """Greedy word wrap of logical text against ``max_width``.

    Returns the logical lines; callers bidi-reorder each line to visual
    order. Wrapping must happen *before* the bidi pass — otherwise reportlab
    would wrap the visual string and the wrapped lines would read bottom-up.
    """
    words = text.split()
    lines, current = [], ''
    for word in words:
        trial = f'{current} {word}'.strip()
        if not current or stringWidth(trial, font, size) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ['']


def _rtl_paragraph(text: str, style, max_width: float) -> Paragraph:
    """Build a right-aligned Paragraph with per-line bidi-reordered text."""
    logical = _rtl_break_lines(text, style.fontName, style.fontSize,
                               max(1.0, max_width))
    visual = [html.escape(_bidi_line(line)) for line in logical]
    return Paragraph('<br/>'.join(visual), style)


def _rtl_width_for(styles, key: str) -> float:
    """Usable width for a top-level RTL flowable of the given style key."""
    style = styles[key]
    pad = 2.0  # safety so measured lines never re-wrap inside reportlab
    width = FRAME_WIDTH - style.leftIndent - style.rightIndent - pad
    border = getattr(style, 'borderPadding', 0) or 0
    return width - 2 * border


def _wrap_hebrew_runs(text: str) -> str:
    """Render Hebrew runs inside LTR text in visual order with a Hebrew font."""
    if _HEBREW_FONT['name'] != 'PHINSHebrew':
        return text

    def repl(match):
        run = match.group(0)
        # Reuse the fail-closed bidi reorder so embedded Hebrew never renders
        # in the wrong visual order: without python-bidi this raises rather
        # than emitting a naively reversed (and subtly incorrect) run.
        visual = _bidi_line(run)
        return f'<font face="PHINSHebrew">{visual}</font>'

    return _HEBREW_RUN.sub(repl, text)


def _inline(text: str) -> str:
    """Convert a small markdown inline subset to reportlab mini-HTML, safely."""
    # Extract code spans first so their contents aren't escaped twice.
    code_spans = []

    def _stash(m):
        code_spans.append(m.group(1))
        return f"\x00CODE{len(code_spans) - 1}\x00"

    text = re.sub(r'`([^`]+)`', _stash, text)
    text = html.escape(text)
    # Bold then italics (order matters); links -> text (url).
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__([^_]+)__', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)
    text = _wrap_hebrew_runs(text)
    for i, span in enumerate(code_spans):
        text = text.replace(
            f"\x00CODE{i}\x00",
            f'<font face="Courier">{html.escape(span)}</font>',
        )
    return text


def _rtl_plain(text: str) -> str:
    """Markdown inline subset -> plain (unescaped) text for RTL paragraphs.

    Inline ``<b>``/``<i>``/``<font>`` tags would split a Hebrew sentence
    into fragments that reassemble in the wrong visual order, so RTL
    documents drop inline emphasis (headings and table headers keep their
    bold font via styles) and render each paragraph as a single fragment.
    Escaping happens per visual line inside :func:`_rtl_paragraph`.
    """
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)
    return text


def _paragraph_for(styles, key: str, text: str, max_width=None) -> Paragraph:
    """Build a Paragraph in the document's direction for a markdown snippet."""
    if styles.get('_rtl'):
        width = _rtl_width_for(styles, key) if max_width is None else max_width
        return _rtl_paragraph(_rtl_plain(text), styles[key], width)
    return Paragraph(_inline(text), styles[key])


def _flush_list(items, ordered, styles, story):
    if not items:
        return
    if styles.get('_rtl'):
        # ListFlowable anchors bullets on the left; for RTL documents render
        # items as right-aligned paragraphs so the marker sits on the right.
        for idx, item in enumerate(items, start=1):
            prefix = f"{idx}. " if ordered else "\u2022 "
            story.append(_paragraph_for(styles, 'bullet', prefix + item))
        story.append(Spacer(1, 4))
        return
    flow = [
        ListItem(Paragraph(_inline(it), styles['bullet']), leftIndent=12)
        for it in items
    ]
    story.append(ListFlowable(
        flow,
        bulletType='1' if ordered else 'bullet',
        start='1' if ordered else None,
        leftIndent=14,
    ))
    story.append(Spacer(1, 4))


def _rtl_col_widths(rows, styles):
    """Column widths for an RTL table (reportlab can't autosize the
    pre-wrapped bidi Paragraphs, so measure the natural text widths and
    scale to the frame if needed)."""
    ncols = max(len(r) for r in rows)
    pad = 10.0  # LEFT+RIGHT cell padding below
    naturals = []
    for c in range(ncols):
        width = 0.0
        for ri, row in enumerate(rows):
            if c < len(row):
                st = styles['cellhdr'] if ri == 0 else styles['cell']
                width = max(width, stringWidth(_rtl_plain(row[c]),
                                               st.fontName, st.fontSize))
        naturals.append(width + pad + 4)
    total = sum(naturals)
    avail = FRAME_WIDTH
    if total <= avail:
        return naturals
    return [max(46.0, avail * w / total) for w in naturals]


def _table(rows, styles, story):
    if not rows:
        return
    header, body = rows[0], rows[1:]
    rtl = styles.get('_rtl', False)
    if rtl:
        # Mirror columns so the logical first column reads from the right,
        # then pre-wrap every cell against its column width and reorder each
        # wrapped line to visual order.
        header = list(reversed(header))
        mirrored = [header]
        for r in body:
            r = (r + [''] * len(header))[:len(header)]
            mirrored.append(list(reversed(r)))
        widths = _rtl_col_widths(mirrored, styles)
        data = []
        for ri, row in enumerate(mirrored):
            key = 'cellhdr' if ri == 0 else 'cell'
            data.append([
                _paragraph_for(styles, key, cell, max_width=widths[ci] - 11)
                for ci, cell in enumerate(row)
            ])
        tbl = Table(data, colWidths=widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), PHINS_BLUE_MID),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 8))
        return
    data = [[Paragraph(_inline(c), styles['cellhdr']) for c in header]]
    for r in body:
        # Pad/truncate to header width.
        r = (r + [''] * len(header))[:len(header)]
        data.append([Paragraph(_inline(c), styles['cell']) for c in r])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PHINS_BLUE_MID),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))


def _parse_table_row(line: str):
    cells = [c.strip() for c in line.strip().strip('|').split('|')]
    return cells


def markdown_to_story(md_text: str, title: str, styles):
    if styles.get('_rtl'):
        story = [_paragraph_for(styles, 'title', title), Spacer(1, 6)]
    else:
        story = [Paragraph(html.escape(title), styles['title']), Spacer(1, 6)]
    lines = md_text.splitlines()
    i = 0
    list_items: list = []
    list_ordered = False
    seen_level1 = False

    def flush_list():
        nonlocal list_items, list_ordered
        _flush_list(list_items, list_ordered, styles, story)
        list_items = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith('```'):
            flush_list()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith('```'):
                buf.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            story.append(Preformatted('\n'.join(buf) or ' ', styles['code']))
            story.append(Spacer(1, 6))
            continue

        # Table (header line followed by a separator of dashes)
        if '|' in stripped and i + 1 < len(lines) and re.match(
            r'^\s*\|?[\s:|-]+\|[\s:|-]+$', lines[i + 1]
        ):
            flush_list()
            rows = [_parse_table_row(stripped)]
            i += 2  # skip header + separator
            while i < len(lines) and '|' in lines[i] and lines[i].strip():
                rows.append(_parse_table_row(lines[i]))
                i += 1
            _table(rows, styles, story)
            continue

        if not stripped:
            flush_list()
            i += 1
            continue

        # Headings
        m = re.match(r'^(#{1,6})\s+(.*)$', stripped)
        if m:
            flush_list()
            level = len(m.group(1))
            if level == 1 and not seen_level1:
                seen_level1 = True
                # The document title flowable already shows this; skip the
                # markdown's own top heading when it repeats the title.
                plain = _rtl_plain(m.group(2)).strip()
                if plain and (plain in title or title in plain):
                    i += 1
                    continue
            key = 'h1' if level <= 1 else ('h2' if level == 2 else 'h3')
            story.append(_paragraph_for(styles, key, m.group(2)))
            i += 1
            continue

        # Horizontal rule
        if re.match(r'^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$', stripped):
            flush_list()
            story.append(Spacer(1, 6))
            i += 1
            continue

        # Blockquote
        if stripped.startswith('>'):
            flush_list()
            quote = re.sub(r'^>\s?', '', stripped)
            story.append(_paragraph_for(styles, 'quote', quote))
            i += 1
            continue

        # Bullet list
        mb = re.match(r'^[-*+]\s+(.*)$', stripped)
        if mb:
            if list_items and list_ordered:
                flush_list()
            list_ordered = False
            list_items.append(mb.group(1))
            i += 1
            continue

        # Numbered list
        mn = re.match(r'^\d+[.)]\s+(.*)$', stripped)
        if mn:
            if list_items and not list_ordered:
                flush_list()
            list_ordered = True
            list_items.append(mn.group(1))
            i += 1
            continue

        # Paragraph
        flush_list()
        story.append(_paragraph_for(styles, 'body', stripped))
        i += 1

    flush_list()
    return story


def _masthead(styles) -> list:
    """Branded letterhead flowables: shield logo, wordmark, tagline, rules.

    Direction-aware: the emblem and wordmark sit on the left for LTR
    documents and on the right for RTL (Hebrew) documents. Falls back to a
    text-only wordmark when the committed logo raster is unavailable.
    """
    rtl = styles.get('_rtl', False)
    # The wordmark itself is Latin ("PHINS") in both directions.
    wordmark = ParagraphStyle('PhinsWordmark', fontName='Helvetica-Bold',
                              fontSize=21, leading=23, textColor=PHINS_NAVY,
                              alignment=TA_RIGHT if rtl else TA_LEFT)
    tagline = ParagraphStyle('PhinsTagline', fontName='Helvetica', fontSize=6.8,
                             leading=9, textColor=PHINS_GREY,
                             alignment=TA_RIGHT if rtl else TA_LEFT)
    if rtl:
        tagline.fontName = _HEBREW_FONT['name'] if _HEBREW_FONT['name'] else 'Helvetica'
        tagline_text = html.escape(_bidi_line(BRAND_TAGLINE_HE))
    else:
        tagline_text = html.escape(BRAND_TAGLINE)

    text_block = [Paragraph(BRAND_NAME, wordmark), Paragraph(tagline_text, tagline)]
    if os.path.isfile(LOGO_PATH):
        logo = RLImage(LOGO_PATH, width=42, height=42)
        cells = [[text_block, logo]] if rtl else [[logo, text_block]]
        widths = [FRAME_WIDTH - 52, 52] if rtl else [52, FRAME_WIDTH - 52]
        head = Table(cells, colWidths=widths)
        head.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        flowables = [head]
    else:
        flowables = list(text_block)
    flowables += [
        Spacer(1, 8),
        HRFlowable(width='100%', thickness=2.2, color=PHINS_GOLD,
                   spaceBefore=0, spaceAfter=1.6, lineCap='butt'),
        HRFlowable(width='100%', thickness=0.8, color=PHINS_NAVY,
                   spaceBefore=0, spaceAfter=14, lineCap='butt'),
    ]
    return flowables


def _truncate_to_width(text: str, font: str, size: float, max_width: float) -> str:
    if stringWidth(text, font, size) <= max_width:
        return text
    ell = '…'
    while text and stringWidth(text + ell, font, size) > max_width:
        text = text[:-1]
    return (text + ell) if text else ell


def _page_decorations(title: str, rtl: bool):
    """Build (onFirstPage, onLaterPages) canvas callbacks.

    Every page gets a branded footer (hairline rule, confidentiality note,
    page number). Continuation pages additionally get a slim running header
    with the shield emblem and the document title, mirrored for RTL.
    """
    left_x, right_x = 2 * cm, A4[0] - 2 * cm
    has_logo = os.path.isfile(LOGO_PATH)
    hebrew_font = _HEBREW_FONT['name'] if _HEBREW_FONT['name'] else 'Helvetica'

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(PHINS_GOLD)
        canvas.setLineWidth(0.9)
        canvas.line(left_x, 1.45 * cm, right_x, 1.45 * cm)
        canvas.setFont('Helvetica', 6.8)
        canvas.setFillColor(PHINS_GREY)
        note = ('PHINS — Confidential investor document · '
                'generated from canonical markdown')
        if has_logo:
            canvas.drawImage(LOGO_PATH, left_x, 0.92 * cm, width=11, height=11,
                             mask='auto', preserveAspectRatio=True)
            canvas.drawString(left_x + 15, 1.02 * cm, note)
        else:
            canvas.drawString(left_x, 1.02 * cm, note)
        canvas.drawRightString(right_x, 1.02 * cm, f"Page {doc.page}")
        canvas.restoreState()

    def _running_header(canvas):
        canvas.saveState()
        y = A4[1] - 1.05 * cm
        canvas.setFont('Helvetica-Bold', 7.5)
        canvas.setFillColor(PHINS_NAVY)
        max_w = FRAME_WIDTH - 60
        if rtl:
            visual_title = _truncate_to_width(title, hebrew_font, 7.5, max_w)
            visual_title = _bidi_line(visual_title)
            canvas.setFont(hebrew_font, 7.5)
            if has_logo:
                canvas.drawImage(LOGO_PATH, right_x - 13, y - 3.5, width=13,
                                 height=13, mask='auto', preserveAspectRatio=True)
                canvas.drawRightString(right_x - 17, y, visual_title)
            else:
                canvas.drawRightString(right_x, y, visual_title)
        else:
            text = _truncate_to_width(title, 'Helvetica-Bold', 7.5, max_w)
            if has_logo:
                canvas.drawImage(LOGO_PATH, left_x, y - 3.5, width=13, height=13,
                                 mask='auto', preserveAspectRatio=True)
                canvas.drawString(left_x + 17, y, text)
            else:
                canvas.drawString(left_x, y, text)
        canvas.setStrokeColor(PHINS_GOLD)
        canvas.setLineWidth(0.9)
        canvas.line(left_x, y - 7, right_x, y - 7)
        canvas.restoreState()

    def on_first(canvas, doc):
        _footer(canvas, doc)

    def on_later(canvas, doc):
        _running_header(canvas)
        _footer(canvas, doc)

    return on_first, on_later


def generate_one(md_path: str, pdf_path: str, title: str, styles) -> None:
    with open(md_path, 'r', encoding='utf-8') as fh:
        md_text = fh.read()
    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=1.9 * cm, bottomMargin=2.0 * cm,
        title=title, author='PHINS',
    )
    story = _masthead(styles) + markdown_to_story(md_text, title, styles)
    on_first, on_later = _page_decorations(title, styles.get('_rtl', False))
    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)


def _source_has_hebrew(md_path: str) -> bool:
    """True when a markdown source embeds Hebrew text needing build-time bidi."""
    with open(md_path, 'r', encoding='utf-8') as fh:
        return _HEBREW_RUN.search(fh.read()) is not None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Generate investor PDF reports')
    parser.add_argument('--check', action='store_true',
                        help='only verify that expected PDFs exist')
    args = parser.parse_args(argv)

    if args.check:
        missing = [
            pdf for _, pdf, _ in DOCUMENTS
            if not os.path.isfile(os.path.join(STATIC_DIR, pdf))
        ]
        if missing:
            print('Missing PDFs:', ', '.join(missing))
            return 1
        print('All investor PDFs present.')
        return 0

    have_hebrew_font = _register_hebrew_font() == 'PHINSHebrew'
    can_render_rtl = have_hebrew_font and _bidi_get_display is not None
    styles = _styles()
    rtl_styles = None
    generated = []
    skipped_rtl = []
    for md_name, pdf_name, title in DOCUMENTS:
        md_path = os.path.join(STATIC_DIR, md_name)
        pdf_path = os.path.join(STATIC_DIR, pdf_name)
        if not os.path.isfile(md_path):
            print(f"  ! skip (source missing): {md_name}")
            continue
        if md_name in RTL_DOCUMENTS:
            if not can_render_rtl:
                # Regenerating without a Hebrew font would overwrite a good
                # Hebrew PDF with missing-glyph output; without python-bidi
                # the build would crash mid-write and could truncate it.
                # Leave the existing file untouched and fail so the bad
                # regen can't ship silently.
                reason = ('no Hebrew font' if not have_hebrew_font
                          else 'python-bidi not installed')
                print(f"  ! skip ({reason}): {pdf_name}")
                skipped_rtl.append(pdf_name)
                continue
            if rtl_styles is None:
                rtl_styles = _rtl_styles()
            generate_one(md_path, pdf_path, title, rtl_styles)
        else:
            # LTR sources can still embed Hebrew runs (e.g. authority names),
            # which _wrap_hebrew_runs bidi-reorders via the Hebrew font. When
            # that font is registered but python-bidi is missing, _bidi_line
            # would crash mid-build; skip (fail-closed) so English regen fails
            # cleanly instead of aborting after other PDFs were rewritten.
            if (have_hebrew_font and _bidi_get_display is None
                    and _source_has_hebrew(md_path)):
                print(f"  ! skip (python-bidi not installed): {pdf_name}")
                skipped_rtl.append(pdf_name)
                continue
            generate_one(md_path, pdf_path, title, styles)
        size_kb = os.path.getsize(pdf_path) / 1024
        generated.append(pdf_name)
        print(f"  ✓ {pdf_name} ({size_kb:.0f} KB)")
    print(f"Generated {len(generated)} investor PDF(s) under {STATIC_DIR}")
    if skipped_rtl:
        print('  ! RTL rendering unavailable (needs a Hebrew-capable font and '
              'python-bidi); skipped: ' + ', '.join(skipped_rtl))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
