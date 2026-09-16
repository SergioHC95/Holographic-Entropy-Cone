# Additional n=6 inequalities

This directory contains two collections of n=6 inequality representatives.
Each JSON file contains only primitive integer coefficient rows in the standard
63-coordinate subset order. The rows are canonical representatives under full
S7 symmetry and are sorted lexicographically within each file. No
contraction maps or orbit copies are included.

## Low rank

These are inequalities which are contraction-valid, cannot be shown redundant
wrt known facets, but also don't reach rank 62 wrt existing extreme rays. As a
result, they could be facets (if we are missing the required extreme-ray
graphs) or they could be deemed redundant (if we are missing facets that are
tighter).

The collection is in [`low-rank.json`](low-rank.json) and contains 35,578
representatives after removing 1,609 exact known-facet redundancies (from an
input collection of 37,187 representatives).

## Noncontracting

These are inequalities for which no contraction map exists (deterministic
contradiction, not a timeout), yet none of the existing extreme rays violate
them. Assuming the contraction proof is an iff validity condition, there
should exist graph-realizable rays that violate them and are extreme.

The collection is in [`noncontracting.json`](noncontracting.json) and contains
116 representatives.

## Redundancy cross-check

[`redundancy.json`](redundancy.json) records an exact known-facet-cone
redundancy classification of both collections against the current n=6 facet
database (59,392 facet representatives and 294,562,583 deduplicated facet
images). The canonical inconclusive files contain only the nonredundant rows;
the report records the before/after counts and provenance hashes.

- `low-rank.json`: 1,609 redundant; 35,578 nonredundant
- `noncontracting.json`: 0 redundant; 116 nonredundant
