from pathlib import Path


VIDEO_AGENTS_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "video-agents.html"


def test_video_agents_loads_all_stored_campaigns():
    content = VIDEO_AGENTS_PATH.read_text(encoding="utf-8")

    assert "async function loadCampaigns()" in content
    assert "fetchJson('/api/admin/marketing-sales-agent/campaigns')" in content
    assert "function renderCampaignOptions" in content
    assert 'Select a stored campaign...' in content


def test_video_agents_refresh_bootstrap_uses_campaign_list():
    content = VIDEO_AGENTS_PATH.read_text(encoding="utf-8")

    assert "await loadCampaigns();" in content
    assert "document.getElementById('va-campaign-id').value = selectedId;" in content
