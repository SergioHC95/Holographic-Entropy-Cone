"""Repository data checks."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .contractions import check_contraction, contraction_coeffs, normalize_contraction
from .data import available_ns, data_path, load_hec_data
from .graphs import check_graph
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


def _selected_ns(root: str | Path | None, n: int | None) -> list[int]:
    available = available_ns(root=root)
    if n is None:
        return available
    if n not in available:
        raise ValueError(f"no stored data for n={n}")
    return [n]


def _stored(root: str | Path | None, *kinds: str, n: int | None = None) -> Iterator[tuple]:
    for current_n in _selected_ns(root, n):
        yield (current_n, *(load_hec_data(current_n, kind, root=root) for kind in kinds))


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


def check_stored_contractions(root: str | Path | None = None, *, n: int | None = None) -> Iterator[str]:
    for current_n in _selected_ns(root, n):
        facets = load_hec_data(current_n, "facets", root=root)
        contractions = load_json(data_path(current_n, "contractions", root=root))
        if not isinstance(contractions, list):
            raise ValueError(f"expected a list of contractions in {data_path(current_n, 'contractions', root=root)}")
        if len(facets) != len(contractions):
            raise ValueError(f"n={current_n}: {len(facets)} facets but {len(contractions)} contractions")
        for index, (facet, contraction) in enumerate(zip(facets, contractions, strict=True)):
            if contraction != normalize_contraction(contraction, current_n):
                raise ValueError(f"n={current_n}, index={index}: contraction is not in canonical stored form")
            coeffs, inferred_n = contraction_coeffs(contraction, current_n)
            if inferred_n != current_n or tuple(coeffs) != tuple(facet):
                raise ValueError(f"n={current_n}, index={index}: contraction lhs/rhs do not match stored facet")
            check = check_contraction(coeffs, current_n, contraction)
            if not check["ok"]:
                raise ValueError(f"n={current_n}, index={index}: {check['errors']}")
        yield f"n={current_n}: {len(facets)} ok"


def check_stored_graphs(root: str | Path | None = None, *, n: int | None = None) -> Iterator[str]:
    for current_n, rays, graphs in _stored(root, "rays", "graphs", n=n):
        if len(rays) != len(graphs):
            raise ValueError(f"n={current_n}: {len(rays)} rays but {len(graphs)} graphs")
        for index, (ray, graph) in enumerate(zip(rays, graphs, strict=True)):
            if not check_graph(graph, ray, current_n, primitive=True)["ok"]:
                raise ValueError(f"n={current_n}, index={index}: graph/ray mismatch")
        yield f"n={current_n}: {len(rays)} ok"
