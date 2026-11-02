"""Bounded, content-addressed selection of software regression controls."""

import hashlib
import json


def ray_fingerprint(row):
    return hashlib.sha256(json.dumps(list(row), separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def select_rays(rows, fingerprints, *, unique=False):
    """Retain requested controls only; optional uniqueness checks read the tail."""
    wanted = set(fingerprints)
    found = {}
    if not wanted:
        return found
    for index, row in enumerate(rows):
        identity = ray_fingerprint(row)
        if identity not in wanted:
            continue
        if identity in found:
            raise ValueError(f"duplicate selected ray: {identity}")
        found[identity] = (index, tuple(row))
        if not unique and len(found) == len(wanted):
            break
    missing = wanted - found.keys()
    if missing:
        raise ValueError(f"missing selected rays: {sorted(missing)}")
    return found
