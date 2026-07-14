# Holographic Entropy Cone (HEC) #

The HEC is a family of polyhedral cones $H_n$ labelled by the number of parties $n \in \mathbb{N}$.  
Each $H_n$ can be dually described by either its facet inequalities or its extreme rays.  
A complete characterization of $H_n$ requires knowledge of both sets of extremal elements.  
This has only been accomplished for $n \leq 5$, and results for $n \geq 6$ are only partial.  


## Description ##

This repository collects all known extremal elements of $H_n$ for $n \leq 6$.  
Each $H_n$ is invariant under the symmetric group of degree $n+1$.  
Files contain one representative element per symmetry orbit.  
Elements of $H_n$ obtained as lifts from $H_k$ for $k < n$ are listed first.

Data files live under `data/n=*/`:

- `data/n=*/facets.json` contains facet-inequality orbit representatives.
- `data/n=*/rays.json` contains extreme-ray orbit representatives.
- `data/n=*/graphs.json` contains exact, monotone quality-gated graph
  representatives for the listed rays.
- `data/n=*/contractions.json` contains contraction-map certificates for the listed facets.

Facets and rays are integer rows in cardinality-then-lexicographic subset order.
Graphs are records with only `edges` and `weights`. Contractions are minimal
records with only `lhs`, `rhs`, and `images`.


## Python package ##

The repository also contains a `hec` package under `src/hec/`.

- `hec.contractions` searches and verifies contraction maps for
  inequalities.
- `hec.rank` checks facet and extreme-ray rank from supporting orbit data.
- `python -m hec.checks {graphs,contractions,facets,rays}` validates the
  official repository data.
- `hec.graphs` realizes entropy vectors by weighted graphs using the
  Avis-Hernandez-Cuenca MILP construction. It combines exact preprocessing,
  symmetry-reduced fixed-vertex search, a deterministic SCIP/HiGHS portfolio,
  and solver-independent exact rational min-cut verification.
- `hec.data` locates and reads official repository JSON data.
- `hec.runs` manages timestamped output folders for generated graph and
  contraction searches.
- `hec.symmetry` provides permutation actions and symmetry-orbit filtering for
  rays and inequalities.
- `hec.coordinates`, `hec.bits`, and `hec.serialization` hold the
  shared low-level machinery without a generic utilities bucket.

Install into a Python environment created on the same operating system that will
run the code.

On macOS or Linux, install with:

```bash
uv sync --locked --dev
uv run python - <<'PY'
from hec.contractions import find_contraction, check_contraction
from hec.data import load_hec_data
from hec.graphs import check_graph, find_graph
from hec.contraction_solver import _SAT_BACKEND

print(len(load_hec_data(6, "rays")))
print(_SAT_BACKEND)

certificate = find_contraction([1, 1, -1], 2)
print(check_contraction([1, 1, -1], 2, certificate)["ok"])

graph = find_graph([1, 1, 0], max_vertices=3)
print(check_graph(graph["graph"], [1, 1, 0], graph["n"], match="ray")["ok"])
PY
uv run ruff check .
```

The macOS/Linux contraction solver uses the direct Kissat C-symbol path exposed
by PySAT. If that ABI is not present, import fails with an explicit solver
installation error. The tracked Cython sources are built automatically in-place
on first contraction-solver use when the compiled local extensions are absent.

On Windows, install the locked Python dependencies first and run from an x64
Visual C++ build environment, such as the "x64 Native Tools Command Prompt for
VS", so the automatic extension build can find a compiler:

```powershell
uv sync --locked --dev
$env:DISTUTILS_USE_SDK = "1"
$env:MSSdk = "1"
@'
from hec.contractions import find_contraction, check_contraction
from hec.contraction_solver import _SAT_BACKEND

print(_SAT_BACKEND)
certificate = find_contraction([1, 1, -1], 2)
print(check_contraction([1, 1, -1], 2, certificate)["ok"])
'@ | uv run python -
uv run ruff check .
```

The contraction solver uses the same direct Kissat/Cython backend on every
platform. Import fails if the installed PySAT build does not provide the
required Kissat solver and raw Kissat C symbols.

The deterministic graph finder pins each solver to one thread and a fixed seed,
trying equivalent SCIP indicator constraints before native HiGHS. A valid SCIP
topology is polished by a fixed-selector continuous HiGHS solve when time remains.
Every incumbent must satisfy the original one-hot model and exact rational
minimum cuts; a polish is accepted only when it strictly improves (normalized
total capacity, entropy multiplier, maximum weight, total weight, edge count).
Limits and backend errors are never themselves treated as infeasibility.

