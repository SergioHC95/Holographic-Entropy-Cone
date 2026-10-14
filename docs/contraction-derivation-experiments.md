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

## Full-corpus extension (October 14, 2026 PDT)

The next experiment inventories **84,690 unique proofs**, not a rounded 85,000:
80,213 baseline n=6 proofs, 4,387 newer primitive campaign proofs, 76 scaled
exact proofs, and 14 n=1 through n=5 proofs. This is proof coverage, not an
assertion that every inequality has an independently certified facet rank.
The full-corpus pass and subsequent alternative-map synthesis are distinct
phases. The earlier 182-proof results above remain historical pilot figures.

`tools/corpus_derivations` adds an exact compatible-domain scalar decision DAG
with shared terminals and subexpressions. Its missing branches are don't-cares
only outside the complete compatible domain; the fixed cancel/fill constructor
still defines every original source vertex. Rational terminal counts use an
explicit, independently checked minimal common denominator. The frozen integer
closure and DNF formats retain their original limits; a larger or rational
case is not falsely labelled an integer-pilot success. An explicit compatible
seed remains a measured fallback when a mathematical DAG is not smaller.

The independent wide auditor accepts source dimensions through 25, exact
64-bit output numerators, and 128-bit coupled distance accumulators. It derives
the complete compatible domain independently, reconstructs the full map, and
checks every original vertex bound, occurrence boundary, and weighted cube
edge. Overflow and unsupported geometry fail closed. The original Boolean
audit supports rows wider than 64 bits and cannot be replaced by a grouped
count audit. The older narrow checker is unchanged.

As a preflight control, exact-corpus index 62 (L=21, G=22) used seed denominator
30,291,545,345,228,800 and full-map clearing scale 908,746,360,356,864,000.
Both initial and source-free saved-recipe audits checked all 22,020,096 cube
edges. Its DAG was larger than its explicit seed, so it is not a DAG storage
success. This one control is not full-corpus completion.

The offline runner snapshots source identities, code and native binaries;
SQLite commits preserve each accepted recipe and receipt. It uses at most two
processing workers, live controller/descendant RSS guards at 64 GiB, and
bounded native table allocations. A separate fresh-process phase reconstructs
all saved winners without source tables. The PR-ready worktree, original
artifacts, completed production proofs and LFS state remain unchanged.

### Prepared alternative-map primitive

`corpus_derivations.simplify` is an arbitrary-precision mathematical reference
for subsequent synthesis, not a replacement for independent acceptance. It
starts from a complete verified compatible seed. With other coordinates fixed,
on a tight edge whose two values in coordinate g agree, those values are moved
together. Connected
components of such equalities are constant in g; any component containing an
occurrence boundary stays fixed.

For a component U with old coordinate value a, each cut edge (u,v), u in U,
imposes an exact interval on its proposed common value t:

```text
B = alpha_axis * D - sum_{h != g} |s_h(u) - s_h(v)|
s_g(v) - B <= t <= s_g(v) + B.
```

The intersection also includes 0 <= t <= beta_g * D. Internal edge loads are
unchanged by the shared move; cut-edge loads are updated exactly, then all
compatible loads are recomputed independently. A deterministic choice favors
coarser exact denominator grids and fewer count discontinuities. These are
search objectives, not a claim that the final stored definition is shorter.
An alternative requires a measured description improvement and exhaustive
original-cube acceptance before it can be retained.

Eight small synthetic-control tests cover fractional-to-integral simplification,
thirty randomly chosen feasible maps, deterministic replay, protected boundary
components, budget exhaustion and malformed input. Their accepted candidate
maps receive exhaustive arbitrary-precision full-cube checks. This preparation
does not start corpus synthesis before the full verification phase ends.

### Full-scope synthesis workflow

`python -m corpus_derivations.synthesize` provides a separate checkpointed
workflow. Its `prepare` command requires the source run to contain all 84,690
derivation results, all 84,690 successful source-free full-cube receipts, and
zero recorded errors. It checks every recipe hash, canonical definition,
inequality identity, receipt binding and original-cube coverage count. It
refuses a locked source controller rather than competing with a live job.
The testing-only small-scope parameters are not exposed by the CLI.

After preparation, `run --phase synthesize` uses exactly two processing workers
and the same live 64 GiB RSS guard. It tries large and rational definitions
first without dropping any source identity. Each outcome has a distinct
durable disposition: unchanged source, incomplete work budget, changed seed
without description improvement, mathematical failure, or a retained strictly
smaller verified alternative. Strictness is measured on uncompressed canonical
definition bytes, not zstd frames or the archived enumerated map.

