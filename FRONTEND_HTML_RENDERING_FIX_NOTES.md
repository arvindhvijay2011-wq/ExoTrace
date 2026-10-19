# ExoTrace HTML rendering hotfix

- Replaces the HTML-only `st.markdown(..., unsafe_allow_html=True)` fragments with `st.html(...)`.
- Supplies the CSS as one complete `<style>` element using the dedicated HTML API.
- Adds a source-level regression test for the markup rendering contract.
- No agent, planner, retrieval, catalogue, Neo4j, API-key, or `.env` behavior is changed.
