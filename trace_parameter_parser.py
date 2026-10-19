"""Trace the exact first-pass decisions of ExoTrace's NASA parser."""

import importlib
import json

from bs4 import BeautifulSoup

parser = importlib.import_module(
    "exotrace.vector.extract_parameter_definitions"
)

manifest_path = parser.PROJECT_ROOT / parser.REFERENCE_MANIFEST_PATH
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

page = next(
    item for item in manifest["pages"]
    if item.get("slug") == parser.SOURCE_SLUG
)

source_path = parser.PROJECT_ROOT / page["raw_file"]
raw_bytes = source_path.read_bytes()
html = raw_bytes.decode("utf-8", errors="replace")

expected_fields = set(
    map(
        str,
        parser.load_snapshot_bundle(parser.PROJECT_ROOT).dataframe.columns,
    )
)

targets = {"pl_orbper", "pl_orbeccen", "pl_insol"}
seen_fields = set()
soup = BeautifulSoup(html, "html.parser")

print("Parser:", parser.__file__)
print("Expected fields:", {
    field: field in expected_fields for field in sorted(targets)
})
print()

for table_number, table in enumerate(soup.find_all("table"), start=1):
    for row_number, row in enumerate(table.find_all("tr"), start=1):
        cells = row.find_all(["th", "td"], recursive=False)

        if len(cells) < 3:
            continue

        raw_texts = [
            cell.get_text(" ", strip=True) for cell in cells
        ]
        cleaned_texts = [
            parser._clean_text(value) for value in raw_texts
        ]

        raw_field = parser._field_name(raw_texts[0])
        field = parser._field_name(cleaned_texts[0])

        if raw_field not in targets and field not in targets:
            continue

        if not field:
            decision = "SKIP: empty normalized field"
        elif field not in expected_fields:
            decision = "SKIP: field not in expected schema"
        elif field in seen_fields:
            decision = "SKIP: already seen"
        elif "_" not in field:
            decision = "SKIP: no underscore"
        elif not cleaned_texts[1].strip() and not cleaned_texts[2].strip():
            decision = "SKIP: both label and description empty"
        else:
            decision = "ACCEPT"
            seen_fields.add(field)

        print(f"Table {table_number}, row {row_number}")
        print("  Raw first cell:    ", repr(raw_texts[0]))
        print("  Cleaned first cell:", repr(cleaned_texts[0]))
        print("  Raw normalized:    ", repr(raw_field))
        print("  Final field:       ", repr(field))
        print("  Already seen:      ", field in seen_fields if decision == "SKIP: already seen" else False)
        print("  Label:             ", repr(cleaned_texts[1]))
        print("  Description:       ", repr(cleaned_texts[2]))
        print("  Decision:          ", decision)
        print()

print("First-pass accepted target fields:", sorted(seen_fields & targets))
