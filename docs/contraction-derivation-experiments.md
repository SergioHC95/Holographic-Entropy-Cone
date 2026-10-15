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

### Bounded speed experiments (October 14)

`corpus_derivations.speedups` is an opt-in prototype, not a live-cohort change.
It removes four redundant full-seed replays per candidate-selection call:
construct all descriptions, compare canonical byte costs, and replay only the
winner. Previously every trial was decoded and the winner was decoded again
by its caller (five replays in the measured eligible controls). Non-winning
encodings are explicitly labelled unaccepted. The winning serialized recipe
must still match EVERY intended compatible count, followed by unchanged
independent original-cube acceptance and the later separate fresh audit.
An uncompetitive winner may skip replay altogether; it produces no accepted
alternative and the verified source remains authoritative.

The prototype also evaluates integer cut formulas as exact Python-integer
bitsets over the complete compatible domain. OR computes each threshold set;
integer NumPy accumulation sums its Boolean layers. This replaces a separate
term-by-term Python query at every compatible vertex. Syntax, literal-mask
bounds, complete-domain coverage and capacity-limited integer arithmetic are
preserved. The original scalar evaluator remains the equivalence reference.

A source/implementation/binary-bound single-process experiment used tasks
18, 24 and 84667, two alternating-order timing pairs, and exact equality of
all compatible values and selected serialized bytes. The 11,760-vertex,
L=17 control (task 84667) improved saved-source decoding from 1.880 s to
0.0635 s (29.6x). Its candidate-selection-plus-caller-replay stage improved
from 16.77/18.55 s to 5.33/5.90 s: 3.15x aggregate paired wall time and
2.54x measured Python-plus-reaped-closure-child CPU. These stage timings do
not establish the same improvement for smoothing, verification or the whole
campaign.

The small controls' aggregate selection ratios were 2.09x and 1.13x; one
tiny optimized timing was slower, and an unchanged closure-source decoder
also had a slower individual observation. Host contention and millisecond
startup costs prevent universal-speedup claims. All three identical winners
passed an actually executed independent audit: 1,114,196 original-cube edges
in total. These are three controls, not additional corpus coverage or newly
imported production proofs. The largest sampled experiment RSS was 283.5 MiB;
sampled experiment-plus-live-cohort RSS stayed below 1.78 GiB, not a measured
peak or a memory reservation guarantee.

Nine unit controls include 100 randomized exact cut programs, non-byte-aligned
domains, empty outputs, fractional seeds using the unchanged decoder,
winner-only replay, uncompetitive candidates and corrupt winning values.
The experiment's immutable local report is under
`/Users/sergio/.hec/contraction-speedups-20261014.gJB6Zu/report.json` (SHA256
`e5178656c2a6979aaac13f254c5d3016261478099f7adb904cdb4329ff569a1c`).
The frozen eight-worker corpus implementation is unchanged. Wider differential
controls and a separately reviewed, checkpoint-preserving handoff would be
required before deploying the prototype; neither is claimed here.

The subsequent rollout gate compares the largest stored cut recipe in each
of the eleven observed source-dimension categories: 1,070,179 exact compatible
count cells agree with the scalar decoder. These are deliberate stress
controls, not whole-corpus equivalence coverage and not another cube audit.
The complete regression suite then passed 152 tests, including optimized
attempt/fresh verification, immutable inherited rows, live-controller refusal,
and committing all in-flight results on a cooperative drain request.

After the user's explicit authorization to replace production with properly
validated speedups, `speedup_rollout` provides a quiescent generation handoff.
It changes only the bound execution optimization; smoothing, source identities,
worker count, memory caps and independent native binaries remain fixed.
Every committed attempt, proof blob and fresh receipt is preserved byte for
byte in an immutable inherited checkpoint and checked on resume/export.
The first old-generation interrupt may require retrying up to eight
uncommitted attempts; they are not completed recorded proofs. New generations
support `pause-after-inflight.json` to stop admission, drain and commit current
work before a later rollout. The active operational pointer records the
actual handoff/generation; the three-case benchmark report remains historical.

### Reusing a bound compact input seed

`source_seed_benchmark` tests an additional source-construction optimization.
For catalogue-backed inputs only, an original compact compatible-count proof
already contains the seed from which the first derivation pass generated its
sparse recipe. Reading that seed can avoid running the closure decoder again.
This is not permission to read the primitive campaign's original Boolean
archives, and the prototype explicitly refuses those inputs.

