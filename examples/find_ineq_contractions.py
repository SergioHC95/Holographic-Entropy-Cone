"""Generate standardized exact compact proof catalogs for stored facets."""

from __future__ import annotations

import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from hec._extensions import ensure_contraction_extensions
from hec.checks import _bounded_parallel_map
from hec.contractions import _image_table, check_contraction, find_contraction
from hec.count_proofs import compatible_vertices, geometry, make_count_proof
from hec.data import available_ns, default_data_root, load_hec_data
from hec.inequality_records import inequality_catalog, write_inequality_catalog
from hec.proof_store import ProofCatalog, write_proof_catalog
from hec.runs import create_run_output
from hec.serialization import save_json
from hec.workers import generation_worker_count

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKERS = generation_worker_count()


def _warm_worker() -> None:
    find_contraction(load_hec_data(2, "facets")[0], 2)


def _worker(item: tuple[int, int, Sequence[int]]) -> tuple[dict, dict]:
    n, index, facet = item
    start = time.perf_counter()
    result = find_contraction(facet, n)
    if result["status"] != "proved" or not check_contraction(facet, n, result)["ok"]:
        raise RuntimeError(f"n={n}, index={index}: no verified full-cube solution")
    problem = geometry(n, tuple(facet))
    table = _image_table(result["images"], problem.L, sum(problem.beta)) if problem.G else None
    offsets = [0]
    for cap in problem.beta:
        offsets.append(offsets[-1] + cap)
    rows = (
        tuple(int(table[vertex, offsets[g] : offsets[g + 1]].sum()) for g in range(problem.G))
        for vertex in compatible_vertices(problem)
    )
    proof = make_count_proof(problem, rows, transport=True)
    return proof, {"index": index, "seconds": time.perf_counter() - start}


def main() -> None:
    ensure_contraction_extensions()
    run_root, _timings = create_run_output("contractions", REPO_ROOT)
    for n in available_ns(root=default_data_root()):
        facets = load_hec_data(n, "facets")
        directory = run_root / f"n={n}"
        directory.mkdir()
        timings = []
        with ProcessPoolExecutor(max_workers=WORKERS, initializer=_warm_worker) as pool:
            results = _bounded_parallel_map(
                pool, _worker, ((n, i, facet) for i, facet in enumerate(facets)), max_pending=2 * WORKERS
            )

            def proofs(results=results, timings=timings):
                for proof, timing in results:
                    timings.append(timing)
                    yield proof

            write_proof_catalog(directory / "proofs.json", proofs())
        stored = ProofCatalog(directory / "proofs.json")
        write_inequality_catalog(directory / "inequalities.json", inequality_catalog(stored))
        save_json(directory / "timings.json", timings)
        print(f"n={n}: wrote {len(stored)} exact compact definitions", flush=True)


if __name__ == "__main__":
    main()
