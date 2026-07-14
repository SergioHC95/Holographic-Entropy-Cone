from __future__ import annotations

import json
import math
import runpy
import unittest
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
from scipy import sparse

from hec import available_ns, load_hec_data
from hec._graph_milp import (
    HIGHSPY_BACKEND,
    SCIP_INDICATOR_BACKEND,
    _exact_ahc_preprocessing,
    _frozen_milp_sha256,
    _has_additive_union_decomposition_exact,
    _integer_graph,
    _milp_attempt_plan,
    _solve_ahc_fixed_vertices,
    _solve_highspy_milp,
    _solve_scip_indicator_milp,
    _trusted_scip_infeasibility,
)
from hec._graph_search import (
    OrbitBranchPlan,
    OrbitSearchPlan,
    _solve_planned_branch,
    plan_orbit_search,
    solve_fixed_n,
)
from hec._graph_validation import graph_total_vertices
from hec.graphs import check_graph, find_graph, find_graph_fixed_n, read_graphs, write_graphs


class GraphFinderBackendTests(unittest.TestCase):
    def test_native_highs_solves_and_proves_small_models(self) -> None:
        solution, feasible = _solve_highspy_milp(
            np.asarray([0.0]),
            sparse.csr_matrix((0, 1)),
            np.empty(0),
            np.empty(0),
            sparse.csr_matrix([[1.0]]),
            np.asarray([1.0]),
            np.asarray([1]),
            np.asarray([0.0]),
            np.asarray([1.0]),
        )
        self.assertEqual(solution.tolist(), [1.0])
        self.assertEqual(feasible["backend"], HIGHSPY_BACKEND)
        self.assertEqual(feasible["status"], "realized")
        self.assertEqual(len(feasible["base_model_sha256"]), 64)

        solution, infeasible = _solve_highspy_milp(
            np.asarray([0.0]),
            sparse.csr_matrix((0, 1)),
            np.empty(0),
            np.empty(0),
            sparse.csr_matrix([[1.0], [1.0]]),
            np.asarray([0.0, 1.0]),
            np.asarray([1]),
            np.asarray([0.0]),
            np.asarray([1.0]),
        )
        self.assertIsNone(solution)
        self.assertEqual(infeasible["status"], "infeasible")

    def test_scip_infeasibility_is_real_and_trusted_only_with_complete_telemetry(self) -> None:
        solution, info = _solve_scip_indicator_milp(
            np.asarray([0.0]),
            sparse.csr_matrix((0, 1)),
            np.empty(0),
            np.empty(0),
            sparse.csr_matrix([[1.0], [1.0]]),
            np.asarray([0.0, 1.0]),
            np.asarray([1]),
            np.asarray([0.0]),
            np.asarray([1.0]),
        )
        self.assertIsNone(solution)
        self.assertEqual(info["status"], "infeasible")
        self.assertTrue(_trusted_scip_infeasibility(info, incumbent_returned=False))

        corruptions = {
            "backend": "not-scip",
            "status_raw": "timelimit",
            "stage": -1,
            "solutions": 1,
            "indicator_equivalence_check": "unchecked",
            "base_model_sha256": "short",
            "indicator_transform_sha256": None,
        }
        for field, value in corruptions.items():
            with self.subTest(field=field):
                malformed = {**info, field: value}
                self.assertFalse(_trusted_scip_infeasibility(malformed, incumbent_returned=False))
        self.assertFalse(_trusted_scip_infeasibility(info, incumbent_returned=True))

    def test_canonical_portfolio_is_small_stable_and_uses_only_public_backends(self) -> None:
        small = _milp_attempt_plan(selector_count=512)
        large = _milp_attempt_plan(selector_count=513)
        self.assertEqual([attempt.backend for attempt in small], [SCIP_INDICATOR_BACKEND, HIGHSPY_BACKEND])
        self.assertIsNone(small[0].time_limit_s)
        self.assertEqual(large[0].time_limit_s, 30.0)
        self.assertNotIn("scipy", " ".join(attempt.name for attempt in small + large).lower())

    def test_backend_errors_fail_open_but_negatives_remain_fail_closed(self) -> None:
        with (
            patch("hec._graph_milp._solve_scip_indicator_milp", side_effect=ImportError("missing")),
            patch(
                "hec._graph_milp._solve_highspy_milp",
                return_value=(None, {"backend": HIGHSPY_BACKEND, "status": "infeasible"}),
            ),
        ):
            graph, info = _solve_ahc_fixed_vertices(
                np.asarray([1, 1, 1], dtype=np.int64),
                2,
                3,
            )
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "infeasible")
        self.assertEqual(len(info["milp"]["attempts"]), 2)
        self.assertEqual(info["milp"]["attempts"][0]["reason"], "backend_error")

        with (
            patch("hec._graph_milp._solve_scip_indicator_milp", side_effect=RuntimeError("scip failed")),
            patch("hec._graph_milp._solve_highspy_milp", side_effect=RuntimeError("highs failed")),
        ):
            graph, info = _solve_ahc_fixed_vertices(
                np.asarray([1, 1, 1], dtype=np.int64),
                2,
                3,
            )
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "unknown")

    def test_real_highs_fallback_reaches_shared_exact_validation(self) -> None:
        with patch("hec._graph_milp._solve_scip_indicator_milp", side_effect=RuntimeError("scip unavailable")):
            result = find_graph_fixed_n([1, 1, 1], 3)
        self.assertEqual(result["status"], "realized")
        self.assertTrue(result["check"]["ok"])
        milp = result["ahc"]["milp"]
        self.assertEqual(milp["backend"], HIGHSPY_BACKEND)
        self.assertEqual(
            [attempt["backend"] for attempt in milp["attempts"]],
            [SCIP_INDICATOR_BACKEND, HIGHSPY_BACKEND],
        )

    def test_exact_preprocessing_never_uses_float_equality(self) -> None:
        large = 10**12
        exact = _exact_ahc_preprocessing(2, 4, (Fraction(1), Fraction(large), Fraction(large)))
        self.assertEqual(exact.scaled_target[0], Fraction(1, large))
        self.assertTrue(
            all(isinstance(value, Fraction) for cuts in exact.cut_bounds for pair in cuts for value in pair)
        )
        near_tight = (Fraction(0),) * 6 + (Fraction(1, 10**12),)
        self.assertFalse(_has_additive_union_decomposition_exact(near_tight, 3, frozenset({0, 1, 2})))

    def test_integer_graph_records_exact_raw_scale(self) -> None:
        graph, scale = _integer_graph([["A", "O"], ["B", "O"]], [2 / 3, 4 / 3])
        self.assertEqual(graph["weights"], [1, 2])
        self.assertEqual(scale, "2/3")


class GraphFinderModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "graph_finder_cases.json").read_text(encoding="utf-8")
        )
        cls.target = np.asarray(fixture["large_orbit_target"], dtype=np.int64)
        cls.expected_plan = fixture["expected_plan"]

    def test_property_derived_orbit_plan_is_deterministic_and_complete(self) -> None:
        first = plan_orbit_search(self.target.tolist(), 6, 15)
        second = plan_orbit_search(self.target.tolist(), 6, 15)
        self.assertEqual(first, second)
        self.assertEqual(first.mode, "orbit")
        self.assertEqual(list(first.selected_subsystems), self.expected_plan["selected_subsystems"])
        self.assertEqual(len(first.branches), self.expected_plan["representative_count"])
        self.assertEqual(sum(branch.orbit_size for branch in first.branches), self.expected_plan["raw_orbit_coverage"])
        self.assertEqual(
            first.branches, tuple(sorted(first.branches, key=lambda branch: (-branch.orbit_size, branch.selected_cuts)))
        )

    def _model_hash(self, selected_cuts: tuple[tuple[int, int], ...]) -> tuple[str, dict]:
        hashes: list[str] = []

        def fake_solver(c, a_ineq, lo, hi, a_eq, rhs, integrality, lb, ub, **_kwargs):
            matrix = sparse.vstack([a_ineq, a_eq], format="csc")
            hashes.append(
                _frozen_milp_sha256(
                    c,
                    matrix,
                    np.concatenate([lo, rhs]),
                    np.concatenate([hi, rhs]),
                    lb,
                    ub,
                    integrality,
                )
            )
            return None, {"backend": HIGHSPY_BACKEND, "status": "infeasible"}

        with (
            patch("hec._graph_milp._solve_scip_indicator_milp", side_effect=ImportError("test skip")),
            patch("hec._graph_milp._solve_highspy_milp", side_effect=fake_solver),
        ):
            _graph, info = _solve_ahc_fixed_vertices(
                self.target,
                6,
                15,
                selected_cuts=selected_cuts,
            )
        return hashes[0], info["profile"]

    def test_selected_orbit_cuts_freeze_a_stable_one_hot_model(self) -> None:
        selected = plan_orbit_search(self.target.tolist(), 6, 15).branches[0].selected_cuts
        first_hash, first_profile = self._model_hash(selected)
        second_hash, second_profile = self._model_hash(selected)
        self.assertEqual(first_hash, second_hash)
        self.assertEqual(first_profile["constraint_model_sha256"], second_profile["constraint_model_sha256"])
        self.assertGreater(first_profile["one_hot_propagated_fixes"], 0)

    def test_parallel_orbit_pool_uses_supported_early_termination(self) -> None:
        plan = OrbitSearchPlan(
            mode="orbit",
            reason="test_plan",
            n=2,
            total_vertices=3,
            selector_count=2,
            branches=(
                OrbitBranchPlan(selected_cuts=(), orbit_size=1),
                OrbitBranchPlan(selected_cuts=((0, 1),), orbit_size=1),
            ),
        )
        with patch("hec._graph_search.plan_orbit_search", return_value=plan):
            graph, info = solve_fixed_n([1, 1, 0], 2, 3, workers=2)
        self.assertIsNotNone(graph, info)
        self.assertEqual(info["status"], "realized")
        self.assertLessEqual(info["orbit_completed_representatives"], 2)

    def test_parallel_pool_infrastructure_failure_returns_unknown(self) -> None:
        plan = OrbitSearchPlan(
            mode="orbit",
            reason="test_plan",
            n=2,
            total_vertices=3,
            selector_count=2,
            branches=(OrbitBranchPlan(selected_cuts=(), orbit_size=1),),
        )
        with (
            patch("hec._graph_search.plan_orbit_search", return_value=plan),
            patch("hec._graph_search.mp.get_context", side_effect=OSError("process quota")),
        ):
            graph, info = solve_fixed_n([1, 1, 0], 2, 3, workers=2)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "unknown")
        self.assertEqual(info["reason"], "process_pool_infrastructure_error")

    def test_all_orbit_representatives_must_be_trusted_infeasible(self) -> None:
        plan = OrbitSearchPlan(
            mode="orbit",
            reason="test_plan",
            n=2,
            total_vertices=3,
            selector_count=2,
            branches=(
                OrbitBranchPlan(selected_cuts=(), orbit_size=1),
                OrbitBranchPlan(selected_cuts=((0, 1),), orbit_size=1),
            ),
        )
        with (
            patch("hec._graph_search.plan_orbit_search", return_value=plan),
            patch(
                "hec._graph_search._solve_planned_branch",
                side_effect=[(None, {"status": "infeasible"}), (None, {"status": "infeasible"})],
            ),
        ):
            graph, info = solve_fixed_n([1, 1, 0], 2, 3, workers=1)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "infeasible")
        self.assertEqual(info["orbit_completed_representatives"], 2)

    def test_one_unknown_orbit_representative_prevents_infeasibility(self) -> None:
        plan = OrbitSearchPlan(
            mode="orbit",
            reason="test_plan",
            n=2,
            total_vertices=3,
            selector_count=2,
            branches=(
                OrbitBranchPlan(selected_cuts=(), orbit_size=1),
                OrbitBranchPlan(selected_cuts=((0, 1),), orbit_size=1),
            ),
        )
        with (
            patch("hec._graph_search.plan_orbit_search", return_value=plan),
            patch(
                "hec._graph_search._solve_planned_branch",
                side_effect=[
                    (None, {"status": "infeasible"}),
                    (None, {"reason": "backend_error", "status": "unknown"}),
                ],
            ),
        ):
            graph, info = solve_fixed_n([1, 1, 0], 2, 3, workers=1)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "unknown")
        self.assertEqual(info["orbit_status_counts"], {"infeasible": 1, "unknown": 1})

    def test_expired_shared_deadline_never_starts_an_orbit_solver(self) -> None:
        with (
            patch("hec._graph_search.time.perf_counter", return_value=10.0),
            patch("hec._graph_search._solve_ahc_fixed_vertices") as solve,
        ):
            graph, info = _solve_planned_branch({"deadline": 9.0, "time_limit_s": 300.0})
        self.assertIsNone(graph)
        self.assertEqual(info["reason"], "fixed_n_time_limit_exhausted")
        solve.assert_not_called()

    def test_parent_deadline_terminates_a_stalled_process_pool(self) -> None:
        plan = OrbitSearchPlan(
            mode="orbit",
            reason="test_plan",
            n=2,
            total_vertices=3,
            selector_count=2,
            branches=(OrbitBranchPlan(selected_cuts=(), orbit_size=1),),
        )

        class StalledResults:
            def next(self, timeout):  # noqa: A003 - mirrors multiprocessing's public iterator API
                raise AssertionError(f"deadline should expire before polling with {timeout}")

        class FakePool:
            terminated = False
            joined = False

            def imap_unordered(self, *_args, **_kwargs):
                return StalledResults()

            def terminate(self):
                self.terminated = True

            def join(self):
                self.joined = True

        pool = FakePool()

        def pool_factory(_context, processes):
            self.assertEqual(processes, 1)
            return pool

        context = type("FakeContext", (), {"Pool": pool_factory})()
        with (
            patch("hec._graph_search.plan_orbit_search", return_value=plan),
            patch("hec._graph_search.mp.get_context", return_value=context),
            patch("hec._graph_search.time.perf_counter", side_effect=[0.0, 1.0, 1.0]),
        ):
            graph, info = solve_fixed_n([1, 1, 0], 2, 3, workers=2, time_limit_s=0.5)
        self.assertIsNone(graph)
        self.assertEqual(info["reason"], "fixed_n_time_limit_exhausted")
        self.assertTrue(pool.terminated)
        self.assertTrue(pool.joined)


