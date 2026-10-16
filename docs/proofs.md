# Contraction proofs

A proof is a deterministic exact map, not a solver log or a stored validity
flag. Its inequality, complete compatible-domain seed and fixed extension
determine every original-cube image. Inequality validity and facethood are
separate claims.

## Mathematical contract

Write a primitive integer inequality as

```text
sum_i alpha_i S(I_i) >= sum_g beta_g S(J_g).
```

Coordinates are nonempty subsets in cardinality-then-lexicographic order.
Physical parties are `0,...,n-1`; atom `n` is the purifier. Each distinct
positive support gives one source axis with capacity `alpha_i`. Repeated
negative terms are grouped into distinct supports with capacities `beta_g`.
Source axis `i` is integer bit `i`. Scaling never adds source axes.

For `L` source axes and `G` output groups the proof defines
`F : {0,1}^L -> Q^G`. Acceptance requires:

1. `0 <= F_g(x) <= beta_g` at every original-cube vertex.
2. Every party/purifier occurrence vector has image `beta_g` when that atom
   belongs to `J_g`, and zero otherwise. Conflicting prescriptions fail.
3. Every source edge of axis `i` satisfies
   `sum_g |F_g(x)-F_g(x xor 2^i)| <= alpha_i`.

All comparisons are exact. Checking the `L*2^(L-1)` edges for `L>0` proves
the global Lipschitz bound by a shortest weighted cube path and the triangle
inequality. The zero normal is a trivial inequality, never a facet.

### Rational scaling proves the original inequality

Let `D` clear all map values. Realize output group `g` as `D*beta_g` Boolean
positions with `D*F_g(x)` leading ones. Prefix Hamming distance is exactly
`D*sum_g |F_g(x)-F_g(y)|`, bounded by `D*d_alpha(x,y)`.

For a graph model, choose an optimal cut `U_i` for each distinct LHS support
and label each graph vertex by `x_i(v)=1[v in U_i]`. The candidate RHS cuts
have indicators `z_(g,k)(v)=1[D*F_g(x(v)) >= k]`. Occurrence conditions give
the correct boundary regions. On every graph edge `(u,v)`,

```text
sum_(g,k) |z_(g,k)(u)-z_(g,k)(v)|
  = D * sum_g |F_g(x(u))-F_g(x(v))|
 <= D * sum_i alpha_i |x_i(u)-x_i(v)|.
```

Sum against nonnegative graph-edge weights and use cut minimality to obtain
`D*sum_g beta_g S(J_g) <= D*sum_i alpha_i S(I_i)`. Divide by `D`.
No expanded source cube, floating-point tolerance or unscaled-Boolean claim
is involved.

## Definition and identity

The single schema is [repository.schema.json](../schemas/repository.schema.json).
It covers proofs, their two indexes and the byte inventory. Schema conformance
is syntax only; the exact reader enforces canonical structure and the verifier
establishes the mathematical contract.

Proof fields are exactly `format`, `inequality`, `function`, `clearing_scale`:

```json
{
  "format": "hec-count-proof",
  "inequality": {"n": 3, "coefficients": ["-1", "-1", "-1", "1", "1", "1", "-1"]},
  "function": {
    "kind": "compatible-reconstruction-pipeline",
    "seed": {
      "kind": "integer-cut-dnf",
      "terms": [["1", "0"], ["2", "0"], ["3", "4"], ["4", "0"], ["5", "2"], ["6", "1"]],
      "groups": [[[2]], [[4]], [[5]], [[0, 1, 3]]]
    },
    "extension": {"kind": "cancel-fill-common-threshold"}
  },
  "clearing_scale": {"value": "1", "minimal": false}
}
```

Canonical JSON sorts keys, uses ASCII escapes and has no insignificant
whitespace or floats. Mathematical integers are canonical decimal strings;
JSON numbers are nonnegative safe dimensions/indices, at most `2^53-1`.
Duplicate keys, unknown fields, noncanonical encodings and invalid bounds fail.

The proof ID is `SHA256(b"hec-count-proof\0" + canonical_json(definition))`.
The inequality ID is `SHA256(b"hec-inequality\0" + canonical_json(inequality))`.
Both bind the exact party frame; relabeling or rescaling is never inferred.
Semantic identity binds the exact ordered seed values and fixed extension.
Identities identify definitions, not mathematical acceptance.

