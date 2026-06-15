"""Deterministic contraction-map solver."""

from __future__ import annotations

import ctypes
import importlib
import sys
import time
from typing import TYPE_CHECKING

import numpy as np
import pysolvers
from numba import njit
from pysat.solvers import Solver

from ._extensions import ensure_contraction_extensions
from .bits import bit_mask

ensure_contraction_extensions()

_clause_builder = importlib.import_module("hec.clause_builder")
_clause_direct = importlib.import_module("hec.clause_direct")
build_clauses = _clause_builder.build_clauses
dispatch_card_direct = _clause_direct.dispatch_card_direct
dispatch_xor_direct = _clause_direct.dispatch_xor_direct
get_model_direct = _clause_direct.get_model_direct
set_kissat_add_fn = _clause_direct.set_kissat_add_fn
set_kissat_value_fn = _clause_direct.set_kissat_value_fn

if TYPE_CHECKING:
    from .contractions import ContractionProblem

KISSAT_OPTIONS = {
    b"probe": 0,
    b"minimize": 0,
    b"bump": 0,
    b"forcephase": 1,
    b"modeinit": 5000,
    b"restartint": 200,
    b"vivifytier2": 2,
}
MAX_ANCHORS = 100
_SAT_SOLVER = "kissat"
_SAT_BACKEND = "kissat_direct_cython"


def _load_direct_kissat_library() -> ctypes.CDLL:
    library = ctypes.CDLL(pysolvers.__file__)
    required = ("kissat_add", "kissat_value", "kissat_set_option")
    missing = [name for name in required if not hasattr(library, name)]
    if missing:
        raise RuntimeError(
            f"PySAT library {pysolvers.__file__!r} is missing required Kissat symbols for {sys.platform}: "
            f"{', '.join(missing)}"
        )
    library.kissat_add.argtypes = [ctypes.c_void_p, ctypes.c_int32]
    library.kissat_add.restype = ctypes.c_int
    library.kissat_value.argtypes = [ctypes.c_void_p, ctypes.c_int32]
    library.kissat_value.restype = ctypes.c_int
    library.kissat_set_option.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    library.kissat_set_option.restype = ctypes.c_int
    if hasattr(library, "kissat_reserve"):
        library.kissat_reserve.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        library.kissat_reserve.restype = None
    return library


def _require_kissat_solver() -> None:
    try:
        solver = Solver(name=_SAT_SOLVER)
    except Exception as exc:  # pragma: no cover - depends on platform wheel contents
        raise RuntimeError(
            f"PySAT library {pysolvers.__file__!r} is missing required solver {_SAT_SOLVER!r} "
            f"for {sys.platform}"
        ) from exc
    solver.delete()


_require_kissat_solver()
_KISSAT_LIB = _load_direct_kissat_library()
set_kissat_add_fn(ctypes.cast(_KISSAT_LIB.kissat_add, ctypes.c_void_p).value)
set_kissat_value_fn(ctypes.cast(_KISSAT_LIB.kissat_value, ctypes.c_void_p).value)

# Optional: pre-sizing the variable arrays avoids incremental growth during clause
# loading. Absent in older wheels, so resolve once here and treat as best-effort.
_KISSAT_RESERVE = getattr(_KISSAT_LIB, "kissat_reserve", None)

ctypes.pythonapi.PyCapsule_GetName.argtypes = [ctypes.py_object]
ctypes.pythonapi.PyCapsule_GetName.restype = ctypes.c_char_p
ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p


class Contradiction(Exception):
    """Raised when deterministic propagation proves a partial contraction impossible."""


def _kissat_inner_ptr(solver: Solver) -> int:
    capsule = solver.solver.kissat
    wrapper_ptr = ctypes.pythonapi.PyCapsule_GetPointer(capsule, ctypes.pythonapi.PyCapsule_GetName(capsule))
    return int(ctypes.cast(wrapper_ptr, ctypes.POINTER(ctypes.c_void_p))[0])


def _seed_partial(problem: ContractionProblem) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = np.zeros((1 << problem.L, problem.R), dtype=np.int8)
    fixed = np.zeros((1 << problem.L, problem.R), dtype=np.int8)
    fix_count = np.zeros(1 << problem.L, dtype=np.int32)
    for point, image in problem.boundary.items():
        vertex = bit_mask(point)
        for rhs_bit, value in enumerate(image):
            value = int(value)
            if fixed[vertex, rhs_bit]:
                if values[vertex, rhs_bit] != value:
                    raise Contradiction("boundary conflict")
            else:
                values[vertex, rhs_bit] = value
                fixed[vertex, rhs_bit] = 1
                fix_count[vertex] += 1
    return values, fixed, fix_count


