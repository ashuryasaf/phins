"""
Mislaka Report Generator
========================
Builds an **affiliation-structured** fact projection (and optional downloadable
PDF) for Mislaka data.

The Mislaka clearinghouse already returns *authoritative* policy rows. The
platform therefore treats every record as a fact and never re-aggregates the
clearinghouse response on top of itself. Statistical reviews, risk scoring and
chart synthesis live in the Assessment Center
(:mod:`services.assessment_center_service`).

This module is responsible for:

1. Normalising the Mislaka response into PHINS' canonical schema so the rest of
   the platform sees the same shape regardless of provider.
2. Decoding every record's raw Mislaka codes into named **affiliations**
   (product / status / provider / interface) via
   :mod:`services.mislaka_affiliations`, so reports are organised A-Z by
   affiliation rather than by opaque numeric codes.
3. Emitting a flat list of affiliation-enriched facts the Assessment Center can
   ingest.
4. Rendering an optional, audit-grade report (text + PDF) that lists the facts
   grouped by affiliation. The renderer never prints derived statistics.

Adjustable reporting: every public builder accepts an optional ``filters``
argument (:class:`services.mislaka_affiliations.ReportFilters`) so callers can
narrow the *real* fact set by policy number, product, status, provider, or a
date window. Filtering only ever removes records - nothing is fabricated.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple, Union

from services.mislaka_affiliations import (
    ReportFilters,
    apply_filters,
    build_affiliation_projection,
    decode_affiliations,
)
from services.mislaka_api_service import MislakaQueryResult

FiltersLike = Union[ReportFilters, Dict[str, Any], None]


def _coerce_filters(filters: FiltersLike) -> ReportFilters:
    if isinstance(filters, ReportFilters):
        return filters
    if isinstance(filters, dict):
        return ReportFilters.from_dict(filters)
    return ReportFilters()


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


def normalize_mislaka_result(
    result: MislakaQueryResult,
    *,
    include_aggregates: bool = False,
    filters: FiltersLike = None,
) -> Dict[str, Any]:
    """Normalize Mislaka API result into PensionDataAgent-like structure.

    Every account is enriched with its decoded ``affiliations`` block (product
    / status / provider / interface) so downstream renderers can organise data
    by named affiliation instead of raw code.

    Aggregate totals (count, balance, coverage, premium) are *not* included by
    default because the Mislaka response is treated as a fact set rather than a
    statistical sample. Pass ``include_aggregates=True`` only when the caller
    needs raw sums for legacy compatibility - downstream analysis should rely
    on the Assessment Center instead.

    ``filters`` narrows the account list to the records matching an adjustable
    report window (policy number, product, status, provider, dates).
    """
    report_filters = _coerce_filters(filters)
    selected_policies = apply_filters(list(result.policies), report_filters)

    accounts: List[Dict[str, Any]] = []
    providers = set()

    total_balance = Decimal("0")
    total_coverage = Decimal("0")
    total_premium = Decimal("0")

    for policy in selected_policies:
        accumulated = _safe_decimal(policy.accumulated_value)
        coverage = _safe_decimal(policy.cover_amount)
        premium = _safe_decimal(policy.premium_monthly)
        mgmt_fee = _safe_decimal(policy.management_fee_percent)
        affiliations = decode_affiliations(policy)

        account = {
            "source": "mislaka_api",
            "policy_id": policy.policy_id,
            "policy_number": policy.policy_number,
            "product_type": policy.product_type,
            "product_type_name": affiliations["product"]["name"],
            "provider": policy.company_name,
            "provider_code": policy.company_code,
            "start_date": policy.start_date,
            "status": policy.status,
            "status_name": affiliations["status"]["name"],
            "total_balance": accumulated,
            "savings_balance": accumulated,
            "coverage_amount": coverage,
            "death_coverage": coverage,
            "monthly_premium": premium,
            "management_fee_savings": mgmt_fee,
            "investment_track": policy.investment_track,
            "beneficiaries": policy.beneficiaries,
            "last_update": policy.last_update,
            "affiliations": affiliations,
        }
        accounts.append(account)

        total_balance += accumulated
        total_coverage += coverage
        total_premium += premium
        if policy.company_name:
            providers.add(policy.company_name)

    client_name = " ".join([result.person.first_name, result.person.last_name]).strip()

    base = {
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
        "filters_applied": report_filters.to_dict(),
        "source_account_count": len(result.policies),
    }

    if include_aggregates:
        base["totals"] = {
            "total_balance": total_balance,
            "total_savings": total_balance,
            "total_severance": Decimal("0"),
            "total_coverage": total_coverage,
            "total_monthly_premium": total_premium,
            "account_count": len(accounts),
            "provider_count": len(providers),
            "providers": list(providers),
            "contributions": {
                "grand_total": total_premium,
            },
        }

    return base


def mislaka_facts(
    result: MislakaQueryResult,
    *,
    filters: FiltersLike = None,
) -> List[Dict[str, Any]]:
    """Convert a Mislaka result into affiliation-enriched fact rows.

    Each row is a self-contained fact: the assessment center is in charge of
    aggregation, the renderer never sums on its own. Each row also carries its
    decoded affiliation labels (product / status / provider) so the Assessment
    Center stores facts that already speak in named affiliations.

    ``filters`` narrows the rows to an adjustable report window.
    """
    report_filters = _coerce_filters(filters)
    selected = apply_filters(list(result.policies), report_filters)

    rows: List[Dict[str, Any]] = []
    for policy in selected:
        affiliations = decode_affiliations(policy)
        rows.append({
            "policy_id": policy.policy_id,
            "policy_number": policy.policy_number,
            "product_type": policy.product_type,
            "company_name": policy.company_name,
            "company_code": policy.company_code,
            "start_date": policy.start_date,
            "status": policy.status,
            "premium_monthly": float(_safe_decimal(policy.premium_monthly)),
            "cover_amount": float(_safe_decimal(policy.cover_amount)),
            "accumulated_value": float(_safe_decimal(policy.accumulated_value)),
            "management_fee_percent": float(_safe_decimal(policy.management_fee_percent)),
            "investment_track": policy.investment_track,
            "beneficiaries": list(policy.beneficiaries or []),
            "last_update": policy.last_update,
            "affiliation_product": affiliations["product"]["name"],
            "affiliation_status": affiliations["status"]["name"],
            "affiliation_provider": affiliations["provider"]["name"],
            "affiliations": affiliations,
        })
    return rows


def link_to_assessment_center(
    result: MislakaQueryResult,
    *,
    customer_id: Optional[str] = None,
    filters: FiltersLike = None,
) -> Dict[str, Any]:
    """Push the Mislaka rows into the Assessment Center as facts.

    Returns the Assessment Center's ingestion summary, which already contains
    the per-fact provenance the dashboards need to render data integrity. The
    rows pushed are affiliation-enriched and honour any adjustable ``filters``.
    """
    from services.assessment_center_service import get_assessment_center

    center = get_assessment_center()
    cust = (customer_id or result.person.id_number or "anonymous").strip() or "anonymous"
    rows = mislaka_facts(result, filters=filters)
    assessment = center.ingest_external_facts(
        customer_id=cust,
        source="mislaka",
        records=rows,
        fact_type="external_policy",
    )
    return assessment.to_dict()


def _format_amount(value: Any) -> str:
    dec = _safe_decimal(value)
    if dec == dec.to_integral_value():
        return f"{int(dec):,}"
    return f"{dec:,.2f}"


def _render_affiliation_text(
    result: MislakaQueryResult,
    projection: Dict[str, Any],
    *,
    include_aggregates: bool,
) -> str:
    """Deterministically render the affiliation-structured report text (A-Z).

    The layout walks the data from A to Z: client header, then policies grouped
    by their named affiliations (provider -> product -> status), then the
    affiliation membership index. No statistics are derived; only the
    clearinghouse facts are listed.
    """
    rows: List[Dict[str, Any]] = projection["rows"]
    client_name = " ".join([result.person.first_name, result.person.last_name]).strip()

    lines: List[str] = []
    lines.append("MISLAKA AFFILIATION REPORT")
    lines.append("=" * 60)
    lines.append(f"Client: {client_name or 'N/A'}")
    lines.append(f"ID Number: {result.person.id_number or 'N/A'}")
    lines.append(f"Request ID: {result.request_id or 'N/A'}")
    lines.append(f"Source records: {projection['source_policy_count']}")
    lines.append(f"Records in report: {projection['policy_count']}")
    if projection.get("filters_active"):
        lines.append("Filters applied:")
        for key, val in sorted(projection.get("filters", {}).items()):
            lines.append(f"  - {key}: {val}")
    lines.append("")

    if not rows:
        lines.append("No records match the selected affiliations / filters.")
        return "\n".join(lines)

    lines.append("POLICIES BY AFFILIATION")
    lines.append("-" * 60)
    for idx, row in enumerate(rows, start=1):
        aff = row["affiliations"]
        lines.append(f"[{idx}] Policy {row.get('policy_number') or row.get('policy_id') or 'N/A'}")
        lines.append(f"    Provider affiliation : {aff['provider']['name']}"
                    + ("" if aff['provider']['decoded'] else "  (code only)"))
        lines.append(f"    Product affiliation  : {aff['product']['name']}"
                    + ("" if aff['product']['decoded'] else "  (code only)"))
        lines.append(f"    Status affiliation   : {aff['status']['name']}"
                    + ("" if aff['status']['decoded'] else "  (code only)"))
        if str(aff['interface']['code']):
            lines.append(f"    Interface affiliation: {aff['interface']['name']}")
        lines.append(f"    Start date           : {row.get('start_date') or 'N/A'}")
        lines.append(f"    Last update          : {row.get('last_update') or 'N/A'}")
        lines.append(f"    Monthly premium      : {_format_amount(row.get('premium_monthly'))}")
        lines.append(f"    Cover amount         : {_format_amount(row.get('cover_amount'))}")
        lines.append(f"    Accumulated value    : {_format_amount(row.get('accumulated_value'))}")
        if row.get("investment_track"):
            lines.append(f"    Investment track     : {row.get('investment_track')}")
        lines.append("")

    lines.append("AFFILIATION INDEX")
    lines.append("-" * 60)
    for dimension, title in (("by_provider", "By provider"),
                            ("by_product", "By product"),
                            ("by_status", "By status")):
        lines.append(f"{title}:")
        for grp in projection["groups"].get(dimension, []):
            lines.append(f"  - {grp['affiliation']}: {grp['policy_count']} policy(ies)")
        lines.append("")

    if include_aggregates:
        total_premium = sum(_safe_decimal(r.get("premium_monthly")) for r in rows)
        total_cover = sum(_safe_decimal(r.get("cover_amount")) for r in rows)
        total_accum = sum(_safe_decimal(r.get("accumulated_value")) for r in rows)
        lines.append("RAW TOTALS (legacy, filtered set)")
        lines.append("-" * 60)
        lines.append(f"  Total monthly premium : {_format_amount(total_premium)}")
        lines.append(f"  Total cover amount    : {_format_amount(total_cover)}")
        lines.append(f"  Total accumulated     : {_format_amount(total_accum)}")
        lines.append("")

    return "\n".join(lines)


def build_mislaka_report_text(
    result: MislakaQueryResult,
    *,
    include_aggregates: bool = False,
    filters: FiltersLike = None,
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Generate the affiliation-structured report text and metadata.

    The report is rebuilt A-Z around named affiliations (provider / product /
    status) decoded from the authoritative Mislaka schema. By default the
    rendered text presents only factual line items; pass
    ``include_aggregates=True`` for legacy callers that still expect raw totals.

    ``filters`` narrows the report to an adjustable window (policy number,
    product, status, provider, date range). The integrity checksum is computed
    over the *filtered* projection so the checksum always matches what the
    report shows.
    """
    report_filters = _coerce_filters(filters)
    projection = build_affiliation_projection(list(result.policies), filters=report_filters)
    data = normalize_mislaka_result(
        result, include_aggregates=include_aggregates, filters=report_filters,
    )
    data["affiliation_projection"] = projection

    report_text = _render_affiliation_text(
        result, projection, include_aggregates=include_aggregates,
    )

    metadata = {
        "request_id": result.request_id,
        "report_generated_at": datetime.utcnow().isoformat() + "Z",
        "policy_count": projection["policy_count"],
        "source_policy_count": projection["source_policy_count"],
        "data_hash": projection["integrity"]["sha256"],
        "data_hash_source": "affiliation_projection",
        "client_id_number": result.person.id_number,
        "filters_applied": report_filters.to_dict(),
        "affiliation_groups": projection["groups"],
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
