"""Private exact symmetry reduction for tuples of bulk-cut masks.

For ``k`` selected subsystem cuts and ``m`` bulk vertices, a labelled tuple of
bulk masks is equivalently an ``m``-column binary matrix with ``k`` rows.
Relabelling bulk vertices permutes columns, so its orbit is classified exactly
by the histogram of the ``2**k`` possible column signatures.

Permutations of the physical terminals and purifier may additionally permute
the selected subsystem rows.  When a subsystem image contains the purifier,
canonicalization by complementarity complements that row's bulk mask.  The
``RowAction`` type represents precisely this signed row action.
"""

from __future__ import annotations

import math
import operator
from collections import Counter, deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import combinations, permutations, product

from .coordinates import infer_n, subsets


@dataclass(frozen=True, order=True)
class RowAction:
    """A signed permutation of selected subsystem rows.

    ``permutation[source]`` is the destination row.  A true entry in
    ``complements[source]`` complements that source row's bulk mask.
    """

    permutation: tuple[int, ...]
    complements: tuple[bool, ...]

    def __post_init__(self) -> None:
        permutation = _integer_tuple("row permutation", self.permutation)
        complements = tuple(self.complements)
        if any(not isinstance(value, bool) for value in complements):
            raise ValueError("row complement flags must be booleans")
        if len(permutation) != len(complements):
            raise ValueError("row permutation and complement tuples must have the same length")
        if sorted(permutation) != list(range(len(permutation))):
            raise ValueError(f"not a row permutation: {permutation!r}")
        object.__setattr__(self, "permutation", permutation)
        object.__setattr__(self, "complements", complements)

    @classmethod
    def identity(cls, row_count: int) -> RowAction:
        """Return the identity action on ``row_count`` rows."""

        _require_nonnegative_int("row_count", row_count)
        return cls(tuple(range(row_count)), (False,) * row_count)

    @property
    def row_count(self) -> int:
        return len(self.permutation)

    def then(self, other: RowAction) -> RowAction:
        """Compose this action followed by ``other``."""

        if self.row_count != other.row_count:
            raise ValueError("cannot compose row actions of different sizes")
        permutation = tuple(other.permutation[self.permutation[source]] for source in range(self.row_count))
        complements = tuple(
            self.complements[source] ^ other.complements[self.permutation[source]] for source in range(self.row_count)
        )
        return RowAction(permutation, complements)

    def transform_signature(self, signature: int) -> int:
        """Apply this action to one binary column signature."""

        clean_signature = _as_int("signature", signature)
        limit = 1 << self.row_count
        if not 0 <= clean_signature < limit:
            raise ValueError(f"signature must be in [0, {limit}), got {signature!r}")
        transformed = 0
        for source, destination in enumerate(self.permutation):
            bit = ((clean_signature >> source) & 1) ^ int(self.complements[source])
            transformed |= bit << destination
        return transformed

    def transform_histogram(self, histogram: Sequence[int]) -> tuple[int, ...]:
        """Apply this action to a column-signature histogram."""

        expected = 1 << self.row_count
        clean = _validate_histogram(histogram, expected)
        transformed = [0] * expected
        for signature, count in enumerate(clean):
            transformed[self.transform_signature(signature)] = count
        return tuple(transformed)

    def transform_masks(self, masks: Sequence[int], bulk_count: int) -> tuple[int, ...]:
        """Apply this action directly to labelled bulk masks."""

        _require_nonnegative_int("bulk_count", bulk_count)
        clean = _validate_masks(masks, bulk_count, self.row_count)
        full_mask = (1 << bulk_count) - 1
        transformed = [0] * self.row_count
        for source, destination in enumerate(self.permutation):
            mask = clean[source]
            transformed[destination] = mask ^ full_mask if self.complements[source] else mask
        return tuple(transformed)


@dataclass(frozen=True)
class BulkMaskOrbit:
    """A canonical bulk-mask representative and its exact labelled weight."""

    masks: tuple[int, ...]
    weight: int


def canonical_masks_from_histogram(histogram: Sequence[int], row_count: int | None = None) -> tuple[int, ...]:
    """Construct the deterministic mask tuple represented by ``histogram``."""

    if row_count is None:
        row_count = _signature_row_count(len(histogram))
    else:
        _require_nonnegative_int("row_count", row_count)
    clean = _validate_histogram(histogram, 1 << row_count)
    masks = [0] * row_count
    bulk_offset = 0
    for signature, count in enumerate(clean):
        if count:
            block = ((1 << count) - 1) << bulk_offset
            for row in range(row_count):
                if (signature >> row) & 1:
                    masks[row] |= block
        bulk_offset += count
    return tuple(masks)