A retained alternative must change at least one exact compatible count and
pass independent exhaustive original-cube verification after reconstruction
from its saved definition. `run --phase fresh` then repeats acceptance from
the saved alternatives in new workers without original source maps. Eleven
fixture-only workflow tests cover the scope/lock/hash/coverage gates, frame
length safety, strict-size rejection, actual mathematical rejection and a
successful changed-map fixture. Those tests are not corpus coverage.

### Final packaging and coverage report

`python -m corpus_derivations.package_results` requires complete source
verification, an explicit synthesis disposition for every source identity,
and a source-free full-cube receipt for every retained alternative. It selects
exactly one definition per inequality, keeping the verified source whenever
there is no strictly smaller verified alternative. Original artifacts remain
unchanged.

The research catalog uses independently seekable frames in immutable,
content-addressed 16 MiB shards. Every sealed frame, identity, offset and
coverage interval is re-read before the final report is emitted. This is
packaging integrity, not a substitute for mathematical verification. The
catalog is explicitly experimental and is not accepted by the production
reader or silently installed in the PR-ready worktree.

The report distinguishes canonical mathematical-definition bytes from frame
compression and archived enumerated tables. It records full-scope source and
alternative verification counts, original-cube edge totals, method capability
and budget failures, source dimensions and denominator sizes, and selection
provenance. CPU totals are not inferred from overlapping per-case wall times.
Fixture tests reject incomplete coverage, missing fresh checks, mismatched
metadata, shard corruption, overlapping offsets and overwrites of old exports.

### Checkpointed phase continuation

`python -m corpus_derivations.continue_pipeline --output NEW_DIRECTORY prepare
--source DERIVATION_RUN --python VENV_PYTHON` freezes a continuation implementation
without changing the live source controller or starting another mathematical
worker. Run its snapshotted module with `--output NEW_DIRECTORY run` in a
detached session. It observes the existing first pass, then admits source-free
verification, synthesis, alternative re-verification, and research packaging
in that order. Later mathematical phases retain the two-worker and 64 GiB
RSS limits; the observing process does not perform corpus mathematics.

Each handoff requires complete checkpoint counts, no recorded errors, a free
controller lock, and no surviving controller, native child or tracked process
group. A missing incomplete first-pass controller requires intervention; the
driver never signals or restarts it. Runtime, source-binding and frozen-code
hashes prevent quietly changing implementations between stages. Failures stop
the continuation without admitting another phase or overwriting old outputs.
Fixture sequencing tests are not corpus mathematical coverage. A final
packaged state still requires independent review and, if no genuinely smaller
alternative was found, further synthesis work; it never marks the goal done.

## Reproduction

On October 14 the user explicitly replaced the two-worker research limit with
eight workers while leaving other jobs running. New generations bind that
cohort in their metadata; historical two-worker runs are unchanged. The
`corpus_derivations.parallelize` handoff requires the old controller and its
workers/session to have exited, preserves a SQLite backup and every completed
receipt byte-for-byte, and records the old/new binding chain. It refuses changes
to mathematical functions, seed/recipe decoders, or native verifier binaries.
All inherited definitions still require the full separate source-free audit.

The eight-worker controllers admit small baseline cases concurrently, reserving
2 GiB of control headroom inside the unchanged 64 GiB aggregate cap. The largest
exact cases reserve 12 GiB each; explicit primitive geometry determines its
full-cube table reservation. Large-case concurrency can therefore be below
eight. Live aggregate/per-worker RSS guards remain active. Admission budgets
are scheduling bounds, not mathematical acceptance or proof-coverage claims.

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

## One general reconstruction pipeline

`hec.reconstruction` factors the successful research representations into one
proposed function kind inside the existing `hec-count-proof/1` envelope:

```text
exact inequality/frame
  -> derive the COMPLETE compatible domain C from supports
  -> evaluate one seed program S : C -> rational grouped counts
  -> fixed cancel/fill/common-threshold expectation E
  -> full map F = E(S) on EVERY original cube vertex
  -> independent exact full-cube audit
```

The seed program has four closed, versioned primitive kinds: exact count
lookup, a shared scalar decision DAG, logical threshold-cut formulas, and
integer interval closure with sparse exceptional choices. These are seed
languages, not four incompatible full-map formats. Geometry, domains,
boundary conventions, extension, scaling and verification are shared.
Proof documents cannot select Python code, native binary paths, solvers,
source archives, fold order, or unverified extension operators.

For example, a complete MMI reconstruction is:

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

The corresponding syntax contract is
`schemas/reconstruction-pipeline-v1.schema.json`. It reuses the existing
inequality and exact-row schemas. The reader separately enforces complete
coverage, canonical/shared DAG objects, exact group capacities, minimal seed
denominators and the derived full-map clearing guarantee. DAG nodes are
canonically relabelled bottom-up by axis and child IDs. Configurable resource
limits are implementation capabilities, not extra mathematical assumptions.

