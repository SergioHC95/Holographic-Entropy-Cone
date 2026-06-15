"""Generate minimal contraction maps for every stored facet."""

from __future__ import annotations

import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from hec._extensions import ensure_contraction_extensions
from hec.contractions import find_contraction, minimal_contraction, write_contractions
from hec.data import default_data_root, load_hec_data
from hec.runs import run_generation
from hec.workers import generation_worker_count

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKERS = generation_worker_count()
WRITE_EVERY = 100


def _warm_worker() -> None:
    find_contraction(load_hec_data(2, "facets")[0], 2)


def _worker(n: int, index: int, facet: Sequence[int]) -> tuple[dict, dict, str]:
    start = time.perf_counter()
    result = find_contraction(facet, n)
    seconds = time.perf_counter() - start
    if result["status"] != "proved":
        raise RuntimeError(f"n={n}, index={index}: result={result}")
    timing = {"index": index, "seconds": seconds, "status": result.get("status")}
    return minimal_contraction(facet, n, result), timing, f"n={n}, index={index}: {seconds:.6f}s"


def main() -> None:
    ensure_contraction_extensions()
    run_generation(
        prefix="contractions",
        run_root_parent=REPO_ROOT,
        data_root=default_data_root(),
        kind="facets",
        record_name="contractions",
        worker=_worker,
        writer=write_contractions,
        executor=lambda: ProcessPoolExecutor(max_workers=WORKERS, initializer=_warm_worker),
        workers=WORKERS,
        write_every=WRITE_EVERY,
    )


if __name__ == "__main__":
    main()
