"""Apply a narrowly scoped ExoTrace retrieval-scope fix.

The patch adds source-derived NASA parameter definitions to the existing
'references' scope. It does not modify the dataset, corpus, FAISS index, or Neo4j.
"""
from __future__ import annotations

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parent
RETRIEVER_PATH = PROJECT_ROOT / "src" / "exotrace" / "vector" / "retrieve.py"

OLD_CONSTANTS = (
    'REFERENCE_DOC_TYPE = "official_nasa_reference_chunk"\n'
    'PROFILE_DOC_TYPE = "planet_profile"'
)
NEW_CONSTANTS = (
    'REFERENCE_DOC_TYPE = "official_nasa_reference_chunk"\n'
    'PARAMETER_DEFINITION_DOC_TYPE = "official_nasa_parameter_definition"\n'
    'PROFILE_DOC_TYPE = "planet_profile"'
)
OLD_SCOPE = (
    '    if scope == "references":\n'
    '        return {REFERENCE_DOC_TYPE}'
)
NEW_SCOPE = (
    '    if scope == "references":\n'
    '        return {REFERENCE_DOC_TYPE, PARAMETER_DEFINITION_DOC_TYPE}'
)


def replace_once(source: str, old: str, new: str, description: str) -> str:
    """Replace exactly one known source fragment or fail safely."""
    count = source.count(old)
    if count == 1:
        return source.replace(old, new, 1)
    if count == 0 and new in source:
        print(f"Already applied: {description}")
        return source
    raise RuntimeError(
        f"Expected exactly one occurrence for {description}, found {count}. "
        "No file has been written. Inspect retrieve.py before proceeding."
    )


def update_legacy_scope_assertions(project_root: Path) -> None:
    """Update direct singleton-scope assertions in tests, when present."""
    patterns = [
        (
            re.compile(r'(allowed_doc_types\(\s*["\']references["\']\s*\)\s*==\s*)\{\s*REFERENCE_DOC_TYPE\s*\}'),
            r'\1{REFERENCE_DOC_TYPE, PARAMETER_DEFINITION_DOC_TYPE}',
        ),
        (
            re.compile(r'(allowed_doc_types\(\s*["\']references["\']\s*\)\s*==\s*)\{\s*["\']official_nasa_reference_chunk["\']\s*\}'),
            r'\1{"official_nasa_reference_chunk", "official_nasa_parameter_definition"}',
        ),
    ]
    tests_root = project_root / "tests"
    if not tests_root.is_dir():
        return

    for test_path in tests_root.rglob("*.py"):
        original = test_path.read_text(encoding="utf-8")
        updated = original
        for pattern, replacement in patterns:
            updated = pattern.sub(replacement, updated)
        if updated == original:
            continue

        # Add the new constant to common imports if a rewritten assertion uses it.
        if "PARAMETER_DEFINITION_DOC_TYPE" in updated and "PARAMETER_DEFINITION_DOC_TYPE" not in original:
            multiline_import = "from exotrace.vector.retrieve import ("
            if multiline_import in updated:
                updated = updated.replace(
                    multiline_import,
                    multiline_import + "\n    PARAMETER_DEFINITION_DOC_TYPE,",
                    1,
                )
            else:
                single_import = re.compile(
                    r'(from exotrace\.vector\.retrieve import [^\n]*\bREFERENCE_DOC_TYPE\b)'
                )
                updated, count = single_import.subn(
                    lambda match: match.group(1).replace(
                        "REFERENCE_DOC_TYPE",
                        "REFERENCE_DOC_TYPE, PARAMETER_DEFINITION_DOC_TYPE",
                        1,
                    ),
                    updated,
                    count=1,
                )
                if count == 0:
                    # Leave tests using alternate import styles untouched; pytest will
                    # expose any stale assertion for a precise manual correction.
                    updated = original
                    continue

        test_path.write_text(updated, encoding="utf-8")
        print(f"Updated legacy scope assertion: {test_path.relative_to(project_root)}")


def main() -> None:
    """Apply the scope patch, update direct stale tests, and verify the scope."""
    if not RETRIEVER_PATH.is_file():
        raise FileNotFoundError(f"ExoTrace retriever not found: {RETRIEVER_PATH}")

    source = RETRIEVER_PATH.read_text(encoding="utf-8")
    patched = replace_once(source, OLD_CONSTANTS, NEW_CONSTANTS, "parameter document type constant")
    patched = replace_once(patched, OLD_SCOPE, NEW_SCOPE, "references scope allowlist")

    # Verify both intended edits before writing anything.
    if "PARAMETER_DEFINITION_DOC_TYPE = \"official_nasa_parameter_definition\"" not in patched:
        raise RuntimeError("Parameter-definition document type constant is missing after patch.")
    if NEW_SCOPE not in patched:
        raise RuntimeError("References scope does not include parameter definitions after patch.")

    if patched != source:
        backup = RETRIEVER_PATH.with_suffix(".py.pre_reference_scope_fix.bak")
        if not backup.exists():
            backup.write_text(source, encoding="utf-8")
        RETRIEVER_PATH.write_text(patched, encoding="utf-8")
        print(f"Updated: {RETRIEVER_PATH}")
        print(f"Backup:  {backup}")
    else:
        print("Retriever already contains the expected fix; no changes needed.")

    update_legacy_scope_assertions(PROJECT_ROOT)

    print("References scope now allows:")
    print("  - official_nasa_reference_chunk")
    print("  - official_nasa_parameter_definition")
    print("Planet profile routing is unchanged.")
    print("No corpus, FAISS index, NASA snapshot, or Neo4j data was modified.")


if __name__ == "__main__":
    main()
