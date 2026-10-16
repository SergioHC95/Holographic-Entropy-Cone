"""Build and bind the installed package's exact C++17 verification backends."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from .count_proofs import canonical_json, parse_json

FORMAT = "hec-exact-native"
SOURCES = {"closure": "closure.cpp", "cube": "verify.cpp"}
MANIFEST = "native.json"


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024**2), b""):
            result.update(block)
    return result.hexdigest()


def source_bindings():
    directory = Path(__file__).with_name("_native")
    return {
        name: {"path": directory / filename, "sha256": digest(directory / filename)}
        for name, filename in SOURCES.items()
    }


def load_backends(directory):
    """Fail closed if a configured release, binary, source or platform differs."""
    directory = Path(directory).absolute()
    if directory.is_symlink() or not directory.is_dir() or (directory / MANIFEST).is_symlink():
        raise ValueError("missing or unsafe exact native directory")
    document = parse_json((directory / MANIFEST).read_bytes())
    if (
        not isinstance(document, dict)
        or set(document) != {"format", "platform", "machine", "compiler", "backends"}
        or document["format"] != FORMAT
        or document["platform"] != platform.system()
        or document["machine"] != platform.machine()
        or not isinstance(document["compiler"], str)
        or not isinstance(document["backends"], dict)
        or set(document["backends"]) != set(SOURCES)
    ):
        raise ValueError("unsupported or cross-platform native release")
    result = {}
    for name, source in source_bindings().items():
        item = document["backends"][name]
        expected = name + (".exe" if os.name == "nt" else "")
        if not isinstance(item, dict) or set(item) != {"file", "sha256", "source_sha256"}:
            raise ValueError("invalid exact native binding")
        binary = directory / expected
        if (
            item["file"] != expected
            or item["source_sha256"] != source["sha256"]
            or binary.is_symlink()
            or not binary.is_file()
            or digest(binary) != item["sha256"]
        ):
            raise ValueError("exact native binary/source binding mismatch")
        result[name] = binary
    return result


def build_backends(directory, *, compiler=None):
    """Publish a complete bound release atomically; never replace an existing one."""
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        load_backends(directory)
        return parse_json((directory / MANIFEST).read_bytes())
    if directory.parent.is_symlink():
        raise ValueError("unsafe exact native build destination")
    command = shlex.split(compiler or os.environ.get("CXX", "c++"))
    if not command:
        raise ValueError("an explicit C++17 compiler is required")
    description = subprocess.run([*command, "--version"], check=True, capture_output=True, text=True).stdout
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".hec-native-", dir=directory.parent))
    try:
        backends = {}
        for name, source in source_bindings().items():
            binary = temporary / (name + (".exe" if os.name == "nt" else ""))
            subprocess.run(
                [*command, "-O3", "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source["path"]), "-o", str(binary)],
                check=True,
            )
            backends[name] = {"file": binary.name, "sha256": digest(binary), "source_sha256": source["sha256"]}
        document = {
            "format": FORMAT,
            "platform": platform.system(),
            "machine": platform.machine(),
            "compiler": description,
            "backends": backends,
        }
        (temporary / MANIFEST).write_bytes(canonical_json(document) + b"\n")
        load_backends(temporary)
        # Publish immutable binaries first and the readiness manifest LAST.
        # No existing release or racing directory is ever overwritten.
        directory.mkdir(exist_ok=False)
        for item in backends.values():
            os.link(temporary / item["file"], directory / item["file"])
        os.link(temporary / MANIFEST, directory / MANIFEST)
        return document
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)  # Solely the directory created by this call.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--compiler")
    args = parser.parse_args(argv)
    if args.command == "build":
        value = build_backends(args.directory, compiler=args.compiler)
    else:
        value = {"verified_backends": {name: str(path) for name, path in load_backends(args.directory).items()}}
    print(canonical_json(value).decode())


if __name__ == "__main__":
    main()
