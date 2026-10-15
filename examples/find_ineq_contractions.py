"""Generate standardized exact compact proof catalogs for stored facets."""

from __future__ import annotations

import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from hec._extensions import ensure_contraction_extensions
from hec.checks import _bounded_parallel_map
from hec.contractions import find_contraction
from hec.data import available_ns, default_data_root, load_hec_data
from hec.proof_store import write_proof_dataset
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
    if result["status"] != "proved":
        raise RuntimeError(f"n={n}, index={index}: no verified full-cube solution")
    return result["proof"], {"index": index, "seconds": time.perf_counter() - start}


def main() -> None:
    ensure_contraction_extensions()
    run_root, _timings = create_run_output("contractions", REPO_ROOT)
    for n in available_ns(root=default_data_root()):
        facets = load_hec_data(n, "facets")
        directory = run_root / f"n={n}"
        timings = []
        with ProcessPoolExecutor(max_workers=WORKERS, initializer=_warm_worker) as pool:
            results = _bounded_parallel_map(
                pool, _worker, ((n, i, facet) for i, facet in enumerate(facets)), max_pending=2 * WORKERS
            )

            def proofs(results=results, timings=timings):
                for proof, timing in results:
                    timings.append(timing)
                    yield proof

            stored = write_proof_dataset(directory, proofs())
        save_json(directory / "timings.json", timings)
        print(f"n={n}: wrote {stored['proofs']} exact compact definitions", flush=True)


if __name__ == "__main__":
    main()