@njit(cache=True)
def _rule1_pair_jit(values, fixed, fix_count, L, R, alpha, left, right, diff_bits, agree_bits, agree_values):
    mask = (left ^ right) & ((1 << L) - 1)
    if mask == 0:
        return 0, False

    distance = 0
    n_diff = 0
    for bit in range(L):
        if (mask >> bit) & 1:
            distance += alpha[bit]
            diff_bits[n_diff] = bit
            n_diff += 1

    fixed_disagreement = 0
    n_agree = 0
    for rhs_bit in range(R):
        if fixed[left, rhs_bit] and fixed[right, rhs_bit]:
            if values[left, rhs_bit] != values[right, rhs_bit]:
                fixed_disagreement += 1
            else:
                agree_bits[n_agree] = rhs_bit
                agree_values[n_agree] = values[left, rhs_bit]
                n_agree += 1

    if fixed_disagreement > distance:
        return 0, True
    if distance - fixed_disagreement > 1 or n_agree == 0:
        return 0, False

    base = left & ~mask & ((1 << L) - 1)
    added = 0
    for submask in range(1 << n_diff):
        point = base
        for offset in range(n_diff):
            if (submask >> offset) & 1:
                point |= 1 << diff_bits[offset]
        if point == left or point == right:
            continue
        for index in range(n_agree):
            rhs_bit = agree_bits[index]
            if not fixed[point, rhs_bit]:
                values[point, rhs_bit] = agree_values[index]
                fixed[point, rhs_bit] = 1
                fix_count[point] += 1
                added += 1
    return added, False


@njit(cache=True)
def _edge_propagate_jit(values, fixed, fix_count, L, R, alpha):
    changes = 0
    changed = True
    loops = 0
    while changed and loops < 100:
        changed = False
        loops += 1
        for left in range(1 << L):
            for bit in range(L):
                if (left >> bit) & 1:
                    continue
                right = left | (1 << bit)
                bound = alpha[bit]
                fixed_disagreement = 0
                for rhs_bit in range(R):
                    if fixed[left, rhs_bit] and fixed[right, rhs_bit]:
                        if values[left, rhs_bit] != values[right, rhs_bit]:
                            fixed_disagreement += 1
                if fixed_disagreement > bound:
                    return -1
                if fixed_disagreement == bound:
                    for rhs_bit in range(R):
                        if fixed[left, rhs_bit] and not fixed[right, rhs_bit]:
                            values[right, rhs_bit] = values[left, rhs_bit]
                            fixed[right, rhs_bit] = 1
                            fix_count[right] += 1
                            changes += 1
                            changed = True
                        elif fixed[right, rhs_bit] and not fixed[left, rhs_bit]:
                            values[left, rhs_bit] = values[right, rhs_bit]
                            fixed[left, rhs_bit] = 1
                            fix_count[left] += 1
                            changes += 1
                            changed = True
    return changes


@njit(cache=True)
def _propagate_boundary_jit(values, fixed, fix_count, L, R, alpha, anchors):
    diff_bits = np.empty(L, dtype=np.int64)
    agree_bits = np.empty(R, dtype=np.int64)
    agree_values = np.empty(R, dtype=np.int8)
    for i in range(anchors.shape[0]):
        for j in range(i + 1, anchors.shape[0]):
            _, conflict = _rule1_pair_jit(
                values,
                fixed,
                fix_count,
                L,
                R,
                alpha,
                anchors[i],
                anchors[j],
                diff_bits,
                agree_bits,
                agree_values,
            )
            if conflict:
                return True
    return False


@njit(cache=True)
def _rule1_cross_jit(values, fixed, fix_count, L, R, alpha, new_anchors, anchors):
    changed = False
    diff_bits = np.empty(L, dtype=np.int64)
    agree_bits = np.empty(R, dtype=np.int64)
    agree_values = np.empty(R, dtype=np.int8)
    for i in range(new_anchors.shape[0]):
        left = new_anchors[i]
        for j in range(anchors.shape[0]):
            added, conflict = _rule1_pair_jit(
                values,
                fixed,
                fix_count,
                L,
                R,
                alpha,
                left,
                anchors[j],
                diff_bits,
                agree_bits,
                agree_values,
            )
            if conflict:
                return False, True
            if added:
                changed = True
    return changed, False


def _propagate(values, fixed, fix_count, problem: ContractionProblem) -> None:
    alpha = np.asarray(problem.alpha, dtype=np.int64)
    anchors = np.asarray(sorted({bit_mask(point) for point in problem.boundary}), dtype=np.int64)
    if _propagate_boundary_jit(values, fixed, fix_count, problem.L, problem.R, alpha, anchors):
        raise Contradiction("boundary propagation contradiction")
    if _edge_propagate_jit(values, fixed, fix_count, problem.L, problem.R, alpha) < 0:
        raise Contradiction("edge propagation contradiction")

    is_anchor = np.zeros(1 << problem.L, dtype=np.bool_)
    is_anchor[anchors] = True
    while anchors.shape[0] < MAX_ANCHORS:
        new_mask = (fix_count == problem.R) & ~is_anchor
        if not new_mask.any():
            break
        new_anchors = np.where(new_mask)[0].astype(np.int64)
        budget = MAX_ANCHORS - anchors.shape[0]
        if new_anchors.shape[0] > budget:
            new_anchors = new_anchors[:budget]
        changed, conflict = _rule1_cross_jit(
            values,
            fixed,
            fix_count,
            problem.L,
            problem.R,
            alpha,
            new_anchors,
            anchors,
        )
        if conflict:
            raise Contradiction("incremental propagation contradiction")
        is_anchor[new_anchors] = True
        anchors = np.concatenate([anchors, new_anchors])
        anchors.sort()
        edge_changes = _edge_propagate_jit(values, fixed, fix_count, problem.L, problem.R, alpha)
        if edge_changes < 0:
            raise Contradiction("edge propagation contradiction")
        if not changed and edge_changes == 0:
            break


