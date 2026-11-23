"""Replay both vertex bounds for the six-party pentagon (+034) with integer cut inequalities.

Normalize any realizing graph to the primitive ray by scaling its nonnegative capacities.
For each terminal contract its inclusion-minimal optimal singleton shore. Minimal optimal
shores for nested terminal sets are nested (uncross by intersection and union); for disjoint
sets they are disjoint (uncross by the two set differences). Thus these contractions preserve
an optimum for every split and do not add vertices. Terminal degrees now equal the singleton
entropies. Pair additivity forces terminal-terminal weights to vanish: a terminal-only pair
cut has cost the sum of its degrees minus twice its internal weight.

Whenever either side of a split has additive entropy, its terminal-only cut therefore attains
it. Pick an optimal shore for each of the five remaining splits. Bulk vertices with identical
membership in those five shores can be identified: no chosen cut is lost and identifying
vertices cannot lower a cut minimum. Add absent types as isolated placeholders. A realization
on at most 19 vertices would occupy at most 12 of the 32 bulk types. Nothing here requires
the realizing graph to have the symmetry of the ray or integral weights.
"""

import json
from fractions import Fraction
from hashlib import sha256
from itertools import combinations, permutations
from math import comb
from pathlib import Path

from hec.count_proofs import canonical_json
from hec.graph_store import GraphCatalog
from hec.ray_store import read_rays

HERE = Path(__file__).resolve().parent
LEDGER = HERE / "six-party-section-ray-certificates.json"
CERTIFICATE = HERE / "pentagon-minimum-20.json"
TARGET_SHA256 = "4fe160a815c77ff79c5a8cbf5536f62d6172c060d52b57c14c8c548e084ebb19"
TERMINALS = "ABCDEFO"  # O is the purifier.
TERMINAL_MASK = (1 << 7) - 1
TYPE_COUNT = 32
TYPE_MASK = (1 << TYPE_COUNT) - 1
ALL_VERTICES = (TYPE_MASK << 7) | TERMINAL_MASK
BULK_BUDGET = 12
SPLITS = [sum(1 << i for i in group) for size in range(1, 7) for group in combinations(range(6), size)]


