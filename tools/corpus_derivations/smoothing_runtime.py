"""Frozen-run-only dispatch for the same exact smoother, never proof acceptance."""

from __future__ import annotations

import atexit
import sqlite3
from contextlib import closing
from functools import partial
from pathlib import Path

from hec.count_proofs import parse_json

from . import run as derivations
from .native_smooth import POLICY, NativeSmoother, supported
from .simplify import smooth

MIN_CELLS = 16384
SOURCE = "tools/corpus_derivations/smooth_exact.cpp"
CONTROL_TASKS = frozenset(
    (0, 24, 16, 993, 991, 3768, 262, 74722, 84323, 81205, 83786, 80231, 80253, 80259, 80285, 80289)
)
BUDGET_TASKS = frozenset((80231, 80253, 80259, 80285))
_ENGINE, _KEY = None, None


def sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def parameters(config):
    if (
        not isinstance(config, dict)
        or set(config) != {"policy", "path", "sha256", "source_sha256", "min_cells"}
        or config["policy"] != POLICY
        or type(config["min_cells"]) is not int
        or config["min_cells"] != MIN_CELLS
        or not sha(config["sha256"])
        or not sha(config["source_sha256"])
        or not isinstance(config["path"], str)
        or not Path(config["path"]).is_absolute()
    ):
        raise ValueError("unsupported frozen exact smoothing backend binding")
    return config


