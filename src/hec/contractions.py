"""Contraction search, authoring and exhaustive verification in one proof language."""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .bits import BitPoint, bit_tuple, d_alpha, d_hamming
from .count_proofs import compatible_vertices, geometry, proof_geometry
from .proof_builders import proof_from_boolean_table, proof_from_seed_rows
from .reconstruction_verify import ReconstructionVerifier
from .serialization import json_path


@dataclass(frozen=True)
class ContractionProblem:
    coeffs: tuple[int, ...]
    n: int
    lhs_sets: list[frozenset[int]]
    alpha: list[int]
    rhs_sets: list[frozenset[int]]
    beta: list[int]
    boundary: dict[BitPoint, BitPoint]
    L: int
    R: int


def _exact_coefficients(coeffs):
    if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) for value in coeffs):
        raise ValueError("inequality coefficients must be exact integers, never floats or booleans")
    return tuple(int(value) for value in coeffs)


def _build_problem(coeffs: Sequence[int], n: int) -> tuple[ContractionProblem | None, dict]:
    p = geometry(n, _exact_coefficients(coeffs))
    info = {"n": n, "L": p.L, "R": sum(p.beta), "lhs_terms": p.L, "rhs_terms": p.G, "alpha_sum": sum(p.alpha)}
    if not p.G:
        return None, {**info, "status": "proved", "reason": "empty_rhs"}
    boundary = {}
    for vertex, counts in p.boundary:
        image = tuple(int(value > 0) for value, cap in zip(counts, p.beta, strict=True) for _ in range(cap))
        boundary[bit_tuple(vertex, p.L)] = image
    for index, (left, image) in enumerate(boundary.items()):
        for right, other in list(boundary.items())[index + 1 :]:
            if d_hamming(image, other) > d_alpha(left, right, p.alpha):
                return None, {**info, "status": "infeasible", "reason": "boundary_pairwise_violation"}

    def supports(values):
        return [frozenset(i for i in range(n) if value >> i & 1) for value in values]

    return ContractionProblem(
        p.coefficients,
        n,
        supports(p.lhs),
        list(p.alpha),
        supports(p.rhs),
        list(p.beta),
        boundary,
        p.L,
        sum(p.beta),
    ), info


def construct_contraction(coeffs: Sequence[int], n: int, *, scale: int = 1) -> dict:
    """Construct the current standard from a compatible seed and audit once.

    Search only the compatible domain. The sole fixed extension defines every
    original-cube image; resource limits and fixed-scale failures confer no
    inequality-invalidity or facethood claim. Solver imports remain lazy.
    """
    from .authoring import construct

    proof, result = construct(_exact_coefficients(coeffs), n, scale)
    return result if proof is None else {**result, "proof": proof}


def find_contraction(coeffs: Sequence[int], n: int) -> dict:
    """Search and return a standard proof only after exhaustive exact verification.

    The solver's Boolean array is ephemeral. No images/lhs/rhs artifact is
    returned or accepted. Grouping and fixed extension may change that array;
    the returned full map receives its own independent exact cube audit.
    """
    start = time.perf_counter()
    coeffs = _exact_coefficients(coeffs)
    problem, info = _build_problem(coeffs, n)
    p = geometry(n, coeffs)
    if problem is None:
        if info["status"] != "proved":
            return {**info, "elapsed_s": time.perf_counter() - start}
        proof = proof_from_seed_rows(p, (() for _ in compatible_vertices(p)))
    else:
        from .contraction_solver import solve_contraction

        table, solver_info = solve_contraction(problem)
        if table is None:
            return {**info, **solver_info, "elapsed_s": time.perf_counter() - start}
        proof = proof_from_boolean_table(p, table)
    verifier = ReconstructionVerifier()
    try:
        audit = verifier.verify(proof)
    finally:
        verifier.close()
    return {"status": "proved", "proof": proof, "audit": audit, "elapsed_s": time.perf_counter() - start}


def check_contraction(coeffs: Sequence[int] | None, n: int | None, proof: dict) -> dict:
    """Audit only the standard definition, optionally requiring an exact context."""
    try:
        problem = proof_geometry(proof)
        if n is not None and (type(n) is not int or n != problem.n):
            raise ValueError("requested party frame differs from the proof")
        if coeffs is not None and _exact_coefficients(coeffs) != problem.coefficients:
            raise ValueError("requested coefficients differ from the proof")
        verifier = ReconstructionVerifier()
        try:
            return {**verifier.verify(proof), "errors": []}
        finally:
            verifier.close()
    except (TypeError, ValueError) as exc:
        return {"ok": False, "errors": [str(exc)]}


def read_contractions(path: str | Path):
    """Read only the canonical standard proof catalogue."""
    from .proof_store import ProofCatalog

    return ProofCatalog(json_path(path, "proof catalog"))


def write_contractions(path: str | Path, proofs: Iterable[dict]) -> None:
    """Independently verify and publish an immutable standard catalogue."""
    from .proof_store import write_proof_catalog

    write_proof_catalog(path, proofs)
