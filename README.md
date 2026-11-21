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
**87,225 listed facet representatives**, with exactly matching inequality
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

Across all party counts, **87,239 full-map proofs** occupy **84 proof shards**
totalling **192,182,585 bytes**. Git LFS is not required.

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
| 6 | 87,225 | 433,022,198 | 3,804,510 | 19,011,941,308 | 87,225 | partial |

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
