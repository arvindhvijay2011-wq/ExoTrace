"""Streamlit presentation for evidence-grounded exoplanet investigations."""

from __future__ import annotations

import json
from html import escape as escape_html
from pathlib import Path
from typing import Any

import streamlit as st

from exotrace.ui.plan_guard import plan_review_issues
from exotrace.ui.presentation import (
    calculation_answer_statements,
    calculation_summaries,
    planned_calculation_formulas,
    reader_friendly_source_title,
    render_cited_claims_paragraph,
)
from exotrace.ui.service import (
    PROJECT_ROOT,
    InvestigationExecutionError,
    execute_investigation,
    list_saved_reports,
    preview_investigation,
    synthesize_investigation,
    workspace_readiness,
)

HERO_IMAGE_PATH = Path(__file__).resolve().parent / "assets" / "exotrace_intro_banner.jpg"
NASA_EXOPLANET_ARCHIVE_URL = "https://exoplanetarchive.ipac.caltech.edu/"


CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
:root { color-scheme: dark; }
html, body, [data-testid="stAppViewContainer"] { background:#06101e; }
.stApp {
  background:
    radial-gradient(ellipse at 8% 0%, rgba(75,127,211,.24), transparent 36%),
    radial-gradient(ellipse at 92% 14%, rgba(46,211,196,.15), transparent 34%),
    radial-gradient(ellipse at 50% 100%, rgba(104,90,190,.10), transparent 43%),
    linear-gradient(145deg,#060f1d 0%,#091729 52%,#071b29 100%);
  background-attachment:fixed;
  color:#edf5ff;
  font-family:'Plus Jakarta Sans',Inter,ui-sans-serif,system-ui,sans-serif;
}
/* The advanced-settings rail is intentionally removed from the visible UI. */
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
[data-testid="stSidebarNav"] { display:none !important; visibility:hidden !important; width:0 !important; }
[data-testid="stAppViewContainer"] > .main { margin-left:0 !important; }
[data-testid="stHeader"] {
  background:rgba(7,15,29,.30) !important;
  backdrop-filter:blur(24px) saturate(145%);
  -webkit-backdrop-filter:blur(24px) saturate(145%);
}
.block-container { max-width:1220px; padding-top:1.55rem; padding-bottom:3rem; }
h1,h2,h3 { letter-spacing:-.035em !important; }
.stMarkdown h2 { color:#f3f7ff; font-weight:800; }
.stMarkdown p { line-height:1.72; }
.exo-brand { display:flex; align-items:center; gap:.7rem; margin:.2rem 0 1.05rem; }
.exo-mark { width:2.4rem;height:2.4rem;display:grid;place-items:center;border-radius:13px;
  color:#d8fbff;font-size:1.3rem;border:1px solid rgba(117,226,222,.36);
  background:linear-gradient(135deg,rgba(75,168,207,.26),rgba(45,209,190,.13)); }
.exo-brand-name { font-size:1.05rem;font-weight:800;letter-spacing:.08em;color:#f2f7ff; }
.exo-brand-sub { font-size:.62rem;color:#7f9bb8;letter-spacing:.13em;text-transform:uppercase;margin-top:.12rem; }
.eyebrow { color:#76d8d0;font-size:.70rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase; }
.hero-title { color:#f1f6ff;font-size:clamp(2rem,4vw,3.1rem);line-height:1.12;font-weight:800;letter-spacing:-.045em;margin:.55rem 0 .55rem; }
.hero-title span { color:#78d9d1; }
.hero-copy { max-width:780px;color:#afc2d8;font-size:.96rem;line-height:1.75;margin-bottom:1.35rem; }
.section-copy { color:#9eb3c9;font-size:.86rem; }
/* Liquid-glass question composer. */
[data-testid="stForm"] {
  position:relative;
  padding:1rem 1rem .85rem;
  border:1px solid rgba(195,222,255,.19) !important;
  border-radius:24px !important;
  background:linear-gradient(135deg,rgba(255,255,255,.085),rgba(255,255,255,.025) 48%,rgba(83,176,206,.045)) !important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.11),0 18px 52px rgba(0,0,0,.20),0 0 36px rgba(69,154,205,.045);
  backdrop-filter:blur(28px) saturate(155%);
  -webkit-backdrop-filter:blur(28px) saturate(155%);
}
[data-testid="stForm"]:before {
  content:"";position:absolute;pointer-events:none;inset:0 10% auto;height:1px;
  background:linear-gradient(90deg,transparent,rgba(209,246,255,.48),rgba(123,227,219,.32),transparent);
}
.stTextArea textarea, .stTextInput input, .stSelectbox div[data-baseweb="select"] > div {
  background:rgba(4,13,27,.55)!important;color:#f0f6ff!important;
  border:1px solid rgba(169,202,235,.20)!important;border-radius:16px!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.035);
  transition:border-color .18s ease,box-shadow .18s ease,background .18s ease;
}
.stTextArea textarea:focus, .stTextInput input:focus {
  border-color:rgba(117,224,220,.60)!important;
  box-shadow:0 0 0 3px rgba(65,197,191,.10),inset 0 1px 0 rgba(255,255,255,.04)!important;
}
div.stButton > button, [data-testid="stFormSubmitButton"] button {
  border-radius:15px; min-height:2.75rem; font-weight:700; letter-spacing:.005em;
  border:1px solid rgba(176,223,242,.20);
  background:linear-gradient(135deg,rgba(255,255,255,.10),rgba(255,255,255,.035));
  color:#effaff; box-shadow:inset 0 1px 0 rgba(255,255,255,.10),0 7px 22px rgba(0,0,0,.12);
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  transition:transform .18s ease,border-color .18s ease,background .18s ease,box-shadow .18s ease;
}
div.stButton > button:hover, [data-testid="stFormSubmitButton"] button:hover {
  transform:translateY(-1px);border-color:rgba(119,227,219,.55);color:#fff;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.15),0 12px 28px rgba(0,0,0,.2),0 0 24px rgba(60,193,190,.08);
}
div.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primary"] {
  color:#041521;border:1px solid rgba(193,255,249,.26);
  background:linear-gradient(112deg,#9be9f2 0%,#5dd7d2 48%,#70e6c0 100%);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.55),0 8px 24px rgba(50,199,187,.15);
}
[data-testid="stMetric"] {
  background:linear-gradient(135deg,rgba(255,255,255,.075),rgba(255,255,255,.025));
  border:1px solid rgba(191,220,244,.15);padding:.9rem 1rem;border-radius:18px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.07),0 14px 32px rgba(0,0,0,.12);
  backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
}
[data-testid="stMetricLabel"] { color:#a9bfd6!important; }
[data-testid="stMetricValue"] { color:#f1f8ff!important; }
[data-testid="stExpander"] {
  border:1px solid rgba(178,211,239,.16)!important;border-radius:16px!important;
  background:linear-gradient(135deg,rgba(255,255,255,.055),rgba(255,255,255,.018))!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.045);
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
}
[data-testid="stAlert"] {
  border:1px solid rgba(174,215,244,.18);border-radius:18px!important;
  background:linear-gradient(135deg,rgba(62,135,194,.17),rgba(255,255,255,.035))!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 12px 28px rgba(0,0,0,.10);
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
}
[data-testid="stTabs"] button { font-weight:600; }
hr { border-color:rgba(180,212,241,.13)!important; }
.small-muted { color:#91a9c3;font-size:.78rem; }
.status-line { color:#a3bad1;font-size:.83rem;margin:.2rem 0 .65rem; }
[data-testid="stImage"] img {
  display:block;width:100%;border:1px solid rgba(164,227,235,.20);border-radius:24px;
  box-shadow:0 24px 64px rgba(0,0,0,.26),inset 0 1px 0 rgba(255,255,255,.1);
}
.data-source-bar {
  display:flex;align-items:center;flex-wrap:wrap;gap:.65rem;margin:.85rem 0 1.35rem;padding:.78rem 1rem;
  border:1px solid rgba(185,221,242,.15);border-radius:16px;
  background:linear-gradient(115deg,rgba(255,255,255,.065),rgba(255,255,255,.018));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.05);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
}
.data-source-label { color:#82e2d9;font-size:.67rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase; }
.data-source-bar a { color:#edf8ff;text-decoration:none;font-size:.82rem;font-weight:700; }
.data-source-bar a:hover { color:#8be7dd;text-decoration:underline; }
.data-source-note { color:#9db4cc;font-size:.74rem; }
.result-formula { color:#b3cfe4;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.9rem;overflow-wrap:anywhere; }
/* Trace stays explicitly report-backed, never labelled as live streaming. */
.trace-panel {
  position:relative;overflow:hidden;margin:1.2rem 0 1.35rem;padding:1.2rem 1.25rem 1rem;
  border:1px solid rgba(164,224,238,.20);border-radius:24px;
  background:linear-gradient(140deg,rgba(255,255,255,.075),rgba(16,49,72,.28) 42%,rgba(255,255,255,.025));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.10),0 24px 62px rgba(0,0,0,.19),0 0 45px rgba(74,184,201,.045);
  backdrop-filter:blur(30px) saturate(160%);-webkit-backdrop-filter:blur(30px) saturate(160%);
}
.trace-panel:before {
  content:"";position:absolute;inset:0 0 auto;height:1px;
  background:linear-gradient(90deg,transparent,rgba(222,250,255,.65),rgba(104,225,215,.60),rgba(129,171,250,.35),transparent);
}
.trace-panel:after {
  content:"";position:absolute;pointer-events:none;right:-7rem;top:-7rem;width:16rem;height:16rem;border-radius:50%;
  background:radial-gradient(circle,rgba(65,188,202,.09),transparent 68%);
}
.trace-head { display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;position:relative;z-index:1; }
.trace-title { color:#f2f8ff;font-size:1.02rem;font-weight:800;letter-spacing:-.025em; }
.trace-copy { margin-top:.3rem;color:#a5bdd3;font-size:.82rem;line-height:1.6; }
.trace-badge { display:inline-flex;align-items:center;gap:.42rem;border:1px solid rgba(126,224,215,.24);border-radius:999px;padding:.34rem .64rem;color:#8fe8dc;background:rgba(85,205,190,.075);font-size:.64rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;white-space:nowrap;box-shadow:inset 0 1px 0 rgba(255,255,255,.08); }
.trace-badge:before { content:"";width:.42rem;height:.42rem;border-radius:50%;background:#80e5d7;box-shadow:0 0 0 4px rgba(112,216,202,.10); }
.trace-list { position:relative;display:grid;gap:.12rem;margin-top:1rem;z-index:1; }
.trace-list:before { content:"";position:absolute;left:.91rem;top:1.2rem;bottom:1.2rem;width:1px;background:linear-gradient(180deg,rgba(94,213,204,.52),rgba(106,144,181,.16)); }
.trace-step { position:relative;display:grid;grid-template-columns:1.85rem minmax(0,1fr) auto;align-items:start;gap:.72rem;padding:.7rem .2rem;border-radius:12px;opacity:0;animation:exoTraceReveal .42s cubic-bezier(.2,.7,.2,1) forwards;animation-delay:var(--trace-delay,0ms); }
.trace-step:hover { background:rgba(255,255,255,.025); }
.trace-node { z-index:1;display:grid;place-items:center;width:1.82rem;height:1.82rem;border-radius:50%;border:1px solid rgba(154,186,217,.32);background:rgba(9,26,44,.78);color:#b1c3d7;font-size:.78rem;font-weight:800;box-shadow:inset 0 1px 0 rgba(255,255,255,.08); }
.trace-step.done .trace-node { border-color:rgba(100,225,207,.50);background:linear-gradient(145deg,rgba(23,108,112,.48),rgba(10,42,60,.78));color:#9af1df; }
.trace-step.alert .trace-node { border-color:rgba(246,190,91,.48);background:rgba(94,63,23,.28);color:#ffd17b; }
.trace-step.waiting .trace-node { border-style:dashed;color:#8ca8c6; }
.trace-step-body { min-width:0;padding-top:.08rem; }
.trace-step-title { color:#eaf3ff;font-size:.84rem;font-weight:750;line-height:1.45; }
.trace-step-detail { margin-top:.15rem;color:#a0b6cd;font-size:.77rem;line-height:1.6;overflow-wrap:anywhere; }
.trace-step-state { padding-top:.22rem;color:#8de4d6;font-size:.61rem;font-weight:800;letter-spacing:.09em;text-transform:uppercase;text-align:right;white-space:nowrap; }
.trace-step.alert .trace-step-state { color:#f4c36e; }
.trace-step.waiting .trace-step-state { color:#93aac2; }
.trace-foot { display:flex;justify-content:space-between;align-items:center;gap:.8rem;flex-wrap:wrap;margin-top:.6rem;padding-top:.78rem;border-top:1px solid rgba(180,212,241,.13);color:#87a7c7;font-size:.72rem;position:relative;z-index:1; }
@keyframes exoTraceReveal { from { opacity:0;transform:translateY(8px);filter:blur(2px); } to { opacity:1;transform:translateY(0);filter:blur(0); } }
@media (prefers-reduced-motion: reduce) { *,*::before,*::after { scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important; } .trace-step { opacity:1;transform:none;filter:none; } }
@media (max-width:640px) {
  .block-container { padding-top:1rem;padding-left:1rem;padding-right:1rem; }
  [data-testid="stForm"] { padding:.8rem .7rem .65rem;border-radius:19px!important; }
  .trace-panel {padding:1rem .8rem;border-radius:20px;}
  .trace-step {grid-template-columns:1.8rem minmax(0,1fr);gap:.55rem;}
  .trace-step-state {grid-column:2;text-align:left;padding-top:0;}
  .trace-list:before {left:.89rem;}
}
"""


def _inject_styles() -> None:
    """Install the app's dark, minimal visual theme."""
    st.html(f"<style>{CUSTOM_CSS}</style>")


def _brand() -> None:
    """Render the compact sidebar identity lockup."""
    st.html(
        """
        <div class="exo-brand">
          <div class="exo-mark">✦</div>
          <div>
            <div class="exo-brand-name">EXOTRACE</div>
            <div class="exo-brand-sub">Exoplanet intelligence</div>
          </div>
        </div>
        """
    )


def _render_intro_hero() -> None:
    """Render the ExoTrace hero artwork and factual NASA data-source attribution."""
    if HERO_IMAGE_PATH.is_file():
        st.image(
            str(HERO_IMAGE_PATH),
            use_container_width=True,
            caption=None,
        )
    else:
        # Fail gracefully if an asset is accidentally omitted from a deployment bundle.
        st.html('<div class="eyebrow">EXOPLANET INTELLIGENCE</div>')
        st.html('<div class="hero-title">Explore <span>exoplanets.</span></div>')
        st.html(
            '<div class="hero-copy">Ask questions about planets, compare catalogue '
            'measurements, and inspect the source records behind each finding.</div>'
        )

    st.html(
        f"""
        <div class="data-source-bar">
          <span class="data-source-label">Data source</span>
          <a href="{NASA_EXOPLANET_ARCHIVE_URL}" target="_blank" rel="noopener noreferrer">
            NASA Exoplanet Archive ↗
          </a>
          <span class="data-source-note">
            Publicly available data · Independent research interface, not affiliated with or endorsed by NASA
          </span>
        </div>
        """
    )


def _readiness_sidebar() -> dict[str, Any]:
    """Render a quiet sidebar; technical controls are opt-in under Advanced settings."""
    readiness = workspace_readiness(PROJECT_ROOT)
    _brand()
    st.caption("Evidence-grounded exoplanet research")

    assets_ready = all(readiness["assets"].values())
    with st.expander("Advanced settings", expanded=False):
        st.caption("Research data: ready" if assets_ready else "Research data: some assets are missing")
        for asset_name, is_ready in readiness["assets"].items():
            st.caption(f"{'✓' if is_ready else '•'} {asset_name}")
        if not readiness["openai_key_configured"] or not readiness["model_configured"]:
            st.warning("Configure OPENAI_API_KEY and EXOTRACE_LLM_MODEL in your local environment.")

        review_plan_first = st.checkbox(
            "Review the plan before running",
            value=False,
            help="Normally ExoTrace validates the plan privately and returns the answer directly. Turn this on only when you want to inspect the specialist steps first.",
        )
        max_agent_tasks = st.slider("Maximum specialist tasks", 1, 10, 5, 1)
        planner_output_tokens = st.slider(
            "Planner output budget", 1000, 10000, 5000, 500,
            help="Applies only to child processes launched by this UI. It does not modify .env.",
        )
        device = st.selectbox("Embedding device", options=["cpu", "cuda"], index=0)
        # Credentials are intentionally never collected in the UI. The CLI reads the
        # existing project-local .env / process environment through its shared settings loader.
        # Clear state left over from a prior version that exposed a password field.
        st.session_state.pop("neo4j_password_input", None)

    return {
        "readiness": readiness,
        "max_agent_tasks": max_agent_tasks,
        "planner_output_tokens": planner_output_tokens,
        "device": device,
        "engine": "langgraph",
        "review_plan_first": review_plan_first,
    }


def _plan_tasks(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the saved plan's task objects when present and well-formed."""
    plan = report.get("plan", {})
    tasks = plan.get("tasks", []) if isinstance(plan, dict) else []
    return [task for task in tasks if isinstance(task, dict)] if isinstance(tasks, list) else []


def _is_executable_plan(report: dict[str, Any]) -> bool:
    """Return true only when the plan is ready and passes UI pre-execution checks."""
    plan = report.get("plan", {})
    structurally_ready = (
        report.get("status") == "planned"
        and isinstance(plan, dict)
        and plan.get("disposition") == "ready"
        and bool(_plan_tasks(report))
    )
    if not structurally_ready:
        return False
    return not plan_review_issues(report, project_root=PROJECT_ROOT)


def _show_plan(report: dict[str, Any]) -> None:
    """Show a brief plan summary and keep verbose task contracts collapsed."""
    plan = report.get("plan", {})
    disposition = plan.get("disposition", "unknown") if isinstance(plan, dict) else "unknown"
    status = str(report.get("status", "unknown")).replace("_", " ").title()
    tasks = _plan_tasks(report)
    st.markdown("### Plan review")
    st.caption(f"Status: {status} · Plan: {disposition} · {len(tasks)} steps")
    if isinstance(plan, dict) and plan.get("summary"):
        st.write(plan["summary"])

    for index, task in enumerate(tasks, start=1):
        task_key = str(task.get("task_key", f"task-{index}"))
        agent_id = str(task.get("agent_id", "specialist")).replace("_", " ")
        objective = str(task.get("objective") or task.get("question") or task_key)
        st.markdown(f"**{index}. {objective}**")
        extra = [agent_id]
        dependencies = task.get("depends_on", [])
        if isinstance(dependencies, list) and dependencies:
            extra.append("depends on " + ", ".join(str(item) for item in dependencies))
        st.caption(" · ".join(extra))

    for calculation in planned_calculation_formulas(report):
        st.caption(f"{calculation['title']} · Formula: {calculation['formula']}")

    if tasks:
        with st.expander("Inspect detailed task contracts", expanded=False):
            for task in tasks:
                task_key = str(task.get("task_key", "task"))
                with st.expander(task_key, expanded=False):
                    st.json(task.get("context", {}), expanded=False)
                    st.caption("Required capabilities: " + ", ".join(str(item) for item in task.get("required_capabilities", [])))

    questions = plan.get("clarifying_questions", []) if isinstance(plan, dict) else []
    if questions:
        st.warning("The planner needs clarification before execution.")
        for question in questions:
            st.write(f"• {question}")


def _collect_evidence(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the report's evidence while retaining original provenance fields."""
    results = report.get("results", [])
    found: dict[str, dict[str, Any]] = {}
    if not isinstance(results, list):
        return []
    for result in results:
        if not isinstance(result, dict):
            continue
        evidence_items = result.get("evidence", [])
        if not isinstance(evidence_items, list):
            continue
        for item in evidence_items:
            if isinstance(item, dict) and isinstance(item.get("evidence_id"), str):
                found.setdefault(item["evidence_id"], item)
    return list(found.values())


def _render_calculation_highlights(report: dict[str, Any]) -> bool:
    """Display deterministic calculations with explicit operand direction and provenance."""
    summaries = calculation_summaries(report)
    if not summaries:
        return False

    st.markdown("### Calculated result")
    for index, item in enumerate(summaries, start=1):
        with st.container(border=True):
            st.metric(item["title"], item["value_display"])
            st.caption(f"Formula: {item['formula']}")
            if item["unit"] == "1":
                st.caption("Dimensionless result · unit conversions were not performed")
            else:
                st.caption(f"Recorded result unit label: {item['unit']}")
            with st.expander("Calculation provenance", expanded=False):
                st.caption("Exact result")
                st.code(item["value_exact"], language=None)
                if item["input_fields"]:
                    st.caption("Input fields: " + ", ".join(str(value) for value in item["input_fields"]))
                if item["input_source_ids"]:
                    st.caption("Source record IDs")
                    for source_id in item["input_source_ids"]:
                        st.code(str(source_id), language=None)
                if item["input_evidence_ids"]:
                    st.caption("Input evidence IDs: " + ", ".join(item["input_evidence_ids"]))
                if item["derived_evidence_ids"]:
                    st.caption("Derived evidence IDs: " + ", ".join(item["derived_evidence_ids"]))
    return True


def _render_report_summary(report: dict[str, Any], *, report_path: str | Path | None = None) -> None:
    """Keep specialist results, counts, and snapshot diagnostics available but unobtrusive."""
    status = str(report.get("status", "unknown"))
    tasks = _plan_tasks(report)
    results = report.get("results", []) if isinstance(report.get("results"), list) else []
    evidence = _collect_evidence(report)
    snapshots = sorted({str(item.get("snapshot_id")) for item in evidence if item.get("snapshot_id")})

    with st.expander("Investigation details", expanded=False):
        st.markdown(f"**Status:** {status.replace('_', ' ').title()}")
        question = report.get("question", "")
        if question:
            st.write(question)
        columns = st.columns(3)
        columns[0].metric("Steps", len(tasks))
        columns[1].metric("Results", len(results))
        columns[2].metric("Evidence items", len(evidence))
        if snapshots:
            st.caption("Frozen snapshot(s): " + " · ".join(snapshots))
        for result in results:
            agent = str(result.get("agent_id", "specialist")).replace("_", " ")
            result_status = str(result.get("status", "unknown")).replace("_", " ")
            with st.expander(f"{agent} · {result_status}", expanded=False):
                if result.get("summary"):
                    st.write(result["summary"])
                for finding in result.get("findings", []) if isinstance(result.get("findings"), list) else []:
                    if not isinstance(finding, dict):
                        continue
                    if finding.get("statement"):
                        st.write(finding["statement"])
                    evidence_ids = finding.get("evidence_ids", [])
                    if evidence_ids:
                        st.caption("Evidence: " + ", ".join(str(item) for item in evidence_ids))
                gaps = result.get("gaps", [])
                if gaps:
                    st.warning("Evidence gaps: " + "; ".join(str(item) for item in gaps))
                if result.get("error_message"):
                    st.error(result["error_message"])
        if report_path:
            st.caption(f"Saved report: `{report_path}`")


def _render_evidence_tab(report: dict[str, Any] | None) -> None:
    """Let a researcher inspect evidence and provenance on demand."""
    st.markdown("## Evidence ledger")
    st.caption("Source records, evidence IDs, snapshot identifiers, excerpts, and source links.")
    if not report:
        st.info("Run an investigation to populate the evidence ledger.")
        return
    evidence = _collect_evidence(report)
    if not evidence:
        st.info("This report does not contain returned evidence items.")
        return
    for item_index, item in enumerate(evidence, start=1):
        title = str(item.get("title") or item.get("evidence_id") or "Evidence item")
        with st.expander(f"{item.get('evidence_id', f'E{item_index}')} · {title}", expanded=False):
            st.write(item.get("excerpt", "No excerpt was supplied."))
            columns = st.columns(2)
            columns[0].caption("Source record")
            columns[0].code(str(item.get("record_id") or item.get("source_id") or "Not supplied"), language=None)
            columns[1].caption("Snapshot")
            columns[1].code(str(item.get("snapshot_id") or "Not supplied"), language=None)
            source_uri = str(item.get("source_uri") or "")
            if source_uri:
                st.caption("Source URI")
                st.code(source_uri, language=None)
                if source_uri.startswith(("https://", "http://")):
                    st.link_button("Open source", source_uri, key=f"evidence-source-{item_index}")
            if item.get("source_kind"):
                st.caption(f"Source kind: {item['source_kind']}")
            metadata = item.get("metadata")
            if metadata:
                with st.expander("Source metadata", expanded=False):
                    st.json(metadata, expanded=False)


def _load_history_report(path: Path) -> dict[str, Any] | None:
    """Read a report file defensively for the history view."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _render_history() -> None:
    """Render recent saved reports with a concise summary and a load action."""
    st.markdown("## History")
    st.caption("Investigations are saved in your local workspace.")
    paths = list_saved_reports(PROJECT_ROOT, limit=30)
    if not paths:
        st.info("Your investigations will appear here after the first execution.")
        return
    for path in paths:
        report = _load_history_report(path)
        if report is None:
            continue
        question = str(report.get("question", path.stem))
        plan = report.get("plan", {})
        task_count = len(plan.get("tasks", [])) if isinstance(plan, dict) and isinstance(plan.get("tasks", []), list) else 0
        with st.container(border=True):
            st.markdown(f"**{question[:170]}{'…' if len(question) > 170 else ''}**")
            left, middle, right = st.columns([0.28, 0.20, 0.52])
            left.caption(str(report.get("status", "unknown")).replace("_", " ").title())
            middle.caption(f"{task_count} steps")
            right.caption(path.name)
            if st.button("Open investigation", key=f"open-history-{path.name}"):
                st.session_state["active_report"] = report
                st.session_state["active_report_path"] = str(path.relative_to(PROJECT_ROOT))
                st.session_state["active_plan_report"] = None
                st.session_state["active_plan_path"] = None
                answer_path = path.with_name(path.name.replace("_result.json", "_answer.json"))
                st.session_state["active_answer"] = _load_history_report(answer_path) if answer_path.is_file() else None
                st.session_state["active_answer_path"] = str(answer_path.relative_to(PROJECT_ROOT)) if answer_path.is_file() else None
                st.session_state["active_query"] = question
                st.session_state.pop("synthesis_error", None)
                st.session_state.pop("synthesis_error_output", None)
                st.session_state["active_tab"] = "Investigate"
                st.rerun()


def _render_synthesized_answer(payload: dict[str, Any] | None, *, answer_path: str | None = None) -> None:
    """Render a direct answer first and keep citation machinery out of the reading flow."""
    st.markdown("### Answer")
    if not payload:
        st.info("No synthesized answer is attached to this investigation.")
        return

    answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else payload
    if not isinstance(answer, dict) or not isinstance(answer.get("answerable"), bool):
        st.warning("The saved synthesis file does not contain a readable grounded answer.")
        return
    if not answer.get("answerable", False):
        st.warning(str(answer.get("insufficient_reason") or "The evidence did not support a complete answer."))
        return

    evidence_items = answer.get("evidence", [])
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in evidence_items
        if isinstance(item, dict) and item.get("evidence_id")
    } if isinstance(evidence_items, list) else {}
    answer_paragraph = render_cited_claims_paragraph(answer)
    if not answer_paragraph:
        st.info("The sources were retrieved, but no answer claims were available to display.")
    else:
        # Keep the narrative coherent across source types. Citation IDs remain attached to each
        # generated claim and the source ledger remains available below in the disclosure.
        st.markdown(answer_paragraph)

    if evidence_by_id:
        with st.expander("Sources and provenance", expanded=False):
            st.caption("Original source excerpts, links, catalogue record IDs, and snapshot IDs.")
            for evidence_id, evidence in evidence_by_id.items():
                raw_title = str(evidence.get("title") or evidence.get("doc_id") or "Source")
                title = reader_friendly_source_title(raw_title)
                record_id = evidence.get("catalogue_record_id")
                expander_title = f"{title} · record {record_id}" if record_id else title
                with st.expander(expander_title, expanded=False):
                    st.write(evidence.get("text", "No source excerpt supplied."))
                    source_url = str(evidence.get("source_url") or "")
                    if source_url:
                        st.caption(source_url)
                        if source_url.startswith(("https://", "http://")):
                            st.link_button("Open source", source_url, key=f"answer-source-{evidence_id}")
                    if record_id:
                        st.caption(f"Catalogue record: {record_id}")
                    if evidence.get("snapshot_id"):
                        st.caption(f"Snapshot: {evidence['snapshot_id']}")
                    with st.expander("Technical evidence identifier", expanded=False):
                        st.code(evidence_id)
    # Artifact paths are intentionally kept in the collapsed investigation details.


def _display_cli_error(error: InvestigationExecutionError) -> None:
    """Display a helpful error, keeping process logs hidden until requested."""
    st.error(str(error))
    output = "\n".join(part.strip() for part in (error.stdout, error.stderr) if part and part.strip())
    if output:
        with st.expander("Technical diagnostics", expanded=False):
            st.code(output[-12000:], language="text")


def _clear_active_investigation() -> None:
    """Remove reports and results from the preceding question before a new preview."""
    keys_to_clear = (
        "active_plan_report", "active_plan_path", "active_run_settings", "active_report",
        "active_report_path", "active_answer", "active_answer_path", "active_run_id",
        "active_query", "last_cli_output", "last_synthesis_output", "synthesis_error",
        "synthesis_error_output", "active_plan_blocked", "active_review_plan_first",
        "active_execution_error", "active_execution_diagnostics",
    )
    for key in keys_to_clear:
        st.session_state.pop(key, None)


def _execute_active_plan(controls: dict[str, Any]) -> None:
    """Execute a validated saved plan and keep the user-facing output answer-first."""
    plan_report = st.session_state.get("active_plan_report")
    plan_path_value = st.session_state.get("active_plan_path")
    run_id = st.session_state.get("active_run_id")
    query = st.session_state.get("active_query", "")
    run_settings = st.session_state.get("active_run_settings", {})

    if not isinstance(plan_report, dict) or not plan_path_value or not run_id:
        st.session_state["active_execution_error"] = "The saved plan could not be loaded. Please submit the question again."
        return

    issues = plan_review_issues(plan_report, project_root=PROJECT_ROOT)
    if not _is_executable_plan(plan_report):
        st.session_state["active_plan_blocked"] = {
            "message": "I couldn't safely run this question because the investigation plan needs correction.",
            "issues": list(issues),
            "clarifying_questions": list((plan_report.get("plan") or {}).get("clarifying_questions", []))
            if isinstance(plan_report.get("plan"), dict) else [],
        }
        return

    planned_tasks = _plan_tasks(plan_report)
    has_graph_task = any(task.get("agent_id") == "graph_investigation" for task in planned_tasks)
    configured_password = bool(controls["readiness"].get("neo4j_password_configured", False))
    if has_graph_task and not configured_password:
        st.session_state["active_plan_blocked"] = {
            "message": (
                "This question needs the local Neo4j graph, but NEO4J_PASSWORD is not configured "
                "in ExoTrace's local environment. Add it once to the project's .env file; "
                "ExoTrace never collects database credentials in the interface. Catalogue and "
                "literature questions can still run without graph access."
            ),
            "issues": [],
            "clarifying_questions": [],
            "retryable": False,
        }
        return

    try:
        with st.spinner("Investigating your question and checking the evidence…"):
            artifact = execute_investigation(
                str(query),
                plan_path=Path(str(plan_path_value)),
                run_id=str(run_id),
                project_root=PROJECT_ROOT,
                engine=str(run_settings.get("engine", controls["engine"])),
                max_agent_tasks=int(run_settings.get("max_agent_tasks", controls["max_agent_tasks"])),
                device=str(run_settings.get("device", controls["device"])),
                planner_output_tokens=int(run_settings.get("planner_output_tokens", controls["planner_output_tokens"])),
            )
        st.session_state["active_report"] = artifact.report
        st.session_state["active_report_path"] = str(artifact.report_path.relative_to(PROJECT_ROOT))
        st.session_state["last_cli_output"] = "\n".join(part for part in (artifact.stdout, artifact.stderr) if part)
        st.session_state.pop("active_plan_blocked", None)
        st.session_state.pop("active_execution_error", None)

        # A deterministic quantitative result is already an authoritative answer. Do not
        # pay for a second model call that could restate its operands in the wrong order.
        has_deterministic_calculation = bool(calculation_summaries(artifact.report))
        plan_tasks = _plan_tasks(artifact.report)
        has_quantitative_task = any(task.get("agent_id") == "quantitative_analysis" for task in plan_tasks)
        if (
            not has_deterministic_calculation
            and not has_quantitative_task
            and artifact.report.get("status") in {"completed", "partial", "insufficient_evidence"}
        ):
            try:
                with st.spinner("Preparing a concise, source-cited answer…"):
                    synthesized = synthesize_investigation(
                        artifact.report_path,
                        run_id=str(run_id),
                        project_root=PROJECT_ROOT,
                        planner_output_tokens=int(run_settings.get("planner_output_tokens", controls["planner_output_tokens"])),
                            )
                st.session_state["active_answer"] = synthesized.answer
                st.session_state["active_answer_path"] = str(synthesized.answer_path.relative_to(PROJECT_ROOT))
                st.session_state["last_synthesis_output"] = "\n".join(part for part in (synthesized.stdout, synthesized.stderr) if part)
                st.session_state.pop("synthesis_error", None)
                st.session_state.pop("synthesis_error_output", None)
            except InvestigationExecutionError as synthesis_error:
                st.session_state["synthesis_error"] = str(synthesis_error)
                st.session_state["synthesis_error_output"] = "\n".join(
                    part for part in (synthesis_error.stdout, synthesis_error.stderr) if part
                )
        else:
            st.session_state["active_answer"] = None
            st.session_state["active_answer_path"] = None
    except InvestigationExecutionError as error:
        st.session_state["active_execution_error"] = str(error)
        st.session_state["active_execution_diagnostics"] = "\n".join(
            part.strip() for part in (error.stdout, error.stderr) if part and part.strip()
        )
    except (ValueError, OSError) as error:
        st.session_state["active_execution_error"] = str(error)


def _render_deterministic_answer(report: dict[str, Any]) -> bool:
    """Render calculator-backed results as the answer, without a contradictory LLM rewrite."""
    statements = calculation_answer_statements(report)
    if not statements:
        return False

    st.markdown("### Answer")
    for item in statements:
        st.markdown(item["text"])
        input_values = item.get("input_values", [])
        if input_values:
            source_values = " · ".join(
                f"{entry['label']} = {entry['value']}"
                for entry in input_values
                if isinstance(entry, dict) and entry.get("label") and entry.get("value") is not None
            )
            if source_values:
                st.caption(f"Source values: {source_values}")
        st.caption(f"Formula: {item['formula']}")

    with st.expander("Calculation evidence", expanded=False):
        for item in statements:
            st.markdown(f"**{item['title']}**")
            st.caption(f"Exact result: {item['value_exact']}")
            if item.get("input_fields"):
                st.caption("Input fields: " + ", ".join(str(value) for value in item["input_fields"]))
            if item.get("input_source_ids"):
                st.caption("Source records: " + " · ".join(str(value) for value in item["input_source_ids"]))
            if item.get("input_evidence_ids"):
                st.caption("Input evidence: " + " · ".join(str(value) for value in item["input_evidence_ids"]))
            if item.get("derived_evidence_ids"):
                st.caption("Derived evidence: " + " · ".join(str(value) for value in item["derived_evidence_ids"]))
    return True


def _render_plan_problem(report: dict[str, Any] | None) -> None:
    """Show only the actionable problem; keep machine-generated plans out of the default UI."""
    if not report:
        return
    block = st.session_state.get("active_plan_blocked", {})
    message = str(block.get("message") or "I couldn't create a safe, complete investigation for this question.")
    questions = block.get("clarifying_questions", [])
    if isinstance(questions, list) and questions:
        st.info("I need one clarification before I can answer:")
        for question in questions:
            st.write(f"• {question}")
    else:
        st.warning(message)

    issues = block.get("issues", [])
    if issues or report.get("plan"):
        with st.expander("More details", expanded=False):
            if isinstance(report.get("plan"), dict) and report["plan"].get("summary"):
                st.write(report["plan"]["summary"])
            for issue in issues if isinstance(issues, list) else []:
                st.write(f"• {issue}")
            questions = report.get("plan", {}).get("clarifying_questions", []) if isinstance(report.get("plan"), dict) else []
            for question in questions if isinstance(questions, list) else []:
                st.write(f"• {question}")


def _render_sources(report: dict[str, Any]) -> None:
    """Render a compact source list within a collapsed disclosure section."""
    evidence = _collect_evidence(report)
    if not evidence:
        st.caption("No evidence items were returned by the specialists.")
        return
    for index, item in enumerate(evidence, start=1):
        evidence_id = str(item.get("evidence_id") or f"evidence-{index}")
        title = reader_friendly_source_title(str(item.get("title") or "Source"))
        record_id = item.get("record_id")
        expander_title = f"{title} · record {record_id}" if record_id else title
        with st.expander(expander_title, expanded=False):
            excerpt = str(item.get("excerpt") or "").strip()
            if excerpt:
                st.write(excerpt)
            source_uri = str(item.get("source_uri") or "")
            if source_uri.startswith(("https://", "http://")):
                st.link_button("Open source", source_uri, key=f"answer-evidence-source-{index}")
            details = [
                ("Record", record_id or item.get("source_id")),
                ("Snapshot", item.get("snapshot_id")),
            ]
            for label, value in details:
                if value:
                    st.caption(f"{label}: {value}")
            with st.expander("Technical evidence identifier", expanded=False):
                st.code(evidence_id)




def _render_execution_trace(plan_report: dict[str, Any] | None, result_report: dict[str, Any] | None) -> None:
    """Render an animated, report-backed trace without changing the investigation pipeline.

    This is a visual replay of persisted plan and result data. It deliberately does not
    claim token-level or live backend streaming, and it never fabricates specialist events.
    """
    if not isinstance(plan_report, dict) and not isinstance(result_report, dict):
        return

    plan_source = plan_report if isinstance(plan_report, dict) else result_report or {}
    plan = plan_source.get("plan", {})
    plan = plan if isinstance(plan, dict) else {}
    query = str(
        st.session_state.get("active_query")
        or plan_source.get("question")
        or (result_report or {}).get("question")
        or "Your research question"
    ).strip()
    disposition = str(plan.get("disposition") or "unknown").replace("_", " ")
    plan_status = str(plan_source.get("status") or "unknown").replace("_", " ")
    tasks = _plan_tasks(plan_source)
    blocked = st.session_state.get("active_plan_blocked")
    blocked = blocked if isinstance(blocked, dict) else {}
    execution_error = st.session_state.get("active_execution_error")
    synthesis_error = st.session_state.get("synthesis_error")
    evidence = _collect_evidence(result_report) if isinstance(result_report, dict) else []
    results = result_report.get("results", []) if isinstance(result_report, dict) else []
    results = [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []
    answer_present = bool(st.session_state.get("active_answer"))
    deterministic_answer = bool(result_report and calculation_summaries(result_report))

    steps: list[tuple[str, str, str]] = []
    steps.append(("Question received", query or "Natural-language question", "done"))

    is_plan_ready = (
        plan_source.get("status") == "planned"
        and plan.get("disposition") == "ready"
        and bool(tasks)
    )
    if plan_source.get("status") == "unsupported" or disposition in {"unsupported", "needs clarification", "clarification required"}:
        plan_state = "alert"
        plan_detail = f"Planner status: {plan_status}. No runnable specialist plan was produced."
    elif plan.get("clarifying_questions"):
        plan_state = "alert"
        plan_detail = "The saved plan contains a clarification request."
    elif is_plan_ready:
        plan_state = "done"
        plan_detail = f"{len(tasks)} specialist step(s) proposed from the saved plan."
    else:
        plan_state = "alert" if execution_error or blocked else "waiting"
        plan_detail = f"Planner status: {plan_status}; disposition: {disposition}."
    if plan.get("summary"):
        summary = str(plan["summary"]).strip()
        if summary and len(summary) < 300:
            plan_detail += " " + summary
    steps.append(("Investigation plan", plan_detail, plan_state))

    if isinstance(result_report, dict):
        steps.append(("Plan checks", "The UI allowed this saved plan to execute and a result report was returned.", "done"))
    elif blocked:
        checks_detail = str(blocked.get("message") or "The plan did not pass the UI execution checks.")
        steps.append(("Plan checks", checks_detail, "alert"))
    elif execution_error:
        steps.append(("Plan checks", str(execution_error), "alert"))
    elif is_plan_ready:
        steps.append(("Plan checks", "The plan is ready; execution is pending user review.", "waiting"))
    else:
        steps.append(("Plan checks", "No specialist work was started for this plan.", "alert"))

    if results:
        for item in results:
            agent = str(item.get("agent_id") or item.get("task_key") or "Specialist").replace("_", " ").title()
            status = str(item.get("status") or "unknown").replace("_", " ")
            agent_evidence = item.get("evidence", [])
            evidence_count = len(agent_evidence) if isinstance(agent_evidence, list) else 0
            detail = f"Result: {status}. {evidence_count} evidence item(s) returned."
            if item.get("summary"):
                brief = str(item["summary"]).strip()
                if brief and len(brief) < 220:
                    detail += " " + brief
            result_status = str(item.get("status") or "").casefold()
            state = "alert" if result_status in {"failed", "error", "blocked", "insufficient_evidence"} else "done"
            steps.append((agent, detail, state))
    elif isinstance(result_report, dict):
        status = str(result_report.get("status") or "unknown").replace("_", " ")
        steps.append(("Specialist work", f"The report contains no specialist result entries (status: {status}).", "alert"))
    elif blocked or execution_error or not is_plan_ready:
        steps.append(("Specialist work", "No specialist result was produced for this run.", "alert"))
    else:
        steps.append(("Specialist work", "Awaiting execution of the saved plan.", "waiting"))

    if isinstance(result_report, dict):
        if evidence:
            steps.append(("Evidence assembled", f"{len(evidence)} unique evidence item(s) are available for inspection, with IDs and provenance preserved.", "done"))
        else:
            steps.append(("Evidence assembled", "The saved report contains no evidence items from specialists.", "alert"))
    elif blocked or execution_error or not is_plan_ready:
        steps.append(("Evidence assembled", "Evidence retrieval did not run for this question.", "alert"))
    else:
        steps.append(("Evidence assembled", "Evidence collection has not started yet.", "waiting"))

    if deterministic_answer:
        steps.append(("Answer prepared", "A deterministic calculation result is ready; it is shown without a second model rewrite.", "done"))
    elif answer_present:
        steps.append(("Answer synthesized", "A written answer is available. Citation IDs are linked to the investigation evidence pack.", "done"))
    elif synthesis_error:
        steps.append(("Answer synthesis", "The investigation ran, but written synthesis failed. See the optional diagnostics for details.", "alert"))
    elif isinstance(result_report, dict):
        steps.append(("Answer synthesis", "No synthesized answer is attached to this report.", "alert"))
    elif blocked or execution_error or not is_plan_ready:
        steps.append(("Answer synthesis", "No answer was synthesized because the investigation did not complete its evidence-gathering path.", "alert"))
    else:
        steps.append(("Answer synthesis", "Waiting for the investigation results.", "waiting"))

    icons = {"done": "✓", "alert": "!", "waiting": "·"}
    rows: list[str] = []
    for index, (title, detail, state) in enumerate(steps):
        safe_title = escape_html(str(title))
        safe_detail = escape_html(str(detail))
        safe_state = escape_html(state)
        label = {"done": "Recorded", "alert": "Needs attention", "waiting": "Pending"}.get(state, "Recorded")
        rows.append(
            '<div class="trace-step ' + safe_state + '" style="--trace-delay:' + str(min(index * 65, 780)) + 'ms">'
            '<div class="trace-node">' + icons.get(state, "·") + '</div>'
            '<div class="trace-step-body"><div class="trace-step-title">' + safe_title + '</div>'
            '<div class="trace-step-detail">' + safe_detail + '</div></div>'
            '<div class="trace-step-state">' + escape_html(label) + '</div></div>'
        )

    evidence_count = len(evidence)
    status_label = "Recorded run" if isinstance(result_report, dict) else "Plan preview"
    st.html(
        '<section class="trace-panel" aria-label="Execution trace">'
        '<div class="trace-head"><div><div class="trace-title">Execution trace</div>'
        '<div class="trace-copy">A visual replay of the saved plan, specialist results, and evidence returned for this question.</div></div>'
        '<div class="trace-badge">' + escape_html(status_label) + '</div></div>'
        '<div class="trace-list">' + ''.join(rows) + '</div>'
        '<div class="trace-foot"><span>Recorded from ExoTrace report data · no private model reasoning shown</span>'
        '<span>' + str(len(steps)) + ' stage(s) · ' + str(evidence_count) + ' evidence item(s)</span></div>'
        '</section>'
    )


def main() -> None:
    """Render the answer-first workspace; plan and technical detail are opt-in."""
    st.set_page_config(
        page_title="ExoTrace · Exoplanet intelligence",
        page_icon="✦",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    # Clear unused state from earlier UI versions that exposed follow-up questions.
    for legacy_key in ("pending_followup", "followup_input", "followup_error", "active_planner_query"):
        st.session_state.pop(legacy_key, None)
    _inject_styles()
    # Preserve the original run-control wiring. The sidebar is hidden by CSS, but the
    # existing control defaults/readiness handling remain the source of run settings.
    with st.sidebar:
        controls = _readiness_sidebar()

    _render_intro_hero()

    st.markdown("## What would you like to understand?")
    st.html(
        '<div class="hero-copy">Ask in your own words. ExoTrace will prepare an investigation, '
        'retrieve relevant evidence, and show the sources behind its answer. You do not need to '
        'know a database column or choose an agent.</div>'
    )

    with st.form("exotrace-query-form", clear_on_submit=False):
        query = st.text_area(
            "Research question",
            key="query_input",
            height=100,
            placeholder="Ask ExoTrace anything about an exoplanet, its host star, or the science behind a discovery…",
            help="Ask naturally. Include an exact planet or host-star name when you know it.",
            label_visibility="collapsed",
        )
        submit_label = "Review plan" if controls["review_plan_first"] else "Ask ExoTrace"
        submitted = st.form_submit_button(submit_label, type="primary", use_container_width=True)

    request_submitted = submitted
    request_query = query.strip()

    if request_submitted:
        _clear_active_investigation()
        if not request_query:
            st.warning("Enter a scientific question first.")
        elif not controls["readiness"]["openai_key_configured"] or not controls["readiness"]["model_configured"]:
            st.error("ExoTrace needs its planner configuration. Set OPENAI_API_KEY and EXOTRACE_LLM_MODEL in your local environment.")
        elif not all(controls["readiness"]["assets"].values()):
            missing_assets = [name for name, ready in controls["readiness"]["assets"].items() if not ready]
            st.error("Required research data are missing: " + ", ".join(missing_assets) + ".")
        else:
            try:
                with st.spinner("Working on your question…"):
                    plan_artifact = preview_investigation(
                        request_query,
                        project_root=PROJECT_ROOT,
                        engine=controls["engine"],
                        max_agent_tasks=controls["max_agent_tasks"],
                        device=controls["device"],
                        planner_output_tokens=controls["planner_output_tokens"],
                    )
                st.session_state["active_plan_report"] = plan_artifact.report
                st.session_state["active_plan_path"] = str(plan_artifact.report_path.relative_to(PROJECT_ROOT))
                st.session_state["active_run_id"] = plan_artifact.run_id
                st.session_state["active_run_settings"] = {
                    "engine": controls["engine"],
                    "max_agent_tasks": controls["max_agent_tasks"],
                    "planner_output_tokens": controls["planner_output_tokens"],
                    "device": controls["device"],
                }
                st.session_state["active_query"] = request_query
                st.session_state["last_cli_output"] = "\n".join(part for part in (plan_artifact.stdout, plan_artifact.stderr) if part)
                st.session_state["active_review_plan_first"] = bool(controls["review_plan_first"])
                if not controls["review_plan_first"]:
                    _execute_active_plan(controls)
                st.rerun()
            except InvestigationExecutionError as error:
                _display_cli_error(error)
            except (ValueError, OSError) as error:
                st.error(str(error))

    plan_report = st.session_state.get("active_plan_report")
    result_report = st.session_state.get("active_report")

    # The reviewed plan is visible only when the researcher explicitly enables review mode.
    if plan_report and not result_report and st.session_state.get("active_review_plan_first", False):
        st.divider()
        _show_plan(plan_report)
        if _is_executable_plan(plan_report):
            if st.button("Run investigation", type="primary", use_container_width=True):
                _execute_active_plan(controls)
                st.rerun()
        else:
            issues = plan_review_issues(plan_report, project_root=PROJECT_ROOT)
            if issues:
                st.error("I couldn't safely run this plan. No specialist tasks were executed.")
                with st.expander("Why the plan needs correction", expanded=False):
                    for issue in issues:
                        st.write(f"• {issue}")
            else:
                questions = plan_report.get("plan", {}).get("clarifying_questions", [])
                if questions:
                    st.info("I need a clarification before I can answer.")
                    for question in questions:
                        st.write(f"• {question}")
                elif plan_report.get("status") == "unsupported":
                    st.info("This question is outside ExoTrace's current investigation capabilities.")
                else:
                    st.info("The plan is not ready yet. See details above.")

    elif plan_report and not result_report:
        if st.session_state.get("active_execution_error"):
            st.error(str(st.session_state["active_execution_error"]))
            diagnostics = st.session_state.get("active_execution_diagnostics")
            if diagnostics:
                with st.expander("Technical diagnostics", expanded=False):
                    st.code(str(diagnostics)[-10000:], language="text")
        elif st.session_state.get("active_plan_blocked"):
            _render_plan_problem(plan_report)
            if st.session_state.get("active_plan_blocked", {}).get("retryable") and st.button(
                "Retry investigation", type="primary", key="retry-auto-plan", use_container_width=False
            ):
                _execute_active_plan(controls)
                st.rerun()
        else:
            st.info("ExoTrace is not ready to answer this question yet.")
            with st.expander("Why couldn't ExoTrace answer?", expanded=False):
                _show_plan(plan_report)

    if plan_report and not result_report:
        _render_execution_trace(plan_report, None)

    if result_report:
        status = str(result_report.get("status", "unknown"))
        if status == "partial":
            st.info(
                "This is a partial answer: one or more investigation steps did not complete. "
                "The available findings are shown below; details are available under Sources and evidence."
            )
        summaries = calculation_summaries(result_report)
        if summaries:
            _render_deterministic_answer(result_report)
        else:
            _render_synthesized_answer(st.session_state.get("active_answer"))
            if not st.session_state.get("active_answer"):
                if status == "insufficient_evidence":
                    st.warning("The available sources did not support a complete answer.")
                elif status in {"partial", "completed"}:
                    st.info("The investigation finished. Open the sources below to inspect its findings.")

        synthesis_error = st.session_state.get("synthesis_error")
        if synthesis_error:
            st.caption("The investigation completed, but the optional written summary could not be generated.")
            with st.expander("Summary diagnostics", expanded=False):
                st.error(str(synthesis_error))
                synthesis_output = st.session_state.get("synthesis_error_output")
                if synthesis_output:
                    st.code(str(synthesis_output)[-10000:], language="text")

        _render_execution_trace(plan_report or result_report, result_report)

        with st.expander("Sources and evidence", expanded=False):
            _render_sources(result_report)
        _render_report_summary(result_report, report_path=st.session_state.get("active_report_path"))
        with st.expander("Developer diagnostics", expanded=False):
            st.caption("Technical logs and raw JSON are for troubleshooting only.")
            st.json(result_report, expanded=False)
            cli_output = st.session_state.get("last_cli_output")
            if cli_output:
                st.code(str(cli_output)[-10000:], language="text")

    with st.expander("Recent investigations", expanded=False):
        _render_history()


if __name__ == "__main__":
    main()
