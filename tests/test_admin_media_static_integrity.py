import re
from pathlib import Path


ADMIN_MEDIA_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin-media.html"
INDEX_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "index.html"
LOGIN_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "login.html"
REGISTER_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "register.html"
SOLUTIONS_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "solutions.html"
PAGE_MEDIA_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "page-surface-media.js"


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
        "login_hero_video_id",
        "login_background_id",
        "login_thumbnail_id",
        "login_banner_id",
        "solutions_hero_video_id",
        "solutions_background_id",
        "solutions_thumbnail_id",
        "solutions_banner_id",
        "solutions_theater_underwriting_id",
        "solutions_theater_assessments_id",
        "solutions_theater_media_id",
        "solutions_theater_deep_research_id",
        "solutions_theater_regulation_id",
        "solutions_theater_individuals_id",
        "data-tab=\"investor-deck\"",
        "Investor Deck Lab",
        "investor-deck-lab.js",
        "data-tab=\"solution-views\"",
        "saveTheaterAssignments",
        "Solution Views",
        "Bundled screen walkthrough",
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


def test_investor_deck_lab_tab_is_a_mount_point():
    content = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")
    pitch = ADMIN_MEDIA_PATH.with_name("pitch-dashboard.html").read_text(encoding="utf-8")
    assert 'id="tab-investor-deck"' in content
    assert 'id="investor-deck-lab"' in content
    assert "InvestorDeckLab.mount" in content
    assert "id=\"investor-deck-film\"" in pitch
    assert "InvestorDeckLab.mount" in pitch
    assert 'src="/investor-deck-lab.js"' in pitch
    assert "Unified Business Plan · Investor Deck · Appendices · One standard" in pitch


def test_solution_views_tab_leaves_design_controls_intact():
    content = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")
    assert 'id="tab-solution-views"' in content
    assert 'id="tab-design"' in content
    assert 'id="assign-solutions-hero-video"' in content
    assert 'id="assign-solutions-background"' in content
    assert "function slotsForMedia(media)" in content
    assert "return PLACEMENT_SLOTS.filter(slot => slot.kind === media.type);" in content
    assert "const THEATER_SLOTS" in content
    assert "PLACEMENT_SLOTS.concat(THEATER_SLOTS)" in content
    assert "Walkthrough films are assigned on the Solution Views tab." in content
    for key in (
        "underwriting",
        "assessments",
        "billing",
        "claims",
        "actuarial_investments",
        "platform",
        "media",
        "smart_contracts",
        "mga_solutions",
        "actuarial_force",
        "deep_research",
        "regulation",
        "individuals",
        "enterprises",
    ):
        assert f"solutions_theater_{key}_id" in content, key
        assert f"assign-solutions-theater-{key.replace('_', '-')}" in content, key


def test_admin_media_keeps_a_url_only_landing_hero_on_save():
    content = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")

    assert "function keepsUrlOnlyLanding(" in content
    assert "legacyHeroVideoUrl = settings.hero_video_id ? '' : (settings.video_url || '')" in content
    assert "legacyVideoPosterUrl = settings.video_poster_id ? '' : (settings.video_poster || '')" in content
    assert "if (keepsUrlOnlyLanding(slot.key)) return;" in content
    assert "placementTouched[type] = true" in content
    assert "mediaLibraryReady" in content
    assert "clear_hero_video" in content
    assert "clear_video_poster" in content
    assert "clearStaleAssignments" not in content


def test_admin_media_never_clears_walkthroughs_it_has_not_loaded():
    content = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")

    # A save before GET /api/design/settings returns would post empty ids,
    # and an empty id is a clear on the server.
    assert "let assignmentsReady = false;" in content
    assert "assignmentsReady = true;" in content
    assert "if (!mediaLibraryReady || !assignmentsReady) {" in content
    # A full save covers the page placements only; the walkthrough films are
    # written by the Solution Views tab alone.
    assert "const keys = slotKeys || PLACEMENT_SLOTS.map(slot => slot.key);" in content


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
    assert "login_background_url" in content
    assert "login_hero_video_url" in content
    assert 'id="login-hero-video"' in content
    assert '<video id="login-hero-video" muted' not in content
    assert "login_thumbnail_url" in content
    assert "login_banner_url" in content
    assert "login_background_url || s.hero_background_url || s.login_thumbnail_url" in content
    assert 'id="login-hero-still"' in content
    assert 'id="login-surface-switch"' in content
    assert 'id="login-surface-video"' in content
    assert 'id="login-surface-background"' in content
    assert "phins.login.surface" in content
    assert "has-login-still" in content
    assert "webkit-playsinline" in content
    assert "x5-playsinline" in content
    assert 'x5-video-player-type="h5"' in content
    assert "if (!stillOn) preferred = 'video';" in content
    assert "p !== '#060d1f'" in content
    assert 'id="username"' in content
    assert 'id="password"' in content
    assert 'id="captcha-section"' in content
    assert 'id="captcha-question"' in content
    assert 'id="otp-section"' in content
    assert 'src="/login.js' in content
    assert 'src="/page-surface-media.js"' in content


