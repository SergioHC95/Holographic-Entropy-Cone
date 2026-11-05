"""Measured scheduling hints; mathematical acceptance never depends on costs.

Each segment gives an exclusive row stop and elapsed milliseconds for that
batch in a completed CI audit. Integer interpolation balances contiguous work
without downloading every payload on every worker. A changed ray index drops
these hints and uses equal row ranges; all actual rank checks still execute.
"""

import hashlib
import json
from bisect import bisect_left
from functools import lru_cache
from pathlib import Path

_PROFILE = Path(__file__).with_name("_ci_ray_costs.json")


def _validate_segments(length, segments):
    previous = 0
    for stop, cost in segments:
        if type(stop) is not int or not previous < stop <= length or type(cost) is not int or cost < 1:
            raise ValueError("invalid CI scheduling cost segment")
        previous = stop
    if previous != length or not segments:
        raise ValueError("incomplete CI scheduling cost coverage")


@lru_cache(maxsize=4)
def _read_profile(path):
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile["format"] != "hec-ci-ray-costs-v1":
        raise ValueError("unsupported CI scheduling cost profile")
    segments = tuple(tuple(entry) for entry in profile["segments"])
    _validate_segments(profile["rows"], segments)
    return profile["rows"], profile["ray_catalog_sha256"], segments


def ray_costs(path, length):
    """Use timing hints only for the exact ordered source ray index."""
    count, digest, segments = _read_profile(_PROFILE)
    if count != length or hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
        return None
    return segments


@lru_cache(maxsize=16)
def balanced_boundaries(length, groups, segments):
    """Near-equal estimated work, monotone nonempty ranges when groups <= rows.

    Costs are scheduling estimates, not saved mathematical results. Boundaries
    use exact integer arithmetic, deterministic ties and at most one-row
    rounding. Missing timings fall back to ordinary equal row partitions.
    """
    if type(length) is not int or length < 0 or type(groups) is not int or groups < 1:
        raise ValueError("invalid balanced row partition size")
    if segments is None:
        return tuple(length * index // groups for index in range(groups + 1))
    _validate_segments(length, segments)
    cumulative = []
    total = 0
    for _, cost in segments:
        total += cost
        cumulative.append(total)
    boundaries = [0]
    for group in range(1, groups):
        # Locate this equal-work quantile in a measured batch, then interpolate
        # to a row. This never samples or reuses any mathematical acceptance.
        target = total * group
        index = bisect_left(cumulative, (target + groups - 1) // groups)
        start = segments[index - 1][0] if index else 0
        before = cumulative[index - 1] if index else 0
        stop, cost = segments[index]
        numerator = (target - before * groups) * (stop - start)
        denominator = cost * groups
        boundary = start + (numerator + denominator // 2) // denominator
        minimum = boundaries[-1] + (groups <= length)
        maximum = length - (groups - group) if groups <= length else length
        boundaries.append(min(maximum, max(minimum, boundary)))
    return (*boundaries, length)