def _final_var_count(top_id: int, edge_offsets: np.ndarray, k_card: np.ndarray) -> int:
    """Max SAT variable id after dispatch_card, used only to size kissat_reserve.

    dispatch_card adds ``k*(m-1)`` sequential-counter aux vars per edge with
    ``m`` diffs and bound ``k``, but only when ``0 < k < m`` (edges with k==0 or
    k>=m emit none). Mirrors the ``cur_top +=`` increments in the dispatch loop.
    """
    if k_card.shape[0] == 0:
        return int(top_id)
    m = np.diff(edge_offsets.astype(np.int64))
    k = k_card.astype(np.int64)
    aux = np.where((k > 0) & (k < m), k * (m - 1), 0).sum()
    return int(top_id) + int(aux)


def _prepare_cube(
    values,
    fixed,
    fix_count,
    problem: ContractionProblem,
) -> tuple[Solver, int, np.ndarray] | None:
    alpha = np.asarray(problem.alpha, dtype=np.int64)
    (
        var_id,
        top_id,
        xor_clauses,
        diffs_flat,
        edge_offsets,
        k_card,
        sym_clauses,
        feasible,
    ) = build_clauses(
        np.ascontiguousarray(values),
        np.ascontiguousarray(fixed),
        np.ascontiguousarray(fix_count),
        problem.L,
        problem.R,
        alpha,
    )
    if not feasible:
        return None

    solver = Solver(name=_SAT_SOLVER)
    inner_ptr = _kissat_inner_ptr(solver)
    for option, value in KISSAT_OPTIONS.items():
        _KISSAT_LIB.kissat_set_option(inner_ptr, option, value)
    if _KISSAT_RESERVE is not None:
        # Pre-size kissat's variable arrays to the final id so neither dispatch
        # pass triggers incremental growth. Pure performance hint: the emitted
        # CNF is unchanged.
        _KISSAT_RESERVE(inner_ptr, _final_var_count(top_id, edge_offsets, k_card))
    if len(xor_clauses):
        dispatch_xor_direct(inner_ptr, np.ascontiguousarray(xor_clauses), len(xor_clauses))
    dispatch_card_direct(inner_ptr, diffs_flat, edge_offsets, k_card, top_id)
    for left, right in sym_clauses:
        pysolvers.kissat404_add_cl(solver.solver.kissat, [int(left), int(right)])
    return solver, inner_ptr, var_id


def _finalize_cube(
    prep: tuple[Solver, int, np.ndarray],
    values: np.ndarray,
    fixed: np.ndarray,
) -> np.ndarray | None:
    solver, inner_ptr, var_id = prep
    try:
        if not solver.solve():
            return None
        out = values.copy()
        unfixed = fixed == 0
        model_values = np.empty(int(var_id.max()) + 1, dtype=np.int8)
        get_model_direct(inner_ptr, model_values.shape[0] - 1, model_values)
        out[unfixed] = model_values[var_id[unfixed]]
        return out
    finally:
        solver.delete()


def solve_contraction(
    problem: ContractionProblem,
) -> tuple[np.ndarray | None, dict]:
    start = time.perf_counter()
    info: dict = {"solver": _SAT_SOLVER, "solver_backend": _SAT_BACKEND}

    try:
        values, fixed, fix_count = _seed_partial(problem)
        _propagate(values, fixed, fix_count, problem)
    except Contradiction as exc:
        info.update(status="no_contraction_map", reason=str(exc), elapsed_s=round(time.perf_counter() - start, 6))
        return None, info

    info["propagate_s"] = round(time.perf_counter() - start, 6)
    info["bits_fixed_after_propagate"] = int(fixed.sum())
    info["bits_total"] = int(fixed.size)
    solve_start = time.perf_counter()
    if int(fix_count.min()) == problem.R:
        table = values.copy()
    else:
        prep = _prepare_cube(values, fixed, fix_count, problem)
        table = None if prep is None else _finalize_cube(prep, values, fixed)
    info["sat_s"] = round(time.perf_counter() - solve_start, 6)
    info["elapsed_s"] = round(time.perf_counter() - start, 6)
    if table is None:
        info.update(status="no_contraction_map", reason="unsat")
        return None, info
    return table, info
