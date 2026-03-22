from pathlib import Path


ADMIN_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin.html"


def test_admin_dashboard_sends_current_campaign_context_for_video_generation():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "function currentMarketingCampaignRequestContext()" in content
    assert "campaign_payload: latestMarketingCampaignPayload.campaign" in content
    assert "campaign_integrity: latestMarketingCampaignPayload.integrity || {}" in content
    assert "'batch'," in content
    assert "currentMarketingCampaignRequestContext()" in content


def test_admin_dashboard_loads_video_provider_status_diagnostics():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert 'id="mkt-video-provider-status"' in content
    assert "async function loadMarketingVideoProviders()" in content
    assert "fetch('/api/admin/media/video-providers'" in content
    assert "loadLatestMarketingCampaign();" in content
