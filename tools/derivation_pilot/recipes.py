"""Exact experimental recipes with no source-table dependency when decoding.

Two candidates are investigated: an integer L1 constraint-closure program
with sparse choices, and explicit Boolean cut formulas on the complete
compatible domain. They never enter the production reader. Acceptance bridges
to the existing exact full-cube checker only after reconstructing every seed.
"""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from hec.count_proofs import (
    canonical_json,
    compatible_vertices,
    decimal,
    decode_rows,
    geometry,
    make_count_proof,
    proof_geometry,
)

FORMAT = "hec-compatible-derivation/experimental-1"
CLOSURE = "integer-interval-closure/experimental-2"
CUTS = "integer-cut-dnf/experimental-1"


class WorkLimit(ValueError):
    """Incomplete extraction under a work budget; not a proof."""


@dataclass
class ClosureResult:
    stats: dict
    tape: list[int]
    widths: list[int]
    rows: list[tuple[int, ...]]
    wall_microseconds: int


def recipe(problem, function: dict) -> dict:
    return {"format": FORMAT, "inequality": problem.inequality(), "function": function}


def recipe_id(document: dict) -> str:
    return hashlib.sha256(FORMAT.encode() + b"\0" + canonical_json(document)).hexdigest()


def recipe_geometry(document: dict):
    canonical_json(document)
    if not isinstance(document, dict) or set(document) != {"format", "inequality", "function"}:
        raise ValueError("invalid experimental recipe fields")
    if document["format"] != FORMAT:
        raise ValueError("unsupported experimental format")
    inequality = document["inequality"]
    if not isinstance(inequality, dict) or set(inequality) != {"n", "coefficients"}:
        raise ValueError("invalid inequality fields")
    coefficients = inequality["coefficients"]
    if not isinstance(coefficients, list):
        raise ValueError("coefficients must be a list")
    if type(inequality["n"]) is not int or not 1 <= inequality["n"] <= 6:
        raise ValueError("experimental recipes support only n=1 through n=6")
    problem = geometry(inequality["n"], tuple(map(decimal, coefficients)))
    if problem.L > 17 or sum(problem.beta) > 63 or any(cap > 32 for cap in problem.alpha):
        raise ValueError("experimental recipe needs a wider exact backend")
    return problem


def integer_seed(proof: dict) -> tuple[object, list[int], list[tuple[int, ...]]]:
    problem = proof_geometry(proof)
    vertices = list(compatible_vertices(problem))
    function = proof["function"]
    if "rows" in function:
        decoded = list(decode_rows(problem, function["rows"]))
        if len(decoded) != len(vertices) or any(q != 1 for q, _ in decoded):
            raise ValueError("this experiment requires a complete integral compatible seed")
        rows = [tuple(values) for _, values in decoded]
    else:
        from hec.count_proofs import evaluate_count_proof

        rows = []
        for vertex in vertices:
            values = evaluate_count_proof(proof, vertex, verify=False)
            if any(value.denominator != 1 for value in values):
                raise ValueError("this experiment does not treat fractional seeds as integral")
            rows.append(tuple(int(value) for value in values))
    return problem, vertices, rows


