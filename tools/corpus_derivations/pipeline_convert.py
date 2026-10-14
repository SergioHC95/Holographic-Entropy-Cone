"""Exact selected-recipe conversion with explicit inherited-audit provenance.

This pure per-record operation does not start a controller or mathematical
search. A full-corpus runner must obtain its inputs from VerifiedSelection,
enforce the approved worker/RSS limits, and checkpoint every manifest task.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from hec.count_proofs import canonical_json, inequality_id, parse_json, proof_geometry, proof_id
from hec.reconstruction import EXTENSION, PIPELINE

from .pipeline_import import import_recipe
from .selected_corpus import SelectedDefinition, check_audit
from .synthesize import geometry_only


@dataclass(frozen=True)
class ConvertedDefinition:
    task: int
    inequality_id: str
    raw: bytes
    recipe_sha256: str
    proof_id: str
    semantic_map_id: str
    receipt: bytes


def convert_definition(record: SelectedDefinition, *, closure_backend=None):
    """Check exact seed equivalence; do not invent a newly executed cube audit."""
    if type(record.task) is not int or record.task < 0:
        raise ValueError("selected task must be an exact nonnegative manifest index")
    if hashlib.sha256(record.raw).hexdigest() != record.recipe_sha256:
        raise ValueError("selected definition changed before pipeline conversion")
    if hashlib.sha256(record.audit_receipt).hexdigest() != record.audit_receipt_sha256:
        raise ValueError("selected mathematical audit receipt changed")
    source = parse_json(record.raw)
    source_geometry = geometry_only(source)
    if canonical_json(source) != record.raw or inequality_id(source_geometry) != record.inequality_id:
        raise ValueError("selected definition is noncanonical or has another inequality identity")
    audit = parse_json(record.audit_receipt)
    check_audit(audit, record.task, record.recipe_sha256, source_geometry)
    target, equivalence = import_recipe(source, closure_backend=closure_backend)
    raw = canonical_json(target)
    sha, target_id = hashlib.sha256(raw).hexdigest(), proof_id(target)
    if (
        target["function"]["kind"] != PIPELINE
        or target["function"]["extension"] != {"kind": EXTENSION}
        or inequality_id(proof_geometry(target)) != record.inequality_id
        or equivalence["source_definition_sha256"] != record.recipe_sha256
        or equivalence["target_proof_id"] != target_id
        or equivalence["new_exhaustive_original_cube_audit_executed"] is not False
    ):
        raise ValueError("pipeline equivalence receipt differs from the selected source/target")
    receipt = {
        "format": "hec-exact-pipeline-conversion/1",
        "task": record.task,
        "inequality_id": record.inequality_id,
        "source_recipe_sha256": record.recipe_sha256,
        "source_origin": record.origin,
        "target_recipe_sha256": sha,
        "target_proof_id": target_id,
        "semantic_map_id": equivalence["semantic_map_id"],
        "equivalence": equivalence,
        "scope": "exact-representation-conversion-with-identical-fixed-extension",
        "source_mathematical_audit": {
            "root": record.audit_root,
            "table": "fresh",
            "task": record.task,
            "receipt_sha256": record.audit_receipt_sha256,
            "scope": audit["full_cube_acceptance"]["scope"],
            "checked_vertices": audit["full_cube_acceptance"]["checked_vertices"],
            "checked_edges": audit["full_cube_acceptance"]["checked_edges"],
        },
        "new_exhaustive_original_cube_audit_executed": False,
        "source_tables_read": False,
        "source_json_bytes": len(record.raw),
        "target_json_bytes": len(raw),
        "size_comparison": "Canonical definition bytes, not compression; wrapper overhead may increase size.",
    }
    return ConvertedDefinition(
        record.task,
        record.inequality_id,
        raw,
        sha,
        target_id,
        equivalence["semantic_map_id"],
        canonical_json(receipt),
    )
