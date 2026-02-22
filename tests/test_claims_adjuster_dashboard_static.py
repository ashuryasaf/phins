from pathlib import Path


def _claims_adjuster_dashboard_html() -> str:
    dashboard_path = (
        Path(__file__).resolve().parents[1]
        / "web_portal"
        / "static"
        / "claims-adjuster-dashboard.html"
    )
    return dashboard_path.read_text(encoding="utf-8")


def test_main_dashboard_script_is_not_terminated_early():
    html = _claims_adjuster_dashboard_html()
    marker = "const token = localStorage.getItem('phins_token');"
    marker_idx = html.find(marker)
    assert marker_idx != -1

    first_script_close_after_marker = html.find("</script>", marker_idx)
    last_script_close = html.rfind("</script>")

    # The main inline script must close only once at the end.
    assert first_script_close_after_marker == last_script_close


def test_dashboard_claims_loader_requests_all_pages():
    html = _claims_adjuster_dashboard_html()
    assert "/api/claims?page=${page}&page_size=${pageSize}" in html


def test_dashboard_does_not_embed_runtime_script_tags_in_html_templates():
    html = _claims_adjuster_dashboard_html()
    assert '<script src="/ui-clarity.js"></script>' not in html