### Shared extension and semantic identity

Let K(x) be the fixed integer cancel/fill mass transport and
q_i(x)=K_i(x)/alpha_i. Sort its distinct positive threshold levels as
0=lambda_0<...<lambda_m=1 and set
y_j(x)_i=1[q_i(x)>=lambda_j]. Then every y_j(x) is compatible, and

```text
F(x) = sum_j (lambda_j-lambda_{j-1}) * S(y_j(x)).
```

Thus any two seed programs that give exactly the same rational counts on C
give exactly the same full map, even if their syntax and file sizes differ.
Conversely E fixes C, so different compatible values give different maps.
This is a useful semantic normal form for this extension, not an assertion
that every possible contraction has a unique short program.

This also gives completeness **up to proof-preserving canonicalization** in
the exact rational-count model. Restrict any already valid full-cube map to
C. Its exact bounds and occurrence images are preserved, and all compatible
edges still contract. Conversely, the isometry of C and the certified
extension theorem turn any seed satisfying that contract into a valid full
map. The explicit-seed primitive can always encode that restriction; sparse
closure programs, cut formulas and DAGs are optional improvements, not
assumptions needed for representability.

This does not assert exact preservation of an arbitrary old function outside
C. For example, a valid weighted map can have F(11)=1 whereas the fixed
extension of its compatible restriction has F(11)=1/2. Both prove the same
inequality. An exact-encoding receipt and a proof-preserving transformation
receipt must therefore remain distinct. Nor does general representability
imply a universally small seed or an inequality-only search algorithm.

`materialize_seed()` derives C independently of supplied row positions,
requires a minimal exact common denominator, and checks every compatible weighted
edge and occurrence boundary. Its seed fingerprint binds the inequality frame,
denominator and every ordered exact count. `semantic_identity()` additionally
binds the fixed extension version. Encoding IDs still identify actual stored
documents. Neither fingerprint is itself mathematical acceptance.

Pure representation conversion can therefore be justified by complete seed
equality and identical extension semantics; it does not require pretending a
third original-cube audit occurred. `corpus_derivations.pipeline_import`
actually compares all compatible values and records that restricted scope.
It rejects silently replacing an order-projection extension by cancel/fill:
that is a proof-preserving change of function, not an exact encoding change.

### One verification interface, no legacy fallback

Every seed kind exposes the same exact seed interface. `program.evaluate(x)`
uses the same extension for arbitrary original-cube queries, without allocating
an entire exponential table. `program.audit_reference()` directly checks every
actual output and every weighted cube edge using arbitrary-precision fractions
for bounded small cases. Larger cases require an explicit independent exact
backend; no resource limit changes a full audit into sampling.

`program.audit(NativePipelineAuditor(binary, expected_sha256))` executes the
existing independent wide C++ auditor after complete seed reconstruction.
The same backend handles every seed kind. Coverage, geometry, seed scale,
clearing scale and full-cube scope must all match. The native backend's
arbitrary-precision query differentials are controls in addition to its
exhaustive mathematical edge coverage, not replacements for it.

Old experimental documents enter only through the offline importer. The new
pipeline reader has no version guessing or legacy fallback. The proposed
function kind remains opt-in: the existing production reader deliberately
rejects it until complete-corpus translation/equivalence and integration QA
are finished. The running, frozen eight-worker verification and subsequent
synthesis workflow are not changed by this refactor.

The control suite exercises all four seed primitives, encoding-independent
identity, all-vertex agreement, weighted thresholds, arbitrary precision,
wide coupled sums, empty maps, malformed DAGs, missing rows, forged acceptance
claims, wrong boundaries, incompatible extensions and audit resource limits.
Controls are not a claim that all 84,690 recipes have already been converted.
In particular the closure choices remain source-guided in general; the new
abstraction is not an inequality-only solver or a universal speedup claim.

The October 14 controls additionally converted five real stored recipes
(tasks 18, 24, 80052, 80286 and 81838), covering every winning seed family and
28,688 complete compatible vertices. The rational control had L=19, G=24 and
denominator 16,777,216; the larger integral DAG control had L=18, G=19. All
exact seed values and fixed-extension semantics were preserved. These were
five conversion-equivalence controls, not five new full-cube audit claims or
a completed full-corpus conversion. The pipeline unit controls separately
include direct reference and independent native full-cube checks on fixtures.

### Complete-corpus selection and conversion gate