Generation scripts use process workers. Contraction generation defaults to
`max(1, os.cpu_count() - 1)` workers. Graph generation defaults to at most four
workers unless `HEC_GRAPH_WORKERS` is set, because each MILP solve is already
CPU-heavy. Rank verification uses Numba threads and defaults to at most 16
workers unless `HEC_CHECK_WORKERS` is set. Set `HEC_WORKERS`,
`HEC_GRAPH_WORKERS`, or `HEC_CHECK_WORKERS` to a positive integer to make a
run's worker count explicit:

```bash
HEC_GRAPH_WORKERS=4 uv run python examples/find_ray_graphs.py
HEC_WORKERS=8 uv run python examples/find_ineq_contractions.py
HEC_CHECK_WORKERS=16 uv run python -m hec.checks facets
```

```powershell
$env:HEC_GRAPH_WORKERS = "4"
uv run python examples\find_ray_graphs.py
$env:HEC_WORKERS = "8"
uv run python examples\find_ineq_contractions.py
$env:HEC_CHECK_WORKERS = "16"
uv run python -m hec.checks facets
Remove-Item Env:\HEC_GRAPH_WORKERS
Remove-Item Env:\HEC_WORKERS
Remove-Item Env:\HEC_CHECK_WORKERS
```

## Summary ##

Orbit-representative and distinct-image counts:
|  n  | facet reps (lifts) | facet images | ray reps (lifts) | ray images | status     |
| :-: | :----------------: | :-------------------: | :--------------: | :-----------------: | :--------: |
| 1   | 1 (0)              | 1                     | 1 (0)            | 1                   | complete   |
| 2   | 1 (0)              | 3                     | 1 (1)            | 3                   | complete   |
| 3   | 2 (1)              | 7                     | 2 (1)            | 7                   | complete   |
| 4   | 2 (2)              | 20                    | 3 (2)            | 20                  | complete   |
| 5   | 8 (3)              | 372                   | 19 (3)           | 2,267               | complete   |
| 6   | 1,875 (11)          | 8,655,773             | 4,151 (19)        | 15,408,106          | incomplete |

Distinct image counts sum the actual $S_{n+1}$ orbit sizes of the listed
representatives, so repeated images from stabilizer symmetries are counted once.

Pinned sequential generation timing stats:
| generated data | records | mean | median | max | sum |
| :------------- | ------: | ---: | -----: | --: | -----------------: |
| contractions   | 1,889   | 0.248 s | 0.164 s | 1.823 s | 468.519 s |
| graphs (fixed-N replay) | 4,177 | 3.508 s | 0.435 s | 10,247.705 s | 14,654.463 s |

The graph row is a sequential one-worker fixed-N replay at each stored graph's
vertex count, not a smallest-realization search. Candidates and stored graphs
are independently normalized and checked by exact rational minimum cuts;
promotion is monotone under the quality tuple above, with ties retaining the
stored graph. All 4,177 representatives verify against their paired rays.
Timings are host-specific: 4,176 rows were recomputed in 4,406.758 s, while the
sole 15-vertex row reused its verified 10,247.705 s native-HiGHS result because
the SCIP-only polishing change cannot affect that winning path.

## Attribution ##

If you find this data useful for your research, please consider citing the following papers.

 * Complete description of $H_n$ for $n \leq 5$ from [arXiv:1903.09148](https://arxiv.org/abs/1903.09148):
~~~bibtex
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
      note           = "Data available at \url{https://github.com/SergioHC95/Holographic-Entropy-Cone}"
  }
~~~


 * Partial description of $H_n$ for $n=6$ from [arXiv:2309.06296](https://arxiv.org/abs/2309.06296):
~~~bibtex
  @article{n6hec,
      author         = "Hern\'andez-Cuenca, Sergio and Hubeny, Veronika E. and Jia, Frederic",
      title          = "{Holographic Entropy Inequalities and Multipartite Entanglement}",
      eprint         = "2309.06296",
      archivePrefix  = "arXiv",
      primaryClass   = "hep-th",
      reportNumber   = "MIT-CTP/5610",
      month          = "9",
      year           = "2023",
      note           = "Data available at \url{https://github.com/SergioHC95/Holographic-Entropy-Cone}"
  }
~~~
