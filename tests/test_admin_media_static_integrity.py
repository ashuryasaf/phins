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
    for token in (
        "hero_video_id",
        "hero_background_id",
        "video_poster_id",
        "promo_banner_id",
        "apply_disclosure_video_id",
        "apply_disclosure_control_video_id",
        "apply_chat_disclaimer_video_id",
        "claims_chat_disclaimer_video_id",
        "apply_disclosure_version_label",
        "function persistAssignments",
        "function confirmUseAllocation",
        "Save Changes",
        "promoteApplyDisclosureControl",
        "Upload the apply disclosure video here",
        "Upload the cut in the library above first",
        "designSettings:",
        "brandSettings:",
    ):
        assert token in content, token


def test_admin_media_keeps_a_url_only_landing_hero_on_save():
    content = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")

    assert "function keepsUrlOnlyLanding(" in content
    assert "legacyHeroVideoUrl = settings.hero_video_id ? '' : (settings.video_url || '')" in content
    assert "legacyVideoPosterUrl = settings.video_poster_id ? '' : (settings.video_poster || '')" in content
    assert "if (keepsUrlOnlyLanding(slot.key)) return;" in content
    assert "placementTouched[type] = true" in content


def test_chat_welcome_screens_mount_assigned_disclaimer():
    root = ADMIN_MEDIA_PATH.parents[0]
    apply_chat = (root / "apply-chat.html").read_text(encoding="utf-8")
    claims_chat = (root / "claims-chat.html").read_text(encoding="utf-8")
    public_claim = (root / "file-a-claim.html").read_text(encoding="utf-8")
    player = (root / "media-disclaimer.js").read_text(encoding="utf-8")

    assert 'data-url-field="apply_chat_disclaimer_video_url"' in apply_chat
    assert 'data-url-field="claims_chat_disclaimer_video_url"' in claims_chat
    assert 'data-url-field="claims_chat_disclaimer_video_url"' in public_claim
    for page in (apply_chat, claims_chat, public_claim):
        assert 'src="/media-disclaimer.js"' in page
        assert "data-media-disclaimer" in page
    assert "method: 'POST'" not in player
    assert "/api/design/settings" in player


def test_index_html_applies_design_colors():
    content = INDEX_PATH.read_text(encoding="utf-8")
    assert "applyDesignColors" in content
    assert "primary_color" in content
    assert "accent_color" in content
    assert "--ds-primary" in content
    assert "builtinPrimary" in content
    assert "--ds-primary: #060d1f" in content
    assert "defaultAccent = '#e3bf6f'" in content


def test_admin_media_defaults_to_the_unified_palette():
    content = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")
    assert "primaryColor: PLATFORM_PRIMARY" in content
    assert "PLATFORM_PRIMARY = '#060d1f'" in content
    assert "PLATFORM_ACCENT = '#e3bf6f'" in content
    assert "displayFont: 'Space Grotesk'" in content
    assert 'id="opt-display-font"' in content
    assert 'value="shield"' in content
    assert "PHINS shield" in content
    assert "function resolveColor(" in content
    assert "primary_color: designSettings.primaryColor" in content
    assert "accent_color: designSettings.accentColor" in content
    assert "selectColor('primary', '#060d1f'" in content
    assert "selectColor('accent', '#e3bf6f'" in content
    assert "selectColor('primary', '#1565c0'" not in content
    assert "selectColor('accent', '#42a5f5'" not in content
    assert "selectColor('primary', '#0d47a1'" not in content
    assert "selectColor('accent', '#ff6b35'" not in content
    assert "persistAssignments(null);" in content


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


def test_index_html_mounts_assigned_hero_video():
    content = INDEX_PATH.read_text(encoding="utf-8")
    assert 'id="video"' in content
    assert 'id="hero-video"' in content
    assert "function applyHeroVideo(" in content
    assert "settings.video_url" in content
    assert "applyHeroVideo(settings)" in content


def test_login_page_applies_branding():
    content = LOGIN_PATH.read_text(encoding="utf-8")
    assert "applyBranding" in content
    assert "/api/design/settings" in content
    assert "primary_color" in content
    assert "hero_background_url" in content
    assert "p !== '#060d1f'" in content


def test_register_page_applies_branding():
    content = REGISTER_PATH.read_text(encoding="utf-8")
    assert "applyBranding" in content
    assert "/api/design/settings" in content
    assert "primary_color" in content
    assert "p !== '#060d1f'" in content
