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

from ._graph_validation import canonical_primitive_ray_graph, exact_entropy_vector_mincut
from .coordinates import infer_n
from .serialization import load_json_records, save_json_records

Graph = dict[str, Any]
MatchMode = Literal["ray", "exact"]


def normalize_graph(graph: Graph | tuple[Sequence[Sequence[str]], Sequence[object]]) -> Graph:
    """Return one repository-format graph with validated labels and weights."""

    if isinstance(graph, dict):
        edges = graph.get("edges", [])
        weights = graph.get("weights", [])
    else:
        edges, weights = graph
    if not isinstance(edges, (list, tuple)) or not isinstance(weights, (list, tuple)):
        raise ValueError("graph records must contain list-valued edges and weights")
    if len(edges) != len(weights):
        raise ValueError(f"edge/weight mismatch: {len(edges)} vs {len(weights)}")

    clean_edges: list[list[str]] = []
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            raise ValueError(f"invalid graph edge {edge!r}")
        left, right = str(edge[0]), str(edge[1])
        if not left or not right or left == right:
            raise ValueError(f"invalid graph edge {edge!r}")
        clean_edges.append([left, right])
    return {
        "edges": clean_edges,
        "weights": [_clean_number(weight) for weight in weights],
    }


def _clean_number(value: object) -> int | float | str:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("graph weights cannot be booleans")
    if isinstance(value, (int, np.integer)):
        number = Fraction(int(value))
        original_float = False
    elif isinstance(value, (float, np.floating)):
        raw = float(value)
        if not math.isfinite(raw):
            raise ValueError("graph weights must be finite and non-negative")
        number = Fraction(str(raw))
        original_float = True
    else:
        try:
            number = Fraction(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"invalid graph weight {value!r}") from exc
        original_float = False
    if number < 0:
        raise ValueError("graph weights must be finite and non-negative")
    if number.denominator == 1:
        return int(number)
    return float(number) if original_float else str(number)


def entropy_vector(
    graph: Graph | tuple[Sequence[Sequence[str]], Sequence[object]],
    n: int,
) -> np.ndarray:
    """Compute the graph entropy vector using exact rational minimum cuts."""

    return np.asarray([float(value) for value in exact_entropy_vector_mincut(graph, n)], dtype=np.float64)


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


def _encode_exact(value: Fraction) -> int | str:
    return int(value) if value.denominator == 1 else str(value)


def _finite_float_or_exact(value: Fraction) -> float | str:
    try:
        encoded = float(value)
    except OverflowError:
        return str(value)
    return encoded if math.isfinite(encoded) else str(value)


