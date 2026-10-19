"""Unit tests for NASA parameter source ingestion."""

from __future__ import annotations

import hashlib


from exotrace.vector import extract_parameter_definitions as extractor
from exotrace.vector.extract_parameter_definitions import _field_name, _header_indices

SOURCE_URL = "https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html"


def test_field_name_removes_source_default_marker() -> None:
    assert _field_name("pl_orbeccen†") == "pl_orbeccen"
    assert _field_name("pl_orbper_reflink") == "pl_orbper_reflink"
    assert _field_name("not a field label") is None


def test_header_mapping_detects_schema_columns() -> None:
    headers = [
        "Database Column Name", "Table Label", "Description",
        "Uncertainties Column (positive +) (negative -)", "Limit Column",
        "In PS Table", "In PSCompPars Table",
    ]
    mapping = _header_indices(headers)
    assert mapping is not None
    assert mapping["field"] == 0
    assert mapping["label"] == 1
    assert mapping["description"] == 2
    assert mapping["uncertainties"] == 3
    assert mapping["limit"] == 4
    assert mapping["in_ps"] == 5
    assert mapping["in_pscomppars"] == 6


def test_field_name_keeps_canonical_schema_identity() -> None:
    assert _field_name("pl_orbeccenerr1") == "pl_orbeccenerr1"
    assert _field_name("pl_orbeccenlim") == "pl_orbeccenlim"


def test_parser_recovers_rows_when_table_headers_are_separate() -> None:
    """Recover verbatim fields from data rows even when their header table is separate."""
    html = """
    <html><body>
      <table>
        <tr><th>Database Column Name</th><th>Table Label</th><th>Description</th>
            <th>Uncertainties Column (positive +) (negative -)</th><th>Limit Column</th>
            <th>In PS Table</th><th>In PSCompPars Table</th></tr>
        <tr><td>pl_orbper</td><td>Orbital Period [days]</td>
            <td>Time the planet takes to make a complete orbit around the host star or system</td>
            <td>(+) pl_orbpererr1 (-) pl_orbpererr2</td><td>pl_orbperlim</td><td>X</td><td>X</td></tr>
      </table>
      <h2>Planet Parameters Continued</h2>
      <table>
        <tr><td>pl_orbeccen†</td><td>Eccentricity</td>
            <td>Amount by which the orbit of the planet deviates from a perfect circle</td>
            <td>(+) pl_orbeccenerr1 (-) pl_orbeccenerr2</td><td>pl_orbeccenlim</td><td>X</td><td>X</td></tr>
        <tr><td>pl_insol†</td><td>Insolation Flux [Earth Flux]</td>
            <td>Insolation flux is another way to give the equilibrium temperature. It is given in units relative to those measured for the Earth from the Sun.</td>
            <td>(+) pl_insolerr1 (-) pl_insolerr2</td><td>pl_insollim</td><td>X</td><td>X</td></tr>
      </table>
    </body></html>
    """
    rows = extractor._parse_source_rows(
        html, SOURCE_URL, hashlib.sha256(html.encode("utf-8")).hexdigest(),
        expected_fields={"pl_orbper", "pl_orbeccen", "pl_insol"},
    )
    by_field = {row["field"]: row for row in rows}

    assert by_field["pl_orbeccen"]["label"] == "Eccentricity"
    assert by_field["pl_orbeccen"]["parse_method"] == "source_row_first_cell"
    assert by_field["pl_insol"]["label"] == "Insolation Flux [Earth Flux]"
    assert by_field["pl_insol"]["parse_method"] == "source_row_first_cell"
    assert "perfect circle" in by_field["pl_orbeccen"]["description"]


def test_parser_uses_body_row_positions_when_header_column_indices_are_misaligned() -> None:
    """Recover source fields when grouped header columns do not align with body cells."""
    html = """
    <html><body>
      <table>
        <tr><th>Group</th><th>Database Column Name</th><th>Table Label</th>
            <th>Description</th><th>Uncertainties Column (positive +) (negative -)</th>
            <th>Limit Column</th><th>In PS Table</th><th>In PSCompPars Table</th></tr>
        <tr><td>Planet data</td><td>pl_orbper</td><td>Orbital Period [days]</td>
            <td>Time the planet takes to make a complete orbit around the host star or system</td>
            <td>(+) pl_orbpererr1 (-) pl_orbpererr2</td><td>pl_orbperlim</td><td>X</td><td>X</td></tr>
      </table>
      <table>
        <tr><th>Database Column Name</th><th>Table Label</th><th>Description</th>
            <th>Uncertainties Column (positive +) (negative -)</th><th>Limit Column</th>
            <th>In PS Table</th><th>In PSCompPars Table</th></tr>
        <tr><td>pl_orbeccen†</td><td>Eccentricity</td>
            <td>Amount by which the orbit of the planet deviates from a perfect circle</td>
            <td>(+) pl_orbeccenerr1 (-) pl_orbeccenerr2</td><td>pl_orbeccenlim</td><td>X</td><td>X</td></tr>
        <tr><td>pl_insol†</td><td>Insolation Flux [Earth Flux]</td>
            <td>Insolation flux is another way to give the equilibrium temperature. It is given in units relative to those measured for the Earth from the Sun.</td>
            <td>(+) pl_insolerr1 (-) pl_insolerr2</td><td>pl_insollim</td><td>X</td><td>X</td></tr>
      </table>
    </body></html>
    """
    rows = extractor._parse_source_rows(
        html, SOURCE_URL, hashlib.sha256(html.encode("utf-8")).hexdigest(),
        expected_fields={"pl_orbper", "pl_orbeccen", "pl_insol"},
    )
    by_field = {row["field"]: row for row in rows}

    assert "pl_orbeccen" in by_field
    assert "pl_insol" in by_field
    assert by_field["pl_orbeccen"]["label"] == "Eccentricity"
    assert by_field["pl_insol"]["label"] == "Insolation Flux [Earth Flux]"
    assert "perfect circle" in by_field["pl_orbeccen"]["description"]


