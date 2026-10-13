# Exact contraction proof standard

The authoritative certificate is an exact definition of a function on the
entire original source cube. It has one rational count per distinct RHS
support. Explicit Boolean tables are optional audit exports, not the standard
repository interface. This first standard covers contractions, their
inequality identities, and migration provenance. It does not change graph,
ray, or facet rank certificates.

The implementation is in `hec.count_proofs` and `hec.proof_store`. Their readers
accept only the new format. Historical JSON and bit tables enter through an
offline importer, never through a fallback in the new verifier. The existing
published dataset is not cut over until its complete migration and LFS
publication have passed; adding these tools does not silently replace it.

## Inequality and coordinate conventions

An inequality is a primitive integer vector in a declared party frame:

```text
sum_i alpha_i S(I_i) >= sum_g beta_g S(J_g).
```

Physical parties are `0,...,n-1`; atom `n` is the purifier. Coordinates are
nonempty subsets in cardinality then lexicographic order. Positive entries
give distinct source supports `I_i`, capacities `alpha_i`, and source axes in
that order. Negative entries give distinct RHS supports `J_g` and capacities
`beta_g`. Source axis `i` is integer bit `i`. An inequality's identifier binds
`n` and its coefficient vector, not a solver name or a facet-file position.

Positive overall coefficient scaling is removed in the importer and must be
recorded in its receipt. The orientation is never reversed. Historical party
representatives are not silently permuted to a different symmetry frame.
Permutation, purifier complement, and changes of frame require explicit
transformations and receipts.

The zero normal is allowed as a trivial inequality, not as a facet.

Contraction validity establishes a valid inequality. It does **not** establish
facethood, uniqueness of its symmetry orbit, or a tight-witness rank. Those
claims need their own verified records.

## Mathematical acceptance contract

For `L` positive supports and `G` distinct negative supports, a certificate
defines

```text
F : {0,1}^L -> Q^G.
```

Acceptance requires:

1. Every coordinate satisfies `0 <= F_g(x) <= beta_g` at every source vertex.
2. For each physical party and the purifier, its occurrence vector has
   `F_g(x(atom)) = beta_g` if the atom belongs to `J_g`, and zero otherwise.
   Conflicting boundary prescriptions are rejected.
3. Every source edge of axis `i` satisfies
   `sum_g |F_g(x)-F_g(x xor 2^i)| <= alpha_i`.

The verifier uses integer cross products for rational comparisons. There is
no tolerance, floating-point acceptance, missing-vertex allowance, or
"inherited valid" status. Full-table verification visits exactly
`L * 2**(L-1)` edges when `L>0`. Edge contraction implies contraction between
arbitrary vertices by a shortest weighted cube path and the triangle inequality.

### Explicit scaling and Boolean realization

Let `D` be a positive integer clearing all values of `F`. The source capacities
are then `D*alpha_i`. Define RHS group `g` as `D*beta_g` Boolean positions,
with `D*F_g(x)` ones followed by zeros. Prefix Hamming distance is

```text
sum_g |D*F_g(x)-D*F_g(y)| <= D*d_alpha(x,y).
```

Thus a rational count map gives a positively scaled Boolean proof of the
same homogeneous inequality. Integral counts have scale one. A scaled proof
must not be labelled an unscaled Boolean-output map. The source dimension
remains `L`; scaling does not manufacture extra source coordinates.

Decision diagrams record their minimal common denominator. The kernel construction
records a derived sufficient clearing scale, explicitly marked nonminimal.
The verifier recomputes both rather than trusting the declaration. Neither
the primary certificate nor verification expands the potentially enormous
virtual Boolean output.

## Canonical proof document

The version identifier is `hec-count-proof/1`. Its fields are exactly:

