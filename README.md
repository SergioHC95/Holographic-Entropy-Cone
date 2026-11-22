# Holographic Entropy Cone

Exact facet inequalities, extreme rays, graph realizations and contraction
proofs for the holographic entropy cones. The facet and ray catalogues are
complete for $n\leq5$; the six-party catalogues are partial.

## Setup and checks

Python dependencies are locked in `uv.lock`. Native exact verification needs
GCC/Clang-compatible C++17 with unsigned 128-bit integers. CI covers Ubuntu 24.04
(x86-64) and macOS 26 (ARM64).

```bash
uv sync --locked --dev --python 3.13.14
uv run hec native build --directory .hec-native
export HEC_NATIVE_DIR="$PWD/.hec-native"
export HEC_CHECK_WORKERS=4
export HEC_RECONSTRUCTION_WORKING_BYTES=268435456

uv run hec storage audit
uv run hec storage history
uv run hec check database --root data
uv run hec check facets --root data
uv run hec check rays --root data
uv run hec check graphs --root data
uv run python -m unittest discover -s tests
uv run ruff check .
```

The buffer limit bounds native output storage, not total RSS. Data is separate
from the Python wheel: use the repository root, `HEC_DATA_ROOT`, or an explicit
data root. Contraction search additionally requires a PySAT build exposing
Kissat and its raw C symbols; the tracked Cython extensions build on first use.

## Data

`data/n=*/facets.json` and `rays.json` store representatives of distinct
full-symmetry orbits under $S_{n+1}$, including permutations of the purifier.
Facet and proof identities bind exact party-labelled coefficient vectors;
the two catalogues cover exactly the same listed representatives.

| File | Contents |
| --- | --- |
| `facets.json` | Listed facet representatives, with lower-party lifts first. |
| `rays.json` | Extreme-ray representatives, inline for small catalogues or an ordered ray-shard index for large ones. |
| `ray-shards/*.json` | Exact integer ray rows in deterministic, content-addressed shards. |
| `graphs.json` | Ordered graph-shard index, with exactly one graph per `rays.json` row. |
| `graph-shards/*.json` | Exact edge/weight records in deterministic, content-addressed shards. |
| `inequalities.json` | Exact facet identities and their selected full-map proofs. |
| `proofs.json` | Content-addressed proof/frame index. |
| `proof-shards/*.proofpack` | Seekable exact definitions, stored in ordinary Git. |

Rows use cardinality-then-lexicographic subset order. Non-lift facet rows are
row-lexicographically sorted. There is exactly one full-map proof per listed facet,
bound by content rather than facet-row position. The six-party data has
**87,236 listed facet representatives**, with exactly matching inequality
and proof catalogues. Candidates without facet certification do not belong
in the accepted data tree.
`data/storage.json` binds every payload to its byte length and SHA256. Ray and
graph shards are at most 16 MiB, preserve ray-row alignment, and use ordinary
Git. Readers check every shard's hash, byte length, and row count; CI still
independently checks every graph realization and exact ray rank. No stored hash
or catalogue metadata substitutes for mathematical verification.

The catalogue publishes one graph per ray: fewest total vertices first, then
fewest edges among the verified graphs at that order. New ray publications
require a vertex lower bound as well as an exact entropy match. Provenance
binds the selected catalogue graph without storing any graph payloads.

The [realization ledger](research/ray-graph-realizations-through-14-vertices.json)
records the provenance of historical exact graph witnesses with at most
14 vertices. A vertex count alone does not establish minimality. Two corrected
catalogue graphs there attain 12 vertices, with exhaustive 11-vertex exclusions.

The [minimal 15-vertex ledger](research/ray-graph-minimal-15-vertex-realizations.json)
records 14,797 six-party rays whose stored graphs have exactly 15 vertices. For
these rays 15 is the minimum: a completed exhaustive search found no graph
realization with at most 14 vertices.

The [second minimal 15-vertex ledger](research/ray-graph-minimal-15-vertex-realizations-followup.json)
records 19,066 six-party ray/graph pairs with exact 15-vertex minimality evidence.

The [third minimal 15-vertex ledger](research/ray-graph-minimal-15-vertex-realizations-structural.json)
records 2,588 six-party ray/graph pairs collected since the second ledger.

