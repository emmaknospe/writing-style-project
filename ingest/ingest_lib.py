"""Shared helpers for the ingest pipeline: chunking speech bodies for
embedding and deriving stable per-chunk Qdrant point IDs.

Frontmatter parsing lives in scrapers/corpus_lib.py, which is the single home
for the corpus file format; it is re-exported here so ingest code can import
everything it needs from one place.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scrapers"))
from corpus_lib import INTERMEDIATE_DIR, parse_frontmatter  # noqa: F401

# Arbitrary fixed namespace so point IDs are stable across runs (same
# file + chunk index always hashes to the same UUID) -- lets re-ingesting
# a file overwrite its old points instead of duplicating them.
_POINT_NAMESPACE = uuid.UUID("d4a1f6ee-6b1d-4c9a-9c2b-2a6b6f9c9a10")


def chunk_body(body, max_words=220, overlap_words=40):
    """Split body into overlapping word-window chunks. Doesn't respect
    sentence/paragraph boundaries -- good enough for embedding similarity,
    not meant for display."""
    words = body.split()
    if len(words) <= max_words:
        return [body.strip()] if body.strip() else []

    chunks = []
    step = max_words - overlap_words
    start = 0
    while start < len(words):
        end = start + max_words
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += step
    return chunks


def point_id(relpath, chunk_index):
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{relpath}:{chunk_index}"))
