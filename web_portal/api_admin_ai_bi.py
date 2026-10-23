"""HTTP surface for the admin AI & BI desk.

Routes:
  POST /api/admin/ai-bi/query
  GET  /api/admin/ai-bi/dashboards
  GET  /api/admin/ai-bi/reports/{id}
  GET  /api/admin/ai-bi/reports/{id}/download?format=json|md|html&lang=en|he

Admin and manager only. The handler reads the live books and stored
simulations. It does not write them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from services.admin_ai_bi_service import (
    AdminAIBiError,
    ALLOWED_ROLES,
    answer_query,
    authorize,
    dashboard_catalog,
    get_report,
    render_html,
    render_markdown,
)

PREFIX = "/api/admin/ai-bi"


def _role(session: Optional[Mapping[str, Any]]) -> str:
    if not session:
        return ""
    return str(session.get("role") or "").strip().lower()


def _guard(session: Optional[Mapping[str, Any]]) -> Optional[Tuple[int, Dict[str, Any]]]:
    if not session:
        return 401, {"error": "Authentication required"}
    if not authorize(_role(session)):
        return 403, {"error": "Admin access required"}
    return None


def _query_value(query_params: Optional[Mapping[str, Any]], key: str, default: str = "") -> str:
    if not query_params:
        return default
    raw = query_params.get(key, default)
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else default
    return str(raw if raw is not None else default)


def _books() -> Dict[str, Any]:
    import web_portal.server as portal

    return {
        "customers": getattr(portal, "CUSTOMERS", {}) or {},
        "policies": getattr(portal, "POLICIES", {}) or {},
        "claims": getattr(portal, "CLAIMS", {}) or {},
        "underwriting": getattr(portal, "UNDERWRITING_APPLICATIONS", {}) or {},
        "billing": getattr(portal, "BILLING", {}) or {},
        "ledger": getattr(portal, "TRANSACTION_LEDGER", {}) or {},
    }


def _simulations() -> List[Mapping[str, Any]]:
    import web_portal.server as portal

    stored = getattr(portal, "ACTUARIAL_SIMULATIONS", {}) or {}
    rows = []
    for sim in stored.values():
        if isinstance(sim, Mapping):
            rows.append(sim)
    return rows


def _download(report: Mapping[str, Any], fmt: str, lang: str) -> Tuple[int, Dict[str, Any]]:
    report_id = str(report.get("report_id") or "report")
    if fmt == "md":
        content = render_markdown(report, lang)
        media = "text/markdown"
        filename = report_id + ".md"
    elif fmt == "html":
        content = render_html(report, lang)
        media = "text/html"
        filename = report_id + ".html"
    elif fmt == "json":
        import json
        content = json.dumps(report, indent=2, default=str)
        media = "application/json"
        filename = report_id + ".json"
    else:
        return 400, {"error": "format must be json, md, or html"}
    integrity = report.get("integrity") or {}
    return 200, {
        "filename": filename,
        "media_type": media,
        "content": content,
        "facts_sha256": integrity.get("facts_sha256"),
        "read_only": True,
    }


def dispatch_get(path: str, session: Optional[Dict], query_params: Optional[Dict]) -> Optional[Tuple[int, Dict]]:
    if path != PREFIX and not path.startswith(PREFIX + "/"):
        return None
    denied = _guard(session)
    if denied:
        return denied
    if path == PREFIX + "/dashboards":
        return 200, {"items": dashboard_catalog(), "roles": sorted(ALLOWED_ROLES)}
    marker = PREFIX + "/reports/"
    if path.startswith(marker):
        rest = path[len(marker):]
        report_id, _, extra = rest.partition("/")
        report = get_report(report_id)
        if report is None:
            return 404, {"error": "Report not found"}
        if extra == "download":
            return _download(
                report,
                _query_value(query_params, "format", "json").lower(),
                _query_value(query_params, "lang", report.get("lang") or "en").lower(),
            )
        if extra:
            return 404, {"error": "Report not found"}
        return 200, report
    return 404, {"error": "Not found"}


def dispatch_post(path: str, session: Optional[Dict], body: Optional[Dict]) -> Optional[Tuple[int, Dict]]:
    if path != PREFIX + "/query":
        return None
    denied = _guard(session)
    if denied:
        return denied
    payload = body if isinstance(body, dict) else {}
    question = str(payload.get("question") or payload.get("query") or "").strip()
    lang = str(payload.get("lang") or "en").strip().lower()
    if lang not in ("en", "he"):
        lang = "en"
    variants = payload.get("variants") if isinstance(payload.get("variants"), dict) else {}
    try:
        report = answer_query(
            question,
            books=_books(),
            simulations=_simulations(),
            variants=variants,
            lang=lang,
            narrate=bool(payload.get("narrate")),
            actor_role=_role(session),
        )
    except AdminAIBiError as exc:
        return exc.status, {"error": str(exc)}
    return 200, report
