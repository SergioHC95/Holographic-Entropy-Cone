"""Public graph formats, exact verification, and graph-realization search."""

from __future__ import annotations

import math
import time
from collections.abc import Iterable, Sequence
from fractions import Fraction
from numbers import Real
from pathlib import Path
from typing import Any, Literal

import numpy as np

from ._graph_validation import (
    canonical_graph,
    canonical_primitive_ray_graph,
    exact_entropy_match,
    exact_entropy_vector_mincut,
    graph_total_vertices,
)
from .coordinates import infer_n
from .serialization import load_json_records, save_json_records

Graph = dict[str, Any]
MatchMode = Literal["ray", "exact"]


def normalize_graph(graph: Graph) -> Graph:
    """Return one canonical repository-format graph."""

    return canonical_graph(graph)


def _exact_target(v: Sequence[object], n: int) -> tuple[Fraction, ...]:
    expected = (1 << n) - 1
    if len(v) != expected:
        raise ValueError(f"expected target length {expected}, got {len(v)}")
    values: list[Fraction] = []
    for value in v:
        if isinstance(value, (bool, np.bool_)):
            raise ValueError("graph entropy vectors must contain finite numbers")
        if isinstance(value, (float, np.floating)):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("graph entropy vectors must contain finite numbers")
            values.append(Fraction(str(number)))
            continue
        try:
            values.append(Fraction(value))  # type: ignore[arg-type]
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise ValueError("graph entropy vectors must contain finite numbers") from exc
    return tuple(values)


def check_graph(
    graph: Graph,
    v: Sequence[object],
    n: int | None = None,
    *,
    match: MatchMode = "ray",
) -> dict[str, Any]:
    """Verify exact equality or positive proportionality to an entropy vector."""

    if n is None:
        n = infer_n(len(v))
    if match not in ("ray", "exact"):
        raise ValueError("match must be 'ray' or 'exact'")
    target = _exact_target(v, n)
    return {"n": n, **exact_entropy_match(graph, target, n, match)}


def read_graphs(path: str | Path) -> list[Graph]:
    return load_json_records(path, "graph", normalize_graph)


def write_graphs(path: str | Path, graphs: Iterable[Graph]) -> None:
    save_json_records(path, (normalize_graph(graph) for graph in graphs))


def _validated_integer_target(v: Sequence[int | float]) -> tuple[int, np.ndarray]:
    n = infer_n(len(v))
    exact = _exact_target(v, n)
    if any(value < 0 for value in exact):
        raise ValueError("graph entropy vectors must be non-negative")
    if any(value.denominator != 1 for value in exact):
        raise ValueError("graph entropy vectors must be integer-valued")
    try:
        target = np.asarray([int(value) for value in exact], dtype=np.int64)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("graph entropy vectors must fit signed 64-bit integers") from exc
    return n, target


def _validate_limits(
    *,
    workers: int,
    node_limit: int | None,
    time_limit_s: float | None,
) -> None:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
    if node_limit is not None and (isinstance(node_limit, bool) or not isinstance(node_limit, int) or node_limit < 1):
        raise ValueError("node_limit must be a positive integer")
    if time_limit_s is not None and (
        isinstance(time_limit_s, bool)
        or not isinstance(time_limit_s, Real)
        or not math.isfinite(time_limit_s)
        or time_limit_s <= 0
    ):
        raise ValueError("time_limit_s must be a positive finite number")


def _scale_graph_for_match(graph: Graph, target: np.ndarray, n: int, match: MatchMode) -> Graph:
    if match == "ray":
        return canonical_primitive_ray_graph(graph, n)
    observed = exact_entropy_vector_mincut(graph, n)
    exact_target = tuple(Fraction(int(value)) for value in target)
    if not any(exact_target):
        if any(observed):
            raise ValueError("solver candidate is not the exact zero vector")
        return canonical_graph(graph, n)
    pivot = next(index for index, value in enumerate(exact_target) if value != 0)
    if observed[pivot] == 0:
        raise ValueError("solver candidate is not proportional to the target")
    factor = exact_target[pivot] / observed[pivot]
    if factor <= 0 or any(factor * value != expected for value, expected in zip(observed, exact_target, strict=True)):
        raise ValueError("solver candidate is not proportional to the target")
    normalized = canonical_graph(graph, n)
    scaled_weights: list[int | str] = []
    for weight in normalized["weights"]:
        scaled = Fraction(weight) * factor
        scaled_weights.append(int(scaled) if scaled.denominator == 1 else str(scaled))
    return canonical_graph({"edges": normalized["edges"], "weights": scaled_weights}, n)


