"""Complete two-cut bulk-symmetry reduction and tight-cut implications.

Two chosen bulk sides describe one two-bit signature per bulk vertex.
Relabelling bulk vertices acts exactly by permuting these signatures; their
multiset therefore gives a complete orbit representative. For three bulk
vertices there are eight proper-side orbits, or three for nested/disjoint
terminal cuts when choosing the unique inclusion-minimal minimum cuts.

Each original cut slack is nonnegative under the global lower bounds.
One inequality on the sum of two slacks is consequently equivalent to both
slacks vanishing. Tight submodularity also forces every edge between the two
cut differences to vanish; adding their nonnegative weights to the sum is
equivalent and exposes those implications to native propagation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from functools import lru_cache
from itertools import combinations
from typing import TYPE_CHECKING

import numpy as np

from ._graph_milp import _frozen_milp_sha256

if TYPE_CHECKING:
    from ._graph_epr import EprModel


@lru_cache(maxsize=8)
def _bulk_pair_orbits(bulk_count: int) -> tuple[tuple[int, int], ...]:
    """Enumerate row-signature histograms, not exponentially many mask pairs."""
    if bulk_count < 2:
        return ()
    full = (1 << bulk_count) - 1
    signatures = []
    for zero in range(bulk_count + 1):
        for left in range(bulk_count - zero + 1):
            for right in range(bulk_count - zero - left + 1):
                both = bulk_count - zero - left - right
                row = (0,) * zero + (1,) * left + (2,) * right + (3,) * both
                a = sum((value & 1) << k for k, value in enumerate(row))
                b = sum(((value >> 1) & 1) << k for k, value in enumerate(row))
                if 0 < a < full and 0 < b < full:
                    signatures.append((row, a, b))
    return tuple((a, b) for _, a, b in sorted(signatures))


def _allowed_pair(left: int, right: int, a: int, b: int) -> bool:
    return not ((left & right == left and a & ~b) or (left & right == right and b & ~a) or (not left & right and a & b))


@lru_cache(maxsize=4096)
def _pair_score(left: int, right: int, saturated: int) -> int:
    """Exact integer ranking; scaling by 24 covers the three/eight orbit counts."""
    total = count = 0
    left_terms = (left & ~right).bit_count()
    right_terms = (right & ~left).bit_count()
    common_terms = (left & right).bit_count()
    outside_terms = (127 & ~(left | right)).bit_count()
    for a, b in _bulk_pair_orbits(3):
        if not _allowed_pair(left, right, a, b):
            continue
        zeros = 0
        if saturated & 9:
            first, second = (a & ~b).bit_count(), (b & ~a).bit_count()
            zeros += first * second + left_terms * second + right_terms * first
        if saturated & 6:
            inside, outside = (a & b).bit_count(), (7 & ~(a | b)).bit_count()
            zeros += inside * outside + common_terms * outside + outside_terms * inside
        total += zeros
        count += 1
    return 4 * total * (24 // count) + (8 - count) * 24


@lru_cache(maxsize=4096)
def _pair_penalties(left: int, right: int, saturated: int) -> tuple:
    result = []
    for a, b in _bulk_pair_orbits(3):
        if not _allowed_pair(left, right, a, b):
            continue
        zero_edges = set()
        for orientation in range(4):
            if not saturated & (1 << orientation):
                continue
            x = (left | a << 7) ^ ((1 << 10) - 1 if orientation & 1 else 0)
            y = (right | b << 7) ^ ((1 << 10) - 1 if orientation & 2 else 0)
            first, second = x & ~y, y & ~x
            for u in range(10):
                if first & (1 << u):
                    for v in range(10):
                        if second & (1 << v) and (u >= 7 or v >= 7):
                            zero_edges.add((min(u, v), max(u, v)))
        row, degree = [0] * 17, [0] * 7
        core = tuple(combinations(range(3), 2))
        for u, v in zero_edges:
            if u < 7:
                bulk = v - 7
                if bulk < 2:
                    row[2 * u + bulk] += 1
                else:
                    degree[u] += 1
                    row[2 * u] -= 1
                    row[2 * u + 1] -= 1
            else:
                row[14 + core.index((u - 7, v - 7))] += 1
        result.append((a, b, tuple(row), tuple(degree), len(zero_edges)))
    return tuple(result)


def pair_cut_disjunctions(source: EprModel) -> EprModel:
    from ._graph_epr import _epr_geometry

    boundary, _ = _epr_geometry()
    values = dict(zip(boundary, source.target, strict=True))
    values[0] = 0

    def entropy(mask: int) -> int:
        return values[mask ^ 127 if mask & 64 else mask]

    total = sum(source.degrees)
    free = [
        sub
        for sub, side in enumerate(boundary)
        if source.target[sub]
        not in (
            sum(source.degrees[t] for t in range(6) if side & (1 << t)),
            total - sum(source.degrees[t] for t in range(6) if side & (1 << t)),
        )
    ]
    if len(free) < 2:
        return source
    best = None
    for i, j in combinations(range(len(free)), 2):
        left, right = boundary[free[i]], boundary[free[j]]
        value = source.target[free[i]] + source.target[free[j]]
        saturated = 9 if value == entropy(left & right) + entropy(left | right) else 0
        saturated |= 6 if value == entropy(left & ~right) + entropy(right & ~left) else 0
        choice = (_pair_score(left, right, saturated), -i, -j, saturated)
        if best is None or choice[:3] > best[:3]:
            best = choice
    assert best is not None
    _, ni, nj, saturated = best
    i, j = -ni, -nj
    penalties = _pair_penalties(boundary[free[i]], boundary[free[j]], saturated)
    merged = []
    for left, right, penalty, degree, _zeros in penalties:
        a, a_rhs = source.disjunctions[i][left - 1]
        b, b_rhs = source.disjunctions[j][right - 1]
        row = tuple(x + y + z for x, y, z in zip(a, b, penalty, strict=True))
        rhs = a_rhs + b_rhs - sum(x * y for x, y in zip(degree, source.degrees, strict=True))
        merged.append((row, rhs))
    disjunctions = (tuple(merged),) + tuple(group for k, group in enumerate(source.disjunctions) if k not in (i, j))
    # The chosen pair already fixes the bulk labelling. Keeping the old
    # global degree sort could remove orbit representatives and is unsafe.
    matrix = source.matrix[:-2].copy()
    rhs = source.rhs[:-2].copy()
    linear_hash = _frozen_milp_sha256(
        np.zeros(17),
        matrix,
        np.full(len(rhs), -np.inf),
        rhs,
        np.zeros(17),
        source.upper,
        np.zeros(17, dtype=np.int32),
    )
    packed = json.dumps({"linear_model": linear_hash, "disjunctions": disjunctions}, separators=(",", ":")).encode()
    digest = hashlib.sha256(packed).hexdigest()
    profile = {
        **source.profile,
        "paired_cut_subsystems": [free[i], free[j]],
        "paired_orbit_representatives": len(penalties),
        "paired_mean_forced_zero_edges": sum(entry[-1] for entry in penalties) / len(penalties),
        "disjunctions": len(disjunctions),
        "ineq_rows": len(rhs),
        "constraint_model_sha256": digest,
        "cut_encoding": "bulk_orbit_linear_disjunction",
    }
    return replace(source, matrix=matrix, rhs=rhs, disjunctions=disjunctions, profile=profile, sha256=digest)
