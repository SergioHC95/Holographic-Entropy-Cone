"""The single authoritative standard-proof catalogue API.

Only the unified exact reconstruction pipeline is accepted. There are no
archive readers, alternate acceptance formats or compatibility adapters.
"""

from ._proof_frames import CATALOG_FORMAT, DEFAULT_SHARD_BYTES, MAX_RECORD_BYTES
from .reconstruction_store import ReconstructionCatalog as ProofCatalog
from .reconstruction_store import write_proof_dataset
from .reconstruction_store import write_reconstruction_catalog as write_proof_catalog

__all__ = [
    "CATALOG_FORMAT",
    "DEFAULT_SHARD_BYTES",
    "MAX_RECORD_BYTES",
    "ProofCatalog",
    "write_proof_catalog",
    "write_proof_dataset",
]
