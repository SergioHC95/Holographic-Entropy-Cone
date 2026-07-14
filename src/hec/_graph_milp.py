"""Private AHC model builder and deterministic MILP backend portfolio."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from itertools import combinations
from math import gcd, lcm
from typing import Any

import numpy as np

from ._graph_reductions import EqualityCut, close_tight_submodularity
from ._graph_validation import (
    exact_entropy_vector_mincut,
    graph_total_vertices,
    lift_graph_total_vertices,
    prune_entropy_irrelevant_components,
)
from .coordinates import party_labels, subset_index_map, subsets

Graph = dict[str, Any]
HIGHSPY_MILP_OPTIONS: dict[str, bool | int | float | str] = {
    "disp": False,
    "presolve": True,
    "mip_abs_gap": 1e9,
    "mip_rel_gap": 1.0,
    "threads": 1,
    "random_seed": 0,
}
SCIP_INDICATOR_BACKEND = "scip-indicator"
HIGHSPY_BACKEND = "highspy"
DEFAULT_SCIP_SELECTOR_THRESHOLD = 512
DEFAULT_SCIP_PREPASS_S = 30.0
SCIP_INDICATOR_OPTIONS: dict[str, bool | int | float | str] = {
    "parallel/maxnthreads": 1,
    "randomization/randomseedshift": 0,
    "randomization/permutationseed": 0,
    "randomization/lpseed": 0,
}


@dataclass(frozen=True)
class _ExactAHCPreprocessing:
    """Cached exact data used only for logical model-building decisions.

    The optimizer still receives ordinary double-precision arrays.  Keeping the
    exact values beside them prevents a solver tolerance from deciding whether a
    cut exists, is automatically tight, or must be selected.
    """

    scaled_target: tuple[Fraction, ...]
    edge_lower: tuple[Fraction, ...]
    edge_upper: tuple[Fraction, ...]
    cut_bounds: tuple[tuple[tuple[Fraction, Fraction], ...], ...]
    choices_by_sub: tuple[tuple[int, tuple[int, ...]], ...]
    auto_selected_by_sub: tuple[tuple[int, int], ...]
    infeasible: bool = False


def _boundary_subset_for_terminals(n: int, terminals: set[int] | frozenset[int]) -> frozenset[int]:
    boundary = {vertex for vertex in terminals if vertex < n}
    return frozenset(set(range(n)) - boundary if n in terminals else boundary)


def _exact_number(value: object) -> Fraction:
    """Interpret one input number as an exact rational, including binary floats."""

    if isinstance(value, (bool, np.bool_)):
        raise TypeError("boolean target entries are not numeric entropies")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, (int, np.integer)):
        return Fraction(int(value), 1)
    try:
        numerator, denominator = value.as_integer_ratio()  # type: ignore[union-attr]
    except AttributeError:
        return Fraction(value)  # type: ignore[arg-type]
    return Fraction(int(numerator), int(denominator))


def _exact_target_values(target: Sequence[object] | np.ndarray, n: int) -> tuple[Fraction, ...]:
    array = np.asarray(target, dtype=object)
    expected = (1 << n) - 1
    if array.shape != (expected,):
        raise ValueError(f"expected target shape ({expected},), got {array.shape}")
    return tuple(_exact_number(value) for value in array.tolist())


def _exact_graph_check(
    graph: Graph,
    target: Sequence[Fraction],
    n: int,
    *,
    ray: bool,
) -> dict[str, Any]:
    """Independently verify a candidate with exact rational minimum cuts."""

    entropy = exact_entropy_vector_mincut(graph, n)
    if ray and any(target):
        pivot = next(index for index, value in enumerate(target) if value != 0)
        scale = entropy[pivot] / target[pivot] if entropy[pivot] != 0 else Fraction(0)
        ok = scale > 0 and all(observed == scale * expected for observed, expected in zip(entropy, target, strict=True))
    else:
        ok = tuple(entropy) == tuple(target)

    def encode(value: Fraction) -> int | str:
        return int(value) if value.denominator == 1 else str(value)

    return {
        "ok": bool(ok),
        "entropy": [encode(value) for value in entropy],
        "target": [encode(value) for value in target],
        "verification": "exact_rational_mincut",
    }


def _terminal_entropy_exact(
    target: Sequence[Fraction],
    n: int,
    terminals: set[int] | frozenset[int],
) -> Fraction:
    boundary = _boundary_subset_for_terminals(n, terminals)
    return Fraction(0) if not boundary else target[subset_index_map(n)[boundary]]


def _has_additive_union_decomposition_exact(
    target: Sequence[Fraction],
    n: int,
    terminals: frozenset[int],
) -> bool:
    pieces = [frozenset(piece) for size in range(1, len(terminals)) for piece in combinations(sorted(terminals), size)]
    value = _terminal_entropy_exact(target, n, terminals)
    return any(
        left | right == terminals
        and _terminal_entropy_exact(target, n, left) + _terminal_entropy_exact(target, n, right) == value
        for left in pieces
        for right in pieces
    )


def _deterministic_cut_stats() -> dict[str, int]:
    return {
        "deterministic_cut_relations": 0,
        "deterministic_fixed_subsystems": 0,
        "deterministic_physical_triples": 0,
        "deterministic_purifier_triples": 0,
        "deterministic_binary_fixes": 0,
    }


def _crossing_edges(edges: Sequence[tuple[int, int]], inside: set[int]) -> list[int]:
    return [index for index, (a, b) in enumerate(edges) if (a in inside) != (b in inside)]


def _edge_bounds_exact(
    edges: Sequence[tuple[int, int]],
    target: Sequence[Fraction],
    n: int,
    N: int,
) -> tuple[tuple[Fraction, ...], tuple[Fraction, ...]]:
    zero = Fraction(0)
    one = Fraction(1)
    terminal_edges = {
        (left, right): max(
            zero,
            (
                _terminal_entropy_exact(target, n, {left})
                + _terminal_entropy_exact(target, n, {right})
                - _terminal_entropy_exact(target, n, {left, right})
            )
            / 2,
        )
        for left in range(n + 1)
        for right in range(left + 1, n + 1)
    }
    residual = tuple(
        max(
            zero,
            _terminal_entropy_exact(target, n, {terminal})
            - sum((weight for edge, weight in terminal_edges.items() if terminal in edge), zero),
        )
        for terminal in range(n + 1)
    )
    lower: list[Fraction] = []
    upper: list[Fraction] = []
    for a, b in edges:
        terminal_a = a if a < n else n if a == N - 1 else None
        terminal_b = b if b < n else n if b == N - 1 else None
        edge_lower = zero
        edge_upper = one
        if terminal_a is not None and terminal_b is not None:
            edge_lower = edge_upper = terminal_edges[tuple(sorted((terminal_a, terminal_b)))]
        elif terminal_a is not None:
            edge_upper = min(edge_upper, residual[terminal_a])
        elif terminal_b is not None:
            edge_upper = min(edge_upper, residual[terminal_b])
        lower.append(edge_lower)
        upper.append(edge_upper)
    return tuple(lower), tuple(upper)


def _cut_bound_status(lower: Fraction, upper: Fraction, target: Fraction) -> str:
    """Classify one cut using exact order/equality only."""

    if upper < target:
        return "infeasible"
    if upper == target:
        return "automatic"
    if lower <= target:
        return "choice"
    return "unavailable"


@lru_cache(maxsize=4)
def _exact_ahc_preprocessing(
    n: int,
    N: int,
    target: tuple[Fraction, ...],
) -> _ExactAHCPreprocessing:
    """Build exact cut decisions with a small cache for same-target branches."""

    maximum = max(target, default=Fraction(0))
    scale = Fraction(1, 1) if maximum == 0 else 1 / maximum
    scaled_target = tuple(value * scale for value in target)
    edges, _fixed_subsystems, fixed_sub_indices, cuts_by_sub = _ahc_structure(n, N)
    edge_lower, edge_upper = _edge_bounds_exact(edges, scaled_target, n, N)

    cut_bounds: list[tuple[tuple[Fraction, Fraction], ...]] = []
    choices_by_sub: list[tuple[int, tuple[int, ...]]] = []
    auto_selected_by_sub: list[tuple[int, int]] = []
    infeasible = False
    zero = Fraction(0)
    for sub_index, cuts in enumerate(cuts_by_sub):
        value = scaled_target[sub_index]
        bounds: list[tuple[Fraction, Fraction]] = []
        choices: list[int] = []
        auto_selected: int | None = None
        for cut_index, crossing in enumerate(cuts):
            lower = sum((edge_lower[int(edge)] for edge in crossing), zero)
            upper = sum((edge_upper[int(edge)] for edge in crossing), zero)
            bounds.append((lower, upper))
            status = _cut_bound_status(lower, upper, value)
            if status == "infeasible":
                infeasible = True
            if sub_index not in fixed_sub_indices:
                if status == "automatic":
                    if auto_selected is None:
                        auto_selected = cut_index
                elif status == "choice":
                    choices.append(cut_index)
        cut_bounds.append(tuple(bounds))
        if sub_index in fixed_sub_indices:
            continue
        if auto_selected is not None:
            auto_selected_by_sub.append((sub_index, auto_selected))
        elif choices:
            choices_by_sub.append((sub_index, tuple(choices)))
        else:
            infeasible = True

    return _ExactAHCPreprocessing(
        scaled_target=scaled_target,
        edge_lower=edge_lower,
        edge_upper=edge_upper,
        cut_bounds=tuple(cut_bounds),
        choices_by_sub=tuple(choices_by_sub),
        auto_selected_by_sub=tuple(auto_selected_by_sub),
        infeasible=infeasible,
    )


def _deterministic_union_cut_fixes_exact(
    target: Sequence[Fraction],
    n: int,
    N: int,
    choices_by_sub: dict[int, tuple[int, ...]],
    cut_bounds: Sequence[Sequence[tuple[Fraction, Fraction]]],
    fixed_sub_indices: frozenset[int],
) -> tuple[
    dict[tuple[int, int], float],
    frozenset[tuple[int, int]],
    dict[str, int],
    bool,
]:
    bulk_count = max(0, N - n - 1)
    purifier_cut = (1 << bulk_count) - 1
    sub_index_by_boundary = subset_index_map(n)
    selected_by_sub: dict[int, int] = {}
    forced_upper_cuts: set[tuple[int, int]] = set()
    stats = _deterministic_cut_stats()

    for triple in combinations(range(n + 1), 3):
        terminals = frozenset(triple)
        if not _has_additive_union_decomposition_exact(target, n, terminals):
            continue
        boundary = _boundary_subset_for_terminals(n, terminals)
        if not boundary:
            continue
        sub_index = sub_index_by_boundary[boundary]
        if sub_index in fixed_sub_indices:
            continue

        selected_cut = purifier_cut if n in terminals else 0
        value = target[sub_index]
        lower, upper = cut_bounds[sub_index][selected_cut]
        if lower > value:
            return {}, frozenset(), stats, False

        stats["deterministic_cut_relations"] += 1
        if n in terminals:
            stats["deterministic_purifier_triples"] += 1
        else:
            stats["deterministic_physical_triples"] += 1
        forced_upper_cuts.add((sub_index, selected_cut))

        choices = choices_by_sub.get(sub_index)
        if choices is not None and selected_cut in choices and sub_index not in selected_by_sub:
            selected_by_sub[sub_index] = selected_cut

    fixed_choice_values: dict[tuple[int, int], float] = {}
    for sub_index, selected_cut in selected_by_sub.items():
        for cut_index in choices_by_sub[sub_index]:
            fixed_choice_values[(sub_index, cut_index)] = 1.0 if cut_index == selected_cut else 0.0

    stats["deterministic_fixed_subsystems"] = len(selected_by_sub)
    stats["deterministic_binary_fixes"] = len(fixed_choice_values)
    return fixed_choice_values, frozenset(forced_upper_cuts), stats, True


def _integer_graph(
    raw_edges: Sequence[list[str]],
    raw_weights: Sequence[float],
    *,
    max_denominator: int = 1_000_000,
    tol: float = 1e-9,
    snap_tol: float = 1e-5,
) -> tuple[Graph, int | str]:
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
        integers = [weight // factor for weight in integers]
    scale = Fraction(factor, denominator)
    weight_scale: int | str = int(scale) if scale.denominator == 1 else str(scale)
    return {"edges": edges, "weights": integers}, weight_scale


def _solve_highspy_milp(
    c: np.ndarray,
    A_ineq: np.ndarray,
    b_ineq_lo: np.ndarray,
    b_ineq_hi: np.ndarray,
    A_eq: np.ndarray,
    b_eq: np.ndarray,
    integrality: np.ndarray,
    lb: np.ndarray,
    ub: np.ndarray,
    *,
    node_limit: int | None = None,
    time_limit_s: float | None = None,
) -> tuple[np.ndarray | None, dict[str, Any]]:
    import highspy
    from scipy import sparse

    A = sparse.vstack([A_ineq, A_eq], format="csc").astype(np.float64, copy=False)
    row_lower = np.concatenate([b_ineq_lo, b_eq]).astype(np.float64)
    row_upper = np.concatenate([b_ineq_hi, b_eq]).astype(np.float64)
    lower = np.asarray(lb, dtype=np.float64)
    upper = np.asarray(ub, dtype=np.float64)
    integrality = np.asarray(integrality, dtype=np.int32)
    objective = np.asarray(c, dtype=np.float64)
    base_model_sha256 = _frozen_milp_sha256(
        objective,
        A,
        row_lower,
        row_upper,
        lower,
        upper,
        integrality,
    )

    model = highspy.HighsModel()
    lp = model.lp_
    lp.num_col_ = int(A.shape[1])
    lp.num_row_ = int(A.shape[0])
    lp.col_cost_ = objective
    lp.col_lower_ = lower
    lp.col_upper_ = upper
    lp.row_lower_ = row_lower
    lp.row_upper_ = row_upper
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.num_col_ = int(A.shape[1])
    lp.a_matrix_.num_row_ = int(A.shape[0])
    lp.a_matrix_.start_ = A.indptr.astype(np.int64, copy=False)
    lp.a_matrix_.index_ = A.indices.astype(np.int32, copy=False)
    lp.a_matrix_.value_ = A.data
    # AHC models use only SciPy integrality codes 0 (continuous) and 1
    # (integer); semi-continuous/semi-integer codes are intentionally absent.
    lp.integrality_ = [
        highspy.HighsVarType.kInteger if value else highspy.HighsVarType.kContinuous for value in integrality
    ]

    def solve(*, presolve: bool) -> tuple[Any, dict[str, Any]]:
        highs = highspy.Highs()
        version = (highs.versionMajor(), highs.versionMinor(), highs.versionPatch())
        if version < (1, 14, 0):
            raise RuntimeError(f"HiGHS >= 1.14.0 is required; found {highs.version()}")
        option_values: dict[str, bool | int | float | str] = {
            "output_flag": bool(HIGHSPY_MILP_OPTIONS["disp"]),
            "presolve": "on" if presolve else "off",
            "mip_abs_gap": float(HIGHSPY_MILP_OPTIONS["mip_abs_gap"]),
            "mip_rel_gap": float(HIGHSPY_MILP_OPTIONS["mip_rel_gap"]),
            "threads": int(HIGHSPY_MILP_OPTIONS["threads"]),
            "random_seed": int(HIGHSPY_MILP_OPTIONS["random_seed"]),
        }
        if node_limit is not None:
            option_values["mip_max_nodes"] = int(node_limit)
        if time_limit_s is not None:
            option_values["time_limit"] = float(time_limit_s)
        for name, value in option_values.items():
            status = highs.setOptionValue(name, value)
            if status != highspy.HighsStatus.kOk:
                raise RuntimeError(f"HiGHS rejected option {name}={value!r}: {status}")
        pass_status = highs.passModel(model)
        run_status = highs.run() if pass_status == highspy.HighsStatus.kOk else highspy.HighsStatus.kError
        model_status = highs.getModelStatus()
        solution = highs.getSolution()
        solver_info = highs.getInfo()
        attempt: dict[str, Any] = {
            "backend": "highspy",
            "base_model_sha256": base_model_sha256,
            "highs_githash": highs.githash(),
            "highs_version": highs.version(),
            "model_status_code": int(model_status),
            "model_status": highs.modelStatusToString(model_status),
            "pass_status_code": int(pass_status),
            "pass_status": str(pass_status),
            "run_status_code": int(run_status),
            "run_status": str(run_status),
            "presolve": presolve,
            "value_valid": bool(solution.value_valid),
        }
        if solver_info.valid:
            attempt["primal_solution_status"] = int(solver_info.primal_solution_status)
            mip_gap = float(solver_info.mip_gap)
            objective_value = float(solver_info.objective_function_value)
            if math.isfinite(mip_gap):
                attempt["mip_gap"] = mip_gap
            if int(solver_info.mip_node_count) >= 0:
                attempt["mip_node_count"] = int(solver_info.mip_node_count)
            if math.isfinite(objective_value):
                attempt["objective"] = objective_value
        return solution, attempt

    raw_solution, info = solve(presolve=bool(HIGHSPY_MILP_OPTIONS["presolve"]))
    error_statuses = {
        int(highspy.HighsModelStatus.kLoadError),
        int(highspy.HighsModelStatus.kModelError),
        int(highspy.HighsModelStatus.kPresolveError),
        int(highspy.HighsModelStatus.kSolveError),
        int(highspy.HighsModelStatus.kPostsolveError),
    }
    backend_error = (
        info["model_status_code"] in error_statuses
        or info["pass_status_code"] == int(highspy.HighsStatus.kError)
        or info["run_status_code"] == int(highspy.HighsStatus.kError)
    )
    if backend_error and bool(HIGHSPY_MILP_OPTIONS["presolve"]):
        first_attempt = info
        raw_solution, info = solve(presolve=False)
        info["retry_without_presolve"] = first_attempt

    solution = np.asarray(raw_solution.col_value, dtype=np.float64) if raw_solution.value_valid else None
    if solution is not None and _satisfies_linear_model(
        solution,
        A,
        row_lower,
        row_upper,
        lower,
        upper,
        integrality,
    ):
        info["success"] = True
        info["status"] = "realized"
        return solution, info
    info["success"] = False
    trustworthy_infeasibility = (
        info["model_status_code"] == int(highspy.HighsModelStatus.kInfeasible)
        and info["pass_status_code"] == int(highspy.HighsStatus.kOk)
        and info["run_status_code"] == int(highspy.HighsStatus.kOk)
        and not raw_solution.value_valid
    )
    info["status"] = "infeasible" if trustworthy_infeasibility else "unknown"
    return None, info


def _frozen_milp_sha256(
    objective: np.ndarray,
    matrix: Any,
    row_lower: np.ndarray,
    row_upper: np.ndarray,
    col_lower: np.ndarray,
    col_upper: np.ndarray,
    integrality: np.ndarray,
) -> str:
    """Hash the byte-exact one-hot model received by a solver backend."""

    frozen = matrix.tocsc(copy=True).astype(np.float64, copy=False)
    frozen.sort_indices()
    digest = hashlib.sha256()
    for label, values in (
        ("objective", objective),
        ("row_lower", row_lower),
        ("row_upper", row_upper),
        ("col_lower", col_lower),
        ("col_upper", col_upper),
        ("integrality", integrality),
        ("indptr", frozen.indptr),
        ("indices", frozen.indices),
        ("data", frozen.data),
    ):
        array = np.ascontiguousarray(values)
        digest.update(label.encode("ascii"))
        digest.update(array.dtype.str.encode("ascii"))
        digest.update(np.asarray(array.shape, dtype=np.int64).tobytes())
        digest.update(array.tobytes())
    return digest.hexdigest()


def _scip_indicator_replacement(
    matrix: Any,
    row_lower: np.ndarray,
    row_upper: np.ndarray,
    col_lower: np.ndarray,
    col_upper: np.ndarray,
    integrality: np.ndarray,
    row: int,
    *,
    tol: float = 1e-10,
) -> tuple[int, np.ndarray, np.ndarray, float, float] | None:
    """Recognize one big-M row whose indicator replacement is proven exact.

    For ``a*x + M*z <= U``, the replacement is ``z=1 -> a*x <= U-M``.
    It is equivalent, rather than merely stronger or weaker, only when the
    inactive inequality ``a*x <= U`` follows from the frozen column bounds.
    No model-builder convention is trusted for that implication.
    """

    lower = float(row_lower[row])
    upper = float(row_upper[row])
    if math.isfinite(lower) or not math.isfinite(upper):
        return None
    csr = matrix if getattr(matrix, "format", None) == "csr" else matrix.tocsr()
    start, stop = csr.indptr[row : row + 2]
    columns = np.asarray(csr.indices[start:stop], dtype=np.int32)
    coefficients = np.asarray(csr.data[start:stop], dtype=np.float64)
    binary_positions = np.flatnonzero(integrality[columns] != 0)
    if len(binary_positions) != 1:
        return None
    binary_position = int(binary_positions[0])
    indicator_column = int(columns[binary_position])
    big_m = float(coefficients[binary_position])
    if big_m <= tol or float(col_lower[indicator_column]) < -tol or float(col_upper[indicator_column]) > 1.0 + tol:
        return None
    keep = np.arange(len(columns)) != binary_position
    continuous_columns = columns[keep]
    continuous_coefficients = coefficients[keep]
    if len(continuous_columns) == 0 or np.any(integrality[continuous_columns] != 0):
        return None
    maximum_terms = np.where(
        continuous_coefficients >= 0.0,
        continuous_coefficients * col_upper[continuous_columns],
        continuous_coefficients * col_lower[continuous_columns],
    )
    inactive_upper = float(np.sum(maximum_terms))
    if not math.isfinite(inactive_upper) or inactive_upper > upper + tol:
        return None
    return indicator_column, continuous_columns, continuous_coefficients, upper - big_m, inactive_upper


def _trusted_scip_infeasibility(info: Mapping[str, Any], *, incumbent_returned: bool) -> bool:
    """Fail closed for all SCIP limits, interrupts, errors, and incumbents."""

    return bool(
        info.get("backend") == SCIP_INDICATOR_BACKEND
        and info.get("status_raw") == "infeasible"
        and info.get("stage") == info.get("stage_solved_code")
        and info.get("solutions") == 0
        and not incumbent_returned
        and info.get("indicator_equivalence_check") == "inactive-side-implied-by-frozen-column-bounds"
        and isinstance(info.get("base_model_sha256"), str)
        and len(str(info.get("base_model_sha256"))) == 64
        and isinstance(info.get("indicator_transform_sha256"), str)
        and len(str(info.get("indicator_transform_sha256"))) == 64
    )


def _solve_scip_indicator_milp(
    c: np.ndarray,
    A_ineq: np.ndarray,
    b_ineq_lo: np.ndarray,
    b_ineq_hi: np.ndarray,
    A_eq: np.ndarray,
    b_eq: np.ndarray,
    integrality: np.ndarray,
    lb: np.ndarray,
    ub: np.ndarray,
    *,
    node_limit: int | None = None,
    solution_limit: int | None = 1,
    time_limit_s: float | None = None,
) -> tuple[np.ndarray | None, dict[str, Any]]:
    """Solve the frozen one-hot AHC model via exact SCIP indicators.

    The mathematical source remains the ordinary linear one-hot model.  This
    backend only performs a mechanically checked representation transform; all
    unrecognized rows are copied verbatim.  A returned incumbent is accepted
    here only if it satisfies the complete *original* linear model.
    """

    from scipy import sparse

    objective = np.asarray(c, dtype=np.float64)
    objective_kind = "constant" if not np.any(objective) else "linear"
    lower = np.asarray(lb, dtype=np.float64)
    upper = np.asarray(ub, dtype=np.float64)
    integer = np.asarray(integrality, dtype=np.int32)
    matrix = sparse.vstack([A_ineq, A_eq], format="csr").astype(np.float64, copy=False)
    row_lower = np.concatenate([b_ineq_lo, b_eq]).astype(np.float64)
    row_upper = np.concatenate([b_ineq_hi, b_eq]).astype(np.float64)
    base_model_sha256 = _frozen_milp_sha256(
        objective,
        matrix,
        row_lower,
        row_upper,
        lower,
        upper,
        integer,
    )

    replacements: dict[int, tuple[int, np.ndarray, np.ndarray, float, float]] = {}
    descriptors: list[dict[str, Any]] = []
    for row in range(matrix.shape[0]):
        replacement = _scip_indicator_replacement(
            matrix,
            row_lower,
            row_upper,
            lower,
            upper,
            integer,
            row,
        )
        if replacement is None:
            continue
        indicator_column, columns, coefficients, target, inactive_upper = replacement
        replacements[row] = replacement
        descriptors.append(
            {
                "coefficients": [float(value).hex() for value in coefficients],
                "columns": [int(column) for column in columns],
                "inactive_upper": float(inactive_upper).hex(),
                "indicator_column": indicator_column,
                "row": row,
                "target": float(target).hex(),
            }
        )
    transform_bytes = json.dumps(descriptors, sort_keys=True, separators=(",", ":")).encode("utf-8")
    transform_sha256 = hashlib.sha256(transform_bytes).hexdigest()
    base_info: dict[str, Any] = {
        "backend": SCIP_INDICATOR_BACKEND,
        "base_model_sha256": base_model_sha256,
        "binary_variables": int(np.count_nonzero(integer)),
        "indicator_equivalence_check": "inactive-side-implied-by-frozen-column-bounds",
        "indicator_rows": len(replacements),
        "indicator_transform_sha256": transform_sha256,
        "linear_rows": int(matrix.shape[0] - len(replacements)),
        "objective_policy": objective_kind,
        "options": dict(SCIP_INDICATOR_OPTIONS),
        "solution_limit": solution_limit,
        "time_limit_s": time_limit_s,
    }

    scip: Any | None = None
    try:
        import pyscipopt

        build_start = time.perf_counter()
        scip = pyscipopt.Model("hec-ahc-one-hot-indicator")
        scip.hideOutput(True)
        for name, value in SCIP_INDICATOR_OPTIONS.items():
            scip.setParam(name, value)
        if node_limit is not None:
            scip.setParam("limits/nodes", int(node_limit))
        if time_limit_s is not None:
            scip.setParam("limits/time", float(time_limit_s))
        if solution_limit is not None:
            scip.setParam("limits/solutions", int(solution_limit))
        variables = [
            scip.addVar(
                name=f"x{column}",
                vtype="B" if integer[column] else "C",
                lb=float(lower[column]),
                ub=float(upper[column]),
            )
            for column in range(matrix.shape[1])
        ]
        for row in range(matrix.shape[0]):
            start, stop = matrix.indptr[row : row + 2]
            replacement = replacements.get(row)
            if replacement is not None:
                indicator_column, columns, coefficients, target, _inactive_upper = replacement
                expression = pyscipopt.quicksum(
                    float(value) * variables[int(column)] for column, value in zip(columns, coefficients, strict=True)
                )
                scip.addConsIndicator(expression <= target, binvar=variables[indicator_column], activeone=True)
                continue
            expression = pyscipopt.quicksum(
                float(value) * variables[int(column)]
                for column, value in zip(matrix.indices[start:stop], matrix.data[start:stop], strict=True)
            )
            row_lo = float(row_lower[row])
            row_hi = float(row_upper[row])
            if math.isfinite(row_lo) and math.isfinite(row_hi) and row_lo == row_hi:
                scip.addCons(expression == row_lo)
            else:
                if math.isfinite(row_lo):
                    scip.addCons(expression >= row_lo)
                if math.isfinite(row_hi):
                    scip.addCons(expression <= row_hi)
        if np.any(objective):
            scip.setObjective(
                pyscipopt.quicksum(
                    float(cost) * variables[column] for column, cost in enumerate(objective) if cost != 0.0
                ),
                "minimize",
            )
        else:
            scip.setObjective(0.0, "minimize")
        build_s = time.perf_counter() - build_start
        solve_start = time.perf_counter()
        scip.optimize()
        solve_s = time.perf_counter() - solve_start
        status_raw = str(scip.getStatus())
        stage = int(scip.getStage())
        raw_solution = scip.getBestSol()
        solution = None
        if raw_solution is not None:
            solution = np.asarray([scip.getSolVal(raw_solution, variable) for variable in variables], dtype=np.float64)
        info = {
            **base_info,
            "build_s": build_s,
            "nodes": int(scip.getNNodes()),
            "pyscipopt_version": pyscipopt.__version__,
            "scip_version": f"{scip.getMajorVersion()}.{scip.getMinorVersion()}.{scip.getTechVersion()}",
            "solve_s": solve_s,
            "solver_reported_s": float(scip.getSolvingTime()),
            "solutions": int(scip.getNSols()),
            "stage": stage,
            "stage_solved_code": int(pyscipopt.SCIP_STAGE.SOLVED),
            "status_raw": status_raw,
        }
    except Exception as exc:
        return None, {
            **base_info,
            "error": f"{type(exc).__name__}: {exc}",
            "status": "unknown",
            "status_raw": "backend_error",
            "success": False,
        }
    finally:
        if scip is not None:
            try:
                scip.freeProb()
            except Exception:
                # Cleanup failure cannot promote a solver result.  All scalar
                # telemetry and any incumbent were copied before this point.
                pass

    if solution is not None and _satisfies_linear_model(
        solution,
        matrix,
        row_lower,
        row_upper,
        lower,
        upper,
        integer,
    ):
        info.update({"incumbent_model_valid": True, "status": "realized", "success": True})
        return solution, info
    info["incumbent_model_valid"] = None if solution is None else False
    info["success"] = False
    info["status"] = (
        "infeasible" if _trusted_scip_infeasibility(info, incumbent_returned=solution is not None) else "unknown"
    )
    return None, info


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


@lru_cache(maxsize=4)
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


@dataclass(frozen=True)
class _MilpAttempt:
    name: str
    backend: str
    objective: str
    time_limit_s: float | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "name": self.name,
            "objective": self.objective,
            "time_limit_s": self.time_limit_s,
        }


def _milp_attempt_plan(
    *,
    selector_count: int,
) -> tuple[_MilpAttempt, ...]:
    """Build the declarative, ordered backend portfolio for one frozen model."""

    if selector_count < 0:
        raise ValueError("selector count must be non-negative")
    scip_limit = None if selector_count <= DEFAULT_SCIP_SELECTOR_THRESHOLD else DEFAULT_SCIP_PREPASS_S
    return (
        _MilpAttempt("scip-indicator-constant", SCIP_INDICATOR_BACKEND, "constant", scip_limit),
        _MilpAttempt("native-highs-1.14-max-edges", HIGHSPY_BACKEND, "max-edges"),
    )


def _solve_ahc_for_N(
    target: np.ndarray,
    n: int,
    N: int,
    *,
    assume_no_smaller: bool = False,
    node_limit: int | None = None,
    branch_choice_values: Mapping[tuple[int, int], int | float] | None = None,
    time_limit_s: float | None = None,
) -> tuple[Graph | None, dict]:
    profile_start = time.perf_counter()
    if time_limit_s is not None and (not math.isfinite(time_limit_s) or time_limit_s <= 0):
        raise ValueError("time_limit_s must be a positive finite number")
    if n < 1 or N < n + 1:
        return None, {"status": "invalid_target"}
    try:
        exact_target = _exact_target_values(target, n)
    except (ArithmeticError, TypeError, ValueError):
        return None, {"status": "invalid_target"}
    if any(value < 0 for value in exact_target):
        return None, {"status": "invalid_target"}

    edges, fixed_subsystems, fixed_sub_indices, cuts_by_sub = _ahc_structure(n, N)
    edge_count = len(edges)

    exact = _exact_ahc_preprocessing(n, N, exact_target)
    if exact.infeasible:
        return None, {"status": "infeasible"}
    scaled = np.asarray([float(value) for value in exact.scaled_target], dtype=np.float64)
    edge_lb = np.asarray([float(value) for value in exact.edge_lower], dtype=np.float64)
    edge_ub = np.asarray([float(value) for value in exact.edge_upper], dtype=np.float64)
    if not np.all(np.isfinite(scaled)) or not np.all(np.isfinite(edge_lb)) or not np.all(np.isfinite(edge_ub)):
        return None, {"status": "invalid_target", "reason": "target_outside_float_solver_range"}
    maximum = max(exact_target, default=Fraction(0))
    scale = 1.0 if maximum == 0 else float(1 / maximum)

    tol = 1e-9
    cut_bounds = exact.cut_bounds
    choices_by_sub = dict(exact.choices_by_sub)
    auto_selected_by_sub = dict(exact.auto_selected_by_sub)

    fixed_choice_values, forced_upper_cuts, deterministic_stats, deterministic_feasible = (
        _deterministic_union_cut_fixes_exact(
            exact.scaled_target,
            n,
            N,
            choices_by_sub,
            cut_bounds,
            fixed_sub_indices,
        )
    )
    if not deterministic_feasible:
        return None, {"status": "infeasible"}

    branch_fixed_count = 0
    if branch_choice_values:
        fixed_choice_values = dict(fixed_choice_values)
        forced_upper_cut_set = set(forced_upper_cuts)
        for raw_key, raw_value in branch_choice_values.items():
            sub_index, cut_index = int(raw_key[0]), int(raw_key[1])
            if raw_value not in (0, 0.0, 1, 1.0):
                raise ValueError(f"branch choice values must be binary, got {raw_value!r}")
            key = (sub_index, cut_index)
            choices = choices_by_sub.get(sub_index)
            existing = fixed_choice_values.get(key)
            if choices is None or cut_index not in choices:
                if existing is not None and abs(existing - float(raw_value)) <= tol:
                    continue
                return None, {
                    "status": "infeasible",
                    "reason": "branch_choice_not_available",
                    "branch_choice": [sub_index, cut_index, int(raw_value)],
                }
            value = float(raw_value)
            if existing is not None:
                if abs(existing - value) > tol:
                    return None, {
                        "status": "infeasible",
                        "reason": "branch_choice_conflict",
                        "branch_choice": [sub_index, cut_index, int(value)],
                    }
                continue
            fixed_choice_values[key] = value
            branch_fixed_count += 1
            if value == 1.0:
                forced_upper_cut_set.add(key)
        forced_upper_cuts = frozenset(forced_upper_cut_set)

    # Exact one-hot propagation keeps compact branch payloads compact without
    # leaving hundreds of implied-zero selectors in the frozen MILP.  A fixed
    # one selects the subsystem cut and fixes every peer to zero; conversely,
    # if fixed zeros leave one cut, that final cut is selected.  Expanded
    # historical branch payloads therefore build the byte-identical model.
    propagated_choice_fixes = 0
    fixed_choice_values = dict(fixed_choice_values)
    forced_upper_cut_set = set(forced_upper_cuts)
    for sub_index, choices in choices_by_sub.items():
        selected = [
            cut_index
            for cut_index in choices
            if abs(float(fixed_choice_values.get((sub_index, cut_index), 0.0)) - 1.0) <= tol
        ]
        if len(selected) > 1:
            return None, {"status": "infeasible", "reason": "multiple_selected_cuts"}
        free = [cut_index for cut_index in choices if (sub_index, cut_index) not in fixed_choice_values]
        if not selected and not free:
            return None, {"status": "infeasible", "reason": "branch_choice_sum_conflict"}
        if not selected and len(free) == 1:
            selected = free
            fixed_choice_values[(sub_index, free[0])] = 1.0
            forced_upper_cut_set.add((sub_index, free[0]))
            propagated_choice_fixes += 1
        if selected:
            forced_upper_cut_set.add((sub_index, selected[0]))
            for cut_index in choices:
                key = (sub_index, cut_index)
                expected = 1.0 if cut_index == selected[0] else 0.0
                existing = fixed_choice_values.get(key)
                if existing is not None and abs(float(existing) - expected) > tol:
                    return None, {"status": "infeasible", "reason": "branch_choice_sum_conflict"}
                if existing is None:
                    fixed_choice_values[key] = expected
                    propagated_choice_fixes += 1
    forced_upper_cuts = frozenset(forced_upper_cut_set)

    selected_by_sub = dict(auto_selected_by_sub)
    for (sub_index, cut_index), value in fixed_choice_values.items():
        if abs(float(value) - 1.0) <= tol:
            previous = selected_by_sub.setdefault(sub_index, cut_index)
            if previous != cut_index:
                return None, {"status": "infeasible", "reason": "multiple_selected_cuts"}

    reduction_stats: dict[str, int] = {
        "tight_known_cuts": 0,
        "tight_derived_cuts": 0,
        "tight_forced_zero_edges": 0,
        "tight_zero_bound_edges_added": 0,
    }
    bulk_count = max(0, N - n - 1)
    full_bulk_mask = (1 << bulk_count) - 1
    known_equality_cuts: set[EqualityCut] = set()
    sub_index_by_boundary = subset_index_map(n)
    for terminals in fixed_subsystems:
        boundary = _boundary_subset_for_terminals(n, terminals)
        known_equality_cuts.add(EqualityCut(boundary, full_bulk_mask if n in terminals else 0))
    for sub_index, cut_index in forced_upper_cuts:
        known_equality_cuts.add(EqualityCut(subsets(n)[sub_index], cut_index))
    for sub_index, cut_index in selected_by_sub.items():
        known_equality_cuts.add(EqualityCut(subsets(n)[sub_index], cut_index))

    deductions = close_tight_submodularity(n, N, exact_target, known_equality_cuts)
    forced_upper_cut_set = set(forced_upper_cuts)
    edge_index = {edge: index for index, edge in enumerate(edges)}
    zero_bound_positions = {index for index, upper in enumerate(exact.edge_upper) if upper == 0}
    zero_bound_edges_before = len(zero_bound_positions)
    for a, b in deductions.forced_zero_edges:
        edge_pos = edge_index[(a, b)]
        if exact.edge_lower[edge_pos] > 0:
            return None, {"status": "infeasible", "reason": "tight_submodularity_edge_conflict"}
        edge_ub[edge_pos] = 0.0
        zero_bound_positions.add(edge_pos)
    for cut in deductions.derived_cuts:
        if cut.boundary:
            forced_upper_cut_set.add((sub_index_by_boundary[cut.boundary], cut.bulk_mask))
            continue
        inside = {n + offset for offset in range(bulk_count) if (cut.bulk_mask >> offset) & 1}
        for edge_pos in _crossing_edges(edges, inside):
            if exact.edge_lower[edge_pos] > 0:
                return None, {"status": "infeasible", "reason": "tight_submodularity_edge_conflict"}
            edge_ub[edge_pos] = 0.0
            zero_bound_positions.add(edge_pos)
    forced_upper_cuts = frozenset(forced_upper_cut_set)
    reduction_stats.update(
        {
            "tight_known_cuts": len(deductions.known_cuts),
            "tight_derived_cuts": len(deductions.derived_cuts),
            "tight_forced_zero_edges": len(deductions.forced_zero_edges),
            "tight_zero_bound_edges_added": len(zero_bound_positions) - zero_bound_edges_before,
        }
    )

    choice_index: dict[tuple[int, int], int] = {}
    next_index = edge_count
    for sub_index, choices in choices_by_sub.items():
        for cut_index in choices:
            if (sub_index, cut_index) in fixed_choice_values:
                continue
            choice_index[(sub_index, cut_index)] = next_index
            next_index += 1
    var_count = next_index
    integrality = np.zeros(var_count, dtype=int)
    integrality[edge_count:] = 1
    lb = np.zeros(var_count)
    ub = np.ones(var_count)
    lb[:edge_count] = edge_lb
    ub[:edge_count] = edge_ub

    ineq_rows: list[int] = []
    ineq_cols: list[int] = []
    ineq_data: list[float] = []
    b_ineq_hi: list[float] = []
    b_ineq_lo: list[float] = []
    eq_rows: list[int] = []
    eq_cols: list[int] = []
    eq_data: list[float] = []
    b_eq: list[float] = []
    for sub_index, cuts in enumerate(cuts_by_sub):
        exact_value = exact.scaled_target[sub_index]
        value = float(exact_value)
        for cut_index, crossing in enumerate(cuts):
            lower, upper = cut_bounds[sub_index][cut_index]
            if lower < exact_value:
                row = len(b_ineq_hi)
                for edge in crossing:
                    ineq_rows.append(row)
                    ineq_cols.append(int(edge))
                    ineq_data.append(-1.0)
                b_ineq_hi.append(-value)
                b_ineq_lo.append(-np.inf)
            if (sub_index, cut_index) in forced_upper_cuts and upper > exact_value:
                row = len(b_ineq_hi)
                for edge in crossing:
                    ineq_rows.append(row)
                    ineq_cols.append(int(edge))
                    ineq_data.append(1.0)
                b_ineq_hi.append(value)
                b_ineq_lo.append(-np.inf)
                continue
            if (sub_index, cut_index) in fixed_choice_values:
                continue
            choice_var = choice_index.get((sub_index, cut_index))
            if choice_var is not None:
                row = len(b_ineq_hi)
                big_m = float(upper - exact_value)
                for edge in crossing:
                    ineq_rows.append(row)
                    ineq_cols.append(int(edge))
                    ineq_data.append(1.0)
                if big_m != 0.0:
                    ineq_rows.append(row)
                    ineq_cols.append(choice_var)
                    ineq_data.append(big_m)
                b_ineq_hi.append(float(upper))
                b_ineq_lo.append(-np.inf)
        choices = choices_by_sub.get(sub_index)
        if choices is not None:
            rhs = 1.0
            free_choices = []
            for cut_index in choices:
                fixed_value = fixed_choice_values.get((sub_index, cut_index))
                if fixed_value is not None:
                    rhs -= fixed_value
                    continue
                free_choices.append(cut_index)
            if rhs < -tol or rhs - len(free_choices) > tol:
                return None, {"status": "infeasible", "reason": "branch_choice_sum_conflict"}
            if not free_choices:
                if abs(rhs) > tol:
                    return None, {"status": "infeasible"}
                continue
            eq_row = len(b_eq)
            for cut_index in free_choices:
                eq_rows.append(eq_row)
                eq_cols.append(choice_index[(sub_index, cut_index)])
                eq_data.append(1.0)
            b_eq.append(rhs)

    for terminals in fixed_subsystems:
        eq_row = len(b_eq)
        inside = {N - 1 if terminal == n else terminal for terminal in terminals}
        for edge in _crossing_edges(edges, inside):
            eq_rows.append(eq_row)
            eq_cols.append(edge)
            eq_data.append(1.0)
        b_eq.append(float(_terminal_entropy_exact(exact.scaled_target, n, terminals)))

    symmetry_rows = 0
    signature_rows = 0
    terminal_signature_pairs = 0
    terminal_signature_rows = 0
    dominance_rows = 0
    fixed_by_sub: dict[int, dict[int, float]] = {}
    for (sub_index, cut_index), value in fixed_choice_values.items():
        fixed_by_sub.setdefault(sub_index, {})[cut_index] = float(value)
    partial_choice_fixing = any(
        sub_index not in selected_by_sub and any(abs(value) <= tol for value in values.values())
        for sub_index, values in fixed_by_sub.items()
    )

    if not partial_choice_fixing:
        bulk_count = max(0, N - n - 1)
        known_subsystems = tuple(sorted(selected_by_sub))
        known_masks = tuple(selected_by_sub[sub_index] for sub_index in known_subsystems)
        prefix_blocks: dict[tuple[int, ...], list[int]] = {}
        for bulk_offset in range(bulk_count):
            signature = tuple((mask >> bulk_offset) & 1 for mask in known_masks)
            prefix_blocks.setdefault(signature, []).append(bulk_offset)
        variable_subsystems = tuple(
            sub_index for sub_index in sorted(choices_by_sub) if sub_index not in selected_by_sub
        )

        if len(variable_subsystems) <= 20:
            for block in prefix_blocks.values():
                for left_offset, right_offset in zip(block, block[1:], strict=False):
                    coefficients: dict[int, float] = {}
                    for position, sub_index in enumerate(variable_subsystems):
                        weight = float(1 << position)
                        for cut_index in choices_by_sub[sub_index]:
                            choice_var = choice_index.get((sub_index, cut_index))
                            if choice_var is None:
                                continue
                            difference = ((cut_index >> left_offset) & 1) - ((cut_index >> right_offset) & 1)
                            if difference:
                                coefficients[choice_var] = coefficients.get(choice_var, 0.0) + weight * difference
                    bound = -1.0 if assume_no_smaller else 0.0
                    if not coefficients:
                        if bound < 0.0:
                            return None, {
                                "status": "infeasible",
                                "reason": "duplicate_bulk_cut_signatures",
                            }
                        continue
                    row = len(b_ineq_hi)
                    for column, coefficient in coefficients.items():
                        ineq_rows.append(row)
                        ineq_cols.append(column)
                        ineq_data.append(coefficient)
                    b_ineq_hi.append(bound)
                    b_ineq_lo.append(-np.inf)
                    symmetry_rows += 1
                    if assume_no_smaller:
                        signature_rows += 1
        elif assume_no_smaller:
            for block in prefix_blocks.values():
                for left_pos, left_offset in enumerate(block):
                    for right_offset in block[left_pos + 1 :]:
                        separating_variables: list[int] = []
                        for sub_index in variable_subsystems:
                            for cut_index in choices_by_sub[sub_index]:
                                if ((cut_index >> left_offset) & 1) == ((cut_index >> right_offset) & 1):
                                    continue
                                choice_var = choice_index.get((sub_index, cut_index))
                                if choice_var is not None:
                                    separating_variables.append(choice_var)
                        if not separating_variables:
                            return None, {
                                "status": "infeasible",
                                "reason": "duplicate_bulk_cut_signatures",
                            }
                        row = len(b_ineq_hi)
                        for column in separating_variables:
                            ineq_rows.append(row)
                            ineq_cols.append(column)
                            ineq_data.append(-1.0)
                        b_ineq_hi.append(-1.0)
                        b_ineq_lo.append(-np.inf)
                        signature_rows += 1

    if assume_no_smaller:
        # Every fixed-N model already selects the terminal-only singleton cut
        # for each physical terminal and the purifier-only singleton cut (in
        # canonical complemented form) for O.  Each such cut separates that
        # terminal from every bulk vertex.  Thus all bulk--terminal signature
        # pairs are checked and already distinct; adding rows based only on the
        # remaining variable cuts would omit these witnesses and be unsound.
        terminal_signature_pairs = max(0, N - n - 1) * (n + 1)
        edge_position = {edge: index for index, edge in enumerate(edges)}
        for bulk_vertex in range(n, N - 1):
            for other_vertex in range(N):
                if other_vertex == bulk_vertex:
                    continue
                row = len(b_ineq_hi)
                dominant_edge = edge_position[tuple(sorted((bulk_vertex, other_vertex)))]
                ineq_rows.append(row)
                ineq_cols.append(dominant_edge)
                ineq_data.append(1.0)
                for neighbor in range(N):
                    if neighbor in (bulk_vertex, other_vertex):
                        continue
                    edge = edge_position[tuple(sorted((bulk_vertex, neighbor)))]
                    ineq_rows.append(row)
                    ineq_cols.append(edge)
                    ineq_data.append(-1.0)
                b_ineq_hi.append(0.0)
                b_ineq_lo.append(-np.inf)
                dominance_rows += 1

    from scipy import sparse

    n_ineq = len(b_ineq_hi)
    n_eq = len(b_eq)
    b_ineq_hi_array = np.asarray(b_ineq_hi, dtype=np.float64)
    b_ineq_lo_array = np.asarray(b_ineq_lo, dtype=np.float64)
    b_eq_array = np.asarray(b_eq, dtype=np.float64)
    A_ineq = sparse.csr_matrix((ineq_data, (ineq_rows, ineq_cols)), shape=(n_ineq, var_count), dtype=np.float64)
    A_eq = sparse.csr_matrix((eq_data, (eq_rows, eq_cols)), shape=(n_eq, var_count), dtype=np.float64)
    frozen_matrix = sparse.vstack([A_ineq, A_eq], format="csr")
    constraint_model_sha256 = _frozen_milp_sha256(
        np.zeros(var_count, dtype=np.float64),
        frozen_matrix,
        np.concatenate([b_ineq_lo_array, b_eq_array]),
        np.concatenate([b_ineq_hi_array, b_eq_array]),
        lb,
        ub,
        integrality,
    )

    binary_count = var_count - edge_count
    attempt_plan = _milp_attempt_plan(selector_count=binary_count)
    profile: dict[str, Any] = {
        "edge_vars": edge_count,
        "binary_vars": binary_count,
        **deterministic_stats,
        **reduction_stats,
        "symmetry_rows": symmetry_rows,
        "assume_no_smaller": int(assume_no_smaller),
        "signature_rows": signature_rows,
        "terminal_signature_pairs": terminal_signature_pairs,
        "terminal_signature_rows": terminal_signature_rows,
        "dominance_rows": dominance_rows,
        "branch_fixed_choices": branch_fixed_count,
        "one_hot_propagated_fixes": propagated_choice_fixes,
        "milp_attempt_plan": [attempt.as_record() for attempt in attempt_plan],
        "constraint_model_sha256": constraint_model_sha256,
        "scip_selector_threshold": DEFAULT_SCIP_SELECTOR_THRESHOLD,
        "vars": var_count,
        "ineq_rows": n_ineq,
        "eq_rows": n_eq,
        "nnz": int(A_ineq.nnz + A_eq.nnz),
        "build_s": time.perf_counter() - profile_start,
        "lp_s": 0.0,
        "lp_status": "eliminated_redundant_relaxation",
    }

    def validate_incumbent(incumbent: np.ndarray, solver_info: dict[str, Any]) -> tuple[Graph | None, int | str | None]:
        labels = party_labels(n)
        raw_edges: list[list[str]] = []
        raw_weights: list[float] = []
        for edge_pos, (a, b) in enumerate(edges):
            weight = float(incumbent[edge_pos]) / scale
            if weight <= 1e-9:
                continue
            raw_edges.append([_vertex_label(a, n, N, labels), _vertex_label(b, n, N, labels)])
            raw_weights.append(weight)
        raw_candidate, candidate_scale = _integer_graph(raw_edges, raw_weights)
        candidate, component_pruning = prune_entropy_irrelevant_components(raw_candidate, n)
        prelift_vertices = graph_total_vertices(candidate, n)
        match_mode = "ray" if any(value != 0 for value in exact_target) else "exact"
        raw_candidate_check = _exact_graph_check(
            raw_candidate,
            exact_target,
            n,
            ray=match_mode == "ray",
        )
        prelift_check = _exact_graph_check(candidate, exact_target, n, ray=match_mode == "ray")
        validation: dict[str, Any] = {
            "accepted": False,
            "exact_rational_mincut_model_candidate": raw_candidate_check,
            "exact_rational_mincut_prelift": prelift_check,
            "original_one_hot_model_valid": True,
            "prelift_total_vertices": prelift_vertices,
            "requested_total_vertices": N,
            "target_match_mode": match_mode,
            "terminal_component_pruning": component_pruning,
        }
        if not raw_candidate_check["ok"] or not prelift_check["ok"] or prelift_vertices > N:
            validation["reason"] = (
                "exact_rational_mincut_mismatch"
                if not raw_candidate_check["ok"] or not prelift_check["ok"]
                else "active_vertex_overflow"
            )
            solver_info["incumbent_validation"] = validation
            return None, None
        lifted_graph, lift = lift_graph_total_vertices(candidate, n, N)
        postlift_check = _exact_graph_check(lifted_graph, exact_target, n, ray=match_mode == "ray")
        postlift_vertices = graph_total_vertices(lifted_graph, n)
        validation.update(
            {
                "accepted": bool(postlift_check["ok"] and postlift_vertices == N),
                "assume_no_smaller_counterexample": bool(assume_no_smaller and prelift_vertices < N),
                "exact_rational_mincut_postlift": postlift_check,
                "lift": {
                    **lift,
                    "assume_no_smaller_counterexample": bool(assume_no_smaller and prelift_vertices < N),
                    "terminal_component_pruning": component_pruning,
                },
                **lift,
            }
        )
        solver_info["incumbent_validation"] = validation
        if not validation["accepted"]:
            return None, None
        return lifted_graph, candidate_scale

    attempt_records: list[dict[str, Any]] = []
    prior_model_valid_incumbent = False
    solve_start = time.perf_counter()
    for attempt in attempt_plan:
        effective_time_limit = attempt.time_limit_s
        if time_limit_s is not None:
            # The public budget covers preprocessing and model construction as
            # well as the backend portfolio, not just time inside the solver.
            remaining = time_limit_s - (time.perf_counter() - profile_start)
            if remaining <= 0:
                attempt_records.append(
                    {
                        "attempt": attempt.as_record(),
                        "attempt_ordinal": len(attempt_records),
                        "reason": "fixed_n_time_limit_exhausted",
                        "status": "unknown",
                    }
                )
                break
            effective_time_limit = remaining if effective_time_limit is None else min(remaining, effective_time_limit)
        objective = np.zeros(var_count)
        if attempt.objective == "max-edges":
            objective[:edge_count] = -1.0
        try:
            if attempt.backend == SCIP_INDICATOR_BACKEND:
                solution, attempt_info = _solve_scip_indicator_milp(
                    objective,
                    A_ineq,
                    b_ineq_lo_array,
                    b_ineq_hi_array,
                    A_eq,
                    b_eq_array,
                    integrality,
                    lb,
                    ub,
                    node_limit=node_limit,
                    solution_limit=1,
                    time_limit_s=effective_time_limit,
                )
            else:
                solution, attempt_info = _solve_highspy_milp(
                    objective,
                    A_ineq,
                    b_ineq_lo_array,
                    b_ineq_hi_array,
                    A_eq,
                    b_eq_array,
                    integrality,
                    lb,
                    ub,
                    node_limit=node_limit,
                    time_limit_s=effective_time_limit,
                )
        except Exception as exc:
            solution = None
            attempt_info = {
                "backend": attempt.backend,
                "error": f"{type(exc).__name__}: {exc}",
                "reason": "backend_error",
                "status": "unknown",
            }
        attempt_info["effective_time_limit_s"] = effective_time_limit
        attempt_info["constraint_model_sha256"] = constraint_model_sha256
        attempt_info.update({"attempt": attempt.as_record(), "attempt_ordinal": len(attempt_records)})
        if solution is not None:
            shared_model_valid = _satisfies_linear_model(
                solution,
                A_ineq,
                b_ineq_lo_array,
                b_ineq_hi_array,
                lb,
                ub,
                integrality,
            ) and _satisfies_linear_model(
                solution,
                A_eq,
                b_eq_array,
                b_eq_array,
                lb,
                ub,
                integrality,
            )
            attempt_info["incumbent_model_valid"] = shared_model_valid
            attempt_info["incumbent_model_validation"] = "shared-frozen-one-hot-linear-model"
            if not shared_model_valid:
                attempt_info["status_before_shared_model_validation"] = attempt_info.get("status")
                attempt_info["status"] = "unknown"
                attempt_records.append(attempt_info)
                continue
            prior_model_valid_incumbent = True
            graph, weight_scale = validate_incumbent(solution, attempt_info)
            attempt_records.append(attempt_info)
            if graph is not None:
                profile.update(
                    {
                        "milp_attempts": len(attempt_records),
                        "milp_effective_backend": attempt.backend,
                        "milp_objective_policy": attempt.objective,
                        "milp_s": time.perf_counter() - solve_start,
                    }
                )
                winning_info = {**attempt_info, "attempts": attempt_records}
                validation = attempt_info["incumbent_validation"]
                return graph, {
                    "status": "realized",
                    "weight_scale": weight_scale,
                    "active_total_vertices": N,
                    "prelift_total_vertices": validation["prelift_total_vertices"],
                    "lift": validation["lift"],
                    "verification": validation["exact_rational_mincut_postlift"],
                    "solver": "milp",
                    "profile": profile,
                    "milp": winning_info,
                }
            continue

        trustworthy_negative = attempt_info.get("status") == "infeasible" and attempt.backend in {
            SCIP_INDICATOR_BACKEND,
            HIGHSPY_BACKEND,
        }
        if trustworthy_negative and prior_model_valid_incumbent:
            attempt_info["status_before_feasibility_contradiction"] = "infeasible"
            attempt_info["status"] = "unknown"
            attempt_info["negative_downgraded_by_prior_model_valid_incumbent"] = True
            trustworthy_negative = False
        attempt_records.append(attempt_info)
        if trustworthy_negative:
            profile.update(
                {
                    "milp_attempts": len(attempt_records),
                    "milp_effective_backend": attempt.backend,
                    "milp_objective_policy": attempt.objective,
                    "milp_s": time.perf_counter() - solve_start,
                }
            )
            terminal_info = {**attempt_info, "attempts": attempt_records}
            return None, {
                "status": "infeasible",
                "solver": "milp",
                "profile": profile,
                "milp": terminal_info,
            }

    profile.update(
        {
            "milp_attempts": len(attempt_records),
            "milp_effective_backend": attempt_records[-1].get("backend") if attempt_records else None,
            "milp_s": time.perf_counter() - solve_start,
        }
    )
    final_info = {**attempt_records[-1], "attempts": attempt_records} if attempt_records else {"status": "unknown"}
    return None, {
        "status": "unknown",
        "reason": "milp_attempt_plan_exhausted",
        "solver": "milp",
        "profile": profile,
        "milp": final_info,
    }


def _vertex_label(vertex: int, n: int, N: int, labels: Sequence[str]) -> str:
    if vertex < n:
        return labels[vertex]
    if vertex == N - 1:
        return "O"
    return f"x{vertex - n + 1}"
