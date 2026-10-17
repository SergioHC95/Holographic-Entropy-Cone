from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pyscipopt

from hec._graph_epr import _build_epr_model, _solve_epr_native, solve_epr_free
from hec._graph_native import build_constraints
from hec._graph_pair import pair_cut_disjunctions
from hec.coordinates import subsets


def reference_constraints(scip, model, variables):
    for row in range(model.matrix.shape[0]):
        first, last = model.matrix.indptr[row : row + 2]
        expression = pyscipopt.quicksum(
            float(value) * variables[int(column)]
            for column, value in zip(model.matrix.indices[first:last], model.matrix.data[first:last], strict=True)
        )
        scip.addCons(expression <= float(model.rhs[row]))
    for ordinal, choices in enumerate(model.disjunctions):
        expressions = [
            pyscipopt.quicksum(value * variables[column] for column, value in enumerate(row) if value) <= bound
            for row, bound in choices
        ]
        scip.addConsDisjunction(expressions, name=f"attaining_cut_{ordinal}")
    return {"policy": "reference_in_test"}


class NativeConstructionTests(unittest.TestCase):
    def model(self, bulk_count=4):
        columns = (
            (1, 1, 1, 1, 1, 0, 0),
            (0, 0, 1, 1, 1, 1, 1),
            (1, 0, 1, 0, 1, 1, 1),
            (0, 1, 0, 1, 1, 1, 1),
        )
        target = tuple(
            sum(min(sum(column[t] for t in side), sum(column) - sum(column[t] for t in side)) for column in columns)
            for side in subsets(6)
        )
        result = pair_cut_disjunctions(_build_epr_model(target, bulk_count))
        self.assertTrue(result.disjunctions)
        return result

    def variables(self, scip, model):
        return [scip.addVar(name=f"w{i}", lb=0, ub=float(value), vtype="C") for i, value in enumerate(model.upper)]

    def test_full_native_model_and_check_flags_match_standard_construction(self):
        for bulk_count in (4, 5):
            with self.subTest(bulk_count=bulk_count):
                self.assert_standard_construction_identical(self.model(bulk_count))

    def assert_standard_construction_identical(self, model):
        class Captured(Exception):
            pass

        with tempfile.TemporaryDirectory(prefix="hec-native-test-") as temp:
            outputs = []
            for standard in (False, True):
                filename = Path(temp) / ("standard.cip" if standard else "batch.cip")
                snapshots = []

                class Capture(pyscipopt.Model):
                    def optimize(self, _filename=filename, _snapshots=snapshots):
                        flags = (
                            "isInitial",
                            "isSeparated",
                            "isEnforced",
                            "isChecked",
                            "isPropagated",
                            "isLocal",
                            "isModifiable",
                            "isDynamic",
                            "isRemovable",
                            "isStickingAtNode",
                        )
                        _snapshots.append(
                            [
                                (c.name, c.getConshdlrName(), tuple(getattr(c, flag)() for flag in flags))
                                for c in self.getConss(transformed=False)
                            ]
                        )
                        self.writeProblem(str(_filename), verbose=False)
                        raise Captured()

                with patch("pyscipopt.Model", Capture):
                    if standard:
                        with patch("hec._graph_native.build_constraints", side_effect=reference_constraints):
                            with self.assertRaises(Captured):
                                _solve_epr_native(model)
                    else:
                        with self.assertRaises(Captured):
                            _solve_epr_native(model)
                outputs.append((filename.read_bytes(), snapshots))
            self.assertEqual(outputs[0], outputs[1])

    def test_nonempty_native_state_is_never_reused(self):
        model = self.model()
        scip = pyscipopt.Model()
        try:
            scip.hideOutput()
            variables = self.variables(scip, model)
            scip.addCons(variables[0] <= 1)
            with patch("hec._graph_native.native_functions", side_effect=AssertionError("ABI reached")):
                with self.assertRaisesRegex(RuntimeError, "nonempty"):
                    build_constraints(scip, model, variables)
        finally:
            scip.free()

    def test_malformed_sparse_indices_fail_before_native_calls(self):
        model = self.model()
        matrix = model.matrix.copy()
        matrix.indices[0] = len(model.upper)
        invalid = replace(model, matrix=matrix)
        scip = pyscipopt.Model()
        try:
            scip.hideOutput()
            variables = self.variables(scip, model)
            with patch("hec._graph_native.native_functions", side_effect=AssertionError("ABI reached")):
                with self.assertRaisesRegex(ValueError, "invalid sparse"):
                    build_constraints(scip, invalid, variables)
        finally:
            scip.free()

    def test_native_errors_and_incomplete_inventory_cannot_become_unsat(self):
        target = self.model().target
        for response in ((-9, 0, 0), (1, -1, -1)):
            with (
                self.subTest(response=response),
                patch("hec._graph_native.construct_constraints", return_value=response),
            ):
                graph, info = solve_epr_free(target, total_vertices=11)
            self.assertIsNone(graph)
            self.assertEqual(info["status"], "unknown")
            self.assertEqual(info["reason"], "reduced_backend_error")

    def test_unvalidated_abi_fails_before_raw_native_calls(self):
        class WrongVersion(pyscipopt.Model):
            def getMajorVersion(self):
                return 99

        model = self.model()
        scip = WrongVersion()
        try:
            variables = self.variables(scip, model)
            with patch("hec._graph_native.native_functions", side_effect=AssertionError("ABI reached")):
                with self.assertRaisesRegex(RuntimeError, "unvalidated SCIP"):
                    build_constraints(scip, model, variables)
        finally:
            scip.free()


if __name__ == "__main__":
    unittest.main()