class PublicGraphFinderTests(unittest.TestCase):
    def test_fixed_n_ray_and_exact_modes_are_explicit_and_verified(self) -> None:
        ray = find_graph_fixed_n([1, 1, 1], 3, match="ray")
        exact = find_graph_fixed_n([1, 1, 1], 3, match="exact")
        self.assertEqual(ray["status"], "realized")
        self.assertEqual(ray["check"]["entropy"], [2, 2, 2])
        self.assertEqual(exact["status"], "realized")
        self.assertEqual(exact["graph"]["weights"], ["1/2", "1/2", "1/2"])
        self.assertEqual(exact["check"]["entropy"], [1, 1, 1])

    def test_fixed_n_lifts_to_exact_requested_active_vertex_count(self) -> None:
        result = find_graph_fixed_n([1, 1, 0], 5)
        self.assertEqual(result["status"], "realized")
        self.assertEqual(graph_total_vertices(result["graph"], 2), 5)
        self.assertTrue(result["check"]["ok"])

    def test_rational_graph_io_roundtrip_is_exact(self) -> None:
        graph = {"edges": [["A", "x1"], ["x1", "O"]], "weights": ["1/3", 2]}
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "graphs.json"
            write_graphs(path, [graph])
            self.assertEqual(read_graphs(path), [graph])

    def test_every_candidate_is_verified_and_reported(self) -> None:
        wrong = {"edges": [], "weights": []}
        with patch("hec._graph_search.solve_fixed_n", return_value=(wrong, {"status": "realized"})):
            result = find_graph([1], max_vertices=2)
        self.assertEqual(result["status"], "unknown")

        valid = {"edges": [["A", "O"]], "weights": [1]}
        with patch("hec._graph_search.solve_fixed_n", return_value=(valid, {"status": "realized"})):
            result = find_graph([1], max_vertices=2)
        self.assertEqual(result["status"], "realized")
        self.assertTrue(result["check"]["ok"])
        self.assertTrue(result["verification"]["ok"])

    def test_candidate_with_wrong_active_vertex_count_is_rejected(self) -> None:
        wrong_size = {"edges": [["x1", "O"]], "weights": [1]}
        with patch("hec._graph_search.solve_fixed_n", return_value=(wrong_size, {"status": "realized"})):
            result = find_graph_fixed_n([0], 2)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("does not use exactly 2", result["reason"]["reason"])

    def test_exact_candidate_with_noncanonical_bulk_labels_is_rejected(self) -> None:
        noncanonical = {"edges": [["A", "x2"], ["x2", "O"]], "weights": [1, 1]}
        with patch("hec._graph_search.solve_fixed_n", return_value=(noncanonical, {"status": "realized"})):
            result = find_graph_fixed_n([1], 3, match="exact")
        self.assertEqual(result["status"], "unknown")
        self.assertIn("contiguous from x1", result["reason"]["reason"])

    def test_trusted_infeasible_and_unknown_statuses_stay_distinct(self) -> None:
        with patch("hec._graph_search.solve_fixed_n", return_value=(None, {"status": "infeasible"})):
            result = find_graph_fixed_n([1], 2)
        self.assertEqual(result["status"], "infeasible")

        with patch("hec._graph_search.solve_fixed_n", return_value=(None, {"status": "unknown"})) as solve:
            result = find_graph([1], max_vertices=4)
        self.assertEqual(result["status"], "unknown")
        solve.assert_called_once()

    def test_search_time_limit_is_shared_across_vertex_counts(self) -> None:
        valid = {"edges": [["A", "x1"], ["x1", "O"]], "weights": [1, 1]}
        with (
            patch(
                "hec._graph_search.solve_fixed_n",
                side_effect=[(None, {"status": "infeasible"}), (valid, {"status": "realized"})],
            ) as solve,
            patch("hec.graphs.time.perf_counter", side_effect=[100.0, 101.0, 104.0, 105.0]),
        ):
            result = find_graph([1], max_vertices=3, time_limit_s=10)
        self.assertEqual(result["status"], "realized")
        self.assertEqual([call.kwargs["time_limit_s"] for call in solve.call_args_list], [9.0, 6.0])

    def test_invalid_inputs_fail_before_model_construction(self) -> None:
        with self.assertRaises(TypeError):
            find_graph([1])  # type: ignore[call-arg]
        for target in ([-1], [float("nan")], [True], [1.25], [1.0000000001]):
            with self.subTest(target=target), self.assertRaises(ValueError):
                find_graph(target, max_vertices=2)
        with self.assertRaises(ValueError):
            find_graph([1], max_vertices=1)
        with self.assertRaises(ValueError):
            find_graph_fixed_n([1], 2, workers=0)
        with self.assertRaises(ValueError):
            find_graph_fixed_n([1], 2, node_limit=0)
        with self.assertRaises(ValueError):
            find_graph_fixed_n([1], 2, time_limit_s=float("inf"))
        with self.assertRaises(ValueError):
            find_graph_fixed_n([1], 2, time_limit_s=True)
        with self.assertRaises(ValueError):
            find_graph_fixed_n([1], 2, time_limit_s="10")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            find_graph_fixed_n([1], 2, match="scale")  # type: ignore[arg-type]

    def test_ray_verification_has_no_tolerance_or_zero_loophole(self) -> None:
        near = {"edges": [["A", "O"], ["B", "O"]], "weights": [1_000_000.1, 1_000_000]}
        self.assertFalse(check_graph(near, [1_000_000, 1_000_000, 2_000_000], 2, match="ray")["ok"])
        self.assertTrue(check_graph({"edges": [], "weights": []}, [0], 1, match="ray")["ok"])
        self.assertFalse(check_graph({"edges": [["A", "O"]], "weights": [1e-8]}, [0], 1, match="ray")["ok"])

    def test_exact_verification_uses_exact_rational_equality(self) -> None:
        graph = {"edges": [["A", "O"]], "weights": [1.05]}
        self.assertFalse(check_graph(graph, [1], 1, match="exact")["ok"])
        self.assertTrue(check_graph(graph, ["21/20"], 1, match="exact")["ok"])

        huge = 10**400
        huge_check = check_graph({"edges": [["A", "O"]], "weights": [huge]}, [0], 1, match="exact")
        self.assertEqual(huge_check["max_error"], huge)
        json.dumps(huge_check, allow_nan=False)

    def test_search_visits_each_explicit_vertex_count(self) -> None:
        with patch("hec._graph_search.solve_fixed_n", return_value=(None, {"status": "infeasible"})) as solve:
            result = find_graph([0] * 63, max_vertices=12)
        self.assertEqual(result["status"], "infeasible")
        self.assertEqual([call.args[2] for call in solve.call_args_list], list(range(7, 13)))
        self.assertEqual(
            [call.kwargs["assume_no_smaller"] for call in solve.call_args_list],
            [False, True, True, True, True, True],
        )

    def test_generation_bound_covers_every_stored_graph(self) -> None:
        script = runpy.run_path(Path(__file__).parents[1] / "examples" / "find_ray_graphs.py")
        largest = max(graph_total_vertices(graph, n) for n in available_ns() for graph in load_hec_data(n, "graphs"))
        self.assertLessEqual(largest, script["DEFAULT_MAX_VERTICES"])

    def test_ray_results_are_primitive_and_strict_json(self) -> None:
        result = find_graph_fixed_n([11, 7, 6], 5, match="ray")
        self.assertEqual(result["status"], "realized")
        self.assertEqual(math.gcd(*result["graph"]["weights"]), 1)
        self.assertIsNone(result["check"]["max_error"])
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
