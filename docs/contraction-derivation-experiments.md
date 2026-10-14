# Contraction proof derivation experiments

Exact derivation recipes reduced a 182-proof pilot from 1,897,232 to 878,196
canonical JSON bytes: a 53.71% reduction before any file compression. Every
selected recipe was reconstructed in a fresh process without source tables
and passed exhaustive original-cube verification. This is a representation
result, not a universal construction or a general speedup.

The experiments are isolated on `codex/contraction-derivation-pilot-20261013`.
The authoritative corpus and the PR preparation branch are unchanged. The
experimental formats are deliberately rejected by the production reader.

## Scope and controls

The October 13, 2026 PDT experiments comprise:

- A structural survey of all 80,213 n=6 facet/proof identities.
- All 14 n=1 through n=5 proofs.
- A reproducible sample of 128 n=6 proofs, balanced across ten existing
  compressed-frame-size deciles, using selection seed 20261013.
- Fifteen additional size extremes and positional controls.
- Twenty-five previously untested structural controls, selected by exact
  inequality identity rather than assuming facet/proof positions align.

The resulting 168 n=6 cases cover every observed value of source dimension
L, RHS group count G, maximum source capacity, and maximum RHS capacity.
L ranges from 2 to 17; the largest source capacity is 8 and the largest RHS
capacity is 6. Covering those categories is not equivalent to processing
every proof in the population.

All tested compatible seeds are integral. Their full-cube extensions may be
rational. Fractional compatible seeds require a separate lattice-aware
extension of these inference rules; they are not rounded or silently accepted.

Two verification/extraction workers were used. The main pilot's maximum
Python-worker RSS was 265,175,040 bytes; maximum native-child RSS was
16,826,368 bytes. These are per-process historical peaks, not additive live
memory measurements.

## Integer interval closure with sparse choices

The decoder derives the complete compatible domain from the inequality. It
starts with integer bounds 0 through beta_g and the prescribed physical-party
and purifier images. It repeatedly applies three necessary constraints.

### Coupled distance budgets

For intervals at vertices u and v, the minimum possible coordinate distance is

```text
gap_g = max(0, lo(u,g)-hi(v,g), lo(v,g)-hi(u,g)).
```

If the sum exceeds the source distance budget, the current choices are
inconsistent. Otherwise the residual budget after all other coordinates
restricts coordinate g at both vertices. This is a joint L1 rule: it does
not incorrectly give every output coordinate the full input-edge budget.

The implementation applies this to compatible edges and to at most 32 fully
determined anchors, using exact weighted source distances.

### Tight-pair interval constraints

For output anchors a and b, the exact identity is

```text
|F(z)-F(a)|_1 + |F(z)-F(b)|_1
 = |F(a)-F(b)|_1
   + 2 * sum_g distance(F_g(z), [min(F_g(a),F_g(b)), max(...) ]).
```

The corresponding source sum equals d_alpha(a,b) plus twice z's weighted
distance from the source interval between a and b. Thus the output's total
distance from the coordinate interval box has an exact upper bound.
For integral seeds, source-minus-image slack zero or one leaves no extra
integer unit on a source geodesic. The decoder uses those tight pairs both
on and off their geodesics.

