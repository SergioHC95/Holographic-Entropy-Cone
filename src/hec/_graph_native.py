"""Fresh sparse SCIP construction through its public constraint API.

The numerical model and all check/enforce flags are unchanged. Batching avoids
temporary Python expression objects; no SCIP model, variable, solution, or
search state is cached. Function addresses are runtime arguments to the JIT,
never machine addresses embedded in a disk cache. Only immutable names and the
loaded library binding are memoized.
"""

from __future__ import annotations

import ctypes as C
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyscipopt
import pyscipopt.scip
from numba import njit


@lru_cache(maxsize=1)
def native_functions():
    """Bind the same loaded SCIP library as PySCIPOpt, using public C signatures.

    Object pointers are opaque here; the arrays retain their exact native
    pointer/double dtypes. SCIPcreateConsBasicLinear uses the same default flags
    as addCons/createConsFromExpr. A created constraint is captured, added to its
    owner, and released exactly once, matching PySCIPOpt's construction sequence.
    """
    library = C.CDLL(pyscipopt.scip.__file__)
    pointer = C.c_void_p
    definitions = (
        ("SCIPcreateConsBasicLinear", [pointer] * 3 + [C.c_int] + [pointer] * 2 + [C.c_double] * 2),
        ("SCIPcreateConsDisjunction", [pointer] * 3 + [C.c_int] + [pointer] * 2 + [C.c_int] * 6),
        ("SCIPaddConsElemDisjunction", [pointer] * 3),
        ("SCIPaddCons", [pointer] * 2),
        ("SCIPreleaseCons", [pointer] * 2),
    )
    functions = tuple(
        C.CFUNCTYPE(C.c_int, *arguments)(C.cast(getattr(library, name), pointer).value)
        for name, arguments in definitions
    )
    capsule = C.pythonapi.PyCapsule_GetPointer
    capsule.argtypes = [C.py_object, C.c_char_p]
    capsule.restype = pointer
    return library, functions, capsule


@lru_cache(maxsize=64)
def constraint_names(rows, groups):
    labels = (
        np.asarray(
            [("c" + str(i + 1)).encode() for i in range(rows)]
            + [("attaining_cut_" + str(i)).encode() for i in range(groups)],
            dtype="S32",
        )
        .view(np.uint8)
        .reshape(-1, 32)
    )
    labels.setflags(write=False)
    return labels


@njit(cache=True)
def construct_constraints(
    scip,
    variables,
    indptr,
    indices,
    data,
    rhs,
    group_offsets,
    or_rows,
    or_rhs,
    labels,
    infinity,
    create_linear,
    create_disjunction,
    add_element,
    add_cons,
    release,
):
    width = len(variables)
    pointer_buffer = np.empty(width, dtype=np.uintp)
    coefficient_buffer = np.empty(width, dtype=np.float64)
    child = np.zeros(1, dtype=np.uintp)
    parent = np.zeros(1, dtype=np.uintp)
    for row in range(len(rhs)):
        count = 0
        for p in range(indptr[row], indptr[row + 1]):
            pointer_buffer[count] = variables[indices[p]]
            coefficient_buffer[count] = data[p]
            count += 1
        code = create_linear(
            scip,
            child.ctypes,
            labels[row].ctypes,
            count,
            pointer_buffer.ctypes,
            coefficient_buffer.ctypes,
            -infinity,
            rhs[row],
        )
        if code != 1:
            return code, 0, row
        code = add_cons(scip, child[0])
        clean = release(scip, child.ctypes)
        if code != 1:
            return code, 1, row
        if clean != 1:
            return clean, 2, row
    for group in range(len(group_offsets) - 1):
        label = labels[len(rhs) + group]
        code = create_disjunction(scip, parent.ctypes, label.ctypes, 0, child.ctypes, 0, 1, 1, 1, 0, 0, 0)
        if code != 1:
            return code, 3, group
        for row in range(group_offsets[group], group_offsets[group + 1]):
            count = 0
            for column in range(width):
                value = or_rows[row, column]
                if value:
                    pointer_buffer[count] = variables[column]
                    coefficient_buffer[count] = value
                    count += 1
            code = create_linear(
                scip,
                child.ctypes,
                label.ctypes,
                count,
                pointer_buffer.ctypes,
                coefficient_buffer.ctypes,
                -infinity,
                or_rhs[row],
            )
            if code != 1:
                release(scip, parent.ctypes)
                return code, 4, row
            code = add_element(scip, parent[0], child[0])
            clean = release(scip, child.ctypes)
            if code != 1 or clean != 1:
                release(scip, parent.ctypes)
                failure = code if code != 1 else clean
                return failure, 5, row
        code = add_cons(scip, parent[0])
        clean = release(scip, parent.ctypes)
        if code != 1:
            return code, 6, group
        if clean != 1:
            return clean, 7, group
    return 1, -1, -1