The [fourth minimal 15-vertex ledger](research/ray-graph-minimal-15-vertex-realizations-adaptive.json)
records 523 six-party ray/graph pairs.

The [fifth minimal 15-vertex ledger](research/ray-graph-minimal-15-vertex-realizations-frontier.json)
adds 1,183 six-party ray/graph pairs with exact 15-vertex minimality evidence.

The [sixth minimal 15-vertex ledger](research/ray-graph-minimal-15-vertex-realizations-continuation.json)
records 829 six-party ray/graph pairs with exact 15-vertex minimality evidence.

The [seventh minimal 15-vertex ledger](research/ray-graph-minimal-15-vertex-realizations-recombined.json)
adds 534 six-party ray/graph pairs with exact 15-vertex minimality evidence.

The [eighth minimal 15-vertex ledger](research/ray-graph-minimal-15-vertex-realizations-anchored.json)
adds 752 six-party ray/graph pairs with exact 15-vertex minimality evidence.

The [ninth minimal 15-vertex ledger](research/ray-graph-minimal-15-vertex-realizations-native-tail.json)
adds seven six-party ray/graph pairs from completed native searches.

The [tenth minimal 15-vertex ledger](research/ray-graph-minimal-15-vertex-realizations-projection.json)
records 132 six-party ray/graph pairs with exact 15-vertex minimality evidence.

The [native continuation ledger](research/ray-graph-minimal-15-vertex-realizations-latest.json)
records nine further six-party pairs from completed native searches, each
with an exhaustive 14-vertex exclusion.

The [search follow-through ledger](research/ray-graph-minimal-15-vertex-realizations-followthrough.json)
records two further pairs: one from the native queue and one found after
relabeling the terminals. Both have exhaustive 14-vertex exclusions.

The [relabeled frontier ledger](research/ray-graph-minimal-15-vertex-realizations-relabeled-frontier.json)
records six pairs found by changing the terminal order in the native search;
each has an exhaustive 14-vertex exclusion.

The native searches after #333 add four six-party ray/graph pairs across two
ledgers ([first](research/ray-graph-minimal-15-vertex-realizations-native-after-333.json),
[second](research/ray-graph-minimal-15-vertex-realizations-certified-continuation.json)).
Each pair has an exhaustive 14-vertex exclusion.

The [frontier continuation ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-continuation.json)
adds five more pairs found by relabeling the terminals. Each has an exhaustive
14-vertex exclusion.

The [witness-tail ledger](research/ray-graph-minimal-15-vertex-realizations-witness-tail.json)
adds five pairs from a disjoint terminal-relabeling sweep. Each has an
exhaustive 14-vertex exclusion.

The [expanded frontier ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-expanded.json)
adds eleven pairs from a further terminal-relabeling sweep. Each has an
exhaustive 14-vertex exclusion.

The [native continuation ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-expanded-native.json)
adds one more pair from the native queue, also with an exhaustive
14-vertex exclusion.

The [queue continuation ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-queue-continuation.json)
adds two more native pairs with exhaustive 14-vertex exclusions.

The [frontier validation ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-validation.json)
adds one benchmark holdout and two native results, each with an exhaustive
14-vertex exclusion.

The [budgeted frontier ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-budgeted.json)
adds twelve relabeling witnesses and three native results, each with an
exhaustive 14-vertex exclusion.

The [native continuation ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-budgeted-native.json)
adds one later native result with an exhaustive 14-vertex exclusion.