def check_graph(
    graph: Graph | tuple[Sequence[Sequence[str]], Sequence[object]],
    v: Sequence[int | float],
    n: int | None = None,
    *,
    tol: float = 1e-7,
    primitive: bool = False,
) -> dict[str, Any]:
    """Verify a graph independently with exact rational minimum cuts.

    primitive=True checks exact positive proportionality and is the legacy name
    for ray matching. In normalized mode, ``tol`` retains the historical public
    checker behavior while all finder incumbents are accepted with ``tol=0``.
    """

    if n is None:
        n = infer_n(len(v))
    target = _exact_target(v, n)
    entropy = exact_entropy_vector_mincut(graph, n)
    if primitive:
        max_error: float | None = None
        if any(target):
            pivot = next(index for index, value in enumerate(target) if value != 0)
            scale = entropy[pivot] / target[pivot] if entropy[pivot] != 0 else Fraction(0)
            ok = scale > 0 and all(
                observed == scale * expected for observed, expected in zip(entropy, target, strict=True)
            )
        else:
            ok = not any(entropy)
    else:
        if isinstance(tol, bool) or not isinstance(tol, Real) or not math.isfinite(tol) or tol < 0:
            raise ValueError("tol must be a finite non-negative number")
        errors = [abs(observed - expected) for observed, expected in zip(entropy, target, strict=True)]
        exact_error = max(errors, default=Fraction(0))
        max_error = _finite_float_or_exact(exact_error)
        ok = exact_error <= Fraction(str(float(tol)))
    return {
        "ok": bool(ok),
        "n": n,
        "max_error": max_error,
        "entropy": [_encode_exact(value) for value in entropy],
        "target": [_encode_exact(value) for value in target],
        "verification": "exact_rational_mincut",
    }


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
        return canonical_primitive_ray_graph(graph)
    observed = exact_entropy_vector_mincut(graph, n)
    exact_target = tuple(Fraction(int(value)) for value in target)
    if not any(exact_target):
        if any(observed):
            raise ValueError("solver candidate is not the exact zero vector")
        return normalize_graph(graph)
    pivot = next(index for index, value in enumerate(exact_target) if value != 0)
    if observed[pivot] == 0:
        raise ValueError("solver candidate is not proportional to the target")
    factor = exact_target[pivot] / observed[pivot]
    if factor <= 0 or any(factor * value != expected for value, expected in zip(observed, exact_target, strict=True)):
        raise ValueError("solver candidate is not proportional to the target")
    scaled_weights: list[int | str] = []
    for weight in normalize_graph(graph)["weights"]:
        scaled = Fraction(weight) * factor
        scaled_weights.append(int(scaled) if scaled.denominator == 1 else str(scaled))
    return normalize_graph({"edges": graph["edges"], "weights": scaled_weights})


def _search_result(
    *,
    graph: Graph | None,
    info: dict[str, Any],
    n: int,
    target: np.ndarray,
    match: MatchMode,
    verify: bool,
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
        check = check_graph(graph, target.tolist(), n, tol=0.0, primitive=match == "ray")
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
        "verification": {"method": "exact_rational_mincut", "ok": True},
        "elapsed_s": round(time.perf_counter() - started, 6),
    }
    if total_vertices is not None:
        result["total_vertices"] = total_vertices
    if verify:
        result["check"] = check
    return result


def find_graph_fixed_n(
    v: Sequence[int | float],
    total_vertices: int,
    *,
    match: MatchMode = "ray",
    verify: bool = False,
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
        verify=verify,
        started=started,
        total_vertices=total_vertices,
    )


def find_graph(
    v: Sequence[int | float],
    *,
    max_vertices: int | None = None,
    match: MatchMode = "ray",
    verify: bool = False,
    workers: int = 1,
    node_limit: int | None = None,
    time_limit_s: float | None = None,
) -> dict[str, Any]:
    """Find a graph realization by searching successively larger vertex counts.

    If max_vertices is omitted, the compatibility policy retains the historical
    ceiling of 12 total vertices (while always permitting the terminal-only
    model). Pass an explicit larger bound, or call find_graph_fixed_n, for rays
    known to require more. Search stops at the first resource-limited or
    otherwise unknown fixed-N result; it never treats an unknown as an
    infeasibility proof.
    """

    started = time.perf_counter()
    n, target = _validated_integer_target(v)
    if match not in ("ray", "exact"):
        raise ValueError("match must be 'ray' or 'exact'")
    _validate_limits(workers=workers, node_limit=node_limit, time_limit_s=time_limit_s)
    if max_vertices is None:
        max_vertices = max(n + 1, min(2 * n + 1, 12))
    if isinstance(max_vertices, bool) or not isinstance(max_vertices, int) or max_vertices < n + 1:
        raise ValueError(f"max_vertices must be an integer at least {n + 1}")

    from ._graph_search import solve_fixed_n

    all_smaller_infeasible = False
    last_info: dict[str, Any] = {}
    for total_vertices in range(n + 1, max_vertices + 1):
        graph, info = solve_fixed_n(
            target.tolist(),
            n,
            total_vertices,
            assume_no_smaller=all_smaller_infeasible,
            node_limit=node_limit,
            time_limit_s=time_limit_s,
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
                verify=verify,
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
                verify=verify,
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
        verify=verify,
        started=started,
        total_vertices=None,
    )
