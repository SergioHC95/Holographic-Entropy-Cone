"""One locked, fully audited selection for downstream representation conversion.

This is a provenance/coverage gate, not a new mathematical verifier. It binds
each selected definition to its actually executed source-free full-cube audit.
No search, artifact rewrite, source-table read or publication occurs here.
"""

from __future__ import annotations

import fcntl
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from hec.count_proofs import canonical_json, inequality_id, parse_json

from . import run as derivations
from .continue_pipeline import idle
from .package_results import DISPOSITIONS, RETAINED
from .simplify import METHOD
from .synthesize import EXPECTED_COUNTS, EXPECTED_TOTAL, VerifiedSource, decode_frame, geometry_only


@dataclass(frozen=True)
class SelectedDefinition:
    task: int
    inequality_id: str
    recipe_sha256: str
    raw: bytes
    origin: str
    audit_root: str
    audit_receipt_sha256: str
    audit_receipt: bytes

    def binding(self):
        return {
            "task": self.task,
            "inequality_id": self.inequality_id,
            "recipe_sha256": self.recipe_sha256,
            "origin": self.origin,
            "audit_root": self.audit_root,
            "audit_receipt_sha256": self.audit_receipt_sha256,
        }


def check_audit(receipt, task, sha, p):
    """Validate scope and identity, never treat a seed-only receipt as a cube audit."""
    if not isinstance(receipt, dict):
        raise ValueError("selected audit receipt must be an object")
    if (
        type(receipt.get("task")) is not int
        or receipt["task"] != task
        or receipt.get("recipe_sha256") != sha
        or receipt.get("ok") is not True
        or receipt.get("source_tables_read") is not False
    ):
        raise ValueError("selected full-cube receipt has wrong identity or source-free status")
    audit = receipt.get("full_cube_acceptance", {})
    if (
        not isinstance(audit, dict)
        or audit.get("ok") is not True
        or audit.get("scope") != "original-cube-all-edges"
        or type(audit.get("checked_vertices")) is not int
        or audit["checked_vertices"] != p.vertices
        or type(audit.get("checked_edges")) is not int
        or audit["checked_edges"] != p.L * (p.vertices // 2)
    ):
        raise ValueError("selected receipt lacks complete exact original-cube coverage")


class VerifiedSelection:
    """Complete selected corpus after BOTH source and alternative fresh phases.

    Private fixture scope parameters are never exposed by a corpus CLI. Live
    controllers/native children are not adopted, stopped or competed with.
    """

    def __init__(self, source, synthesis, *, _expected_total=EXPECTED_TOTAL, _expected_counts=None):
        self.source, self.db, self.lock = None, None, None
        self.root = Path(synthesis).resolve()
        self.expected = _expected_total
        self.expected_counts = EXPECTED_COUNTS if _expected_counts is None else _expected_counts
        try:
            if not idle(Path(source).resolve(), set()) or not idle(self.root, set()):
                raise BlockingIOError("source/synthesis controller or worker is still live; no competing conversion")
            self.source = VerifiedSource(source, _expected_total=_expected_total, _expected_counts=self.expected_counts)
            self.lock = (self.root / "controller.lock").open("r")
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.binding = parse_json((self.root / "run-binding.json").read_bytes())
            if (
                self.binding.get("source") != str(self.source.root)
                or self.binding.get("source_total") != _expected_total
                or self.binding.get("source_records_sha256") != self.source.records_sha256
                or self.binding.get("source_manifest_sha256") != self.source.binding["manifest_sha256"]
                or self.binding.get("method") != METHOD
                or self.binding.get("rss_limit_bytes") != 64 * 1024**3
                or derivations.worker_count(self.binding) != derivations.worker_count(self.source.binding)
            ):
                raise ValueError("synthesis binding differs from the fully verified source corpus")
            for relative, sha in self.binding["implementation"].items():
                if derivations.digest(self.root / "implementation" / relative) != sha:
                    raise ValueError("frozen synthesis implementation changed")
            for info in self.binding["binaries"].values():
                if derivations.digest(info["path"]) != info["sha256"]:
                    raise ValueError("frozen synthesis primitive binary changed")
            if "checkpoint_parent" in self.binding:
                from .speedup_rollout import validate_inheritance

                validate_inheritance(self.root, self.binding)
            self.db = sqlite3.connect(f"file:{self.root / 'checkpoint.sqlite3'}?mode=ro", uri=True)
            self.db.execute("BEGIN")
            self.statuses = dict(self.db.execute("SELECT status,COUNT(*) FROM attempts GROUP BY status"))
            if sum(self.statuses.values()) != _expected_total or set(self.statuses) - DISPOSITIONS:
                raise ValueError("every source identity requires a supported synthesis disposition")
            if self.db.execute("SELECT COUNT(*) FROM errors").fetchone()[0]:
                raise ValueError("unresolved synthesis errors block unified conversion")
            accepted = self.statuses.get(RETAINED, 0)
            if (
                self.db.execute("SELECT COUNT(*) FROM fresh").fetchone()[0] != accepted
                or self.db.execute("SELECT COUNT(*) FROM fresh WHERE ok=1").fetchone()[0] != accepted
            ):
                raise ValueError("every retained alternative requires the separate source-free full-cube audit")
            digest, seen = hashlib.sha256(), 0
            for record in self.items():
                digest.update(canonical_json(record.binding()) + b"\n")
                seen += 1
            if seen != _expected_total:
                raise ValueError("selected corpus has incomplete manifest coverage")
            self.records_sha256 = digest.hexdigest()
        except Exception:
            self.close()
            raise

    def items(self, done=frozenset()):
        query = "SELECT task,inequality_id,recipe_sha256,json_bytes,compressed FROM results ORDER BY task"
        for task, iid, source_sha, size, data in self.source.db.execute(query):
            raw = self.source.validate_record(task, iid, source_sha, size, data)
            row = self.db.execute(
                """SELECT inequality_id,source_sha256,status,source_json_bytes,alternative_json_bytes,
                          alternative_sha256,compressed,report FROM attempts WHERE task=?""",
                (task,),
            ).fetchone()
            if row is None or row[0] != iid or row[1] != source_sha or row[3] != size:
                raise ValueError("synthesis disposition changed its source task/identity/hash/size")
            report = parse_json(row[7].encode())
            if (
                type(report.get("task")) is not int
                or report["task"] != task
                or report.get("inequality_id") != iid
                or report.get("source_recipe_sha256") != source_sha
                or report.get("source_json_bytes") != size
                or report.get("status") != row[2]
            ):
                raise ValueError("synthesis disposition report differs from its bound ledger row")
            origin, selected_sha = "verified-source", source_sha
            audit_root, audit_db = self.source.root, self.source.db
            if row[2] == RETAINED:
                candidate_size, selected_sha, compressed = row[4:7]
                if type(candidate_size) is not int or not 0 < candidate_size < size:
                    raise ValueError("retained alternative is not strictly smaller")
                raw = decode_frame(compressed, candidate_size)
                if (
                    len(raw) != candidate_size
                    or hashlib.sha256(raw).hexdigest() != selected_sha
                    or canonical_json(parse_json(raw)) != raw
                    or inequality_id(geometry_only(parse_json(raw))) != iid
                    or report.get("alternative_recipe_sha256") != selected_sha
                    or report.get("alternative_json_bytes") != candidate_size
                ):
                    raise ValueError("selected alternative changed its canonical identity/hash/size")
                changed = report.get("synthesis", {}).get("changed_cells")
                if type(changed) is not int or changed < 1:
                    raise ValueError("selected alternative is not a changed exact map")
                origin, audit_root, audit_db = "verified-alternative", self.root, self.db
            elif row[6] is not None:
                raise ValueError("non-retained disposition unexpectedly contains an active alternative payload")
            receipt_row = audit_db.execute("SELECT report FROM fresh WHERE task=? AND ok=1", (task,)).fetchone()
            if receipt_row is None:
                raise ValueError("selected definition lacks its successful source-free full-cube audit")
            receipt_raw = receipt_row[0].encode()
            receipt = parse_json(receipt_raw)
            check_audit(receipt, task, selected_sha, geometry_only(parse_json(raw)))
            if task not in done:
                yield SelectedDefinition(
                    task,
                    iid,
                    selected_sha,
                    raw,
                    origin,
                    str(audit_root),
                    hashlib.sha256(receipt_raw).hexdigest(),
                    receipt_raw,
                )

    def source_definition(self, task):
        """Audited baseline variant, including when an alternative was selected.

        Downstream formats must compare source/alternative costs in the SAME
        encoding instead of inheriting a size ranking from another language.
        """
        if type(task) is not int or not 0 <= task < self.expected:
            raise ValueError("source variant task is outside the complete manifest")
        row = self.source.db.execute(
            "SELECT inequality_id,recipe_sha256,json_bytes,compressed FROM results WHERE task=?", (task,)
        ).fetchone()
        if row is None:
            raise ValueError("source variant is missing from its verified ledger")
        iid, sha, size, data = row
        raw = self.source.validate_record(task, iid, sha, size, data)
        receipt_row = self.source.db.execute("SELECT report FROM fresh WHERE task=? AND ok=1", (task,)).fetchone()
        if receipt_row is None:
            raise ValueError("source variant lacks its own successful cube audit")
        receipt_raw = receipt_row[0].encode()
        check_audit(parse_json(receipt_raw), task, sha, geometry_only(parse_json(raw)))
        return SelectedDefinition(
            task,
            iid,
            sha,
            raw,
            "verified-source",
            str(self.source.root),
            hashlib.sha256(receipt_raw).hexdigest(),
            receipt_raw,
        )

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.lock is not None:
            self.lock.close()
            self.lock = None
        if self.source is not None:
            self.source.close()
            self.source = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