def closure_call(
    binary: Path,
    problem,
    *,
    mode: str,
    rows: list[tuple[int, ...]] | None = None,
    anchors: int = 32,
    enumeration: int = 64,
    pairs: bool = True,
    choice_count: int = 0,
    default: str = "lower",
    exceptions: list[list] | None = None,
) -> ClosureResult:
    if type(anchors) is not int or not 0 <= anchors <= 128 or type(pairs) is not bool:
        raise ValueError("invalid closure settings")
    if type(enumeration) is not int or not 0 <= enumeration <= 1024:
        raise ValueError("invalid integer candidate work bound")
    if mode not in ("encode", "decode", "lower", "upper"):
        raise ValueError("invalid closure mode")
    if problem.n > 6 or problem.L > 17 or sum(problem.beta) > 63:
        raise ValueError("unsupported native pilot geometry")
    count = len(list(compatible_vertices(problem)))
    request = struct.pack("<8sIII", b"HECDRV01", problem.n, len(problem.coefficients), count)
    request += struct.pack(f"<{len(problem.coefficients)}i", *problem.coefficients)
    if mode == "encode":
        if rows is None or len(rows) != count or any(len(row) != problem.G for row in rows):
            raise ValueError("encoder needs its complete source seed")
        flat = [value for row in rows for value in row]
        if any(type(value) is not int or not 0 <= value <= 65535 for value in flat):
            raise ValueError("encoder values must be bounded exact integers")
        request += struct.pack(f"<{len(flat)}H", *flat)
    elif mode == "decode":
        exceptions = [] if exceptions is None else exceptions
        if (
            type(choice_count) is not int
            or not 0 <= choice_count <= count * problem.G
            or default not in ("lower", "upper")
            or not isinstance(exceptions, list)
        ):
            raise ValueError("invalid sparse choice tape")
        request += struct.pack("<III", choice_count, 1 if default == "lower" else 2, len(exceptions))
        previous = -1
        for entry in exceptions:
            if not isinstance(entry, list) or len(entry) != 2:
                raise ValueError("invalid choice exception")
            position, raw = entry
            offset = decimal(raw)
            if type(position) is not int or not previous < position < choice_count or not 0 <= offset <= 65535:
                raise ValueError("noncanonical choice exceptions")
            previous = position
            request += struct.pack("<IH", position, offset)
    started = time.perf_counter_ns()
    args = [str(binary), "--mode", mode, "--anchors", str(anchors), "--enumeration", str(enumeration)]
    if not pairs:
        args.append("--no-pairs")
    completed = subprocess.run(args, input=request, capture_output=True, check=True)
    wall = (time.perf_counter_ns() - started) // 1000
    if len(completed.stdout) < 16:
        raise ValueError("truncated native derivation response")
    json_bytes, tape_bytes, width_bytes, row_bytes = struct.unpack("<IIII", completed.stdout[:16])
    if json_bytes > 8192 or len(completed.stdout) != 16 + json_bytes + tape_bytes + width_bytes + row_bytes:
        raise ValueError("unsafe or incomplete native derivation response")
    stats = json.loads(completed.stdout[16 : 16 + json_bytes])
    if stats.get("ok") is not True:
        raise ValueError(stats.get("error", "derivation failed"))
    expected = stats.get("choices")
    if (
        stats.get("vertices") != count
        or stats.get("groups") != problem.G
        or type(expected) is not int
        or tape_bytes != 2 * expected
        or width_bytes != 2 * expected
        or row_bytes != 2 * count * problem.G
    ):
        raise ValueError("misbound native derivation response")
    at = 16 + json_bytes
    tape = list(struct.unpack(f"<{expected}H", completed.stdout[at : at + tape_bytes]))
    at += tape_bytes
    widths = list(struct.unpack(f"<{expected}H", completed.stdout[at : at + width_bytes]))
    at += width_bytes
    values = struct.unpack(f"<{count * problem.G}H", completed.stdout[at:])
    reconstructed = [tuple(values[i * problem.G : (i + 1) * problem.G]) for i in range(count)]
    return ClosureResult(stats, tape, widths, reconstructed, wall)


def choice_recipe(
    problem, result: ClosureResult, *, anchors: int = 32, enumeration: int = 64, pairs: bool = True
) -> dict:
    lower = [[i, str(value)] for i, value in enumerate(result.tape) if value]
    upper = [[i, str(value)] for i, value in enumerate(result.tape) if value != result.widths[i]]
    default, exceptions = min((("lower", lower), ("upper", upper)), key=lambda item: (len(item[1]), item[0]))
    return recipe(
        problem,
        {
            "kind": CLOSURE,
            "anchors": anchors,
            "enumeration": enumeration,
            "pairs": pairs,
            "policy": default,
            "choice_count": len(result.tape),
            "exceptions": exceptions,
        },
    )


def policy_recipe(problem, policy: str, *, anchors: int = 32, enumeration: int = 64, pairs: bool = True) -> dict:
    if policy not in ("lower", "upper"):
        raise ValueError("unknown deterministic endpoint policy")
    return recipe(
        problem,
        {"kind": CLOSURE, "anchors": anchors, "enumeration": enumeration, "pairs": pairs, "policy": "derive-" + policy},
    )


