"""Repository data checks."""

from __future__ import annotations

import argparse
import math
import os
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor, wait
from pathlib import Path
from typing import TypeVar

from ._graph_validation import canonical_primitive_ray_graph
from .contractions import check_contraction, contraction_coeffs, minimal_contraction
from .data import available_ns, data_path, load_hec_data
from .graphs import check_graph
from .rank import check_support_rank_prepared, prepare_rank_candidates
from .serialization import load_json
from .symmetry import canonical_vector
from .workers import generation_worker_count

_Input = TypeVar("_Input")
_Output = TypeVar("_Output")


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


def _bounded_parallel_map(
    pool: Executor,
    function: Callable[[_Input], _Output],
    values: Iterable[_Input],
    *,
    max_pending: int,
) -> Iterator[_Output]:
    """Apply ``function`` without eagerly materializing the input iterable."""

    iterator = iter(values)
    pending: dict[Future[_Output], None] = {}

    def submit_next() -> bool:
        try:
            value = next(iterator)
        except StopIteration:
            return False
        pending[pool.submit(function, value)] = None
        return True

    for _ in range(max_pending):
        if not submit_next():
            break
    while pending:
        completed, _ = wait(pending, return_when=FIRST_COMPLETED)
        for future in completed:
            del pending[future]
            yield future.result()
            submit_next()


def _is_primitive_row(row: tuple[int, ...]) -> bool:
    nonzero = [abs(int(value)) for value in row if int(value)]
    return bool(nonzero) and math.gcd(*nonzero) == 1


def _facet_orbit_key(row: tuple[int, ...], n: int) -> tuple[int, ...]:
    return tuple(int(value) for value in canonical_vector(row, n))


def _check_stored_rank(
    root: str | Path | None,
    fixed_kind: str,
    candidate_kind: str,
    *,
    n: int | None = None,
) -> Iterator[str]:
    for current_n, fixed_rows, candidate_rows in _stored(root, fixed_kind, candidate_kind, n=n):
        prepared = prepare_rank_candidates(candidate_rows, current_n)
        workers = check_worker_count()

        def check_row(row, *, current_n=current_n, prepared=prepared):
            return check_support_rank_prepared(row, current_n, *prepared)

        if workers > 1 and len(fixed_rows) >= 32:
            first = check_row(fixed_rows[0])
            if not first["ok"]:
                raise ValueError(f"n={current_n}, index=0: rank {first['rank']} < {first['target_rank']}")

            def check_indexed(pair: tuple[int, tuple[int, ...]]) -> tuple[int, dict]:
                index, row = pair
                return index, check_row(row)

            print(
                f"n={current_n}: validating {len(fixed_rows):,} {fixed_kind} ranks against "
                f"{len(candidate_rows):,} {candidate_kind} rows with {workers} workers",
                flush=True,
            )
            with ThreadPoolExecutor(max_workers=workers) as pool:
                checks = _bounded_parallel_map(
                    pool,
                    check_indexed,
                    enumerate(fixed_rows[1:], start=1),
                    max_pending=2 * workers,
                )
                for completed, (index, check) in enumerate(checks, start=1):
                    if not check["ok"]:
                        raise ValueError(f"n={current_n}, index={index}: rank {check['rank']} < {check['target_rank']}")
                    if completed % 1_000 == 0:
                        print(f"n={current_n}: checked {completed + 1:,}/{len(fixed_rows):,} {fixed_kind}", flush=True)
        else:
            for index, row in enumerate(fixed_rows):
                check = check_row(row)
                if not check["ok"]:
                    raise ValueError(f"n={current_n}, index={index}: rank {check['rank']} < {check['target_rank']}")
        yield f"n={current_n}: {len(fixed_rows)} ok"


def check_stored_facets(root: str | Path | None = None, *, n: int | None = None) -> Iterator[str]:
    yield from _check_stored_rank(root, "facets", "rays", n=n)


