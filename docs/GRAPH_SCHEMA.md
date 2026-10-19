# ExoTrace Neo4j graph schema

## Identity and provenance strategy

The graph deliberately separates stable scientific entities from the source row that
supports each claim. `PSCompPars` is a composite table, so numerical and stellar parameters
are stored on snapshot-scoped `CatalogueRecord` nodes rather than merged into shared
`Planet` or `HostStar` nodes.

## Node labels

- `DatasetSnapshot`: the downloaded raw snapshot, identified by its raw SHA-256 checksum.
- `CatalogueRecord`: one row from the validated `PSCompPars` CSV. Stores original columns,
  missing-field names, source file/row metadata, and the insolation caution classification.
- `Planet`: canonical planet entity identified by `pl_name`.
- `HostStar`: host identity, canonicalized by normalized case-insensitive `hostname`.
- `DiscoveryMethod`: discovery method name.
- `DiscoveryFacility`: discovery facility name.
- `PublicationReference`: exact source reference record with its visible label and optional href.

## Relationship types

- `(:DatasetSnapshot)-[:CONTAINS_RECORD]->(:CatalogueRecord)`
- `(:CatalogueRecord)-[:DESCRIBES_PLANET]->(:Planet)`
- `(:CatalogueRecord)-[:IDENTIFIES_HOST]->(:HostStar)`
- `(:HostStar)-[:HOSTS {snapshot_id, source_record_id}]->(:Planet)`
- `(:CatalogueRecord)-[:USES_DISCOVERY_METHOD]->(:DiscoveryMethod)`
- `(:Planet)-[:DETECTED_BY {snapshot_id, source_record_id}]->(:DiscoveryMethod)`
- `(:CatalogueRecord)-[:USES_DISCOVERY_FACILITY]->(:DiscoveryFacility)`
- `(:Planet)-[:DISCOVERED_AT {snapshot_id, source_record_id}]->(:DiscoveryFacility)`
- `(:CatalogueRecord)-[:CITES_DISCOVERY_REFERENCE]->(:PublicationReference)`
- `(:Planet)-[:HAS_DISCOVERY_REFERENCE {snapshot_id, source_record_id}]->(:PublicationReference)`

Direct relationships that can support investigation carry `snapshot_id` and
`source_record_id`, so an answer can be traced back to the exact catalogue row. Entity
nodes are merged by unique constraints, and the importer uses `MERGE` for idempotency.

## Measurement semantics

Original source fields, uncertainty fields, limit flags, and reference markup remain on each
`CatalogueRecord`. Missing values remain missing. Zero insolation linked to the archive's
`CALCULATED_VALUE` marker is classified as `calculated_zero_requires_caution`; the value is
not overwritten or silently converted to null. Any derived diagnostic estimate is kept
outside the authoritative source fields.
