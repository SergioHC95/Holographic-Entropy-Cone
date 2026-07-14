"""Private exact graph-model deductions from tight entropy submodularity.

An equality cut is represented by its physical boundary subset ``A`` and a
bit mask selecting bulk vertices.  The corresponding vertex side is

``W_A = A union {n + bit: bit is set in bulk_mask}``.

The purifier, vertex ``N - 1``, is always on the other side.  For two known
equality cuts, the cut-capacity identity is

``c(W_A) + c(W_B) = c(W_A intersection W_B)``
``                       + c(W_A union W_B)``
``                       + 2 c(E(W_A \\ W_B, W_B \\ W_A)).``

If the target entropy is tight for the same submodularity relation, cut
minimality forces the intersection and union to be equality cuts.  It also
forces every edge between the two opposite Venn regions to have zero weight.
Repeatedly applying this argument gives the finite fixed-point closure below.

No numerical tolerance is used.  Floats are interpreted as their exact binary
rational values, so floating-point addition cannot create a false equality.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from numbers import Integral, Real
from typing import TypeAlias

Edge: TypeAlias = tuple[int, int]


@dataclass(frozen=True, slots=True)
class EqualityCut:
    """A cut known to attain the target entropy for ``boundary``.

    ``boundary`` contains physical-party indices in ``range(n)``.  Bit
    ``offset`` of ``bulk_mask`` represents graph vertex ``n + offset``.  The
    empty physical boundary is valid and has target value zero.
    """

    boundary: frozenset[int]
    bulk_mask: int

    def __post_init__(self) -> None:
        try:
            boundary = frozenset(self.boundary)
        except TypeError as exc:
            raise TypeError("equality-cut boundary must be an iterable of integers") from exc
        if any(not isinstance(vertex, Integral) or isinstance(vertex, bool) for vertex in boundary):
            raise TypeError("equality-cut boundary indices must be integers")
        if not isinstance(self.bulk_mask, Integral) or isinstance(self.bulk_mask, bool):
            raise TypeError("equality-cut bulk mask must be an integer")
        object.__setattr__(self, "boundary", frozenset(int(vertex) for vertex in boundary))
        object.__setattr__(self, "bulk_mask", int(self.bulk_mask))


EqualityCutLike: TypeAlias = EqualityCut | tuple[Iterable[int], int]


@dataclass(frozen=True, slots=True)
class TightSubmodularityResult:
    """Fixed-point deductions from a collection of known equality cuts."""

    known_cuts: frozenset[EqualityCut]
    derived_cuts: frozenset[EqualityCut]
    forced_zero_edges: frozenset[Edge]

    @property
    def all_cuts(self) -> frozenset[EqualityCut]:
        """Return the known and derived equality cuts together."""

        return self.known_cuts | self.derived_cuts


def close_tight_submodularity(
    n: int,
    N: int,
    target: Sequence[Real],
    equality_cuts: Iterable[EqualityCutLike],
) -> TightSubmodularityResult:
    """Close equality cuts under exact tight-submodularity deductions.

    ``target`` uses the repository's cardinality-then-lexicographic ordering
    of nonempty physical subsets.  Every comparison is exact.

    For a processed pair, cut submodularity and feasibility of the
    intersection and union give

    ``h(A)+h(B) >= c(W_A inter W_B)+c(W_A union W_B)``
    ``            >= h(A inter B)+h(A union B).``

    Equality of the endpoints forces equality throughout.  The cut identity
    in the module docstring then makes every nonnegative edge between the
    opposite Venn regions individually zero.  Adding the derived equality
    cuts and repeating is sound by induction.  Termination follows from the
    finite number of represented cuts.
    """

    n, target_values, subset_index, bulk_count = _validate_problem(n, N, target)
    known = frozenset(_normalize_cut(cut, n, bulk_count) for cut in equality_cuts)
    closure = set(known)
    pending = deque(known)
    processed_pairs: set[frozenset[EqualityCut]] = set()
    forced_zero_edges: set[Edge] = set()

    while pending:
        left = pending.popleft()
        for right in tuple(closure):
            if left == right:
                continue
            pair_key = frozenset((left, right))
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            intersection_boundary = left.boundary & right.boundary
            union_boundary = left.boundary | right.boundary
            if not _is_tight(
                target_values,
                subset_index,
                left.boundary,
                right.boundary,
                intersection_boundary,
                union_boundary,
            ):
                continue

            intersection_cut = EqualityCut(intersection_boundary, left.bulk_mask & right.bulk_mask)
            union_cut = EqualityCut(union_boundary, left.bulk_mask | right.bulk_mask)
            for derived in (intersection_cut, union_cut):
                if derived not in closure:
                    closure.add(derived)
                    pending.append(derived)

            left_vertices = _cut_vertices(left, n, bulk_count)
            right_vertices = _cut_vertices(right, n, bulk_count)
            forced_zero_edges.update(_cross_pairs(left_vertices - right_vertices, right_vertices - left_vertices))

    return TightSubmodularityResult(
        known_cuts=known,
        derived_cuts=frozenset(closure - set(known)),
        forced_zero_edges=frozenset(forced_zero_edges),
    )


def _validate_problem(
    n: int,
    N: int,
    target: Sequence[Real],
) -> tuple[int, tuple[Fraction, ...], dict[frozenset[int], int], int]:
    if not isinstance(n, Integral) or isinstance(n, bool) or int(n) < 1:
        raise ValueError("n must be a positive integer")
    if not isinstance(N, Integral) or isinstance(N, bool) or int(N) < int(n) + 1:
        raise ValueError("N must be an integer at least n + 1")
    n = int(n)
    N = int(N)
    raw_target = tuple(target)
    expected = (1 << n) - 1
    if len(raw_target) != expected:
        raise ValueError(f"target must have length {expected} for n={n}, got {len(raw_target)}")

    target_values: list[Fraction] = []
    for value in raw_target:
        if not isinstance(value, Real) or isinstance(value, bool):
            raise TypeError("target values must be real numbers")
        try:
            exact_value = _exact_fraction(value)
        except (OverflowError, ValueError, ZeroDivisionError) as exc:
            raise ValueError("target values must be finite") from exc
        if exact_value < 0:
            raise ValueError("target values must be nonnegative")
        target_values.append(exact_value)

    ordered_subsets = tuple(frozenset(subset) for size in range(1, n + 1) for subset in combinations(range(n), size))
    subset_index = {subset: index for index, subset in enumerate(ordered_subsets)}
    return n, tuple(target_values), subset_index, N - n - 1


def _exact_fraction(value: Real) -> Fraction:
    if isinstance(value, Integral):
        return Fraction(int(value), 1)
    try:
        numerator, denominator = value.as_integer_ratio()
    except AttributeError:
        return Fraction(value)
    return Fraction(int(numerator), int(denominator))


def _normalize_cut(cut: EqualityCutLike, n: int, bulk_count: int) -> EqualityCut:
    if isinstance(cut, EqualityCut):
        normalized = cut
    else:
        try:
            boundary, bulk_mask = cut
        except (TypeError, ValueError) as exc:
            raise TypeError("equality cuts must be EqualityCut objects or (boundary, bulk_mask) pairs") from exc
        normalized = EqualityCut(frozenset(boundary), bulk_mask)

    if any(vertex < 0 or vertex >= n for vertex in normalized.boundary):
        raise ValueError(f"equality-cut boundary indices must be in range({n})")
    if normalized.bulk_mask < 0 or normalized.bulk_mask >= (1 << bulk_count):
        raise ValueError(f"equality-cut bulk mask must fit in {bulk_count} bits")
    return normalized


def _entropy_value(
    target: tuple[Fraction, ...],
    subset_index: dict[frozenset[int], int],
    boundary: frozenset[int],
) -> Fraction:
    return Fraction(0) if not boundary else target[subset_index[boundary]]


def _is_tight(
    target: tuple[Fraction, ...],
    subset_index: dict[frozenset[int], int],
    left: frozenset[int],
    right: frozenset[int],
    intersection: frozenset[int],
    union: frozenset[int],
) -> bool:
    return bool(
        _entropy_value(target, subset_index, left) + _entropy_value(target, subset_index, right)
        == _entropy_value(target, subset_index, intersection) + _entropy_value(target, subset_index, union)
    )


def _cut_vertices(cut: EqualityCut, n: int, bulk_count: int) -> frozenset[int]:
    bulk = (n + offset for offset in range(bulk_count) if (cut.bulk_mask >> offset) & 1)
    return cut.boundary | frozenset(bulk)


def _cross_pairs(left: frozenset[int], right: frozenset[int]) -> set[Edge]:
    return {(min(u, v), max(u, v)) for u in left for v in right}
