"""Exact compact-domain authoring for the sole standard full-map proof language.

Only the complete compatible seed is searched. The standard fixed extension
defines every source-cube image; actual full-cube verification is mandatory.
This is a candidate constructor, not an additional accepted proof format.
"""

import argparse
import json
import time
from fractions import Fraction
from itertools import accumulate
from pathlib import Path

import numpy as np
from pysat.card import CardEnc, EncType
from pysat.solvers import Solver

from hec._reconstruction_extension import CompatibleRank
from hec.contraction_solver import _KISSAT_LIB, KISSAT_OPTIONS, _kissat_inner_ptr
from hec.count_proofs import compatible_vertices, geometry, inequality_id, parse_json, proof_id
from hec.proof_builders import proof_from_seed_rows
from hec.proof_store import write_proof_dataset
from hec.reconstruction_verify import ReconstructionVerifier
from hec.serialization import read_integer_rows


def intervals(p, vertices):
    """Necessary half-integer bounds from exact boundary-pair triangle excess."""
    if not p.G or sum(p.alpha) >= 1 << 40 or max(p.beta) >= 1 << 40:
        raise ValueError("boundary-interval authoring capability exceeded, not mathematical rejection")
    anchors = list(p.boundary)
    distances = np.asarray(
        [
            [sum(weight for axis, weight in enumerate(p.alpha) if (vertex ^ a) >> axis & 1) for vertex in vertices]
            for a, _ in anchors
        ],
        dtype=np.int64,
    )
    lower = np.zeros((len(vertices), p.G), dtype=np.int64)
    upper = np.tile(2 * np.asarray(p.beta, dtype=np.int64), (len(vertices), 1))
    for left, (_, a) in enumerate(anchors):
        for right in range(left, len(anchors)):
            b = anchors[right][1]
            excess = distances[left] + distances[right] - sum(abs(x - y) for x, y in zip(a, b, strict=True))
            if int(excess.min()) < 0:
                raise ValueError("boundary metric obstruction; no candidate at this context")
            low, high = np.minimum(a, b), np.maximum(a, b)
            lower = np.maximum(lower, 2 * low[None, :] - excess[:, None])
            upper = np.minimum(upper, 2 * high[None, :] + excess[:, None])
    if np.any(lower > upper):
        raise ValueError("inconsistent necessary boundary intervals")
    return lower, upper


