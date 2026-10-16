# Holographic Entropy Cone

The Holographic Entropy Cone (HEC) is a family of polyhedral cones
\(H_n\), labelled by the number of parties \(n\). Each cone has a dual
description in terms of facet inequalities and extreme rays. The cones are
known completely for \(n \leq 5\); the \(n=6\) data in this repository is
partial.

## Data

The repository contains one representative from each known full-symmetry orbit
under \(S_{n+1}\). Data files live under `data/n=*/`:

- `facets.json` contains facet-inequality representatives.
- `rays.json` contains extreme-ray representatives.
- `graphs.json` contains exact graph realizations for the listed rays.
- `inequalities.json` binds primitive inequality identities to proof identities.
- `proofs.json` indexes the exact compact contraction proofs.
- `proof-shards/*.proofpack` contains immutable, independently seekable exact
  definitions, committed directly in ordinary Git for every party count.
- `data/storage.json` binds current data paths to byte lengths and hashes.

Rows use primitive integer coefficients in cardinality-then-lexicographic
subset order. Facet and ray files list lifts from lower-party cones first. The
remaining facet rows—historical and newly added—are mixed and sorted
row-lexicographically. Proofs bind to inequalities by content identity, not
by their position in the facet file. Database checks require exact proof bindings for every listed facet. Additional
validity proofs are recorded separately; a contraction does not certify facethood.

Graphs contain only `edges` and `weights`. A contraction proof defines an
exact rational count map on every vertex of the original source cube.
Repeated RHS terms are grouped; clearing scales are explicit. Enumerated
Boolean tables are optional audit exports rather than the active interface.

The authoritative format is specified in
[Exact contraction proof standard](docs/contraction-proof-standard.md).
`hec.reconstruction` defines one closed reconstruction pipeline with four seed
primitives. `hec.proof_store` exposes only that strict reader/writer. No historical
format readers, migration tools, compatibility adapters or fallback paths remain.
The supported CLI, storage inventory, authoring and CI lifecycle are documented
in [The supported repository pipeline](docs/repository-pipeline.md).

The corpus contains **85,047 self-contained proofs**, including 85,033 n=6
inequality identities. Not every validity proof is asserted to define a facet.
Proof frames occupy 178,456,073 bytes in 17 ordinary-Git shards.

CI independently reconstructs every saved map and checks all bounds,
party/purifier images and weighted cube edges. Complete-proof partitions avoid
duplicate audits; metadata bindings and existing rank/graph checks are
separate required jobs. Required data arrives with Git: no Git LFS installation,
payload hydration service, transfer cache or external artifact host is needed.
CI verifies all data hashes and rejects pointers or oversize blobs throughout
the checked-out commit's ancestry. Sparse Git checkouts limit each mathematical
partition to its owned proof shards. Historical recovery artifacts are kept
outside the current repository, not as alternate accepted formats.

## Python package

The `hec` package under `src/hec/` provides:

- contraction search and certificate checking;
- facet and ray rank checks;
- exact graph realization and verification;
- loading and validating the repository data;
- symmetry actions, canonicalization, and shared serialization utilities.

Install the locked dependencies in an environment on the operating system
where the code will run:

```bash
uv sync --locked --dev --python 3.13.14
uv run hec native build --directory .hec-native
export HEC_NATIVE_DIR="$PWD/.hec-native"
export HEC_RECONSTRUCTION_WORKING_BYTES=268435456
uv run hec storage audit
HEC_CHECK_WORKERS=2 uv run hec check database --root data
uv run ruff check .
```

The contraction solver requires a PySAT build exposing Kissat and its raw C
symbols. The tracked Cython sources are built automatically on first use when
the local extensions are absent. On Windows, run the installation and checks
with a compiler/toolchain providing the required exact native integer types.
The maintained CI platforms are Linux and macOS; proof verification requires
GCC/Clang-compatible C++17 with unsigned 128-bit integer support.

Set worker counts explicitly when desired:

```bash
HEC_WORKERS=2 uv run python examples/find_ineq_contractions.py
HEC_GRAPH_WORKERS=4 uv run python examples/find_ray_graphs.py
HEC_CHECK_WORKERS=2 uv run hec check facets
```

The corresponding PowerShell environment-variable form is:

```powershell
$env:HEC_WORKERS = "2"
uv run python examples\find_ineq_contractions.py
$env:HEC_GRAPH_WORKERS = "4"
uv run python examples\find_ray_graphs.py
$env:HEC_CHECK_WORKERS = "2"
uv run hec check facets
```

## Summary

The table gives orbit-representative counts and the number of distinct images
of those representatives. Stabilizer-related repeats within an orbit are
counted once.

| n | facet reps (lifts) | facet images | ray reps (lifts) | ray images | status |
| :-: | ----------------: | -----------: | ---------------: | ----------: | :----- |
| 1 | 1 (0) | 1 | 1 (0) | 1 | complete |
| 2 | 1 (0) | 3 | 1 (1) | 3 | complete |
| 3 | 2 (1) | 7 | 2 (1) | 7 | complete |
| 4 | 2 (2) | 20 | 3 (2) | 20 | complete |
| 5 | 8 (3) | 372 | 19 (3) | 2,267 | complete |
| 6 | 80,570 (11) | — | 4,161 (19) | 15,455,986 | incomplete |

## Attribution

If you use this data, please consider citing the following papers.

* Complete description of \(H_n\) for \(n \leq 5\) from
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

* Partial description of \(H_6\) from
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
