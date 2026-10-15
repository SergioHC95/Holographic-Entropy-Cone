"""Manifest-driven storage for standard proofs and their declared provenance.

Only the producer may fetch LFS. Consumers fail closed on a missing/corrupt
cache: they never retry an unrestricted download in every matrix job.
Historical revisions and undeclared archive payloads are never fetched.
This is a transfer optimization, not a replacement for mathematical checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .count_proofs import canonical_json, parse_json

CACHE_DIRECTORY = Path(".hec-ci-lfs/objects")
MAX_CACHE_BYTES = 2 * 1024**3
OID_RE = re.compile(r"[0-9a-f]{64}")
INVENTORY = "data/storage.json"
INVENTORY_FORMAT = "hec-repository-storage/1"


def safe_path(root: Path, relative: str) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or ":" in relative
        or Path(relative).is_absolute()
        or any(part in ("", ".", "..") for part in relative.split("/"))
    ):
        raise ValueError("unsafe repository storage path")
    target = root / relative
    if any(path.is_symlink() for path in (target, *target.parents) if path != root.parent):
        raise ValueError("repository storage paths cannot traverse symlinks")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("storage path escapes the repository")
    return target


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_file(path: Path, item: dict[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"verified LFS object missing or not a regular file: {path}")
    if path.stat().st_size != item["size"] or file_hash(path) != item["oid"]:
        raise ValueError(f"LFS object length/SHA256 mismatch: {path}")


def payload_entry(root: Path, path: Path, manifest: dict[str, Any], n: int) -> dict[str, Any] | None:
    relative = path.relative_to(root).as_posix()
    safe_path(root, relative)
    if git(root, "check-attr", "filter", "--", relative).rsplit(": ", 1)[-1] != "lfs":
        return None  # Ordinary Git payloads already arrive with the checkout.
    blob = f"HEAD:{relative}"
    if int(git(root, "cat-file", "-s", blob)) > 1024:
        raise ValueError(f"expected a committed LFS pointer, not a large Git blob: {relative}")
    pointer = git(root, "show", blob).splitlines()
    if len(pointer) != 3 or pointer[0] != "version https://git-lfs.github.com/spec/v1":
        raise ValueError(f"invalid LFS pointer: {relative}")
    if not pointer[1].startswith("oid sha256:") or not pointer[2].startswith("size "):
        raise ValueError(f"unsupported LFS pointer: {relative}")
    oid, size = pointer[1][11:], int(pointer[2][5:])
    if OID_RE.fullmatch(oid) is None or size < 0:
        raise ValueError(f"invalid LFS object identity: {relative}")
    if type(manifest.get("compressed_size")) is not int:
        raise ValueError(f"proof manifest compressed size must be an integer: {relative}")
    if oid != manifest.get("compressed_sha256") or size != manifest.get("compressed_size"):
        raise ValueError(f"committed LFS pointer differs from the proof manifest: {relative}")
    return {"n": n, "path": relative, "oid": oid, "size": size}


def make_plan(root: Path) -> dict[str, Any]:
    from .proof_store import ProofCatalog

    root = root.resolve()
    assets = []
    for source in sorted((root / "data").glob("n=*/proofs.json")):
        if not source.parent.name[2:].isdigit():
            continue
        n = int(source.parent.name[2:])
        safe_path(root, source.relative_to(root).as_posix())
        catalog = ProofCatalog(source)
        expected = {source.parent / "proof-shards" / f"{key}.proofpack" for key in catalog.shards}
        if set((source.parent / "proof-shards").glob("*.proofpack")) != expected:
            raise ValueError("missing or unindexed active proof payload")
        for key, shard in sorted(catalog.shards.items()):
            item = {"compressed_sha256": key, "compressed_size": shard["bytes"]}
            path = source.parent / "proof-shards" / f"{key}.proofpack"
            entry = payload_entry(root, path, item, n)
            if entry is not None:
                assets.append(entry)
            else:
                if n == 6 or shard["bytes"] > 1024**2:
                    raise ValueError("large active proof payloads must use LFS")
                verify_file(path, {"oid": key, "size": shard["bytes"]})
    corpus = root / "data/contraction-corpus.json"
    if corpus.exists():
        descriptor = parse_json(corpus.read_bytes())
        relative, oid = descriptor["conversion_provenance"], descriptor["conversion_provenance_sha256"]
        if (
            not isinstance(relative, str)
            or re.fullmatch(
                r"archives/contractions/[A-Za-z0-9_-]+/[0-9a-f]{64}\.conversion-provenance\.jsonl\.zst", relative
            )
            is None
            or Path(relative).name != f"{oid}.conversion-provenance.jsonl.zst"
        ):
            raise ValueError("invalid declared provenance location")
        path = safe_path(root, relative)
        blob = f"HEAD:{relative}"
        if int(git(root, "cat-file", "-s", blob)) > 1024:
            raise ValueError("large declared provenance must be a committed LFS pointer")
        pointer = git(root, "show", blob).splitlines()
        if len(pointer) != 3 or not pointer[2].startswith("size "):
            raise ValueError("invalid declared provenance pointer")
        entry = payload_entry(root, path, {"compressed_sha256": oid, "compressed_size": int(pointer[2][5:])}, None)
        if entry is None:
            raise ValueError("declared large provenance must use LFS")
        assets.append(entry)
    for directory in (root / "data").glob("n=*"):
        if directory.name[2:].isdigit() and not (directory / "proofs.json").is_file():
            raise ValueError(f"dataset has no standardized proof catalog: {directory}")
    objects = {}
    for entry in assets:
        item = {"oid": entry["oid"], "size": entry["size"]}
        if entry["oid"] in objects and objects[entry["oid"]] != item:
            raise ValueError("one LFS SHA256 has conflicting declared byte lengths")
        objects[entry["oid"]] = item
    ordered = [objects[key] for key in sorted(objects)]
    size = sum(entry["size"] for entry in ordered)
    if size > MAX_CACHE_BYTES:
        raise ValueError("active proof cache exceeds the 2 GiB safety cap; shard the data before extending CI")
    fingerprint = hashlib.sha256(json.dumps(ordered, sort_keys=True).encode()).hexdigest()
    return {
        "schema_version": 1,
        "assets": assets,
        "objects": ordered,
        "bytes": size,
        "cache_key": f"hec-storage-v1-{fingerprint}",
        "required_ns": sorted({entry["n"] for entry in assets if entry["n"] is not None}),
    }


def inventory_document(root: Path) -> dict:
    """Bind all active data bytes plus declared lineage, never arbitrary archives.

    Proof bytes are bound by strict catalogues and committed LFS pointers.
    This inventory checks storage integrity, not mathematical validity.
    """
    root = root.resolve()
    plan = make_plan(root)
    lfs = {entry["path"]: entry for entry in plan["assets"]}
    paths = set(git(root, "ls-files", "--cached", "--others", "--exclude-standard", "--", "data").splitlines())
    paths.discard(INVENTORY)
    corpus = root / "data/contraction-corpus.json"
    if corpus.exists():
        descriptor = parse_json(corpus.read_bytes())
        paths.update((descriptor["conversion_provenance"], descriptor["audit_report"]))
        review = str(Path(descriptor["audit_report"]).with_name("acceptance-review.json"))
        paths.add(review)
        for relative, expected in (
            (descriptor["audit_report"], descriptor["audit_report_sha256"]),
            (review, descriptor["acceptance_review_sha256"]),
        ):
            if file_hash(safe_path(root, relative)) != expected:
                raise ValueError("declared mathematical provenance reference differs from its hash")
    entries = []
    for relative in sorted(paths):
        path = safe_path(root, relative)
        if not path.exists():
            continue  # A deliberately removed tracked path is absent from this snapshot.
        if not path.is_file():
            raise ValueError("storage inventory requires regular files")
        if relative in lfs:
            item = lfs[relative]
            # Accept a pointer or the exact hydrated bytes, never corrupt live data.
            if path.stat().st_size <= 1024 and path.read_bytes().startswith(
                b"version https://git-lfs.github.com/spec/v1\n"
            ):
                expected = (
                    f"version https://git-lfs.github.com/spec/v1\noid sha256:{item['oid']}\nsize {item['size']}\n"
                )
                if path.read_bytes() != expected.encode():
                    raise ValueError("working-tree pointer differs from the declared LFS object")
            else:
                verify_file(path, item)
            entry = {"path": relative, "sha256": item["oid"], "bytes": item["size"], "storage": "lfs"}
        else:
            entry = {"path": relative, "sha256": file_hash(path), "bytes": path.stat().st_size, "storage": "git"}
        entries.append(entry)
    if not entries:
        raise ValueError("empty storage inventory is not repository integrity")
    return {"format": INVENTORY_FORMAT, "entries": entries}


def snapshot(root: Path, *, replace: bool = False) -> dict:
    root = root.resolve()
    document = inventory_document(root)
    target = safe_path(root, INVENTORY)
    if target.exists() and not replace:
        raise ValueError("storage inventory already exists; explicit --replace is required")
    fd, name = tempfile.mkstemp(prefix=".storage-inventory-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(canonical_json(document) + b"\n")
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(name, target)
        else:
            os.link(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    return {"format": INVENTORY_FORMAT, "files": len(document["entries"]), "mathematical_acceptance": False}


def audit_inventory(root: Path, *, payloads: bool = False) -> dict:
    root = root.resolve()
    stored = parse_json(safe_path(root, INVENTORY).read_bytes())
    if canonical_json(stored) != canonical_json(inventory_document(root)):
        raise ValueError("storage inventory differs from actual data paths, hashes, pointers or sizes")
    if payloads:
        for entry in stored["entries"]:
            if entry["storage"] == "lfs":
                verify_file(safe_path(root, entry["path"]), {"oid": entry["sha256"], "size": entry["bytes"]})
    return {"files": len(stored["entries"]), "LFS_payload_bytes_verified": payloads, "mathematical_acceptance": False}


def cache_path(root: Path, oid: str) -> Path:
    root = root.resolve()
    if OID_RE.fullmatch(oid) is None:
        raise ValueError("invalid cache object SHA256")
    directory = root / CACHE_DIRECTORY
    if (root / CACHE_DIRECTORY.parts[0]).is_symlink() or directory.is_symlink():
        raise ValueError("CI cache directory must not be a symlink")
    return directory / oid


def copy_verified(source: Path, target: Path, item: dict[str, Any]) -> None:
    verify_file(source, item)
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError(f"refusing symlink destination: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    # The temporary file belongs solely to this copy operation. Never prune
    # proof data, Git history, or another job's scratch/cache files here.
    fd, name = tempfile.mkstemp(prefix=".verified-copy-", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        verify_file(temporary, item)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def populate(
    root: Path, plan: dict[str, Any], *, offline: bool = False, source_root: Path | None = None
) -> dict[str, int]:
    root = root.resolve()
    media = None
    needed = []
    for item in plan["objects"]:
        cached = cache_path(root, item["oid"])
        if cached.exists() or cached.is_symlink():
            verify_file(cached, item)
        else:
            needed.append(item)
    if source_root is not None:
        source_root = source_root.resolve()
        for item in needed:
            relative = next(entry["path"] for entry in plan["assets"] if entry["oid"] == item["oid"])
            copy_verified(safe_path(source_root, relative), cache_path(root, item["oid"]), item)
        verify_cache(root, plan)
        return {"objects": len(plan["objects"]), "requested_LFS_bytes": 0}
    if needed:
        # Worktrees may share their common Git LFS store; honor lfs.storage.
        environment = git(root, "lfs", "env")
        locations = [
            line.removeprefix("LocalMediaDir=")
            for line in environment.splitlines()
            if line.startswith("LocalMediaDir=")
        ]
        if len(locations) != 1:
            raise ValueError("could not locate the repository's existing LFS object store")
        media = Path(locations[0])
    missing = []
    for item in needed:
        oid = item["oid"]
        source = media / oid[:2] / oid[2:4] / oid
        if source.is_file():
            copy_verified(source, cache_path(root, oid), item)
        else:
            missing.append(item)
    if missing:
        if offline:
            raise ValueError("active LFS objects are missing locally; offline mode forbids a download")
        identifiers = {item["oid"] for item in missing}
        paths = [entry["path"] for entry in plan["assets"] if entry["oid"] in identifiers]
        # One producer, one explicitly filtered fetch of HEAD, no recent refs.
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "lfs.fetchrecentalways=false",
                "lfs",
                "fetch",
                "--include=" + ",".join(paths),
                "--exclude=",
                "origin",
                "HEAD",
            ],
            check=True,
        )
        for item in missing:
            oid = item["oid"]
            copy_verified(media / oid[:2] / oid[2:4] / oid, cache_path(root, oid), item)
    verify_cache(root, plan)
    return {"objects": len(plan["objects"]), "requested_LFS_bytes": sum(item["size"] for item in missing)}


def verify_cache(root: Path, plan: dict[str, Any]) -> None:
    for item in plan["objects"]:
        verify_file(cache_path(root, item["oid"]), item)


def compact_cache(root: Path, plan: dict[str, Any]) -> dict:
    """Keep only declared objects in the shared cache; retire extras recoverably.

    This touches only this tool's transfer cache, never Git/LFS objects or
    authoritative proof artifacts. Old cache bytes are hard-linked into an
    ignored recovery directory before their cache-directory links are removed.
    """
    verify_cache(root, plan)
    directory = safe_path(root.resolve(), CACHE_DIRECTORY.as_posix())
    if not directory.exists():
        return {"retired_cache_objects": 0, "authoritative_or_LFS_store_objects_deleted": False}
    declared = {entry["oid"] for entry in plan["objects"]}
    unused = [path for path in directory.iterdir() if path.name not in declared]
    for path in unused:
        if (
            OID_RE.fullmatch(path.name) is None
            or path.is_symlink()
            or not path.is_file()
            or file_hash(path) != path.name
        ):
            raise ValueError("unrecognized/corrupt cache data cannot be silently retired")
    if not unused:
        return {"retired_cache_objects": 0, "authoritative_or_LFS_store_objects_deleted": False}
    retired = Path(tempfile.mkdtemp(prefix="retired-cache-", dir=directory.parent))
    for path in unused:
        os.link(path, retired / path.name)
        path.unlink()
    return {
        "retired_cache_objects": len(unused),
        "recoverable_at": str(retired),
        "authoritative_or_LFS_store_objects_deleted": False,
    }


def install(root: Path, plan: dict[str, Any], n: int, shard_index: int = 0, shard_count: int = 1) -> int:
    from ._proof_partitions import physical_groups
    from .inequality_records import InequalityCatalog
    from .proof_store import ProofCatalog

    root = root.resolve()
    selected = [entry for entry in plan["assets"] if entry["n"] == n]
    directory = root / f"data/n={n}"
    catalog = ProofCatalog(directory / "proofs.json")
    inequalities = InequalityCatalog(directory / "inequalities.json")
    if type(shard_index) is not int or not 0 <= shard_index < shard_count:
        raise ValueError("invalid physical proof shard group")
    owned = physical_groups(catalog, inequalities, shard_count)[shard_index]
    selected = [entry for entry in selected if Path(entry["path"]).stem in owned]
    if not selected:
        raise ValueError(f"no LFS proof payload selected for n={n}")
    for entry in selected:
        target = safe_path(root, entry["path"])
        if not target.resolve().is_relative_to(root):
            raise ValueError("proof destination escapes the repository")
        copy_verified(cache_path(root, entry["oid"]), target, entry)
    return len(selected)


def outputs(plan: dict[str, Any], path: Path) -> None:
    values = {
        "required": str(bool(plan["assets"])).lower(),
        "ns": json.dumps(plan["required_ns"], separators=(",", ":")),
        "key": plan["cache_key"],
        "bytes": str(plan["bytes"]),
    }
    with path.open("a", encoding="utf-8") as stream:
        for name, value in values.items():
            stream.write(f"{name}={value}\n")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "populate", "verify", "install", "snapshot", "audit", "compact"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--fetch", action="store_true", help="explicitly allow one filtered fetch of missing HEAD objects"
    )
    parser.add_argument("--replace", action="store_true", help="explicitly replace the generated storage inventory")
    parser.add_argument("--payloads", action="store_true", help="require actual hydrated LFS bytes, not pointers")
    parser.add_argument("--n", type=int)
    parser.add_argument("--source-root", type=Path, help="verified offline repository-layout payload source")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.fetch and args.command != "populate":
        parser.error("--fetch belongs only to the cache producer")
    if args.source_root is not None and (args.command != "populate" or args.fetch):
        parser.error("--source-root is an offline cache producer, not a download source")
    if args.replace and args.command != "snapshot":
        parser.error("--replace belongs only to inventory snapshot")
    if args.payloads and args.command != "audit":
        parser.error("--payloads belongs only to inventory audit")
    if args.command in ("snapshot", "audit"):
        result = (
            snapshot(root, replace=args.replace)
            if args.command == "snapshot"
            else audit_inventory(root, payloads=args.payloads)
        )
        print(canonical_json(result).decode())
        return
    audit_inventory(root)
    plan = make_plan(root)
    if args.command == "populate":
        result = populate(root, plan, offline=not args.fetch, source_root=args.source_root)
    elif args.command == "verify":
        verify_cache(root, plan)
        result = {"verified_objects": len(plan["objects"]), "verified_bytes": plan["bytes"]}
    elif args.command == "compact":
        result = compact_cache(root, plan)
    elif args.command == "install":
        if args.n is None:
            parser.error("install requires --n")
        result = {"installed_payloads": install(root, plan, args.n, args.shard_index, args.shard_count)}
    else:
        result = plan
    if args.github_output is not None:
        outputs(plan, args.github_output)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