This generalizes the geodesic-rigidity starting point of the deterministic
methods in [Bao and Naskar](https://arxiv.org/html/2403.13283v2). The integer
lattice restriction is essential: the same unit-slack deduction cannot
simply be applied to arbitrary rational values.

### Small exact candidate intersections

When a row's remaining integer domain has at most 64 candidates, the decoder
enumerates that domain and intersects its anchor-ball and neighboring-interval
constraints. It tightens each coordinate to the surviving extrema. Larger
domains skip this rule; the work bound is not an acceptance shortcut.

After closure stops, a fixed row/group ordering selects the next unknown
coordinate. The source-preserving encoder records the required offset in its
current interval. A lower- or upper-endpoint default plus exceptional offsets
reconstructs the tape. The saved recipe contains no source table, source
proof ID, or truth oracle. Its ordering, defaults, work bound, and inference
version are explicit.

The source-independent variants choose an endpoint at every remaining choice.
They can fail: necessary inference constraints are not a proof that an
unfixed choice is globally free. Failed branches do not show the inequality
is invalid and are never counted as proofs.

## Explicit logical cut formulas

For each integral RHS count, the extractor uses the identity

```text
s_g(x) = sum_{k=1}^{beta_g} 1[s_g(x) >= k].
```

Each threshold set is described by a disjunction of literal conjunctions.
A conjunction consists of the source bits required to be one and the source
bits required to be zero. The extractor removes literals only when the
resulting region contains no negative compatible example. Incompatible
vertices are don't-cares because the fixed cancel/fill extension only queries
the compatible domain.

Shared conjunctions are interned across groups and levels. Reconstruction
uses only these predicates and the inequality. No entropy coder or byte
compressor is used. The predicates are not claimed individually to establish
contraction; their reconstructed seed and full extension receive the same
coupled mathematical checks as the existing definitions.

MMI provides a concrete six-term example. With inputs a=AB, b=AC, c=BC:

```text
F_A   = a b (1-c)       F_B = a c (1-b)
F_C   = b c (1-a)       F_ABC = a OR b OR c.
```

The prototype also derives MMI completely from its boundary images, without
recorded choices. All eight vertices and twelve edges pass exact checking.
The corresponding cut construction appears in the
[original holographic entropy cone paper](https://arxiv.org/html/1505.07839v1).

## Measured results

The byte comparison uses complete canonical JSON documents, including their
inequality context. It does not compare compressed files or extrapolate LFS
quota savings. Reconstruction timings include native-process startup where
applicable and were measured on the local host with two workers.

| Representation | Full-map successes | Total recipe bytes | Smaller than source | Median reconstruction |
| :-- | --: | --: | --: | --: |
| Existing compact definitions | 182 source proofs | 1,897,232 | baseline | not measured here |
| Sparse-choice closure | 182/182 | 1,077,425 | 168/182 | 248 ms |
| Logical cut formulas | 182/182 | 1,031,734 | 170/182 | 70 ms |
| Smallest valid definition per case | 182/182 | 878,196 | selected case by case | depends on constructor |

The selection used closure for 102 cases, cut formulas for 57, and a
source-independent lower-endpoint construction for 23. The existing
definition remains an allowed fallback; these observed winners are not a
promise for every untested case.

Across these cases, 8,926,547 stored source count values became either:

- 1,245,169 algorithmic choices, with only 91,243 exceptional offsets
  explicitly recorded; or
- 64,588 distinct conjunctions containing 387,138 source literals.

These are different semantic units, not interchangeable byte counts.

### Generality and performance limitations

Both source-dependent constructions passed all 182 cases, each checking
20,884,617 original-cube edges. Fresh-process verification of the selected
recipes repeated those 20,884,617 edge checks with no source-data option.
Hashes and successful extraction alone do not confer mathematical validity.

The unbiased-within-size-strata 128-case n=6 subset had zero successes for
either fixed endpoint policy. Including small proofs and special controls
gives 29/182 lower-endpoint and 18/182 upper-endpoint successes. Those aggregate
rates must not be presented as ordinary n=6 success rates.

The main pilot's 4,419 paired full-map query timings showed formulas slower
than packed seed lookup in 136 of 143 n=6 cases. The median formula/packed
time ratio was 1.36; aggregate times were 446,260 versus 316,802 microseconds.
The formulas can be evaluated without materializing a full seed table, but
are not a demonstrated general query-speed improvement.

Bounded counterexample-guided anchor enrichment also failed to complete all
20 ordinary tested cases within eight anchors. Two hand-picked large cases
also remained incomplete at sixteen anchors. Those attempts produced no new
accepted proofs. They do not establish that a different anchor selection or
a larger generating core cannot work.

## Verification and failure tests

The experimental decoder emits an ordinary exact count definition only after
reconstructing its complete seed. The existing independent C++ verifier then
rebuilds geometry, checks the seed, reconstructs every original source vertex,
and checks every weighted cube edge. It reads neither source tables nor
migration receipts. Original artifact files are unchanged.

Tests cover complete MMI derivation, random feasible high-capacity maps,
source-excluding inference, missing/trailing choices, out-of-range offsets,
fractional values, contradictory anchors, malformed references, unreachable
terms, huge unsupported dimensions, unsupported versions/fields, and forged
verification claims. Syntactically valid constant formulas with wrong boundary
images are rejected mathematically. Budget exhaustion is labelled incomplete.

## Reproduction

Use the repository's locked dependencies. The native experiments support
n<=6, L<=17, total RHS capacity<=63, and source capacities<=32; wider cases
fail closed. Keep generated runs outside the authoritative dataset.

```bash
uv sync --locked --dev
run_dir=$(mktemp -d)
c++ -O3 -std=c++17 -Wall -Wextra -Werror tools/derivation_pilot/closure.cpp -o "$run_dir/closure"
c++ -O3 -std=c++17 -Wall -Wextra -Werror tools/derivation_pilot/anchors.cpp -o "$run_dir/anchors"
c++ -O3 -std=c++17 -Wall -Wextra -Werror tools/verify_count_proofs.cpp -o "$run_dir/verifier"
export PYTHONPATH=src:tools
uv run --no-sync python -m derivation_pilot.benchmark \
  --data-root /absolute/path/to/hydrated/data --closure "$run_dir/closure" \
  --verifier "$run_dir/verifier" --output "$run_dir/pilot" --sample 128 --workers 2
uv run --no-sync python -m derivation_pilot.survey \
  --data-root /absolute/path/to/hydrated/data --output "$run_dir/population.json"
uv run --no-sync python -m derivation_pilot.benchmark \
  --data-root /absolute/path/to/hydrated/data --closure "$run_dir/closure" \
  --verifier "$run_dir/verifier" --output "$run_dir/coverage" \
  --indices-file "$run_dir/population.json" --exclude-results "$run_dir/pilot/results.json"
uv run --no-sync python -m derivation_pilot.validate_batch \
  --results "$run_dir/pilot/results.json" --results "$run_dir/coverage/results.json" \
  --closure "$run_dir/closure" --verifier "$run_dir/verifier" --output "$run_dir/fresh.json"
uv run --no-sync python -m unittest discover -s tests
```

`anchor_benchmark` reproduces the bounded anchor trial from the pilot results.
`verify_recipe` accepts an individual recipe without any source-corpus path.
Run bindings record source catalogue, implementation, and binary hashes;
per-case records retain exact identities, timing, failure, and acceptance
scope. Historical runs are never overwritten.

## Next mathematical priorities

The highest validated representation return is a cost-aware choice between
logical cuts and sparse derivation tapes. Production integration still needs
a standard-schema constructor, explicit derived scaling, complete corpus
verification, and a query/reconstruction cost policy. It should retain the
current mathematical acceptance contract rather than add a legacy fallback.

Much smaller descriptions likely require finding a simpler valid map, not
faithfully reproducing arbitrary choices made by an old solver. The next
research priority is synthesis of low-complexity coupled cut/circuit rules:
fit boundary conditions, use the exact verifier to find violating edges, and
refine the rule while minimizing its description length. Comparator, transfer,
MMI, and exclusion blocks are candidates for shared certified primitives.
The current pilot establishes neither a universal small circuit nor a fast
inequality-only generator for the hard corpus.
