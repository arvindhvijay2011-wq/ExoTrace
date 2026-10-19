"""Regression checks for ExoTrace's Streamlit HTML rendering path.

These source-level checks run without launching Streamlit or an external browser.
They guard against accidentally returning the UI's literal tags to markdown text.
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = PROJECT_ROOT / "src" / "exotrace" / "ui" / "app.py"


def test_frontend_source_parses() -> None:
    """The patched Streamlit app remains valid Python."""
    ast.parse(APP_SOURCE.read_text(encoding="utf-8"))


def test_html_fragments_use_streamlit_html_api() -> None:
    """HTML fragments must use st.html instead of relying on markdown flags."""
    source = APP_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    html_calls = 0
    markdown_calls_with_unsafe_html = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_html_call = isinstance(func, ast.Attribute) and func.attr == "html"
        is_markdown_call = isinstance(func, ast.Attribute) and func.attr == "markdown"
        if is_html_call:
            html_calls += 1
        if is_markdown_call and any(
            keyword.arg == "unsafe_allow_html"
            for keyword in node.keywords
        ):
            markdown_calls_with_unsafe_html += 1

    assert html_calls >= 3, "Expected the style, brand, and hero fragments to use st.html."
    assert markdown_calls_with_unsafe_html == 0
    assert "unsafe_allow_html=True" not in source


def test_custom_css_is_wrapped_exactly_once() -> None:
    """Custom CSS is supplied as one complete style element."""
    source = APP_SOURCE.read_text(encoding="utf-8")
    assert 'st.html(f"<style>{CUSTOM_CSS}</style>")' in source
    assert "</style>\n\"\"\"" not in source


def test_streamlit_alerts_do_not_use_invalid_text_symbols_as_icons() -> None:
    """Streamlit alert icons must be valid emojis or omitted."""
    source = APP_SOURCE.read_text(encoding="utf-8")
    assert 'icon="✓"' not in source
    assert 'icon="!"' not in source
