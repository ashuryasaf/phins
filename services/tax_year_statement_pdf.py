"""
PHINS tax-year premium statement PDF.

Chrome-only renderer: every figure is copied from the precomputed statement
payload. This module does not re-sum bills, reprice policies, or invent
missing allocations. The statement hash printed on the PDF is the same
sha256 the builder stored on the payload.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.phins_pdf_brand import (
    BRAND_NAME,
    BRAND_TAGLINE,
    PHINS_CYAN,
    PHINS_GOLD,
    PHINS_GOLD_SOFT,
    PHINS_GREY,
    PHINS_NAVY,
    PHINS_WASH,
    page_callbacks,
)

STATEMENT_STANDARD = 'PHINS_CUSTOMER_TAX_YEAR_STATEMENT_V2'
PDF_TITLE = 'Tax-Year Premium Statement'


def statement_filename(tax_year: Any, customer_id: str) -> str:
    year = str(tax_year or 'unknown')
    safe_customer = ''.join(
        ch if ch.isalnum() or ch in ('-', '_') else '_'
        for ch in str(customer_id or 'customer')
    ) or 'customer'
    return f'PHINS_Tax_Year_Statement_{year}_{safe_customer}.pdf'


def _esc(text: Any) -> str:
    return (
        str(text if text is not None else '')
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )


def _money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return '$0.00'
    if number != number or number in (float('inf'), float('-inf')):
        return '$0.00'
    sign = '-$' if number < 0 else '$'
    return sign + f'{abs(number):,.2f}'


def _text(value: Any, fallback: str = '—') -> str:
    text = str(value or '').strip()
    return text if text else fallback


def _pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return '—'
    return f'{number:.2f}%'


def render_tax_year_statement_pdf(report: Dict[str, Any]) -> bytes:
    """Render one branded PDF: unified cover sheet, then one sheet per policy."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    report = report if isinstance(report, dict) else {}
    personal = report.get('personal_details') or {}
    summary = report.get('tax_year_summary') or report.get('premium_summary') or {}
    policies = list(report.get('policies') or [])
    allocation = report.get('allocation_profile') or {}
    balances = report.get('verified_balances') or report.get('savings_usage') or {}
    integrity = report.get('integrity') or {}
    tax_year = report.get('tax_year') or summary.get('tax_year')
    customer_name = _text(personal.get('full_name') or personal.get('customer_id'), 'Customer')
    digest = str(integrity.get('statement_sha256') or '')
    currency = _text(report.get('currency'), 'USD')

    buffer = io.BytesIO()
    pagesize = A4
    usable = pagesize[0] - 32 * mm
    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=26 * mm,
        bottomMargin=18 * mm,
        title=f'{BRAND_NAME} {PDF_TITLE} {tax_year}',
        author=BRAND_NAME,
        subject=digest or STATEMENT_STANDARD,
    )
    styles = getSampleStyleSheet()
    navy = colors.HexColor(PHINS_NAVY)
    gold = colors.HexColor(PHINS_GOLD)
    grey = colors.HexColor(PHINS_GREY)
    wash = colors.HexColor(PHINS_WASH)
    ink = colors.HexColor('#1A202C')

    title_style = ParagraphStyle(
        'TaxStmtTitle', parent=styles['Title'], fontName='Helvetica-Bold',
        fontSize=16, leading=20, textColor=navy, alignment=TA_LEFT, spaceAfter=4,
    )
    h2 = ParagraphStyle(
        'TaxStmtH2', parent=styles['Heading2'], fontName='Helvetica-Bold',
        fontSize=12, leading=15, textColor=navy, alignment=TA_LEFT,
        spaceBefore=10, spaceAfter=4,
    )
    body = ParagraphStyle(
        'TaxStmtBody', parent=styles['BodyText'], fontName='Helvetica',
        fontSize=9, leading=12, textColor=ink, alignment=TA_LEFT,
    )
    meta = ParagraphStyle(
        'TaxStmtMeta', parent=body, fontSize=8, leading=11, textColor=grey,
    )
    cell = ParagraphStyle(
        'TaxStmtCell', parent=body, fontSize=8, leading=11,
    )
    head_cell = ParagraphStyle(
        'TaxStmtHead', parent=cell, fontName='Helvetica-Bold', textColor=colors.white,
    )
    kpi_label = ParagraphStyle(
        'TaxStmtKpiLabel', parent=cell, fontName='Helvetica', fontSize=7,
        textColor=colors.HexColor('#eaf1ff'), alignment=TA_LEFT,
    )
    kpi_value = ParagraphStyle(
        'TaxStmtKpiValue', parent=cell, fontName='Helvetica-Bold', fontSize=12,
        textColor=colors.HexColor('#f7e2a0'), alignment=TA_LEFT,
    )

    def para(text: Any, style=body) -> Paragraph:
        return Paragraph(_esc(text), style)

    def kv_table(rows: Sequence[Sequence[Any]]) -> Table:
        data = [[para(label, cell), para(value, cell)] for label, value in rows]
        table = Table(data, colWidths=[usable * 0.38, usable * 0.62])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), wash),
            ('TEXTCOLOR', (0, 0), (-1, -1), ink),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('BOX', (0, 0), (-1, -1), 0.4, gold),
            ('INNERGRID', (0, 0), (-1, -1), 0.2, colors.HexColor('#d5deee')),
        ]))
        return table

    def data_table(headers: Sequence[str], rows: Sequence[Sequence[Any]], col_widths: Optional[List[float]] = None) -> Table:
        head = [Paragraph(_esc(h), head_cell) for h in headers]
        body_rows = [
            [Paragraph(_esc(value), cell) for value in row]
            for row in rows
        ]
        table = Table([head] + body_rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), navy),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, wash]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('BOX', (0, 0), (-1, -1), 0.4, gold),
            ('LINEBELOW', (0, 0), (-1, 0), 0.6, colors.HexColor(PHINS_GOLD_SOFT)),
            ('INNERGRID', (0, 1), (-1, -1), 0.2, colors.HexColor('#d5deee')),
        ]))
        return table

    story: List[Any] = [
        para(f'Tax Year {tax_year} Premium Statement', title_style),
        para(BRAND_TAGLINE, meta),
        Spacer(1, 4),
        para(
            f'Unified annual statement for {customer_name}. '
            f'One customer record, every policy on its own sheet. Currency {currency}.',
            body,
        ),
        Spacer(1, 8),
    ]

    kpi_items = [
        ('Premium paid', summary.get('paid_premium_total')),
        ('Risk coverage', summary.get('risk_paid_total')),
        ('Savings', summary.get('savings_paid_total')),
        ('Policies', summary.get('policy_count') if summary.get('policy_count') is not None else len(policies)),
    ]
    kpi_cells = []
    for label, value in kpi_items:
        display = _money(value) if label != 'Policies' else str(int(value or 0))
        kpi_cells.append([
            Paragraph(_esc(label), kpi_label),
            Paragraph(_esc(display), kpi_value),
        ])
    kpi = Table([kpi_cells], colWidths=[usable / 4.0] * 4)
    kpi.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), navy),
        ('BOX', (0, 0), (-1, -1), 0.6, gold),
        ('INNERGRID', (0, 0), (-1, -1), 0.3, colors.HexColor(PHINS_CYAN)),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(kpi)
    story.append(Spacer(1, 10))

    address_parts = [
        personal.get('address'),
        personal.get('city'),
        personal.get('state'),
        personal.get('zip'),
    ]
    address = ', '.join(part for part in address_parts if part)
    story.append(para('Customer', h2))
    story.append(kv_table([
        ('Name', customer_name),
        ('Customer ID', _text(personal.get('customer_id'))),
        ('Email', _text(personal.get('email'))),
        ('Phone', _text(personal.get('phone'))),
        ('Address', _text(address)),
        ('Date of birth', _text(personal.get('date_of_birth'))),
        ('Prepared', _text(report.get('generated_at'))),
        ('Bills settled', str(int(summary.get('paid_bill_count') or 0))),
    ]))

    if policies:
        story.append(para('All policies on this statement', h2))
        story.append(data_table(
            ['Policy', 'Type', 'Status', 'Premium paid', 'Risk', 'Savings'],
            [
                [
                    _text(item.get('policy_id')),
                    _text(item.get('type') or item.get('policy_type'), 'policy'),
                    _text(item.get('status')),
                    _money(item.get('paid_premium_total')),
                    _money(item.get('risk_paid_total')),
                    _money(item.get('savings_paid_total')),
                ]
                for item in policies
            ],
            col_widths=[usable * 0.22, usable * 0.16, usable * 0.14, usable * 0.16, usable * 0.16, usable * 0.16],
        ))

    story.append(para('Allocation profile', h2))
    story.append(kv_table([
        ('Risk share', _pct(allocation.get('risk_pct'))),
        ('Savings share', _pct(allocation.get('savings_pct'))),
        ('Wallet of savings', _pct(allocation.get('wallet_pct'))),
        ('Investment of savings', _pct(allocation.get('investment_pct'))),
        ('Algo of savings', _pct(allocation.get('algo_pct'))),
    ]))

    story.append(para('Year-end balances on file', h2))
    story.append(kv_table([
        ('Health wallet', _money(balances.get('wallet_balance'))),
        ('Investment balance', _money(balances.get('investment_balance'))),
        ('Index', _money(balances.get('index_balance'))),
        ('Bonds', _money(balances.get('bonds_balance'))),
        ('Crypto', _money(balances.get('crypto_balance'))),
        ('Verified total savings', _money(balances.get('verified_total_savings'))),
    ]))

    story.append(para('Integrity', h2))
    story.append(para(
        'Figures on every sheet are copied from the same statement payload. '
        'Policy sheets must sum to the unified totals. The hash below is the '
        'sha256 of those canonical numbers.',
        meta,
    ))
    story.append(kv_table([
        ('Statement standard', _text(report.get('statement_standard') or STATEMENT_STANDARD)),
        ('Statement hash', digest or '—'),
        ('Policy sheets match unified', 'Yes' if integrity.get('policies_sum_matches_unified') else 'No'),
        ('Premium = risk + savings', 'Yes' if integrity.get('premium_equals_risk_plus_savings') else 'Review'),
        ('Unallocated residual', _money(integrity.get('residual_unallocated'))),
    ]))

    for item in policies:
        story.append(PageBreak())
        policy_id = _text(item.get('policy_id'), 'Policy')
        story.append(para(f'Policy sheet · {policy_id}', title_style))
        story.append(para(
            f'Tax year {tax_year} detail for one policy on {customer_name}.',
            meta,
        ))
        story.append(Spacer(1, 6))
        story.append(kv_table([
            ('Policy ID', policy_id),
            ('Type', _text(item.get('type') or item.get('policy_type'), 'policy')),
            ('Status', _text(item.get('status'))),
            ('Product', _text(item.get('product_id'))),
            ('Coverage', _money(item.get('coverage_amount'))),
            ('Quoted monthly premium', _money(item.get('monthly_premium'))),
            ('Quoted annual premium', _money(item.get('annual_premium'))),
            ('Billing frequency', _text(item.get('billing_frequency'))),
            ('Start date', _text(item.get('start_date') or item.get('created_date'))),
            ('Premium paid this year', _money(item.get('paid_premium_total'))),
            ('Risk portion', _money(item.get('risk_paid_total'))),
            ('Savings portion', _money(item.get('savings_paid_total'))),
            ('Bills on this sheet', str(int(item.get('paid_bill_count') or 0))),
        ]))
        bills = list(item.get('bills') or [])
        if bills:
            story.append(para('Premium bills included', h2))
            story.append(data_table(
                ['Bill', 'Paid date', 'Billed', 'Paid', 'Status'],
                [
                    [
                        _text(bill.get('id')),
                        _text(str(bill.get('paid_date') or bill.get('created_date') or '')[:10]),
                        _money(bill.get('amount')),
                        _money(bill.get('amount_paid')),
                        _text(bill.get('status')),
                    ]
                    for bill in bills
                ],
                col_widths=[usable * 0.28, usable * 0.18, usable * 0.18, usable * 0.18, usable * 0.18],
            ))
        else:
            story.append(Spacer(1, 8))
            story.append(para('No premium bills settled on this policy in the tax year.', meta))

    on_first, on_later = page_callbacks(
        pagesize,
        title=f'{PDF_TITLE} {tax_year}',
        badge='Customer Statement',
        footer_note=f'{BRAND_NAME} tax-year premium statement · hash {digest[:16] + "…" if len(digest) > 16 else digest or "n/a"}',
    )
    doc.build(story, onFirstPage=on_first, onLaterPages=on_later)
    return buffer.getvalue()
