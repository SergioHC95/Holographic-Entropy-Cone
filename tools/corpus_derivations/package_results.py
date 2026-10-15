"""Immutable research recipe shards and a complete, gated corpus report.

This does not promote experimental recipe formats into the production reader.
Hashes establish identity/integrity, not mathematical validity. Mathematical
acceptance remains the independently executed original-cube audit recorded in
the completed source and alternative fresh passes.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from hec.count_proofs import canonical_json, inequality_id, parse_json

from . import run as derivations
from .simplify import METHOD
from .synthesize import EXPECTED_COUNTS, EXPECTED_TOTAL, VerifiedSource, decode_frame, geometry_only

FORMAT = "hec-research-recipe-catalog/1"
HASH = re.compile(r"[0-9a-f]{64}\Z")
SHARD_BYTES = 16 * 1024**2
RETAINED = "accepted_strictly_smaller_alternative"
DISPOSITIONS = {
    RETAINED,
    "unchanged_source_no_alternative",
    "incomplete_synthesis_budget_not_a_proof",
    "changed_seed_without_strict_description_improvement_not_retained",
}


class RecipeCatalog:
    """Exact-identity reader for research definitions; no stored validity flag."""

    def __init__(self, path):
        self.path = Path(path)
        document = parse_json(self.path.read_bytes())
        if not isinstance(document, dict) or set(document) != {"format", "scope", "entries", "shards"}:
            raise ValueError("invalid research recipe catalog fields")
        if document["format"] != FORMAT or not isinstance(document["scope"], dict):
            raise ValueError("unsupported research recipe catalog")
        self.scope, self.entries, self.shards = document["scope"], document["entries"], document["shards"]
        if not isinstance(self.entries, list) or not isinstance(self.shards, dict):
            raise ValueError("catalog entries/shards must be arrays/objects")
        self.verified = {}
        ranges, ids, tasks = {}, set(), set()
        for key, metadata in self.shards.items():
            if not isinstance(key, str) or HASH.fullmatch(key) is None or set(metadata) != {"bytes"}:
                raise ValueError("invalid immutable research shard identity")
            if type(metadata["bytes"]) is not int or metadata["bytes"] < 1:
                raise ValueError("invalid research shard size")
            ranges[key] = []
        fields = {"task", "inequality_id", "recipe_sha256", "origin", "shard", "offset", "bytes", "json_bytes"}
        for entry in self.entries:
            if not isinstance(entry, dict) or set(entry) != fields:
                raise ValueError("invalid research recipe entry")
            if any(
                not isinstance(entry[k], str) or HASH.fullmatch(entry[k]) is None
                for k in ("inequality_id", "recipe_sha256", "shard")
            ):
                raise ValueError("invalid recipe, inequality or shard hash")
            if entry["inequality_id"] in ids or entry["task"] in tasks:
                raise ValueError("duplicated corpus task/inequality")
            ids.add(entry["inequality_id"])
            tasks.add(entry["task"])
            if entry["origin"] not in ("verified-source", "verified-alternative"):
                raise ValueError("unknown selected recipe provenance")
            if any(type(entry[k]) is not int or entry[k] < 0 for k in ("task", "offset", "bytes", "json_bytes")):
                raise ValueError("invalid recipe offset/length/task")
            if not entry["bytes"] or entry["json_bytes"] > 1024**3 or entry["shard"] not in ranges:
                raise ValueError("recipe is outside the bounded shard inventory")
            start, stop = entry["offset"], entry["offset"] + entry["bytes"]
            if stop > self.shards[entry["shard"]]["bytes"]:
                raise ValueError("recipe interval exceeds its shard")
            ranges[entry["shard"]].append((start, stop))
        if (
            type(self.scope.get("proofs")) is not int
            or self.scope["proofs"] != len(self.entries)
            or tasks != set(range(len(self.entries)))
        ):
            raise ValueError("catalog task coverage differs from its stated scope")
        for key, intervals in ranges.items():
            cursor = 0
            for start, stop in sorted(intervals):
                if start != cursor:
                    raise ValueError("research shard overlap or unindexed bytes")
                cursor = stop
            if cursor != self.shards[key]["bytes"]:
                raise ValueError("research shard has unindexed trailing bytes")

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, index):
        return self.read_record(index)[0]

    def read_record(self, index):
        """One verified frame read, also available for lossless reframing."""
        entry = self.entries[index]
        path = self.path.parent / "recipe-shards" / f"{entry['shard']}.recipepack"
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ValueError("missing or unsafe research shard")
        stat = path.stat()
        fingerprint = stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
        if self.verified.get(entry["shard"]) != fingerprint:
            if stat.st_size != self.shards[entry["shard"]]["bytes"] or derivations.digest(path) != entry["shard"]:
                raise ValueError("research shard SHA256/length mismatch")
            self.verified[entry["shard"]] = fingerprint
        with path.open("rb") as stream:
            stream.seek(entry["offset"])
            data = stream.read(entry["bytes"])
        raw = decode_frame(data, entry["json_bytes"])
        if hashlib.sha256(raw).hexdigest() != entry["recipe_sha256"]:
            raise ValueError("research recipe SHA256 differs from its entry")
        recipe = parse_json(raw)
        if canonical_json(recipe) != raw or inequality_id(geometry_only(recipe)) != entry["inequality_id"]:
            raise ValueError("research recipe is noncanonical or belongs to another inequality")
        return recipe, data


class Shards:
    def __init__(self, output, target=SHARD_BYTES):
        if type(target) is not int or target < 1:
            raise ValueError("positive shard target required")
        self.root = output / "recipe-shards"
        self.root.mkdir()
        self.target, self.blocks, self.pending, self.entries, self.shards = target, bytearray(), [], [], {}

    def append(self, entry, data):
        if self.blocks and len(self.blocks) + len(data) > self.target:
            self.seal()
        entry = dict(entry, offset=len(self.blocks), bytes=len(data))
        self.pending.append(entry)
        self.blocks.extend(data)

    def seal(self):
        if not self.blocks:
            return
        sha = hashlib.sha256(self.blocks).hexdigest()
        destination = self.root / f"{sha}.recipepack"
        descriptor, temporary = tempfile.mkstemp(prefix=".recipe-shard-", dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(self.blocks)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, destination)  # Existing immutable objects are never overwritten.
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.shards[sha] = {"bytes": len(self.blocks)}
        self.entries.extend(dict(entry, shard=sha) for entry in self.pending)
        self.blocks.clear()
        self.pending.clear()


def export(
    source_root,
    synthesis_root,
    output,
    *,
    _expected_total=EXPECTED_TOTAL,
    _expected_counts=None,
    _shard_bytes=SHARD_BYTES,
):
    expected_counts = EXPECTED_COUNTS if _expected_counts is None else _expected_counts
    source = VerifiedSource(source_root, _expected_total=_expected_total, _expected_counts=expected_counts)
    lock, db = None, None
    try:
        synthesis_root, output = Path(synthesis_root).resolve(), Path(output).resolve()
        lock = (synthesis_root / "controller.lock").open("r")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        binding = parse_json((synthesis_root / "run-binding.json").read_bytes())
        if (
            binding["source_total"] != _expected_total
            or derivations.worker_count(binding) != derivations.worker_count(source.binding)
            or binding["method"] != METHOD
            or binding["source_records_sha256"] != source.records_sha256
        ):
            raise ValueError("synthesis binding differs from the fully verified source corpus")
        for relative, sha in binding["implementation"].items():
            if derivations.digest(synthesis_root / "implementation" / relative) != sha:
                raise ValueError("frozen synthesis code changed")
        for info in binding["binaries"].values():
            if derivations.digest(info["path"]) != info["sha256"]:
                raise ValueError("frozen synthesis binary changed")
        db = sqlite3.connect(f"file:{synthesis_root / 'checkpoint.sqlite3'}?mode=ro", uri=True)
        statuses = dict(db.execute("SELECT status,COUNT(*) FROM attempts GROUP BY status"))
        if sum(statuses.values()) != _expected_total or set(statuses) - DISPOSITIONS:
            raise ValueError("every source task needs an explicit supported synthesis disposition")
        if db.execute("SELECT COUNT(*) FROM errors").fetchone()[0]:
            raise ValueError("unresolved synthesis errors prevent a final report")
        accepted = statuses.get(RETAINED, 0)
        if db.execute("SELECT COUNT(*) FROM fresh WHERE ok=1").fetchone()[0] != accepted:
            raise ValueError("all retained alternatives require the separate source-free fresh audit")
        if output.exists() and any(output.iterdir()):
            raise ValueError("choose an empty new export; never replace an earlier result")
        output.mkdir(parents=True, exist_ok=True)
        shards = Shards(output, _shard_bytes)
        source_json = selected_json = source_frames = selected_frames = source_edges = alternative_edges = 0
        source_initial_json = phase_one_json = 0
        dimensions, winners, methods, denominators = Counter(), Counter(), {}, Counter()
        query = "SELECT task,inequality_id,recipe_sha256,json_bytes,compressed,report FROM results ORDER BY task"
        for task, iid, sha, size, data, source_report in source.db.execute(query):
            raw = source.validate_record(task, iid, sha, size, data)
            p = geometry_only(parse_json(raw))
            baseline = parse_json(source_report.encode())
            if baseline.get("winner_json_bytes") != size:
                raise ValueError("phase-one size receipt differs from the saved source definition")
            row = db.execute(
                """SELECT inequality_id,source_sha256,status,source_json_bytes,
                       alternative_json_bytes,alternative_sha256,compressed,report FROM attempts WHERE task=?""",
                (task,),
            ).fetchone()
            if row is None or row[0] != iid or row[1] != sha or row[3] != size:
                raise ValueError("synthesis attempt changed a source task/identity/hash/size")
            origin, selected_sha, selected_size, chosen = "verified-source", sha, size, data
            if row[2] == RETAINED:
                alternative_size, alternative_sha, chosen = row[4:7]
                candidate = decode_frame(chosen, alternative_size)
                report = parse_json(row[7].encode())
                if alternative_size >= size or hashlib.sha256(candidate).hexdigest() != alternative_sha:
                    raise ValueError("retained alternative is not strictly smaller or hash-bound")
                if (
                    canonical_json(parse_json(candidate)) != candidate
                    or inequality_id(geometry_only(parse_json(candidate))) != iid
                ):
                    raise ValueError("retained alternative changed the inequality or canonical encoding")
                if report.get("synthesis", {}).get("changed_cells", 0) < 1:
                    raise ValueError("retained alternative is not a changed exact map")
                receipt_row = db.execute("SELECT report FROM fresh WHERE task=? AND ok=1", (task,)).fetchone()
                if receipt_row is None:
                    raise ValueError("retained alternative has no successful fresh receipt")
                receipt = parse_json(receipt_row[0].encode())
                audit = receipt.get("full_cube_acceptance", {})
                if (
                    receipt.get("task") != task
                    or receipt.get("recipe_sha256") != alternative_sha
                    or receipt.get("ok") is not True
                    or receipt.get("source_tables_read") is not False
                    or audit.get("ok") is not True
                    or audit.get("scope") != "original-cube-all-edges"
                    or audit.get("checked_vertices") != p.vertices
                    or audit.get("checked_edges") != p.L * (p.vertices // 2)
                ):
                    raise ValueError("alternative receipt is mismatched or lacks complete original-cube coverage")
                origin, selected_sha, selected_size = "verified-alternative", alternative_sha, alternative_size
                alternative_edges += audit["checked_edges"]
            shards.append(
                {
                    "task": task,
                    "inequality_id": iid,
                    "recipe_sha256": selected_sha,
                    "origin": origin,
                    "json_bytes": selected_size,
                },
                chosen,
            )
            source_json += size
            selected_json += selected_size
            source_frames += len(data)
            selected_frames += len(chosen)
            source_edges += p.L * (p.vertices // 2)
            dimensions[str(p.L)] += 1
            winners[baseline["winner"]] += 1
            denominators[str(len(bin(int(baseline["seed_scale"]))) - 2)] += 1
            source_initial_json += baseline["source_json_bytes"]
            phase_one_json += baseline["winner_json_bytes"]
            for name, result in baseline["methods"].items():
                methods.setdefault(name, Counter())[result["status"]] += 1
        shards.seal()
        if len(shards.entries) != _expected_total:
            raise ValueError("export missed one or more corpus tasks")
        scope = {
            "proofs": _expected_total,
            "populations": expected_counts,
            "source_manifest_sha256": source.binding["manifest_sha256"],
            "source_records_sha256": source.records_sha256,
            "synthesis_binding_sha256": derivations.digest(synthesis_root / "run-binding.json"),
            "production_format_promoted": False,
        }
        catalog = {"format": FORMAT, "scope": scope, "entries": shards.entries, "shards": shards.shards}
        derivations.save_new(output / "recipes.json", catalog)
        # Re-read EVERY sealed frame and identity. This is packaging integrity,
        # not another mathematical acceptance claim.
        reader = RecipeCatalog(output / "recipes.json")
        for index in range(len(reader)):
            reader[index]
        report = {
            "format": "hec-full-corpus-derivation-report/1",
            "reported_utc": datetime.now(UTC).isoformat(),
            "scope": scope,
            "source_initial_full_cube_verified": _expected_total,
            "source_fresh_full_cube_verified": _expected_total,
            "retained_alternatives": accepted,
            "alternative_fresh_full_cube_verified": accepted,
            "synthesis_dispositions": statuses,
            "initial_source_definition_json_bytes": source_initial_json,
            "phase_one_selected_json_bytes": phase_one_json,
            "source_selected_json_bytes": source_json,
            "final_selected_json_bytes": selected_json,
            "synthesis_json_bytes_saved": source_json - selected_json,
            "source_selected_frame_bytes": source_frames,
            "final_selected_frame_bytes": selected_frames,
            "catalog_bytes": (output / "recipes.json").stat().st_size,
            "shard_bytes": sum(s["bytes"] for s in shards.shards.values()),
            "shards": len(shards.shards),
            "source_original_cube_edges_per_full_pass": source_edges,
            "retained_alternative_original_cube_edges_per_full_pass": alternative_edges,
            "source_dimensions": dict(dimensions),
            "source_seed_denominator_bit_lengths": dict(denominators),
            "phase_one_winners": dict(winners),
            "phase_one_method_statuses": {k: dict(v) for k, v in methods.items()},
            "packaging_integrity_checked_frames": len(reader),
            "processing_worker_limit": derivations.worker_count(binding),
            "source_checkpoint_parent": source.binding.get("checkpoint_parent"),
            "rss_limit_bytes": 64 * 1024**3,
            "original_archived_tables_overwritten": False,
            "comparison_scope": "canonical mathematical definition bytes; original enumerated audit downloads excluded",
            "cpu_totals": "not collected; per-case wall timings are not aggregate CPU time",
            "remaining_goal_work": "independent final review and any needed additional synthesis improvements",
        }
        derivations.save_new(output / "report.json", report)
        return report
    finally:
        if db is not None:
            db.close()
        if lock is not None:
            lock.close()
        source.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--synthesis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = export(args.source, args.synthesis, args.output)
    print(canonical_json(report).decode())


if __name__ == "__main__":
    main()
