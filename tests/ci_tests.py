"""Exact unittest routing: every discovered case runs on each CI platform.

Portable controls stay in the short unit job; whole-catalogue regressions run
in a separate required job. Discovery produces a deterministic partition hash
which every executor must match. No environment-dependent skip/slow markers.
"""

import argparse
import faulthandler
import hashlib
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_PREFIXES = ("test_compact_database.ReadmeDataTests.",)
CATALOGUE_CASES = frozenset(
    {"test_graph_finder.PublicGraphFinderTests.test_n6_pathological_incumbents_are_polished_to_small_exact_graphs"}
)


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def partition_tests(suite, *, prefixes=CATALOGUE_PREFIXES, cases=CATALOGUE_CASES, source_tree=""):
    tests = list(flatten(suite))
    identities = [test.id() for test in tests]
    if not tests or len(identities) != len(set(identities)):
        raise ValueError("empty or duplicate unittest discovery is not complete coverage")
    if cases - set(identities) or any(not any(name.startswith(prefix) for name in identities) for prefix in prefixes):
        raise ValueError("configured catalogue test disappeared from discovery")
    groups = {"unit": [], "catalogue": []}
    for test in tests:
        name = test.id()
        group = "catalogue" if name in cases or name.startswith(prefixes) else "unit"
        groups[group].append(test)
    if any(not selected for selected in groups.values()):
        raise ValueError("every required test partition must be nonempty")
    manifest = {kind: sorted(test.id() for test in selected) for kind, selected in groups.items()}
    encoded = json.dumps(
        {"source_tree": source_tree, "tests": manifest}, sort_keys=True, separators=(",", ":")
    ).encode()
    return groups, manifest, hashlib.sha256(encoded).hexdigest()


class TimedResult(unittest.TextTestResult):
    def startTest(self, test):
        # A newline before unittest's partial status line survives job timeout.
        self.stream.writeln(f"START {test.id()}")
        self.stream.flush()
        self.started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        elapsed = time.perf_counter() - self.started
        super().stopTest(test)
        self.stream.writeln(f"ELAPSED {test.id()} {elapsed:.3f}s")
        self.stream.flush()


def complete_success(result, expected):
    return (
        result.wasSuccessful()
        and result.testsRun == expected
        and not result.skipped
        and not result.expectedFailures
        and not result.unexpectedSuccesses
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partition", choices=("unit", "catalogue"))
    parser.add_argument("--expected-plan")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT / "tests"))
    if loader.errors:
        raise ValueError("unittest discovery failed: " + "\n".join(loader.errors))
    source_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    groups, manifest, identity = partition_tests(suite, source_tree=source_tree)
    if args.expected_plan is not None and args.expected_plan != identity:
        raise ValueError("discovered tests differ from the exact CI test plan")
    if args.github_output is not None:
        if args.partition is not None:
            parser.error("only complete discovery may publish a CI test plan")
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"test_plan_sha256={identity}\n")
    if args.partition is None:
        print(json.dumps({"sha256": identity, "tests": manifest}, sort_keys=True))
        return 0
    if args.expected_plan is None:
        parser.error("a CI execution requires --expected-plan from complete discovery")
    selected = groups[args.partition]
    print(f"test plan {identity}: {args.partition}={len(selected)}; total={sum(map(len, groups.values()))}", flush=True)
    # Diagnostic only: no interrupted test or timer is ever turned into a pass.
    faulthandler.dump_traceback_later(120, repeat=True)
    try:
        result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(unittest.TestSuite(selected))
    finally:
        faulthandler.cancel_dump_traceback_later()
    return 0 if complete_success(result, len(selected)) else 1


if __name__ == "__main__":
    sys.exit(main())
