"""Continue completed corpus phases without overlapping mathematical workers.

The existing derive controller is observed, never adopted, signalled or restarted.
Each later phase uses its own frozen implementation and durable checkpoint. This
driver does not establish mathematical validity and never declares the goal done.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hec.count_proofs import canonical_json, parse_json

from . import run as derivations
from .synthesize import EXPECTED_COUNTS, EXPECTED_TOTAL

FORMAT = "hec-corpus-continuation/1"


def processes():
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,pgid=,rss=,lstart=,command="],
        check=True,
        text=True,
        capture_output=True,
    )
    rows = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 9)
        if len(fields) != 10:
            raise ValueError("cannot safely parse complete live process inventory")
        rows.append(
            {
                "pid": int(fields[0]),
                "ppid": int(fields[1]),
                "pgid": int(fields[2]),
                "rss_bytes": int(fields[3]) * 1024,
                "birth": " ".join(fields[4:9]),
                "command": fields[9],
            }
        )
    return rows


def birth(value):
    return " ".join(value.split())


def read_json(path):
    # Controller owner records are written in place by the older frozen runner.
    for attempt in range(5):
        try:
            return parse_json(Path(path).read_bytes())
        except ValueError:
            if attempt == 4:
                raise
            time.sleep(0.05)


def atomic_record(path, value):
    temporary = path.with_name(path.name + ".next")
    with temporary.open("wb") as stream:
        stream.write(canonical_json(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def counters(root, phase):
    path = root / "checkpoint.sqlite3"
    if not path.is_file():
        return {"done": 0, "expected": EXPECTED_TOTAL, "errors": 0}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        errors = db.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
        if phase == "derive":
            done = db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
            expected = EXPECTED_TOTAL
        elif phase == "source-fresh":
            if db.execute("SELECT COUNT(*) FROM results").fetchone()[0] != EXPECTED_TOTAL:
                raise ValueError("source fresh phase requires every derivation result first")
            done = db.execute("SELECT COUNT(*) FROM fresh WHERE ok=1").fetchone()[0]
            expected = EXPECTED_TOTAL
        elif phase == "synthesize":
            done = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            expected = EXPECTED_TOTAL
        elif phase == "alternative-fresh":
            if db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] != EXPECTED_TOTAL:
                raise ValueError("alternative fresh phase requires every synthesis disposition first")
            done = db.execute("SELECT COUNT(*) FROM fresh WHERE ok=1").fetchone()[0]
            expected = db.execute(
                "SELECT COUNT(*) FROM attempts WHERE status='accepted_strictly_smaller_alternative'"
            ).fetchone()[0]
        else:
            raise ValueError("unknown checkpoint phase")
    if not 0 <= done <= expected:
        raise ValueError("checkpoint exceeds its complete expected phase scope")
    return {"done": done, "expected": expected, "errors": errors}


def idle(root, tracked_groups):
    """Conservative identity/orphan check; no process is ever signalled here."""
    lock_path = root / "controller.lock"
    if lock_path.exists():
        with lock_path.open("r") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
    rows = processes()
    owner_path = root / "controller.json"
    if owner_path.exists():
        owner = read_json(owner_path)
        for row in rows:
            if row["pid"] == owner["pid"] and birth(row["birth"]) == birth(owner["birth"]):
                tracked_groups.add(row["pgid"])
                return False
    binaries = {str(root / name) for name in ("wide", "narrow", "closure", "smoother")}
    for row in rows:
        if row["pid"] == os.getpid():
            continue
        if row["pgid"] in tracked_groups:
            return False
        try:
            args = shlex.split(row["command"])
        except ValueError:
            if str(root) in row["command"]:
                return False
            continue
        if args and args[0] in binaries:
            return False
        if any(args[i : i + 2] == ["--output", str(root)] for i in range(len(args))):
            if "corpus_derivations.run" in args or "corpus_derivations.synthesize" in args:
                tracked_groups.add(row["pgid"])
                return False
    return True


def environment(snapshot):
    result = os.environ.copy()
    result.update(
        PYTHONPATH=str(snapshot / "src") + os.pathsep + str(snapshot / "tools"),
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
    )
    return result


class Continuation:
    def __init__(self, output, binding):
        self.output, self.binding = output, binding
        self.groups = set(binding["initial_source_process_groups"])

    def status(self, phase, **details):
        value = {
            "sample_utc": datetime.now(UTC).isoformat(),
            "phase": phase,
            "processing_worker_limit": derivations.worker_count(self.binding),
            "rss_limit_bytes": 64 * 1024**3,
            "full_goal_complete": False,
            **details,
        }
        atomic_record(self.output / "progress.json", value)
        print(json.dumps(value, sort_keys=True), flush=True)

    def command(self, module, args, snapshot):
        command = [self.binding["python"], "-m", module, *map(str, args)]
        with (self.output / "phases.log").open("ab", buffering=0) as log:
            child = subprocess.Popen(
                command,
                env=environment(snapshot),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self.groups.add(child.pid)
            while child.poll() is None:
                self.status("running-command", command=command, child_pid=child.pid)
                time.sleep(30)
            if child.returncode:
                raise RuntimeError(f"phase exited {child.returncode}; see phases.log: {command}")

    def phase(self, root, phase, module, native_phase, snapshot, *, start_if_idle):
        while True:
            counts = counters(root, phase)
            if counts["errors"]:
                raise RuntimeError(f"{phase} has recorded errors; no next phase admitted")
            is_idle = idle(root, self.groups)
            if counts["done"] == counts["expected"] and is_idle:
                self.status("phase-complete", completed_phase=phase, **counts)
                return
            if is_idle:
                if not start_if_idle:
                    raise RuntimeError(f"{phase} stopped incomplete; intervention required, no automatic restart")
                self.status("admitting-next-phase", admitted_phase=phase, **counts)
                self.command(module, ["--output", root, "run", "--phase", native_phase], snapshot)
                # A partial --limit invocation or unexpected early success is not completion.
                start_if_idle = False
                continue
            self.status("waiting-for-phase-and-process-exit", waiting_phase=phase, **counts)
            time.sleep(30)

    def execute(self):
        source = Path(self.binding["source"])
        snapshot = self.output / "implementation"
        self.phase(source, "derive", "corpus_derivations.run", "derive", source / "implementation", start_if_idle=False)
        self.phase(
            source, "source-fresh", "corpus_derivations.run", "fresh", source / "implementation", start_if_idle=True
        )
        synthesis = self.output / "synthesis"
        if not (synthesis / "run-binding.json").exists():
            if synthesis.exists() and any(synthesis.iterdir()):
                raise RuntimeError("partial synthesis preparation retained; choose an explicit repair, never overwrite")
            self.command(
                "corpus_derivations.synthesize", ["--output", synthesis, "prepare", "--source", source], snapshot
            )
        synthesis_binding = read_json(synthesis / "run-binding.json")
        if (
            synthesis_binding["source"] != str(source)
            or synthesis_binding["source_manifest_sha256"] != self.binding["source_manifest_sha256"]
            or derivations.worker_count(synthesis_binding) != derivations.worker_count(self.binding)
            or synthesis_binding["source_total"] != EXPECTED_TOTAL
            or synthesis_binding["rss_limit_bytes"] != 64 * 1024**3
        ):
            raise ValueError("synthesis binding differs from the approved continuation")
        self.phase(
            synthesis,
            "synthesize",
            "corpus_derivations.synthesize",
            "synthesize",
            synthesis / "implementation",
            start_if_idle=True,
        )
        self.phase(
            synthesis,
            "alternative-fresh",
            "corpus_derivations.synthesize",
            "fresh",
            synthesis / "implementation",
            start_if_idle=True,
        )
        export = self.output / "export"
        if export.exists():
            raise RuntimeError("export already exists; preserve it for independent review rather than overwrite")
        self.command(
            "corpus_derivations.package_results",
            ["--source", source, "--synthesis", synthesis, "--output", export],
            snapshot,
        )
        report = read_json(export / "report.json")
        self.status(
            "packaged-awaiting-independent-review",
            report=str(export / "report.json"),
            retained_alternatives=report["retained_alternatives"],
            additional_synthesis_needed=report["retained_alternatives"] == 0,
        )


def prepare(args):
    output, source = args.output.resolve(), args.source.resolve()
    source_binding = read_json(source / "run-binding.json")
    if (
        source_binding["total"] != EXPECTED_TOTAL
        or derivations.worker_count(source_binding) not in (2, 4, 8)
        or source_binding["scope_counts"] != EXPECTED_COUNTS
        or source_binding["rss_limit_bytes"] != 64 * 1024**3
    ):
        raise ValueError("source differs from the full approved corpus and resource limits")
    if output.exists() and any(output.iterdir()):
        raise ValueError("choose a new empty continuation directory")
    output.mkdir(parents=True, exist_ok=True)
    root, implementation = Path(__file__).resolve().parents[2], {}
    for folder in ("src/hec", "tools/corpus_derivations", "tools/derivation_pilot"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".cpp"):
                relative = path.relative_to(root)
                target = output / "implementation" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                implementation[str(relative)] = derivations.digest(target)
    owner, groups = read_json(source / "controller.json"), []
    for row in processes():
        if row["pid"] == owner["pid"] and birth(row["birth"]) == birth(owner["birth"]):
            groups.append(row["pgid"])
    # Preserve the venv executable path; resolving its symlink would discard the venv.
    python = str(args.python.absolute())
    binding = {
        "format": FORMAT,
        "prepared_utc": datetime.now(UTC).isoformat(),
        "source": str(source),
        "source_binding_sha256": derivations.digest(source / "run-binding.json"),
        "source_manifest_sha256": source_binding["manifest_sha256"],
        "python": python,
        "python_sha256": derivations.digest(python),
        "workers": derivations.worker_count(source_binding),
        "rss_limit_bytes": 64 * 1024**3,
        "total": EXPECTED_TOTAL,
        "initial_source_process_groups": groups,
        "implementation": implementation,
    }
    derivations.save_new(output / "run-binding.json", binding)
    print(json.dumps({"prepared": True, "output": str(output), "workers_started": 0}), flush=True)


def execute(args):
    output = args.output.resolve()
    with (output / "continuation.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        binding = read_json(output / "run-binding.json")
        if (
            binding["format"] != FORMAT
            or derivations.worker_count(binding) not in (2, 4, 8)
            or binding["total"] != EXPECTED_TOTAL
            or binding["rss_limit_bytes"] != 64 * 1024**3
        ):
            raise ValueError("continuation scope/resource binding changed")
        if derivations.digest(binding["python"]) != binding["python_sha256"]:
            raise ValueError("continuation Python runtime changed")
        source = Path(binding["source"])
        if (
            derivations.digest(source / "run-binding.json") != binding["source_binding_sha256"]
            or derivations.digest(source / "manifest.json") != binding["source_manifest_sha256"]
        ):
            raise ValueError("immutable source binding or manifest changed")
        for relative, sha in binding["implementation"].items():
            if derivations.digest(output / "implementation" / relative) != sha:
                raise ValueError("frozen continuation implementation changed")
        own = next(row for row in processes() if row["pid"] == os.getpid())
        # This is a mutable operational identity, not an immutable proof binding.
        atomic_record(output / "owner.json", own)
        driver = Continuation(output, binding)
        try:
            driver.execute()
        except Exception as error:
            driver.status("needs-attention-no-next-phase-admitted", error=str(error))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare")
    setup.add_argument("--source", type=Path, required=True)
    setup.add_argument("--python", type=Path, required=True)
    commands.add_parser("run")
    args = parser.parse_args()
    prepare(args) if args.command == "prepare" else execute(args)


if __name__ == "__main__":
    main()
