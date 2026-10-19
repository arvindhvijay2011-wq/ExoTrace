"""Regression tests for the answer-first default interaction."""

from pathlib import Path


def test_plan_review_is_opt_in_and_defaults_to_false() -> None:
    source_path = Path(__file__).parents[1] / "src" / "exotrace" / "ui" / "app.py"
    source = source_path.read_text(encoding="utf-8")

    assert '"Review the plan before running"' in source
    assert "value=False" in source
    assert 'submit_label = "Review plan" if controls["review_plan_first"] else "Ask ExoTrace"' in source


def test_normal_question_submission_executes_without_rendering_plan_first() -> None:
    source_path = Path(__file__).parents[1] / "src" / "exotrace" / "ui" / "app.py"
    source = source_path.read_text(encoding="utf-8")

    assert 'if not controls["review_plan_first"]:\n                    _execute_active_plan(controls)' in source
    assert 'if plan_report and not result_report and st.session_state.get("active_review_plan_first", False):' in source


def test_deterministic_calculations_are_rendered_as_answer_not_rewritten_by_llm() -> None:
    source_path = Path(__file__).parents[1] / "src" / "exotrace" / "ui" / "app.py"
    source = source_path.read_text(encoding="utf-8")

    assert "has_deterministic_calculation = bool(calculation_summaries(artifact.report))" in source
    assert "not has_deterministic_calculation" in source
    assert "not has_quantitative_task" in source
    assert "_render_deterministic_answer(result_report)" in source
