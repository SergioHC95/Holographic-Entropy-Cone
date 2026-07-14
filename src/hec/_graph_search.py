"""Private deterministic planning for symmetry-sharded fixed-N searches.

The MILP remains the source of feasibility and the graph verifier remains the
source of acceptance.  This module only partitions a large one-hot search into
disjoint representatives of the exact bulk/target symmetry action.
"""

from __future__ import annotations

import contextlib
import math
import multiprocessing as mp
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from typing import Any, Literal

import numpy as np

from ._graph_milp import (
    DEFAULT_SCIP_SELECTOR_THRESHOLD,
    _ahc_structure,
    _deterministic_union_cut_fixes_exact,
    _exact_ahc_preprocessing,
    _exact_target_values,
    _solve_ahc_for_N,
)
from ._graph_symmetry import (
    extended_terminal_automorphisms,
    quotient_bulk_mask_orbits,
    setwise_stabilizer_actions,
)
from .coordinates import party_labels, subset_index_map, subsets

AUTOMATIC_ORBIT_STRATEGY = "automatic-orbit-search-v1"
DEFAULT_MAX_ORBIT_FRONTIER = 512


def _json_native(value: Any) -> Any:
    """Return nested records with tuples normalized to JSON arrays."""

    if isinstance(value, Mapping):
        return {str(key): _json_native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_native(item) for item in value]
    return value


@dataclass(frozen=True)
class OrbitBranchPlan:
    """One compact exact orbit representative.

    Selecting one cut fixes the other cuts in that subsystem to zero through
    the existing one-hot equality, so zero assignments are intentionally not
    serialized in branch payloads.
    """

    selected_cuts: tuple[tuple[int, int], ...]
    orbit_size: int

    def as_record(self) -> dict[str, Any]:
        return {
            "orbit_size": self.orbit_size,
            "selected_cuts": [list(choice) for choice in self.selected_cuts],
        }


@dataclass(frozen=True)
class OrbitSearchPlan:
    """Property-derived choice between a monolithic and orbit search."""

    mode: Literal["monolithic", "orbit"]
    reason: str
    n: int
    total_vertices: int
    selector_count: int
    selected_subsystems: tuple[int, ...] = ()
    branches: tuple[OrbitBranchPlan, ...] = ()
    metadata: tuple[tuple[str, Any], ...] = ()

    @property
    def metadata_dict(self) -> dict[str, Any]:
        return dict(self.metadata)

    def as_record(self) -> dict[str, Any]:
        record = {
            "branches": [branch.as_record() for branch in self.branches],
            "mode": self.mode,
            "n": self.n,
            "reason": self.reason,
            "selected_subsystems": list(self.selected_subsystems),
            "selector_count": self.selector_count,
            "strategy": AUTOMATIC_ORBIT_STRATEGY,
            "total_vertices": self.total_vertices,
            **self.metadata_dict,
        }
        return _json_native(record)


