# Holographic Entropy Cone

Exact facet inequalities, extreme rays, graph realizations and contraction
proofs for the holographic entropy cones. The facet and ray catalogues are
complete for $n\leq5$; the six-party catalogues are partial.

## Setup and checks

Python dependencies are locked in `uv.lock`. Native exact verification needs
GCC/Clang-compatible C++17 with unsigned 128-bit integers. CI covers Linux and
macOS.

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
**85,668 listed facet representatives**, with exactly matching inequality
and proof catalogues. Candidates without facet certification do not belong
in the accepted data tree.
`data/storage.json` binds every payload to its byte length and SHA256. Ray and
graph shards are at most 16 MiB, preserve ray-row alignment, and use ordinary
Git. Readers check every shard's hash, byte length, and row count; CI still
independently checks every graph realization and exact ray rank. No stored hash
or catalogue metadata substitutes for mathematical verification.

Across all party counts, **85,682 full-map proofs** occupy **34 proof shards**
totalling **182,429,558 bytes**. Git LFS is not required.

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
| 6 | 85,668 | 425,221,538 | 3,763,751 | 18,807,044,308 | 85,668 | partial |

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