def review_controls(directory, implementation, source_binding, *, check_binary=False):
    """Inspect executed, source/code-bound performance evidence, not a proof cache."""
    directory, implementation = Path(directory), Path(implementation)
    binding_path, report_path = directory / "binding.json", directory / "report.json"
    binding, report = parse_json(binding_path.read_bytes()), parse_json(report_path.read_bytes())
    if (
        binding.get("format") != "hec-native-smoothing-control-run/1"
        or report.get("format") != "hec-native-smoothing-control-report/1"
        or report.get("binding_sha256") != derivations.digest(binding_path)
        or binding.get("source_binding_sha256") != derivations.digest(source_binding)
        or binding.get("paired_repeats") != 2
        or binding.get("sweeps") != 2
        or binding.get("max_work") != 50_000_000
        or binding.get("production_workers_started") != 0
        or binding.get("rss_limit_bytes") != 64 * 1024**3
        or report.get("live_cohort_modified") is not False
        or set(binding.get("tasks", [])) != CONTROL_TASKS
        or len(binding.get("tasks", [])) != len(CONTROL_TASKS)
    ):
        raise ValueError("native smoothing control source, settings or complete scope changed")
    for relative, expected in binding["implementation"].items():
        if not sha(expected) or derivations.digest(implementation / relative) != expected:
            raise ValueError("native smoothing control implementation changed: " + relative)
    if SOURCE not in binding["implementation"] or not sha(binding["binary"].get("sha256")):
        raise ValueError("native control lacks explicit source/binary identity")
    cases = report.get("cases", [])
    if len(cases) != len(CONTROL_TASKS) or {case.get("task") for case in cases} != CONTROL_TASKS:
        raise ValueError("native control report has missing or repeated tasks")
    source_db = Path(source_binding).parent / "checkpoint.sqlite3"
    with closing(sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)) as db:
        identities = {
            task: db.execute("SELECT inequality_id,recipe_sha256 FROM results WHERE task=?", (task,)).fetchone()
            for task in CONTROL_TASKS
        }
    for case in cases:
        if (
            type(case.get("task")) is not int
            or any(
                type(case.get(key)) is not int or case[key] < 0
                for key in ("L", "G", "compatible_vertices", "compatible_cells_compared")
            )
            or not 0 <= case["L"] <= 25
            or not 0 <= case["G"] <= 63
            or identities[case["task"]] != (case.get("inequality_id"), case.get("source_sha256"))
        ):
            raise ValueError("native control source identity or typed geometry changed")
        if len(case.get("paired_comparisons", [])) != 2 or case.get("full_corpus_coverage_claimed") is not False:
            raise ValueError("native controls changed their executed comparison scope")
        if case["task"] in BUDGET_TASKS:
            if (
                case.get("status") != "identical_budget_exhaustion_not_a_proof"
                or case.get("independent_original_cube_audit") is not None
                or case.get("statistics") is not None
                or case.get("compatible_cells_compared") != 0
            ):
                raise ValueError("budget-limited control was incorrectly promoted to a proof")
            continue
        audit, stats = case.get("independent_original_cube_audit"), case.get("statistics")
        if case.get("status") != "complete" or not isinstance(audit, dict) or not isinstance(stats, dict):
            raise ValueError("complete native control lacks its executed independent cube audit")
        expected = {
            "ok": True,
            "scope": "original-cube-all-edges",
            "L": case["L"],
            "G": case["G"],
            "seed_vertices": case["compatible_vertices"],
            "seed_scale": stats.get("candidate_scale"),
            "checked_vertices": 1 << case["L"],
            "checked_edges": case["L"] * ((1 << case["L"]) // 2),
        }
        if any(type(audit.get(key)) is not type(value) or audit[key] != value for key, value in expected.items()):
            raise ValueError("native control cube audit has incomplete or incorrectly typed coverage")
        if case["compatible_cells_compared"] != case["compatible_vertices"] * case["G"]:
            raise ValueError("native control did not compare all compatible counts")
    if check_binary:
        NativeSmoother(binding["binary"]["path"], binding["binary"]["sha256"]).close()
    return {
        "binding": binding,
        "report": report,
        "binding_sha256": derivations.digest(binding_path),
        "report_sha256": derivations.digest(report_path),
    }


def validate_run(settings, output):
    config = parameters(settings["smoothing_backend"])
    output = Path(output)
    if config["path"] != str(output / "smoother") or settings["implementation"].get(SOURCE) != config["source_sha256"]:
        raise ValueError("native smoother must match this frozen generation's source and binary path")
    validation = settings.get("smoothing_validation")
    if not isinstance(validation, dict) or set(validation) != {"binding_sha256", "report_sha256"}:
        raise ValueError("native smoother requires frozen reviewed control evidence")
    reviewed = review_controls(
        output / "smoothing-controls", output / "implementation", Path(settings["source"]) / "run-binding.json"
    )
    if any(validation[key] != reviewed[key] for key in validation):
        raise ValueError("native smoother control evidence changed")
    if (
        reviewed["binding"]["binary"]["sha256"] != config["sha256"]
        or reviewed["binding"]["implementation"][SOURCE] != config["source_sha256"]
        or settings["sweeps"] != reviewed["binding"]["sweeps"]
        or settings["max_work"] != reviewed["binding"]["max_work"]
    ):
        raise ValueError("native smoothing settings or reviewed source/binary changed")
    NativeSmoother(config["path"], config["sha256"]).close()


def close():
    global _ENGINE, _KEY
    if _ENGINE is not None:
        _ENGINE.close()
    _ENGINE, _KEY = None, None


def operation(settings, p, vertices, scale, rows):
    """Return the actual chosen operation and its provenance BEFORE execution.

    Small/unsupported seeds use the identical arbitrary-precision reference.
    Every candidate still needs independent original-cube acceptance. Nothing
    here is called by the saved-artifact fresh audit path.
    """
    global _ENGINE, _KEY
    config = parameters(settings["smoothing_backend"])
    limits = {"sweeps": settings["sweeps"], "max_work": settings["max_work"]}
    values = p, vertices, scale, rows
    metadata = {
        "policy": POLICY,
        "seed_cells": len(vertices) * p.G,
        "min_cells": MIN_CELLS,
        "implementation": "python-reference",
        "mathematical_acceptance_cached": False,
    }
    if metadata["seed_cells"] < MIN_CELLS:
        metadata["reason"] = "tiny_seed_below_measured_crossover"
        return partial(smooth, *values, **limits), metadata
    if not supported(*values, **limits):
        metadata["reason"] = "unsupported_exact_native_capability_no_truncation"
        return partial(smooth, *values, **limits), metadata
    key = config["path"], config["sha256"], config["source_sha256"]
    if _ENGINE is None:
        _ENGINE = NativeSmoother(config["path"], config["sha256"])
        _KEY = key
    elif _KEY != key:
        raise ValueError("native smoothing binding changed inside a processing worker")
    metadata.update(
        implementation="native-uint64-uint128-with-python-postchecks",
        binary_sha256=config["sha256"],
        source_sha256=config["source_sha256"],
        reason="measured_native_capability",
    )
    return partial(_ENGINE.smooth, *values, **limits), metadata


atexit.register(close)
