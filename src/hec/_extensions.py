"""Build helpers for local compiled extensions."""

from __future__ import annotations

import importlib
import subprocess
import sys
import time
from pathlib import Path

CONTRACTION_EXTENSION_NAMES = ("clause_builder", "clause_direct")


def ensure_contraction_extensions() -> None:
    """Build contraction Cython extensions in-place when a source checkout lacks them."""
    missing = _missing_contraction_extensions()
    if not missing:
        return

    repo_root = Path(__file__).resolve().parents[2]
    setup_py = repo_root / "setup.py"
    if not setup_py.exists():
        names = ", ".join(f"hec.{name}" for name in missing)
        raise RuntimeError(f"missing compiled contraction extensions ({names}) and no setup.py was found at {setup_py}")

    _build_extensions_once(repo_root)
    importlib.invalidate_caches()
    missing = _missing_contraction_extensions()
    if missing:
        names = ", ".join(f"hec.{name}" for name in missing)
        raise RuntimeError(f"compiled contraction extensions are still missing after build: {names}")


def _missing_contraction_extensions() -> list[str]:
    missing: list[str] = []
    for name in CONTRACTION_EXTENSION_NAMES:
        try:
            importlib.import_module(f"hec.{name}")
        except ImportError:
            missing.append(name)
    return missing


def _build_extensions_once(repo_root: Path) -> None:
    lock = repo_root / "build" / ".hec-extension-build.lock"
    lock.parent.mkdir(exist_ok=True)
    deadline = time.monotonic() + 600.0
    acquired = False
    while time.monotonic() < deadline:
        try:
            lock.mkdir()
            acquired = True
            break
        except FileExistsError:
            time.sleep(0.2)
            importlib.invalidate_caches()
            if not _missing_contraction_extensions():
                return
    if not acquired:
        raise TimeoutError(f"timed out waiting for extension build lock: {lock}")

    try:
        subprocess.run([sys.executable, "setup.py", "build_ext", "--inplace"], cwd=repo_root, check=True)
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass
