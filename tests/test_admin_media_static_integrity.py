import re
from pathlib import Path


ADMIN_MEDIA_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin-media.html"


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
        r"downloadLatestSubtitle\('\$\{media\.id\}'\)",
        flags=re.S,
    )
    assert preview_link_pattern.search(content)
    assert 'class="link-button"' in content
