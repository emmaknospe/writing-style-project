#!/usr/bin/env python3
"""Embed the corpus in data/ into the project's Qdrant collection.

Reads every .md file in data/ (YAML/JSON-scalar frontmatter + Markdown
body -- see scraping/corpus_lib.py for the schema), splits the body into
overlapping word-window chunks, embeds each chunk with a Gemini embedding
model via Vertex AI (auth: Application Default Credentials -- run
`gcloud auth application-default login` once, or set
GOOGLE_APPLICATION_CREDENTIALS to a service-account key), and upserts the
vectors into Qdrant with the speech metadata + chunk text as payload.

Re-running is safe: each file's existing points are deleted (matched by
`source_file` in the payload) and replaced, so edits/re-ingests don't
accumulate stale or duplicate vectors.

Usage:
  python ingest/ingest.py                        # embed + upsert everything under data/ (recursive)
  python ingest/ingest.py --dry-run              # parse/chunk only, print stats, skip embedding+Qdrant
  python ingest/ingest.py --glob 'speeches/*.md' # only matching files, for iterating

Env vars (see .env.example), loaded from .env if present:
  QDRANT_URL (default http://localhost:6333 -- ingest runs on the host,
    against the port docker-compose maps out, not the in-network hostname
    the api container uses)
  QDRANT_COLLECTION_NAME, QDRANT_VECTOR_SIZE
  GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, GEMINI_EMBEDDING_MODEL
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)

sys.path.insert(0, str(Path(__file__).parent))
from ingest_lib import DATA_DIR, parse_frontmatter, chunk_body, point_id
from embeddings import build_client, embed_text

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("ingest")

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION_NAME", "writing_style")
QDRANT_VECTOR_SIZE = int(os.environ.get("QDRANT_VECTOR_SIZE", "1536"))

PAYLOAD_META_KEYS = [
    "title", "speaker", "date", "role", "speech_type", "location",
    "source_name", "source_url", "retrieved_date", "word_count", "tags",
]


def ensure_collection(client, max_retries=10, retry_delay_seconds=2.0):
    for attempt in range(1, max_retries + 1):
        try:
            if not client.collection_exists(QDRANT_COLLECTION_NAME):
                client.create_collection(
                    collection_name=QDRANT_COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=QDRANT_VECTOR_SIZE, distance=Distance.COSINE
                    ),
                )
                logger.info("Created Qdrant collection %r", QDRANT_COLLECTION_NAME)
            return
        except Exception as exc:
            logger.warning(
                "Qdrant not ready (attempt %d/%d): %s", attempt, max_retries, exc
            )
            if attempt == max_retries:
                raise
            time.sleep(retry_delay_seconds)


def load_documents(pattern):
    docs = []
    for fpath in sorted(DATA_DIR.rglob(pattern)):
        if not fpath.is_file() or fpath.name == "INDEX.md":
            continue
        relpath = str(fpath.relative_to(DATA_DIR))
        parsed = parse_frontmatter(fpath.read_text())
        if parsed is None:
            logger.warning("SKIP %s: no frontmatter", relpath)
            continue
        meta, body = parsed
        if meta.get("duplicate_of"):
            logger.info("SKIP %s: duplicate_of=%s", relpath, meta["duplicate_of"])
            continue
        if not body.strip():
            logger.warning("SKIP %s: empty body", relpath)
            continue
        docs.append((relpath, meta, body))
    return docs


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--glob", default="**/*.md",
        help="Only ingest files under data/ matching this glob, relative to "
             "data/ (default: **/*.md, i.e. everything recursively)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse and chunk only; skip embedding and Qdrant writes",
    )
    args = parser.parse_args()

    docs = load_documents(args.glob)
    if not docs:
        logger.info("No documents to ingest.")
        return

    qdrant = None
    genai_client = None
    if not args.dry_run:
        qdrant = QdrantClient(url=QDRANT_URL)
        ensure_collection(qdrant)
        genai_client = build_client()

    total_chunks = 0
    for fname, meta, body in docs:
        chunks = chunk_body(body)
        total_chunks += len(chunks)
        logger.info("%s: %d word(s) -> %d chunk(s)", fname, len(body.split()), len(chunks))

        if args.dry_run:
            continue

        points = []
        for i, chunk in enumerate(chunks):
            vector = embed_text(genai_client, chunk, output_dimensionality=QDRANT_VECTOR_SIZE)
            payload = {k: meta.get(k) for k in PAYLOAD_META_KEYS}
            payload.update({
                "source_file": fname,
                "chunk_index": i,
                "chunk_count": len(chunks),
                "text": chunk,
            })
            points.append(PointStruct(id=point_id(fname, i), vector=vector, payload=payload))

        qdrant.delete(
            collection_name=QDRANT_COLLECTION_NAME,
            points_selector=Filter(
                must=[FieldCondition(key="source_file", match=MatchValue(value=fname))]
            ),
        )
        qdrant.upsert(collection_name=QDRANT_COLLECTION_NAME, points=points)

    logger.info(
        "\nDone. %d document(s), %d chunk(s) %s.",
        len(docs), total_chunks,
        "would be embedded (dry run)" if args.dry_run else "embedded and upserted",
    )


if __name__ == "__main__":
    main()