def test_source_first_cell_rows_are_extracted_even_when_header_indices_mislead() -> None:
    """The frozen NASA rows must be read from their observed body-cell order."""
    html = """
    <html><body>
      <table>
        <tr><th>Grouped parameter metadata</th><th>Database Column Name</th>
            <th>Table Label</th><th>Description</th>
            <th>Uncertainties Column (positive +) (negative -)</th>
            <th>Limit Column</th><th>In PS Table</th><th>In PSCompPars Table</th></tr>
        <tr><td>pl_orbper†</td><td>Orbital Period [days]</td>
            <td>Time the planet takes to make a complete orbit around the host star or system</td>
            <td>(+) pl_orbpererr1 (-) pl_orbpererr2</td><td>pl_orbperlim</td><td>X</td><td>X</td></tr>
        <tr><td>pl_orbeccen†</td><td>Eccentricity</td>
            <td>Amount by which the orbit of the planet deviates from a perfect circle</td>
            <td>(+) pl_orbeccenerr1 (-) pl_orbeccenerr2</td><td>pl_orbeccenlim</td><td>X</td><td>X</td></tr>
        <tr><td>pl_insol†</td><td>Insolation Flux [Earth Flux]</td>
            <td>Insolation flux is another way to give the equilibrium temperature. It is given in units relative to those measured for the Earth from the Sun.</td>
            <td>(+) pl_insolerr1 (-) pl_insolerr2</td><td>pl_insollim</td><td>X</td><td>X</td></tr>
      </table>
    </body></html>
    """
    rows = extractor._parse_source_rows(
        html,
        SOURCE_URL,
        hashlib.sha256(html.encode("utf-8")).hexdigest(),
        expected_fields={"pl_orbper", "pl_orbeccen", "pl_insol"},
    )
    by_field = {row["field"]: row for row in rows}

    assert set(by_field) >= {"pl_orbper", "pl_orbeccen", "pl_insol"}
    assert by_field["pl_orbeccen"]["label"] == "Eccentricity"
    assert by_field["pl_orbeccen"]["description"] == (
        "Amount by which the orbit of the planet deviates from a perfect circle"
    )
    assert by_field["pl_insol"]["label"] == "Insolation Flux [Earth Flux]"
    assert by_field["pl_insol"]["parse_method"] == "source_row_first_cell"


def test_parser_recovers_valid_rows_not_attached_to_table_element() -> None:
    """NASA continuation rows can be visible to the document parser but orphaned from tables."""
    html = """
    <html><body>
      <table>
        <tr><td>pl_orbper†</td><td>Orbital Period [days]</td>
            <td>Time the planet takes to make a complete orbit around the host star or system</td>
            <td>(+) pl_orbpererr1 (-) pl_orbpererr2</td><td>pl_orbperlim</td><td>X</td><td>X</td></tr>
      </table>
      <h2>Planet Parameters Continued</h2>
      <tr><td>pl_orbeccen†</td><td>Eccentricity</td>
          <td>Amount by which the orbit of the planet deviates from a perfect circle</td>
          <td>(+) pl_orbeccenerr1 (-) pl_orbeccenerr2</td><td>pl_orbeccenlim</td><td>X</td><td>X</td></tr>
      <tr><td>pl_insol†</td><td>Insolation Flux [Earth Flux]</td>
          <td>Insolation flux is another way to give the equilibrium temperature. It is given in units relative to those measured for the Earth from the Sun.</td>
          <td>(+) pl_insolerr1 (-) pl_insolerr2</td><td>pl_insollim</td><td>X</td><td>X</td></tr>
    </body></html>
    """
    soup = extractor.BeautifulSoup(html, "html.parser")
    orphan_fields = {
        _field_name(row.find(["th", "td"], recursive=False).get_text(" ", strip=True))
        for row in soup.find_all("tr")
        if row.find_parent("table") is None
    }
    assert {"pl_orbeccen", "pl_insol"}.issubset(orphan_fields)

    rows = extractor._parse_source_rows(
        html, SOURCE_URL, hashlib.sha256(html.encode("utf-8")).hexdigest(),
        expected_fields={"pl_orbper", "pl_orbeccen", "pl_insol"},
    )
    by_field = {row["field"]: row for row in rows}

    assert by_field["pl_orbeccen"]["parse_method"] == "source_row_first_cell"
    assert by_field["pl_insol"]["parse_method"] == "source_row_first_cell"
    assert by_field["pl_orbeccen"]["description"] == (
        "Amount by which the orbit of the planet deviates from a perfect circle"
    )