Five hand-picked controls (68492, 80022, 47976, 8380 and 18) compared all
855,264 compatible cells against the saved-recipe decoder. All matched exactly.
The four larger controls took 3.58--4.52 s for saved-recipe reconstruction and
0.30--0.40 s for warm compact-input reads: 12.05x aggregate observed decode wall
time. The first cold catalogue/shard-validated read took 1.13 s. The experiment
includes proof/catalogue identity checks and records cold versus amortized
costs separately. It is neither a representative sample nor a whole-campaign
speedup. Its report is
`/Users/sergio/.hec/contraction-source-seed-speed-20261014.1PCH8r/result.json`,
SHA256 `3477a102e84546dbfb067a5e452a98b6a9449240b1f2fa4c07d9f2df44d712cf`.

No new cube audit was executed by this lossless-input comparison. Before a
production rollout, the loader must explicitly bind input proof/catalogue IDs,
the previously executed compatible-value equivalence, saved-source recipe
hash and frozen source implementation. It must remain a construction input
optimization, not an acceptance cache. Every synthesized winner must still
receive the exact original-cube check and a separate source-free saved-recipe
audit; that fresh phase must NOT use original compact inputs. Only the common
compatible seed is reused: an older input's extension outside that domain is
not silently substituted for the current fixed full-map extension.

The reviewed `compact_source.Reader` now implements that construction-only
provenance contract. It binds the frozen source run and ordered manifest,
actual input proof/catalogue/shard identities, saved recipe SHA, executed
first-pass equality report and the source recipe's own fresh full-cube audit.
Only integral sparse-closure sources with catalogue-backed seed tables use
the shortcut. Primitive Boolean archives and non-table input constructors do
not. Missing optional compact inputs fall back to the saved standalone recipe;
changed hashes or contradictory provenance fail closed. No acceptance result
is cached, and every candidate still goes through smoothing's exact checks,
winner replay, independent full-cube acceptance and separate source-free fresh
verification. The fresh function does not call this reader.

The same five controls passed all 855,264 count comparisons through the actual
reviewed reader, not just the earlier direct-input prototype. Its gate is
`/Users/sergio/.hec/contraction-compact-source-gate-20261014.2Y09XW/result.json`.
The combined suite passed 161 tests, including catalogue/manifest tampering,
false equivalence identity, missing fresh evidence, archive exclusion,
optional-input fallback and independent acceptance after seed reuse. The
standing user authorization permits a checkpoint-preserving production
rollout; the active operational pointer records the released generation.

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

### Single-parse installed-package audits (October 14, late PDT)

The upcoming repository-layout QA path previously constructed a complete
checked reconstruction program in the catalogue reader, discarded it, then
constructed the same program again in the mathematical verifier. The new
`ReconstructionCatalog.audit_entry` keeps the canonical frame, shard hash,
proof identity and inequality identity checks, and delegates the closed
program construction and actual original-cube audit directly to the same
`ReconstructionVerifier`. Ordinary public catalogue reads still perform their
syntax checks. No unchecked document, stored acceptance cache, legacy runtime
fallback, sampling or skipped cube edge is introduced.

The full staged-corpus runner now uses that path, before its own exact
task/proof/semantic-identity and coverage checks. This is preparation for the
next frozen QA generation, not a modification of the running conversion or
a promotion of the repository's primary reader. All 244 combined regression
tests passed, including the actual staged-run/resume fixtures, rejected
unknown syntax and legacy documents, corrupted shard hashes, incorrect or
boolean coverage counts, wrong identities, seed-only receipts, bad boundaries,
and a constructor-count control showing one program construction per audit.

`corpus_derivations.catalog_audit_benchmark` preserves the paired experiment.
Five saved controls (18, 68492, 84667, 80289 and 80263) cover all four seed
primitives, including two large rational cases. Both arms use the SAME saved
canonical definitions and exact package verifier; each performs an actual
complete cube audit. Two alternating-order timing pairs include private
native-process startup, shutdown and reaped CPU. All expected proof and
semantic identities and exact vertex/edge counts agreed.

Across those controls, combined Python-plus-reaped-child CPU was 20.320647 s
for the double-parse path and 18.809438 s for single-parse: 1.0803x, or 7.44%
less measured CPU. The rational table control was 1.1427x and the rational
DAG 1.0907x; closure controls were essentially unchanged (0.9974x and
0.9979x), not demonstrated improvements. Aggregate wall time was 1.0491x,
but the DAG wall measurement was slightly slower under host contention.
These hand-picked results are not a population-wide performance estimate or
a universal speedup guarantee.

