"""Graph realization and graph-ray discovery for HEC vectors."""

from __future__ import annotations

import math
import time
import warnings
from collections.abc import Iterable, Sequence
from fractions import Fraction
from functools import cache
from itertools import combinations
from math import gcd, lcm
from pathlib import Path
from typing import Any

import numpy as np

from .coordinates import infer_n, party_labels, primitive_vector, row_to_array, subset_index_map, subsets
from .serialization import load_json_records, save_json_records

Graph = dict[str, Any]
SCIPY_LP_OPTIONS: dict[str, bool] = {"disp": False, "presolve": True}
SCIPY_MILP_OPTIONS: dict[str, bool | int | float] = {
    "disp": False,
    "presolve": True,
    "mip_abs_gap": 1e9,
    "mip_rel_gap": 1.0,
}


def normalize_graph(graph: Graph | tuple[Sequence[Sequence[str]], Sequence[int | float]]) -> Graph:
    if isinstance(graph, dict):
        edges = graph.get("edges", [])
        weights = graph.get("weights", [])
    else:
        edges, weights = graph
    if not isinstance(edges, list | tuple) or not isinstance(weights, list | tuple):
        raise ValueError("graph records must contain list-valued edges and weights")
    if len(edges) != len(weights):
        raise ValueError(f"edge/weight mismatch: {len(edges)} vs {len(weights)}")
    clean_edges = []
    for edge in edges:
        if not isinstance(edge, list | tuple) or len(edge) != 2:
            raise ValueError(f"invalid graph edge {edge!r}")
        clean_edges.append([str(edge[0]), str(edge[1])])
    return {
        "edges": clean_edges,
        "weights": [_clean_number(weight) for weight in weights],
    }


def _clean_number(value: int | float) -> int | float:
    if isinstance(value, bool):
        raise ValueError("graph weights cannot be booleans")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("graph weights must be finite and non-negative")
    return int(value) if value.is_integer() else value


def entropy_vector(graph: Graph | tuple[Sequence[Sequence[str]], Sequence[float]], n: int) -> np.ndarray:
    """Compute the graph min-cut entropy vector by enumerating bulk cuts."""
    g = normalize_graph(graph)
    labels = party_labels(n)
    parties = labels[:n]
    terminals = set(labels)
    graph_vertices = {vertex for edge in g["edges"] for vertex in edge}
    bulk = sorted(graph_vertices - terminals)
    if n + len(bulk) + 1 > 63:
        raise ValueError("graph verification supports at most 63 vertices")
    vertex_index = {party: index for index, party in enumerate(parties)}
    vertex_index.update({vertex: n + offset for offset, vertex in enumerate(bulk)})
    vertex_index[labels[-1]] = n + len(bulk)
    left_bits = np.asarray([1 << vertex_index[str(edge[0])] for edge in g["edges"]], dtype=np.uint64)
    right_bits = np.asarray([1 << vertex_index[str(edge[1])] for edge in g["edges"]], dtype=np.uint64)
    weights = np.asarray(g["weights"], dtype=np.float64)
    inside = _inside_masks(n, len(bulk)).reshape(-1)
    crosses = ((inside[:, None] & left_bits[None, :]) != 0) ^ ((inside[:, None] & right_bits[None, :]) != 0)
    values = crosses.astype(np.float64, copy=False) @ weights
    return values.reshape(len(subsets(n)), 1 << len(bulk)).min(axis=1)


@cache
def _inside_masks(n: int, bulk_count: int) -> np.ndarray:
    rows = []
    for sub in subsets(n):
        boundary = 0
        for party in sub:
            boundary |= 1 << party
        rows.append([boundary | (bulk_mask << n) for bulk_mask in range(1 << bulk_count)])
    return np.asarray(rows, dtype=np.uint64)


def check_graph(
    graph: Graph | tuple[Sequence[Sequence[str]], Sequence[float]],
    v: Sequence[int | float],
    n: int | None = None,
    *,
    tol: float = 1e-7,
    primitive: bool = False,
) -> dict:
    if n is None:
        n = infer_n(len(v))
    target = row_to_array(v, n, dtype=np.float64)
    ent = entropy_vector(graph, n)
    if primitive:
        ok = primitive_vector(ent) == primitive_vector(target)
        max_error = float("nan")
    else:
        max_error = float(np.max(np.abs(ent - target))) if ent.size else 0.0
        ok = max_error <= tol
    return {
        "ok": bool(ok),
        "n": n,
        "max_error": max_error,
        "entropy": ent.tolist(),
        "target": target.tolist(),
    }