def construct(coefficients, n=6, scale=1):
    start = time.monotonic()
    if type(scale) is not int or scale < 1:
        raise ValueError("authoring scale must be an exact positive integer")
    p = geometry(n, coefficients)
    if p.n > 6 or p.L > 25 or CompatibleRank(p).count * sum(p.beta) * scale > 1000000:
        raise ValueError("seed-authoring resource capability exceeded, not mathematical rejection")
    vertices = tuple(compatible_vertices(p))
    at = {vertex: index for index, vertex in enumerate(vertices)}
    if not p.G:
        proof = proof_from_seed_rows(p, (() for _ in vertices))
    else:
        offsets = [0, *accumulate(cap * scale for cap in p.beta)]
        width = offsets[-1]
        if len(vertices) * width > 1000000:
            raise ValueError("Finite seed-authoring resource cap; not a mathematical rejection")
        low2, high2 = intervals(p, vertices)
        lower, upper = (low2 * scale + 1) // 2, high2 * scale // 2
        if np.any(lower > upper):
            return None, {"status": "no_integral_seed_at_this_scale", "inequality_invalidity_claimed": False}
        variables = np.zeros((len(vertices), width), dtype=np.int64)
        fixed = np.zeros((len(vertices), width), dtype=np.int8)
        top, clause_count = 0, 0
        prefix = []
        for row in range(len(vertices)):
            for group, cap in enumerate(p.beta):
                previous = 0
                for threshold in range(1, cap * scale + 1):
                    column = offsets[group] + threshold - 1
                    if threshold <= lower[row, group]:
                        fixed[row, column] = 1
                    elif threshold <= upper[row, group]:
                        top += 1
                        variables[row, column] = top
                        if previous:
                            prefix.append([-top, previous])
                        previous = top
        solver = Solver(name="kissat")
        try:
            pointer = _kissat_inner_ptr(solver)
            for key, value in KISSAT_OPTIONS.items():
                _KISSAT_LIB.kissat_set_option(pointer, key, value)
            solver.append_formula(prefix)
            clause_count += len(prefix)
            edge_count = 0
            for row, vertex in enumerate(vertices):
                for axis, weight in enumerate(p.alpha):
                    other_vertex = vertex | 1 << axis
                    if vertex >> axis & 1 or other_vertex not in at:
                        continue
                    other = at[other_vertex]
                    edge_count += 1
                    budget, singles, pairs = scale * weight, [], []
                    for column in range(width):
                        a, b = int(variables[row, column]), int(variables[other, column])
                        if a and b:
                            pairs.append((a, b))
                        elif a:
                            singles.append(-a if fixed[other, column] else a)
                        elif b:
                            singles.append(-b if fixed[row, column] else b)
                        elif fixed[row, column] != fixed[other, column]:
                            budget -= 1
                    if budget < 0:
                        return None, {
                            "status": "inconsistent_integral_seed_bounds",
                            "inequality_invalidity_claimed": False,
                        }
                    if len(singles) + len(pairs) <= budget:
                        continue
                    clauses = []
                    for a, b in pairs:
                        top += 1
                        z = top
                        clauses.extend([[a, b, -z], [-a, -b, -z], [a, -b, z], [-a, b, z]])
                        singles.append(z)
                    if budget == 0:
                        clauses.extend([[-literal] for literal in singles])
                    else:
                        encoding = CardEnc.atmost(singles, bound=budget, top_id=top, encoding=EncType.seqcounter)
                        clauses.extend(encoding.clauses)
                        top = encoding.nv
                    solver.append_formula(clauses)
                    clause_count += len(clauses)
            print(
                json.dumps(
                    {
                        "event": "compatible-seed-sat",
                        "inequality_id": inequality_id(p),
                        "L": p.L,
                        "seed_vertices": len(vertices),
                        "seed_edges": edge_count,
                        "scale": scale,
                        "variables": top,
                        "clauses": clause_count,
                    }
                ),
                flush=True,
            )
            if not solver.solve():
                return None, {"status": "no_seed_at_this_scale", "inequality_invalidity_claimed": False}
            model = {literal for literal in (solver.get_model() or []) if literal > 0}
            bits = fixed.copy()
            for row in range(len(vertices)):
                for column in range(width):
                    if variables[row, column]:
                        bits[row, column] = int(int(variables[row, column]) in model)
            counts = [
                tuple(int(bits[row, offsets[g] : offsets[g + 1]].sum()) for g in range(p.G))
                for row in range(len(vertices))
            ]
        finally:
            solver.delete()
        if not all(counts[at[v]] == tuple(scale * value for value in values) for v, values in p.boundary):
            raise ValueError("SAT proposal violates exact occurrence anchors")
        if not all(0 <= value <= scale * p.beta[g] for values in counts for g, value in enumerate(values)):
            raise ValueError("SAT proposal violates exact count bounds")
        if not all(
            sum(abs(a - b) for a, b in zip(counts[row], counts[at[v | 1 << axis]], strict=True)) <= scale * weight
            for row, v in enumerate(vertices)
            for axis, weight in enumerate(p.alpha)
            if not v >> axis & 1 and v | 1 << axis in at
        ):
            raise ValueError("SAT proposal violates an exact compatible edge")
        proof = proof_from_seed_rows(p, (tuple(Fraction(value, scale) for value in row) for row in counts))
    verifier = ReconstructionVerifier()
    try:
        audit = verifier.verify(proof)
    finally:
        verifier.close()
    if (
        audit.get("ok") is not True
        or audit.get("scope") != "original-cube-all-edges"
        or audit.get("checked_vertices") != p.vertices
        or audit.get("checked_edges") != p.L * (p.vertices // 2)
    ):
        raise ValueError("Actual complete original-cube verification is required")
    return proof, {
        "status": "proved",
        "proof_id": proof_id(proof),
        "inequality_id": inequality_id(p),
        "method": "exact compatible-domain prefix SAT; same Kissat settings; standard fixed extension",
        "scale": scale,
        "audit": audit,
        "elapsed_s": time.monotonic() - start,
        "floating_point_acceptance": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rows", type=Path, required=True, help="Exact integer coefficient rows in repository row order"
    )
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--case-index", type=Path, help="Optional hec-proof-authoring-case-index/1 subset")
    parser.add_argument("--output", type=Path, required=True, help="New standard dataset directory; never overwritten")
    parser.add_argument("--scale", type=int, default=1)
    args = parser.parse_args(argv)
    rows = read_integer_rows(args.rows, n=args.n)
    if args.case_index is not None:
        index = parse_json(args.case_index.read_bytes())
        if (
            not isinstance(index, dict)
            or index.get("format") != "hec-proof-authoring-case-index/1"
            or type(index.get("n")) is not int
            or index["n"] != args.n
        ):
            raise ValueError("authoring subset differs from the requested party frame")
        wanted = index["inequality_ids"]
        if (
            not isinstance(wanted, list)
            or any(not isinstance(key, str) for key in wanted)
            or len(set(wanted)) != len(wanted)
        ):
            raise ValueError("authoring subset must contain unique inequality identities")
        selected = {inequality_id(geometry(args.n, row)): row for row in rows}
        if not set(wanted) <= selected.keys():
            raise ValueError("requested authoring identity has no exact input coefficient row")
        rows = [selected[key] for key in wanted]

    def definitions():
        for row in rows:
            proof, result = construct(row, n=args.n, scale=args.scale)
            if proof is None:
                raise ValueError(f"No candidate constructed at this scale: {result}; no invalidity claim")
            print(json.dumps(result), flush=True)
            yield proof

    print(json.dumps(write_proof_dataset(args.output, definitions())), flush=True)


if __name__ == "__main__":
    main()