def check_stored_rays(root: str | Path | None = None, *, n: int | None = None) -> Iterator[str]:
    yield from _check_stored_rank(root, "rays", "facets", n=n)


def check_stored_contractions(root: str | Path | None = None, *, n: int | None = None) -> Iterator[str]:
    for current_n in _selected_ns(root, n):
        facets = load_hec_data(current_n, "facets", root=root)
        contractions = load_hec_data(current_n, "contractions", root=root)
        if len(facets) != len(contractions):
            raise ValueError(f"n={current_n}: {len(facets)} facets but {len(contractions)} contractions")

        def check_pair(pair: tuple[int, tuple[int, ...], dict], *, current_n=current_n) -> tuple[int, dict]:
            index, facet, contraction = pair
            if set(contraction) != {"lhs", "rhs", "images"}:
                raise ValueError(f"n={current_n}, index={index}: contraction is not a minimal record")
            if minimal_contraction(facet, current_n, contraction) != contraction:
                raise ValueError(f"n={current_n}, index={index}: contraction is not in canonical stored form")
            coeffs, inferred_n = contraction_coeffs(contraction, current_n)
            if inferred_n != current_n or tuple(coeffs) != tuple(facet):
                raise ValueError(f"n={current_n}, index={index}: contraction lhs/rhs do not match stored facet")
            return index, check_contraction(coeffs, current_n, contraction)

        pairs = (
            (index, tuple(facet), contraction)
            for index, (facet, contraction) in enumerate(zip(facets, contractions, strict=True))
        )
        workers = check_worker_count()
        print(f"n={current_n}: validating {len(facets):,} contractions with {workers} workers", flush=True)
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                checks = _bounded_parallel_map(pool, check_pair, pairs, max_pending=2 * workers)
                for completed, (index, check) in enumerate(checks, start=1):
                    if not check["ok"]:
                        raise ValueError(f"n={current_n}, index={index}: {check['errors']}")
                    if completed % 100 == 0:
                        print(f"n={current_n}: checked {completed:,}/{len(facets):,} contractions", flush=True)
        else:
            for index, check in map(check_pair, pairs):
                if not check["ok"]:
                    raise ValueError(f"n={current_n}, index={index}: {check['errors']}")
                if (index + 1) % 100 == 0:
                    print(f"n={current_n}: checked {index + 1:,}/{len(facets):,} contractions", flush=True)
        yield f"n={current_n}: {len(facets)} ok"


