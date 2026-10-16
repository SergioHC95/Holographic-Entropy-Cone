# Exact contraction proof standard

The sole authoritative artifact is `hec-count-proof/1` with function kind
`compatible-reconstruction-pipeline/1`. All four seed primitives feed the SAME
`cancel-fill-common-threshold/1` full-map extension. There is no format
guessing, legacy-reader fallback, executable proof code or stored-valid flag.

Proofs are self-contained mathematical definitions. Validity is determined
from the declared inequality and reconstructed full map, independently of the
constructor, authoring history or any stored audit receipt. Contraction validity
does not by itself assert facethood.

`hec.proof_store.ProofCatalog` and `write_proof_catalog` are aliases of the
single implementation in `hec.reconstruction_store`.
`read_contractions`, `write_contractions`, the dataset loader and repository
checks use that standard. No archive readers, migration commands or historical
acceptance implementations are shipped. Archived bytes and source snapshots
are recovery evidence, not supported inputs to the maintained pipeline.

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

Persisted normals must be primitive; the reader rejects implicit scaling or
orientation changes. Positive-scale normalization during authoring must use
exact arithmetic. Party permutations and purifier complements change the
declared frame and inequality identity; they are never inferred from history.

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
hashes, or seed-only checks substitute for exhaustive per-map acceptance:
the writer and required CI execute all original-cube bounds, occurrence
images, and weighted edges on every saved definition.

Decision diagrams record their minimal common denominator. The kernel construction
records a derived sufficient clearing scale, explicitly marked nonminimal.
The verifier recomputes both rather than trusting the declaration. Neither
the primary certificate nor verification expands the potentially enormous
virtual Boolean output.


## One closed proof language

The fields are exactly `format`, `inequality`, `function` and
`clearing_scale`. The normative syntax is
[`count-proof-v1.schema.json`](../schemas/count-proof-v1.schema.json).
Schema conformance alone is not mathematical acceptance. For example:

```json
{
  "format": "hec-count-proof/1",
  "inequality": {"n": 3, "coefficients": ["-1", "-1", "-1", "1", "1", "1", "-1"]},
  "function": {
    "kind": "compatible-reconstruction-pipeline/1",
    "seed": {
      "kind": "integer-cut-dnf/1",
      "terms": [["1", "0"], ["2", "0"], ["3", "4"], ["4", "0"], ["5", "2"], ["6", "1"]],
      "groups": [[[2]], [[4]], [[5]], [[0, 1, 3]]]
    },
    "extension": {"kind": "cancel-fill-common-threshold/1"}
  },
  "clearing_scale": {"value": "1", "minimal": false}
}
```

The only seed kinds are:

- `compatible-count-table/1`: one exact bounded-integer or reduced-rational
  count row per independently derived compatible vertex, in ascending mask order.
- `compatible-scalar-dag/1`: shared, ordered, reduced scalar decision DAGs
  with integer numerators over one minimal positive seed denominator.
- `integer-cut-dnf/1`: shared literal conjunctions and disjunctions defining
  Boolean layers whose sum is the integral count in each RHS group.
- `integer-interval-closure/1`: versioned exact coupled interval propagation,
  deterministic defaults and sparse exceptional choices; no source-table oracle.

These are interchangeable seed encodings, not alternative full-map formats.
The reader checks exact complete-domain size, capacities, canonical DAG/term
structure, bounds, occurrence images, coupled compatible edges and minimal
seed denominator. Integer row payloads use bounded little-endian fields;
fractional rows use reduced minimal unsigned LEB128 records. Noncanonical
base64, varints, padding, duplicate keys, unknown fields/versions and floats fail.

Closure choices remain source-guided in general. This representation is not a
claim of a universal short description or a fast inequality-only solver.
A seed table guarantees general representability when a valid count map exists;
the other three primitives express useful structure without changing the proof.

## Complete compatible domain and fixed extension

For the distinct LHS supports, C is derived from the clauses

```text
I_i disjoint I_j  -> not (x_i = x_j = 1)
I_i proper subset I_j -> x_i <= x_j.
```

No proof-supplied vertex list is trusted.
### Compatible domain distances

