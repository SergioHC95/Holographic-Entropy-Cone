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

The collection is in [`low-rank.json`](low-rank.json) and contains 37,187
representatives.

## Noncontracting

These are inequalities for which no contraction map exists (deterministic
contradiction, not a timeout), yet none of the existing extreme rays violate
them. Assuming the contraction proof is an iff validity condition, there
should exist graph-realizable rays that violate them and are extreme.

The collection is in [`noncontracting.json`](noncontracting.json) and contains
482 representatives.
