# Archive-backed S7 facet proof supplement

`archive-mapbacked-facets-20261003.zip` is a supplemental, canonical-S7-indexed proof catalog built from the supplied HEC6 archive and compared against the `origin/main` dataset at base commit `738503a930154ee2f56dc1700d2bf15ce9797be3`.

It contains 4,463 distinct six-party facet claims absent from the base dataset, each with one map/certificate payload already present in the source archive: 22 full-cube binary maps and 4,441 compatible-domain rational count maps. The latter are proofs on the complete compatible mincut domain, not Boolean maps on the full cube.

The row index is also available separately as `archive-mapbacked-facets-20261003.index.jsonl.gz`; its `.sha256` file binds it to the catalog embedded in the ZIP.

The ZIP includes canonical 63-coordinate normals, row-to-source bindings, exact original compressed map bytes, source map catalogs/replay receipts, proof-format notes, a manifest, and a SHA-256 sidecar. No contractions were generated for this supplement. The source packages' proof/replay statuses are preserved as source claims; the package assembly verified row/payload hashes but did not independently replay all map edges.

The repository's existing `contractions.json` format represents full-cube contraction maps only. To avoid encoding compatible-domain certificates as cube maps, this supplement is separate from the official `facets.json`/`contractions.json` arrays. The 162 additional accepted-facet claims in the source archive without a located map payload are not included.

The 4,463 count is after full-S7 canonical deduplication, including purifier permutations, against the 80,213 facets at the stated base. Source snapshots and the 4,397-row map chain overlap; their counts must not be added.
