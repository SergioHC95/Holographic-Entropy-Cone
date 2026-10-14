"""Share only active, SHA256-verified compact proof shards between CI jobs.

Only the producer may fetch LFS. Consumers fail closed on a missing/corrupt
cache: they never retry an unrestricted download in every matrix job. Archive
bundles, historical revisions, and inconclusive proof streams are not selected.
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

CACHE_DIRECTORY = Path(".hec-ci-lfs/objects")
MAX_CACHE_BYTES = 2 * 1024**3
OID_RE = re.compile(r"[0-9a-f]{64}")


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
    root = root.resolve()
    assets = []
    for source in sorted((root / "data").glob("n=*/proofs.json")):
        if not source.parent.name[2:].isdigit():
            continue
        n = int(source.parent.name[2:])
        payload = json.loads(source.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"format", "entries", "shards"}
            or payload.get("format") != "hec-proof-catalog/1"
            or not isinstance(payload["shards"], dict)
        ):
            raise ValueError(f"unsupported exact proof catalog: {source}")
        for key, shard in sorted(payload["shards"].items()):
            if OID_RE.fullmatch(key) is None or not isinstance(shard, dict) or set(shard) != {"bytes"}:
                raise ValueError(f"invalid proof shard identity: {source}")
            item = {"compressed_sha256": key, "compressed_size": shard["bytes"]}
            path = source.parent / "proof-shards" / f"{key}.proofpack"
            entry = payload_entry(root, path, item, n)
            if entry is not None:
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
        "cache_key": f"hec-active-proofs-v2-{fingerprint}",
        "required_ns": sorted({entry["n"] for entry in assets}),
    }


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


def populate(root: Path, plan: dict[str, Any], *, offline: bool = False) -> dict[str, int]:
    root = root.resolve()
    media = None
    needed = []
    for item in plan["objects"]:
        cached = cache_path(root, item["oid"])
        if cached.exists() or cached.is_symlink():
            verify_file(cached, item)
        else:
            needed.append(item)
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


def install(root: Path, plan: dict[str, Any], n: int, shard_index: int = 0, shard_count: int = 1) -> int:
    root = root.resolve()
    selected = [entry for entry in plan["assets"] if entry["n"] == n]
    catalog = json.loads((root / f"data/n={n}/proofs.json").read_text())
    keys = sorted(catalog["shards"])
    if not 1 <= shard_count <= len(keys) or not 0 <= shard_index < shard_count:
        raise ValueError("invalid physical proof shard group")
    owned = set(keys[shard_index::shard_count])
    selected = [entry for entry in selected if Path(entry["path"]).stem in owned]
    if not selected:
        raise ValueError(f"no LFS proof payload selected for n={n}")
    for entry in selected:
        target = root / entry["path"]
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "populate", "verify", "install"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--n", type=int)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    root = args.root.resolve()
    plan = make_plan(root)
    if args.command == "populate":
        result = populate(root, plan, offline=args.offline)
    elif args.command == "verify":
        verify_cache(root, plan)
        result = {"verified_objects": len(plan["objects"]), "verified_bytes": plan["bytes"]}
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