The timing repetitions actually checked 279,183,680 original-cube edges in
total, including repeated audits of the same five maps; they are not new
whole-corpus coverage or newly proved inequalities. Maximum sampled combined
experiment-plus-conversion RSS was 1,397,587,968 bytes, below the unchanged
64 GiB cap; this is a sample maximum, not a peak-memory guarantee. Eight
conversion workers were preserved and no new persistent corpus pool started.

The immutable experiment report is
`/Users/sergio/.hec/contraction-single-parse-audit-20261014.mMwDUv/report.json`,
SHA256 `fa1d8cc2b995ad5ac9eaa9234ec5f6dda3f28c698246f7d6c0e7a164dec9583b`.
Full conversion/export, actual complete staged-data audits, final integration
review and repository/CI promotion remain separate required gates. LFS and
the clean PR-preparation branch were not changed.

### Unified repository/CI contract preparation

`hec.reconstruction_checks` is an opt-in candidate for the final standardized
repository gate. It reads only unified reconstruction definitions for actual
mathematical checks, using `ReconstructionCatalog.audit_entry` and the exact
installed-package verifier. This does not switch the primary loader, the
existing `hec.checks` command, or the production GitHub workflow before the
complete migration audit.

The inequality catalogue and proof index must bind exactly one selected proof
per inequality, with the correct party count. Every currently listed facet
must have an exact proof binding. Additional validity proofs are deliberately
NOT added to the facet list and receive no inherited rank/facethood claim.
Facet order, primitive representatives and orbit uniqueness retain the same
shared structural checks. The separate facet/ray rank and graph jobs remain
required; contraction validity alone is not a rank certificate.

The current CI repeats the same exhaustive map audit in both its contraction
jobs and its database job. The candidate plan instead assigns every physical
proof shard to exactly one contraction partition, alongside a separate global
`database-bindings` job for metadata and facet-list structure. A bindings job
neither reads proof payloads nor confers mathematical acceptance. CI must
require ALL planned contraction partitions, bindings, facet/ray ranks and
graphs at the same immutable checkout. This removes a duplicate full-cube
pass, not an independent construction/verification method. No measured CI
runtime improvement or live workflow rollout is claimed here.

Each contraction partition preflights exact expected proof and original-cube
edge counts against the bound indexes, executes every selected audit, rejects
duplicate/missing/out-of-partition results, and checks complete coverage.
It reads no original source tables or stored validity flags. A missing or
corrupt proof payload fails the mathematical job even if metadata checks pass.
Empty datasets cannot silently pass. The full CI plan has no party/subset
switch; individual contraction commands require an explicit party count and
physical partition. The standalone `database` command still executes BOTH
global bindings and every full-map audit, including extra nonfacet proofs.

For example, against a completed, fully staged repository-layout dataset:

```bash
PYTHONPATH=src VENV_PYTHON -m hec.reconstruction_checks plan \
  --root VERIFIED_DATA --lfs-ns-json '[6]'
PYTHONPATH=src VENV_PYTHON -m hec.reconstruction_checks database \
  --root VERIFIED_DATA --n 6
```

The mathematical commands require the trusted closure/full-cube native
backends through `HEC_RECONSTRUCTION_CLOSURE` and
`HEC_RECONSTRUCTION_VERIFIER`, except for the explicitly bounded complete
arbitrary-precision reference cases. No proof document selects an executable.
CI runner memory sizing remains a required integration gate: the current
native auditor materializes the full cube, so a small fixture or the local
128-GiB host cannot establish hosted-runner capacity for the largest cases.

A metadata-only census of the CURRENT research checkout (October 14 late
PDT, not the new full-corpus export) planned all 80,227 indexed proofs and
9,501,708,505 original-cube edges: nine contraction partitions, six binding
jobs, thirteen facet-rank jobs, six graph jobs and six ray-rank jobs. That
40-job plan executed zero new mathematical audits and changed no payload,
LFS cache, reader registration or workflow. The actual migration target
remains all 84,690 unique source identities; this smaller historical-layout
census is not a substitute for their complete staged-data audit.

The combined regression suite passed 256 tests. After adding the explicit
duplicate-party-directory guard, the updated 21-test repository/checks suite
also passed, including actual CLI audits and a full database rejection of an
invalid extra nonfacet proof. These are software/fixture checks, not a new
full-corpus mathematical pass. No active controller or worker was restarted.

