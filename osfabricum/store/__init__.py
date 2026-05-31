"""Content-addressed artifact store (M3)."""

from osfabricum.store.ingest import ingest_blob
from osfabricum.store.verify import verify_store

__all__ = ["ingest_blob", "verify_store"]
