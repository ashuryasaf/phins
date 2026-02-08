"""
Mislaka Report Generator
========================
Builds a downloadable report (PDF/text) for Mislaka data.

This module normalizes Mislaka API data into the PensionDataAgent schema,
generates the professional report text, and renders it to PDF.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from services.mislaka_api_service import MislakaQueryResult
from services.pension_data_agent import get_pension_agent


def _safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, str):
            cleaned = (
                value.replace(",", "")
                .replace("₪", "")
                .replace("ש\"ח", "")
                .replace("$", "")
                .replace("€", "")
                .strip()
            )
            if cleaned == "":
                return default
            return Decimal(cleaned)
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _format_iso(ts: Optional[str]) -> str:
    if not ts:
        return ""
    return ts


def _compute_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _register_fonts() -> Tuple[str, str, str]:
    try:
        from reportlab.pdfbase import pdfmetrics  # type: ignore
        from reportlab.pdfbase.ttfonts import TTFont  # type: ignore
    except Exception:
        return "Helvetica", "Courier", "Helvetica-Bold"

    base_font = "Helvetica"
    mono_font = "Courier"
    bold_font = "Helvetica-Bold"

    font_candidates = {
        "DejaVuSans": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSansMono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "DejaVuSans-Bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    }

    for name, path in font_candidates.items():
        if os.path.exists(path):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path))

    if "DejaVuSans" in pdfmetrics.getRegisteredFontNames():
        base_font = "DejaVuSans"
    if "DejaVuSansMono" in pdfmetrics.getRegisteredFontNames():
        mono_font = "DejaVuSansMono"
    if "DejaVuSans-Bold" in pdfmetrics.getRegisteredFontNames():
        bold_font = "DejaVuSans-Bold"

    return base_font, mono_font, bold_font


def normalize_mislaka_result(result: MislakaQueryResult) -> Dict[str, Any]:
    """Normalize Mislaka API result into PensionDataAgent-like structure."""
    accounts: List[Dict[str, Any]] = []
    providers = set()

    total_balance = Decimal("0")
    total_coverage = Decimal("0")
    total_premium = Decimal("0")

    for policy in result.policies:
        accumulated = _safe_decimal(policy.accumulated_value)
        coverage = _safe_decimal(policy.cover_amount)
        premium = _safe_decimal(policy.premium_monthly)
        mgmt_fee = _safe_decimal(policy.management_fee_percent)

        account = {
            "source": "mislaka_api",
            "policy_id": policy.policy_id,
            "policy_number": policy.policy_number,
            "product_type": policy.product_type,
            "product_type_name": policy.product_type,
            "provider": policy.company_name,
            "provider_code": policy.company_code,
            "start_date": policy.start_date,
            "status": policy.status,
            "total_balance": accumulated,
            "savings_balance": accumulated,
            "coverage_amount": coverage,
            "death_coverage": coverage,
            "monthly_premium": premium,
            "management_fee_savings": mgmt_fee,
            "investment_track": policy.investment_track,
            "beneficiaries": policy.beneficiaries,
            "last_update": policy.last_update,
        }
        accounts.append(account)

        total_balance += accumulated
        total_coverage += coverage
        total_premium += premium
        if policy.company_name:
            providers.add(policy.company_name)

    client_name = " ".join([result.person.first_name, result.person.last_name]).strip()
    totals = {
        "total_balance": total_balance,
        "total_savings": total_balance,
        "total_severance": Decimal("0"),
        "total_coverage": total_coverage,
        "total_monthly_premium": total_premium,
        "account_count": len(accounts),
        "provider_count": len(providers),
        "providers": list(providers),
        "contributions": {
            "grand_total": total_premium
        },
    }

    return {
        "header": {
            "source": "Mislaka API",
            "request_id": result.request_id,
            "report_date": _format_iso(result.timestamp),
        },
        "client": {
            "full_name": client_name,
            "first_name": result.person.first_name,
            "last_name": result.person.last_name,
            "id_number": result.person.id_number,
        },
        "accounts": accounts,
        "contributions": [],
        "severance": [],
        "employers": [],
        "totals": totals,
    }


def build_mislaka_report_text(result: MislakaQueryResult) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Generate the report text and metadata from a Mislaka result."""
    data = normalize_mislaka_result(result)
    agent = get_pension_agent()
    report_text = agent.generate_report_text(data)

    if result.raw_response:
        hash_payload = result.raw_response
        hash_source = "raw_response"
    else:
        hash_payload = {
            "request_id": result.request_id,
            "timestamp": result.timestamp,
            "person": {
                "id_number": result.person.id_number,
                "first_name": result.person.first_name,
                "last_name": result.person.last_name,
            },
            "policies": [vars(p) for p in result.policies],
        }
        hash_source = "normalized"

    metadata = {
        "request_id": result.request_id,
        "report_generated_at": datetime.utcnow().isoformat() + "Z",
        "policy_count": len(result.policies),
        "data_hash": _compute_hash(hash_payload),
        "data_hash_source": hash_source,
        "client_id_number": result.person.id_number,
    }

    return report_text, metadata, data


def render_mislaka_report_pdf(report_text: str, metadata: Dict[str, Any], title: str = "Mislaka Report") -> bytes:
    """Render report text as PDF bytes."""
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # type: ignore
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted  # type: ignore
        from reportlab.lib.units import mm  # type: ignore
    except Exception as exc:  # pragma: no cover - handled by caller
        raise ImportError(
            "reportlab is required to generate PDFs. Install with: `python -m pip install reportlab`"
        ) from exc

    base_font, mono_font, bold_font = _register_fonts()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "MislakaTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=16,
        leading=18,
        alignment=1,
    )
    meta_style = ParagraphStyle(
        "MislakaMeta",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=9,
        leading=11,
    )
    mono_style = ParagraphStyle(
        "MislakaMono",
        parent=styles["Normal"],
        fontName=mono_font,
        fontSize=8,
        leading=9,
    )

    story = []
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Request ID: {metadata.get('request_id', 'N/A')}", meta_style))
    story.append(Paragraph(f"Generated: {metadata.get('report_generated_at', '')}", meta_style))
    story.append(Paragraph(f"Policies: {metadata.get('policy_count', 0)}", meta_style))
    story.append(Paragraph(f"Checksum (SHA-256): {metadata.get('data_hash', '')}", meta_style))
    story.append(Spacer(1, 12))
    story.append(Preformatted(report_text, mono_style))

    def _draw_footer(canvas, doc_instance) -> None:
        canvas.saveState()
        width, _ = A4
        footer_hash = metadata.get("data_hash", "")[:16]
        footer_text = f"Checksum: {footer_hash}... | Page {getattr(doc_instance, 'page', 1)}"
        canvas.setFont(base_font, 7)
        canvas.drawRightString(width - (20 * mm), 10 * mm, footer_text)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