def free_subsystem_choices(
    target: Sequence[object],
    n: int,
    total_vertices: int,
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    """Return root one-hot choices after exact deterministic preprocessing."""

    exact_target = _exact_target_values(target, n)
    exact = _exact_ahc_preprocessing(n, total_vertices, exact_target)
    if exact.infeasible:
        return ()
    _edges, _fixed_subsystems, fixed_sub_indices, _cuts_by_sub = _ahc_structure(n, total_vertices)
    choices_by_sub = dict(exact.choices_by_sub)
    deterministic, _upper, _stats, feasible = _deterministic_union_cut_fixes_exact(
        exact.scaled_target,
        n,
        total_vertices,
        choices_by_sub,
        exact.cut_bounds,
        fixed_sub_indices,
    )
    if not feasible:
        return ()
    merged = {(sub, cut): int(round(value)) for (sub, cut), value in deterministic.items()}

    free: list[tuple[int, tuple[int, ...]]] = []
    for sub_index, choices in sorted(choices_by_sub.items()):
        if any(merged.get((sub_index, cut), 0) == 1 for cut in choices):
            continue
        remaining = tuple(cut for cut in choices if (sub_index, cut) not in merged)
        if len(remaining) > 1:
            free.append((sub_index, remaining))
    return tuple(free)


def _subsystem_mask(n: int, sub_index: int) -> int:
    return sum(1 << party for party in subsets(n)[sub_index])


def _tight_closure_gain(
    target: tuple[Fraction, ...],
    n: int,
    left_index: int,
    right_index: int,
) -> int:
    """Return exact nontrivial submodular cut-closure potential.

    Equality is checked over exact rationals.  For crossing boundaries A and B,
    ``|A\\B| |B\\A|`` counts the terminal cross-block pairs whose separation
    is constrained when the two selected cuts close to intersection/union.
    Nested pairs have no new closure and deliberately score zero.
    """

    boundaries = subsets(n)
    index = subset_index_map(n)
    left = frozenset(boundaries[left_index])
    right = frozenset(boundaries[right_index])
    left_only = left - right
    right_only = right - left
    if not left_only or not right_only:
        return 0

    def value(boundary: frozenset[int]) -> Fraction:
        return Fraction(0) if not boundary else target[index[boundary]]

    if value(left) + value(right) != value(left & right) + value(left | right):
        return 0
    return len(left_only) * len(right_only)


def _pair_orbits(
    n: int,
    total_vertices: int,
    selected: tuple[int, int],
    choices_by_sub: Mapping[int, tuple[int, ...]],
    automorphisms: Sequence[Sequence[int]],
    *,
    max_frontier: int,
) -> tuple[tuple[OrbitBranchPlan, ...], dict[str, int]] | None:
    bulk_count = total_vertices - n - 1
    selected_masks = tuple(_subsystem_mask(n, sub_index) for sub_index in selected)
    actions = setwise_stabilizer_actions(selected_masks, automorphisms, party_count=n)
    allowed = tuple(set(choices_by_sub[sub_index]) for sub_index in selected)
    full_bulk_mask = (1 << bulk_count) - 1

    # Fail closed unless both the bulk action and every target-induced row
    # action preserve the exact preprocessed choice domain.
    for choices in allowed:
        counts: dict[int, int] = {}
        for mask in choices:
            counts[mask.bit_count()] = counts.get(mask.bit_count(), 0) + 1
        if any(count != math.comb(bulk_count, weight) for weight, count in counts.items()):
            return None
    for action in actions:
        for source, destination in enumerate(action.permutation):
            transformed = {mask ^ full_bulk_mask if action.complements[source] else mask for mask in allowed[source]}
            if transformed != allowed[destination]:
                return None

    branches: list[OrbitBranchPlan] = []
    for orbit in quotient_bulk_mask_orbits(bulk_count, 2, actions):
        if not all(mask in choices for mask, choices in zip(orbit.masks, allowed, strict=True)):
            continue
        branches.append(OrbitBranchPlan(tuple(zip(selected, orbit.masks, strict=True)), orbit.weight))
        if len(branches) > max_frontier:
            return None
    expected = math.prod(len(choices_by_sub[sub_index]) for sub_index in selected)
    if sum(branch.orbit_size for branch in branches) != expected:
        return None
    ordered = tuple(
        sorted(
            branches,
            key=lambda branch: (-branch.orbit_size, tuple(cut for _sub, cut in branch.selected_cuts)),
        )
    )
    return ordered, {
        "boundary_action_count": len(actions),
        "bulk_count": bulk_count,
        "raw_orbit_coverage": expected,
        "representative_count": len(ordered),
    }


def plan_orbit_search(
    target: Sequence[object],
    n: int,
    total_vertices: int,
    *,
    selector_threshold: int = DEFAULT_SCIP_SELECTOR_THRESHOLD,
    max_frontier: int = DEFAULT_MAX_ORBIT_FRONTIER,
) -> OrbitSearchPlan:
    """Choose the deterministic production fixed-N search topology.

    Small models stay monolithic.  A large model is sharded only when two free
    subsystems have an exact, nontrivial tight-submodularity closure and their
    complete bulk/target quotient fits the bounded outer frontier.
    """

    if selector_threshold < 0 or max_frontier < 1:
        raise ValueError("selector_threshold must be nonnegative and max_frontier positive")
    candidates = free_subsystem_choices(target, n, total_vertices)
    selector_count = sum(len(choices) for _sub, choices in candidates)
    base = {
        "n": n,
        "total_vertices": total_vertices,
        "selector_count": selector_count,
    }
    if selector_count <= selector_threshold:
        return OrbitSearchPlan(
            mode="monolithic",
            reason="selector_count_at_or_below_threshold",
            metadata=(("selector_threshold", selector_threshold),),
            **base,
        )
    if len(candidates) < 2:
        return OrbitSearchPlan(
            mode="monolithic",
            reason="fewer_than_two_free_subsystems",
            metadata=(("selector_threshold", selector_threshold),),
            **base,
        )

    exact_target = _exact_target_values(target, n)
    automorphisms = extended_terminal_automorphisms(list(exact_target))
    choices_by_sub = dict(candidates)
    best: (
        tuple[
            tuple[int, int, tuple[int, int]],
            tuple[int, int],
            tuple[OrbitBranchPlan, ...],
            dict[str, int],
        ]
        | None
    ) = None
    tight_pair_count = 0
    for selected in combinations(tuple(sorted(choices_by_sub)), 2):
        gain = _tight_closure_gain(exact_target, n, selected[0], selected[1])
        if gain == 0:
            continue
        tight_pair_count += 1
        quotient = _pair_orbits(
            n,
            total_vertices,
            selected,
            choices_by_sub,
            automorphisms,
            max_frontier=max_frontier,
        )
        if quotient is None:
            continue
        branches, orbit_metadata = quotient
        key = (len(branches), -gain, selected)
        candidate = (key, selected, branches, {**orbit_metadata, "tight_closure_gain": gain})
        if best is None or key < best[0]:
            best = candidate

    if best is None:
        return OrbitSearchPlan(
            mode="monolithic",
            reason=("no_exact_tight_pair" if tight_pair_count == 0 else "no_manageable_exact_orbit_frontier"),
            metadata=(
                ("max_frontier", max_frontier),
                ("selector_threshold", selector_threshold),
                ("tight_pair_count", tight_pair_count),
            ),
            **base,
        )

    _key, selected, branches, orbit_metadata = best
    labels = party_labels(n)
    names = tuple("".join(labels[party] for party in subsets(n)[index]) for index in selected)
    metadata: dict[str, Any] = {
        **orbit_metadata,
        "max_frontier": max_frontier,
        "selected_subsystem_names": names,
        "selector_threshold": selector_threshold,
        "tight_pair_count": tight_pair_count,
    }
    return OrbitSearchPlan(
        mode="orbit",
        reason="large_model_with_exact_tight_manageable_orbit_pair",
        selected_subsystems=selected,
        branches=branches,
        metadata=tuple(sorted(metadata.items())),
        **base,
    )


def _solve_planned_branch(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    deadline = payload.get("deadline")
    remaining = payload["time_limit_s"]
    if deadline is not None:
        remaining = float(deadline) - time.perf_counter()
        if remaining <= 0:
            return None, {
                "reason": "fixed_n_time_limit_exhausted",
                "status": "unknown",
            }
    target = np.asarray(payload["target"], dtype=np.int64)
    return _solve_ahc_for_N(
        target,
        int(payload["n"]),
        int(payload["total_vertices"]),
        assume_no_smaller=bool(payload["assume_no_smaller"]),
        node_limit=payload["node_limit"],
        time_limit_s=remaining,
        branch_choice_values={(int(sub), int(cut)): 1 for sub, cut in payload["selected_cuts"]},
    )


def _solve_indexed_branch(
    item: tuple[int, dict[str, Any]],
) -> tuple[int, dict[str, Any] | None, dict[str, Any]]:
    """Process-pool boundary that turns worker failures into explicit unknowns."""

    ordinal, payload = item
    try:
        graph, info = _solve_planned_branch(payload)
    except Exception as exc:
        graph, info = (
            None,
            {
                "error": f"{type(exc).__name__}: {exc}",
                "reason": "worker_infrastructure_error",
                "status": "unknown",
            },
        )
    return ordinal, graph, info


def solve_fixed_n(
    target: Sequence[int],
    n: int,
    total_vertices: int,
    *,
    assume_no_smaller: bool = False,
    node_limit: int | None = None,
    time_limit_s: float | None = None,
    workers: int = 1,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Run one exact fixed-N model through the automatic production topology.

    Every branch uses the canonical solver portfolio and its shared exact
    incumbent validator.  An infeasibility is returned only after every exact
    orbit representative has a trusted negative result.
    """

    started = time.perf_counter()
    deadline = None if time_limit_s is None else started + time_limit_s
    if workers < 1:
        raise ValueError("workers must be positive")
    clean_target = tuple(int(value) for value in target)
    plan = plan_orbit_search(clean_target, n, total_vertices)
    if plan.mode == "monolithic":
        remaining = None if deadline is None else deadline - time.perf_counter()
        if remaining is not None and remaining <= 0:
            return None, {
                "reason": "fixed_n_time_limit_exhausted_during_planning",
                "search_plan": plan.as_record(),
                "status": "unknown",
            }
        graph, info = _solve_ahc_for_N(
            np.asarray(clean_target, dtype=np.int64),
            n,
            total_vertices,
            assume_no_smaller=assume_no_smaller,
            node_limit=node_limit,
            time_limit_s=remaining,
        )
        return graph, {**info, "search_plan": plan.as_record()}

    base_payload = {
        "assume_no_smaller": assume_no_smaller,
        "deadline": deadline,
        "n": n,
        "node_limit": node_limit,
        "time_limit_s": time_limit_s,
        "target": clean_target,
        "total_vertices": total_vertices,
    }
    completions: list[dict[str, Any]] = []

    def payload(ordinal: int) -> dict[str, Any]:
        branch = plan.branches[ordinal]
        return {
            **base_payload,
            "selected_cuts": branch.selected_cuts,
        }

    def consume(
        ordinal: int,
        graph: dict[str, Any] | None,
        info: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        branch = plan.branches[ordinal]
        milp = info.get("milp") if isinstance(info.get("milp"), Mapping) else {}
        completions.append(
            {
                "backend": info.get("backend", milp.get("backend")),
                "error": info.get("error", milp.get("error")),
                "ordinal": ordinal,
                "orbit_size": branch.orbit_size,
                "reason": info.get("reason", milp.get("reason")),
                "selected_cuts": [list(choice) for choice in branch.selected_cuts],
                "status": info.get("status", "unknown"),
            }
        )
        if graph is None:
            return None, None
        return graph, {
            **info,
            "orbit_branch": completions[-1],
            "orbit_completed_representatives": len(completions),
            "orbit_elapsed_s": time.perf_counter() - started,
            "search_plan": plan.as_record(),
        }

    if workers == 1:
        for ordinal in range(len(plan.branches)):
            graph, info = _solve_planned_branch(payload(ordinal))
            realized, result = consume(ordinal, graph, info)
            if realized is not None:
                return realized, result or info
    else:
        pool: Any | None = None
        found = False
        completed = False
        try:
            context = mp.get_context("spawn")
            process_count = min(workers, len(plan.branches))
            pool = context.Pool(processes=process_count)
            jobs = ((ordinal, payload(ordinal)) for ordinal in range(len(plan.branches)))
            results = pool.imap_unordered(_solve_indexed_branch, jobs, chunksize=1)
            while True:
                try:
                    if deadline is None:
                        ordinal, graph, info = next(results)
                    else:
                        remaining = deadline - time.perf_counter()
                        if remaining <= 0:
                            return None, {
                                "orbit_completed_representatives": len(completions),
                                "orbit_elapsed_s": time.perf_counter() - started,
                                "reason": "fixed_n_time_limit_exhausted",
                                "search_plan": plan.as_record(),
                                "status": "unknown",
                            }
                        ordinal, graph, info = results.next(timeout=min(remaining, 1.0))
                except mp.TimeoutError:
                    continue
                except StopIteration:
                    completed = True
                    break
                realized, result = consume(ordinal, graph, info)
                if realized is not None:
                    pool.terminate()
                    pool.join()
                    found = True
                    return realized, result or info
        except Exception as exc:
            return None, {
                "error": f"{type(exc).__name__}: {exc}",
                "orbit_completed_representatives": len(completions),
                "orbit_elapsed_s": time.perf_counter() - started,
                "reason": "process_pool_infrastructure_error",
                "search_plan": plan.as_record(),
                "status": "unknown",
            }
        finally:
            if pool is not None and not found:
                with contextlib.suppress(Exception):
                    if completed:
                        pool.close()
                    else:
                        pool.terminate()
                    pool.join()

    statuses = {str(completion["status"]) for completion in completions}
    status = "infeasible" if statuses == {"infeasible"} and len(completions) == len(plan.branches) else "unknown"
    diagnostic_fields = ("backend", "error", "ordinal", "reason", "status")
    failures = [
        {field: completion[field] for field in diagnostic_fields if completion.get(field) is not None}
        for completion in completions
        if completion["status"] != "infeasible"
    ]
    normalized_reasons = [str(item["reason"]) for item in completions if item.get("reason") is not None]
    reason_counts = {reason: normalized_reasons.count(reason) for reason in sorted(set(normalized_reasons))}
    return None, {
        "status": status,
        "reason": (
            "all_exact_orbit_representatives_infeasible"
            if status == "infeasible"
            else "one_or_more_orbit_representatives_unknown"
        ),
        "orbit_completed_representatives": len(completions),
        "orbit_elapsed_s": time.perf_counter() - started,
        "orbit_failure_samples": failures[:16],
        "orbit_reason_counts": reason_counts,
        "orbit_status_counts": {value: sum(item["status"] == value for item in completions) for value in statuses},
        "search_plan": plan.as_record(),
    }