def decode_closure(document: dict, binary: Path) -> ClosureResult:
    problem = recipe_geometry(document)
    function = document["function"]
    if not isinstance(function, dict) or function.get("kind") != CLOSURE:
        raise ValueError("unsupported closure recipe")
    policy = function.get("policy")
    common = {"kind", "anchors", "enumeration", "pairs", "policy"}
    if policy in ("derive-lower", "derive-upper") and set(function) == common:
        return closure_call(
            binary,
            problem,
            mode=policy[7:],
            anchors=function["anchors"],
            enumeration=function["enumeration"],
            pairs=function["pairs"],
        )
    if policy not in ("lower", "upper") or set(function) != common | {"choice_count", "exceptions"}:
        raise ValueError("invalid closure policy or fields")
    return closure_call(
        binary,
        problem,
        mode="decode",
        anchors=function["anchors"],
        enumeration=function["enumeration"],
        pairs=function["pairs"],
        choice_count=function["choice_count"],
        default=policy,
        exceptions=function["exceptions"],
    )


def _select(bits: int, ordinal: int) -> int:
    offset = 0
    while bits.bit_length() > 1:
        half = bits.bit_length() // 2
        lower = bits & ((1 << half) - 1)
        count = lower.bit_count()
        if ordinal < count:
            bits = lower
        else:
            ordinal -= count
            bits >>= half
            offset += half
    if bits != 1 or ordinal:
        raise ValueError("invalid Boolean-set rank")
    return offset


