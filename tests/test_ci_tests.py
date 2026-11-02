"""The routing itself must not permit missing, skipped, or duplicate tests."""

import io
import unittest

from ci_tests import TimedResult, complete_success, partition_tests


def controls():
    class Control(unittest.TestCase):
        def test_a(self):
            pass

        def test_b(self):
            pass

        def test_c(self):
            pass

    return [Control(name) for name in ("test_a", "test_b", "test_c")]


class TestPlanTests(unittest.TestCase):
    def test_every_discovered_case_has_exactly_one_partition(self):
        cases = controls()
        wanted = frozenset({cases[0].id()})
        groups, manifest, identity = partition_tests(unittest.TestSuite(cases), prefixes=(), cases=wanted)
        self.assertEqual(set(manifest["unit"]) | set(manifest["catalogue"]), {case.id() for case in cases})
        self.assertFalse(set(manifest["unit"]) & set(manifest["catalogue"]))
        self.assertEqual(sum(map(len, groups.values())), 3)
        reordered = partition_tests(unittest.TestSuite(reversed(cases)), prefixes=(), cases=wanted)
        self.assertEqual(identity, reordered[2])
        bound = partition_tests(unittest.TestSuite(cases), prefixes=(), cases=wanted, source_tree="different")
        self.assertNotEqual(identity, bound[2])

    def test_empty_duplicate_missing_and_unassigned_partitions_fail_closed(self):
        cases = controls()
        bad = (
            ([], (), frozenset()),
            ([cases[0], cases[0]], (), frozenset({cases[0].id()})),
            (cases, ("missing.class.",), frozenset()),
            (cases, (), frozenset({"missing.case"})),
            (cases, (), frozenset()),
            (cases, (), frozenset(case.id() for case in cases)),
        )
        for selected, prefixes, wanted in bad:
            with self.subTest(selected=len(selected), wanted=wanted), self.assertRaises(ValueError):
                partition_tests(unittest.TestSuite(selected), prefixes=prefixes, cases=wanted)

    def test_completion_rejects_missing_skipped_and_expected_failure_cases(self):
        result = unittest.TestResult()
        result.testsRun = 3
        self.assertTrue(complete_success(result, 3))
        self.assertFalse(complete_success(result, 4))
        for field in ("skipped", "expectedFailures", "unexpectedSuccesses", "failures", "errors"):
            values = getattr(result, field)
            values.append((controls()[0], "synthetic incomplete result"))
            self.assertFalse(complete_success(result, 3), field)
            values.clear()

    def test_start_record_has_a_complete_line_before_the_case_executes(self):
        output = io.StringIO()

        class Control(unittest.TestCase):
            def runTest(self):
                self.assertIn(f"START {self.id()}\n", output.getvalue())

        result = unittest.TextTestRunner(stream=output, verbosity=2, resultclass=TimedResult).run(Control())
        self.assertTrue(complete_success(result, 1))
        self.assertIn("ELAPSED", output.getvalue())