def bits(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def crosses(shore, i, j):
    return ((shore >> i) ^ (shore >> j)) & 1


def signature_model(ray, declared_axes):
    """Construct optimum cuts on seven terminals and one placeholder per possible bulk type."""
    entropy = {0: 0, TERMINAL_MASK: 0}
    for shore, value in zip(SPLITS, ray, strict=True):
        entropy[shore] = entropy[TERMINAL_MASK ^ shore] = value
    degree_sum = {shore: sum(entropy[1 << i] for i in bits(shore)) for shore in entropy}
    if any(entropy[s] != degree_sum[s] for s in entropy if s.bit_count() == 2):
        raise ValueError("pair additivity required for terminal-only cuts")
    small = [s if s.bit_count() <= 3 else TERMINAL_MASK ^ s for s in SPLITS]
    axes = [s for s in small if entropy[s] not in (degree_sum[s], degree_sum[TERMINAL_MASK ^ s])]
    if axes != declared_axes or 1 << len(axes) != TYPE_COUNT:
        raise ValueError("wrong cut-signature axes")
    known = {0, ALL_VERTICES}
    for s in small:
        shore = s
        if s in axes:
            bit = 1 << axes.index(s)
            shore |= sum(1 << (7 + t) for t in range(TYPE_COUNT) if t & bit)
        elif entropy[s] != degree_sum[s]:
            shore |= TYPE_MASK << 7  # The complementary terminal-only cut attains the target.
        known.update((shore, ALL_VERTICES ^ shore))
    return entropy, axes, known


def uncross(entropy, known):
    """Tight submodularity certifies two more optimal cuts and a rectangle of zero-weight edges."""
    forbidden = [0] * 39
    for _ in range(4):  # Four rounds suffice for this certificate; closure is not assumed.
        derived, rectangles = set(), set()
        for x, y in combinations(known, 2):
            a, b = x & TERMINAL_MASK, y & TERMINAL_MASK
            if entropy[a] + entropy[b] != entropy[a & b] + entropy[a | b]:
                continue
            derived.update((x & y, x | y))
            # c(x)+c(y)-c(x&y)-c(x|y) = 2*w(x\y, y\x).
            left, right = x & ~y, y & ~x
            if left and right:
                rectangles.add((min(left, right), max(left, right)))
        for left, right in rectangles:
            for i in bits(left):
                forbidden[i] |= right
            for j in bits(right):
                forbidden[j] |= left
        known.update(derived)

    # Each remaining edge is bounded by the cost of every known optimum it crosses.
    return {
        (i, j): min(entropy[s & TERMINAL_MASK] for s in known if crosses(s, i, j))
        for i, j in combinations(range(39), 2)
        if j >= 7 and not forbidden[i] & (1 << j)
    }


def type_actions(entropy, axes):
    """Permute obligations on the target, not vertices of an assumed symmetric realization."""
    for perm in permutations(range(7)):
        if any(entropy[1 << i] != entropy[1 << j] for i, j in enumerate(perm)):
            continue
        image = {s: sum(1 << perm[i] for i in bits(s)) for s in entropy}
        if all(entropy[s] == entropy[t] for s, t in image.items()):
            axes_image = [axes.index(image[s]) for s in axes]
            yield [sum(1 << axes_image[i] for i in bits(t)) for t in range(TYPE_COUNT)]


def hitting_clauses(certificate, entropy, axes, known, bounds):
    """A strict integer separation excludes even the superset of types allowed by its mask."""
    actions = list(type_actions(entropy, axes))
    clauses = set()
    for index, dual in enumerate(certificate["duals"]):
        terms = dual["terms"]
        for shore, weight in terms:
            if type(shore) is not int or not 0 <= shore <= ALL_VERTICES or type(weight) is not int or not weight:
                raise ValueError(f"invalid signed cut in separation {index}")
            if weight < 0 and shore not in known:
                raise ValueError(f"negative coefficient on an unproved optimum in separation {index}")
        # Every cut costs at least its target; a negative multiplier needs equality.
        required = sum(weight * entropy[shore & TERMINAL_MASK] for shore, weight in terms)
        edge_max = {
            (i, j): cap * max(0, sum(weight for shore, weight in terms if crosses(shore, i, j)))
            for (i, j), cap in bounds.items()
        }
        for allowed in dual["forbidden_present_masks"]:
            if type(allowed) is not int or not 0 <= allowed < TYPE_MASK:
                raise ValueError(f"invalid allowed type mask in separation {index}")
            enabled = (allowed << 7) | TERMINAL_MASK
            possible = sum(v for (i, j), v in edge_max.items() if (enabled >> i) & (enabled >> j) & 1)
            if possible >= required:
                raise ValueError(f"separation {index} does not exclude type mask {allowed:#x}")
            # At least one type OUTSIDE 'allowed' must be occupied.
            for action in actions:
                clauses.add(sum(1 << action[t] for t in bits(TYPE_MASK ^ allowed)))
    return clauses


def exclude_small_supports(clauses):
    """Enumerate all 12-subsets in two 16-bit halves. Any smaller hitting set extends to 12."""
    half = TYPE_COUNT // 2
    half_mask = (1 << half) - 1
    by_size = [[] for _ in range(BULK_BUDGET + 1)]
    for mask in range(1 << half):
        if mask.bit_count() <= BULK_BUDGET:
            by_size[mask.bit_count()].append(mask)

    checked = 0
    for low_size, lows in enumerate(by_size):
        highs = by_size[BULK_BUDGET - low_size]
        # Bit j represents the j-th high half. Intersect these bitsets only for
        # clauses not already hit by the fixed low half.
        containing = [0] * half
        for j, mask in enumerate(highs):
            for i in bits(mask):
                containing[i] |= 1 << j
        filters = []
        for clause in clauses:
            hits = 0
            for i in bits(clause >> half):
                hits |= containing[i]
            filters.append((clause & half_mask, hits))
        filters.sort(key=lambda pair: pair[1].bit_count())
        all_highs = (1 << len(highs)) - 1
        for low in lows:
            live = all_highs
            for low_bits, high_hits in filters:
                if not low & low_bits:
                    live &= high_hits
                    if not live:
                        break
            if live:
                support = low | (highs[next(bits(live))] << half)
                raise ValueError(f"certificate leaves a 12-type support: {support:#x}")
        checked += len(lows) * len(highs)
    if checked != comb(TYPE_COUNT, BULK_BUDGET):
        raise ValueError("incomplete enumeration of bulk supports")
    return checked


def paired_graph(row):
    """Resolve the core pair even after later insertions shift its original index."""
    directory = HERE.parent / "data" / "n=6"
    index_file = directory / "rays.json"
    rays = read_rays(index_file, 6)
    target = tuple(row["ray"])
    index = row["catalogue_index"]
    if sha256(index_file.read_bytes()).hexdigest() != row["ray_index_sha256"]:
        index = next((i for i, ray in enumerate(rays) if ray == target), None)
    if type(index) is not int or not 0 <= index < len(rays) or rays[index] != target:
        raise ValueError("pentagon core ray is missing or misbound")
    graph = GraphCatalog(directory / "graphs.json")[index]
    if sha256(canonical_json(graph)).hexdigest() != row["graph_sha256"]:
        raise ValueError("pentagon core graph differs from the certified witness")
    return graph


def check_witness(row, graph):
    """Minimize over all 8,192 bulk assignments for each split of the core graph."""
    labels = {name: i for i, name in enumerate([*TERMINALS, *(f"x{i}" for i in range(1, 14))])}
    if {v for edge in graph["edges"] for v in edge} != labels.keys():
        raise ValueError("witness must use seven terminals and thirteen bulk vertices")
    edges = []
    for (a, b), w in zip(graph["edges"], graph["weights"], strict=True):
        if a == b or type(w) is not int or w <= 0:
            raise ValueError("invalid witness edge or weight")
        edges.append((labels[a], labels[b], w))
    scale = Fraction(row["entropy_scale"])
    if scale <= 0 or len(edges) != row["edge_count"]:
        raise ValueError("invalid witness metadata")
    assignments = 1 << (len(labels) - len(TERMINALS))
    for terminals, value in zip(SPLITS, row["ray"], strict=True):
        shores = (terminals | (bulk << 7) for bulk in range(assignments))
        minimum = min(sum(w for i, j, w in edges if ((s >> i) ^ (s >> j)) & 1) for s in shores)
        if minimum != scale * value:
            raise ValueError(f"witness min-cut mismatch on terminal mask {terminals:#x}")
    return len(SPLITS) * assignments


def verify():
    ledger = json.loads(LEDGER.read_bytes())
    (row,) = (r for r in ledger["rays"] if r["key"] == "034")
    exclusion = row["exclusion"]
    payload = CERTIFICATE.read_bytes()
    if exclusion["certificate"] != CERTIFICATE.name or exclusion["result_sha256"] != sha256(payload).hexdigest():
        raise ValueError("ledger does not bind this certificate")
    cert = json.loads(payload)
    ray = row["ray"]
    if len(ray) != len(SPLITS) or not all(type(v) is int and v > 0 for v in ray):
        raise ValueError("invalid pentagon ray")
    digest = sha256(",".join(map(str, ray)).encode()).hexdigest()
    if not digest == TARGET_SHA256 == cert["target_sha256"] == exclusion["target_sha256"]:
        raise ValueError("certificate and ledger must refer to the +034 ray")
    if cert["format"] != "hec-normalized-cut-support-exclusion-v1":
        raise ValueError("unknown certificate format")
    entropy, axes, known = signature_model(ray, cert["free_small_masks"])
    bounds = uncross(entropy, known)
    clauses = hitting_clauses(cert, entropy, axes, known, bounds)
    supports = exclude_small_supports(clauses)
    cuts = check_witness(row, paired_graph(row))
    minimum = len(TERMINALS) + BULK_BUDGET + 1
    if not (
        row["minimum_total_vertices"] == row["lower_bound"] == row["total_vertices"] == minimum
        and row["minimality_status"] == "certified_minimal"
        and exclusion["maximum_total_vertices"] == minimum - 1
        and exclusion["method"] == "normalized_cut_support"
        and exclusion["status"] == "UNSAT"
    ):
        raise ValueError("ledger claim differs from the verified vertex bounds")
    return supports, cuts, minimum


if __name__ == "__main__":
    supports, cuts, minimum = verify()
    print(f"+034: excluded {supports:,} twelve-type supports; checked {cuts:,} witness cuts; exact minimum {minimum}.")