```json
{
  "format": "hec-count-proof/1",
  "inequality": {"n": 2, "coefficients": ["2", "1", "-1"]},
  "function": {
    "kind": "count-decision-dag/1",
    "terminals": [["0", "1"], ["1", "2"], ["1", "1"]],
    "nodes": [[0, 0, 2], [0, 2, 1], [1, 3, 4]],
    "roots": [5]
  },
  "clearing_scale": {"value": "2", "minimal": true}
}
```

This example's images are `0,1,1,1/2`. It is a full map, not a list of
successful searches. Unknown fields, duplicate keys, floating-point numbers,
noncanonical decimal integers, malformed row encodings, or unknown versions
are rejected. Arbitrary-precision mathematical integers are decimal strings
in JSON. JSON numbers are restricted to nonnegative safe dimensions and
indices; their upper limit is `2**53-1`.

Canonical JSON sorts keys, uses ASCII escapes, has no insignificant whitespace,
and forbids floating point. This is the repository's restricted canonical
JSON, not RFC 8785 JCS. The proof ID is SHA-256 of
`b"hec-count-proof/1\0" + canonical_json(document)`. The inequality ID uses
the analogous `hec-inequality/1` prefix and the inequality object. Dates,
solver logs, performance measurements, and migration receipts are outside
the mathematical document, so changing them does not change the proof ID.

### Reduced exact decision diagrams

`count-decision-dag/1` stores one scalar root per RHS group. Terminals are
nonnegative reduced rational pairs, numerically sorted and unique. Terminal
IDs come first; node IDs follow in the array's order. Each node is
`[source_axis, zero_child, one_child]`. Child IDs precede their parent, axes
strictly decrease along a path, equal children are eliminated, identical
nodes are shared, and nodes are sorted by axis then child IDs. All terminals
and nodes must be reachable from the roots. These conditions give a canonical
reduced diagram for the chosen fixed variable order.

Scalar roots share nodes across groups. Vector-valued leaves would explode
even for identity-like maps; that representation is not the standard. The
diagram defines every source vertex, including omitted variables, with no
missing-row convention. The verifier checks exact root ranges and boundary
images, then takes the exact maximum of the sum of absolute differences of
each pair of axis cofactors. A joint recursive split covers both values of
every remaining relevant variable. Equal cofactors contribute zero without
branching, and memoization reuses identical subproblems. Every original-cube
edge is covered; no sampling or floating point is used.

The scope is `symbolic-original-cube-all-edges`, distinct from enumerating an
audit table. Tests compare symbolic acceptance against an independent
exhaustive arbitrary-precision audit. The minimal clearing scale is the LCM
of reachable terminal denominators.

### Seed rows and optional audit exports

Base64 contains the canonical row bytes; strict canonical base64 is required.
The group order and group bounds come exclusively from the coefficient vector.

Integral rows use `bounded-integers/1`: group `g` occupies
`beta_g.bit_length()` bits, little-endian, groups then rows without intermediate
padding. Only the final byte may have padding, and its unused bits must be
zero. This uses no more bits than the historical repeated Boolean groups.

Fractional rows use `reduced-rationals/1`: each row encodes its positive common
denominator followed by its `G` nonnegative numerators as minimal unsigned
LEB128 integers. Their joint gcd, including the denominator, must be one.
Truncation, trailing bytes, and nonminimal varints are rejected. Integral
functions or seeds must use the bounded integer encoding. Rational rows use
their own reduced denominators, not giant global fixed-width numerators.

Seed rows belong to compact kernel definitions. Enumerated full tables use
the separate `hec-count-audit/1` format, with function kind `full-table/1`.
They are optional audit exports. The authoritative catalogue rejects them.
`make_count_proof(..., audit_table=True)` and the independent reference
checker support these exports without introducing a legacy reader.

## Compact compatible order construction

The other supported full-map definition is `compatible-order-kernel/1`.
Its row payload is a seed on **all** compatible vertices, ordered by ascending
source integer. The complete domain is independently derived from supports;
there is no supplied vertex list to trust:

```text
I_i intersect I_j is empty -> not (x_i = x_j = 1)
I_i proper subset I_j     -> x_i <= x_j.
```

