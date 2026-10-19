"""Schema and query safety tests for the Neo4j-backed graph builder."""

from exotrace.graph.build_graph import (
    BASE_IMPORT_QUERY,
    FACILITY_IMPORT_QUERY,
    METHOD_IMPORT_QUERY,
    NODE_LABELS,
    REFERENCE_IMPORT_QUERY,
    RELATIONSHIP_TYPES,
    SCHEMA_STATEMENTS,
)


def test_schema_has_unique_constraints_for_all_entity_keys() -> None:
    schema = "\n".join(SCHEMA_STATEMENTS)
    for entity_key in (
        "DatasetSnapshot",
        "CatalogueRecord",
        "Planet",
        "HostStar",
        "DiscoveryMethod",
        "DiscoveryFacility",
        "PublicationReference",
    ):
        assert f"{entity_key}) REQUIRE" in schema


def test_base_import_is_idempotent_and_snapshot_scoped() -> None:
    assert "MERGE (record:CatalogueRecord" in BASE_IMPORT_QUERY
    assert "MERGE (planet:Planet" in BASE_IMPORT_QUERY
    assert "MERGE (host:HostStar" in BASE_IMPORT_QUERY
    assert "MERGE (host)-[hosting:HOSTS {snapshot_id: row.snapshot_id}]->(planet)" in BASE_IMPORT_QUERY
    assert "source_record_id = row.record_id" in BASE_IMPORT_QUERY


def test_relationship_catalog_matches_query_model() -> None:
    assert "DatasetSnapshot" in NODE_LABELS
    assert "CatalogueRecord" in NODE_LABELS
    assert "CONTAINS_RECORD" in RELATIONSHIP_TYPES
    assert "HOSTS" in RELATIONSHIP_TYPES
    assert "DETECTED_BY" in RELATIONSHIP_TYPES
    assert "HAS_DISCOVERY_REFERENCE" in RELATIONSHIP_TYPES
    for query in (METHOD_IMPORT_QUERY, FACILITY_IMPORT_QUERY, REFERENCE_IMPORT_QUERY):
        assert "MERGE" in query
        assert "$rows" in query
        assert "source_record_id = row.record_id" in query
