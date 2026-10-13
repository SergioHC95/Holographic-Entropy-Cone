"""Ordinary-Git inequality identities and exact bindings to proof objects.

These records make no inherited facethood or rank claims. A verified count
proof is evidence for inequality validity, not for being a facet.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from .count_proofs import canonical_json, decimal, geometry, inequality_id, parse_json, proof_geometry, proof_id
from .proof_store import ProofCatalog

FORMAT = "hec-inequality-catalog/1"
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def inequality_catalog(proofs: Iterable[dict]) -> dict:
    entries = {}
    for proof in proofs:
        problem = proof_geometry(proof)
        key = inequality_id(problem)
        entry = entries.setdefault(key, {"id": key, **problem.inequality(), "proof_ids": []})
        identity = proof_id(proof)
        if identity in entry["proof_ids"]:
            raise ValueError("duplicate proof identity in inequality catalogue")
        entry["proof_ids"].append(identity)
    for entry in entries.values():
        entry["proof_ids"].sort()
    return {"format": FORMAT, "entries": [entries[key] for key in sorted(entries)]}


class InequalityCatalog:
    def __init__(self, path: str | Path):
        catalog = parse_json(Path(path).read_bytes())
        if not isinstance(catalog, dict) or set(catalog) != {"format", "entries"} or catalog["format"] != FORMAT:
            raise ValueError("unsupported inequality catalogue")
        if not isinstance(catalog["entries"], list):
            raise ValueError("inequality entries must be a list")
        self.entries = {}
        last = ""
        for entry in catalog["entries"]:
            if not isinstance(entry, dict) or set(entry) != {"id", "n", "coefficients", "proof_ids"}:
                raise ValueError("invalid inequality record")
            if not isinstance(entry["coefficients"], list):
                raise ValueError("inequality coefficients must be a list")
            problem = geometry(entry["n"], tuple(decimal(value) for value in entry["coefficients"]))
            identity = inequality_id(problem)
            if entry["id"] != identity or identity <= last:
                raise ValueError("inequality identity/order differs or is duplicated")
            references = entry["proof_ids"]
            if not isinstance(references, list) or not references:
                raise ValueError("accepted inequality must reference at least one proof")
            if any(not isinstance(value, str) or _HASH.fullmatch(value) is None for value in references):
                raise ValueError("invalid referenced proof identity")
            if references != sorted(set(references)):
                raise ValueError("proof references must be sorted and unique")
            self.entries[identity] = entry
            last = identity

    def check_bindings(self, proofs: ProofCatalog) -> dict:
        expected = {identity: entry["id"] for entry in self.entries.values() for identity in entry["proof_ids"]}
        reference_count = sum(len(entry["proof_ids"]) for entry in self.entries.values())
        if len(expected) != reference_count:
            raise ValueError("one proof cannot be assigned to different inequalities")
        actual = {entry["proof_id"]: entry["inequality_id"] for entry in proofs.entries}
        if expected != actual:
            raise ValueError("inequality records and proof catalogue are not exactly aligned")
        return {"ok": True, "inequalities": len(self.entries), "proofs": len(actual)}


def write_inequality_catalog(path: str | Path, catalog: dict) -> None:
    # This is generated data, not a source edit. Refuse to replace any original.
    with Path(path).open("xb") as output:
        output.write(canonical_json(catalog) + b"\n")