`corpus_derivations.selected_corpus.VerifiedSelection` provides one read-only,
locked source for the subsequent full-corpus converter. Its default scope is
all 84,690 identities. It requires all source-free source audits, a supported
synthesis disposition for every identity, and a separate successful fresh
full-cube audit for every retained alternative. Source, manifest, frozen code,
binary and synthesis bindings must agree. A live controller, native child,
unfinished phase or recorded error prevents admission of conversion work.

Every selected definition carries its own exact saved recipe and audit-receipt
hash. A changed alternative cannot inherit its source's audit. Non-retained
or budget-limited attempts select the fully verified source; they do not
become new proofs. Receipt checks distinguish exact integer coverage counts
from booleans, partial checks and compatible-seed-only scopes.

`pipeline_convert.convert_definition` applies the unified encoding to such a
record, checks all compatible values through the offline importer, and emits
an exact-conversion receipt binding the target proof, semantic identity and
actual selected mathematical audit. It explicitly records that no new cube
audit was executed. Canonical wrapper overhead is reported even when it
increases an individual definition's size; standardization is not disguised
as a storage improvement.

The per-record core does not launch a cohort. `pipeline_batch` provides the
full-scope frozen runner: it inherits the approved worker count, snapshots
implementations/runtime/primitive identities, and binds every selected input
and audit in an immutable manifest. Completed conversions commit individually
to a WAL/FULL SQLite ledger. Resume validates their canonical target and
provenance before skipping them; original proofs are never replaced. There
is no CLI subset/limit switch. Private two-case fixtures do not satisfy the
default 84,690-case scope.

The runner reserves memory for compatible-seed/Fraction/JSON copies rather
than incorrectly allocating an original-cube table for conversion. It shares
the two-GiB control reserve, 64 GiB aggregate/per-worker guards and approved
worker target. Mathematical failures stop admission; they do not become
converted proofs. The actual live-source gate refused competing conversion
and started zero workers, leaving the existing verification unchanged.
The complete first-pass inventory has maximum seed size 133,958 vertices and
3,482,908 grouped count cells, with a maximum stored recipe of 16,058,490 raw
JSON bytes. These fit the configurable pipeline limits; they are corpus
inventory figures, not new audit coverage. Seed-evaluator ownership is also
checked with cyclic GC disabled so decoded arrays do not await cyclic cleanup.

### Comparable costs and a unified export

A representation change can reverse which of two maps is shorter. For every
previously retained alternative, the runner therefore converts BOTH it and
its independently audited source into the same pipeline profile. It checks
that their exact map semantics differ, compares canonical bytes on equal
terms, and retains the alternative only if it is strictly smaller there too.
Otherwise the verified source wins. Both conversion/evidence references stay
in the provenance ledger. This does not resynthesize a map or invent another
full-cube audit.

`pipeline_export` requires complete error-free conversion coverage and checks
the actual selected source/alternative bindings again. It writes one pipeline
definition per inequality into immutable shards, alongside a content-addressed
compressed provenance stream. Every sealed proof frame and every provenance
record is re-read. The report separates same-profile synthesis savings,
wrapper/encoding overhead, compressed sizes and reused executed edge coverage.
It states zero newly executed cube audits for pure conversion. An export is
not production registration or goal completion; no surviving strictly smaller
alternative means further synthesis is still needed.

Resume and export also validate the nested provenance claims themselves:
source-free flags, the `fresh` audit table and exact task, conversion versions
and scopes, semantic-identity links, absence of invented cube audits, and the
chosen definition's actual byte count. Corruption controls change both copies
of a nested receipt together, so agreement between duplicated fields alone
cannot pass the gate. A changed alternative/source pair must retain distinct
map identities and its correct same-profile selection disposition. These
checks protect checkpoint/report integrity; they are not new mathematical
acceptance or new corpus coverage.

After the existing frozen workflow ends, the full-scope commands are:

```bash
PYTHONPATH=src:tools VENV_PYTHON -m corpus_derivations.pipeline_batch \
  --output NEW_CONVERSION_RUN prepare --source COMPLETED_SOURCE --synthesis COMPLETED_SYNTHESIS
PYTHONPATH=NEW_CONVERSION_RUN/implementation/src:NEW_CONVERSION_RUN/implementation/tools \
  VENV_PYTHON -m corpus_derivations.pipeline_batch --output NEW_CONVERSION_RUN run
PYTHONPATH=NEW_CONVERSION_RUN/implementation/src:NEW_CONVERSION_RUN/implementation/tools \
  VENV_PYTHON -m corpus_derivations.pipeline_export --run NEW_CONVERSION_RUN --output NEW_EXPORT
```

The named values are absolute paths chosen for the completed source, synthesis,
new immutable outputs and locked Python runtime. Existing run directories must
not be reused as new outputs. The running source/synthesis cohort remains on
its original frozen implementation; these commands are not started while it
is still live.

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