The [post-#347 ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-after-347.json)
adds the next native result with an exhaustive 14-vertex exclusion.

The [post-#348 ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-after-348.json)
adds twelve terminal-relabeling witnesses and one native result, each with an
exhaustive 14-vertex exclusion.

The [matched-search ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-after-349.json)
adds ten distinct pairs from native and terminal-relabeling witness searches,
each with an exhaustive 14-vertex exclusion.

The [post-#350 ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-after-350.json)
adds eight native ray/graph pairs, each with an exhaustive 14-vertex exclusion.

The [post-#352 ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-after-352.json)
adds 26 portfolio witnesses and two native results, each with an exhaustive
14-vertex exclusion.

The [post-#354 ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-after-354.json)
adds two native ray/graph pairs, each with an exhaustive 14-vertex exclusion.

The [post-#355 ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-after-355.json)
adds seven ray/graph pairs: six from the weighted-first portfolio and one from
native search. Each has an exhaustive 14-vertex exclusion.

The [post-#353 ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-after-353.json)
adds ten portfolio witnesses and six native results, each with an exhaustive
14-vertex exclusion.

The [first ARM64 sweep ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-post353-arm-first.json)
adds eight independently checked ray/graph pairs, each with an exhaustive
14-vertex exclusion.

The [remaining ARM64 sweep ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-post353-arm-final.json)
adds 21 ray/graph pairs from the second and third waves, each with an exhaustive
14-vertex exclusion.

The [first surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-first.json)
adds 19 ray/graph pairs from the ARM64 and AMD64 witness waves, each with an
exhaustive 14-vertex exclusion.

The [second surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-second.json)
adds another 24 ray/graph pairs from the next two waves, each with an exhaustive
14-vertex exclusion.

The [third surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-third.json)
adds 32 ray/graph pairs from two more waves and one from the native queue.
Each has an exhaustive 14-vertex exclusion.

The [fourth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-fourth.json)
adds 26 ray/graph pairs from two more waves and one from the native queue.
Each has an exhaustive 14-vertex exclusion.

The [fifth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-fifth.json)
adds six ray/graph pairs from the next ARM64 wave, each with an exhaustive
14-vertex exclusion.

The [sixth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-sixth.json)
adds 21 ray/graph pairs from the next AMD64 wave, each with an exhaustive
14-vertex exclusion.

The [seventh surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-seventh.json)
adds 13 ray/graph pairs from the next ARM64 wave and one from the native queue.
Each has an exhaustive 14-vertex exclusion.

The [eighth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-eighth.json)
adds 15 ray/graph pairs from the next AMD64 wave, each with an exhaustive
14-vertex exclusion.

The [ninth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-ninth.json)
adds 19 ray/graph pairs from the next ARM64 and AMD64 waves, each with an
exhaustive 14-vertex exclusion.

The [tenth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-tenth.json)
adds 22 ray/graph pairs from the next ARM64 and AMD64 waves, each with an
exhaustive 14-vertex exclusion.

The [eleventh surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-eleventh.json)
adds 20 ray/graph pairs from the next ARM64 and AMD64 waves, each with an
exhaustive 14-vertex exclusion.

The [twelfth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-twelfth.json)
adds 19 ray/graph pairs from the next ARM64 and AMD64 waves, each with an
exhaustive 14-vertex exclusion.

The [thirteenth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-thirteenth.json)
adds five ray/graph pairs from the last ARM64 wave, each with an
exhaustive 14-vertex exclusion.

The [fourteenth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-fourteenth.json)
adds 10 ray/graph pairs from the next AMD64 wave, each with an
exhaustive 14-vertex exclusion.

The [fifteenth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-fifteenth.json)
adds 15 ray/graph pairs from the next AMD64 wave, each with an
exhaustive 14-vertex exclusion.

The [sixteenth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-sixteenth.json)
adds five ray/graph pairs from the next AMD64 wave and one from the native
queue, each with an exhaustive 14-vertex exclusion.

The [seventeenth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-seventeenth.json)
adds 15 ray/graph pairs from the next AMD64 wave, each with an
exhaustive 14-vertex exclusion.

The [eighteenth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-eighteenth.json)
adds 12 ray/graph pairs from the final AMD64 wave, each with an
exhaustive 14-vertex exclusion.

The [nineteenth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-nineteenth.json)
adds one ray/graph pair from the native queue with an exhaustive 14-vertex
exclusion.

The [twentieth surge ledger](research/ray-graph-minimal-15-vertex-realizations-frontier-six-hour-surge-twentieth.json)
adds 11 ray/graph pairs from the supplemental ARM64 wave, each with an
exhaustive 14-vertex exclusion.

The [renewed native-search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-native.json)
adds one ray/graph pair with an exact 15-vertex realization and an
exhaustive 14-vertex exclusion.

The [renewed ARM-search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-arm-first.json)
adds 21 ray/graph pairs from the first three terminal-relabeling waves.
Each has an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [second renewed ARM-search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-arm-second.json)
adds 27 ray/graph pairs from the next three ARM64 waves and one from the
native queue. Each has an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [renewed AMD64-search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-amd-first.json)
adds three ray/graph pairs from the combined capacity-closure and live cut-row
search. Each has an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [third renewed ARM-search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-arm-third.json)
adds eight ray/graph pairs from the continuing ARM64 terminal-relabeling
search, each with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [fourth renewed ARM-search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-arm-followup.json)
adds five ray/graph pairs from the continuing ARM64 terminal-relabeling
search, each with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [fifth renewed ARM-search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-arm-third-complete.json)
adds five ray/graph pairs from the final wave of the third ARM64 round.
Each has an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [fourth-round ARM-search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-arm-fourth.json)
adds 20 ray/graph pairs from two waves of the fourth ARM64 round.
Each has an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [fourth-round completion ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-fourth-complete.json)
adds eight ray/graph pairs from the last ARM64 wave and seven from the AMD64
capacity-closure and live cut-row search. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [fifth-round ARM-search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-arm-fifth.json)
adds 16 ray/graph pairs from two waves of the fifth ARM64 round.
Each has an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [fifth-round completion ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-fifth-complete.json)
adds 14 ray/graph pairs from the last fifth-round ARM64 wave and four from
the next round. Each has an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [sixth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-sixth.json)
adds 12 ray/graph pairs from an ARM64 wave, four from the AMD64 capacity-closure
and live cut-row search, and one from the native queue. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [seventh-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-seventh.json)
adds 14 ray/graph pairs from two ARM64 terminal-relabeling waves. Each has an
exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [eighth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-eighth.json)
adds 13 ray/graph pairs from two ARM64 terminal-relabeling waves. Each has an
exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [ninth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-ninth.json)
adds 23 ray/graph pairs from three ARM64 terminal-relabeling waves. Each has
an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [tenth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-tenth.json)
adds 26 ray/graph pairs from two ARM64 waves, eight from the AMD64 capacity-closure
and live cut-row search, and one from the native queue. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [Mistral recovery ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-mistral-recovery.json)
adds eight ray/graph pairs from a resumed ARM64 lane and eight from an
additional ARM64 node. Each has an exact 15-vertex realization and an
exhaustive 14-vertex exclusion.

The [eleventh-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-eleventh.json)
adds ten ray/graph pairs from an ARM64 terminal-relabeling wave. Each has an
exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [twelfth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twelfth.json)
adds ten ray/graph pairs from a Mistral ARM64 terminal-relabeling wave. Each
has an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [thirteenth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-thirteenth.json)
adds nine ray/graph pairs from the additional Mistral ARM64 lane. Each has
an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [fourteenth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-fourteenth.json)
adds 16 ray/graph pairs from two ARM64 waves and nine from the AMD64
capacity-closure and live cut-row search. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [fifteenth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-fifteenth.json)
adds three ray/graph pairs from a Mistral ARM64 wave. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [sixteenth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-sixteenth.json)
adds 13 ray/graph pairs from two ARM64 waves. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [seventeenth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-seventeenth.json)
adds 19 ray/graph pairs from two ARM64 waves and one from the native queue.
Each has an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [eighteenth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-eighteenth.json)
adds 12 ray/graph pairs from two ARM64 waves and 11 from the AMD64
capacity-closure and live cut-row search. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [nineteenth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-nineteenth.json)
adds seven ray/graph pairs from a Mistral ARM64 wave. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [twentieth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twentieth.json)
adds 13 ray/graph pairs from an ARM64 wave. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [twenty-first-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twenty-first.json)
adds four ray/graph pairs from an ARM64 wave. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [twenty-second-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twenty-second.json)
adds 15 ray/graph pairs from a Mistral ARM64 wave and one from the native
queue. Each has an exact 15-vertex realization and an exhaustive 14-vertex
exclusion.

The [twenty-third-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twenty-third.json)
adds nine ray/graph pairs from an ARM64 wave. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [twenty-fourth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twenty-fourth.json)
adds three ray/graph pairs from a Mistral ARM64 wave. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [twenty-fifth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twenty-fifth.json)
adds eight ray/graph pairs from an ARM64 wave. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [twenty-sixth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twenty-sixth.json)
adds 12 ray/graph pairs from a Mistral ARM64 wave. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [twenty-seventh-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twenty-seventh.json)
adds nine ray/graph pairs from a Mistral ARM64 wave. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [twenty-eighth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twenty-eighth.json)
adds 12 ray/graph pairs from an ARM64 wave. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [twenty-ninth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-twenty-ninth.json)
adds six ray/graph pairs from a Mistral ARM64 wave. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [thirtieth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-thirtieth.json)
adds nine ray/graph pairs from a Mistral ARM64 wave. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [thirty-first-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-thirty-first.json)
adds ten ray/graph pairs from a Mistral ARM64 wave and one from the native
queue. Each has an exact 15-vertex realization and an exhaustive 14-vertex
exclusion.

The [native follow-up ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-native-followup.json)
adds one ray/graph pair from the native queue, with an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [thirty-second-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-thirty-second.json)
adds six ray/graph pairs from a Mistral ARM64 wave. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [thirty-third-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-thirty-third.json)
adds five ray/graph pairs from a Mistral ARM64 wave. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [thirty-fourth-round search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-frontier-thirty-fourth.json)
adds 12 ray/graph pairs from the final ARM64 wave. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [renewed live-row ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-live-rows-first.json)
adds 15 ray/graph pairs from three ARM64 waves with new terminal labelings
and live original cut rows. Each has an exact 15-vertex realization and an
exhaustive 14-vertex exclusion.

The [second renewed live-row ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-live-rows-second.json)
adds 11 ray/graph pairs from the remaining first-round ARM64 wave. Each has
an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [renewed cross-platform ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-live-rows-and-controls.json)
adds 29 ray/graph pairs from four ARM64 waves, four from the AMD64
capacity-closure search, one from an AMD64 benchmark replay, and one from the
native queue. Each has an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [novel-root and lookahead ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-novel-roots-and-lookahead.json)
adds 30 ray/graph pairs from four ARM64 waves, one from exact closure
lookahead on AMD64, and one from the native queue. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [third renewed ARM ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-third-arm-block.json)
adds 31 ray/graph pairs from four live-row ARM64 waves. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [fourth renewed ARM ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-fourth-arm-block.json)
adds 29 ray/graph pairs from three live-row ARM64 waves. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [renewed capacity and ARM ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-capacity-live-and-arm.json)
adds nine ray/graph pairs from two ARM64 waves, four from AMD64
capacity-closure search, and one from a matched AMD64 benchmark. Each has
an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [first budget-trial ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-first-budget-wave.json)
adds 17 ray/graph pairs from three ARM64 waves comparing two search budgets.
Each has an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [second budget-trial ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-second-budget-block.json)
adds 23 ray/graph pairs from four ARM64 waves comparing two search budgets,
and one from the native queue. Each has an exact 15-vertex realization and
an exhaustive 14-vertex exclusion.

The [post-pilot ARM ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-after-budget-pilot.json)
adds 14 ray/graph pairs from three subsequent ARM64 waves. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [continuing ARM ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-continuing-arm.json)
adds six ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [next verified ARM ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-next-verified-waves.json)
adds four ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [continuing ARM and AMD ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-continuing-arm-and-amd.json)
adds eleven ARM64 and four AMD64 ray/graph pairs. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [later ARM wave ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-later-arm-waves.json)
adds 19 ray/graph pairs from three ARM64 waves. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [development ARM wave ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-dev-arm-proof-block.json)
adds 13 ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [next ARM block ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-next-arm-block.json)
adds 17 ray/graph pairs from two ARM64 waves. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [AMD tail and ARM ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-amd-tail-and-arm.json)
adds four AMD64 and eleven ARM64 ray/graph pairs. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [follow-on ARM ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-follow-on-wave.json)
adds six ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 344 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-344.json)
adds ten ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 343 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-343.json)
adds seven ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [resumed ARM lane ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-resumed-arm-wave.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 345 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-345.json)
adds eight ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 348 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-348.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 347 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-347.json)
adds eleven ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [AMD wave 380 and ARM ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-amd-wave-380.json)
adds three AMD64 and 15 ARM64 ray/graph pairs. Each has an exact 15-vertex
realization and an exhaustive 14-vertex exclusion.

The [ARM wave 352 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-352.json)
adds eight ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 351 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-351.json)
adds seven ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 354 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-354.json)
adds nine ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM waves 353 and 356 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-353.json)
adds 14 ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 355 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-355.json)
adds 16 ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 358 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-358.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 357 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-357.json)
adds four ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM waves 359 and 360 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-360.json)
adds 12 ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 362 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-362.json)
adds four ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 361 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-wave-361.json)
adds seven ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM waves 363, 364, and 366 ledger](research/ray-graph-minimal-15-vertex-realizations-rechallenge-arm-waves-363-364.json)
adds 21 ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [six-hour extension ledger](research/ray-graph-minimal-15-vertex-realizations-six-hour-extension-first-batch.json)
adds six ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [recovered ARM ledger](research/ray-graph-minimal-15-vertex-realizations-six-hour-extension-recovered-arm.json)
adds 28 ray/graph pairs from four previously completed search waves. Each
has an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [next extension ARM ledger](research/ray-graph-minimal-15-vertex-realizations-six-hour-extension-next-arm.json)
adds eight ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM and replayed AMD ledger](research/ray-graph-minimal-15-vertex-realizations-six-hour-extension-arm-and-replayed-amd.json)
adds ten ARM64 ray/graph pairs and two independently replayed AMD64 witnesses
from an interrupted search. Each has an exact 15-vertex realization and an
exhaustive 14-vertex exclusion.

