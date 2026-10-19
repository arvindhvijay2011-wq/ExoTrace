# ExoTrace frontend HTML rendering fix

## Symptom

The first Streamlit frontend displayed its HTML fragments as literal text, including the sidebar brand, hero elements, and summary panels, instead of rendering those elements.

## Fix

The presentation module now uses Streamlit's dedicated `st.html()` API for HTML-only markup and CSS injection instead of using `st.markdown(..., unsafe_allow_html=True)` for those fragments. The CSS payload is plain CSS wrapped once in a complete `<style>` element. Ordinary headings, Markdown, text, tables, JSON, and user-visible code continue to use native Streamlit components.

## Apply

Use `Apply_ExoTrace_Frontend_HTML_Rendering_Fix.ps1` from the Downloads folder. The installer backs up the existing `src/exotrace/ui/app.py`, then installs the full corrected module and regression test. It does not modify the backend agents, `.env`, catalogue, FAISS index, Neo4j data, or existing project configuration.

## Validation

The regression test checks Python syntax and guards the rendering API usage at source level. This is not a browser-level visual test; after installing, restart Streamlit and confirm the sidebar brand, hero header, and three summary panels render normally.

## Restart

Stop the existing Streamlit process with `Ctrl+C` in the terminal that launched it, then run:

```powershell
python -m streamlit run streamlit_app.py
```
