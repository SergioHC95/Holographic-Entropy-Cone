"""Slow, independent exact reference for the certified full-cube extension.

No solver libraries, native release binaries, float rounding or cached answers
are needed. Exact flow certificates certify every isotonic projection result.
"""

from __future__ import annotations

from collections import deque
from fractions import Fraction

from .count_proofs import CountGeometry


def _flow(capacity: list[list[int]], source: int, sink: int) -> tuple[int, set[int]]:
    """Integer Edmonds--Karp, including the residual minimum-cut side."""
    residual = [row.copy() for row in capacity]
    size, total = len(residual), 0
    while True:
        parent = [-1] * size
        parent[source] = source
        queue = deque([source])
        while queue and parent[sink] == -1:
            u = queue.popleft()
            for v, available in enumerate(residual[u]):
                if available and parent[v] == -1:
                    parent[v] = u
                    queue.append(v)
        if parent[sink] == -1:
            return total, {i for i, predecessor in enumerate(parent) if predecessor != -1}
        amount, v = None, sink
        while v != source:
            u = parent[v]
            amount = residual[u][v] if amount is None else min(amount, residual[u][v])
            v = u
        v = sink
        while v != source:
            u = parent[v]
            residual[u][v] -= amount
            residual[v][u] += amount
            v = u
        total += amount


def _closure_flow(problem: CountGeometry, block: set[int], supply: dict[int, int]) -> tuple[int, set[int]]:
    source, sink = problem.L, problem.L + 1
    capacity = [[0] * (problem.L + 2) for _ in range(problem.L + 2)]
    positive = sum(max(0, value) for value in supply.values())
    for i, value in supply.items():
        if value > 0:
            capacity[source][i] = value
        else:
            capacity[i][sink] = -value
    for i, j in problem.nested:
        if i in block and j in block:
            capacity[i][j] = positive + 1
    value, reachable = _flow(capacity, source, sink)
    return value, reachable & block


def isotonic_projection(problem: CountGeometry, vertex: int) -> tuple[Fraction, ...]:
    """Weighted L2 order projection, then an independent exact KKT audit."""
    values = [Fraction(0)] * problem.L

    def split(block: set[int]) -> None:
        if not block:
            return
        weight = sum(problem.alpha[i] for i in block)
        mass = sum(problem.alpha[i] for i in block if vertex >> i & 1)
        supply = {i: problem.alpha[i] * (weight * ((vertex >> i) & 1) - mass) for i in block}
        positive = sum(max(0, value) for value in supply.values())
        transported, high = _closure_flow(problem, block, supply)
        if transported == positive:
            mean = Fraction(mass, weight)
            for i in block:
                values[i] = mean
        else:
            if not high or high == block:
                raise ValueError("invalid exact maximum-closure split")
            split(block - high)
            split(high)

    split(set(range(problem.L)))
    if any(not 0 <= value <= 1 for value in values):
        raise ValueError("isotonic result outside [0,1]")
    if any(values[i] > values[j] for i, j in problem.nested):
        raise ValueError("isotonic result violates order")
    for level in set(values):
        block = {i for i, value in enumerate(values) if value == level}
        supply = {i: problem.alpha[i] * (level.denominator * ((vertex >> i) & 1) - level.numerator) for i in block}
        if sum(supply.values()) != 0:
            raise ValueError("isotonic KKT mass imbalance")
        transported, _ = _closure_flow(problem, block, supply)
        if transported != sum(max(0, value) for value in supply.values()):
            raise ValueError("isotonic KKT flow certificate failed")
    return tuple(values)


def evaluate_kernel(
    problem: CountGeometry,
    seed: dict[int, tuple[Fraction, ...]],
    vertex: int,
) -> tuple[Fraction, ...]:
    """Lexicographic disjoint folds, exact order projection, common threshold."""
    particles = {vertex: Fraction(1)}
    for i, j in problem.disjoint:
        large, small = (i, j) if problem.alpha[i] >= problem.alpha[j] else (j, i)
        a, b = problem.alpha[large], problem.alpha[small]
        updated: dict[int, Fraction] = {}
        mask = (1 << i) | (1 << j)
        for endpoint, probability in particles.items():
            if endpoint & mask != mask:
                updated[endpoint] = updated.get(endpoint, Fraction(0)) + probability
                continue
            cleared = endpoint & ~mask
            low_mass = probability * Fraction(b, a)
            updated[cleared] = updated.get(cleared, Fraction(0)) + low_mass
            if a > b:
                kept = cleared | (1 << large)
                updated[kept] = updated.get(kept, Fraction(0)) + probability - low_mass
        particles = updated
    if sum(particles.values()) != 1:
        raise ValueError("disjoint fold probability mass mismatch")
    result = [Fraction(0)] * problem.G
    for endpoint, probability in particles.items():
        if any(endpoint >> i & endpoint >> j & 1 for i, j in problem.disjoint):
            raise ValueError("disjoint fold left a conflict")
        levels = isotonic_projection(problem, endpoint)
        previous = Fraction(0)
        for level in sorted(set(levels) | {Fraction(1)}):
            if not level:
                continue
            threshold = sum(int(value >= level) << i for i, value in enumerate(levels))
            if threshold not in seed:
                raise ValueError("projection threshold outside complete compatible seed")
            for group, value in enumerate(seed[threshold]):
                result[group] += probability * (level - previous) * value
            previous = level
    return tuple(result)
