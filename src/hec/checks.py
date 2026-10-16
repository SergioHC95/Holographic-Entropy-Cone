"""Repository data checks."""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor, wait
from pathlib import Path
from typing import TypeVar

from ._graph_validation import canonical_primitive_ray_graph
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


def _shard_indices(length: int, shard_index: int, shard_count: int) -> range:
    """Return the global row indices assigned to one round-robin shard."""

    if shard_count < 1:
        raise ValueError(f"shard count must be positive, got {shard_count}")
    if not 0 <= shard_index < shard_count:
        raise ValueError(f"shard index must be in [0, {shard_count}), got {shard_index}")
    return range(shard_index, length, shard_count)


def _shard_label(shard_index: int, shard_count: int) -> str:
    return "" if shard_count == 1 else f" shard {shard_index + 1}/{shard_count}"


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


def _facet_orbit_keys_chunk(
    chunk: tuple[int, list[tuple[int, ...]], int],
) -> tuple[int, list[tuple[int, ...]]]:
    offset, rows, n = chunk
    return offset, [_facet_orbit_key(row, n) for row in rows]


def _check_stored_rank(
    root: str | Path | None,
    fixed_kind: str,
    candidate_kind: str,
    *,
    n: int | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
) -> Iterator[str]:
    for current_n, fixed_rows, candidate_rows in _stored(root, fixed_kind, candidate_kind, n=n):
        selected = _shard_indices(len(fixed_rows), shard_index, shard_count)
        selected_count = len(selected)
        label = _shard_label(shard_index, shard_count)
        prepared = prepare_rank_candidates(candidate_rows, current_n)
        workers = check_worker_count()

        def check_row(row, *, current_n=current_n, prepared=prepared):
            return check_support_rank_prepared(row, current_n, *prepared)

        if workers > 1 and selected_count >= 32:
            print(
                f"n={current_n}{label}: validating {selected_count:,} {fixed_kind} ranks against "
                f"{len(candidate_rows):,} {candidate_kind} rows with {workers} workers",
                flush=True,
            )
            first_index = selected[0]
            first = check_row(fixed_rows[first_index])
            if not first["ok"]:
                raise ValueError(f"n={current_n}, index={first_index}: rank {first['rank']} < {first['target_rank']}")

            def check_indexed(pair: tuple[int, tuple[int, ...]]) -> tuple[int, dict]:
                index, row = pair
                return index, check_row(row)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                checks = _bounded_parallel_map(
                    pool,
                    check_indexed,
                    ((index, fixed_rows[index]) for index in selected[1:]),
                    max_pending=2 * workers,
                )
                for completed, (index, check) in enumerate(checks, start=1):
                    if not check["ok"]:
                        raise ValueError(f"n={current_n}, index={index}: rank {check['rank']} < {check['target_rank']}")
                    if completed % 1_000 == 0:
                        print(
                            f"n={current_n}{label}: checked {completed + 1:,}/{selected_count:,} {fixed_kind}",
                            flush=True,
                        )
        else:
            for index in selected:
                check = check_row(fixed_rows[index])
                if not check["ok"]:
                    raise ValueError(f"n={current_n}, index={index}: rank {check['rank']} < {check['target_rank']}")
        yield f"n={current_n}{label}: {selected_count} ok"


def check_stored_facets(
    root: str | Path | None = None,
    *,
    n: int | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
) -> Iterator[str]:
    yield from _check_stored_rank(
        root,
        "facets",
        "rays",
        n=n,
        shard_index=shard_index,
        shard_count=shard_count,
    )


def check_stored_rays(
    root: str | Path | None = None,
    *,
    n: int | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
) -> Iterator[str]:
    yield from _check_stored_rank(
        root,
        "rays",
        "facets",
        n=n,
        shard_index=shard_index,
        shard_count=shard_count,
    )


