import importlib
import json
from bs4 import BeautifulSoup

parser = importlib.import_module(
    "exotrace.vector.extract_parameter_definitions"
)

manifest = json.loads(
    (parser.PROJECT_ROOT / parser.REFERENCE_MANIFEST_PATH)
    .read_text(encoding="utf-8")
)
page = next(
    item for item in manifest["pages"]
    if item.get("slug") == parser.SOURCE_SLUG
)
html = (
    parser.PROJECT_ROOT / page["raw_file"]
).read_text(encoding="utf-8")

targets = ("pl_orbper", "pl_orbeccen", "pl_insol")
soup = BeautifulSoup(html, "html.parser")
matches = 0

for row_number, row in enumerate(soup.find_all("tr"), start=1):
    cells = row.find_all(["th", "td"], recursive=False)
    if not cells:
        continue

    first_cell = cells[0].get_text(" ", strip=True)

    if any(target in first_cell for target in targets):
        matches += 1
        cleaned = parser._clean_text(first_cell)

        print(f"\nHTML row #{row_number}")
        print("Raw first cell:      ", repr(first_cell))
        print("Cleaned first cell:  ", repr(cleaned))
        print("Normalized raw:      ", repr(parser._field_name(first_cell)))
        print("Normalized cleaned:  ", repr(parser._field_name(cleaned)))
        print("Cell count:          ", len(cells))
        print("All cells:           ", [
            cell.get_text(" ", strip=True) for cell in cells
        ])

print(f"\nTotal matching raw rows: {matches}")
