"""Fail-closed checks for plans reviewed in the Streamlit interface.

The guard is intentionally separate from specialist execution. It checks that task graphs
cover exact catalogue entities explicitly named in a question and that calculation tasks
consume their declared prerequisite evidence. It does not calculate scientific values.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


_PLACEHOLDER_VALUES = {"", "null", "none", "n/a", "<null>"}
_ARITHMETIC_REQUEST = re.compile(
    r"\b(?:ratio|difference|average|mean|sum|total|percentage|percent|"
    r"multiply|product|divide|divided|quotient|calculate|calculation)\b",
    re.IGNORECASE,
)


def _catalogue_path(project_root: Path) -> Path:
    return project_root / "data" / "processed" / "planets_validated.csv"


@lru_cache(maxsize=8)
def _load_planet_names_cached(path_text: str, modified_ns: int, size: int) -> tuple[str, ...]:
    """Load exact planet identifiers from the current validated catalogue snapshot."""
    del modified_ns, size  # Included in the cache key so changed snapshots invalidate it.
    path = Path(path_text)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "pl_name" not in reader.fieldnames:
            raise ValueError("The validated catalogue does not contain the pl_name column.")
        names = {
            row.get("pl_name", "").strip()
            for row in reader
            if row.get("pl_name", "").strip()
        }
    return tuple(sorted(names, key=lambda item: (-len(item), item.casefold())))


def _known_names_mentioned(question: str, project_root: Path) -> tuple[str, ...]:
    """Find exact catalogue planet identifiers literally mentioned in the question."""
    path = _catalogue_path(project_root)
    if not path.is_file():
        # Minimal offline tests and non-catalogue utilities may use a workspace stub. The main
        # UI checks workspace readiness before previewing; execution's CLI remains authoritative
        # if the real validated catalogue is unavailable.
        return ()
    stat = path.stat()
    names = _load_planet_names_cached(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    matches: list[str] = []
    for name in names:
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE)
        if pattern.search(question):
            matches.append(name)
    return tuple(matches)


def _filter_map(task: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Read either the current compact filter-pair list or a legacy mapping."""
    context = task.get("context")
    if not isinstance(context, Mapping):
        return {}, ["task context is missing or is not an object"]
    raw_filters = context.get("filters")
    issues: list[str] = []
    filters: dict[str, str] = {}
    if isinstance(raw_filters, Mapping):
        source_pairs = list(raw_filters.items())
    elif isinstance(raw_filters, list):
        source_pairs = []
        for index, item in enumerate(raw_filters, start=1):
            if not isinstance(item, Mapping) or set(item) != {"field", "value"}:
                issues.append(f"filter clause {index} must contain exactly 'field' and 'value'")
                continue
            source_pairs.append((item.get("field"), item.get("value")))
    else:
        return {}, ["filters must be a non-empty list of field/value clauses"]

    for raw_field, raw_value in source_pairs:
        if not isinstance(raw_field, str) or not raw_field.strip():
            issues.append("a filter has an invalid field name")
            continue
        field = raw_field.strip()
        if field in filters:
            issues.append(f"filter field {field!r} is duplicated")
            continue
        if not isinstance(raw_value, str) or not raw_value.strip():
            issues.append(f"filter {field!r} has no string value")
            continue
        value = raw_value.strip()
        if value.casefold() in _PLACEHOLDER_VALUES:
            issues.append(
                f"filter {field!r} uses placeholder value {value!r}; absent predicates must be omitted"
            )
            continue
        filters[field] = value
    if not filters and not issues:
        issues.append("filters must contain at least one selection predicate")
    return filters, issues


def _task_field(task: Mapping[str, Any], key: str) -> str:
    value = task.get(key)
    return value.strip() if isinstance(value, str) else ""


