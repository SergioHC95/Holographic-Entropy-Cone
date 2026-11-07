"""Authenticate reusable integrity results against Git trees and GitHub Actions.

An arbitrary cache flag, commit status, successful unrelated workflow or PR
head is insufficient. The actual checkout tree of the successful integrity
run must equal the baseline tree, and its verifier inputs must be unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .count_proofs import canonical_json, parse_json

SHA = re.compile(r"[0-9a-f]{40}\Z")
WORKFLOW = ".github/workflows/database-integrity.yml"
RECEIPT_TITLE = "HEC integrity acceptance v1"
VERIFIER_ROOTS = ("src/", "schemas/", "tests/", ".github/")
VERIFIER_FILES = {
    "pyproject.toml",
    "uv.lock",
    "uv.toml",
    "setup.py",
    "setup.cfg",
    "MANIFEST.in",
    "requirements.txt",
    "requirements-dev.txt",
    ".python-version",
    ".gitattributes",
    ".gitmodules",
}


class GitTree:
    def __init__(self, repository, revision="HEAD"):
        self.repository = Path(repository).resolve()
        self.commit = self.git("rev-parse", "--verify", revision + "^{commit}").decode().strip()
        if SHA.fullmatch(self.commit) is None:
            raise ValueError("invalid immutable Git commit")
        self.tree = self.git("rev-parse", self.commit + "^{tree}").decode().strip()
        self.files = {}
        self.entries = {}
        for row in self.git("ls-tree", "-rz", "--full-tree", self.commit).split(b"\0"):
            if not row:
                continue
            header, path = row.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            name = path.decode()
            self.entries[name] = (mode, kind, oid)
            if kind == "blob":
                self.files[name] = (mode, oid)

    def git(self, *args, input=None):
        return subprocess.run(
            ["git", "-C", str(self.repository), *args], input=input, capture_output=True, check=True
        ).stdout

    def read(self, path):
        if path not in self.files or self.files[path][0] not in ("100644", "100755"):
            raise ValueError(f"missing or non-regular Git file: {path}")
        return self.git("show", self.commit + ":" + path)

    def oid(self, path):
        return self.files.get(path)

    def fingerprint(self):
        entries = [
            [path, *value]
            for path, value in sorted(self.entries.items())
            if path in VERIFIER_FILES or path.startswith(VERIFIER_ROOTS)
        ]
        if not any(path.startswith("src/") for path, *_ in entries):
            raise ValueError("missing verifier implementation")
        return hashlib.sha256(canonical_json(entries)).hexdigest()

    def require_clean_verifier(self):
        dirty = self.git(
            "status", "--porcelain", "--untracked-files=all", "--", *VERIFIER_ROOTS, *sorted(VERIFIER_FILES)
        )
        if dirty.strip():
            raise ValueError("CI verifier working files differ from the immutable commit")

    def is_ancestor(self, commit):
        if SHA.fullmatch(commit) is None:
            return False
        return (
            subprocess.run(
                ["git", "-C", str(self.repository), "merge-base", "--is-ancestor", commit, self.commit],
                capture_output=True,
            ).returncode
            == 0
        )


def prepare_history(repository, head, base=None):
    """Fetch commit/tree ancestry, lazily fetching only metadata blobs in use."""
    if SHA.fullmatch(head) is None or (base is not None and SHA.fullmatch(base) is None):
        raise ValueError("history preparation requires full immutable SHAs")
    directory = Path(repository).resolve()

    def git(*args):
        return subprocess.run(["git", "-C", str(directory), *args], capture_output=True, check=True).stdout

    git("config", "remote.origin.promisor", "true")
    git("config", "remote.origin.partialclonefilter", "blob:none")
    if git("rev-parse", "--is-shallow-repository").strip() == b"true":
        git("fetch", "--no-tags", "--no-recurse-submodules", "--filter=blob:none", "--unshallow", "origin", head)
    if base is not None:
        exists = subprocess.run(
            ["git", "-C", str(directory), "cat-file", "-e", base + "^{commit}"], capture_output=True
        )
        if exists.returncode:
            git("fetch", "--no-tags", "--no-recurse-submodules", "--filter=blob:none", "origin", base)


class GitHub:
    def __init__(self, repository=None):
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY", "")
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository) is None:
            raise ValueError("an exact GitHub repository identity is required")

    def request(self, path, *, pages=False, raw=False):
        args = ["gh", "api", "--hostname", "github.com", f"repos/{self.repository}/{path}"]
        if pages:
            args += ["--paginate", "--slurp"]
        for attempt in range(3):
            try:
                result = subprocess.run(args, capture_output=True, check=True, timeout=60)
                break
            except subprocess.TimeoutExpired:
                if attempt == 2:
                    raise
            except subprocess.CalledProcessError as exc:
                error = (exc.stderr or b"").decode(errors="replace").lower()
                if attempt == 2 or not any(
                    term in error
                    for term in (
                        "http 502",
                        "http 503",
                        "http 504",
                        "tls handshake timeout",
                        "connection reset",
                        "unexpected eof",
                        "i/o timeout",
                        "could not resolve host",
                    )
                ):
                    raise
            time.sleep(2**attempt)
        if raw:
            return result.stdout.decode("utf-8-sig")
        return json.loads(result.stdout)


@dataclass(frozen=True)
class VerifiedBaseline:
    base: str
    tree: str
    accepted_commit: str
    tested_commit: str
    run_id: int
    run_attempt: int
    gate_id: int
    verifier: str

    def document(self):
        return asdict(self)


def checkout_commit(log):
    """Read the explicit checkout log command, never an arbitrary SHA in logs."""
    ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    pending, commits = False, []
    for raw in log.splitlines():
        line = ansi.sub("", raw.lstrip("\ufeff"))
        line = re.sub(r"^\d{4}-\d\d-\d\dT\S+\s+", "", line).strip()
        if "git log -1 --format=%H" in line:
            pending = True
        elif pending and SHA.fullmatch(line):
            commits.append(line)
            pending = False
        elif pending and line and not line.startswith("##["):
            pending = False
    if len(commits) != 1:
        raise ValueError("integrity checkout commit is absent or ambiguous")
    return commits[0]


def acceptance_receipt(pages, verifier):
    records = [entry for page in pages for entry in page if entry.get("title") == RECEIPT_TITLE]
    if not records:
        return None
    if len(records) != 1 or records[0].get("annotation_level") != "notice":
        raise ValueError("ambiguous integrity acceptance annotation")
    value = parse_json(records[0]["message"].encode())
    if not isinstance(value, dict) or set(value) != {
        "format",
        "tested_commit",
        "tree",
        "verifier",
        "plan_sha256",
        "mode",
    }:
        raise ValueError("invalid integrity acceptance annotation")
    if not all(isinstance(item, str) for item in value.values()):
        raise ValueError("non-string integrity acceptance context")
    if (
        value["format"] != "hec-integrity-acceptance-v1"
        or value["verifier"] != verifier
        or value["mode"] not in ("full", "incremental")
        or SHA.fullmatch(value["tested_commit"]) is None
        or SHA.fullmatch(value["tree"]) is None
        or re.fullmatch(r"[0-9a-f]{64}", value["plan_sha256"]) is None
    ):
        raise ValueError("integrity acceptance annotation has a different context")
    return value


def verify_baseline(current, base, github, *, run_id=None, gate_id=None):
    """Return evidence only after authenticating a complete successful run.

    A merge commit may share its exact tree with its already-tested parent.
    Its extra history is NOT inherited: storage history still audits every
    commit/object after accepted_commit, including the new merge parents.
    """
    if SHA.fullmatch(base or "") is None or not current.is_ancestor(base):
        raise ValueError("baseline is not an ancestor of the tested checkout")
    baseline = GitTree(current.repository, base)
    if current.fingerprint() != baseline.fingerprint():
        raise ValueError("verifier, schemas, dependencies, tests or CI changed")
    workflow = github.request("actions/workflows/database-integrity.yml")
    candidates = [base]
    parents = baseline.git("show", "-s", "--format=%P", base).decode().split()
    for parent in parents:
        tree = GitTree(current.repository, parent)
        if tree.tree == baseline.tree:
            candidates.append(parent)
    for candidate in candidates:
        if gate_id is not None:
            checks = [github.request(f"check-runs/{gate_id}")]
        else:
            pages = github.request(
                f"commits/{candidate}/check-runs?check_name=database%20integrity&filter=latest&per_page=100",
                pages=True,
            )
            checks = [check for page in pages for check in page["check_runs"]]
        for check in checks:
            if not (
                check.get("name") == "database integrity"
                and check.get("status") == "completed"
                and check.get("conclusion") == "success"
                and check.get("head_sha") == candidate
                and check.get("app", {}).get("id") == 15368
            ):
                continue
            match = re.fullmatch(
                rf"https://github.com/{re.escape(github.repository)}/actions/runs/(\d+)/job/(\d+)",
                check.get("details_url", ""),
            )
            if not match or int(match[2]) != check["id"] or (run_id is not None and int(match[1]) != run_id):
                continue
            run = github.request(f"actions/runs/{match[1]}")
            if not (
                run.get("status") == "completed"
                and run.get("conclusion") == "success"
                and run.get("head_sha") == candidate
                and run.get("workflow_id") == workflow["id"]
                and run.get("path") == WORKFLOW
                and run.get("event") in ("push", "pull_request", "workflow_dispatch")
            ):
                continue
            receipt = acceptance_receipt(
                github.request(f"check-runs/{check['id']}/annotations?per_page=100", pages=True),
                current.fingerprint(),
            )
            if receipt is not None:
                tested = receipt["tested_commit"]
                if receipt["tree"] != baseline.tree or (
                    run["event"] in ("push", "workflow_dispatch") and tested != candidate
                ):
                    raise ValueError("acceptance annotation does not bind the actual baseline tree")
            else:
                # Legacy full runs predate explicit tree receipts. Authenticate
                # their complete job set and actual checkout log instead.
                pages = github.request(f"actions/runs/{run['id']}/jobs?filter=latest&per_page=100", pages=True)
                jobs = [job for page in pages for job in page["jobs"]]
                if len({job["id"] for job in jobs}) != len(jobs) or any(
                    page.get("total_count") != len(jobs) for page in pages
                ):
                    raise ValueError("duplicate or incomplete baseline workflow job pages")
                required = {
                    "discover datasets",
                    "ordinary Git data and complete main-ancestry hygiene",
                    "installed wheel and exact small-corpus acceptance",
                    "database integrity",
                    "code quality and tests (ubuntu-24.04)",
                    "code quality and tests (macos-15)",
                    "catalogue integration (ubuntu-24.04)",
                    "catalogue integration (macos-15)",
                }
                if not required <= {job["name"] for job in jobs} or any(
                    job.get("status") != "completed" or job.get("conclusion") != "success" for job in jobs
                ):
                    continue
                gate = [job for job in jobs if job["id"] == check["id"]]
                if len(gate) != 1 or gate[0].get("conclusion") != "success":
                    continue
                if run["event"] in ("push", "workflow_dispatch"):
                    tested = candidate
                else:
                    discovery = [job for job in jobs if job["name"] == "discover datasets"]
                    if len(discovery) != 1 or discovery[0].get("conclusion") != "success":
                        continue
                    log = github.request(f"actions/jobs/{discovery[0]['id']}/logs", raw=True)
                    tested = checkout_commit(log)
            commit = github.request(f"git/commits/{tested}")
            if commit["tree"]["sha"] != baseline.tree:
                continue
            if (
                receipt is not None
                and run["event"] == "pull_request"
                and tested != candidate
                and candidate not in {parent["sha"] for parent in commit["parents"]}
            ):
                raise ValueError("acceptance annotation is not the tested pull-request merge")
            return VerifiedBaseline(
                base,
                baseline.tree,
                candidate,
                tested,
                run["id"],
                run["run_attempt"],
                check["id"],
                current.fingerprint(),
            )
    raise ValueError("no authenticated successful integrity run for the exact baseline tree")
