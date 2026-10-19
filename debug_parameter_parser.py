
"""Diagnose NASA parameter extraction without changing project data."""

import importlib
import json

from bs4 import BeautifulSoup
from exotrace.graph.build_graph import load_snapshot_bundle

parser = importlib.import_module(
    "exotrace.vector.extract_parameter_definitions"
)

print("Loaded parser:", parser.__file__)
print("Project root:", parser.PROJECT_ROOT)

manifest_path = parser.PROJECT_ROOT / parser.REFERENCE_MANIFEST_PATH
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

page = next(
    (
        item
        for item in manifest["pages"]
        if item.get("slug") == parser.SOURCE_SLUG
    ),
    None,
)

if page is None:
    raise RuntimeError("NASA parameter-page entry not found in manifest.")

source_path = parser.PROJECT_ROOT / page["raw_file"]
raw_bytes = source_path.read_bytes()
actual_hash = parser.sha256_bytes(raw_bytes)

print("Frozen HTML:", source_path)
print("Manifest SHA-256 matches:", actual_hash == page["raw_sha256"])
print("Field normalizer:", repr(parser._field_name("pl_insol†")))

bundle = load_snapshot_bundle(parser.PROJECT_ROOT)
expected_fields = set(map(str, bundle.dataframe.columns))

print("Expected pl_insol:", "pl_insol" in expected_fields)
print("Expected pl_orbeccen:", "pl_orbeccen" in expected_fields)

html = raw_bytes.decode("utf-8", errors="replace")

rows = parser._parse_source_rows(
    html,
    page["url"],
    actual_hash,
    expected_fields=expected_fields,
)

targets = {"pl_insol", "pl_orbeccen", "pl_orbper"}

print("\n=== Rows returned by the parser ===")

for row in rows:
    if row["field"] in targets:
        print(json.dumps(row, indent=2, ensure_ascii=False))

print("\n=== Raw source rows ===")

soup = BeautifulSoup(html, "html.parser")

for tr in soup.find_all("tr"):
    cells = tr.find_all(["th", "td"], recursive=False)
    values = [cell.get_text(" ", strip=True) for cell in cells]

    if values and parser._field_name(values[0]) in targets:
        print(json.dumps(values, ensure_ascii=False))

print("\n=== Existing generated definitions ===")

output_path = parser.PROJECT_ROOT / parser.OUTPUT_JSONL

if output_path.exists():
    for line in output_path.read_text(encoding="utf-8").splitlines():
        document = json.loads(line)
        field = document.get("metadata", {}).get("parameter_field")

        if field in targets:
            print(
                field,
                "|",
                document.get("title"),
                "|",
                document.get("metadata", {}).get("definition_extraction"),
            )
else:
    print("No generated definitions file exists yet.")

print("\nDiagnostic finished. No project data was modified.")