### Bounded-memory full-cube auditor prototype

`audit_tiled.cpp` is an opt-in mode-0-only experiment, not the production
backend. It reuses the existing independent geometry, complete-domain, seed
and protocol checks, preserving uint64 values and uint128 distance sums.
Small maps keep the existing full-table path. Above a trusted primary-buffer
budget, it evaluates fixed low-axis tiles and one adjacent tile at a time.
Every vertex receives its bound checks in exactly one base tile; low-axis
edges belong to that tile, and high-axis edges belong to their bit-zero
endpoint tile. Every boundary image is checked, and the exact total must be
`L*2**(L-1)`. Repeated evaluation trades CPU for storage, not for sampling.

Eight native controls exercised forced one-row/tiny tiles, every queried
vertex of the small weighted/nested/rational fixtures, a real n=5 fixture,
empty outputs, zero-dimensional cubes and explicit insufficient-budget
failures. A distance exceeding uint64 but correctly rejected using uint128
could not wrap into acceptance. The combined suite passed 265 tests.

The saved five-control paired benchmark uses a 256-MiB PRIMARY output-buffer
budget. It does not bound the whole process to 256 MiB: the seed, compatible
domain index, protocol buffers and Python parent are separate. Unix `wait4`
measures each private native child's actual peak RSS, without conflating it
with a later live sample or summing independent historical peaks.

Both arms executed complete cube audits and exact rational query
differentials, checking 279,183,680 edges across timing repetitions. For the
L=21/G=22 control, native peak RSS fell from 385,024,000 to 200,425,472 bytes,
but combined measured CPU increased by about 1.62x. For L=22/G=25 it fell from
864,665,600 to 235,503,616 bytes, with about 1.87x CPU cost. Smaller controls
retained the full-table path. These are native-request timings on warm seeds,
not end-to-end construction or population-wide performance estimates.

Accordingly this is NOT deployed as a general production speedup. It offers
a possible bounded-memory CI path, pending largest-case/full-data checks and
a resource policy; the healthy conversion and its fast bound binaries stay
unchanged. No proof format, source artifact, LFS state or PR branch changed.
The report is
`/Users/sergio/.hec/contraction-tiled-controls-20261014.x434S7/report.json`,
SHA256 `4a8415c937d0d151bb9c5ac5b5260e08eedc19a18bb4924270c0d73f18bbec39`.

The subsequent `large_tiled_control` used existing task 80231, binding its
actual saved source definition and its own previously executed source-free
fresh audit. It converted all compatible values exactly, saved and re-read
the standard standalone pipeline, then executed a NEW full-cube audit using
the tiled prototype. No solver or synthesis search ran, and the earlier
budget-limited alternative disposition remains unchanged.

For this L=25/G=26 case the native auditor actually checked 33,554,432
vertices and 419,430,400 original-cube edges, with exact rational constructor
query differentials as additional implementation controls, not sampling-based
acceptance. Its primary output buffers occupied 218,103,808 bytes under the
268,435,456-byte budget; measured private-native peak RSS was 383,303,680
bytes (about 366 MiB). The avoided full output-table allocation is calculated
as 6,979,321,856 bytes (6.5 GiB), NOT a measured baseline peak for this case.
Measured native CPU was 66.677196 s and request wall time 82.805954167 s.

This is one existing valid inequality, not another new proof/solve or
whole-corpus/hosted-runner certification. The result is
`/Users/sergio/.hec/contraction-tiled-largest-20261014.nDAXrg/report.json`,
SHA256 `d5316f389726aa156e95b296e7d9bdd265bacfaa93768794d9eb3fff7c0fd8f0`.
The fast production binaries and live conversion were preserved. Selecting
the final CI memory policy and verifying all staged artifacts remain required.

### Standalone standard verifier selected for staged QA

`tools/verify_reconstruction.cpp` is now a standalone standard-proof native
verifier, without includes or runtime fallback to the experimental/Boolean
import tools. Its full-table and tiled paths call ONE exact point evaluator.
The mode-0 protocol, complete compatible-domain reconstruction, exact scaled
bounds, occurrence images and exhaustive original-cube edges are unchanged.
The default primary-output-buffer budget is 256 MiB; total RSS also includes
the domain index, seed, protocol buffers and Python parent.

