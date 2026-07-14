"""Private exact validation and safe normalization of graph realizations.

This module is deliberately independent of every optimizer.  A solver may
suggest a graph, but only the exact minimum-cut computation here decides
whether that graph realizes an entropy vector.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from fractions import Fraction
from math import lcm
from typing import Any, Literal, TypeAlias

import numpy as np

from .coordinates import party_index, party_labels, subsets

ExactGraph: TypeAlias = Mapping[str, Any]

_BULK_VERTEX = re.compile(r"x([1-9]\d*)\Z")


def _vertex_sort_key(vertex: str) -> tuple[int, int | str]:
    """Return the repository order: physical parties, bulk vertices, purifier."""

    if vertex == "O":
        return (2, 0)
    try:
        return (0, party_index(vertex))
    except ValueError:
        pass
    bulk = _BULK_VERTEX.fullmatch(vertex)
    if bulk:
        return (1, int(bulk.group(1)))
    raise ValueError(f"invalid graph vertex label {vertex!r}")


def _orient_edge(left: str, right: str) -> tuple[str, str]:
    return (left, right) if _vertex_sort_key(left) < _vertex_sort_key(right) else (right, left)


def _edge_sort_key(edge: Sequence[object]) -> tuple[tuple[int, int | str], tuple[int, int | str]]:
    return (_vertex_sort_key(str(edge[0])), _vertex_sort_key(str(edge[1])))


def _as_fraction(value: object) -> Fraction:
    """Convert a graph weight to a finite exact rational."""

    if isinstance(value, (bool, np.bool_)):
        raise TypeError("boolean graph weights are not exact numbers")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, (int, np.integer)):
        return Fraction(int(value), 1)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("graph weights must be finite")
        # Interpret the user's displayed decimal, rather than exposing the
        # binary approximation used to transport a Python float.
        return Fraction(str(number))
    try:
        result = Fraction(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise TypeError(f"graph weight is not an exact number: {value!r}") from exc
    return result


def _exact_graph_edges(graph: ExactGraph, n: int | None = None) -> tuple[tuple[str, str, Fraction], ...]:
    """Return canonical positive undirected edges with parallel edges merged."""

    terminals: frozenset[str] | None = None
    if n is not None:
        _validate_party_count(n)
        terminals = frozenset(party_labels(n))
    if not isinstance(graph, Mapping):
        raise ValueError("graph must be an object with edges and weights")
    raw_edges = graph.get("edges")
    raw_weights = graph.get("weights")
    if not isinstance(raw_edges, list) or not isinstance(raw_weights, list):
        raise ValueError("graph records must contain list-valued edges and weights")
    if len(raw_edges) != len(raw_weights):
        raise ValueError(f"edge/weight mismatch: {len(raw_edges)} vs {len(raw_weights)}")

    combined: defaultdict[tuple[str, str], Fraction] = defaultdict(Fraction)
    for raw_edge, raw_weight in zip(raw_edges, raw_weights, strict=True):
        if not isinstance(raw_edge, list) or len(raw_edge) != 2:
            raise ValueError(f"invalid graph edge {raw_edge!r}")
        if not all(isinstance(vertex, str) and vertex for vertex in raw_edge):
            raise ValueError(f"graph edge labels must be nonempty strings: {raw_edge!r}")
        left, right = raw_edge
        if left == right:
            raise ValueError("self-loop edges are not valid realization edges")
        oriented = _orient_edge(left, right)
        if terminals is not None:
            for vertex in oriented:
                if vertex not in terminals and not _BULK_VERTEX.fullmatch(vertex):
                    raise ValueError(f"graph vertex {vertex!r} is not a terminal for n={n} or a bulk label")
        weight = _as_fraction(raw_weight)
        if weight < 0:
            raise ValueError("graph weights must be non-negative")
        if weight > 0:
            combined[oriented] += weight
    return tuple(
        (left, right, weight)
        for (left, right), weight in sorted(combined.items(), key=lambda item: _edge_sort_key(item[0]))
        if weight > 0
    )


def _json_weight(value: Fraction) -> int | str:
    return int(value) if value.denominator == 1 else str(value)


def _graph_payload(edges: Sequence[tuple[str, str, Fraction]]) -> dict[str, list[Any]]:
    canonical = tuple(sorted(edges, key=_edge_sort_key))
    return {
        "edges": [[left, right] for left, right, _weight in canonical],
        "weights": [_json_weight(weight) for _left, _right, weight in canonical],
    }


def canonical_graph(graph: ExactGraph, n: int | None = None) -> dict[str, list[Any]]:
    """Return one strict, merged repository-format graph record."""

    edges = _exact_graph_edges(graph, n)
    if n is not None:
        _validate_contiguous_bulk_labels(edges, n)
    return _graph_payload(edges)


def _validate_contiguous_bulk_labels(edges: Sequence[tuple[str, str, Fraction]], n: int) -> None:
    terminals = frozenset(party_labels(n))
    bulk_numbers = {
        int(vertex[1:]) for left, right, _weight in edges for vertex in (left, right) if vertex not in terminals
    }
    if bulk_numbers != set(range(1, len(bulk_numbers) + 1)):
        raise ValueError("canonical graph bulk labels must be contiguous from x1")


def canonical_primitive_ray_graph(graph: ExactGraph, n: int | None = None) -> dict[str, Any]:
    """Return a canonical integer graph with primitive positive weights."""

    edges = _exact_graph_edges(graph, n)
    if n is not None:
        _validate_contiguous_bulk_labels(edges, n)
    if not edges:
        return {"edges": [], "weights": []}
    denominator = 1
    for _left, _right, weight in edges:
        denominator = lcm(denominator, weight.denominator)
    integer_weights = [weight.numerator * (denominator // weight.denominator) for _left, _right, weight in edges]
    factor = math.gcd(*integer_weights)
    return {
        "edges": [[left, right] for left, right, _weight in edges],
        "weights": [weight // factor for weight in integer_weights],
    }


def _validate_party_count(n: int) -> None:
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("party count must be a positive integer")


def graph_total_vertices(graph: ExactGraph, n: int) -> int:
    """Count fixed terminals and bulk vertices incident to positive edges."""

    edges = _exact_graph_edges(graph, n)
    terminals = frozenset(party_labels(n))
    bulk = {vertex for left, right, _weight in edges for vertex in (left, right) if vertex not in terminals}
    return n + 1 + len(bulk)


def prune_entropy_irrelevant_components(
    graph: ExactGraph,
    n: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drop positive components containing no physical terminal.

    Such a component can always be placed with the purifier in every physical
    terminal cut, so removing it leaves every entropy unchanged.
    """

    canonical_edges = _exact_graph_edges(graph, n)
    physical_terminals = frozenset(party_labels(n)[:n])
    all_terminals = frozenset(party_labels(n))
    adjacency: defaultdict[str, set[str]] = defaultdict(set)
    for left, right, _weight in canonical_edges:
        adjacency[left].add(right)
        adjacency[right].add(left)

    reachable = set(physical_terminals)
    pending = deque(sorted(physical_terminals))
    while pending:
        vertex = pending.popleft()
        for neighbor in sorted(adjacency.get(vertex, ())):
            if neighbor not in reachable:
                reachable.add(neighbor)
                pending.append(neighbor)

    kept = tuple(edge for edge in canonical_edges if edge[0] in reachable)
    removed = tuple(edge for edge in canonical_edges if edge[0] not in reachable)
    pruned = _graph_payload(kept)
    removed_payload = _graph_payload(removed)
    kept_vertices = {vertex for left, right, _weight in kept for vertex in (left, right)}
    removed_vertices = {vertex for left, right, _weight in removed for vertex in (left, right)}

    def bulk_label_key(vertex: str) -> tuple[int, int | str]:
        return (0, int(vertex[1:])) if vertex.startswith("x") and vertex[1:].isdigit() else (1, vertex)

    metadata = {
        "changed": bool(removed),
        "postprune_total_vertices": graph_total_vertices(pruned, n),
        "preprune_total_vertices": graph_total_vertices(graph, n),
        "removed_bulk_vertices": sorted(
            (removed_vertices - kept_vertices) - all_terminals,
            key=bulk_label_key,
        ),
        "removed_edges": removed_payload["edges"],
        "removed_weights": removed_payload["weights"],
    }
    return pruned, metadata