The seed must satisfy the same exact bounds and boundary conditions and every
compatible one-bit edge. Missing or extra rows are rejected. Every step below
is fixed by this version; certificates cannot supply arbitrary executable
code, tuned probabilities, a different fold order, or a numerical projector.

### Compatible domain distances

The compatible domain is isometric in the weighted source cube. To move from
`x` to `y`, delete supports in `x` absent from `y`, smaller supports first,
then add supports in `y` absent from `x`, larger supports first. The path goes
through `x intersect y`, stays compatible, and flips each differing axis once.
Consequently checking every compatible edge proves the seed's global
Lipschitz bound on that domain.

### Disjoint support folds

Process every disjoint pair `(i,j)` in lexicographic source-axis order. With
capacities `a>=b`, its forbidden state `11` becomes `00` with probability
`b/a`, or the larger-capacity singleton with probability `(a-b)/a`. Fix the
other three states and other coordinates. Equal capacities send `11` to `00`.

Its expected distances to the larger and smaller singletons are respectively
`b` and `(b/a)*b + ((a-b)/a)*(a+b) = a`, exactly their source edge bounds.
Other pair edges are fixed. An unrelated-axis edge couples the same random
choice at both ends. Shortest paths therefore prove weighted Wasserstein
nonexpansion. Composition preserves it. Folds only remove ones, so a single
pass eliminates every disjoint conflict without reintroducing earlier ones.

### Exact order projection and threshold

For each disjoint-valid endpoint, use the unique weighted L2 order projection

```text
P(x) = argmin_u sum_i alpha_i (u_i-x_i)^2
       subject to u_i <= u_j whenever I_i proper subset I_j.
```

The feasible cone is closed under coordinatewise min and max. Comparing the
two optimal objectives with their min/max replacements proves order
preservation: for `x<=y`, the replacement difference on a coordinate with
`P(x)_i>P(y)_i` is `2*alpha_i*(P(x)_i-P(y)_i)*(x_i-y_i)<=0`; uniqueness forces
`P(x)<=P(y)`. Translation by a constant is feasible, so stationarity gives
`sum alpha_i P(x)_i = sum alpha_i x_i`. Projection lies in `[0,1]^L`.

For `z=min(x,y)`, these facts imply

```text
sum_i alpha_i |P(x)_i-P(y)_i|
 <= sum_i alpha_i (P(x)_i+P(y)_i-2P(z)_i)
  = d_alpha(x,y).
```

Positive projected supports belong to the upward closure of the initially
active supports: setting coordinates outside that closure to zero is feasible
and improves the objective unless they are already zero. Supersets of
pairwise-intersecting active supports remain pairwise intersecting. Therefore
the common threshold `Y_i(x,t)=1[P(x)_i>=t]`, `0<t<=1`, is compatible.

Coupling the same threshold at two endpoints gives expected source distance
`sum alpha_i |P(x)_i-P(y)_i|`. The seed bound and convexity of the output L1
norm prove that its expected seed image is nonexpansive. Composing with the
disjoint folds gives a full-cube function. All occurrence boundaries are
compatible, so folds, projection, and threshold fix them. Convex expectation
preserves the count bounds.

The expectation is an exact finite sum over rational projection levels, not
Monte Carlo sampling. The Python reference computes maximum-closure splits,
then independently certifies order, rational level balances, and integer KKT
flows. Tests compare it to exhaustive partition optimization and full-cube
edge verification on small instances.

### Derived clearing scale

Every projection level is a weighted block mean; its denominator divides a
positive integer no greater than `sum(alpha)`. If the seed's minimal common
denominator is `D_seed`, a sufficient bound is

```text
D_seed * lcm(1,...,sum(alpha))
       * product_over_disjoint_pairs(max(alpha_i,alpha_j)/gcd(alpha_i,alpha_j)).
```

