"""Opt-in speed experiments; no live controller imports this module.

Losing descriptions are NOT proofs and need no acceptance replay. The chosen
description must still reconstruct every exact seed value, then receive the
unchanged independent full-cube audit and subsequent separate fresh audit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from derivation_pilot import recipes

from hec.count_proofs import canonical_json, compatible_vertices, parse_json

from . import run as derivations
from .diagrams import build


def cut_rows(document):
    """Exact bulk evaluation of a validated integer cut program on COMPLETE C.

    Python integers hold bitsets; uint64 accumulators cannot overflow because
    each coordinate sums exactly beta_g Boolean layers and beta_g is bounded
    here. No floats, interpolation, samples or omitted compatible vertices.
    This evaluates a function; it does NOT establish contraction.
    """
    program = recipes.CutFunction(document)  # All existing strict syntax checks.
    p = program.problem
    if p.L > 63 or any(cap >= 1 << 64 for cap in p.beta):
        raise ValueError("bulk exact cut evaluation exceeds its integer capability")
    vertices = list(compatible_vertices(p))
    count = len(vertices)
    if count * p.G > 16_000_000:
        raise ValueError("bulk exact cut matrix exceeds the bounded experiment")
    values = np.asarray(vertices, dtype=np.uint64)
    universe, literals = (1 << count) - 1, []
    for axis in range(p.L):
        positive = int.from_bytes(
            np.packbits(((values >> axis) & 1).astype(np.uint8), bitorder="little").tobytes(), "little"
        )
        literals.append((universe ^ positive, positive))
    hits = []
    for ones, zeros in program.terms:
        covered, mask = universe, ones | zeros
        while mask and covered:
            bit = mask & -mask
            covered &= literals[bit.bit_length() - 1][int(bool(ones & bit))]
            mask ^= bit
        hits.append(covered)
    matrix = np.zeros((count, p.G), dtype=np.uint64)
    width = (count + 7) // 8
    for group, layers in enumerate(program.groups):
        for layer in layers:
            covered = 0
            for ref in layer:
                covered |= hits[ref]
            packed = np.frombuffer(covered.to_bytes(width, "little"), dtype=np.uint8)
            matrix[:, group] += np.unpackbits(packed, bitorder="little")[:count].astype(np.uint64)
    return p, vertices, 1, [tuple(row) for row in matrix.tolist()]


def reconstruct(document):
    if document.get("format") == recipes.FORMAT and document.get("function", {}).get("kind") == recipes.CUTS:
        return cut_rows(document)
    return derivations.reconstruct(document)


@dataclass(frozen=True)
class SelectedEncoding:
    winner: str
    raw: bytes
    methods: dict
    decoded: tuple | None


def choose_definition(problem, vertices, scale, rows, *, closure=None, source_json_bytes=None):
    """Construct/rank identical candidates, replay only a potentially retained winner.

    An uncompetitive candidate needs no decode at all. A selected winner is
    decoded from its serialized bytes and compared with every intended count.
    Callers must pass those actual decoded values to independent acceptance;
    no loser, cached source rows, or stored validity receipt can substitute.
    """
    choices, methods = {}, {}

    def add(name, document):
        choices[name] = canonical_json(document)
        methods[name] = {"status": "encoded_not_replayed_not_accepted", "json_bytes": len(choices[name])}

    add("explicit-compatible-seed", derivations.standard(problem, scale, rows))
    add("shared-compatible-dag", build(problem, vertices, scale, rows))
    eligible = scale == 1 and problem.L <= 17 and sum(problem.beta) <= 63 and max(problem.alpha, default=0) <= 32
    if eligible and closure is not None:
        result = recipes.closure_call(closure, problem, mode="encode", rows=rows)
        add("choice-closure", recipes.choice_recipe(problem, result))
        try:
            document, _ = recipes.cut_recipe(problem, vertices, rows, candidates=4, max_terms=512)
            add("cut-formulas", document)
        except recipes.WorkLimit as error:
            methods["cut-formulas"] = {"status": "incomplete_encoding_budget_not_a_proof", "error": str(error)}
    winner = min(choices, key=lambda name: (len(choices[name]), name))
    raw = choices[winner]
    if source_json_bytes is not None:
        if type(source_json_bytes) is not int or source_json_bytes < 1:
            raise ValueError("source description cost must be an exact positive integer")
        if len(raw) >= source_json_bytes:
            return SelectedEncoding(winner, raw, methods, None)
    decoded = reconstruct(parse_json(raw))
    if decoded != (problem, vertices, scale, rows):
        raise ValueError("winning encoding changed a synthesized exact compatible value")
    methods[winner] = {**methods[winner], "status": "complete_exact_seed_replay_pending_full_cube_audit"}
    return SelectedEncoding(winner, raw, methods, decoded)