def lift_graph_total_vertices(graph: ExactGraph, n: int, total_vertices: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministically add active bulk vertices without changing entropies.

    Each step subdivides a positive edge ``u--v`` into ``u--x--v`` with the
    same weight on both new edges.  The zero graph is first seeded by attaching
    a unit edge to the purifier; this still contributes zero to every terminal
    minimum cut.
    """

    _validate_party_count(n)
    if isinstance(total_vertices, bool) or not isinstance(total_vertices, int) or total_vertices < n + 1:
        raise ValueError(f"total_vertices must be an integer at least {n + 1}")

    canonical_edges = list(_exact_graph_edges(graph, n))
    current_total = graph_total_vertices(graph, n)
    if current_total > total_vertices:
        raise ValueError(f"cannot lift {current_total} active vertices down to {total_vertices}")
    terminals = frozenset(party_labels(n))
    used_labels = terminals | {vertex for left, right, _weight in canonical_edges for vertex in (left, right)}
    canonical_bulk_pool = tuple(f"x{index}" for index in range(1, total_vertices - n))

    def next_unused_bulk() -> str:
        try:
            return next(vertex for vertex in canonical_bulk_pool if vertex not in used_labels)
        except StopIteration as exc:
            raise ValueError("no inactive canonical bulk label remains for the requested total") from exc

    zero_ray_seed: dict[str, Any] | None = None
    if current_total < total_vertices and not canonical_edges:
        new_vertex = next_unused_bulk()
        purifier = party_labels(n)[-1]
        seed_edge = _orient_edge(purifier, new_vertex)
        canonical_edges.append((*seed_edge, Fraction(1)))
        used_labels = used_labels | {new_vertex}
        current_total += 1
        zero_ray_seed = {
            "edge": list(seed_edge),
            "new_vertex": new_vertex,
            "weight": 1,
        }

    steps: list[dict[str, Any]] = []
    while current_total < total_vertices:
        new_vertex = next_unused_bulk()
        left, right, weight = min(canonical_edges)
        canonical_edges.remove((left, right, weight))
        canonical_edges.extend(
            [
                (*_orient_edge(left, new_vertex), weight),
                (*_orient_edge(new_vertex, right), weight),
            ]
        )
        canonical_edges.sort(key=_edge_sort_key)
        used_labels = used_labels | {new_vertex}
        steps.append(
            {
                "new_vertex": new_vertex,
                "replaced_edge": [left, right],
                "weight": _json_weight(weight),
            }
        )
        current_total += 1

    lifted = _graph_payload(canonical_edges)
    metadata = {
        "canonical_bulk_label_pool": list(canonical_bulk_pool),
        "lift_steps": steps,
        "postlift_total_vertices": graph_total_vertices(lifted, n),
        "prelift_total_vertices": graph_total_vertices(graph, n),
        "requested_total_vertices": total_vertices,
        "zero_ray_seed": zero_ray_seed,
    }
    return lifted, metadata


def _maximum_flow(
    vertex_count: int,
    directed_edges: Sequence[tuple[int, int, int]],
    source: int,
    sink: int,
) -> int:
    """Return an exact integer max-flow using Dinic's algorithm."""

    adjacency: list[list[list[int]]] = [[] for _ in range(vertex_count)]

    def add_arc(left: int, right: int, capacity: int) -> None:
        forward = [right, capacity, len(adjacency[right])]
        reverse = [left, 0, len(adjacency[left])]
        adjacency[left].append(forward)
        adjacency[right].append(reverse)

    for left, right, capacity in directed_edges:
        add_arc(left, right, capacity)

    total = 0
    while True:
        level = [-1] * vertex_count
        level[source] = 0
        pending = deque([source])
        while pending:
            vertex = pending.popleft()
            for neighbor, capacity, _reverse in adjacency[vertex]:
                if capacity > 0 and level[neighbor] < 0:
                    level[neighbor] = level[vertex] + 1
                    pending.append(neighbor)
        if level[sink] < 0:
            return total

        next_edge = [0] * vertex_count

        def send(
            available: int,
            level: list[int] = level,
            next_edge: list[int] = next_edge,
        ) -> int:
            vertices = [source]
            path: list[tuple[int, int]] = []
            bottleneck = [available]
            while vertices:
                vertex = vertices[-1]
                if vertex == sink:
                    pushed = bottleneck[-1]
                    for path_vertex, edge_index in path:
                        edge = adjacency[path_vertex][edge_index]
                        neighbor, _capacity, reverse = edge
                        edge[1] -= pushed
                        adjacency[neighbor][reverse][1] += pushed
                    return pushed

                while next_edge[vertex] < len(adjacency[vertex]):
                    edge_index = next_edge[vertex]
                    neighbor, capacity, _reverse = adjacency[vertex][edge_index]
                    if capacity > 0 and level[neighbor] == level[vertex] + 1:
                        vertices.append(neighbor)
                        path.append((vertex, edge_index))
                        bottleneck.append(min(bottleneck[-1], capacity))
                        break
                    next_edge[vertex] += 1
                else:
                    vertices.pop()
                    if path:
                        parent, _edge_index = path.pop()
                        bottleneck.pop()
                        next_edge[parent] += 1
            return 0

        flow_bound = sum(capacity for _left, _right, capacity in directed_edges) + 1
        while pushed := send(flow_bound):
            total += pushed


def exact_entropy_vector_mincut(graph: ExactGraph, n: int) -> tuple[Fraction, ...]:
    """Return exact graph entropies via one integer max-flow per subsystem."""

    edges = _exact_graph_edges(graph, n)
    denominator = 1
    for _left, _right, weight in edges:
        denominator = lcm(denominator, weight.denominator)
    integer_edges = [
        (left, right, weight.numerator * (denominator // weight.denominator)) for left, right, weight in edges
    ]

    labels = party_labels(n)
    vertices = sorted(set(labels) | {vertex for left, right, _weight in integer_edges for vertex in (left, right)})
    vertex_index = {vertex: index for index, vertex in enumerate(vertices)}
    source = len(vertices)
    sink = source + 1
    base_capacity = sum(weight for _left, _right, weight in integer_edges)
    force_capacity = base_capacity + 1
    base_arcs: list[tuple[int, int, int]] = []
    for left, right, weight in integer_edges:
        left_index, right_index = vertex_index[left], vertex_index[right]
        base_arcs.append((left_index, right_index, weight))
        base_arcs.append((right_index, left_index, weight))

    entropy: list[Fraction] = []
    for subset in subsets(n):
        selected = {labels[index] for index in subset}
        arcs = list(base_arcs)
        for terminal in labels:
            terminal_index = vertex_index[terminal]
            if terminal in selected:
                arcs.append((source, terminal_index, force_capacity))
            else:
                arcs.append((terminal_index, sink, force_capacity))
        entropy.append(Fraction(_maximum_flow(len(vertices) + 2, arcs, source, sink), denominator))
    return tuple(entropy)


def exact_entropy_match(
    graph: ExactGraph,
    target: Sequence[Fraction],
    n: int,
    match: Literal["ray", "exact"],
) -> dict[str, Any]:
    """Compare exact graph min-cuts with an exact target under one match mode."""

    if match not in ("ray", "exact"):
        raise ValueError("match must be 'ray' or 'exact'")
    entropy = exact_entropy_vector_mincut(graph, n)
    target_tuple = tuple(target)
    if len(entropy) != len(target_tuple):
        raise ValueError(f"expected target length {len(entropy)}, got {len(target_tuple)}")
    if match == "ray":
        max_error: int | str | None = None
        if any(target_tuple):
            pivot = next(index for index, value in enumerate(target_tuple) if value != 0)
            scale = entropy[pivot] / target_tuple[pivot] if entropy[pivot] != 0 else Fraction(0)
            ok = scale > 0 and all(
                observed == scale * expected for observed, expected in zip(entropy, target_tuple, strict=True)
            )
        else:
            ok = not any(entropy)
    else:
        exact_error = max(
            (abs(observed - expected) for observed, expected in zip(entropy, target_tuple, strict=True)),
            default=Fraction(0),
        )
        max_error = _json_weight(exact_error)
        ok = exact_error == 0
    return {
        "ok": bool(ok),
        "max_error": max_error,
        "entropy": [_json_weight(value) for value in entropy],
        "target": [_json_weight(value) for value in target_tuple],
        "verification": "exact_rational_mincut",
    }
