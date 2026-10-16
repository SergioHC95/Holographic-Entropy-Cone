"""Deterministic complete proof-work partitions, independent of storage size."""

import heapq
from fractions import Fraction

from .count_proofs import decimal


def proof_work(entry):
    """Scheduling estimate only; never a mathematical acceptance criterion."""
    coefficients = tuple(map(decimal, entry["coefficients"]))
    axes = sum(value > 0 for value in coefficients)
    groups = max(1, sum(value < 0 for value in coefficients))
    vertices = 1 << axes
    edges = axes * (vertices // 2)
    return groups * (edges + vertices) + (1 << 18)


def proof_groups(catalog, inequalities, groups):
    """Balance complete maps while keeping downloads local to storage shards.

    A storage shard can feed multiple disjoint audit jobs. No map is split,
    omitted or audited twice. Weights affect scheduling only, not verification.
    """
    if type(groups) is not int or not 1 <= groups <= len(catalog):
        raise ValueError("invalid complete proof partition count")
    inequalities.check_bindings(catalog)
    members = {key: [] for key in catalog.shards}
    weights = {}
    for index, entry in enumerate(catalog.entries):
        weights[index] = proof_work(inequalities.entries[entry["inequality_id"]])
        members[entry["shard"]].append(index)
    totals = {key: sum(weights[index] for index in indices) for key, indices in members.items()}
    result = [[] for _ in range(groups)]

    if groups < len(members):
        heap = [(0, 0, index) for index in range(groups)]
        for key in sorted(members, key=lambda key: (-totals[key], key)):
            cost, count, target = heapq.heappop(heap)
            result[target].extend(members[key])
            heapq.heappush(heap, (cost + totals[key], count + len(members[key]), target))
    else:
        splits = dict.fromkeys(members, 1)
        for _ in range(groups - len(members)):
            available = [key for key in members if splits[key] < len(members[key])]
            key = min(available, key=lambda key: (-Fraction(totals[key], splits[key]), key))
            splits[key] += 1
        offset = 0
        for key in sorted(members):
            heap = [(0, 0, offset + index) for index in range(splits[key])]
            for index in sorted(members[key], key=lambda index: (-weights[index], catalog.entries[index]["proof_id"])):
                cost, count, target = heapq.heappop(heap)
                result[target].append(index)
                heapq.heappush(heap, (cost + weights[index], count + 1, target))
            offset += splits[key]

    for indices in result:
        indices.sort()
    flattened = [index for indices in result for index in indices]
    if (
        any(not indices for indices in result)
        or len(flattened) != len(catalog)
        or set(flattened) != set(range(len(catalog)))
    ):
        raise ValueError("incomplete or duplicate complete-proof ownership")
    return result


def partition_entries(catalog, inequalities, group, groups):
    if type(group) is not int or type(groups) is not int or not 0 <= group < groups:
        raise ValueError("invalid complete proof partition index")
    return proof_groups(catalog, inequalities, groups)[group]
