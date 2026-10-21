# External 46D fixed-10 graph-realization screen

This directory is a research record, deliberately separate from the accepted
`data/n=6` catalogue. It contains the 722 graph realizations found in a
complete fixed-10 native model for an externally supplied set of canonical
candidate rays.

Every JSONL record was independently replayed against this repository base:

- its 63-coordinate vector and SHA-256 binding were checked;
- all 5,040 `S_7` images were checked for canonicality;
- all 504 terminal/bulk rational cuts of the three-bulk graph were enumerated
  exactly;
- the current repository graph checker accepted the graph; and
- the ray was checked not to overlap the current accepted ray catalogue.

The model constructs an exactly ten-vertex graph. A lower-vertex graph may be
lifted to ten vertices by positive-edge subdivision, so these records certify
realizability with **at most ten vertices**, but do **not** establish minimal
vertex count.

## Deliberate boundary

The source export establishes extremality only for its supplied inequality-bank
face. It does not by itself establish that these candidates are accepted
extreme rays of the repository's full HEC catalogue. Therefore this directory
does not change `data/n=6`, `data/storage.json`, catalogue counts, proofs, or
the public ray/graph API. The records are graph-realization evidence awaiting a
separate full repository eligibility/extremality admission audit.

`manifest.json` identifies the input and audit bindings; `audit-report.json`
records the replay result; `realizations.jsonl` contains one deterministic
record per positive candidate.