def cut_recipe(problem, vertices: list[int], rows: list[tuple[int, ...]], *, candidates: int = 4, max_terms=512):
    """Greedy exact implicants; absent incompatible points are don't-cares.

    This produces logical formulas, not an entropy compressor. Saving is
    measured against source row atoms and exact canonical JSON bytes. Search
    budget exhaustion is explicitly incomplete, not a successful proof.
    """
    if vertices != list(compatible_vertices(problem)) or len(rows) != len(vertices):
        raise ValueError("cut extractor needs the complete compatible domain")
    if any(
        len(row) != problem.G
        or any(type(value) is not int or not 0 <= value <= cap for value, cap in zip(row, problem.beta, strict=True))
        for row in rows
    ):
        raise ValueError("cut extraction requires bounded integral count rows")
    if type(candidates) is not int or not 1 <= candidates <= 16:
        raise ValueError("invalid formula search candidates")
    count = len(vertices)
    all_rows = (1 << count) - 1
    values = np.asarray(vertices, dtype=np.uint32)
    literals = []
    for axis in range(problem.L):
        positive = int.from_bytes(
            np.packbits(((values >> axis) & 1).astype(np.uint8), bitorder="little").tobytes(), "little"
        )
        literals.append((all_rows ^ positive, positive))
    cache_limit = max(64, min(16384, (8 * 1024**2) // max(1, (count + 7) // 8)))

    @lru_cache(maxsize=cache_limit)
    def hits(ones: int, zeros: int) -> int:
        mask = ones | zeros
        if not mask:
            return all_rows
        bit = mask & -mask
        axis = bit.bit_length() - 1
        return hits(ones & ~bit, zeros & ~bit) & literals[axis][int(bool(ones & bit))]

    full = problem.vertices - 1
    orders = (tuple(range(problem.L)), tuple(reversed(range(problem.L))))
    groups, clauses = [], set()
    generated = 0
    for group, capacity in enumerate(problem.beta):
        layers = []
        for level in range(1, capacity + 1):
            labels = np.fromiter((int(row[group] >= level) for row in rows), dtype=np.uint8, count=count)
            positive = int.from_bytes(np.packbits(labels, bitorder="little").tobytes(), "little")
            negative, remaining, terms = all_rows ^ positive, positive, set()
            while remaining:
                if len(terms) >= max_terms:
                    raise WorkLimit("cut formula term budget exhausted; domain not fully covered")
                number = remaining.bit_count()
                ordinals = sorted({int(i * (number - 1) // max(1, candidates - 1)) for i in range(candidates)})
                best = None
                for ordinal in ordinals:
                    vertex = vertices[_select(remaining, ordinal)]
                    for order in orders:
                        ones, zeros = vertex, full ^ vertex
                        for axis in order:
                            bit = 1 << axis
                            if not hits(ones & ~bit, zeros & ~bit) & negative:
                                ones &= ~bit
                                zeros &= ~bit
                        coverage = hits(ones, zeros) & remaining
                        key = (-coverage.bit_count(), (ones | zeros).bit_count(), ones, zeros)
                        if best is None or key < best[0]:
                            best = key, ones, zeros, coverage
                if best is None or not best[3]:
                    raise ValueError("formula extractor made no exact progress")
                _, ones, zeros, coverage = best
                terms.add((ones, zeros))
                remaining &= ~coverage
            layers.append(sorted(terms))
            clauses.update(terms)
            generated += len(terms)
        groups.append(layers)
    terms = sorted(clauses)
    locations = {term: i for i, term in enumerate(terms)}
    result = recipe(
        problem,
        {
            "kind": CUTS,
            "terms": [list(term) for term in terms],
            "groups": [[[locations[term] for term in layer] for layer in group] for group in groups],
        },
    )
    return result, {
        "unique_terms": len(terms),
        "term_references": generated,
        "literal_atoms": sum((a | b).bit_count() for a, b in terms),
    }


class CutFunction:
    def __init__(self, document: dict):
        self.problem = recipe_geometry(document)
        function = document["function"]
        if not isinstance(function, dict) or set(function) != {"kind", "terms", "groups"} or function["kind"] != CUTS:
            raise ValueError("unsupported cut formula")
        self.terms, self.groups = function["terms"], function["groups"]
        if not isinstance(self.terms, list) or not isinstance(self.groups, list) or len(self.groups) != self.problem.G:
            raise ValueError("cut formula arrays do not match RHS geometry")
        for term in self.terms:
            if (
                not isinstance(term, list)
                or len(term) != 2
                or any(type(value) is not int or not 0 <= value < self.problem.vertices for value in term)
                or term[0] & term[1]
            ):
                raise ValueError("invalid Boolean literal term")
        if self.terms != sorted(map(list, sorted(set(map(tuple, self.terms))))):
            raise ValueError("cut terms must be sorted and unique")
        used = set()
        for group, capacity in zip(self.groups, self.problem.beta, strict=True):
            if not isinstance(group, list) or len(group) != capacity:
                raise ValueError("threshold layers differ from RHS capacity")
            for layer in group:
                if (
                    not isinstance(layer, list)
                    or any(type(ref) is not int or not 0 <= ref < len(self.terms) for ref in layer)
                    or layer != sorted(set(layer))
                ):
                    raise ValueError("invalid cut-term references")
                used.update(layer)
        if used != set(range(len(self.terms))):
            raise ValueError("unreachable cut terms")

    def __getitem__(self, vertex: int) -> tuple[int, ...]:
        if type(vertex) is not int or not 0 <= vertex < self.problem.vertices:
            raise ValueError("query outside source cube")
        truth = [(vertex & ones) == ones and not vertex & zeros for ones, zeros in self.terms]
        return tuple(sum(any(truth[ref] for ref in layer) for layer in group) for group in self.groups)


def reconstruct(document: dict, closure_binary: Path) -> tuple[object, list[tuple[int, ...]], dict]:
    problem = recipe_geometry(document)
    function = document["function"]
    if not isinstance(function, dict):
        raise ValueError("function must be an object")
    if function.get("kind") == CLOSURE:
        result = decode_closure(document, closure_binary)
        return problem, result.rows, {**result.stats, "wall_microseconds": result.wall_microseconds}
    if function.get("kind") == CUTS:
        start = time.perf_counter_ns()
        definition = CutFunction(document)
        rows = [definition[vertex] for vertex in compatible_vertices(problem)]
        return problem, rows, {"wall_microseconds": (time.perf_counter_ns() - start) // 1000}
    raise ValueError("unsupported experimental constructor")


def full_map_definition(problem, rows: list[tuple[int, ...]]) -> dict:
    return make_count_proof(problem, rows, transport=True)