The [ARM wave 377 ledger](research/ray-graph-minimal-15-vertex-realizations-six-hour-extension-arm-wave-377.json)
adds five ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 381 ledger](research/ray-graph-minimal-15-vertex-realizations-six-hour-extension-arm-wave-381.json)
adds eleven ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM wave 376 and native ledger](research/ray-graph-minimal-15-vertex-realizations-six-hour-extension-arm-wave-376.json)
adds six ARM64 ray/graph pairs and one from the native queue. Each has an
exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [ARM extension wave 501 ledger](research/ray-graph-minimal-15-vertex-realizations-six-hour-extension-wave-501.json)
adds five ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [ARM extension wave 505 ledger](research/ray-graph-minimal-15-vertex-realizations-six-hour-extension-wave-505.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [renewed native search ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-native-intake.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [renewed wave 509 and native ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-509.json)
adds three ARM64 ray/graph pairs and one from the native queue. Each has an
exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [AMD residual wave 401 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-amd-wave-401.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [renewed wave 513 and native ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-513.json)
adds four ARM64 ray/graph pairs and one from the native queue. Each has an
exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [latest native intake ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-latest-intake.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [AMD residual wave 402 and native ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-amd-wave-402.json)
adds three AMD64 ray/graph pairs and one from the native queue. Each has an
exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [compact live-row wave 601 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-compact-wave-601.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [renewed ARM wave 521 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-521.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [renewed ARM wave 525 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-525.json)
adds six ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [AMD residual wave 403 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-amd-wave-403.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [renewed ARM wave 529 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-529.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [renewed Mistral ARM wave 371 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-371.json)
adds ten ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [AMD wave 404, ARM wave 533, and native ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-amd404-arm533.json)
adds two AMD64 ray/graph pairs, one ARM64 pair, and one from the native queue.
Each has an exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [renewed ARM wave 537 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-537.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [renewed ARM wave 541 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-541.json)
adds four ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [AMD residual wave 405 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-amd-wave-405.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [renewed ARM wave 545 and native ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-545.json)
adds four ARM64 ray/graph pairs and one from the native queue. Each has an
exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [renewed ARM wave 549 and native ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-549.json)
adds four ARM64 ray/graph pairs and two from the native queue. Each has an
exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [renewed Mistral ARM wave 375 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-375.json)
adds seven ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [renewed ARM wave 553 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-553.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [renewed ARM wave 557 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-557.json)
adds five ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [renewed ARM wave 561 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-561.json)
adds four ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [Mistral wave 379 and AMD wave 407 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-379.json)
adds eight ARM64 ray/graph pairs and one AMD64 pair. Each has an exact
15-vertex realization and an exhaustive 14-vertex exclusion.

The [compact live-row wave 606 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-compact-wave-606.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [renewed ARM wave 565 and native ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-565.json)
adds two ARM64 ray/graph pairs and one from the native queue. Each has an
exact 15-vertex realization and an exhaustive 14-vertex exclusion.

The [AMD residual wave 408 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-amd-wave-408.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [renewed DEV ARM wave 569 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-569.json)
adds four ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [compact comparison wave 607 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-compact-wave-607.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [DEV ARM handoff wave 502 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-502.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [DEV ARM handoff wave 506 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-506.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [DEV ARM handoff wave 510 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-510.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [compact comparison wave 608 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-compact-wave-608.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [DEV ARM handoff wave 514 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-514.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [DEV ARM handoff wave 518 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-518.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [native intake after wave 518 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-intake-after-518.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [DEV ARM handoff wave 522 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-522.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [compact comparison wave 609 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-compact-wave-609.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [DEV ARM handoff wave 526 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-526.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [Mistral ARM wave 383 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-383.json)
adds four ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [native intake after wave 383 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-intake-after-383.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [DEV ARM handoff wave 534 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-534.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [recovered waves 538 and 610 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-recovered-waves-538-610.json)
adds four ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions: two from DEV ARM wave 538 and two from AMD64 comparison
wave 610.

The [DEV ARM handoff wave 542 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-542.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [DEV ARM handoff wave 546 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-546.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [compact comparison wave 611 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-compact-wave-611.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [DEV ARM handoff wave 550 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-550.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [DEV ARM handoff wave 554 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-554.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [Mistral ARM wave 503 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-503.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [wave 612 and native intake ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-compact-wave-612.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions: two from AMD64 comparison wave 612 and one from the
native solver.

The [DEV ARM handoff wave 562 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-562.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [wave 566 and native intake ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-566.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions: one from DEV ARM wave 566 and one from the native solver.

The [DEV ARM handoff wave 570 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-570.json)
adds one ray/graph pair with an exact 15-vertex realization and an exhaustive
14-vertex exclusion.

The [DEV ARM handoff wave 511 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-511.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [DEV ARM handoff wave 515 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-515.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [DEV ARM handoff wave 519 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-519.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [DEV ARM handoff wave 523 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-523.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [wave 527 and native intake ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-527.json)
adds three ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions: two from DEV ARM wave 527 and one from the native solver.

The [DEV ARM handoff wave 531 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-531.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [DEV ARM handoff wave 539 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-539.json)
adds two ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

The [DEV ARM handoff wave 543 ledger](research/ray-graph-minimal-15-vertex-realizations-renewed-six-hour-wave-543.json)
adds five ray/graph pairs with exact 15-vertex realizations and exhaustive
14-vertex exclusions.

Across all party counts, **87,250 full-map proofs** occupy **85 proof shards**
totalling **192,258,450 bytes**. Git LFS is not required.

One [mathematical specification](docs/proofs.md) defines the reconstruction
contract. One [schema](schemas/repository.schema.json) describes proofs,
catalogues and the byte inventory.
The Python API is `hec.proof_store`:
`ProofCatalog`, `write_proof_catalog` and `write_proof_dataset`.
The reader rejects unknown syntax; the writer independently verifies each
complete map before publishing a new immutable dataset.

Useful storage commands:

```bash
uv run hec storage plan                 # expected payloads; metadata only
uv run hec storage audit                # actual bytes and hashes
uv run hec storage history              # complete HEAD ancestry hygiene
uv run hec storage snapshot --replace   # intentional byte-inventory update
```

Hash/schema checks are not mathematical acceptance. The required CI gate also
reconstructs every proof and checks all original-cube bounds, occurrence images
and weighted edges, plus exact facet/ray ranks, graph realizations and global
bindings. Membership must agree in both directions: no facet without a proof
and no unlisted proof inequality. Facet ranks use stored rays and independently
verified graph realizations. Additional [exact graph-entropy rank witnesses](docs/facet-rank-witnesses.md)
can supply tight directions outside the example ray catalogue. CI freshly checks
their feasible flows, matching cuts, tightness and modular independence.
Saved rank and validity flags confer no acceptance.
Complete maps belong to disjoint, cost-balanced jobs; each uses at
most four workers and only its owned shards. All jobs must pass at one commit.

## Construct proofs and graphs

The production constructor `hec.construct_contraction(coefficients, n, scale=1)`
searches a compatible seed and returns a self-contained current-standard proof
only after exact independent verification. To construct a catalogue:

```bash
uv run hec construct \
  --rows data/n=2/facets.json --n 2 --output contractions_example
```

Input rows must be exact integers. Output must be a new directory.
`--scale D` sets an explicit positive search scale. The constructor bounds
compatible counts with exact triangle inequalities, imposes prefix-layer
SAT edge constraints, reconstructs the fixed full map and exhaustively audits
it. Solver models are transient; a resource limit or unfinished search is not
a proof or a mathematical impossibility result.

The implementation is `hec.authoring`; there is no separate example-only
constructor or alternate proof format. The CLI streams proposals to the
standard writer, which audits each complete map once and atomically publishes
the two bound indexes and immutable shards. Proof construction establishes
inequality validity; repository admission additionally requires facet rank.

The graph-generation example `find_ray_graphs.py` uses `HEC_GRAPH_WORKERS`;
checks use `HEC_CHECK_WORKERS`.
In PowerShell, set variables with `$env:HEC_CHECK_WORKERS = "4"`.

## Cone summary

Counts below come from the tracked data, not solver runs. Facet/ray images
count distinct $S_{n+1}$ relabelings, discarding stabilizer-related repeats.
The proof column counts selected full maps, one per listed facet. Complete
proof coverage does not mean the six-party cone is fully known.

| n | facet reps | facet images | ray reps / graphs | ray images | full-map proofs | cone catalogue |
| :-: | ---------: | -----------: | ----------------: | ---------: | --------------: | :------------- |
| 1 | 1 | 1 | 1 | 1 | 1 | complete |
| 2 | 1 | 3 | 1 | 3 | 1 | complete |
| 3 | 2 | 7 | 2 | 7 | 2 | complete |
| 4 | 2 | 20 | 3 | 20 | 2 | complete |
| 5 | 8 | 372 | 19 | 2,267 | 8 | complete |
| 6 | 87,236 | 433,075,118 | 3,806,132 | 19,020,103,588 | 87,236 | partial |

CI recomputes this table and the proof-storage totals from the data; stale
README counts fail the tests. These documentation checks do not replace
independent mathematical verification.

[Incremental integrity CI](docs/incremental-integrity.md) audits new or edited
results and their affected dependencies. Reuse requires a successful integrity
run for the exact baseline tree with unchanged validators; otherwise CI runs
the complete audit. Current bindings, counts, changed bytes and new Git history
are always checked.

The 205 source facets from `HEC6_207_expanded_evidence` have current-standard
full-map proofs and exact rank-62 bases. Fourteen are already in the parent IC
facet batch; this change adds the remaining 191. Of all 205, 64 use additional graph models;
their 40 supporting models live in the separate content-addressed witness
catalogue. The [source ledger](research/HEC6_207_proven_facets.json) binds each
original bank index to its stored inequality and proof. The two source rows
still at rank 61, old indices 44610 and 59782, are excluded.

## Attribution

If you use this data, please consider citing the following papers.

* Complete description of $H_n$ for $n \leq 5$ from
  [arXiv:1903.09148](https://arxiv.org/abs/1903.09148):

  ```bibtex
  @article{n5hec,
      author         = "Hern\'andez Cuenca, Sergio",
      title          = "{The Holographic Entropy Cone for Five Regions}",
      eprint         = "1903.09148",
      archivePrefix  = "arXiv",
      primaryClass   = "hep-th",
      doi            = "10.1103/PhysRevD.100.026004",
      journal        = "Phys. Rev. D",
      volume         = "100",
      number         = "2",
      pages          = "026004",
      year           = "2019",
      note           = "Data available at https://github.com/SergioHC95/Holographic-Entropy-Cone"
  }
  ```

* Partial description of $H_6$ from
  [arXiv:2309.06296](https://arxiv.org/abs/2309.06296):

  ```bibtex
  @article{n6hec,
      author         = "Hern\'andez-Cuenca, Sergio and Hubeny, Veronika E. and Jia, Frederic",
      title          = "{Holographic Entropy Inequalities and Multipartite Entanglement}",
      eprint         = "2309.06296",
      archivePrefix  = "arXiv",
      primaryClass   = "hep-th",
      reportNumber   = "MIT-CTP/5610",
      month          = "9",
      year           = "2023",
      note           = "Data available at https://github.com/SergioHC95/Holographic-Entropy-Cone"
  }
  ```