def row_action_group(row_count: int, generators: Sequence[RowAction] = ()) -> tuple[RowAction, ...]:
    """Return the finite signed-permutation group generated by ``generators``."""

    _require_nonnegative_int("row_count", row_count)
    identity = RowAction.identity(row_count)
    clean_generators = tuple(generators)
    if any(generator.row_count != row_count for generator in clean_generators):
        raise ValueError("row action has the wrong row count")

    group = {identity}
    pending = deque([identity])
    while pending:
        action = pending.popleft()
        for generator in clean_generators:
            for composed in (action.then(generator), generator.then(action)):
                if composed not in group:
                    group.add(composed)
                    pending.append(composed)
    return tuple(sorted(group))


def quotient_bulk_mask_orbits(
    bulk_count: int,
    row_count: int,
    actions: Sequence[RowAction],
) -> Iterator[BulkMaskOrbit]:
    """Yield bulk-mask orbits modulo a signed row-action group.

    Each returned ``weight`` counts all labelled mask tuples in the combined
    class.  Consequently, the weights sum to ``2**(bulk_count * row_count)``.
    """

    _require_nonnegative_int("bulk_count", bulk_count)
    _require_nonnegative_int("row_count", row_count)
    group = row_action_group(row_count, actions)
    seen: set[tuple[int, ...]] = set()
    for histogram in _weak_compositions(bulk_count, 1 << row_count):
        if histogram in seen:
            continue
        orbit = {action.transform_histogram(histogram) for action in group}
        seen.update(orbit)
        representative = min(orbit)
        if histogram != representative:
            continue
        yield BulkMaskOrbit(
            masks=canonical_masks_from_histogram(representative, row_count),
            weight=sum(_histogram_weight(member) for member in orbit),
        )


def extended_terminal_automorphisms(entropy_vector: Sequence[object]) -> tuple[tuple[int, ...], ...]:
    """Return exact terminal permutations preserving an entropy vector.

    The vector follows HEC's cardinality-then-lexicographic ordering of
    nonempty physical-party subsets.  Permutations act on physical terminals
    ``0..n-1`` and purifier ``n``; purifier-containing images are evaluated by
    complementarity.
    """

    values_tuple = tuple(entropy_vector)
    party_count = infer_n(len(values_tuple))
    physical_masks = tuple(_subsystem_mask(subset) for subset in subsets(party_count))
    values = dict(zip(physical_masks, values_tuple, strict=True))
    terminals = tuple(range(party_count + 1))
    automorphisms: list[tuple[int, ...]] = []
    for permutation in permutations(terminals):
        if all(
            _exactly_equal(
                value,
                0
                if (
                    canonical := _canonical_physical_mask(
                        _permute_extended_mask(subsystem_mask, permutation), party_count
                    )
                )
                == 0
                else values[canonical],
            )
            for subsystem_mask, value in values.items()
        ):
            automorphisms.append(tuple(permutation))
    if not automorphisms:
        raise ValueError("entropy vector is not preserved by the identity permutation")
    return tuple(automorphisms)


def transform_subsystem_mask(
    subsystem_mask: int,
    automorphism: Sequence[int],
    party_count: int | None = None,
) -> tuple[int, bool]:
    """Transform a physical subsystem and report purifier complementation."""

    permutation = _validate_terminal_permutation(automorphism, party_count)
    if party_count is None:
        party_count = len(permutation) - 1
    full_physical_mask = (1 << party_count) - 1
    clean_mask = _as_int("subsystem mask", subsystem_mask)
    if not 0 < clean_mask <= full_physical_mask:
        raise ValueError(f"subsystem mask must be in [1, {full_physical_mask}], got {subsystem_mask!r}")
    image = _permute_extended_mask(clean_mask, permutation)
    complemented = bool(image & (1 << party_count))
    return _canonical_physical_mask(image, party_count), complemented


