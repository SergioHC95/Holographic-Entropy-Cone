"""Repository data checks."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .contractions import check_contraction, contraction_coeffs
from .coordinates import primitive_vector
from .data import available_ns, data_path, load_hec_data
from .graphs import entropy_vector
from .rank import check_support_rank_prepared, prepare_rank_candidates
from .serialization import load_json
from .workers import generation_worker_count


def check_worker_count() -> int:
    """Worker policy for CPU-heavy verification checks."""
    return (
        generation_worker_count("HEC_CHECK_WORKERS")
        if "HEC_CHECK_WORKERS" in os.environ
        else min(16, generation_worker_count())
    )


def run_check(results: Iterable[str]) -> None:
    try:
        for result in results:
            print(result, flush=True)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


def _stored(root: str | Path | None, *kinds: str) -> Iterator[tuple]:
    for n in available_ns(root=root):
        yield (n, *(load_hec_data(n, kind, root=root) for kind in kinds))


def _check_stored_rank(
    root: str | Path | None,
    fixed_kind: str,
    candidate_kind: str,
) -> Iterator[str]:
    for n, fixed_rows, candidate_rows in _stored(root, fixed_kind, candidate_kind):
        prepared = prepare_rank_candidates(candidate_rows, n)
        workers = check_worker_count()

        def check_row(row, *, n=n, prepared=prepared):
            return check_support_rank_prepared(row, n, *prepared)

        if workers > 1 and len(fixed_rows) >= 32:
            first = check_row(fixed_rows[0])
            if not first["ok"]:
                raise ValueError(f"n={n}, index=0: rank {first['rank']} < {first['target_rank']}")
            with ThreadPoolExecutor(max_workers=workers) as pool:
                checks = enumerate(pool.map(check_row, fixed_rows[1:]), start=1)
                for index, check in checks:
                    if not check["ok"]:
                        raise ValueError(f"n={n}, index={index}: rank {check['rank']} < {check['target_rank']}")
        else:
            for index, row in enumerate(fixed_rows):
                check = check_row(row)
                if not check["ok"]:
                    raise ValueError(f"n={n}, index={index}: rank {check['rank']} < {check['target_rank']}")
        yield f"n={n}: {len(fixed_rows)} ok"


def check_stored_facets(root: str | Path | None = None) -> Iterator[str]:
    yield from _check_stored_rank(root, "facets", "rays")


def check_stored_rays(root: str | Path | None = None) -> Iterator[str]:
    yield from _check_stored_rank(root, "rays", "facets")


def check_stored_contractions(root: str | Path | None = None) -> Iterator[str]:
    for n in available_ns(root=root):
        facets = load_hec_data(n, "facets", root=root)
        contractions = load_json(data_path(n, "contractions", root=root))
        if not isinstance(contractions, list):
            raise ValueError(f"expected a list of contractions in {data_path(n, 'contractions', root=root)}")
        if len(facets) != len(contractions):
            raise ValueError(f"n={n}: {len(facets)} facets but {len(contractions)} contractions")
        for index, (facet, contraction) in enumerate(zip(facets, contractions, strict=True)):
            coeffs, inferred_n = contraction_coeffs(contraction, n)
            if inferred_n != n or tuple(coeffs) != tuple(facet):
                raise ValueError(f"n={n}, index={index}: contraction lhs/rhs do not match stored facet")
            check = check_contraction(coeffs, n, contraction)
            if not check["ok"]:
                raise ValueError(f"n={n}, index={index}: {check['errors']}")
        yield f"n={n}: {len(facets)} ok"


def check_stored_graphs(root: str | Path | None = None) -> Iterator[str]:
    for n, rays, graphs in _stored(root, "rays", "graphs"):
        if len(rays) != len(graphs):
            raise ValueError(f"n={n}: {len(rays)} rays but {len(graphs)} graphs")
        for index, (ray, graph) in enumerate(zip(rays, graphs, strict=True)):
            if primitive_vector(entropy_vector(graph, n)) != primitive_vector(ray):
                raise ValueError(f"n={n}, index={index}: graph/ray mismatch")
        yield f"n={n}: {len(rays)} ok"
