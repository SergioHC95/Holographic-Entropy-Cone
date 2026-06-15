"""Locate and read HEC repository data files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, get_args

from .serialization import read_integer_rows

DataKind = Literal["facets", "rays", "graphs", "contractions"]
DATA_KINDS = frozenset(get_args(DataKind))


def default_data_root() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def available_ns(root: str | Path | None = None, max_n: int | None = None) -> list[int]:
    base = default_data_root() if root is None else Path(root)
    ns = (int(path.name[2:]) for path in base.glob("n=*") if path.name[2:].isdigit())
    return sorted(n for n in ns if max_n is None or n <= max_n)


def data_path(n: int, kind: DataKind, *, root: str | Path | None = None) -> Path:
    if kind not in DATA_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(sorted(DATA_KINDS))}")
    base = default_data_root() if root is None else Path(root)
    return base / f"n={int(n)}" / f"{kind}.json"


def load_hec_data(n: int, kind: DataKind, *, root: str | Path | None = None) -> Any:
    path = data_path(n, kind, root=root)
    if kind == "graphs":
        from .graphs import read_graphs

        return read_graphs(path)
    if kind == "contractions":
        from .contractions import read_contractions

        return read_contractions(path)
    return read_integer_rows(path, n=n)