The compatible domain is isometric in the weighted source cube. To move from
`x` to `y`, delete supports in `x` absent from `y`, smaller supports first,
then add supports in `y` absent from `x`, larger supports first. The path goes
through `x intersect y`, stays compatible, and flips each differing axis once.
Consequently checking every compatible edge proves the seed's global
Lipschitz bound on that domain.


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


Different seeds can give different valid maps. Equal exact seeds give the
same full map under this fixed extension. Restricting an arbitrary old valid
map to C and applying this extension preserves the proof, but need not preserve
every old output bit outside C. Original artifacts and explicit transformation
receipts are therefore retained; an exact-encoding conversion and a
proof-preserving change of function must never be conflated.

## Identity and canonical bytes

Canonical JSON sorts keys, uses ASCII escapes, no insignificant whitespace,
and no floats. Mathematical integers are canonical decimal strings; JSON
numbers are only nonnegative safe dimensions/indices, at most `2**53-1`.
This restricted canonical JSON is not RFC 8785 JCS.

Proof identity is SHA256 of
`b"hec-count-proof/1\0" + canonical_json(document)`.
Inequality identity uses the `hec-inequality/1` prefix and the exact frame/vector.
Semantic map identity binds the inequality, minimal seed denominator, all
ordered compatible values and fixed extension version. These hashes identify
bytes or semantics; they are NOT mathematical acceptance.

Dates, solvers, benchmarks and provenance belong outside the proof document.
Changing them cannot change a proof ID. Party permutations, purifier
complements, normalization and representation changes require explicit receipts.

## Exact verification and resource policy

The installed-package `ReconstructionVerifier` handles every seed kind.
The trusted native decoder and full-map verifier are configured by the caller,
not selected by proof fields. Native requests use uint64 exact numerators and
uint128 sums; unsupported precision fails closed or uses a COMPLETE
arbitrary-precision reference audit only within its explicit small-case bound.
Resource limits never turn a full audit into sampling.

The native verifier uses the same exact point rule in full and tiled layouts.
`HEC_RECONSTRUCTION_WORKING_BYTES=268435456` bounds primary output buffers,
not total RSS: the seed, complete-domain index, protocol and parent are separate.
Actual helper arguments and returned limits must match. Scope, identities,
all vertices/edges and source-free status are checked with exact types.
Native query differentials are extra controls, not replacements for full coverage.

For a local check, build a bound release from the installed package's sources:

```bash
uv run hec native build --directory .hec-native
HEC_NATIVE_DIR="$PWD/.hec-native" \
HEC_RECONSTRUCTION_WORKING_BYTES=268435456 HEC_CHECK_WORKERS=2 \
uv run hec check database --root data
```

Missing payloads or backends fail the check; there is no network fallback or
acceptance from migration receipts. Standalone `hec check database` checks
metadata AND executes all mathematical audits. CI partitions complete maps
independently of storage-file boundaries so each proof is audited exactly once, and runs global
`database-bindings` separately. ALL proof partitions, bindings, graph and
facet/ray-rank jobs must succeed at the same immutable checkout.

## Immutable publication and archive policy

`proofs.json` is a `hec-proof-catalog/1` index of content-addressed,
independently seekable Zstd frames in `proof-shards/<sha>.proofpack`.
Frames contain canonical full-map definitions; compression is a transport
layer, not the mathematical compactness claim. Inequality IDs and proof IDs
do not depend on compression or shard boundaries. `inequalities.json`
binds every selected proof to its exact inequality; one selection per inequality.

The strict writer owns bytes before verification, executes every full-map
audit and atomically publishes the catalogue LAST. Existing targets, corrupt
immutable payloads, duplicate selections and failed/partial verification are
not overwritten or accepted. A failed stream may leave reusable immutable
frames but no authoritative catalogue. Stored hashes/flags never cache acceptance.

Every current proof payload and index is committed directly in ordinary Git. The version-two storage inventory binds every required
path, byte length and SHA256. Pointer files and external-payload fallback paths
are rejected. A plain clone is a complete input to independent verification.

Historical recovery artifacts are retained outside the active repository.
The coordinated publication history removes obsolete data and old storage
filters from its ancestry. Hash/ancestry hygiene is a separate required CI gate;
it does not confer mathematical acceptance. Every proof partition still executes
all original-cube checks from the saved definitions.
