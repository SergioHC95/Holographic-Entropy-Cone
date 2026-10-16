# Exact compatible-domain proof authoring

`examples/compatible_seed_authoring.py` constructs candidates in the sole
`compatible-reconstruction-pipeline/1` proof language. It searches a smaller
domain without changing the full-map verification contract.

## Construction

1. Derive the exact weighted source geometry and complete compatible domain
   from a primitive integer inequality in its declared party frame.
2. Apply boundary-pair triangle inequalities to bound each output count using
   exact doubled integers, with no floating-point tolerance.
3. Search compatible vertices with ordered prefix bits within each repeated
   RHS group. Prefix Hamming distance equals absolute count distance; exact
   SAT cardinality clauses impose compatible weighted-edge constraints.
   This is not source-coordinate monotonicity. Kissat uses the package settings.
4. Recheck anchors, bounds and compatible edges with exact integers, divide
   counts by the explicit scale, and build the standard fixed extension.
5. Independently audit every original-cube vertex and weighted edge. The
   standard dataset writer repeats full-map verification before atomic publication.

The constructor has finite resource capabilities and an explicit positive
integer scale. A resource limit or unsuccessful search at one scale is not
a claim that the inequality is invalid or has no other proof. Solver models
are transient; only complete self-contained standard definitions are published.

## Usage

After the locked setup and native build in the repository pipeline guide:

```bash
uv run python examples/compatible_seed_authoring.py \
  --rows data/n=2/facets.json --n 2 --output contractions_example
```

Input is an integer-row JSON file in the repository subset order. To process a
subset, supply only those rows. Output must be a new directory: existing
datasets are never overwritten. Use `--scale D` for a larger exact search scale.

Each saved proof is deterministic to reconstruct and independently check.
Different solver versions can find different valid maps and proof identities.
Contraction validity and facet/ray rank are separate mathematical checks.
