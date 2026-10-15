"""Install an accepted corpus locally, preserving old files; NO LFS writes.

The Git index is not touched. Large new payloads remain in immutable external
staging and get ordinary pointer files; a publication-assets manifest records
what must be imported/uploaded only after separate LFS authorization.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from hec.count_proofs import canonical_json, parse_json

from . import run as d
from .repository_acceptance import bound, equal
from .synthesize import EXPECTED_TOTAL

HASH = re.compile(r"[0-9a-f]{64}\Z")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def pointer(sha, size):
    if HASH.fullmatch(sha) is None or type(size) is not int or size < 1:
        raise ValueError("invalid immutable publication asset")
    return f"version https://git-lfs.github.com/spec/v1\noid sha256:{sha}\nsize {size}\n".encode()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".accepted-cutover-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def cutover(repo, review_path, review_sha, archive, *, _expected_total=EXPECTED_TOTAL):
    repo, review_path, archive = (Path(x).resolve() for x in (repo, review_path, archive))
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise ValueError("explicit Git worktree root required")
    if archive.is_relative_to(repo) or repo.is_relative_to(archive) or archive.exists():
        raise ValueError("choose a new outside-repository recoverable archive")
    bound(review_path, review_sha)
    review = parse_json(review_path.read_bytes())
    equal(review.get("format"), "hec-full-corpus-acceptance-review/1", "acceptance version")
    equal(review.get("proofs"), _expected_total, "full accepted corpus")
    equal(review.get("checked_stored_frames"), _expected_total, "all accepted stored frames")
    equal(review.get("mathematical_promotion_precondition_passed"), True, "actual complete math precondition")
    audit, stage = Path(review["audit"]), Path(review["stage"])
    if any(archive.is_relative_to(p) or p.is_relative_to(archive) for p in (audit, stage)):
        raise ValueError("archive must not overwrite immutable audit/stage inputs")
    bound(audit / "report.json", review["audit_report_sha256"])
    bound(audit / "run-binding.json", review["audit_binding_sha256"])
    bound(stage / "stage-report.json", review["staging_binding_sha256"])
    binding = parse_json((audit / "run-binding.json").read_bytes())
    staged = parse_json((stage / "stage-report.json").read_bytes())
    equal(binding["total"], _expected_total, "accepted binding total")
    equal(str(stage), binding["stage"], "accepted stage location")
    actual_ns = {int(p.name[2:]) for p in (repo / "data").glob("n=*") if p.name[2:].isdigit()}
    if actual_ns != {int(n) for n in binding["catalogs"]}:
        raise ValueError("cutover cannot drop or add an undeclared party dataset")
    writes, assets, payload_bytes = {}, [], 0
    for n, info in binding["catalogs"].items():
        directory = stage / "data" / f"n={int(n)}"
        for name, sha in (("proofs.json", info["sha256"]), ("inequalities.json", info["inequalities_sha256"])):
            bound(directory / name, sha)
            writes[f"data/n={int(n)}/{name}"] = (directory / name).read_bytes()
        for sha, meta in info["shards"].items():
            path = directory / "proof-shards" / f"{sha}.proofpack"
            bound(path, sha)
            equal(path.stat().st_size, meta["bytes"], "audited payload size")
            relative = f"data/n={int(n)}/proof-shards/{sha}.proofpack"
            payload_bytes += meta["bytes"]
            if int(n) == 6:
                writes[relative] = pointer(sha, meta["bytes"])
                assets.append({"path": relative, "sha256": sha, "bytes": meta["bytes"], "source": str(path)})
            else:
                writes[relative] = path.read_bytes()
    equal(payload_bytes, staged["exact_compressed_frame_bytes_preserved"], "all frame bytes preserved")
    archive_relative = "archives/contractions/standard-20261015"
    if (repo / archive_relative).exists():
        raise ValueError("never replace an earlier cutover/archive record")
    provenance_sha = staged["provenance_sha256"]
    provenance = stage / "conversion-provenance" / f"{provenance_sha}.conversion-provenance.jsonl.zst"
    bound(provenance, provenance_sha)
    relative = f"{archive_relative}/{provenance.name}"
    writes[relative] = pointer(provenance_sha, provenance.stat().st_size)
    assets.append(
        {"path": relative, "sha256": provenance_sha, "bytes": provenance.stat().st_size, "source": str(provenance)}
    )
    old_paths = []
    for n in sorted(actual_ns):
        directory = repo / "data" / f"n={n}"
        old_paths.extend([directory / "proofs.json", directory / "inequalities.json"])
        old_paths.extend(sorted((directory / "proof-shards").glob("*.proofpack")))
    tracked = set(git(repo, "ls-files").splitlines())
    old_relatives = [p.relative_to(repo).as_posix() for p in old_paths]
    if any(p not in tracked for p in old_relatives):
        raise ValueError("untracked user files in old artifact targets; preserve and resolve before cutover")
    if git(repo, "diff", "--name-only", "HEAD", "--", *old_relatives):
        raise ValueError("old artifact targets have user changes; never overwrite them")
    for relative in writes:
        if (repo / relative).exists() and relative not in old_relatives:
            raise ValueError("new artifact path already exists outside the validated replacement set")
    originals, copies, media = [], {}, None
    for path in old_paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("old artifact target is missing or unsafe")
        relative = path.relative_to(repo).as_posix()
        data = path.read_bytes()
        entry = {"path": relative, "sha256": d.digest(path), "bytes": len(data)}
        copies[relative] = (path, entry["sha256"])
        if data.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
            lines = data.decode().splitlines()
            if len(lines) != 3 or not lines[1].startswith("oid sha256:") or not lines[2].startswith("size "):
                raise ValueError("old pointer is not a complete immutable LFS reference")
            sha, size = lines[1][11:], int(lines[2][5:])
            if pointer(sha, size) != data:
                raise ValueError("old pointer is noncanonical")
            if media is None:
                locations = [
                    line.split("=", 1)[1]
                    for line in git(repo, "lfs", "env").splitlines()
                    if line.startswith("LocalMediaDir=")
                ]
                if len(locations) != 1:
                    raise ValueError("cannot locate existing local payloads read-only")
                media = Path(locations[0])
            payload = media / sha[:2] / sha[2:4] / sha
            bound(payload, sha)
            equal(payload.stat().st_size, size, "recoverable old payload size")
            archived_payload = f"lfs-payloads/{sha}"
            copies[archived_payload] = (payload, sha)
            entry.update(payload_sha256=sha, payload_bytes=size, archived_payload=archived_payload)
        originals.append(entry)
    # EVERY original and referenced payload is copied/checked before ANY
    # active worktree artifact is removed or replaced. LFS store is read-only.
    archive.mkdir(parents=True, exist_ok=False)
    for relative, (source, sha) in copies.items():
        target = archive / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        bound(target, sha)
    old_index = {
        "format": "hec-original-artifact-archive/1",
        "original_git_head": git(repo, "rev-parse", "HEAD"),
        "entries": originals,
        "payloads_retained_locally": True,
        "lfs_store_or_history_deleted": False,
    }
    d.save_new(archive / "originals-index.json", old_index)
    writes[f"{archive_relative}/originals-index.json"] = canonical_json(old_index) + b"\n"
    writes[f"{archive_relative}/staged-full-cube-audit.json"] = (audit / "report.json").read_bytes()
    writes[f"{archive_relative}/acceptance-review.json"] = review_path.read_bytes()
    corpus = {
        "format": "hec-contraction-corpus/1",
        "proofs": _expected_total,
        "scope_counts": review["scope_counts"],
        "proof_catalog": "hec-proof-catalog/1",
        "definition_profile": "compatible-reconstruction-pipeline/1",
        "extension": "cancel-fill-common-threshold/1",
        "one_selected_proof_per_inequality": True,
        "facet_or_rank_claims_inherited": False,
        "compressed_frame_bytes": payload_bytes,
        "audit_report": f"{archive_relative}/staged-full-cube-audit.json",
        "audit_report_sha256": review["audit_report_sha256"],
        "acceptance_review_sha256": review_sha,
        "conversion_provenance": f"{archive_relative}/{provenance.name}",
        "conversion_provenance_sha256": provenance_sha,
    }
    writes["data/contraction-corpus.json"] = canonical_json(corpus) + b"\n"
    for entry in originals:
        bound(repo / entry["path"], entry["sha256"])
    for path in old_paths:
        # Retire exact validated active paths recoverably, rather than delete
        # even their final working-tree bytes. LFS objects/history stay intact.
        retired = archive / "retired-working-tree" / path.relative_to(repo)
        retired.parent.mkdir(parents=True, exist_ok=True)
        path.rename(retired)
    for relative, data in writes.items():
        atomic(repo / relative, data)
    publication = {
        "format": "hec-local-publication-assets/1",
        "repo": str(repo),
        "original_archive": str(archive),
        "assets": assets,
        "git_lfs_or_billing_mutated": False,
        "published": False,
        "required_after_explicit_lfs_authorization": (
            "Import these exact verified payloads into Git LFS, then upload; no payload is invented from a pointer."
        ),
    }
    d.save_new(archive.parent / "publication-assets.json", publication)
    return {
        "format": "hec-local-cutover-result/1",
        "proofs": _expected_total,
        "replaced_old_active_paths": len(old_paths),
        "recoverable_original_archive": str(archive),
        "new_lfs_pointer_files": len(assets),
        "ordinary_git_small_payloads": sum(
            len(info["shards"]) for n, info in binding["catalogs"].items() if int(n) != 6
        ),
        "frame_bytes_preserved": payload_bytes,
        "git_index_changed": False,
        "git_lfs_or_billing_mutated": False,
        "new_math_audits_executed": 0,
        "full_goal_complete": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("repo", "review", "archive"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--review-sha256", required=True)
    args = parser.parse_args()
    print(canonical_json(cutover(args.repo, args.review, args.review_sha256, args.archive)).decode())


if __name__ == "__main__":
    main()
