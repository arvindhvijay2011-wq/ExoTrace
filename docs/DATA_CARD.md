# ExoTrace data card (initial)

## Source

NASA Exoplanet Archive `PSCompPars` table via the official TAP service.

## Intended use

A small, reproducible prototype for investigating confirmed exoplanet catalogue records, host-star relationships, discovery metadata, and selected physical/orbital parameters.

## Not intended for

- replacing peer-reviewed scientific analysis;
- asserting that every parameter in a composite row comes from one internally consistent solution;
- inferring habitability or life from one parameter;
- filling missing measurements with language-model guesses;
- treating generated planet profiles as independent evidence.

## Known caveats

- Different parameters may be drawn from different sources or may be calculated by the archive.
- Availability varies by parameter, and measurements can include asymmetric uncertainty, limits, and missing values.
- The archive changes over time. The fetch manifest must identify the precise query and retrieval timestamp.
- Graph edges beyond direct catalogue support must not be inferred merely because two objects have similar properties.

## Required validation before indexing

- Confirm `pl_name` and `hostname` are present.
- Check duplicate `pl_name` values and investigate rather than silently deduplicating.
- Summarize missingness per column.
- Preserve error bars, limit flags, and reference links.
- Record the raw snapshot SHA-256.
- Run data validation again whenever the snapshot changes.
