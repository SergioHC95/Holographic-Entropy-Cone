r"""Exact finite-domain propagation for inclusion-minimal graph cuts.

Minimal cuts form a monotone map on terminal sets and cuts for disjoint
terminal sets are disjoint. When entropy submodularity is tight, the union
of two minimal cuts is a minimum cut for the union. It contains that union's
unique minimal cut and is contained in it by monotonicity, hence they coincide.
Only these necessary properties are propagated; nonempty domains are never
treated as graph realizations or proofs of feasibility.

With no terminal-terminal edges, a fixed bulk side has cut capacity affine in
the terminal indicator vector. Complementary bulk sides have opposite slopes.
Balanced sums of entropy lower bounds therefore certify pairs of cuts that
cannot use equal or complementary bulk sides. Each exclusion is backed by an
explicit integer pair witness, checked before any domains are pruned.

Terminal exchanges also force bulk-cut regions to be nonempty. If U_A is
contained in U_B, moving T contained in A\B from A to B cannot increase the
sum of capacities: the difference is twice the nonnegative capacity from T
to U_B\U_A. A strict entropy increase therefore forces U_A\U_B nonempty.
Complement either cut to obtain the other three quadrant rules. These too
carry exact integer witnesses. Support images are immutable finite tables,
not cached target-specific domains or reusable native solver state.

At every branch, quotient cut choices by permutations of bulk vertices with
identical fixed-cut signatures. There is no competing capacity ordering.
Native-created branches disable this quotient for their entire subtrees.
Four-bulk search only; no clocks, weight integrality, or cross-case solver state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations

import numpy as np
import pyscipopt
from numba import njit
from pyscipopt import SCIP_RESULT

from ._graph_capacity import CapacityPlan, capacity_plan, prune_capacity
from ._graph_capacity import geometry as capacity_geometry


@njit(cache=True)
def make_join_tables():
    image = np.zeros((16, 65536), dtype=np.uint16)
    preimage = np.zeros((16, 65536), dtype=np.uint16)
    single = np.zeros((16, 16), dtype=np.uint16)
    for a in range(16):
        for b in range(16):
            single[a, a | b] |= 1 << b
        for mask in range(1, 65536):
            rest = mask & (mask - 1)
            one = mask ^ rest
            b = 0
            while (1 << b) != one:
                b += 1
            image[a, mask] = image[a, rest] | (1 << (a | b))
            preimage[a, mask] = preimage[a, rest] | single[a, b]
    return image, preimage


@lru_cache(maxsize=1)
def tables():
    result = make_join_tables()
    for array in result:
        array.setflags(write=False)
    return result


@lru_cache(maxsize=1)
def affine_geometry():
    """Carry-free ternary codes for terminal sums/differences; exact supports.

    Relation flags are nested (1), disjoint (2), unequal (4), not opposite (8),
    and nonempty A-only/B-only/common/outside quadrants (16/32/64/128).
    Combine flags before arc consistency, not as separate weaker relations.
    """
    powers = 3 ** np.arange(6, dtype=np.int64)
    bits = np.asarray([[(s >> t) & 1 for t in range(6)] for s in range(64)])
    codes = np.empty((2, 64, 64), dtype=np.int64)
    for a in range(64):
        for b in range(64):
            codes[0, a, b] = (bits[a] + bits[b]) @ powers
            codes[1, a, b] = (bits[a] - bits[b] + 1) @ powers
    support = np.zeros((2, 256, 16), dtype=np.int64)
    for flags in range(256):
        for a in range(16):
            for b in range(16):
                good = (not flags & 1 or a & b == a) and (not flags & 2 or not a & b)
                good = good and (not flags & 4 or a != b) and (not flags & 8 or a != (b ^ 15))
                good = good and (not flags & 16 or bool(a & ~b)) and (not flags & 32 or bool(b & ~a))
                good = good and (not flags & 64 or bool(a & b)) and (not flags & 128 or bool(15 & ~(a | b)))
                if good:
                    support[0, flags, a] |= 1 << b
                    support[1, flags, b] |= 1 << a
    codes.setflags(write=False)
    support.setflags(write=False)
    return codes, support


@njit(cache=True)
def affine_pair_bounds(h, codes):
    """Max-plus bounds with explicit attaining terminal-pair witnesses.

    If U minimizes A and B, then h(A)+h(B) = C_U(A)+C_U(B) must be at least
    h(C)+h(D) for every 1_A+1_B = 1_C+1_D. If U minimizes A and its complement
    minimizes B, use 1_A-1_B = 1_C-1_D instead: complementary cut capacities
    have opposite terminal slopes and their constant sum is independent of S.
    A strict violation therefore forbids the corresponding bulk-side pair.
    No converse is assumed; remaining domains still require the full solver.
    """
    bounds = np.full((2, 729), -1, dtype=np.int64)
    witnesses = np.zeros((2, 729, 2), dtype=np.uint8)
    for a in range(64):
        for b in range(64):
            value = h[a] + h[b]
            for kind in range(2):
                code = codes[kind, a, b]
                if value > bounds[kind, code]:
                    bounds[kind, code] = value
                    witnesses[kind, code, 0] = a
                    witnesses[kind, code, 1] = b
    return bounds, witnesses


@njit(cache=True)
def verify_affine_bounds(h, bounds, witnesses):
    # Check every coordinate directly, independently of the code lookup table.
    # An attaining witness is enough for soundness; maximality only adds pruning.
    for kind in range(2):
        for code in range(729):
            a, b = witnesses[kind, code]
            if a >= 64 or b >= 64 or h[a] + h[b] != bounds[kind, code]:
                return False
            for t in range(6):
                digit = code // (3**t) % 3
                value = ((a >> t) & 1) + ((b >> t) & 1) if kind == 0 else ((a >> t) & 1) - ((b >> t) & 1) + 1
                if value != digit:
                    return False
    return True


@njit(cache=True)
def exchanged_sides(a, b, transfer, kind):
    if kind == 0:
        c, d = a & ~transfer, b | transfer
    elif kind == 1:
        c, d = a | transfer, b & ~transfer
    elif kind == 2:
        c, d = a & ~transfer, b & ~transfer
    else:
        c, d = a | transfer, b | transfer
    return c ^ 127 if c & 64 else c, d ^ 127 if d & 64 else d


@njit(cache=True)
def exchange_bounds(h):
    bounds = np.empty((1953, 4), dtype=np.int64)
    witnesses = np.zeros((1953, 4), dtype=np.uint8)
    k = 0
    for a in range(1, 64):
        for b in range(a + 1, 64):
            regions = (a & ~b, b & ~a, a & b, 127 & ~(a | b))
            for kind in range(4):
                best = -1
                argument = 0
                transfer = regions[kind]
                while True:
                    c, d = exchanged_sides(a, b, transfer, kind)
                    value = h[c] + h[d]
                    if value > best:
                        best, argument = value, transfer
                    if not transfer:
                        break
                    transfer = (transfer - 1) & regions[kind]
                bounds[k, kind], witnesses[k, kind] = best, argument
            k += 1
    return bounds, witnesses


@njit(cache=True)
def verify_exchange_bounds(h, bounds, witnesses):
    k = 0
    for a in range(1, 64):
        for b in range(a + 1, 64):
            for kind in range(4):
                region = a & ~b if kind == 0 else b & ~a if kind == 1 else a & b if kind == 2 else 127 & ~(a | b)
                transfer = witnesses[k, kind]
                if transfer & ~region:
                    return False
                c, d = exchanged_sides(a, b, transfer, kind)
                if h[c] + h[d] != bounds[k, kind]:
                    return False
            k += 1
    return True


@njit(cache=True)
def affine_relations(h, codes, bounds, exchanges):
    relations = np.empty((1953, 3), dtype=np.int64)
    count = equal = opposite = quadrants = k = 0
    for a in range(1, 64):
        for b in range(a + 1, 64):
            flags = 1 if a & b == a else 2 if not a & b else 0
            value = h[a] + h[b]
            if value < bounds[0, codes[0, a, b]]:
                flags |= 4
                equal += 1
            if value < bounds[1, codes[1, a, b]]:
                flags |= 8
                opposite += 1
            for kind in range(4):
                if value < exchanges[k, kind]:
                    flags |= 16 << kind
                    quadrants += 1
            if flags:
                relations[count, 0], relations[count, 1], relations[count, 2] = a, b, flags
                count += 1
            k += 1
    return relations[:count], equal, opposite, quadrants


@dataclass(frozen=True)
class CutRules:
    """Immutable, target-local plan; never shared mutable solver state."""

    joins: np.ndarray
    binary: np.ndarray
    equal_exclusions: int
    opposite_exclusions: int
    certificate_sha256: str
    quadrant_requirements: int
    capacity: CapacityPlan


def initial(source):
    from ._graph_epr import _epr_geometry

    if source.bulk_count != 4:
        raise ValueError("minimum-cut domains are specialized for four bulk vertices")
    if any(not 0 <= v <= np.iinfo(np.int64).max // 2 for v in source.target):
        raise ValueError("balanced-cut arithmetic exceeds its exact integer range")
    boundary, _ = _epr_geometry(4)
    h = np.zeros(64, dtype=np.int64)
    domains = np.ones(64, dtype=np.int64)
    total = sum(source.degrees)
    for i, s in enumerate(boundary):
        h[s] = source.target[i]
        ds = sum(source.degrees[t] for t in range(6) if s >> t & 1)
        if h[s] == ds:
            domains[s] = 1
        elif h[s] == total - ds:
            domains[s] = 65534
        else:
            domains[s] = 32766
    rules = []
    for a, b in combinations(range(1, 64), 2):
        if a & b in (a, b):
            continue
        union = a | b
        if h[a] + h[b] == h[a & b] + h[union]:
            rules.append((a, b, union))
    joins = np.asarray(rules, dtype=np.int64).reshape(-1, 3)
    codes, _ = affine_geometry()
    bounds, witnesses = affine_pair_bounds(h, codes)
    if not verify_affine_bounds(h, bounds, witnesses):
        raise RuntimeError("invalid exact balanced-cut certificate")
    exchanges, transfers = exchange_bounds(h)
    if not verify_exchange_bounds(h, exchanges, transfers):
        raise RuntimeError("invalid exact terminal-exchange certificate")
    binary, equal, opposite, quadrants = affine_relations(h, codes, bounds, exchanges)
    capacity = capacity_plan(h, source.degrees)
    digest = hashlib.sha256(
        h.tobytes()
        + bounds.tobytes()
        + witnesses.tobytes()
        + exchanges.tobytes()
        + transfers.tobytes()
        + binary.tobytes()
        + capacity.certificate_sha256.encode()
    ).hexdigest()
    joins.setflags(write=False)
    binary.setflags(write=False)
    return domains, CutRules(joins, binary, int(equal), int(opposite), digest, int(quadrants), capacity)


@njit(cache=True)
def make_support_images(rows):
    images = np.zeros((len(rows), 65536), dtype=np.uint16)
    for k in range(len(rows)):
        for domain in range(1, 65536):
            rest = domain & (domain - 1)
            one = domain ^ rest
            value = 0
            while (1 << value) != one:
                value += 1
            images[k, domain] = images[k, rest] | rows[k, value]
    return images


@lru_cache(maxsize=1)
def support_tables():
    """Deduplicate the 512 directed relations into 64 exact support images.

    Eight MiB per worker replace per-value loops with two table lookups.
    Every entry is the union of the same explicit finite relation's supports.
    """
    _, support = affine_geometry()
    ids, rows = {}, []
    mapping = np.empty((2, 256), dtype=np.uint8)
    for orientation in range(2):
        for flags in range(256):
            row = support[orientation, flags]
            key = row.tobytes()
            if key not in ids:
                ids[key] = len(rows)
                rows.append(row)
            mapping[orientation, flags] = ids[key]
    images = make_support_images(np.asarray(rows, dtype=np.int64))
    mapping.setflags(write=False)
    images.setflags(write=False)
    return mapping, images


@njit(cache=True)
def propagate(domains, binary, mapping, images, joins, image, preimage):
    while True:
        changed = False
        for k in range(len(binary)):
            i, j, flags = binary[k]
            a, b = domains[i], domains[j]
            aa = a & images[mapping[1, flags], b]
            bb = b & images[mapping[0, flags], aa]
            if not aa or not bb:
                return False
            if aa != a:
                domains[i] = aa
                changed = True
            if bb != b:
                domains[j] = bb
                changed = True
        for k in range(len(joins)):
            i, j, u = joins[k]
            a, b, c = domains[i], domains[j], domains[u]
            aa = bb = cc = 0
            for x in range(16):
                if not a & (1 << x):
                    continue
                allowed = b & int(preimage[x, c])
                if allowed:
                    aa |= 1 << x
                    bb |= allowed
                    cc |= int(image[x, allowed])
            if not aa or not bb or not cc:
                return False
            if aa != a:
                domains[i] = aa
                changed = True
            if bb != b:
                domains[j] = bb
                changed = True
            if cc != c:
                domains[u] = cc
                changed = True
        if not changed:
            return True


def close(domains, rules):
    mapping, images = support_tables()
    image, preimage = tables()
    inside, outside, cuts = capacity_geometry()
    plan = rules.capacity
    while True:
        if not propagate(domains, rules.binary, mapping, images, rules.joins, image, preimage):
            return False
        changed = prune_capacity(domains, plan.entropy, plan.degree_twice, plan.crossing_caps, inside, outside, cuts)
        if changed <= 0:
            return changed == 0


def local_zero_rows(penalty, degree, bulk_count):
    stride = bulk_count - 1
    zeros = []
    for t in range(7):
        for k in range(stride):
            if penalty[t * stride + k] + degree[t]:
                zeros.append(("bound", t * stride + k))
        if degree[t]:
            zeros.append(("last", t))
    for j in range(7 * stride, len(penalty)):
        if penalty[j]:
            zeros.append(("bound", j))
    return zeros


@njit(cache=True)
def stabilizer_representatives(fixed, tracked=True):
    """One proper mask per orbit of the fixed-cut signature stabilizer.

    Within each equal-signature block, put the next cut's ones at the largest
    vertex indices. This is the maximum integer in each orbit. Only a single
    next cut is ordered: ordering every unfixed cut at once would be unsound.
    Untracked native branches may have additional asymmetric constraints.
    """
    representatives = 32766
    if not tracked:
        return representatives
    for left in range(4):
        for right in range(left + 1, 4):
            same = True
            for side in range(1, 64):
                if fixed[side] >= 0 and (fixed[side] >> left & 1) != (fixed[side] >> right & 1):
                    same = False
                    break
            if same:
                for value in range(1, 15):
                    if (value >> left & 1) > (value >> right & 1):
                        representatives &= ~(1 << value)
    return representatives


class OrbitCover(pyscipopt.Conshdlr):
    def __init__(self, source, variables, templates):
        self.source = source
        self.variables = variables
        self.templates = templates
        self.calls = 0
        self.children = 0
        self.zero_bounds = 0
        self.root_children = 0

    def add_root_constraints(self, node, choice, template):
        source = self.source
        stride = source.bulk_count - 1
        a, b, penalty, degree, zeros = template
        row, rhs = choice
        self.model.addConsNode(
            node, pyscipopt.quicksum(v * self.variables[j] for j, v in enumerate(row) if v) <= rhs, removable=False
        )
        for kind, j in local_zero_rows(penalty, degree, source.bulk_count):
            if kind == "bound":
                self.model.chgVarUbNode(node, self.variables[j], 0.0)
            else:
                expr = pyscipopt.quicksum(self.variables[j * stride + k] for k in range(stride))
                self.model.addConsNode(node, expr >= source.degrees[j], removable=False)
            self.zero_bounds += 1

    def conscheck(self, *args, **kwargs):
        return {"result": SCIP_RESULT.FEASIBLE}

    def consenfops(self, *args, **kwargs):
        return {"result": SCIP_RESULT.SOLVELP}

    def conslock(self, *args, **kwargs):
        pass


@lru_cache(maxsize=65536)
def proper_values(mask):
    return tuple(k for k in range(1, 15) if mask >> k & 1)


class DomainCover(OrbitCover):
    def __init__(self, source, variables, templates):
        super().__init__(source, variables, templates)
        self.base, self.rules = initial(source)
        self.base_ok = close(self.base, self.rules)
        self.states = {}
        self.symmetry_nodes = set()
        self.symmetry_raw_masks = 0
        self.symmetry_orbit_masks = 0
        self.symmetry_skipped_masks = 0
        self.symmetry_untracked_enforcements = 0
        self.symmetry_consistent = True
        self.pruned = 0
        self.forced = 0
        self.root_candidates = 0
        self.root_pruned = 0
        self.branch_candidates = 0
        self.branch_pruned = 0
        self.state_fallbacks = 0
        from ._graph_epr import _epr_geometry

        self.boundary, self.coefficients = _epr_geometry(4)
        self.index = {s: i for i, s in enumerate(self.boundary)}
        D = sum(source.degrees)
        self.degree_sums = [sum(source.degrees[t] for t in range(6) if side >> t & 1) for side in self.boundary]
        self.free = [i for i, h in enumerate(source.target) if h not in (self.degree_sums[i], D - self.degree_sums[i])]
        self.expressions = {}
        self.gather = self.coefficients[self.free].reshape(-1, 27)
        self.bounds = np.asarray(
            [
                [
                    source.target[i] - (D - self.degree_sums[i] if mask & 8 else self.degree_sums[i])
                    for mask in range(1, 15)
                ]
                for i in self.free
            ]
        )

    def expression(self, sub, mask):
        key = (sub, mask)
        if key not in self.expressions:
            row = self.coefficients[sub, mask - 1]
            constant = sum(self.source.degrees) - self.degree_sums[sub] if mask & 8 else self.degree_sums[sub]
            rhs = self.source.target[sub] - constant
            expr = pyscipopt.quicksum(int(value) * self.variables[j] for j, value in enumerate(row) if value)
            self.expressions[key] = expr <= rhs
        return self.expressions[key]

    def enforce_singles(self, node, trial, parent_fixed):
        fixed = parent_fixed.copy()
        for side in range(1, 64):
            mask = int(trial[side])
            if not mask or mask & (mask - 1):
                continue
            value = mask.bit_length() - 1
            if fixed[side] == value:
                continue
            fixed[side] = value
            if 0 < value < 15:
                self.model.addConsNode(node, self.expression(self.index[side], value), removable=False)
                self.forced += 1
        return fixed

    def ancestor_state(self):
        node = self.model.getCurrentNode()
        while node is not None:
            number = node.getNumber()
            if number in self.states:
                return self.states[number]
            node = node.getParent()
        return None

    def consenfolp(self, constraints, nuseful, solinfeasible):
        self.calls += 1
        if self.model.getDepth() == 0:
            self.states = {}
            self.symmetry_nodes = set()
            if not self.base_ok:
                self.root_candidates += len(self.templates)
                self.root_pruned += len(self.templates)
                return {"result": SCIP_RESULT.CUTOFF}
            first, second = self.source.profile["paired_cut_subsystems"]
            left, right = self.boundary[first], self.boundary[second]
            created = 0
            for choice, template in zip(self.source.disjunctions[0], self.templates, strict=True):
                a, b, *_ = template
                self.root_candidates += 1
                trial = self.base.copy()
                trial[left] = 1 << a
                trial[right] = 1 << b
                if not close(trial, self.rules):
                    self.pruned += 1
                    self.root_pruned += 1
                    continue
                node = self.model.createChild(0, self.model.getLocalEstimate())
                self.children += 1
                self.root_children += 1
                created += 1
                self.add_root_constraints(node, choice, template)
                fixed = self.enforce_singles(node, trial, np.full(64, -1, dtype=np.int16))
                self.states[node.getNumber()] = (trial, fixed)
                self.symmetry_nodes.add(node.getNumber())
            return {"result": SCIP_RESULT.BRANCHED if created else SCIP_RESULT.CUTOFF}
        state = self.ancestor_state()
        if state is None:
            self.state_fallbacks += 1
            return {"result": SCIP_RESULT.FEASIBLE}
        current, fixed = state
        symmetry_allowed = self.model.getCurrentNode().getNumber() in self.symmetry_nodes
        representatives = stabilizer_representatives(fixed, symmetry_allowed)
        if not symmetry_allowed:
            self.symmetry_untracked_enforcements += 1
        point = np.asarray([self.model.getSolVal(None, v) for v in self.variables])
        violations = (self.gather @ point).reshape(len(self.free), 14) - self.bounds
        candidates = []
        for k, sub in enumerate(self.free):
            side = self.boundary[sub]
            domain = int(current[side])
            if domain.bit_count() <= 1:
                continue
            reduced = domain & representatives
            if not reduced:
                # Never turn a broken symmetry invariant into an exclusion.
                self.symmetry_consistent = False
                self.model.interruptSolve()
                return {"result": SCIP_RESULT.FEASIBLE}
            allowed = proper_values(reduced)
            minimum = min(float(violations[k, m - 1]) for m in allowed)
            if self.model.isFeasLE(minimum, 0.0):
                continue
            key = (-minimum, len(allowed), sub)
            candidates.append((key, sub, side, allowed))
        if not candidates:
            return {"result": SCIP_RESULT.FEASIBLE}
        _, sub, side, allowed = min(candidates, key=lambda item: item[0])
        raw_count = int(current[side]).bit_count()
        self.symmetry_raw_masks += raw_count
        self.symmetry_orbit_masks += len(allowed)
        self.symmetry_skipped_masks += raw_count - len(allowed)
        created = 0
        for mask in allowed:
            self.branch_candidates += 1
            trial = current.copy()
            trial[side] = 1 << mask
            if not close(trial, self.rules):
                self.pruned += 1
                self.branch_pruned += 1
                continue
            node = self.model.createChild(0, self.model.getLocalEstimate())
            self.children += 1
            created += 1
            new_fixed = self.enforce_singles(node, trial, fixed)
            self.states[node.getNumber()] = (trial, new_fixed)
            if symmetry_allowed:
                self.symmetry_nodes.add(node.getNumber())
        return {"result": SCIP_RESULT.BRANCHED if created else SCIP_RESULT.CUTOFF}

    def record(self):
        return {
            "kind": "minimal_cut_domain_branching",
            "recipe_sha256": self.recipe_sha256,
            "propagation_policy": "cut_regions_and_exact_capacity_budgets",
            "cut_certificate_verified": True,
            "cut_certificate_sha256": self.rules.certificate_sha256,
            "cut_equal_exclusions": self.rules.equal_exclusions,
            "cut_opposite_exclusions": self.rules.opposite_exclusions,
            "cut_quadrant_requirements": self.rules.quadrant_requirements,
            "binary_support_policy": "immutable_complete_support_images",
            "capacity_budget_policy": "exact_terminal_and_core_interval_feedback",
            "capacity_certificate_sha256": self.rules.capacity.certificate_sha256,
            "edge_weight_integrality_required": False,
            "total_vertices": 11,
            "root_orbit_candidates": self.root_candidates,
            "root_orbit_children": self.root_children,
            "root_orbit_pruned": self.root_pruned,
            "domain_branch_candidates": self.branch_candidates,
            "domain_branch_children": self.children - self.root_children,
            "domain_branch_pruned": self.branch_pruned,
            "forced_upper_cuts": self.forced,
            "zero_edge_constraints": self.zero_bounds,
            "residual_order_rows": 0,
            "symmetry_policy": "dynamic_minimal_cut_stabilizer",
            "symmetry_raw_masks": self.symmetry_raw_masks,
            "symmetry_orbit_masks": self.symmetry_orbit_masks,
            "symmetry_skipped_masks": self.symmetry_skipped_masks,
            "symmetry_untracked_enforcements": self.symmetry_untracked_enforcements,
            "symmetry_consistent": self.symmetry_consistent,
            "capacity_ordering_disabled": True,
            "branch_selection": "largest_minimum_slack_then_fewest_orbits",
            "domain_state_fallbacks": self.state_fallbacks,
            "covers_complete": (
                self.symmetry_consistent
                and self.root_candidates == self.root_children + self.root_pruned
                and self.branch_candidates == self.children - self.root_children + self.branch_pruned
                and self.symmetry_raw_masks == self.symmetry_orbit_masks + self.symmetry_skipped_masks
                and self.symmetry_orbit_masks == self.branch_candidates
            ),
            "automatic_symmetry_disabled": True,
            "dual_reductions_disabled": True,
        }


def install_cut_domain_branching(model, source, variables):
    """Install a complete minimal-cut orbit cover, never a heuristic filter.

    Any realizing graph has unique inclusion-minimal cuts. Anchor-pair
    signature histograms cover the initial labellings. For each next chosen
    cut, permute only vertices with identical previously fixed signatures.
    Those permutations preserve every ancestor constraint, so one proper mask
    per stabilizer orbit is a complete cover. Repeat on the refined partition;
    never simultaneously order all unfixed cuts or impose capacity ordering.
    If native SCIP creates a branch, disable quotienting throughout its subtree
    because its additional constraints might not preserve that stabilizer.
    Arc consistency removes only unsupported values. All original native
    disjunctions and independent exact graph acceptance remain in place.

    Disable solver-picked symmetry and dual reductions: either could select
    a different representative before our conditional canonical ordering.
    """
    if source.bulk_count != 4 or "paired_cut_subsystems" not in source.profile:
        return None
    from ._graph_epr import _epr_geometry
    from ._graph_pair import _pair_penalties

    boundary, _ = _epr_geometry(4)
    i, j = source.profile["paired_cut_subsystems"]
    left, right = boundary[i], boundary[j]
    values = dict(zip(boundary, source.target, strict=True))
    values[0] = 0

    def entropy(side):
        return values[side ^ 127 if side & 64 else side]

    saturated = 9 if entropy(left) + entropy(right) == entropy(left & right) + entropy(left | right) else 0
    saturated |= 6 if entropy(left) + entropy(right) == entropy(left & ~right) + entropy(right & ~left) else 0
    templates = _pair_penalties(left, right, saturated, 4)
    model.setParam("misc/usesymmetry", 0)
    model.setParam("misc/allowstrongdualreds", False)
    model.setParam("misc/allowweakdualreds", False)
    handler = DomainCover(source, variables, templates)
    recipe = {
        "kind": "minimal_cut_domain_branching",
        "base_model_sha256": source.sha256,
        "initial_closed_domains": handler.base.tolist(),
        "tight_union_rules": handler.rules.joins.tolist(),
        "propagation_policy": "cut_regions_and_exact_capacity_budgets",
        "cut_certificate_sha256": handler.rules.certificate_sha256,
        "binary_support_policy": "immutable_complete_support_images",
        "capacity_budget_policy": "exact_terminal_and_core_interval_feedback",
        "capacity_certificate_sha256": handler.rules.capacity.certificate_sha256,
        "anchor_subsystems": [left, right],
        "anchor_orbits": [[a, b] for a, b, *_ in templates],
        "symmetry_policy": "dynamic_minimal_cut_stabilizer",
        "native_branch_guard": True,
        "capacity_ordering": False,
        "branch_selection": "largest_minimum_slack_then_fewest_orbits",
    }
    handler.recipe_sha256 = hashlib.sha256(
        json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    model.includeConshdlr(
        handler,
        "minimal_cut_domains",
        "complete minimum-cut domain and bulk-orbit branching",
        enfopriority=-900000,
        chckpriority=-900000,
        needscons=False,
    )
    return handler
