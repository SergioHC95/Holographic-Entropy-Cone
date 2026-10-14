"""Exact, source-guided simpler-map synthesis reference (not an acceptance gate).

A tight edge with equal values in one coordinate forces both endpoints to move
together in that coordinate. We collect such components, then intersect ALL
coupled residual-budget intervals on their cut edges. Moving a whole component
to a value in that intersection preserves every compatible edge and boundary.
The resulting full-map recipe must still receive independent original-cube
acceptance. This is a bounded heuristic, not a universal construction theorem.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from .diagrams import validate_rows

METHOD = "exact-tight-component-smoothing/experimental-1"


class WorkLimit(ValueError):
    """Synthesis budget exhausted; no accepted alternative is produced."""


def small_denominators(scale):
    """Fixed deterministic grid family, always dividing the exact source scale."""
    values = {q for q in range(1, 257) if scale % q == 0}
    values.update(1 << k for k in range(31) if scale % (1 << k) == 0)
    return sorted(values)


@dataclass
class Edge:
    left: int
    right: int
    budget: int
    load: int


def smooth(problem, vertices, scale, original, *, sweeps=2, max_work=50_000_000):
    if type(sweeps) is not int or not 1 <= sweeps <= 8 or type(max_work) is not int or max_work < 1:
        raise ValueError("invalid exact synthesis work bounds")
    if not 1 <= problem.n <= 6 or problem.L > 25 or problem.G > 63:
        raise ValueError("geometry exceeds bounded corpus synthesis capability")
    validate_rows(problem, vertices, scale, original)
    rows = [list(row) for row in original]  # Never modify an original proof seed.
    index = {x: i for i, x in enumerate(vertices)}
    fixed = set()
    for x, image in problem.boundary:
        u = index[x]
        if rows[u] != [value * scale for value in image]:
            raise ValueError("source occurrence boundary mismatch")
        fixed.add(u)
    edges, adjacency = [], [[] for _ in vertices]
    for u, x in enumerate(vertices):
        for axis in range(problem.L):
            v = index.get(x ^ (1 << axis))
            if v is None or v <= u:
                continue
            load = sum(abs(a - b) for a, b in zip(rows[u], rows[v], strict=True))
            budget = problem.alpha[axis] * scale
            if load > budget:
                raise ValueError("source compatible edge violation")
            at = len(edges)
            edges.append(Edge(u, v, budget, load))
            adjacency[u].append(at)
            adjacency[v].append(at)
    denominators, work, moves, visits, actual_sweeps = small_denominators(scale), 0, 0, 0, 0

    def charge(amount=1):
        nonlocal work
        work += amount
        if work > max_work:
            raise WorkLimit("exact synthesis work budget exhausted; alternative not accepted")

    for _ in range(sweeps):
        before, actual_sweeps = moves, actual_sweeps + 1
        for group, cap in enumerate(problem.beta):
            parent = list(range(len(vertices)))

            def root(u, parent=parent):
                while parent[u] != u:
                    parent[u] = parent[parent[u]]
                    u = parent[u]
                return u

            for edge in edges:
                charge()
                if edge.load == edge.budget and rows[edge.left][group] == rows[edge.right][group]:
                    a, b = root(edge.left), root(edge.right)
                    parent[max(a, b)] = min(a, b)
            components = {}
            for u in range(len(vertices)):
                components.setdefault(root(u), []).append(u)
            for members in components.values():
                visits += 1
                if any(u in fixed for u in members):
                    continue
                inside = set(members)
                old = rows[members[0]][group]
                if any(rows[u][group] != old for u in members):
                    raise ValueError("tight equality component does not have a constant coordinate")
                low, high, neighbors, crossing = 0, cap * scale, Counter(), []
                for u in members:
                    for at in adjacency[u]:
                        charge()
                        edge = edges[at]
                        v = edge.right if u == edge.left else edge.left
                        if v in inside:
                            continue
                        value = rows[v][group]
                        other_load = edge.load - abs(old - value)
                        residual = edge.budget - other_load
                        if residual < 0:
                            raise ValueError("negative coupled residual budget")
                        low, high = max(low, value - residual), min(high, value + residual)
                        neighbors[value] += 1
                        crossing.append((at, value))
                if not low <= old <= high:
                    raise ValueError("exact feasible interval excluded the current source")
                choices = {old, low, high}
                choices.update(value for value in neighbors if low <= value <= high)
                for denominator in denominators:
                    step = scale // denominator
                    first, last = ((low + step - 1) // step) * step, (high // step) * step
                    if first > last:
                        continue
                    choices.update((first, last, min(last, max(first, (old // step) * step))))
                    upper = ((old + step - 1) // step) * step
                    if first <= upper <= last:
                        choices.add(upper)

                def score(value, neighbors=neighbors):
                    charge(len(neighbors) + 1)
                    return (
                        scale // math.gcd(scale, value),
                        sum(count for neighbor, count in neighbors.items() if neighbor != value),
                        sum(count * abs(value - neighbor) for neighbor, count in neighbors.items()),
                        value,
                    )

                value = min(sorted(choices), key=score)
                if value == old:
                    continue
                # Internal edges are unchanged: both coordinate values move
                # together. Every cut edge has already constrained this value.
                for at, neighbor in crossing:
                    edge = edges[at]
                    edge.load += abs(value - neighbor) - abs(old - neighbor)
                    if edge.load > edge.budget:
                        raise ValueError("component move violated a coupled edge")
                for u in members:
                    rows[u][group] = value
                moves += 1
        if moves == before:
            break
    divisor = scale
    for row in rows:
        for value in row:
            divisor = math.gcd(divisor, value)
    new_scale = scale // divisor
    result = [tuple(value // divisor for value in row) for row in rows]
    validate_rows(problem, vertices, new_scale, result)
    # Recompute loads, independently of all cached incremental updates.
    for edge in edges:
        load = sum(abs(a - b) for a, b in zip(rows[edge.left], rows[edge.right], strict=True))
        if load != edge.load or load > edge.budget:
            raise ValueError("final exact edge audit disagrees with cached updates")
    for x, image in problem.boundary:
        if result[index[x]] != tuple(value * new_scale for value in image):
            raise ValueError("synthesis changed an occurrence boundary")
    changes = sum(
        a * new_scale != b * scale
        for original_row, changed_row in zip(original, result, strict=True)
        for a, b in zip(original_row, changed_row, strict=True)
    )
    return (
        new_scale,
        result,
        {
            "method": METHOD,
            "status": "complete_compatible_seed_pending_independent_full_cube_acceptance",
            "source_scale": str(scale),
            "candidate_scale": str(new_scale),
            "changed_cells": changes,
            "component_moves": moves,
            "component_visits": visits,
            "compatible_edges": len(edges),
            "sweeps": actual_sweeps,
            "work": work,
            "strict_description_improvement": "not_yet_measured",
        },
    )
