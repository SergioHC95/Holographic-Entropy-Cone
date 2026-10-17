"""Complete selector-free realization of pairwise-independent seven-terminal targets.

Contract disjoint inclusion-minimal singleton cuts to terminals without adding
vertices or changing entropies. Zero pair mutual information forces every
terminal-terminal edge to vanish. With three or four bulk vertices, eliminating
one terminal capacity per degree leaves 17 or 27 continuous parameters.
Zero-weight padding covers every smaller realization.

For additive T, every bulk side U obeys D(U)+C(U)>=2*a(T,U)>=2*a(S,U)
for S contained in T. Keeping all maximal additive sets therefore implies
every omitted lower bound. Every nonadditive split must attain its entropy on
a proper bulk side: a native linear disjunction needs no selectors.

Graph acceptance remains independent and exact. Exclusion requires completed
native infeasibility, never a limit. Other sizes retain the general solver.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from itertools import combinations
from typing import Any

import numpy as np
from scipy import sparse

from ._graph_milp import (
    SCIP_INDICATOR_OPTIONS,
    _exact_graph_quality,
    _frozen_milp_sha256,
    _integer_graph,
    _json_fraction,
    _solve_highspy_milp,
)
from ._graph_validation import (
    canonical_primitive_ray_graph,
    exact_entropy_match,
    graph_total_vertices,
    lift_graph_total_vertices,
    prune_entropy_irrelevant_components,
)
from .coordinates import subsets

EPR_BACKEND = "scip-disjunction"


@dataclass(frozen=True)
class EprModel:
    target: tuple[int, ...]
    degrees: tuple[int, ...]
    matrix: Any
    rhs: np.ndarray
    upper: np.ndarray
    disjunctions: tuple[tuple[tuple[tuple[int, ...], int], ...], ...]
    profile: dict[str, Any]
    sha256: str
    bulk_count: int = 3


@lru_cache(maxsize=2)
def _epr_geometry(bulk_count: int = 3) -> tuple[tuple[int, ...], np.ndarray]:
    if bulk_count not in (3, 4):
        raise ValueError("the exact small-bulk specialization supports three or four bulk vertices")
    stride = bulk_count - 1
    full = (1 << bulk_count) - 1
    width = 7 * stride + math.comb(bulk_count, 2)
    boundary = tuple(sum(1 << vertex for vertex in sub) for sub in subsets(6))
    rows = np.zeros((63, full - 1, width), dtype=np.int16)
    for index, mask in enumerate(boundary):
        for offset, bulk in enumerate(range(1, full)):
            bits = tuple((bulk >> bit) & 1 for bit in range(bulk_count))
            for terminal in range(7):
                sign = -1 if mask & (1 << terminal) else 1
                for bit in range(stride):
                    rows[index, offset, stride * terminal + bit] = sign * (bits[bit] - bits[-1])
            for column, (left, right) in enumerate(combinations(range(bulk_count), 2), 7 * stride):
                rows[index, offset, column] = bits[left] != bits[right]
    rows.flags.writeable = False
    return boundary, rows


def _build_epr_model(target: tuple[int, ...], bulk_count: int = 3) -> EprModel | None:
    """None means not applicable, not an infeasibility verdict."""
    if bulk_count not in (3, 4) or len(target) != 63 or any(value < 0 for value in target) or not any(target):
        return None
    divisor = math.gcd(*target)
    target = tuple(value // divisor for value in target)
    # Keep every transported integer and intermediate RHS exactly
    # representable. Larger targets use the general formulation.
    if max(target) >= 1 << 45:
        return None
    stride = bulk_count - 1
    full = (1 << bulk_count) - 1
    width = 7 * stride + math.comb(bulk_count, 2)
    boundary, coefficients = _epr_geometry(bulk_count)
    index = {mask: i for i, mask in enumerate(boundary)}
    values = dict(zip(boundary, target, strict=True))
    values[0] = 0

    def entropy(mask: int) -> int:
        return values[mask ^ 127 if mask & 64 else mask]

    degrees = tuple(entropy(1 << terminal) for terminal in range(7))
    if any(entropy((1 << a) | (1 << b)) != degrees[a] + degrees[b] for a, b in combinations(range(7), 2)):
        return None
    total = sum(degrees)
    additive = [
        mask
        for mask in range(1, 127)
        if entropy(mask) == sum(value for terminal, value in enumerate(degrees) if mask & (1 << terminal))
    ]
    maximal = [mask for mask in additive if not any(mask != other and mask & other == mask for other in additive)]
    retained = {index[mask ^ 127 if mask & 64 else mask] for mask in maximal}
    # Clipping any bulk edge above max entropy to that value preserves all
    # old minima: it crossed no old minimum, and every changed cut still
    # contains an edge at least as large as its target entropy.
    upper = np.asarray(
        [degrees[column // stride] for column in range(7 * stride)] + [max(target)] * math.comb(bulk_count, 2),
        dtype=float,
    )
    rows, rhs, disjunctions = [], [], []
    for terminal in range(7):
        row = np.zeros(width)
        row[stride * terminal : stride * (terminal + 1)] = 1
        rows.append(row)
        rhs.append(degrees[terminal])
    lower_subsystems = 0
    for sub, mask in enumerate(boundary):
        degree_sum = sum(degrees[terminal] for terminal in range(6) if mask & (1 << terminal))
        h = target[sub]
        if h > min(degree_sum, total - degree_sum):
            return None
        endpoint = h == degree_sum or h == total - degree_sum
        retain = not endpoint or sub in retained
        lower_subsystems += retain
        choices = []
        for bulk in range(1, full):
            constant = degree_sum if not bulk & (1 << stride) else total - degree_sum
            row = tuple(map(int, coefficients[sub, bulk - 1]))
            if retain:
                rows.append(-coefficients[sub, bulk - 1].astype(float))
                rhs.append(constant - h)
            if not endpoint:
                choices.append((row, h - constant))
        if choices:
            disjunctions.append(tuple(choices))
    # Relabel bulk columns so their total terminal capacities descend.
    for left, right in zip(range(stride), range(1, bulk_count), strict=True):
        row = np.zeros(width)
        constant = 0
        for terminal in range(7):
            for bulk, sign in [(right, 1), (left, -1)]:
                if bulk < stride:
                    row[stride * terminal + bulk] += sign
                else:
                    constant += sign * degrees[terminal]
                    row[stride * terminal : stride * (terminal + 1)] -= sign
        rows.append(row)
        rhs.append(-constant)
    matrix = sparse.csr_matrix(np.asarray(rows))
    bound = np.asarray(rhs, dtype=float)
    linear_hash = _frozen_milp_sha256(
        np.zeros(width),
        matrix,
        np.full(len(rhs), -np.inf),
        bound,
        np.zeros(width),
        upper,
        np.zeros(width, dtype=np.int32),
    )
    packed = json.dumps({"linear_model": linear_hash, "disjunctions": disjunctions}, separators=(",", ":")).encode()
    digest = hashlib.sha256(packed).hexdigest()
    profile = {
        "continuous_parameters": width,
        "bulk_vertices": bulk_count,
        "total_vertices": 7 + bulk_count,
        "binary_vars": 0,
        "cut_selectors": 0,
        "ineq_rows": len(rhs),
        "disjunctions": len(disjunctions),
        "retained_lower_subsystems": lower_subsystems,
        "maximal_additive_sets": len(maximal),
        "constraint_model_sha256": digest,
        "cut_encoding": "linear_disjunction",
    }
    return EprModel(target, degrees, matrix, bound, upper, tuple(disjunctions), profile, digest, bulk_count)


def _trusted_epr_infeasibility(info: dict[str, Any], *, incumbent_returned: bool) -> bool:
    return bool(
        info.get("backend") == EPR_BACKEND
        and info.get("status_raw") == "infeasible"
        and isinstance(info.get("stage"), int)
        and isinstance(info.get("stage_solved_code"), int)
        and info.get("stage") == info.get("stage_solved_code")
        and info.get("solutions") == 0
        and not incumbent_returned
        and len(str(info.get("base_model_sha256", ""))) == 64
        and (
            info.get("branching") is None
            or isinstance(info["branching"], dict)
            and info["branching"].get("covers_complete") is True
        )
    )


def _solve_epr_native(model: EprModel) -> tuple[np.ndarray | None, dict[str, Any]]:
    import pyscipopt

    scip = pyscipopt.Model("hec-pairwise-independent-cut-disjunctions")
    try:
        scip.hideOutput(True)
        scip.setEmphasis(pyscipopt.SCIP_PARAMEMPHASIS.EASYCIP, quiet=True)
        for name, value in SCIP_INDICATOR_OPTIONS.items():
            scip.setParam(name, value)
        scip.setParam("limits/solutions", 1)
        limits = {name: scip.getParam(name) for name in ("limits/time", "limits/nodes", "limits/memory")}
        if limits["limits/time"] < 1e20 or limits["limits/nodes"] != -1:
            raise RuntimeError("unlimited specialization acquired an unexpected resource limit")
        variables = [
            scip.addVar(name=f"w{column}", lb=0, ub=float(model.upper[column]), vtype="C")
            for column in range(len(model.upper))
        ]
        for row in range(model.matrix.shape[0]):
            first, last = model.matrix.indptr[row : row + 2]
            expression = pyscipopt.quicksum(
                float(value) * variables[int(column)]
                for column, value in zip(model.matrix.indices[first:last], model.matrix.data[first:last], strict=True)
            )
            scip.addCons(expression <= float(model.rhs[row]))
        for ordinal, choices in enumerate(model.disjunctions):
            expressions = [
                pyscipopt.quicksum(value * variables[column] for column, value in enumerate(row) if value) <= bound
                for row, bound in choices
            ]
            scip.addConsDisjunction(expressions, name=f"attaining_cut_{ordinal}")
        brancher = None
        if model.bulk_count == 4:
            from ._graph_cut_domains import install_cut_domain_branching

            brancher = install_cut_domain_branching(scip, model, variables)
        started = time.perf_counter()
        scip.optimize()
        best = scip.getBestSol()
        solution = None if best is None else np.asarray([scip.getSolVal(best, variable) for variable in variables])
        info = {
            "backend": EPR_BACKEND,
            "base_model_sha256": model.sha256,
            "emphasis": "EASYCIP",
            "status_raw": str(scip.getStatus()),
            "stage": int(scip.getStage()),
            "stage_solved_code": int(pyscipopt.SCIP_STAGE.SOLVED),
            "solutions": int(scip.getNSols()),
            "nodes": int(scip.getNNodes()),
            "solve_s": time.perf_counter() - started,
            "resource_limits": limits,
            "effective_time_limit_s": None,
            "scip_version": f"{scip.getMajorVersion()}.{scip.getMinorVersion()}.{scip.getTechVersion()}",
            "pyscipopt_version": pyscipopt.__version__,
        }
        if brancher is not None:
            info["branching"] = brancher.record()
        trusted = _trusted_epr_infeasibility(info, incumbent_returned=solution is not None)
        info.update(status="realized" if solution is not None else "infeasible" if trusted else "unknown")
        info["trusted_infeasibility"] = trusted
        return solution, info
    finally:
        # A custom handler and its Model hold strong references to each other.
        # freeProb() leaves that plugin cycle alive until cyclic GC happens;
        # free() tears SCIP down safely and then clears plugin references.
        scip.free()


def _epr_graph(solution: np.ndarray, model: EprModel) -> dict[str, Any]:
    labels = tuple("ABCDEF") + ("O",)
    stride = model.bulk_count - 1
    edges, weights = [], []
    for terminal in range(7):
        direct = list(solution[stride * terminal : stride * (terminal + 1)])
        values = direct + [model.degrees[terminal] - sum(direct)]
        for bulk, value in enumerate(values, 1):
            edges.append([labels[terminal], f"x{bulk}"])
            weights.append(float(value))
    for column, (left, right) in enumerate(combinations(range(model.bulk_count), 2), 7 * stride):
        edges.append([f"x{left + 1}", f"x{right + 1}"])
        weights.append(float(solution[column]))
    graph = prune_entropy_irrelevant_components(_integer_graph(edges, weights), 6)
    bulk_vertices = sorted({vertex for edge in graph["edges"] for vertex in edge if vertex.startswith("x")})
    rename = {vertex: f"x{index + 1}" for index, vertex in enumerate(bulk_vertices)}
    graph["edges"] = [[rename.get(left, left), rename.get(right, right)] for left, right in graph["edges"]]
    return canonical_primitive_ray_graph(graph, 6)


def solve_epr_free(
    target: tuple[int, ...], *, total_vertices: int = 10
) -> tuple[dict[str, Any] | None, dict[str, Any]] | None:
    started = time.perf_counter()
    model = _build_epr_model(target, total_vertices - 7)
    if model is None:
        return None
    from ._graph_pair import pair_cut_disjunctions

    model = pair_cut_disjunctions(model)
    profile = {**model.profile, "build_s": time.perf_counter() - started}
    try:
        solution, attempt = _solve_epr_native(model)
    except Exception as exc:
        return None, {"status": "unknown", "reason": "reduced_backend_error", "error": str(exc)}
    if solution is None:
        return None, {"status": attempt["status"], "profile": profile, "attempts": [attempt], "backend": EPR_BACKEND}
    exact_target = tuple(Fraction(value) for value in target)
    candidates = {}
    rejected = {}

    def accept(name: str, point: np.ndarray) -> None:
        try:
            graph = _epr_graph(point, model)
            prelift = graph_total_vertices(graph, 6)
            graph = lift_graph_total_vertices(graph, 6, total_vertices)
            checked = exact_entropy_match(graph, exact_target, 6, "ray")
        except (ArithmeticError, IndexError, TypeError, ValueError) as exc:
            rejected[name] = str(exc)
            return
        if checked["ok"]:
            quality, record = _exact_graph_quality(graph, exact_target, checked)
            candidates[name] = (quality, record, graph, checked, prelift)

    accept("scip-incumbent", solution)
    cell_rows, cell_rhs = [], []
    for choices in model.disjunctions:
        row, bound = min(choices, key=lambda item: float(np.asarray(item[0]) @ solution - item[1]))
        cell_rows.append(row)
        cell_rhs.append(bound)
    cell_a = sparse.vstack(
        [model.matrix, sparse.csr_matrix(np.asarray(cell_rows).reshape(len(cell_rows), len(model.upper)))], format="csr"
    )
    rhs = np.concatenate([model.rhs, np.asarray(cell_rhs)])
    objective = np.zeros(len(model.upper))
    objective[7 * (model.bulk_count - 1) :] = 1
    try:
        refined, _ = _solve_highspy_milp(
            objective,
            cell_a,
            np.full(len(rhs), -np.inf),
            rhs,
            sparse.csr_matrix((0, len(model.upper))),
            np.empty(0),
            np.zeros(len(model.upper), dtype=np.int32),
            np.zeros(len(model.upper)),
            model.upper,
            node_limit=None,
            time_limit_s=None,
        )
        if refined is not None:
            accept("refined", refined)
    except (ArithmeticError, RuntimeError, TypeError, ValueError):
        pass
    if not candidates:
        return None, {
            "status": "unknown",
            "reason": "exact_reduced_candidate_rejected",
            "attempts": [attempt],
            "candidate_errors": rejected,
        }
    selected = min(candidates, key=lambda name: candidates[name][0])
    _, quality, graph, checked, prelift = candidates[selected]
    pivot = next(index for index, value in enumerate(target) if value)
    scale = Fraction(target[pivot]) / Fraction(checked["entropy"][pivot])
    attempt["refinement"] = {
        "status": "refined" if selected == "refined" else "retained",
        "exact_graph_validation": "accepted",
        "selected_solution": selected,
        "candidate_quality": {name: value[1] for name, value in candidates.items()},
        "candidate_validity": {name: True for name in candidates},
    }
    return graph, {
        "status": "realized",
        "backend": EPR_BACKEND,
        "profile": profile,
        "attempts": [attempt],
        "quality": quality,
        "weight_scale": _json_fraction(scale),
        "prelift_total_vertices": prelift,
    }
