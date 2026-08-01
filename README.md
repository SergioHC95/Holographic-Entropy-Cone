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
- `contractions.json` contains contraction-map certificates for the listed
  facets.

Rows use primitive integer coefficients in cardinality-then-lexicographic
subset order. Facet and ray files list lifts from lower-party cones first. The
remaining facet rows—historical and newly added—are mixed and sorted
row-lexicographically. The contraction record at each position proves the
facet at that position.

Graphs contain only `edges` and `weights`. Contractions contain only `lhs`,
`rhs`, and `images`.

For n=6, `contractions.json` is a manifest for the aligned
`contractions.packbits.zst` stream. The stream stores one binary contraction
table per facet, in facet-file order, using little-endian row-major packbits.
The manifest records dimensions, hashes, sizes, and ordering information so
the complete stream can be checked without a solver.

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
uv sync --locked --dev
uv run python -m hec.checks database
uv run ruff check .
```

The contraction solver requires a PySAT build exposing Kissat and its raw C
symbols. The tracked Cython sources are built automatically on first use when
the local extensions are absent. On Windows, run the installation and checks
from an x64 Visual C++ environment such as the “x64 Native Tools Command
Prompt for VS”.

Set worker counts explicitly when desired:

```bash
HEC_WORKERS=8 uv run python examples/find_ineq_contractions.py
HEC_GRAPH_WORKERS=4 uv run python examples/find_ray_graphs.py
HEC_CHECK_WORKERS=16 uv run python -m hec.checks facets
```

The corresponding PowerShell form is:

```powershell
$env:HEC_WORKERS = "8"
uv run python examples\find_ineq_contractions.py
$env:HEC_GRAPH_WORKERS = "4"
uv run python examples\find_ray_graphs.py
$env:HEC_CHECK_WORKERS = "16"
uv run python -m hec.checks facets
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
| 6 | 57,940 (11) | 287,558,243 | 4,160 (19) | 15,450,946 | incomplete |

Data updates:

- 2026-07-30: computed and verified the complete n=6 facet-image total,
  287,558,243, for the 57,940 stored representatives.
- 2026-07-28: added 52,211 retained new facet representatives and their
  proved contraction certificates. Historical representative values were
  preserved, and all n=1 through n=6 facet files
  were sorted with lifts first and the remaining old/new rows mixed in
  row-lexicographic order. The 57,940 aligned n=6 contraction tables are
  stored as a 251.7 MiB zstd packbits stream (1.83 GiB raw), with exact
  dimensions and SHA-256 metadata.

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