def read_graphs(path: str | Path) -> list[Graph]:
    return load_json_records(path, "graph", normalize_graph)


def write_graphs(path: str | Path, graphs: Iterable[Graph]) -> None:
    save_json_records(path, (normalize_graph(graph) for graph in graphs))


def _boundary_subset_for_terminals(n: int, terminals: set[int] | frozenset[int]) -> frozenset[int]:
    boundary = {vertex for vertex in terminals if vertex < n}
    return frozenset(set(range(n)) - boundary if n in terminals else boundary)


def _terminal_entropy(target: np.ndarray, n: int, terminals: set[int] | frozenset[int]) -> float:
    boundary = _boundary_subset_for_terminals(n, terminals)
    return 0.0 if not boundary else float(target[subset_index_map(n)[boundary]])


def _crossing_edges(edges: Sequence[tuple[int, int]], inside: set[int]) -> list[int]:
    return [index for index, (a, b) in enumerate(edges) if (a in inside) != (b in inside)]


def _terminal_edge_weight(target: np.ndarray, n: int, left: int, right: int) -> float:
    return (
        _terminal_entropy(target, n, {left})
        + _terminal_entropy(target, n, {right})
        - _terminal_entropy(target, n, {left, right})
    ) / 2.0


def _edge_bounds(edges: Sequence[tuple[int, int]], target: np.ndarray, n: int, N: int) -> tuple[np.ndarray, np.ndarray]:
    lb = np.zeros(len(edges), dtype=np.float64)
    ub = np.ones(len(edges), dtype=np.float64)
    terminal_edges = {
        (left, right): max(0.0, _terminal_edge_weight(target, n, left, right))
        for left in range(n + 1)
        for right in range(left + 1, n + 1)
    }
    residual = [
        max(
            0.0,
            _terminal_entropy(target, n, {terminal})
            - sum(weight for edge, weight in terminal_edges.items() if terminal in edge),
        )
        for terminal in range(n + 1)
    ]
    for edge_index, (a, b) in enumerate(edges):
        terminal_a = a if a < n else n if a == N - 1 else None
        terminal_b = b if b < n else n if b == N - 1 else None
        if terminal_a is not None and terminal_b is not None:
            weight = terminal_edges[tuple(sorted((terminal_a, terminal_b)))]
            lb[edge_index] = weight
            ub[edge_index] = weight
        elif terminal_a is not None:
            ub[edge_index] = min(ub[edge_index], residual[terminal_a])
        elif terminal_b is not None:
            ub[edge_index] = min(ub[edge_index], residual[terminal_b])
    return lb, ub