def check_stored_facet_database_format(root: str | Path | None = None, *, n: int | None = None) -> Iterator[str]:
    """Check the shared facet/order/contraction representation contract.

    Historical representative values are intentionally preserved.  The
    ordering invariant is lifts first, followed by one row-lexicographically
    sorted mix of all remaining old and new representatives; each contraction
    record is aligned with the facet at the same position.
    """

    lift_counts = {1: 0, 2: 1, 3: 1, 4: 2, 5: 3, 6: 11}
    for current_n in _selected_ns(root, n):
        facets = load_hec_data(current_n, "facets", root=root)
        lift_count = lift_counts.get(current_n, 0)
        if lift_count > len(facets):
            raise ValueError(f"n={current_n}: lift count {lift_count} exceeds facet count {len(facets)}")
        for index, row in enumerate(facets):
            if not _is_primitive_row(row):
                raise ValueError(f"n={current_n}, index={index}: facet is not primitive")
        keys = [_facet_orbit_key(row, current_n) for row in facets]
        if len(keys) != len(set(keys)):
            raise ValueError(f"n={current_n}: duplicate facet symmetry orbit")
        expected = sorted(facets[:lift_count]) + sorted(facets[lift_count:])
        if facets != expected:
            raise ValueError(f"n={current_n}: facets are not ordered lifts-first, then row-lexicographically")

        contractions_path = data_path(current_n, "contractions", root=root)
        raw = load_json(contractions_path)
        if isinstance(raw, list):
            if len(raw) != len(facets):
                raise ValueError(f"n={current_n}: raw contraction count does not match facets")
            for index, record in enumerate(raw):
                if not isinstance(record, dict) or set(record) != {"lhs", "rhs", "images"}:
                    raise ValueError(f"n={current_n}, index={index}: contraction is not a minimal record")
                if minimal_contraction(facets[index], current_n, record) != record:
                    raise ValueError(f"n={current_n}, index={index}: contraction is not in standard minimal form")
        elif isinstance(raw, dict) and raw.get("kind") == "packed-contractions":
            if int(raw.get("schema_version", -1)) != 1 or int(raw.get("n", -1)) != current_n:
                raise ValueError(f"n={current_n}: packed contraction manifest has the wrong schema or party count")
            if int(raw.get("record_count", -1)) != len(facets):
                raise ValueError(f"n={current_n}: packed contraction count does not match facets")
            if raw.get("order") != "same-as-facets-json":
                raise ValueError(f"n={current_n}: packed contractions do not declare facet-file order")
            records = raw.get("records")
            if not isinstance(records, list) or len(records) != len(facets):
                raise ValueError(f"n={current_n}: packed contraction index is not aligned with facets")
            for record in records:
                if not isinstance(record, list | tuple) or len(record) != 2 or int(record[0]) < 0 or int(record[1]) < 0:
                    raise ValueError(f"n={current_n}: packed contraction index contains an invalid table shape")
            # The contractions check streams and verifies every table; this
            # check validates the manifest/order contract without a duplicate
            # expensive proof pass.
        else:
            raise ValueError(f"n={current_n}: unsupported contraction storage format")
        yield f"n={current_n}: {len(facets)} standard facet/contraction records"


def _check_graph_pair(pair: tuple[int, tuple[int, ...], dict, int]) -> tuple[int, str | None]:
    """Validate one graph/ray pair in a process-safe worker."""

    index, ray, graph, n = pair
    if graph != canonical_primitive_ray_graph(graph, n):
        return index, "graph is not in canonical stored form"
    if not check_graph(graph, ray, n, match="ray")["ok"]:
        return index, "graph/ray mismatch"
    return index, None


def check_stored_graphs(root: str | Path | None = None, *, n: int | None = None) -> Iterator[str]:
    for current_n in _selected_ns(root, n):
        rays = load_hec_data(current_n, "rays", root=root)
        graphs = load_json(data_path(current_n, "graphs", root=root))
        if not isinstance(graphs, list):
            raise ValueError(f"expected a list of graphs in {data_path(current_n, 'graphs', root=root)}")
        if len(rays) != len(graphs):
            raise ValueError(f"n={current_n}: {len(rays)} rays but {len(graphs)} graphs")
        pairs = (
            (index, tuple(ray), graph, current_n) for index, (ray, graph) in enumerate(zip(rays, graphs, strict=True))
        )
        workers = check_worker_count()
        print(f"n={current_n}: validating {len(rays):,} graphs with {workers} workers", flush=True)
        if workers > 1 and len(rays) >= 32:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                checks = _bounded_parallel_map(pool, _check_graph_pair, pairs, max_pending=2 * workers)
                for index, error in checks:
                    if error is not None:
                        raise ValueError(f"n={current_n}, index={index}: {error}")
        else:
            for pair in pairs:
                index, error = _check_graph_pair(pair)
                if error is not None:
                    raise ValueError(f"n={current_n}, index={index}: {error}")
        yield f"n={current_n}: {len(rays)} ok"


def main() -> None:
    """Run one repository-data validation from the command line."""

    checks = {
        "contractions": check_stored_contractions,
        "database": check_stored_facet_database_format,
        "facets": check_stored_facets,
        "graphs": check_stored_graphs,
        "rays": check_stored_rays,
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=checks)
    parser.add_argument("--n", type=int, help="check only this stored party count")
    args = parser.parse_args()
    run_check(checks[args.kind](n=args.n))


if __name__ == "__main__":
    main()
