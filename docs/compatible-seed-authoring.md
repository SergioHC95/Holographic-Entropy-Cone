# Exact compatible-domain proof authoring

`examples/compatible_seed_authoring.py` is a saved candidate constructor for
the sole `compatible-reconstruction-pipeline/1` proof language. It changes
where a candidate is searched, not the mathematical acceptance contract.

## Construction

1. Derive the exact weighted source geometry and complete compatible domain
   from the primitive inequality in its declared party frame.
2. For every pair of occurrence anchors, apply the triangle inequality to
   bound each output count. Twice each bound is an integer; no floating
   arithmetic or tolerance is used.
3. Search count values only on compatible vertices. An RHS group of capacity
   `beta` at scale `D` has an ordered prefix of `D*beta` Boolean positions.
   Prefix Hamming distance equals absolute count distance, so exact SAT
   cardinality clauses impose every compatible weighted-edge constraint.
   Prefix order is within an RHS group, not source-coordinate monotonicity.
   Kissat uses the existing package settings.
4. Recheck anchors, bounds and compatible edges with exact integers, then
   divide counts by `D` and build the existing deterministic fixed extension.
5. Run the independent verifier on every original-cube vertex and edge.
   The standard dataset writer independently audits every definition again
   before atomically publishing the new dataset and exact inequality bindings.

The constructor has finite authoring resource capabilities and an explicit
positive integer scale. Failure, a resource limit or unsatisfiability at one
scale is **not** a claim that the inequality is invalid or has no other proof.
There is no solver wall-clock timeout or floating-point acceptance path.
SAT models and original enumerated tables are not accepted repository artifacts.

## Reproduce the PR #238 subset

After the locked setup and native build in the repository pipeline guide:

```bash
uv run python examples/compatible_seed_authoring.py \
  --rows data/n=6/facets.json --n 6 \
  --case-index provenance/contractions/pr238-20261015/case-index.json \
  --output /tmp/hec-pr238-regenerated
```

Use a new output directory: existing datasets are never overwritten. Each
saved definition is deterministic to reconstruct and independently check;
different solver versions can find different valid maps, so regenerated
proof identities need not equal the committed ones.

All 357 committed PR #238 definitions passed fresh writer audits covering
5,095,424 vertices and 36,112,384 original weighted-cube edges. Most were
constructed with the existing public full-cube search API; the new constructor
independently completed and audited the two remaining compact-domain controls.
No claim is made that this alternative method has been benchmarked on all
85,047 maps. Original journals were not recovered: source commit, exact normals,
new definitions, frozen runtime information and executed audits are recorded
under `provenance/contractions/pr238-20261015/`.

On this device, compact-domain controls `fe8fb9ef...` and `ef4641b5...`
completed construction and full-cube auditing in approximately 1.05 s and
2.94 s. They searched 2,502 and 5,150 compatible vertices instead of 65,536
original vertices, respectively. These are case-specific observations, not
a universal speedup guarantee. Unit tests include actual subadditivity,
weighted and MMI maps at two scales, a real PR row and complete-cube audits.

Contraction validity is separate from facethood. The 357 listed additions
also passed exact modular tight-support rank 62, a strict positive graph-backed
witness and nonnegative pairings with every listed representative ray. Their
source facet representatives were separately checked against the existing
corpus and each other under the full S7 symmetry action.
