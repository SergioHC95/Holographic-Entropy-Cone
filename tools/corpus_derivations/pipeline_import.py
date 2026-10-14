"""Offline, exact-value conversion to one reconstruction pipeline.

Historical research formats are accepted HERE ONLY, not by the pipeline
reader. This does not change a running cohort, promote a proof into production,
or turn source audit receipts into newly executed mathematical checks.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from derivation_pilot import recipes

from hec.count_proofs import FORMAT, TRANSPORT, canonical_json, compatible_vertices
from hec.reconstruction import CLOSURE, CUTS, DAG, EXTENSION, TABLE, compile_pipeline

from . import diagrams
from .native import Auditor


def bound_binary(binary, expected_sha256):
    binary = Path(binary)
    if binary.is_symlink() or not binary.is_file():
        raise ValueError("missing or unsafe exact primitive binary")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError("explicit frozen primitive binary SHA256 required")
    actual = hashlib.sha256(binary.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise ValueError("exact primitive binary changed")
    return binary, actual


class NativeClosure:
    """Caller-selected, hash-bound exact primitive; no artifact-selected binary."""

    primitive = CLOSURE

    def __init__(self, binary, expected_sha256):
        self.binary, self.sha256 = bound_binary(binary, expected_sha256)

    def decode(self, p, seed):
        bound_binary(self.binary, self.sha256)
        return recipes.closure_call(
            self.binary,
            p,
            mode="decode",
            anchors=seed["anchors"],
            enumeration=seed["enumeration"],
            pairs=seed["pairs"],
            choice_count=seed["choice_count"],
            default=seed["policy"],
            exceptions=seed["exceptions"],
        ).rows


class NativePipelineAuditor(Auditor):
    """Same independent exact wide auditor, shared by ALL seed program kinds."""

    extension = EXTENSION

    def __init__(self, binary, expected_sha256):
        binary, self.sha256 = bound_binary(binary, expected_sha256)
        super().__init__(binary)

    def verify(self, p, vertices, scale, rows):
        bound_binary(self.binary, self.sha256)
        return super().verify(p, vertices, scale, rows)


def canonical_dag(function):
    """Relabel the existing scalar DAG bottom-up; no mathematical values change."""
    terminals, nodes = function["terminals"], function["nodes"]
    remap, result = {i: i for i in range(len(terminals))}, []
    for axis in sorted({node[0] for node in nodes}):
        level = sorted(
            (axis, remap[low], remap[high], len(terminals) + index)
            for index, (at, low, high) in enumerate(nodes)
            if at == axis
        )
        for at, low, high, old in level:
            remap[old] = len(terminals) + len(result)
            result.append([at, low, high])
    return {
        "kind": DAG,
        "scale": function["seed_scale"],
        "terminals": terminals,
        "nodes": result,
        "roots": [remap[ref] for ref in function["roots"]],
    }


def import_recipe(document, *, closure_backend=None):
    """Return a pipeline and an explicit exact-extension equivalence receipt.

    Both decoders actually reconstruct every compatible count. This is an
    equivalence check, NOT another executed exhaustive original-cube audit.
    The source must separately have mathematical acceptance. Order-projection
    kernels are rejected: replacing their extension would change the full map.
    """
    source_raw = canonical_json(document)
    if document.get("format") == FORMAT:
        if document.get("function", {}).get("kind") != TRANSPORT:
            raise ValueError("offline exact conversion requires the same cancel/fill extension")
        p, vertices, scale, rows = diagrams.common_seed(document)
        seed = {"kind": TABLE, "rows": document["function"]["rows"]}
    elif document.get("format") == diagrams.FORMAT:
        p, vertices, scale, rows = diagrams.reconstruct(document)
        seed = canonical_dag(document["function"])
    elif document.get("format") == recipes.FORMAT:
        p = recipes.recipe_geometry(document)
        function = document["function"]
        vertices, scale = list(compatible_vertices(p)), 1
        if function.get("kind") == recipes.CUTS:
            original = recipes.CutFunction(document)
            rows = [original[vertex] for vertex in vertices]
            seed = {
                "kind": CUTS,
                "terms": [[str(one), str(zero)] for one, zero in function["terms"]],
                "groups": function["groups"],
            }
        elif function.get("kind") == recipes.CLOSURE:
            expected = {"kind", "anchors", "enumeration", "pairs", "policy", "choice_count", "exceptions"}
            if set(function) != expected or function["policy"] not in ("lower", "upper"):
                raise ValueError("offline conversion requires an explicit bounded sparse-choice program")
            if closure_backend is None:
                raise ValueError("exact closure backend required for offline equivalence check")
            original = recipes.decode_closure(document, closure_backend.binary)
            rows = original.rows
            seed = dict(function, kind=CLOSURE)
        else:
            raise ValueError("unsupported offline research seed")
    else:
        raise ValueError("unsupported offline source format")
    program = compile_pipeline(p, seed, closure_backend=closure_backend)
    target = program.document
    decoded = program.materialize_seed()
    if (tuple(vertices), scale, tuple(map(tuple, rows))) != (decoded.vertices, decoded.scale, decoded.numerators):
        raise ValueError("pipeline conversion changed an exact compatible value")
    return target, {
        "source_definition_sha256": hashlib.sha256(source_raw).hexdigest(),
        "target_proof_id": program.identity,
        "semantic_map_id": program.semantic_identity(),
        "checked_compatible_vertices": len(vertices),
        "scope": "complete-compatible-value-equivalence-and-identical-fixed-extension",
        "new_exhaustive_original_cube_audit_executed": False,
        "source_mathematical_acceptance_still_required": True,
        "source_tables_read": False,
    }