def plan_review_issues(
    report: Mapping[str, Any],
    *,
    project_root: Path,
) -> tuple[str, ...]:
    """Return reasons why a ready-looking plan should not be executed yet.

    This is a safety/quality gate, not a repair pass. A malformed plan remains visible to the
    researcher, but the UI and service refuse to execute it until a new plan passes review.
    """
    plan = report.get("plan")
    if not isinstance(plan, Mapping):
        return ("The report does not contain a structured plan object.",)
    raw_tasks = plan.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return ("The plan contains no specialist tasks.",)
    tasks = [item for item in raw_tasks if isinstance(item, Mapping)]
    if len(tasks) != len(raw_tasks):
        return ("The task array contains malformed entries.",)

    question = report.get("question")
    if not isinstance(question, str) or not question.strip():
        question = plan.get("question")
    if not isinstance(question, str):
        question = ""

    issues: list[str] = []
    catalogue_tasks_by_planet: dict[str, list[str]] = {}
    for task in tasks:
        task_key = _task_field(task, "task_key")
        agent_id = _task_field(task, "agent_id")
        if agent_id != "catalogue_data":
            continue
        filters, filter_issues = _filter_map(task)
        if filter_issues:
            visible_filter_issues = filter_issues[:3]
            for issue in visible_filter_issues:
                issues.append(f"Catalogue task {task_key or '(missing task key)'}: {issue}.")
            if len(filter_issues) > len(visible_filter_issues):
                issues.append(
                    f"Catalogue task {task_key or '(missing task key)'} has "
                    f"{len(filter_issues) - len(visible_filter_issues)} additional invalid filter(s)."
                )
        planet_name = filters.get("pl_name")
        if planet_name:
            catalogue_tasks_by_planet.setdefault(planet_name.casefold(), []).append(task_key)

        # A named exact record should not be narrowed by incidental values inferred from
        # identifier fragments. Additional predicates are allowed only when their field name
        # or underscore-expanded field label is explicitly mentioned in the user's question.
        if planet_name:
            query_folded = question.casefold()
            extras = [
                field for field in filters
                if field != "pl_name"
                and field.casefold() not in query_folded
                and field.replace("_", " ").casefold() not in query_folded
            ]
            for field in extras[:3]:
                issues.append(
                    f"Catalogue task {task_key or '(missing task key)'} applies unrequested "
                    f"filter {field!r} alongside exact planet identifier {planet_name!r}. "
                    "Keep only explicit user-requested predicates."
                )
            if len(extras) > 3:
                issues.append(
                    f"Catalogue task {task_key or '(missing task key)'} applies "
                    f"{len(extras) - 3} additional unrequested filter(s)."
                )

    try:
        mentioned_names = _known_names_mentioned(question, project_root)
    except (OSError, ValueError, csv.Error) as exc:
        issues.append(f"Could not verify named planet identifiers against the frozen catalogue: {exc}")
        mentioned_names = ()

    matched_tasks_by_name: dict[str, str] = {}
    for planet_name in mentioned_names:
        matching_keys = catalogue_tasks_by_planet.get(planet_name.casefold(), [])
        if not matching_keys:
            issues.append(
                f"The question explicitly names catalogue planet {planet_name!r}, but no "
                "catalogue_data task filters by that exact pl_name."
            )
        else:
            matched_tasks_by_name[planet_name.casefold()] = matching_keys[0]

    # If a request mentions several known planet records and requests arithmetic or a ratio,
    # require a separate quantitative task with dependencies on all corresponding lookups.
    needs_calculation = len(mentioned_names) >= 2 and bool(_ARITHMETIC_REQUEST.search(question))
    if needs_calculation:
        quantitative_tasks = [
            task for task in tasks if _task_field(task, "agent_id") == "quantitative_analysis"
        ]
        if not quantitative_tasks:
            issues.append(
                "The question names multiple catalogue planets and requests a calculation, but "
                "the plan contains no quantitative_analysis task."
            )
        else:
            required_lookup_keys = {
                matched_tasks_by_name[name.casefold()]
                for name in mentioned_names
                if name.casefold() in matched_tasks_by_name
            }
            has_valid_calculation = False
            for task in quantitative_tasks:
                task_key = _task_field(task, "task_key")
                dependencies = task.get("depends_on", [])
                dependency_set = set(dependencies) if isinstance(dependencies, list) else set()
                context = task.get("context")
                calculations = context.get("calculations", []) if isinstance(context, Mapping) else []
                operand_sources: set[str] = set()
                operations: set[str] = set()
                if isinstance(calculations, list):
                    for calculation in calculations:
                        if not isinstance(calculation, Mapping):
                            continue
                        operation = calculation.get("operation")
                        if isinstance(operation, str):
                            operations.add(operation.casefold())
                        operands = calculation.get("operands", [])
                        if not isinstance(operands, list):
                            continue
                        for operand in operands:
                            if isinstance(operand, Mapping):
                                source_key = operand.get("source_task_key")
                                if isinstance(source_key, str) and source_key.strip():
                                    operand_sources.add(source_key.strip())
                requested_ratio = bool(re.search(r"\bratio\b", question, re.IGNORECASE))
                operation_matches_request = not requested_ratio or "ratio" in operations
                if (
                    calculations
                    and required_lookup_keys.issubset(dependency_set)
                    and required_lookup_keys.issubset(operand_sources)
                    and operation_matches_request
                ):
                    has_valid_calculation = True
                    break
                missing_deps = sorted(required_lookup_keys - dependency_set)
                missing_operands = sorted(required_lookup_keys - operand_sources)
                details: list[str] = []
                if missing_deps:
                    details.append("missing dependencies for " + ", ".join(missing_deps))
                if missing_operands:
                    details.append("missing calculation operands from " + ", ".join(missing_operands))
                if not calculations:
                    details.append("no calculation specification is present")
                if requested_ratio and "ratio" not in operations:
                    details.append("the request asks for a ratio but no ratio operation is specified")
                issues.append(
                    f"Quantitative task {task_key or '(missing task key)'} is incomplete: "
                    + "; ".join(details or ["the calculation does not cover all named records"])
                    + "."
                )
            if not has_valid_calculation:
                issues.append(
                    "No quantitative task depends on and uses source fields from every explicitly "
                    "named planet lookup."
                )

    # Stable order and no duplicate diagnostics make UI output predictable.
    return tuple(dict.fromkeys(issues))