def check_stored_contractions(root=None, *, n=None, shard_index=0, shard_count=1):
    from .reconstruction_checks import check_stored_contractions as check

    yield from check(root, n=n, shard_index=shard_index, shard_count=shard_count)


def _check_facet_structure(current_n, facets):
    """Facet-list structure only; neither contraction nor rank acceptance."""
    lift_counts = {1: 0, 2: 1, 3: 1, 4: 2, 5: 3, 6: 11}
    lift_count = lift_counts.get(current_n, 0)
    if lift_count > len(facets):
        raise ValueError(f"n={current_n}: lift count {lift_count} exceeds facet count {len(facets)}")
    for index, row in enumerate(facets):
        if not _is_primitive_row(row):
            raise ValueError(f"n={current_n}, index={index}: facet is not primitive")
    workers = check_worker_count()
    if workers > 1 and len(facets) >= 32:
        keys: list[tuple[int, ...]] = [()] * len(facets)
        chunk_size = max(1, math.ceil(len(facets) / (workers * 8)))
        chunks = (
            (offset, facets[offset : offset + chunk_size], current_n) for offset in range(0, len(facets), chunk_size)
        )
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for offset, chunk_keys in _bounded_parallel_map(
                pool,
                _facet_orbit_keys_chunk,
                chunks,
                max_pending=2 * workers,
            ):
                keys[offset : offset + len(chunk_keys)] = chunk_keys
    else:
        keys = [_facet_orbit_key(row, current_n) for row in facets]
    if len(keys) != len(set(keys)):
        raise ValueError(f"n={current_n}: duplicate facet symmetry orbit")
    expected = sorted(facets[:lift_count]) + sorted(facets[lift_count:])
    if facets != expected:
        raise ValueError(f"n={current_n}: facets are not ordered lifts-first, then row-lexicographically")


def check_stored_facet_database_format(root=None, *, n=None, shard_index=0, shard_count=1):
    from .reconstruction_checks import check_stored_facet_database_format as check

    yield from check(root, n=n, shard_index=shard_index, shard_count=shard_count)


def check_stored_database_bindings(root=None, *, n=None, shard_index=0, shard_count=1):
    from .reconstruction_checks import check_stored_database_bindings as check

    yield from check(root, n=n, shard_index=shard_index, shard_count=shard_count)


def _check_graph_pair(pair: tuple[int, tuple[int, ...], dict, int]) -> tuple[int, str | None]:
    """Validate one graph/ray pair in a process-safe worker."""

    index, ray, graph, n = pair
    if graph != canonical_primitive_ray_graph(graph, n):
        return index, "graph is not in canonical stored form"
    if not check_graph(graph, ray, n, match="ray")["ok"]:
        return index, "graph/ray mismatch"
    return index, None


def check_stored_graphs(
    root: str | Path | None = None,
    *,
    n: int | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
) -> Iterator[str]:
    for current_n in _selected_ns(root, n):
        rays = load_hec_data(current_n, "rays", root=root)
        graphs = load_json(data_path(current_n, "graphs", root=root))
        if not isinstance(graphs, list):
            raise ValueError(f"expected a list of graphs in {data_path(current_n, 'graphs', root=root)}")
        if len(rays) != len(graphs):
            raise ValueError(f"n={current_n}: {len(rays)} rays but {len(graphs)} graphs")
        selected = _shard_indices(len(rays), shard_index, shard_count)
        selected_count = len(selected)
        label = _shard_label(shard_index, shard_count)
        pairs = ((index, tuple(rays[index]), graphs[index], current_n) for index in selected)
        workers = check_worker_count()
        print(f"n={current_n}{label}: validating {selected_count:,} graphs with {workers} workers", flush=True)
        if workers > 1 and selected_count >= 32:
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
        yield f"n={current_n}{label}: {selected_count} ok"


if __name__ == "__main__":
    raise SystemExit("Use 'hec check' or 'python -m hec check' to run repository checks.")
