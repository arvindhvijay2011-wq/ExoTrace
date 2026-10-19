"""Regression checks for the single-question ExoTrace UI."""

from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "src" / "exotrace" / "ui" / "app.py"


def test_followup_form_and_submission_helpers_are_removed() -> None:
    """The UI must not offer or enqueue conversational follow-up requests."""
    source = APP_PATH.read_text(encoding="utf-8")

    assert 'with st.form("exotrace-follow-up-form"' not in source
    assert 'st.markdown("### Ask a follow-up")' not in source
    assert "def _answer_context_text(" not in source
    assert "def _queue_followup_submission(" not in source
    assert "pending_followup = st.session_state.pop" not in source
    assert 'st.session_state.get("active_planner_query"' not in source
    assert 'st.session_state["active_planner_query"]' not in source


def test_sidebar_is_collapsed_by_default_but_advanced_controls_remain_available() -> None:
    """Keep operational controls available without making them part of the primary UI."""
    source = APP_PATH.read_text(encoding="utf-8")

    assert 'initial_sidebar_state="collapsed"' in source
    assert 'with st.expander("Advanced settings", expanded=False)' in source
    assert '"Maximum specialist tasks"' in source
    assert '"Planner output budget"' in source
    assert '"Embedding device"' in source
