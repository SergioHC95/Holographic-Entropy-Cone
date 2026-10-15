# Exact contraction proof standard

Migration status, October 15, 2026: all 84,690 selected definitions have been
converted to the single `compatible-reconstruction-pipeline/1` profile and
staged. A NEW exhaustive staged-data audit is running; this is not yet a
primary-reader/data/CI cutover. The individual full-map kinds below document
the historical pre-unification profile, not fallbacks in the unified reader.
The target language has four seed primitives feeding ONE fixed extension;
see [the general pipeline specification](contraction-derivation-experiments.md#one-general-reconstruction-pipeline).
After complete mathematical QA, the active specification and entry points
must be cut over together rather than leave multiple authoritative formats.

The authoritative certificate is an exact definition of a function on the
entire original source cube. It has one rational count per distinct RHS
support. Explicit Boolean tables are optional audit exports, not the standard
repository interface. This first standard covers contractions, their
inequality identities, and migration provenance. It does not change graph,
ray, or facet rank certificates.

The implementation is in `hec.count_proofs` and `hec.proof_store`. Their readers
accept only the new format. Historical JSON and bit tables enter through an
offline importer, never through a fallback in the new verifier. All 80,213
n=6 baseline proofs and the 14 n=1 through n=5 proofs have been migrated and
fully audited. Publication requires every referenced LFS payload to be
available and the new database-integrity gate to pass.

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
same homogeneous inequality. An integer-valued full map admits a scale-one
realization, although a constructor may record a larger sufficient scale
explicitly marked nonminimal; that is not evidence of nonintegrality. A scaled proof
must not be labelled an unscaled Boolean-output map. The source dimension
remains `L`; scaling does not manufacture extra source coordinates.

### Why scaling does not require an expanded source cube

The source metric is weighted on one coordinate per distinct positive
entropy support. RHS multiplicities, in contrast, are realized by repeated
Boolean output positions. This distinction agrees with the
[weighted-input convention in Section 2 of Bao and Naskar](https://arxiv.org/html/2403.13283v2#S2).
Our grouped rational-count contract has the following direct cut-cost proof.

Choose an optimal graph cut `U_i` for each distinct LHS support `I_i`, and
label each graph vertex by `x_i(v)=1[v in U_i]`. Let `D` clear all values of
the complete count map. For each RHS support `J_g`, form `D*beta_g` candidate
cuts with indicators

```text
z_(g,k)(v) = 1[D*F_g(x(v)) >= k],   1 <= k <= D*beta_g.
```

The occurrence conditions give every candidate the correct boundary region.
For each graph edge `(u,v)`, prefix Hamming distance and contraction give

```text
sum_(g,k) |z_(g,k)(u)-z_(g,k)(v)|
  = D * sum_g |F_g(x(u))-F_g(x(v))|
 <= D * sum_i alpha_i |x_i(u)-x_i(v)|.
```

Multiply by nonnegative graph-edge weights and sum. Minimality of the RHS
cuts and optimality of the chosen LHS cuts imply

```text
D * sum_g beta_g S(J_g)
 <= sum_(g,k) cost(z_(g,k))
 <= D * sum_i alpha_i S(I_i).
```

Dividing by `D` proves the original graph-model inequality. No arbitrary input bitstrings
on an imagined `sum_i D*alpha_i`-dimensional cube are assumed or checked.
The declared full source cube is precisely `{0,1}^L` with its explicit
`alpha` metric. This argument concerns inequality validity, not facethood.

The compatible-domain extension theorem below explains why the same full-map
rule works for every seed representation. It is not a claim that syntax,
hashes, or seed-only checks substitute for the exhaustive per-map migration
audit: the running staged-data pass still executes all original-cube bounds,
occurrence images, and weighted edges on every saved definition.

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

## Deterministic cancel fill construction

`compatible-cancel-fill-kernel/1` is a distinct certified constructor. It uses
the same complete compatible-domain seed, independently rebuilt coverage,
exact row bounds, occurrence images, and compatible-edge checks as the order
kernel. It does not change the meaning of `compatible-order-kernel/1`.

Start with integer masses `k_i=alpha_i*x_i`. Process disjoint source-axis pairs
in lexicographic order, subtracting `min(k_i,k_j)` from both masses. The pair
map is `(max(a-b,0),max(b-a,0))`; its L1 distance between two inputs is
`|(a-b)-(a'-b')|`, bounded by the input L1 distance. A single pass eliminates
every disjoint conflict because masses only decrease.

Then process **all** proper inclusion pairs `(i,j)` in lexicographic axis
order, moving `min(k_i,alpha_j-k_j)` from the subset to the superset. The pair
map is `(max(a+b-alpha_j,0),min(a+b,alpha_j))`. Its components are monotone
in their sum, so its output L1 distance is the difference between the two
input sums and cannot exceed the input L1 distance. Moving positive mass to
a superset preserves pairwise intersection of active supports.

Cardinality-lexicographic axes put every proper subset before its superset.
All incoming transfers to axis `i` therefore precede its outgoing transfers.
If `i` retains mass after its outgoing pairs, every strict superset is full.
That full upward family cannot later empty: transfers out of it can only go
to another full strict superset. One pass consequently gives
`k_i>0 => k_j=alpha_j` on every proper inclusion.

Normalize `q_i=k_i/alpha_i` and use the common threshold
`Y_i(x,t)=1[q_i>=t]`, for `0<t<=1`. Each threshold is compatible. Coupling the
same threshold at two inputs gives expected source distance
`sum alpha_i |q_i(x)-q_i(y)| = sum |k_i(x)-k_i(y)| <= d_alpha(x,y)`.
The seed's global bound and the triangle inequality for an exact expectation
prove the full map `F(x)=integral_0^1 F_C(Y(x,t)) dt` is nonexpansive.
This integral is a finite rational sum, not Monte Carlo sampling. Compatible
inputs are fixed by every operation, preserving the seed and boundaries;
convexity preserves output count bounds.

The derived sufficient clearing scale is
`D_seed * lcm(alpha_i)`. With uniform source capacities, masses stay zero or
their common capacity, so `D_seed` alone suffices. This constructor always
marks its clearing guarantee nonminimal; exhaustive audits may record a
smaller observed denominator in a separate receipt without changing the
definition's semantics.

Integral seed queries use exact compatible-domain ranking. Descending source
axes force future zeros: choosing zero forbids subsets and choosing one
forbids disjoint supports. Cached completion counts select the packed row
without enumerating the domain or retaining a vertex dictionary. Rational
rows have the same mathematical semantics and exact reduced encoding.

The October 13, 2026 full-baseline run reconstructed all 80,213 maps, directly
audited 9,501,700,040 original and 9,501,700,040 reconstructed cube edges,
checked 1,320,807,803 compatible edges, and differentially compared the native
implementation with Python on 2,373,852 query vertices. Source artifacts and
the exact verifier snapshots were retained. That source audit preceded the
repository cutover; it did not change the production solver. The active
database gate now repeats the full reconstructed-cube check independently
from compact seeds, without reading source tables or migration receipts.

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
reason to weaken checks. A fully verified local branch may retain its
catalogues and all payloads while publishing is blocked. Do not publish or
merge the cutover until every active shard and retained archive object is
retrievable; missing payloads must fail CI. Existing published artifacts
remain unchanged until that cutover is merged.

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

The complete 80,213-record n=6 baseline migration is recorded in
`data/n=6/migration.json`. Its original stream, small-n source documents,
and transformation receipts live under `archives/contractions/legacy-v1/`.
The archive index records source hashes and the original Git revision.
Exact audit-source snapshots are retained as inactive `.txt` files in its
`verification-source/` directory; their index binds the original byte hashes.
Additional original-scale campaign maps are outside this baseline cutover;
they require their own full source audit before publication.

## Running the checks

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_count*.py'
hec_verify_dir=$(mktemp -d)
c++ -O3 -std=c++17 -Wall -Wextra -Werror tools/verify_count_proofs.cpp -o "$hec_verify_dir/check"
HEC_COUNT_VERIFIER="$hec_verify_dir/check" HEC_CHECK_WORKERS=2 \
  PYTHONPATH=src python -m hec.checks database
```

The database command checks complete inequality/proof bindings, facet order
and orbit uniqueness, and the full mathematical maps. Rank and graph checks
remain separate mandatory CI jobs. Unsupported large constructions require
an exact verification backend; they fail closed rather than using sampling.

The offline importer writes a new staging directory, not the active dataset:

```bash
c++ -O3 -std=c++17 tools/audit_counts.cpp -o /absolute/scratch/audit_counts
PYTHONPATH=src python tools/migrate_count_proofs.py /absolute/new/staging \
  legacy-json data --n 1 --n 2 --n 3 --n 4 --n 5
```

The sealed-release mode requires the release directory and explicit auditor
binary. It checks source hashes and every original edge before creating
compact seed definitions. It reads one case at a time and removes only its
own temporary decoded data. No production controller, solver settings,
healthy searches, completed proofs, or sealed release files are modified.