## Complete compatible seed

Derive `C` from the inequality, never a proof-supplied vertex list:

```text
I_i disjoint I_j       => not (x_i = x_j = 1)
I_i proper subset I_j  => x_i <= x_j.
```

The four seed primitives are:

| Kind | Exact definition |
| --- | --- |
| `compatible-count-table` | Bounded integer or reduced-rational rows, ascending compatible masks. |
| `compatible-scalar-dag` | Ordered reduced scalar decision DAGs over one minimal positive denominator. |
| `integer-cut-dnf` | Shared literal conjunctions/disjunctions defining Boolean prefix layers. |
| `integer-interval-closure` | Deterministic coupled interval propagation with explicit settings and sparse exceptional choices. |

All four feed the same extension. Table rows use `bounded-integers` packed
little-endian fields or `reduced-rationals` minimal unsigned LEB128 records.
Base64, padding and varints must be canonical. DAG order/reduction, cut terms,
closure choices, complete coverage and the minimal seed denominator are checked.
The [closure implementation](../src/hec/_native/closure.cpp) fixes propagation,
default choices and tie order; it needs no source-table oracle or solver.

`C` is isometric in the weighted cube: delete supports in `x` absent from `y`,
smaller supports first; then add supports in `y` absent from `x`, larger first.
The path through `x intersect y` stays compatible and flips each differing
axis once. Exact compatible-edge checks therefore prove the seed's global
Lipschitz bound on `C`.

## Fixed full-cube extension

Start with integer masses `k_i=alpha_i*x_i`.

1. Process disjoint axis pairs in lexicographic order, subtracting
   `min(k_i,k_j)` from both masses. The pair map
   `(max(a-b,0),max(b-a,0))` is L1-nonexpansive. Masses only decrease, so one
   pass eliminates every disjoint conflict.
2. Process **all** proper inclusion pairs `(i,j)` in lexicographic axis order,
   transferring `min(k_i,alpha_j-k_j)` from subset to superset. The pair map
   `(max(a+b-alpha_j,0),min(a+b,alpha_j))` is L1-nonexpansive: output distance
   is the absolute difference of the input sums. Moving mass to a superset
   preserves pairwise intersection of active supports.
3. Set `q_i=k_i/alpha_i` and `Y_i(x,t)=1[q_i>=t]` for `0<t<=1`. Define
   `F(x)=integral_0^1 F_C(Y(x,t)) dt`, a finite exact rational sum.

Subset-first axes put every incoming transfer before outgoing transfers.
If `i` retains mass, every strict superset is full; that full upward family
cannot empty later. Thus each threshold lies in `C`. Coupling the same
threshold at two inputs gives expected source distance
`sum_i alpha_i*|q_i(x)-q_i(y)| <= d_alpha(x,y)`. The seed's Lipschitz bound
and the triangle inequality prove the extension is nonexpansive. Compatible
points are fixed; convexity preserves output bounds and occurrence images.

For seed denominator `d`, the sufficient clearing scale is
`d*lcm(alpha_i)`, or just `d` for uniform source capacities. The reader
recomputes it; `minimal:false` means this is a sufficient guarantee, not
a claim that every output needs that denominator. No virtual Boolean output
is materialized. Equal exact seeds determine equal full maps.

## Verification and publication

`ReconstructionProgram` reconstructs the definition.
`ReconstructionVerifier` independently checks every seed edge and every
original-cube vertex, occurrence image and weighted edge. Native code uses
uint64 numerators and uint128 sums. Unsupported precision either fails closed
or receives a complete bounded arbitrary-precision reference audit—never a
sample or numerical acceptance.

Full-table and bounded-memory layouts use the same point rule. The configured
primary output-buffer limit is not total RSS. Backend source/binary hashes,
request identity, exact result types and complete coverage are checked.
Proofs cannot select executables or assert their own validity.

`ProofCatalog` and `write_proof_catalog` live in `hec.proof_store`.
`write_proof_dataset` owns each definition, verifies its complete map and
atomically publishes the proof and inequality indexes. Existing datasets,
corrupt immutable payloads, duplicate selections and incomplete audits fail.
Each shard contains independently seekable Zstd frames; compression and shard
boundaries do not enter proof identities. `inequalities.json` binds exactly
one selected proof to each accepted inequality. A contraction does not add
an inequality to the facet list without a separate exact rank check.
