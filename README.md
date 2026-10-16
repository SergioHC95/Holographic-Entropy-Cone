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
Inequality and proof identities instead bind exact party-labelled coefficient
vectors; they are not a separate list of symmetry-inequivalent facets.

| File | Contents |
| --- | --- |
| `facets.json` | Listed facet representatives, with lower-party lifts first. |
| `rays.json` | Extreme-ray representatives, with lifts first. |
| `graphs.json` | One exact graph realization per `rays.json` row, in the same order. |
| `inequalities.json` | Primitive inequality identities and their selected proofs. |
| `proofs.json` | Content-addressed proof/frame index. |
| `proof-shards/*.proofpack` | Seekable exact definitions, stored in ordinary Git. |

Rows use cardinality-then-lexicographic subset order. Non-lift facet rows are
row-lexicographically sorted. Each `inequalities.json` entry selects exactly
one full-map proof in `proofs.json`, bound by content rather than facet-row
position. The six-party data has **85,033 inequality/proof records** but
**80,570 listed facet representatives**: the **4,463 additional records**
establish inequality validity, not an additional facethood claim.
`data/storage.json` binds every payload to its byte length and SHA256.

Across all party counts, **85,047 full-map proofs** occupy **16 proof shards**
totalling **178,245,333 bytes**. Git LFS is not required.

One [mathematical specification](docs/proofs.md) defines the reconstruction
contract. One [schema](schemas/repository.schema.json) describes proofs,
catalogues and the byte inventory. The Python API is `hec.proof_store`:
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
bindings. Complete maps belong to disjoint, cost-balanced jobs; each uses at
most four workers and only its owned shards. All jobs must pass at one commit.

## Construct proofs and graphs

`hec.find_contraction(coefficients, n)` returns a self-contained proof only
after exact independent verification. For compact-domain authoring:

```bash
uv run python examples/compatible_seed_authoring.py \
  --rows data/n=2/facets.json --n 2 --output contractions_example
```

Input rows must be exact integers. Output must be a new directory.
`--scale D` sets an explicit positive search scale. The constructor bounds
compatible counts with exact triangle inequalities, imposes prefix-layer
SAT edge constraints, reconstructs the fixed full map and exhaustively audits
it. Solver models are transient; a resource limit or unfinished search is not
a proof or a mathematical impossibility result.

The examples `find_ineq_contractions.py` and `find_ray_graphs.py` use
`HEC_WORKERS` and `HEC_GRAPH_WORKERS`; checks use `HEC_CHECK_WORKERS`.
In PowerShell, set variables with `$env:HEC_CHECK_WORKERS = "4"`.

## Cone summary

Counts below come from the tracked data, not solver runs. Facet/ray images
count distinct $S_{n+1}$ relabelings, discarding stabilizer-related repeats.
The proof column counts selected full maps, one per inequality record; a
complete proof catalogue does not mean the six-party cone is fully known.

| n | facet reps | facet images | ray reps / graphs | ray images | full-map proofs | cone catalogue |
| :-: | ---------: | -----------: | ----------------: | ---------: | --------------: | :------------- |
| 1 | 1 | 1 | 1 | 1 | 1 | complete |
| 2 | 1 | 3 | 1 | 3 | 1 | complete |
| 3 | 2 | 7 | 2 | 7 | 2 | complete |
| 4 | 2 | 20 | 3 | 20 | 2 | complete |
| 5 | 8 | 372 | 19 | 2,267 | 8 | complete |
| 6 | 80,570 | 399,910,238 | 4,161 | 15,455,986 | 85,033 | partial |

CI recomputes this table and the proof-storage totals from the data; stale
README counts fail the tests. These documentation checks do not replace
independent mathematical verification.

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