def setwise_stabilizer_actions(
    selected_subsystems: Sequence[int],
    automorphisms: Sequence[Sequence[int]],
    *,
    party_count: int | None = None,
) -> tuple[RowAction, ...]:
    """Return signed row actions induced by a selected tuple's stabilizer."""

    selected = tuple(_as_int("selected subsystem mask", value) for value in selected_subsystems)
    automorphisms = tuple(tuple(automorphism) for automorphism in automorphisms)
    if party_count is None:
        if not automorphisms:
            raise ValueError("party_count is required when automorphisms is empty")
        party_count = len(automorphisms[0]) - 1
    _require_nonnegative_int("party_count", party_count)
    full_physical_mask = (1 << party_count) - 1
    if any(not 0 < subsystem <= full_physical_mask for subsystem in selected):
        raise ValueError(f"selected subsystem masks must be in [1, {full_physical_mask}]")

    target_positions = {
        subsystem: tuple(index for index, value in enumerate(selected) if value == subsystem)
        for subsystem in set(selected)
    }
    selected_counter = Counter(selected)
    actions: set[RowAction] = set()
    for raw_automorphism in automorphisms:
        automorphism = _validate_terminal_permutation(raw_automorphism, party_count)
        mapped = tuple(transform_subsystem_mask(subsystem, automorphism, party_count) for subsystem in selected)
        mapped_masks = tuple(mask for mask, _complemented in mapped)
        if Counter(mapped_masks) != selected_counter:
            continue
        complements = tuple(complemented for _mask, complemented in mapped)

        source_groups: list[tuple[tuple[int, ...], tuple[tuple[int, ...], ...]]] = []
        for subsystem in sorted(target_positions):
            sources = tuple(index for index, value in enumerate(mapped_masks) if value == subsystem)
            source_groups.append((sources, tuple(permutations(target_positions[subsystem]))))
        for matching in product(*(matches for _sources, matches in source_groups)):
            row_permutation = [-1] * len(selected)
            for (sources, _matches), destinations in zip(source_groups, matching, strict=True):
                for source, destination in zip(sources, destinations, strict=True):
                    row_permutation[source] = destination
            actions.add(RowAction(tuple(row_permutation), complements))

    return tuple(sorted(actions))


def _as_int(name: str, value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    try:
        return operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _integer_tuple(name: str, values: Sequence[object]) -> tuple[int, ...]:
    return tuple(_as_int(name, value) for value in values)


def _require_nonnegative_int(name: str, value: object) -> None:
    clean = _as_int(name, value)
    if clean < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")


def _validate_masks(masks: Sequence[int], bulk_count: int, row_count: int) -> tuple[int, ...]:
    clean = _integer_tuple("bulk mask", masks)
    if len(clean) != row_count:
        raise ValueError(f"expected {row_count} masks, got {len(clean)}")
    limit = 1 << bulk_count
    if any(not 0 <= mask < limit for mask in clean):
        raise ValueError(f"bulk masks must be in [0, {limit})")
    return clean


def _validate_histogram(histogram: Sequence[int], expected_length: int) -> tuple[int, ...]:
    clean = _integer_tuple("histogram count", histogram)
    if len(clean) != expected_length:
        raise ValueError(f"expected histogram length {expected_length}, got {len(clean)}")
    if any(count < 0 for count in clean):
        raise ValueError("histogram counts must be non-negative integers")
    return clean


def _signature_row_count(signature_count: int) -> int:
    if signature_count < 1 or signature_count & (signature_count - 1):
        raise ValueError("histogram length must be a positive power of two")
    return signature_count.bit_length() - 1


def _histogram_weight(histogram: Sequence[int]) -> int:
    weight = math.factorial(sum(histogram))
    for count in histogram:
        weight //= math.factorial(count)
    return weight


def _weak_compositions(total: int, parts: int) -> Iterator[tuple[int, ...]]:
    if parts == 1:
        yield (total,)
        return
    for bars in combinations(range(total + parts - 1), parts - 1):
        previous = -1
        counts: list[int] = []
        for bar in bars:
            counts.append(bar - previous - 1)
            previous = bar
        counts.append(total + parts - 2 - previous)
        yield tuple(counts)


def _subsystem_mask(subsystem: Sequence[int]) -> int:
    return sum(1 << party for party in subsystem)


def _validate_terminal_permutation(
    automorphism: Sequence[int],
    party_count: int | None,
) -> tuple[int, ...]:
    permutation = _integer_tuple("terminal permutation entry", automorphism)
    if party_count is None:
        if not permutation:
            raise ValueError("terminal permutation cannot be empty")
        party_count = len(permutation) - 1
    _require_nonnegative_int("party_count", party_count)
    expected = party_count + 1
    if len(permutation) != expected or sorted(permutation) != list(range(expected)):
        raise ValueError(f"not a permutation of {expected} extended terminals: {permutation!r}")
    return permutation


def _permute_extended_mask(mask: int, permutation: Sequence[int]) -> int:
    transformed = 0
    for source, destination in enumerate(permutation):
        if (mask >> source) & 1:
            transformed |= 1 << destination
    return transformed


def _canonical_physical_mask(extended_mask: int, party_count: int) -> int:
    full_physical_mask = (1 << party_count) - 1
    physical_mask = extended_mask & full_physical_mask
    return full_physical_mask ^ physical_mask if extended_mask & (1 << party_count) else physical_mask


def _exactly_equal(left: object, right: object) -> bool:
    try:
        return bool(left == right)
    except (TypeError, ValueError) as exc:
        raise ValueError("entropy entries must support scalar exact equality") from exc