def _integer_graph(
    raw_edges: Sequence[list[str]],
    raw_weights: Sequence[float],
    *,
    max_denominator: int = 1_000_000,
    tol: float = 1e-9,
    snap_tol: float = 1e-5,
) -> tuple[Graph, int]:
    fractions: list[Fraction] = []
    edges: list[list[str]] = []
    for edge, weight in zip(raw_edges, raw_weights, strict=True):
        if weight <= tol:
            continue
        nearest_integer = round(weight)
        if abs(weight - nearest_integer) <= snap_tol:
            fractions.append(Fraction(int(nearest_integer), 1))
        else:
            fractions.append(Fraction(float(weight)).limit_denominator(max_denominator))
        edges.append([str(edge[0]), str(edge[1])])
    if not fractions:
        return {"edges": [], "weights": []}, 1

    denominator = 1
    for weight in fractions:
        denominator = lcm(denominator, weight.denominator)
    integers = [int(weight * denominator) for weight in fractions]
    factor = 0
    for weight in integers:
        factor = gcd(factor, abs(weight))
    if factor > 1:
        denominator //= factor
        integers = [weight // factor for weight in integers]
    return {"edges": edges, "weights": integers}, denominator


def _solve_scipy_milp(
    c: np.ndarray,
    A_ineq: np.ndarray,
    b_ineq_lo: np.ndarray,
    b_ineq_hi: np.ndarray,
    A_eq: np.ndarray,
    b_eq: np.ndarray,
    integrality: np.ndarray,
    lb: np.ndarray,
    ub: np.ndarray,
) -> np.ndarray | None:
    from scipy import sparse
    from scipy.optimize import Bounds, LinearConstraint, milp

    A = sparse.vstack([A_ineq, A_eq], format="csr").astype(np.float64, copy=False)
    row_lower = np.concatenate([b_ineq_lo, b_eq]).astype(np.float64)
    row_upper = np.concatenate([b_ineq_hi, b_eq]).astype(np.float64)
    lower = np.asarray(lb, dtype=np.float64)
    upper = np.asarray(ub, dtype=np.float64)
    integrality = np.asarray(integrality, dtype=np.int32)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = milp(
            c=np.asarray(c, dtype=np.float64),
            integrality=integrality,
            bounds=Bounds(lower, upper),
            constraints=LinearConstraint(A, row_lower, row_upper),
            options=dict(SCIPY_MILP_OPTIONS),
        )
    if result.x is None:
        return None
    solution = np.asarray(result.x, dtype=np.float64)
    if result.success or _satisfies_linear_model(solution, A, row_lower, row_upper, lower, upper, integrality):
        return solution
    return None


def _satisfies_linear_model(
    solution: np.ndarray,
    matrix: np.ndarray,
    row_lower: np.ndarray,
    row_upper: np.ndarray,
    col_lower: np.ndarray,
    col_upper: np.ndarray,
    integrality: np.ndarray,
    *,
    tol: float = 1e-6,
) -> bool:
    if solution.shape != col_lower.shape or not np.all(np.isfinite(solution)):
        return False
    if np.any(solution < col_lower - tol) or np.any(solution > col_upper + tol):
        return False
    row_values = matrix @ solution
    if np.any(row_values < row_lower - tol) or np.any(row_values > row_upper + tol):
        return False
    integer_cols = integrality != 0
    if np.any(np.abs(solution[integer_cols] - np.rint(solution[integer_cols])) > tol):
        return False
    return True


def _solve_lp_relaxation(
    A_ineq: np.ndarray,
    b_ineq_hi: np.ndarray,
    A_eq: np.ndarray,
    b_eq: np.ndarray,
    lb: np.ndarray,
    ub: np.ndarray,
) -> str:
    from scipy.optimize import linprog

    result = linprog(
        c=np.zeros(lb.shape[0], dtype=np.float64),
        A_ub=A_ineq if A_ineq.shape[0] else None,
        b_ub=np.asarray(b_ineq_hi, dtype=np.float64) if A_ineq.shape[0] else None,
        A_eq=A_eq if A_eq.shape[0] else None,
        b_eq=np.asarray(b_eq, dtype=np.float64) if A_eq.shape[0] else None,
        bounds=list(zip(np.asarray(lb, dtype=np.float64), np.asarray(ub, dtype=np.float64), strict=True)),
        method="highs",
        options=SCIPY_LP_OPTIONS,
    )
    if result.success:
        return "feasible"
    if result.status == 2:
        return "infeasible"
    return "unknown"


@cache
def _ahc_structure(
    n: int,
    N: int,
) -> tuple[
    tuple[tuple[int, int], ...],
    tuple[frozenset[int], ...],
    frozenset[int],
    tuple[tuple[np.ndarray, ...], ...],
]:
    edges = tuple(combinations(range(N), 2))
    terminals = range(n + 1)
    fixed_subsystems = tuple(frozenset([terminal]) for terminal in terminals) + tuple(
        frozenset(pair) for pair in combinations(terminals, 2)
    )
    fixed_sub_indices = frozenset(
        subset_index_map(n)[boundary]
        for terminals in fixed_subsystems
        if (boundary := _boundary_subset_for_terminals(n, terminals))
    )
    bulk = list(range(n, N - 1))
    cuts_by_sub: list[tuple[np.ndarray, ...]] = []
    for sub in subsets(n):
        cuts = []
        for mask in range(1 << len(bulk)):
            W = set(sub)
            for offset, vertex in enumerate(bulk):
                if (mask >> offset) & 1:
                    W.add(vertex)
            cuts.append(np.asarray(_crossing_edges(edges, W), dtype=np.int32))
        cuts_by_sub.append(tuple(cuts))
    return edges, fixed_subsystems, fixed_sub_indices, tuple(cuts_by_sub)


def find_graph(
    v: Sequence[int | float],
    *,
    max_vertices: int | None = None,
    verify: bool = False,
) -> dict:
    """Find a weighted graph realizing an entropy vector by AHC MILP."""
    start = time.perf_counter()
    n = infer_n(len(v))
    raw = row_to_array(v, n, dtype=np.float64)
    target = np.rint(raw)
    if not np.allclose(raw, target, atol=1e-9, rtol=0.0):
        raise ValueError("graph entropy vectors must be integer-valued")
    target = target.astype(np.int64)
    graph, info = _find_graph_ahc(
        target,
        n,
        max_vertices=max_vertices,
    )
    if graph is None:
        return {
            "status": "unknown",
            "algorithm": "ahc_milp",
            "n": n,
            "reason": info,
            "elapsed_s": round(time.perf_counter() - start, 6),
        }
    result = {
        "status": "realized",
        "algorithm": "ahc_milp",
        "n": n,
        "graph": graph,
        "ahc": info,
        "elapsed_s": round(time.perf_counter() - start, 6),
    }
    if verify:
        result["check"] = check_graph(graph, target, n, primitive=True)
    return result


def _find_graph_ahc(
    target: np.ndarray,
    n: int,
    *,
    max_vertices: int | None,
) -> tuple[Graph | None, dict]:
    if max_vertices is None:
        max_vertices = min(2 * n + 1, 12)
    for total_vertices in range(n + 1, max_vertices + 1):
        graph, info = _solve_ahc_for_N(
            target,
            n,
            total_vertices,
        )
        if graph is not None:
            return graph, {**info, "N": total_vertices}
        if info["status"] != "infeasible":
            return None, {**info, "last_N": total_vertices}
    return None, {"status": "infeasible_or_unknown", "max_vertices": max_vertices}


def _solve_ahc_for_N(
    target: np.ndarray,
    n: int,
    N: int,
) -> tuple[Graph | None, dict]:
    profile_start = time.perf_counter()
    if not np.all(np.isfinite(target)) or np.min(target) < 0:
        return None, {"status": "invalid_target"}

    edges, fixed_subsystems, fixed_sub_indices, cuts_by_sub = _ahc_structure(n, N)
    edge_count = len(edges)

    max_target = float(np.max(np.abs(target))) if target.size else 0.0
    scale = 1.0 / max_target if max_target > 0 else 1.0
    scaled = target * scale
    edge_lb, edge_ub = _edge_bounds(edges, scaled, n, N)

    tol = 1e-9
    cut_bounds: list[tuple[tuple[float, float], ...]] = []
    choices_by_sub: dict[int, tuple[int, ...]] = {}
    lower_row_count = 0
    for sub_index, cuts in enumerate(cuts_by_sub):
        value = float(scaled[sub_index])
        bounds: list[tuple[float, float]] = []
        auto_realized = False
        choices: list[int] = []
        for cut_index, crossing in enumerate(cuts):
            lower = float(np.sum(edge_lb[crossing])) if len(crossing) else 0.0
            upper = float(np.sum(edge_ub[crossing])) if len(crossing) else 0.0
            if upper < value - tol:
                return None, {"status": "infeasible"}
            if lower < value - tol:
                lower_row_count += 1
            if sub_index not in fixed_sub_indices:
                if upper <= value + tol:
                    auto_realized = True
                elif lower <= value + tol:
                    choices.append(cut_index)
            bounds.append((lower, upper))
        cut_bounds.append(tuple(bounds))
        if sub_index not in fixed_sub_indices and not auto_realized:
            if not choices:
                return None, {"status": "infeasible"}
            choices_by_sub[sub_index] = tuple(choices)

    choice_index: dict[tuple[int, int], int] = {}
    next_index = edge_count
    for sub_index, choices in choices_by_sub.items():
        for cut_index in choices:
            choice_index[(sub_index, cut_index)] = next_index
            next_index += 1
    var_count = next_index
    integrality = np.zeros(var_count, dtype=int)
    integrality[edge_count:] = 1
    lb = np.zeros(var_count)
    ub = np.ones(var_count)
    lb[:edge_count] = edge_lb
    ub[:edge_count] = edge_ub

    n_ineq = lower_row_count + sum(len(choices) for choices in choices_by_sub.values())
    ineq_rows: list[int] = []
    ineq_cols: list[int] = []
    ineq_data: list[float] = []
    b_ineq_hi = np.zeros(n_ineq, dtype=np.float64)
    b_ineq_lo = -np.inf * np.ones(n_ineq, dtype=np.float64)
    choice_sub_count = len(choices_by_sub)
    n_eq = choice_sub_count + len(fixed_subsystems)
    eq_rows: list[int] = []
    eq_cols: list[int] = []
    eq_data: list[float] = []
    b_eq = np.zeros(choice_sub_count + len(fixed_subsystems), dtype=np.float64)
    row = 0
    eq_row = 0
    for sub_index, cuts in enumerate(cuts_by_sub):
        value = float(scaled[sub_index])
        for cut_index, crossing in enumerate(cuts):
            lower, upper = cut_bounds[sub_index][cut_index]
            if lower < value - tol:
                for edge in crossing:
                    ineq_rows.append(row)
                    ineq_cols.append(int(edge))
                    ineq_data.append(-1.0)
                b_ineq_hi[row] = -value
                row += 1
            choice_var = choice_index.get((sub_index, cut_index))
            if choice_var is not None:
                big_m = upper - value
                for edge in crossing:
                    ineq_rows.append(row)
                    ineq_cols.append(int(edge))
                    ineq_data.append(1.0)
                if big_m != 0.0:
                    ineq_rows.append(row)
                    ineq_cols.append(choice_var)
                    ineq_data.append(big_m)
                b_ineq_hi[row] = value + big_m
                row += 1
        choices = choices_by_sub.get(sub_index)
        if choices is not None:
            for cut_index in choices:
                eq_rows.append(eq_row)
                eq_cols.append(choice_index[(sub_index, cut_index)])
                eq_data.append(1.0)
            b_eq[eq_row] = 1.0
            eq_row += 1

    for terminals in fixed_subsystems:
        inside = {N - 1 if terminal == n else terminal for terminal in terminals}
        for edge in _crossing_edges(edges, inside):
            eq_rows.append(eq_row)
            eq_cols.append(edge)
            eq_data.append(1.0)
        b_eq[eq_row] = _terminal_entropy(scaled, n, terminals)
        eq_row += 1

    from scipy import sparse

    A_ineq = sparse.csr_matrix((ineq_data, (ineq_rows, ineq_cols)), shape=(n_ineq, var_count), dtype=np.float64)
    A_eq = sparse.csr_matrix((eq_data, (eq_rows, eq_cols)), shape=(n_eq, var_count), dtype=np.float64)

    profile: dict[str, int | float] = {
        "edge_vars": edge_count,
        "binary_vars": var_count - edge_count,
        "vars": var_count,
        "ineq_rows": n_ineq,
        "eq_rows": n_eq,
        "nnz": int(A_ineq.nnz + A_eq.nnz),
        "build_s": time.perf_counter() - profile_start,
    }

    lp_start = time.perf_counter()
    relaxation_status = _solve_lp_relaxation(
        A_ineq,
        b_ineq_hi,
        A_eq,
        b_eq,
        lb,
        ub,
    )
    profile["lp_s"] = time.perf_counter() - lp_start
    if relaxation_status == "infeasible":
        return None, {"status": "infeasible", "solver": "lp_relaxation", "profile": profile}

    objective = np.zeros(var_count)
    objective[:edge_count] = -1.0
    milp_start = time.perf_counter()
    solution = _solve_scipy_milp(
        objective,
        A_ineq,
        b_ineq_lo,
        b_ineq_hi,
        A_eq,
        b_eq,
        integrality,
        lb,
        ub,
    )
    profile["milp_s"] = time.perf_counter() - milp_start
    if solution is None:
        return None, {"status": "infeasible", "solver": "milp", "profile": profile}

    labels = party_labels(n)
    raw_edges: list[list[str]] = []
    raw_weights: list[float] = []
    for edge_pos, (a, b) in enumerate(edges):
        weight = float(solution[edge_pos]) / scale
        if weight <= 1e-9:
            continue
        raw_edges.append([_vertex_label(a, n, N, labels), _vertex_label(b, n, N, labels)])
        raw_weights.append(weight)
    graph, weight_scale = _integer_graph(raw_edges, raw_weights)
    return graph, {"status": "realized", "weight_scale": weight_scale, "solver": "milp", "profile": profile}


def _vertex_label(vertex: int, n: int, N: int, labels: Sequence[str]) -> str:
    if vertex < n:
        return labels[vertex]
    if vertex == N - 1:
        return "O"
    return f"x{vertex - n + 1}"
