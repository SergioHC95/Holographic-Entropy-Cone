"""Timestamped output folders and the parallel generation harness."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Executor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from .data import available_ns, load_hec_data
from .serialization import save_json

write_timings = save_json

# A worker maps (n, index, item) to (record, timing, log_line).
Worker = Callable[[int, int, Any], tuple[Any, dict, str]]
Writer = Callable[[Path, Sequence[Any]], None]


def create_run_output(prefix: str, root: str | Path) -> tuple[Path, Path]:
    path = Path(root) / f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    if path.exists():
        raise FileExistsError(f"output root already exists: {path}")
    path.mkdir()
    return path, path / "timings.json"


def run_generation(
    *,
    prefix: str,
    run_root_parent: str | Path,
    data_root: str | Path | None,
    kind: str,
    record_name: str,
    worker: Worker,
    writer: Writer,
    executor: Callable[[], Executor],
    workers: int,
    write_every: int,
) -> None:
    """Solve ``worker`` for every stored item of ``kind`` across all ``n``.

    Records are streamed to ``{prefix}_<timestamp>/<record_name>_n<n>.json`` as workers
    finish: every ``write_every`` completions (and at the end of each ``n``) the
    longest gap-free prefix of finished records is written, alongside timings.
    """
    run_root, timings_path = create_run_output(prefix, run_root_parent)
    print(f"writing {run_root}", flush=True)
    print(f"writing {timings_path}", flush=True)
    print(f"workers {workers}", flush=True)

    timings: dict[str, list[dict | None]] = {}
    for n in available_ns(root=data_root):
        items = load_hec_data(n, kind, root=data_root)
        records: list[Any] = [None] * len(items)
        timings[str(n)] = [None] * len(items)
        record_path = run_root / f"{record_name}_n{n}.json"
        written_ready = 0

        with executor() as pool:
            futures = {pool.submit(worker, n, index, item): index for index, item in enumerate(items)}
            for completed, future in enumerate(as_completed(futures), start=1):
                index = futures[future]
                record, timing, log_line = future.result()
                records[index] = record
                timings[str(n)][index] = timing
                print(log_line, flush=True)
                if completed % write_every == 0 or completed == len(items):
                    ready = next((i for i, item in enumerate(records) if item is None), len(records))
                    write_timings(
                        timings_path,
                        {key: [row for row in rows if row is not None] for key, rows in timings.items()},
                    )
                    if ready != written_ready:
                        writer(record_path, records[:ready])
                        written_ready = ready

        if any(record is None for record in records):
            raise RuntimeError(f"n={n}: missing result")
        print(f"n={n}: wrote {len(records)} records", flush=True)
