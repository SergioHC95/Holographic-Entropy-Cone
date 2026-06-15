"""JSON serialization helpers for repository data."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from .coordinates import dim


def json_ready(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, list | tuple):
        return [json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    return value


def json_path(path: str | Path, label: str) -> Path:
    source = Path(path)
    if source.suffix != ".json":
        raise ValueError(f"expected a .json {label} file, got {source}")
    return source


def save_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(json_ready(payload), indent=2) + "\n")


def save_json_records(path: str | Path, records: Iterable[Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(json_ready(record), separators=(",", ": ")) for record in records]
    if not lines:
        target.write_text("[]\n")
        return
    target.write_text("[\n  " + ",\n  ".join(lines) + "\n]\n")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def load_json_records(path: str | Path, label: str, normalize) -> list:
    records = load_json(json_path(path, label))
    if not isinstance(records, list):
        raise ValueError(f"expected a list of {label}s in {path}")
    return [normalize(record) for record in records]


def _clean_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("integer rows cannot contain booleans")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    raise ValueError(f"expected an integer value, got {value!r}")


def read_integer_rows(path: str | Path, *, n: int | None = None) -> list[tuple[int, ...]]:
    rows = load_json(json_path(path, "row"))
    if not isinstance(rows, list):
        raise ValueError(f"expected a list of integer rows in {path}")
    out = []
    for row in rows:
        if not isinstance(row, list | tuple):
            raise ValueError(f"expected an integer row in {path}, got {row!r}")
        out.append(tuple(_clean_int(value) for value in row))
    if n is not None:
        expected = dim(n)
        for row in out:
            if len(row) != expected:
                raise ValueError(f"row in {path} has width {len(row)}, expected {expected}")
    return out