This is the recorded nonminimal scale. It can be much larger than the scale
of a previous enumerated map; it is a clearing guarantee, not a requirement
to allocate that Boolean output or a minimal-scale claim.

The verifier reports `complete-compatible-seed-and-certified-extension`, with
the actual seed vertex and edge counts. It does not report those edges as a
fresh exhaustive full-cube evaluation. Migration source audits have a separate
scope and count.

## Immutable LFS shards and inequality indexes

`hec-proof-catalog/1` indexes content-addressed `.proofpack` shards. It accepts
only compact decision diagrams and certified kernel definitions. Each proof
is one independent Zstandard frame containing its canonical document. The
default soft shard target is 16 MiB; one larger frame remains whole. Shards
are immutable and named by their complete compressed SHA-256. The catalogue
records proof and inequality IDs plus byte offsets and lengths, and covers
each shard exactly once with no gaps, overlaps, or trailing data.

The catalogue and provenance stay in ordinary Git; proof shards use Git LFS.
`hec-inequality-catalog/1` keeps primitive coefficient vectors and their proof
references in ordinary Git, sorted by inequality ID. Exact binding checks
require the same complete proof set on both sides. These validity records do
not silently add facet or rank claims.

Changing Zstandard level or repacking shards changes physical object hashes,
not proof or inequality identities. Random access decompresses only the
selected proof, not a monolithic dataset from the beginning. Reads verify
shard bytes and hashes, canonical proof identity, and inequality binding.
Mathematical verification is still required; hashes are not proofs.

LFS quota failure is a publication failure, not mathematical evidence or a
reason to weaken checks. Keep verified local staging and the old active
dataset intact until every referenced shard is retrievable and CI passes.
Do not commit an active catalogue pointing at unavailable payloads.

## Proof preserving migration and archive

For a historical Boolean table, replace each repeated RHS block by its number
of ones. Prefix sorting fixes boundary images and never increases an edge
distance because `|count(u)-count(v)| <= Hamming(u,v)` per group. Exact original
bits need not be preserved in the live certificate. The original artifact
must remain in the archive, and the receipt must say that the transformation
preserves the inequality proof rather than every output bit.

For a positively scaled full table, a complete compatible seed can be
extracted as exact counts divided by its recorded positive scale, followed
by the fixed full-cube construction. The new definition is independently
verified. It need not have the old scale or identical noncompatible images.

The importer must:

1. Bind original inequality/frame, compressed and decoded hashes and sizes.
2. Re-audit every edge and boundary of the retained **original** cube map.
   Auditing a normalized count map alone must not hide an invalid old bit map.
3. Verify the new definition exactly and record its independent scope.
4. Record original and target IDs, scales, transformation, audit time, and
   audit implementation/configuration hashes where a native backend is used.
5. Leave originals unchanged and publish the catalogue only after every
   selected record passes. Partial migrations are not active datasets.

`tools/migrate_count_proofs.py` implements the small historical JSON importer
and the sealed exact-order release importer. `tools/audit_counts.cpp` is a
bounded-memory independent 64/128-bit source-table auditor. Its arithmetic
limits fail closed; they are not restrictions on rational certificate math.
An explicit wider auditor is required for wider historical tables.

The 80,213-record published n=6 packed stream and the additional original-scale
campaign maps still require their own complete staged migration before the
old public reader and old active payload can be retired. Their current files
must not be rewritten as an unaudited "format cleanup."

## Running the checks

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_count*.py'
c++ -O3 -std=c++17 tools/audit_counts.cpp -o /absolute/scratch/audit_counts
PYTHONPATH=src python tools/migrate_count_proofs.py /absolute/new/staging \
  legacy-json data --n 1 --n 2 --n 3 --n 4 --n 5
```

The sealed-release mode requires the release directory and explicit auditor
binary. It checks source hashes and every original edge before creating
compact seed definitions. It reads one case at a time and removes only its
own temporary decoded data. No production controller, solver settings,
healthy searches, completed proofs, or sealed release files are modified.