def _search_result(
    *,
    graph: Graph | None,
    info: dict[str, Any],
    n: int,
    target: np.ndarray,
    match: MatchMode,
    started: float,
    total_vertices: int | None,
) -> dict[str, Any]:
    if graph is None:
        status = "infeasible" if info.get("status") == "infeasible" else "unknown"
        return {
            "status": status,
            "algorithm": "ahc_milp",
            "n": n,
            "reason": info,
            "elapsed_s": round(time.perf_counter() - started, 6),
        }

    try:
        graph = _scale_graph_for_match(graph, target, n, match)
        check = check_graph(graph, target.tolist(), n, match=match)
        if total_vertices is not None and graph_total_vertices(graph, n) != total_vertices:
            raise ValueError(f"candidate does not use exactly {total_vertices} active vertices")
    except (ArithmeticError, TypeError, ValueError) as exc:
        return {
            "status": "unknown",
            "algorithm": "ahc_milp",
            "n": n,
            "reason": {"status": "unknown", "reason": f"exact_candidate_validation_failed: {exc}"},
            "elapsed_s": round(time.perf_counter() - started, 6),
        }
    if not check["ok"]:
        return {
            "status": "unknown",
            "algorithm": "ahc_milp",
            "n": n,
            "reason": {"status": "unknown", "reason": "exact_candidate_validation_failed", "check": check},
            "elapsed_s": round(time.perf_counter() - started, 6),
        }

    result: dict[str, Any] = {
        "status": "realized",
        "algorithm": "ahc_milp",
        "n": n,
        "match": match,
        "graph": graph,
        "ahc": info,
        "check": check,
        "verification": {"method": "exact_rational_mincut", "ok": True},
        "elapsed_s": round(time.perf_counter() - started, 6),
    }
    if total_vertices is not None:
        result["total_vertices"] = total_vertices
    return result


def find_graph_fixed_n(
    v: Sequence[int | float],
    total_vertices: int,
    *,
    match: MatchMode = "ray",
    workers: int = 1,
    node_limit: int | None = None,
    time_limit_s: float | None = None,
) -> dict[str, Any]:
    """Search for a realization with exactly total_vertices active vertices.

    A realization using fewer active vertices may be lifted to the requested
    size by deterministic positive-edge subdivision, which preserves every
    terminal minimum cut. time_limit_s is shared across planning, model
    construction, portfolio attempts, and orbit representatives for this call.
    """

    started = time.perf_counter()
    n, target = _validated_integer_target(v)
    if match not in ("ray", "exact"):
        raise ValueError("match must be 'ray' or 'exact'")
    if isinstance(total_vertices, bool) or not isinstance(total_vertices, int) or total_vertices < n + 1:
        raise ValueError(f"total_vertices must be an integer at least {n + 1}")
    _validate_limits(workers=workers, node_limit=node_limit, time_limit_s=time_limit_s)

    from ._graph_search import solve_fixed_n

    graph, info = solve_fixed_n(
        target.tolist(),
        n,
        total_vertices,
        node_limit=node_limit,
        time_limit_s=time_limit_s,
        workers=workers,
    )
    return _search_result(
        graph=graph,
        info={**info, "N": total_vertices},
        n=n,
        target=target,
        match=match,
        started=started,
        total_vertices=total_vertices,
    )


def find_graph(
    v: Sequence[int | float],
    *,
    max_vertices: int,
    match: MatchMode = "ray",
    workers: int = 1,
    node_limit: int | None = None,
    time_limit_s: float | None = None,
) -> dict[str, Any]:
    """Find a graph realization by searching successively larger vertex counts.

    Search stops at the first resource-limited or otherwise unknown fixed-N
    result; it never treats an unknown as an infeasibility proof. ``time_limit_s``
    is a single deadline shared across all vertex counts.
    """

    started = time.perf_counter()
    n, target = _validated_integer_target(v)
    if match not in ("ray", "exact"):
        raise ValueError("match must be 'ray' or 'exact'")
    _validate_limits(workers=workers, node_limit=node_limit, time_limit_s=time_limit_s)
    if isinstance(max_vertices, bool) or not isinstance(max_vertices, int) or max_vertices < n + 1:
        raise ValueError(f"max_vertices must be an integer at least {n + 1}")

    from ._graph_search import solve_fixed_n

    all_smaller_infeasible = False
    last_info: dict[str, Any] = {}
    deadline = None if time_limit_s is None else started + float(time_limit_s)
    for total_vertices in range(n + 1, max_vertices + 1):
        remaining_s = None if deadline is None else deadline - time.perf_counter()
        if remaining_s is not None and remaining_s <= 0:
            return _search_result(
                graph=None,
                info={"status": "unknown", "reason": "search_time_limit_exhausted"},
                n=n,
                target=target,
                match=match,
                started=started,
                total_vertices=None,
            )
        graph, info = solve_fixed_n(
            target.tolist(),
            n,
            total_vertices,
            assume_no_smaller=all_smaller_infeasible,
            node_limit=node_limit,
            time_limit_s=remaining_s,
            workers=workers,
        )
        info = {**info, "N": total_vertices}
        if graph is not None:
            return _search_result(
                graph=graph,
                info=info,
                n=n,
                target=target,
                match=match,
                started=started,
                total_vertices=total_vertices,
            )
        if info.get("status") != "infeasible":
            return _search_result(
                graph=None,
                info=info,
                n=n,
                target=target,
                match=match,
                started=started,
                total_vertices=None,
            )
        all_smaller_infeasible = True
        last_info = info

    final_info = {
        "status": "infeasible",
        "reason": "all_fixed_n_models_infeasible_within_bound",
        "max_vertices": max_vertices,
        "last_fixed_n": last_info,
    }
    return _search_result(
        graph=None,
        info=final_info,
        n=n,
        target=target,
        match=match,
        started=started,
        total_vertices=None,
    )
