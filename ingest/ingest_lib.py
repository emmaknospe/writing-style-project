"""Shared helpers for the ingest pipeline: parsing the corpus_lib.py
frontmatter format, chunking speech bodies for embedding, and deriving
stable per-chunk Qdrant point IDs.
"""
import uuid
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

# Arbitrary fixed namespace so point IDs are stable across runs (same
# file + chunk index always hashes to the same UUID) -- lets re-ingesting
# a file overwrite its old points instead of duplicating them.
_POINT_NAMESPACE = uuid.UUID("d4a1f6ee-6b1d-4c9a-9c2b-2a6b6f9c9a10")


def parse_frontmatter(text):
    """Parse the JSON-scalar YAML frontmatter written by
    scraping/corpus_lib.py. Returns (meta_dict, body) or None if the file
    has no frontmatter block."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    block = text[4:end]
    body = text[end + 5:]
    meta = {}
    for line in block.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()
        try:
            meta[key] = json.loads(raw_value)
        except json.JSONDecodeError:
            meta[key] = raw_value
    return meta, body.strip()


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
