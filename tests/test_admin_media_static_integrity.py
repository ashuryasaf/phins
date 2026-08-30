import re
from pathlib import Path


ADMIN_MEDIA_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin-media.html"
INDEX_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "index.html"
LOGIN_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "login.html"
REGISTER_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "register.html"


def test_admin_media_uses_authenticated_subtitle_download_helper():
    content = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")

    assert "async function downloadSubtitleTrack(media, latestTrack)" in content
    assert "fetch(latestTrack.download_url" in content
    assert "'Authorization': `Bearer ${token}`" in content
    assert "window.URL.createObjectURL(blob)" in content
    assert "window.open(latestTrack.download_url, '_blank')" not in content
    assert 'href="${latestTrack.download_url}"' not in content


def test_admin_media_preview_subtitle_uses_download_handler():
    content = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")

    preview_link_pattern = re.compile(
        r"downloadLatestSubtitle\('\$\{(?:media\.id|safeId)\}'\)",
        flags=re.S,
    )
    assert preview_link_pattern.search(content)
    assert 'class="link-button"' in content


def test_admin_media_sends_design_settings_on_save():
    content = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")
    assert "hero_background_id:" in content
    assert "promo_banner_id:" in content
    assert "apply_disclosure_video_id:" in content
    assert "apply_disclosure_control_video_id:" in content
    assert "apply_disclosure_version_label:" in content
    assert "promoteApplyDisclosureControl" in content
    assert "Upload the apply disclosure video here" in content
    assert "Upload the cut in the library above first" in content
    assert "designSettings:" in content
    assert "brandSettings:" in content


def test_index_html_applies_design_colors():
    content = INDEX_PATH.read_text(encoding="utf-8")
    assert "applyDesignColors" in content
    assert "primary_color" in content
    assert "accent_color" in content
    assert "--ds-primary" in content


def test_index_html_applies_hero_background():
    content = INDEX_PATH.read_text(encoding="utf-8")
    assert "applyHeroBackground" in content
    assert "hero_background_url" in content


def test_index_html_applies_promo_banner():
    content = INDEX_PATH.read_text(encoding="utf-8")
    assert "applyPromoBanner" in content
    assert "promo_banner_url" in content
    assert "promo-banner" in content


def test_index_html_applies_section_visibility():
    content = INDEX_PATH.read_text(encoding="utf-8")
    assert "applySectionVisibility" in content
    assert "show_video" in content
    assert "show_contact" in content


def test_login_page_applies_branding():
    content = LOGIN_PATH.read_text(encoding="utf-8")
    assert "applyBranding" in content
    assert "/api/design/settings" in content
    assert "primary_color" in content
    assert "hero_background_url" in content


def test_register_page_applies_branding():
    content = REGISTER_PATH.read_text(encoding="utf-8")
    assert "applyBranding" in content
    assert "/api/design/settings" in content
    assert "primary_color" in content
