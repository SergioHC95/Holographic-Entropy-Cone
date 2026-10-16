"""Ordinary-Git storage integrity for the exact reconstruction proof corpus.

Every required byte arrives through Git. No hydration service, artifact cache,
download command, pointer resolver or stored mathematical acceptance exists.
Metadata planning and byte integrity never substitute for full-map audits.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .count_proofs import canonical_json, parse_json

INVENTORY = "data/storage.json"
INVENTORY_FORMAT = "hec-repository-storage"
MAX_GIT_FILE_BYTES = 100 * 1024**2
POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"


def run_git(root, *args, input=None):
    return subprocess.run(["git", "-C", str(root), *args], input=input, check=True, capture_output=True).stdout


def safe_path(root, relative):
    if (
        not isinstance(relative, str)
        or not re.fullmatch(r"[A-Za-z0-9_=./-]+", relative)
        or relative.startswith("/")
        or any(part in ("", ".", "..") for part in relative.split("/"))
    ):
        raise ValueError("unsafe repository storage path")
    root = Path(root).resolve()
    target = root / relative
    current = target
    while current != root:
        if current.is_symlink():
            raise ValueError("repository storage paths cannot traverse symlinks")
        current = current.parent
    if not target.resolve().is_relative_to(root):
        raise ValueError("storage path escapes the repository")
    return target


def inspect_file(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required Git payload is missing or unsafe: {path}")
    size = path.stat().st_size
    if size > MAX_GIT_FILE_BYTES:
        raise ValueError("file exceeds the ordinary-Git limit; shard or improve the encoding")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        first = source.read(1024**2)
        if first.startswith(POINTER_PREFIX):
            raise ValueError("LFS pointers are forbidden; actual payload bytes must be committed in Git")
        digest.update(first)
        for block in iter(lambda: source.read(1024**2), b""):
            digest.update(block)
    return size, digest.hexdigest()


def repository_paths(root):
    raw = run_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "data", "provenance")
    paths = set(filter(None, raw.decode("utf-8").split("\0")))
    allowed = re.compile(
        r"data/(?:storage\.json|n=[1-9][0-9]*/(?:(?:facets|rays|graphs|inequalities|proofs)\.json"
        r"|proof-shards/[0-9a-f]{64}\.proofpack))"
    )
    if any(allowed.fullmatch(path) is None for path in paths):
        raise ValueError("unexpected production data path; research and migration records belong outside the data tree")
    return paths


def make_plan(root):
    """Plan complete payload ownership without requiring a materialized checkout.

    A sparse Git checkout may omit payload bytes while planning. This performs
    NO mathematical or byte-validity acceptance. Required storage and full-cube
    CI jobs independently verify the actual saved bytes.
    """
    from .proof_store import ProofCatalog

    root = Path(root).resolve()
    known = repository_paths(root)
    payloads, count, identities = [], 0, set()
    catalogs = sorted(path for path in known if re.fullmatch(r"data/n=[1-9][0-9]*/proofs.json", path))
    if not catalogs:
        raise ValueError("no standard proof catalogs; empty storage is not acceptance")
    expected = set()
    for relative in catalogs:
        path = safe_path(root, relative)
        n = int(path.parent.name[2:])
        catalog = ProofCatalog(path)
        count += len(catalog)
        for entry in catalog.entries:
            if entry["proof_id"] in identities:
                raise ValueError("proof identity is repeated across party-count catalogues")
            identities.add(entry["proof_id"])
        for key, shard in sorted(catalog.shards.items()):
            relative_payload = f"data/n={n}/proof-shards/{key}.proofpack"
            if not 0 < shard["bytes"] <= MAX_GIT_FILE_BYTES:
                raise ValueError("proof shard exceeds the ordinary-Git file limit; improve or shard the encoding")
            expected.add(relative_payload)
            payloads.append({"path": relative_payload, "sha256": key, "bytes": shard["bytes"], "n": n})
    actual = {path for path in known if "/proof-shards/" in path}
    if expected != actual:
        raise ValueError("missing or unindexed ordinary-Git proof payload")
    return {
        "format": "hec-git-storage-plan",
        "proofs": count,
        "payloads": payloads,
        "payload_bytes": sum(row["bytes"] for row in payloads),
        "content_verified": False,
        "mathematical_acceptance": False,
    }


def inventory_document(root):
    root = Path(root).resolve()
    plan = make_plan(root)
    required = {row["path"]: row for row in plan["payloads"]}
    paths = repository_paths(root)
    paths.discard(INVENTORY)
    entries = []
    for relative in sorted(paths):
        path = safe_path(root, relative)
        if not path.exists():
            if relative in required:
                raise ValueError("required Git payload is absent from the checkout")
            continue
        size, sha = inspect_file(path)
        if relative in required:
            item = required[relative]
            if type(item["bytes"]) is not int or item["bytes"] != size or item["sha256"] != sha:
                raise ValueError("required payload differs from its proof identity")
        entries.append({"path": relative, "sha256": sha, "bytes": size})
    if not entries or not required.keys() <= {entry["path"] for entry in entries}:
        raise ValueError("incomplete ordinary-Git inventory")
    return {"format": INVENTORY_FORMAT, "entries": entries}


def snapshot(root, *, replace=False):
    root = Path(root).resolve()
    document = inventory_document(root)
    target = safe_path(root, INVENTORY)
    if target.exists() and not replace:
        raise ValueError("storage inventory exists; explicit --replace is required")
    fd, name = tempfile.mkstemp(prefix=".git-inventory-", dir=target.parent)
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
    return {"files": len(document["entries"]), "content_verified": True, "mathematical_acceptance": False}


def audit_inventory(root):
    root = Path(root).resolve()
    document = parse_json(safe_path(root, INVENTORY).read_bytes())
    if canonical_json(document) != canonical_json(inventory_document(root)):
        raise ValueError("ordinary-Git inventory differs from actual paths, hashes or sizes")
    return {"files": len(document["entries"]), "content_verified": True, "mathematical_acceptance": False}


def history_audit(root, *, all_refs=False):
    """Read every reachable blob: no pointers, large artifacts or LFS filters.

    A complete history is required. This never deletes objects, rewrites refs,
    fetches artifacts, or accepts a mathematical proof.
    """
    root = Path(root).resolve()
    if run_git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ValueError("complete Git history is required for the history hygiene audit")
    revision = "--all" if all_refs else "HEAD"
    records = run_git(root, "rev-list", "--objects", revision).decode().splitlines()
    ids, attributes = [], set()
    if run_git(root, "log", "--format=%H", "-1", revision, "--", ".lfsconfig", ":(glob)**/.lfsconfig").strip():
        raise ValueError("retired LFS configuration remains in reachable history")
    changes = (
        run_git(
            root,
            "log",
            "--format=",
            "--raw",
            "--no-abbrev",
            "-m",
            "--no-renames",
            revision,
            "--",
            ".gitattributes",
            ":(glob)**/.gitattributes",
        )
        .decode()
        .splitlines()
    )
    for line in changes:
        if line.startswith(":"):
            fields = line.split("\t", 1)[0].split()
            attributes.update(oid for oid in fields[2:4] if set(oid) != {"0"})
    for record in records:
        oid, _, path = record.partition(" ")
        ids.append(oid)
        if path.endswith(".lfsconfig"):
            raise ValueError("retired LFS configuration remains in reachable history")
        if path.endswith(".gitattributes"):
            attributes.add(oid)
    metadata = (
        run_git(
            root,
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            input=("".join(oid + "\n" for oid in ids)).encode(),
        )
        .decode()
        .splitlines()
    )
    blobs = []
    for row in metadata:
        oid, kind, size = row.split()
        if kind == "blob":
            if int(size) > MAX_GIT_FILE_BYTES:
                raise ValueError("reachable Git blob exceeds the ordinary-Git file limit")
            if oid in attributes and int(size) > 1024**2:
                raise ValueError("oversized Git attributes cannot be audited safely")
            blobs.append((oid, int(size)))
    process = subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    total, largest = 0, 0
    try:
        for oid, size in blobs:
            process.stdin.write((oid + "\n").encode())
            process.stdin.flush()
            header = process.stdout.readline().split()
            if header != [oid.encode(), b"blob", str(size).encode()]:
                raise ValueError("incomplete or misbound Git object response")
            remaining, prefix = size, bytearray()
            while remaining:
                block = process.stdout.read(min(1024**2, remaining))
                if not block:
                    raise ValueError("truncated reachable Git blob")
                prefix.extend(block if oid in attributes else block[: max(0, 1024 - len(prefix))])
                remaining -= len(block)
            if process.stdout.read(1) != b"\n":
                raise ValueError("invalid Git object framing")
            if prefix.startswith(POINTER_PREFIX):
                raise ValueError("reachable LFS pointer remains in Git history")
            if oid in attributes and re.search(rb"filter\s*=\s*lfs\b", prefix):
                raise ValueError("reachable LFS filter remains in Git history")
            total += size
            largest = max(largest, size)
        process.stdin.close()
        if process.wait() != 0:
            raise ValueError("Git object audit failed")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait()
        if not process.stdin.closed:
            process.stdin.close()
        process.stdout.close()
    return {
        "commits": int(run_git(root, "rev-list", "--count", revision)),
        "blobs": len(blobs),
        "reachable_blob_bytes": total,
        "largest_blob_bytes": largest,
        "LFS_pointers": 0,
        "LFS_filters": 0,
        "mathematical_acceptance": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "snapshot", "audit", "history"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--all-refs", action="store_true")
    args = parser.parse_args(argv)
    if args.replace and args.command != "snapshot":
        parser.error("--replace belongs only to snapshot")
    if args.all_refs and args.command != "history":
        parser.error("--all-refs belongs only to history")
    if args.command == "plan":
        result = make_plan(args.root)
    elif args.command == "snapshot":
        result = snapshot(args.root, replace=args.replace)
    elif args.command == "history":
        result = history_audit(args.root, all_refs=args.all_refs)
    else:
        result = audit_inventory(args.root)
    print(canonical_json(result).decode())


if __name__ == "__main__":
    main()