def test_solutions_page_applies_assigned_media():
    content = SOLUTIONS_PATH.read_text(encoding="utf-8")
    assert "/api/design/settings" in content
    assert "solutions_hero_video_url" in content
    assert "solutions_background_url" in content
    assert "solutions_thumbnail_url" in content
    assert "solutions_banner_url" in content
    assert 'id="solutions-hero-video"' in content
    assert 'src="/page-surface-media.js"' in content


def test_page_surface_media_rejects_unsafe_urls():
    content = PAGE_MEDIA_PATH.read_text(encoding="utf-8")
    assert "function isPlayableMediaUrl(url)" in content
    assert "value.indexOf('..') === -1" in content
    assert "/api/design/settings" not in content
    mounted = content.split("if (!isPlayableMediaUrl(url))", 1)[1]
    assert mounted.index("section.hidden = false") < mounted.index("video.src = url")
    assert "video.playsInline = true" in content
    assert "webkit-playsinline" in content
    assert "x5-video-player-type" in content
    assert "function enableSpeaker(video)" in content
    assert "video.volume = 1" in content
    assert "video.muted = true" not in content.split("function startInlinePlayback", 1)[0]


def test_uploaded_video_players_default_to_speaker():
    dashboard = (ADMIN_MEDIA_PATH.parent / "dashboard.html").read_text(encoding="utf-8")
    admin_media = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")
    assert 'controls preload="metadata" muted' not in dashboard
    assert 'controls autoplay muted playsinline' not in dashboard
    assert "player.muted = false" in admin_media
    assert "player.volume = 1" in admin_media


def test_customer_relations_tab_assigns_one_film_per_intro_path():
    content = ADMIN_MEDIA_PATH.read_text(encoding="utf-8")
    join = (ADMIN_MEDIA_PATH.parent / "join.html").read_text(encoding="utf-8")
    login = (ADMIN_MEDIA_PATH.parent / "login.js").read_text(encoding="utf-8")
    register = (ADMIN_MEDIA_PATH.parent / "register.js").read_text(encoding="utf-8")
    assert 'data-tab="customer-relations"' in content
    assert 'id="tab-customer-relations"' in content
    assert "const JOIN_INTRO_SLOTS" in content
    assert "saveJoinIntroAssignments" in content
    assert "sendJoinIntroBlueprint" in content
    assert "saveJoinEnginePriority" in content
    assert "join_intro_engine_priority" in content
    assert 'id="join-blueprint-engine"' in content
    assert "engine_id: engine.id" in content
    assert "/api/admin/media/join-intro-blueprints" in content
    assert "return PLACEMENT_SLOTS.filter(slot => slot.kind === media.type);" in content
    assert "PLACEMENT_SLOTS.concat(THEATER_SLOTS).concat(JOIN_INTRO_SLOTS)" in content
    for key in (
        "welcome",
        "insurance",
        "health_wallet",
        "investments",
        "credit",
        "agent",
        "supplier",
        "claims_chat",
    ):
        assert f"join_intro_{key}_id" in content, key
        assert f"join_intro_{key}_poster_id" in content, key
        assert f"join_intro_{key}_url" in join, key
        assert f"join_intro_{key}_poster_url" in join, key
        assert f'data-path="{key}"' in join or key in {"welcome", "claims_chat"}, key
    assert 'data-path="claims"' in join
    assert "join_background_id" in content
    assert "join_background_url" in join
    assert "claims-chat.html?start=1" in join
    assert "claims: '/claims-chat.html?start=1'" in login
    assert "'claims'" in register
    assert 'href="/apply-chat.html"' in join
    assert "next=health_wallet" in join
    assert "CUSTOMER_NEXT" in login
    assert "health_wallet: '/dashboard.html#health-wallet'" in login
    assert "function registrationNextToken(" in register
    assert "/join.html?code=" in (ADMIN_MEDIA_PATH.parent / "dashboard.html").read_text(encoding="utf-8")
    assert "register.html?code=" not in (ADMIN_MEDIA_PATH.parent / "dashboard.html").read_text(encoding="utf-8")


def test_register_page_applies_branding():
    content = REGISTER_PATH.read_text(encoding="utf-8")
    assert "applyBranding" in content
    assert "/api/design/settings" in content
    assert "primary_color" in content
    assert "p !== '#060d1f'" in content
