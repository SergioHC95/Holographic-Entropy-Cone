"""Counterexample-guided extraction of small fixed-anchor derivations.

The source seed is used only during extraction. Saved recipes regenerate an
alternative integer seed from geometry and explicit pins; failed attempts
never count as proofs. Original-cube acceptance remains a separate check.
"""

import json
import struct
import subprocess
import time
from pathlib import Path

import numpy as np

from hec.count_proofs import compatible_vertices, decimal

from .recipes import recipe, recipe_geometry

KIND = "fixed-anchor-closure/experimental-1"


def definition(problem, pins, *, policy="lower", enumeration=64):
    return recipe(
        problem,
        {
            "kind": KIND,
            "pins": [[v, [str(x) for x in values]] for v, values in sorted(pins)],
            "policy": policy,
            "enumeration": enumeration,
            "anchors": 32,
        },
    )


def derive(document, binary):
    problem = recipe_geometry(document)
    function = document["function"]
    if not isinstance(function, dict) or set(function) != {"kind", "pins", "policy", "enumeration", "anchors"}:
        raise ValueError("invalid fixed-anchor function fields")
    if function["kind"] != KIND or function["policy"] not in ("lower", "upper"):
        raise ValueError("unknown fixed-anchor derivation")
    for key, maximum in (("anchors", 128), ("enumeration", 1024)):
        if type(function[key]) is not int or not 0 <= function[key] <= maximum:
            raise ValueError("invalid fixed-anchor settings")
    if problem.n > 6 or problem.L > 17 or sum(problem.beta) > 63 or any(x > 32 for x in problem.alpha):
        raise ValueError("unsupported exact anchored backend geometry")
    vertices = list(compatible_vertices(problem))
    pins = function["pins"]
    if not isinstance(pins, list) or len(pins) > 64:
        raise ValueError("invalid fixed-anchor array")
    request = struct.pack("<8sIII", b"HECPIN01", problem.n, len(problem.coefficients), len(vertices))
    request += struct.pack(f"<{len(problem.coefficients)}i", *problem.coefficients) + struct.pack("<I", len(pins))
    previous = -1
    domain = set(vertices)
    for pin in pins:
        if not isinstance(pin, list) or len(pin) != 2 or type(pin[0]) is not int or not isinstance(pin[1], list):
            raise ValueError("malformed fixed anchor")
        vertex, values = pin[0], tuple(map(decimal, pin[1]))
        if vertex not in domain or vertex <= previous or len(values) != problem.G:
            raise ValueError("noncanonical or out-of-domain fixed anchor")
        if any(not 0 <= x <= cap for x, cap in zip(values, problem.beta, strict=True)):
            raise ValueError("fixed anchor exceeds count bounds")
        previous = vertex
        request += struct.pack("<I", vertex) + struct.pack(f"<{len(values)}H", *values)
    start = time.perf_counter_ns()
    completed = subprocess.run(
        [
            str(binary),
            "--anchors",
            str(function["anchors"]),
            "--enumeration",
            str(function["enumeration"]),
            "--policy",
            function["policy"],
        ],
        input=request,
        check=True,
        capture_output=True,
    )
    elapsed = (time.perf_counter_ns() - start) // 1000
    if len(completed.stdout) < 16:
        raise ValueError("truncated anchored response")
    size, first, second, third = struct.unpack("<IIII", completed.stdout[:16])
    if size > 8192 or len(completed.stdout) != 16 + size + first + second + third:
        raise ValueError("unsafe anchored response")
    stats = json.loads(completed.stdout[16 : 16 + size])
    stats["wall_microseconds"] = elapsed
    offset = 16 + size
    cells = len(vertices) * problem.G
    if stats.get("ok") is not True:
        if first == second == 2 * cells and third == 0:
            lower = np.frombuffer(completed.stdout[offset : offset + first], dtype="<u2").reshape(
                len(vertices), problem.G
            )
            upper = np.frombuffer(completed.stdout[offset + first :], dtype="<u2").reshape(len(vertices), problem.G)
            return problem, None, stats, (lower, upper)
        return problem, None, stats, None
    if stats.get("vertices") != len(vertices) or stats.get("groups") != problem.G or third != 2 * cells:
        raise ValueError("incomplete anchored result")
    values = np.frombuffer(completed.stdout[offset + first + second :], dtype="<u2").reshape(len(vertices), problem.G)
    rows = [tuple(map(int, row)) for row in values]
    return problem, rows, stats, None


def extract(problem, source_rows, binary: Path, *, budget=16, policy="lower"):
    vertices = list(compatible_vertices(problem))
    known = np.asarray(source_rows, dtype=np.uint16).reshape(len(vertices), problem.G)
    pinned, history = {}, []
    boundary = {v for v, _ in problem.boundary}
    for iteration in range(budget + 1):
        doc = definition(problem, list(pinned.items()), policy=policy)
        _, rows, stats, bounds = derive(doc, binary)
        history.append({"pins": len(pinned), **stats})
        if rows is not None:
            return (
                doc,
                rows,
                {
                    "status": "complete_candidate_needs_full_verification",
                    "attempts": history,
                    "pins": len(pinned),
                    "recorded_count_values": len(pinned) * problem.G,
                },
            )
        if iteration == budget or bounds is None:
            break
        lower, upper = bounds
        violations = np.count_nonzero((known < lower) | (known > upper), axis=1)
        candidates = [
            i
            for i, count in enumerate(violations)
            if count and vertices[i] not in pinned and vertices[i] not in boundary
        ]
        if not candidates:
            break
        chosen = min(candidates, key=lambda i: (-int(violations[i]), vertices[i]))
        pinned[vertices[chosen]] = tuple(map(int, known[chosen]))
    return None, None, {"status": "incomplete_anchor_budget_not_a_proof", "attempts": history, "pins": len(pinned)}
