"""Read-only complete-corpus promotion precondition, not a new math audit.

No reader/data/CI switch, Git/LFS operation, stored flag as new acceptance, or
subset CLI. Independently reconcile all frozen inputs, real result rows and
actual staged frames after the original audit process and helpers are idle.
"""

from __future__ import annotations

import argparse
import fcntl
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hec.count_proofs import canonical_json, decimal, geometry, parse_json, proof_geometry, proof_id
from hec.inequality_records import InequalityCatalog
from hec.reconstruction import EXTENSION, PIPELINE
from hec.reconstruction_store import ReconstructionCatalog

from . import run as derivations
from .continue_pipeline import idle
from .repository_audit import FORMAT, validate_result
from .synthesize import EXPECTED_COUNTS, EXPECTED_TOTAL


def equal(actual, expected, label):
    if type(actual) is not type(expected) or actual != expected:
        raise ValueError("incomplete or changed acceptance evidence: " + label)


def bound(path, sha):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or derivations.digest(path) != sha:
        raise ValueError("bound acceptance input changed: " + str(path))


def review(output, *, _expected_total=EXPECTED_TOTAL, _expected_counts=None):
    output = Path(output).resolve()
    counts = EXPECTED_COUNTS if _expected_counts is None else _expected_counts
    if not idle(output, set()):
        raise BlockingIOError("full audit controller/native helpers remain live; no promotion acceptance")
    with (output / "controller.lock").open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        binding = parse_json((output / "run-binding.json").read_bytes())
        equal(binding.get("format"), FORMAT, "audit version")
        equal(binding.get("total"), _expected_total, "all source identities")
        equal(binding.get("scope_counts"), counts, "population scope")
        equal(binding.get("rss_limit_bytes"), 64 * 1024**3, "unchanged RSS cap")
        derivations.worker_count(binding)
        bound(output / "manifest.json", binding["manifest_sha256"])
        manifest = parse_json((output / "manifest.json").read_bytes())
        if len(manifest) != _expected_total or [item["task"] for item in manifest] != list(range(_expected_total)):
            raise ValueError("audit manifest does not cover every task exactly once")
        if len({item["inequality_id"] for item in manifest}) != _expected_total:
            raise ValueError("audit manifest repeats an inequality instead of covering the whole corpus")
        for relative, sha in binding["implementation"].items():
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or path.suffix not in (".py", ".cpp"):
                raise ValueError("unsafe frozen implementation reference")
            bound(output / "implementation" / path, sha)
        for label, info in binding["binaries"].items():
            if Path(info["path"]).resolve() != output / label:
                raise ValueError("audit backend is outside its immutable run")
            bound(info["path"], info["sha256"])
        profile = binding.get("cube_backend_profile")
        if _expected_total == EXPECTED_TOTAL and profile is None:
            raise ValueError("complete standard corpus requires the qualified standard native profile")
        if profile is not None:
            equal(profile["sha256"], binding["binaries"]["wide"]["sha256"], "actual cube binary")
            equal(profile["source_sha256"], binding["implementation"]["tools/verify_reconstruction.cpp"], "cube source")
            equal(profile["primary_output_buffer_bytes"], 256 * 1024**2, "bound native output budget")
            for label in ("controls", "control_binding"):
                bound(profile[label], profile[label + "_sha256"])
        stage, conversion = Path(binding["stage"]), Path(binding["conversion"])
        bound(stage / "stage-report.json", binding["stage_report_sha256"])
        bound(conversion / "run-binding.json", binding["conversion_binding_sha256"])
        staged = parse_json((stage / "stage-report.json").read_bytes())
        equal(staged.get("proofs"), _expected_total, "complete staging")
        equal(staged.get("scope_counts"), counts, "staged population scope")
        equal(staged.get("frames_recompressed"), 0, "lossless frame transfer")
        equal(staged.get("packaging_integrity_checked_frames"), _expected_total, "staged frames checked")
        equal(
            staged.get("conversion_binding_sha256"), binding["conversion_binding_sha256"], "staging/conversion identity"
        )
        exported = Path(staged["source_export"])
        bound(exported / "report.json", staged["source_export_report_sha256"])
        export = parse_json((exported / "report.json").read_bytes())
        equal(export.get("exact_converted_inequality_identities"), _expected_total, "complete export")
        equal(export.get("packaging_integrity_checked_frames"), _expected_total, "all exported frames checked")
        equal(
            export.get("new_exhaustive_original_cube_audits_executed_by_conversion"), 0, "no invented conversion audits"
        )
        equal(export["scope"].get("definition_profile"), PIPELINE, "one proof language")
        equal(export["scope"].get("extension"), EXTENSION, "one extension rule")
        original = parse_json((conversion / "run-binding.json").read_bytes())
        source = Path(original["source"])
        bound(source / "run-binding.json", original["source_binding_sha256"])
        source_binding = parse_json((source / "run-binding.json").read_bytes())
        bound(source / "manifest.json", source_binding["manifest_sha256"])
        source_manifest = parse_json((source / "manifest.json").read_bytes())
        source_ids = {item["inequality_id"]: item for item in source_manifest}
        if len(source_ids) != _expected_total or set(source_ids) != {item["inequality_id"] for item in manifest}:
            raise ValueError("audit/staging dropped or substituted an original source inequality")
        equal(
            dict(Counter(item["group"] if item["n"] == 6 else "small-n" for item in source_manifest)),
            counts,
            "actual source populations",
        )
        with closing(sqlite3.connect(f"file:{conversion / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            equal(db.execute("SELECT COUNT(*) FROM converted").fetchone()[0], _expected_total, "conversion ledger")
            equal(db.execute("SELECT COUNT(*) FROM errors").fetchone()[0], 0, "conversion errors")
            chosen = {
                iid: (pid, semantic)
                for iid, pid, semantic in db.execute("SELECT inequality_id,proof_id,semantic_map_id FROM converted")
            }
        if set(chosen) != set(source_ids):
            raise ValueError("conversion ledger differs from exact original identity set")
        catalogs, geometries = {}, {}
        for n, info in binding["catalogs"].items():
            path = Path(info["path"])
            if path != stage / "data" / f"n={int(n)}" / "proofs.json":
                raise ValueError("staged catalogue lies outside its expected party directory")
            bound(path, info["sha256"])
            bound(path.with_name("inequalities.json"), info["inequalities_sha256"])
            catalog, records = ReconstructionCatalog(path), InequalityCatalog(path.with_name("inequalities.json"))
            records.check_bindings(catalog)
            equal(catalog.shards, info["shards"], "immutable shard manifest")
            for sha, meta in info["shards"].items():
                payload = path.parent / "proof-shards" / f"{sha}.proofpack"
                bound(payload, sha)
                equal(payload.stat().st_size, meta["bytes"], "payload byte count")
            catalogs[n] = catalog
            for iid, item in records.entries.items():
                if item["n"] != int(n) or iid in geometries:
                    raise ValueError("mixed/repeated party-frame identity")
                geometries[iid] = geometry(item["n"], tuple(map(decimal, item["coefficients"])))
        if set(geometries) != set(source_ids):
            raise ValueError("staged inequality indexes do not cover the original source set")
        edges, vertices, seen, parties = 0, 0, set(), Counter()
        with closing(sqlite3.connect(f"file:{output / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            equal(
                db.execute("SELECT COUNT(*) FROM audited").fetchone()[0],
                _expected_total,
                "actual successful result rows",
            )
            equal(db.execute("SELECT COUNT(*) FROM errors").fetchone()[0], 0, "actual audit errors")
            rows = db.execute("SELECT task,proof_id,report FROM audited ORDER BY task")
            for item, (task, pid, raw) in zip(manifest, rows, strict=True):
                equal(task, item["task"], "result task order")
                equal(pid, item["proof_id"], "result definition identity")
                result = parse_json(raw.encode())
                validate_result(result, item)
                iid = item["inequality_id"]
                equal((pid, item["semantic_map_id"]), chosen[iid], "actual map versus selected conversion")
                p = geometries[iid]
                equal((p.n, p.L, p.G), (item["n"], item["L"], item["G"]), "actual geometry")
                entry = catalogs[str(p.n)].entries[item["index"]]
                equal((entry["inequality_id"], entry["proof_id"]), (iid, pid), "actual frame/index binding")
                doc = catalogs[str(p.n)][item["index"]]
                equal(proof_id(doc), pid, "actual stored canonical definition")
                equal(proof_geometry(doc), p, "actual stored inequality")
                audit = result["audit"]
                if profile is not None and audit.get("implementation") != "exact-fraction-reference/1":
                    equal(audit.get("binary_sha256"), profile["sha256"], "actually used native binary")
                    equal(
                        audit.get("output_row_storage_limit"),
                        profile["primary_output_buffer_bytes"],
                        "actual native budget",
                    )
                    used = audit.get("output_row_storage_bytes")
                    if type(used) is not int or not 0 <= used <= profile["primary_output_buffer_bytes"]:
                        raise ValueError("native result did not honor the selected memory profile")
                elif audit.get("implementation") == "exact-fraction-reference/1" and p.vertices > 16384:
                    raise ValueError("reference result claims unsupported large-cube scope")
                seen.add(iid)
                parties[str(p.n)] += 1
                vertices += p.vertices
                edges += p.L * (p.vertices // 2)
        if seen != set(source_ids):
            raise ValueError("actual successful audits are not exactly the original full corpus")
        report = parse_json((output / "report.json").read_bytes())
        expected = {
            "format": FORMAT,
            "actual_full_cube_audited": _expected_total,
            "checked_original_cube_vertices": vertices,
            "checked_original_cube_edges": edges,
            "party_counts": dict(parties),
            "recorded_errors": 0,
            "source_tables_read": False,
            "stored_acceptance_flags_used": False,
            "run_binding_sha256": derivations.digest(output / "run-binding.json"),
        }
        for key, value in expected.items():
            equal(report.get(key), value, "completed report " + key)
        equal(
            export.get("selected_original_cube_edges_covered_by_executed_evidence"),
            edges,
            "geometry versus original evidence",
        )
        return {
            "format": "hec-full-corpus-acceptance-review/1",
            "reviewed_utc": datetime.now(UTC).isoformat(),
            "audit": str(output),
            "stage": str(stage),
            "proofs": _expected_total,
            "scope_counts": counts,
            "checked_stored_frames": _expected_total,
            "actual_prior_audit_vertices_reconciled": vertices,
            "actual_prior_audit_edges_reconciled": edges,
            "new_mathematical_audits_executed_by_review": 0,
            "audit_report_sha256": derivations.digest(output / "report.json"),
            "audit_binding_sha256": derivations.digest(output / "run-binding.json"),
            "staging_binding_sha256": binding["stage_report_sha256"],
            "mathematical_promotion_precondition_passed": True,
            "repository_reader_data_or_ci_changed": False,
            "git_lfs_or_billing_mutated": False,
            "facet_or_rank_claims_inherited": False,
            "full_goal_complete": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()
    print(canonical_json(review(args.audit)).decode())


if __name__ == "__main__":
    main()
