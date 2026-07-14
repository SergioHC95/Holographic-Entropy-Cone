"""Generate graph data for every stored ray."""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from hec.data import default_data_root
from hec.graphs import find_graph, write_graphs
from hec.runs import run_generation
from hec.workers import generation_worker_count

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_VERTICES = 15
WORKERS = (
    generation_worker_count("HEC_GRAPH_WORKERS")
    if "HEC_GRAPH_WORKERS" in os.environ
    else min(4, generation_worker_count())
)
WRITE_EVERY = int(os.environ.get("HEC_WRITE_EVERY", "10"))
if WRITE_EVERY < 1:
    raise ValueError("HEC_WRITE_EVERY must be a positive integer")


def _worker(n: int, index: int, ray: Sequence[int]) -> tuple[dict, dict, str]:
    start = time.perf_counter()
    result = find_graph(
        tuple(int(value) for value in ray),
        max_vertices=DEFAULT_MAX_VERTICES,
    )
    seconds = time.perf_counter() - start
    if result["status"] != "realized":
        raise RuntimeError(f"index={index}: {result}")
    graph = result["graph"]
    vertices = result["total_vertices"]
    timing = {
        "index": index,
        "seconds": seconds,
        "status": result["status"],
        "vertices": vertices,
        "edges": len(graph["edges"]),
    }
    ahc = result.get("ahc", {})
    if isinstance(ahc, dict):
        timing["N"] = ahc.get("N")
        timing["solver"] = ahc.get("solver")
        if isinstance(ahc.get("profile"), dict):
            timing["profile"] = ahc["profile"]
    log = f"n={n}, index={index}, time={seconds:.6f}s, vertices={vertices}, edges={len(graph['edges'])}"
    return graph, timing, log


def main() -> None:
    run_generation(
        prefix="graphs",
        run_root_parent=REPO_ROOT,
        data_root=default_data_root(),
        kind="rays",
        record_name="graphs",
        worker=_worker,
        writer=write_graphs,
        executor=lambda: ProcessPoolExecutor(max_workers=WORKERS),
        workers=WORKERS,
        write_every=WRITE_EVERY,
    )


if __name__ == "__main__":
    main()