def build_constraints(scip, model, variables):
    """Build all rows into a fresh original-stage model; fail closed on any error."""
    if scip.getMajorVersion() != 10:
        raise RuntimeError("unvalidated SCIP constraint ABI")
    if np.dtype(np.uintp).itemsize != C.sizeof(C.c_void_p) or C.sizeof(C.c_double) != 8:
        raise RuntimeError("unsupported native pointer/double representation")
    if int(scip.getStage()) != int(pyscipopt.SCIP_STAGE.PROBLEM) or scip.getNSols() != 0:
        raise RuntimeError("constraint compiler requires a fresh, unsolved model")
    width = len(variables)
    if scip.getNConss(transformed=False) != 0 or len(scip.getVars(transformed=False)) != width:
        raise RuntimeError("constraint compiler received nonempty or mismatched native state")
    indptr = np.ascontiguousarray(model.matrix.indptr)
    indices = np.ascontiguousarray(model.matrix.indices)
    data = np.ascontiguousarray(model.matrix.data, dtype=np.float64)
    rhs = np.ascontiguousarray(model.rhs, dtype=np.float64)
    if (
        model.matrix.shape[1] != width
        or len(indptr) != len(rhs) + 1
        or indptr[0] != 0
        or indptr[-1] != len(indices)
        or len(indices) != len(data)
        or np.any(indptr[1:] < indptr[:-1])
        or np.any(indices < 0)
        or np.any(indices >= width)
        or not np.all(np.isfinite(data))
        or not np.all(np.isfinite(rhs))
    ):
        raise ValueError("invalid sparse model at the native construction boundary")
    offsets = np.cumsum([0] + [len(group) for group in model.disjunctions], dtype=np.int64)
    choices = [(row, bound) for group in model.disjunctions for row, bound in group]
    coefficients = np.asarray([row for row, _ in choices], dtype=np.float64).reshape(-1, width)
    right = np.asarray([bound for _, bound in choices], dtype=np.float64)
    if not np.all(np.isfinite(coefficients)) or not np.all(np.isfinite(right)):
        raise ValueError("non-finite disjunction at the native construction boundary")
    library, functions, capsule = native_functions()
    pointer = capsule(scip.to_ptr(False), b"scip")
    pointers = np.asarray([variable.ptr() for variable in variables], dtype=np.uintp)
    if not pointer or np.any(pointers == 0) or len(np.unique(pointers)) != width:
        raise RuntimeError("invalid native model/variable identity")
    result = construct_constraints(
        pointer,
        pointers,
        indptr,
        indices,
        data,
        rhs,
        offsets,
        coefficients,
        right,
        constraint_names(len(rhs), len(model.disjunctions)),
        scip.infinity(),
        *functions,
    )
    if result[0] != 1:
        raise RuntimeError(f"native constraint construction failed: {result}")
    expected = len(rhs) + len(model.disjunctions)
    if scip.getNConss(transformed=False) != expected or scip.getNSols() != 0:
        raise RuntimeError("native constraint inventory or fresh-state check failed")
    return {
        "policy": "fresh_batched_scip_constraints",
        "linear_rows": len(rhs),
        "disjunctions": len(model.disjunctions),
        "disjunctive_rows": len(choices),
        "native_constraints": expected,
        "variables": width,
        "all_original_constraints_retained": True,
        "native_state_reused": False,
        "solutions_before_solve": 0,
        "api_library": str(Path(pyscipopt.scip.__file__).resolve()),
        "scip_major": scip.getMajorVersion(),
    }
