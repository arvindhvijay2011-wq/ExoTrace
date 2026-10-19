"""Regression checks for the ExoTrace introductory hero UI."""

from pathlib import Path


PATCH_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PATCH_ROOT / "src" / "exotrace" / "ui" / "app.py"
HERO_PATH = PATCH_ROOT / "src" / "exotrace" / "ui" / "assets" / "exotrace_intro_banner.jpg"


def test_intro_hero_asset_is_bundled_and_rendered_by_the_app() -> None:
    """The main UI must include the locally bundled hero rather than a network-only image."""
    source = APP_PATH.read_text(encoding="utf-8")

    assert HERO_PATH.is_file()
    assert "HERO_IMAGE_PATH" in source
    assert "_render_intro_hero()" in source
    assert "st.image(" in source
    assert "assets" in source


def test_nasa_is_credited_as_data_source_without_an_endorsement_claim() -> None:
    """The UI links to the archive and avoids implying official NASA sponsorship."""
    source = APP_PATH.read_text(encoding="utf-8")

    assert "NASA_EXOPLANET_ARCHIVE_URL" in source
    assert "NASA Exoplanet Archive" in source
    assert "not affiliated with or endorsed by NASA" in source
    assert "Powered by NASA" not in source
    assert "nasa insignia" not in source.lower()


def test_followup_form_remains_removed() -> None:
    """The hero update must not reintroduce conversational follow-ups."""
    source = APP_PATH.read_text(encoding="utf-8")

    assert 'with st.form("exotrace-follow-up-form"' not in source
    assert "def _answer_context_text(" not in source
    assert "def _queue_followup_submission(" not in source
