"""Exact capacity budgets for minimum-cut domains; never a feasibility test.

Flipping terminal t in a minimum cut S gives the necessary inequality
  2 * crossing_capacity(t,S) <= d[t] + h(S) - h(S xor {t}).
Mandatory bulk memberships yield subset upper bounds on terminal capacities.
Nonnegative capacities and their exact terminal degree sums yield cover bounds.
Bounds on the bulk edges feed back into these same minimum-cut budgets.

Bounds are represented in twice-capacity units. This does NOT require integer
or half-integer edge weights: all variables remain arbitrary nonnegative reals.
No clock, search budget, native model, or cross-target state is used here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations

import numpy as np
from numba import njit


def _single_bit_index_table():
    table = np.zeros(32, dtype=np.int64)
    for bit in range(32):
        table[(((1 << bit) * 0x077CB531) & 0xFFFFFFFF) >> 27] = bit
    if not np.array_equal(np.sort(table), np.arange(32)):
        raise RuntimeError("invalid one-hot bit-index geometry")
    table.setflags(write=False)
    return table


_BIT_INDEX = _single_bit_index_table()


@njit(cache=True, inline="always")
def single_bit_index(one):
    """Perfect hash of a nonzero one-hot 32-bit word; callers ensure that form."""
    return _BIT_INDEX[((one * 0x077CB531) & 0xFFFFFFFF) >> 27]


@njit(cache=True, inline="always")
def terminal_totals(upper, degree):
    """Exact subset DP for the same seven-terminal crossing sums.

    Terminal O stays outside every represented side. Starting with side zero,
    adding terminal t flips only that terminal's bulk-side contribution.
    """
    size = upper.shape[1]
    full = size - 1
    lower = np.empty((7, size), dtype=np.int64)
    total_lower = np.empty((64, size), dtype=np.int64)
    total_upper = np.empty((64, size), dtype=np.int64)
    for t in range(7):
        for q in range(size):
            lower[t, q] = max(0, degree[t] - upper[t, q ^ full])
    for u in range(size):
        total_lower[0, u] = total_upper[0, u] = 0
        for t in range(7):
            total_lower[0, u] += lower[t, u]
            total_upper[0, u] += upper[t, u]
    for side in range(1, 64):
        one = side & -side
        t = single_bit_index(one)
        previous = side ^ one
        for u in range(size):
            total_lower[side, u] = total_lower[previous, u] + lower[t, u ^ full] - lower[t, u]
            total_upper[side, u] = total_upper[previous, u] + upper[t, u ^ full] - upper[t, u]
    return lower, total_lower, total_upper


@njit(cache=True, inline="always")
def sparse_terminal_budgets(domain, side, inside, outside, entropy, lower_cut, total_lower, terminal_lower):
    """Evaluate the original maxima over set bits only; no choices are omitted."""
    full = terminal_lower.shape[1] - 1
    budgets = np.full(7, -1, dtype=np.int64)
    remaining = domain
    while remaining:
        one = remaining & -remaining
        u = single_bit_index(one)
        remaining ^= one
        residual = 2 * entropy - lower_cut[min(u, u ^ full)] - total_lower[u]
        for t in range(7):
            q = outside if side >> t & 1 else inside
            if q:
                crossing = (u ^ full) if side >> t & 1 else u
                budgets[t] = max(budgets[t], residual + terminal_lower[t, crossing])
    return budgets


@dataclass(frozen=True)
class CapacityPlan:
    entropy: np.ndarray
    degree_twice: np.ndarray
    crossing_caps: np.ndarray
    certificate_sha256: str


def capacity_plan(h, degrees):
    limit = np.iinfo(np.int64).max // 64
    if len(h) != 64 or len(degrees) != 7 or any(not 0 <= v <= limit for v in (*h, *degrees)):
        raise ValueError("capacity budget exceeds its exact integer range")
    if h[0] != 0 or tuple(degrees) != tuple(h[1 << t] if t < 6 else h[63] for t in range(7)):
        raise ValueError("capacity budget degree/entropy binding is inconsistent")
    entropy = np.asarray(h, dtype=np.int64).copy()
    degree = 2 * np.asarray(degrees, dtype=np.int64)
    caps = np.empty((64, 7), dtype=np.int64)
    for side in range(64):
        for terminal in range(7):
            flipped = side ^ (1 << terminal)
            if flipped & 64:
                flipped ^= 127
            caps[side, terminal] = degrees[terminal] + entropy[side] - entropy[flipped]
    digest = hashlib.sha256(entropy.tobytes() + degree.tobytes() + caps.tobytes()).hexdigest()
    for array in (entropy, degree, caps):
        array.setflags(write=False)
    return CapacityPlan(entropy, degree, caps, digest)


@njit(cache=True)
def make_memberships():
    inside = np.full(65536, 15, dtype=np.int64)
    outside = np.zeros(65536, dtype=np.int64)
    for domain in range(1, 65536):
        rest = domain & (domain - 1)
        one = domain ^ rest
        value = 0
        while (1 << value) != one:
            value += 1
        inside[domain] = inside[rest] & value
        outside[domain] = outside[rest] | value
    outside ^= 15
    return inside, outside


@lru_cache(maxsize=1)
def geometry():
    inside, outside = make_memberships()
    edges = tuple(combinations(range(4), 2))
    cuts = np.asarray(
        [sum(1 << e for e, (a, b) in enumerate(edges) if ((u >> a) & 1) != ((u >> b) & 1)) for u in range(8)],
        dtype=np.int64,
    )
    for array in (inside, outside, cuts):
        array.setflags(write=False)
    return inside, outside, cuts


@njit(cache=True)
def close_terminal_upper(upper, degree):
    """Exact monotone/subadditive closure by a subset transform and partition DP.

    First minimize each bound over supersets. Then minimize over partitions,
    considering each split only once (the anchored half contains the low bit).
    Proper parts precede their union numerically. Restricting a partition to a
    subset proves the result is still monotone, so no repeated sweep is needed.
    This is the same greatest fixed point as alternating the two old closures.
    """
    full = upper.shape[1] - 1
    for t in range(7):
        bit = 1
        while bit <= full:
            for q in range(1, full + 1):
                if not q & bit:
                    upper[t, q] = min(upper[t, q], upper[t, q | bit])
            bit <<= 1
        for q in range(1, full + 1):
            anchor = q & -q
            a = (q - 1) & q
            while a:
                if a & anchor:
                    upper[t, q] = min(upper[t, q], upper[t, a] + upper[t, q ^ a])
                a = (a - 1) & q
        if upper[t, full] < degree[t]:
            return False
    return True


@njit(cache=True)
def prune_capacity(domains, h, degree, caps, inside, outside, core_masks):
    return prune_capacity_memberships(domains, h, degree, caps, inside[domains], outside[domains], core_masks, 4)


@njit(cache=True)
def prune_capacity_memberships(domains, h, degree, caps, inside, outside, core_masks, bulk_count):
    """Return -1 on an exact contradiction, 1 on pruning, or 0 if unchanged."""
    if bulk_count not in (4, 5):
        raise ValueError("capacity propagation requires four or five bulk vertices")
    size = 1 << bulk_count
    full = size - 1
    half = size // 2
    edges = bulk_count * (bulk_count - 1) // 2
    upper = np.empty((7, size), dtype=np.int64)
    maximum = 2 * h.max()  # The original complete model clips each core edge here.
    for t in range(7):
        for q in range(size):
            upper[t, q] = degree[t] if q else 0
    for side in range(1, 64):
        if domains[side] < 0 or domains[side] >> size:
            raise ValueError("domain exceeds the validated bulk-choice width")
        if not domains[side]:
            return -1
        for t in range(7):
            cap = caps[side, t]
            if cap < 0:
                return -1
            q = outside[side] if side >> t & 1 else inside[side]
            if q and cap < upper[t, q]:
                upper[t, q] = cap
    while True:
        if not close_terminal_upper(upper, degree):
            return -1
        # All feedback reads this snapshot; any tightening repeats the closure.
        terminal_lower, total_lower, total_upper = terminal_totals(upper, degree)
        lower_cut = np.zeros(half, dtype=np.int64)
        upper_cut = np.zeros(half, dtype=np.int64)
        for k in range(1, half):
            for e in range(edges):
                if core_masks[k] >> e & 1:
                    upper_cut[k] += maximum
        for side in range(1, 64):
            common = -1
            best_upper = -1
            for u in range(size):
                k = min(u, u ^ full)
                lo, hi = total_lower[side, u], total_upper[side, u]
                # Every cut, not merely an attaining cut, obeys its entropy lower bound.
                lower_cut[k] = max(lower_cut[k], 2 * h[side] - hi)
                if domains[side] >> u & 1:
                    if common == -1:
                        common = k
                    elif common != k:
                        common = -2
                    best_upper = max(best_upper, 2 * h[side] - lo)
            # Complementary bulk sides have exactly the same core-cut capacity.
            if common >= 0:
                upper_cut[common] = min(upper_cut[common], best_upper)
        lower_edge = np.zeros(edges, dtype=np.int64)
        upper_edge = np.full(edges, maximum, dtype=np.int64)
        if lower_cut[0] > 0 or upper_cut[0] < 0:
            return -1
        while True:
            changed = False
            for k in range(1, half):
                bits = core_masks[k]
                lo = hi = 0
                for e in range(edges):
                    if bits >> e & 1:
                        lo += lower_edge[e]
                        hi += upper_edge[e]
                if lo > upper_cut[k] or hi < lower_cut[k]:
                    return -1
                for e in range(edges):
                    if not bits >> e & 1:
                        continue
                    lb = max(lower_edge[e], lower_cut[k] - (hi - upper_edge[e]))
                    ub = min(upper_edge[e], upper_cut[k] - (lo - lower_edge[e]))
                    if lb > ub:
                        return -1
                    if lb != lower_edge[e]:
                        lower_edge[e] = lb
                        changed = True
                    if ub != upper_edge[e]:
                        upper_edge[e] = ub
                        changed = True
            if not changed:
                break
        for k in range(1, half):
            lo = hi = 0
            for e in range(edges):
                if core_masks[k] >> e & 1:
                    lo += lower_edge[e]
                    hi += upper_edge[e]
            lower_cut[k] = max(lower_cut[k], lo)
            upper_cut[k] = min(upper_cut[k], hi)
            if lower_cut[k] > upper_cut[k]:
                return -1
        tightened = False
        for side in range(1, 64):
            if not (inside[side] or outside[side]):
                continue
            budgets = sparse_terminal_budgets(
                domains[side], side, inside[side], outside[side], h[side], lower_cut, total_lower[side], terminal_lower
            )
            for t in range(7):
                q = outside[side] if side >> t & 1 else inside[side]
                if not q:
                    continue
                budget = budgets[t]
                if budget < 0:
                    return -1
                if budget < upper[t, q]:
                    upper[t, q] = budget
                    tightened = True
        if not tightened:
            break
    changed = 0
    for side in range(1, 64):
        current = domains[side]
        kept = 0
        remaining = current
        while remaining:
            one = remaining & -remaining
            u = single_bit_index(one)
            remaining ^= one
            lo, hi = lower_cut[min(u, u ^ full)], upper_cut[min(u, u ^ full)]
            possible = True
            for t in range(7):
                crossing = (u ^ full) if side >> t & 1 else u
                lower = max(0, degree[t] - upper[t, crossing ^ full])
                if lower > caps[side, t]:
                    possible = False
                    break
                lo += lower
                hi += upper[t, crossing]
            if possible and lo <= 2 * h[side] <= hi:
                kept |= 1 << u
        if not kept:
            return -1
        if kept != current:
            domains[side] = kept
            changed = 1
    return changed
