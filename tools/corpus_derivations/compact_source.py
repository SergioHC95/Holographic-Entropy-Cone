"""Construction-only reuse of an input seed with executed-equivalence provenance.

Not an acceptance cache and never called by fresh verification. The first
derivation pass actually compared every compatible value; this locator binds
both sides of that executed comparison to unchanged proof/catalogue bytes.
The fixed production extension, smoothing checks and independent winner/fresh
audits remain mandatory. Primitive Boolean archives are never opened here.
"""

from __future__ import annotations

import atexit
import hashlib
import sqlite3
from pathlib import Path

from derivation_pilot import recipes

from hec._archive_proof_store import ArchiveProofCatalog as ProofCatalog
from hec.count_proofs import canonical_json, inequality_id, parse_json

from . import run as derivations
from .diagrams import common_seed
from .selected_corpus import check_audit
from .synthesize import geometry_only

POLICY = "bound-compact-construction-seed-reuse/1"
_READER = None
_KEY = None


class Reader:
    def __init__(self, settings):
        config = settings["source_seed_input"]
        if set(config) != {"policy", "source_binding_sha256", "source_manifest_sha256"} or config["policy"] != POLICY:
            raise ValueError("unsupported construction-seed input policy")
        self.root = Path(settings["source"]).resolve()
        if derivations.digest(self.root / "run-binding.json") != config["source_binding_sha256"]:
            raise ValueError("construction input source binding changed")
        self.binding = parse_json((self.root / "run-binding.json").read_bytes())
        manifest = (self.root / "manifest.json").read_bytes()
        if (
            hashlib.sha256(manifest).hexdigest() != config["source_manifest_sha256"]
            or self.binding["manifest_sha256"] != config["source_manifest_sha256"]
            or self.binding["total"] != settings["source_total"]
        ):
            raise ValueError("construction input manifest/scope changed")
        entries = parse_json(manifest)
        if [entry["task"] for entry in entries] != list(range(settings["source_total"])):
            raise ValueError("construction input manifest is not the complete ordered scope")
        # Keep only compact-input locators, never Boolean archive locations.
        self.entries = {
            entry["task"]: (entry["catalog"], entry["index"], entry["source_proof_id"], entry["inequality_id"])
            for entry in entries
            if entry["group"] != "primitive" and "catalog" in entry
        }
        self.config, self.catalogs, self.fingerprints = dict(config), {}, {}
        self.db = sqlite3.connect(f"file:{self.root / 'checkpoint.sqlite3'}?mode=ro", uri=True)
        self.db.execute("BEGIN")

    def close(self):
        self.db.close()

    def decode(self, item, document):
        task, raw, sha, iid = item
        if document.get("format") != recipes.FORMAT or document.get("function", {}).get("kind") != recipes.CLOSURE:
            return None
        if task not in self.entries:  # In particular, no primitive/archive fallback.
            return None
        if hashlib.sha256(raw).hexdigest() != sha or canonical_json(document) != raw:
            raise ValueError("saved construction source changed")
        key, index, input_id, manifest_iid = self.entries[task]
        if iid != manifest_iid:
            raise ValueError("construction input changed its exact inequality frame")
        row = self.db.execute("SELECT recipe_sha256,inequality_id,report FROM results WHERE task=?", (task,)).fetchone()
        if row is None or row[:2] != (sha, iid):
            raise ValueError("construction input is not the bound saved-source recipe")
        report_raw = row[2].encode()
        report = parse_json(report_raw)
        winner = report.get("winner")
        method = report.get("methods", {}).get(winner, {})
        if (
            type(report.get("task")) is not int
            or report["task"] != task
            or report.get("inequality_id") != iid
            or report.get("source_proof_id") != input_id
            or report.get("winner_json_bytes") != len(raw)
            or winner != "choice-closure"
            or report.get("seed_scale") != "1"
            or method.get("recipe_sha256") != sha
            or method.get("status") != "exact_equivalence_to_full_cube_verified_map"
            or report.get("mathematical_transform")
            != "preserve complete compatible counts; fixed cancel/fill full-cube extension"
        ):
            raise ValueError("missing/mismatched executed first-pass compatible-value equivalence provenance")
        p = geometry_only(document)
        saved_audit = self.db.execute("SELECT report FROM fresh WHERE task=? AND ok=1", (task,)).fetchone()
        if saved_audit is None:
            raise ValueError("construction source lacks its own source-free cube audit")
        check_audit(parse_json(saved_audit[0].encode()), task, sha, p)
        expected = self.binding["source_catalogs"][key]["sha256"]
        path = Path(key)
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None  # Optional input unavailable; saved standalone recipe remains authoritative.
        fingerprint = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if self.fingerprints.get(key) != fingerprint:
            if derivations.digest(path) != expected:
                raise ValueError("original compact input catalogue changed")
            self.fingerprints[key] = fingerprint
        if key not in self.catalogs:
            self.catalogs[key] = ProofCatalog(path)
        catalog = self.catalogs[key]
        if type(index) is not int or not 0 <= index < len(catalog) or catalog.entries[index]["proof_id"] != input_id:
            raise ValueError("original compact input proof/index identity changed")
        shard = path.parent / "proof-shards" / f"{catalog.entries[index]['shard']}.proofpack"
        if not shard.exists():
            return None
        original = catalog[index]  # Checks immutable shard and actual canonical proof identity.
        if "rows" not in original["function"]:
            return None  # No speculative DAG shortcut; use the saved recipe normally.
        decoded = common_seed(original)
        rp, vertices, scale, rows = decoded
        if (
            rp != p
            or inequality_id(rp) != iid
            or scale != 1
            or type(report.get("compatible_vertices")) is not int
            or report["compatible_vertices"] != len(vertices)
            or type(report.get("L")) is not int
            or report["L"] != p.L
            or type(report.get("G")) is not int
            or report["G"] != p.G
        ):
            raise ValueError("original compatible seed disagrees with the executed source-equivalence geometry")
        return decoded, {
            "policy": POLICY,
            "scope": "reuse-of-executed-complete-compatible-seed-equivalence",
            "source_run_binding_sha256": self.config["source_binding_sha256"],
            "source_recipe_sha256": sha,
            "input_catalog_sha256": expected,
            "input_proof_id": input_id,
            "executed_first_pass_report_sha256": hashlib.sha256(report_raw).hexdigest(),
            "source_free_audit_sha256": hashlib.sha256(saved_audit[0].encode()).hexdigest(),
            "original_boolean_archives_read": False,
            "mathematical_acceptance_cached": False,
        }


def decode(item, document, settings):
    global _READER, _KEY
    if document.get("format") != recipes.FORMAT or document.get("function", {}).get("kind") != recipes.CLOSURE:
        return None
    key = (settings["source"], canonical_json(settings["source_seed_input"]))
    if key != _KEY:
        if _READER is not None:
            _READER.close()
        _READER, _KEY = Reader(settings), key
        atexit.register(_READER.close)
    return _READER.decode(item, document)