The package adapter can bind a trusted working-byte limit to its actual native
launch arguments and requires the reply to acknowledge that exact limit.
The field is operator/CI configuration, never proof-specified executable code
or a way to reduce mathematical coverage. Invalid/inexact limits fail closed.
The QA runner may select this binary only with its explicit SHA256 and a
source-bound, complete all-four-primitive control report. Source changes,
partial/boolean coverage and unacknowledged budgets invalidate the selection.
Admission uses the bound output-buffer budget plus the full domain index and
conservative Python/seed reserves; 64-GiB RSS guards and eight approved workers
remain unchanged.

The standalone binary passed the eight forced-layout/native differential
tests, package-adapter controls and the full 271-test regression suite. Five
actual saved controls repeated 279,183,680 original-cube edges against the
earlier independent full-table binary. These qualify the implementation, not
all 84,690 proofs: the upcoming staged-data run must still execute every map's
full audit itself, without accepting stored flags or these control results.

The selected local binary is
`/Users/sergio/.hec/contraction-standard-verifier-20261014.KgDfUR/verify-reconstruction`,
SHA256 `dee60188230e495cab9896cb647871c4cdaf2bb67824c9ce77c41c679809c777`;
its source SHA256 is
`f45c756c826c2e7719b9d38f3c00d989f71ed7b4774e4f5d1cc4c5e3b939bb35`.
Qualification is saved beside it in `qualification.json`. The actual paired
report is
`/Users/sergio/.hec/contraction-standard-controls-20261014.FBi9Sb/report.json`,
SHA256 `05ed742787d0ea77278db79ca4be34bd8906ec14295e94f522ce780f44628c26`.
No live conversion, primary repository reader, LFS state or CI workflow was
switched by this preparation. The full-data mathematical gate remains pending.

### Unified-only writer and publication discipline

`write_reconstruction_catalog` completes the proposed standard storage API.
It accepts only `compatible-reconstruction-pipeline/1`, requires a nonempty
selection with one proof per inequality, and executes actual complete
original-cube verification before publishing an authoritative catalogue.
Legacy function kinds, optional full tables, seed-only receipts and invalid
boundaries cannot become successful writes. Native paths and verification
implementations remain trusted caller configuration, never proof fields.

The writer owns canonical bytes before verification; changes to a caller's
mutable dict while a backend runs cannot change the published proof. Its
verification result must match those exact proof/inequality identities and
typed complete coverage. It shares only byte framing with the pre-cutover
writer, not an artifact-format fallback. Existing immutable payloads are
reused only when their lengths and hashes match and are never replaced when
corrupt. Destination/catalogue races fail closed.

The authoritative catalogue is linked into place atomically LAST. Failure
after a shard was sealed may leave a reusable content-addressed payload, but
never an index falsely claiming a complete publication. Existing destinations
and unsafe symlink parents are refused before a backend call. These are
local file operations, not Git LFS, billing or publication operations.

All 60 targeted storage/writer/migration tests and the combined 279-test
regression suite passed. Controls include exact write/read re-verification,
duplicate selections, mutation, bad boundaries, corrupted payload reuse and
late failure. This function is not yet registered as the primary repository
writer; the current full-data audit is running its unchanged frozen code.
That audit and final reader/data/schema/CI integration remain required.

### Complete read-only acceptance review before cutover

`repository_acceptance` is a separate read-only promotion precondition, not
another mathematical pass or a command that changes the repository. It
requires the audit controller and native helpers to be idle and takes the
audit lock before reviewing anything. Its CLI cannot narrow the corpus.

It checks every frozen source/binary and actual payload hash, reconciles the
original source identity set, all conversion selections, the party indexes
and every actual successful audit row, then re-reads every stored frame.
Expected vertex/edge totals come from the actual indexed inequalities, not
only duplicate manifest/report claims. Missing rows, unresolved errors,
seed-only or boolean coverage, substituted geometry, changed source/payload
bytes, a different native binary/buffer profile, or an incomplete report
cannot authorize cutover. Review reports explicitly count ZERO newly
executed mathematical audits and inherit no facet/rank claim.

Six complete/tampered tiny fixtures passed, and the combined regression suite
passed 285 tests. The real live audit was also correctly refused without any
worker signal, data write or restart. A passing fixture is not acceptance of
the 84,690-case run: its actual complete idle ledger/report must still pass
this gate, followed by the primary reader/writer/data/schema/CI integration
and independent final review. No LFS, billing or publishing action is implied.
