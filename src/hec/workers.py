"""Worker-count policy for generation scripts."""

from __future__ import annotations

import os


def generation_worker_count(env_var: str = "HEC_WORKERS") -> int:
    raw = os.environ.get(env_var)
    if raw is not None:
        try:
            workers = int(raw)
        except ValueError as exc:
            raise ValueError(f"{env_var} must be a positive integer, got {raw!r}") from exc
        if workers < 1:
            raise ValueError(f"{env_var} must be a positive integer, got {workers}")
        return workers
    return max(1, (os.cpu_count() or 2) - 1)
