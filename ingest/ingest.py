#!/usr/bin/env python3
"""Embed the classified corpus in intermediate/ into the project's Qdrant collection.

Reads every .md file under intermediate/ (frontmatter + Markdown body -- see
scrapers/corpus_lib.py for the schema), splits the body into overlapping
word-window chunks, embeds each chunk with a Gemini embedding model via Vertex
AI (auth: Application Default Credentials -- run
`gcloud auth application-default login` once, or set
GOOGLE_APPLICATION_CREDENTIALS to a service-account key), and upserts the
vectors into Qdrant with the document metadata + chunk text as payload.

Layout: intermediate/<visibility>/<category>/<file>.md, written by
tagging/tag.py. Both path segments land in the payload, so answers can be
filtered by either.

Re-running is safe: each file's existing points are deleted (matched by
`source_file` in the payload) and replaced. But a file that *moves* -- because
the classifier changed its mind about the category -- keeps its old points
under the old path, since nothing matches them any more. Use --prune to drop
points whose source_file no longer exists, or --recreate to start clean.

Usage:
  python ingest/ingest.py                      # embed + upsert everything under intermediate/
  python ingest/ingest.py --dry-run            # parse/chunk only, print stats, skip embedding+Qdrant
  python ingest/ingest.py --recreate           # drop and rebuild the collection first
  python ingest/ingest.py --prune              # also delete points for files that no longer exist
  python ingest/ingest.py --glob 'public/speech/*.md'   # only matching files, for iterating

Env vars (see .env.example), loaded from .env if present:
  QDRANT_URL (default http://localhost:6333 -- ingest runs on the host,
    against the port docker-compose maps out, not the in-network hostname
    the api container uses)
  QDRANT_COLLECTION_NAME, QDRANT_VECTOR_SIZE
  GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, GEMINI_EMBEDDING_MODEL
"""
import argparse
import concurrent.futures
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
from ingest_lib import INTERMEDIATE_DIR, parse_frontmatter, chunk_body, point_id
from embeddings import build_client, embed_text

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("ingest")
# One INFO line per Qdrant request buries the per-document output.
logging.getLogger("httpx").setLevel(logging.WARNING)

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION_NAME", "writing_style")
QDRANT_VECTOR_SIZE = int(os.environ.get("QDRANT_VECTOR_SIZE", "1536"))

PAYLOAD_META_KEYS = [
    "title", "display_title", "speaker", "date", "role", "category", "voice",
    "location", "source_name", "source_url", "retrieved_date", "word_count",
    "tags", "classifier", "classifier_confidence",
]

# Third-party reporting reposted onto the campaign site. It is about her, not
# by her, so it is the wrong thing to retrieve when the question is how she
# writes or what she said. Override with --include-category.
DEFAULT_EXCLUDED_CATEGORIES = ("media-coverage", "unclassified")

# Vertex embeds one chunk per request, so the wall-clock cost is entirely
# round-trips; a modest pool turns hours into minutes.
MAX_WORKERS = 8


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


def recreate_collection(client):
    if client.collection_exists(QDRANT_COLLECTION_NAME):
        client.delete_collection(collection_name=QDRANT_COLLECTION_NAME)
        logger.info("Dropped Qdrant collection %r", QDRANT_COLLECTION_NAME)
    ensure_collection(client)


def load_documents(pattern, excluded, included):
    docs = []
    for fpath in sorted(INTERMEDIATE_DIR.rglob(pattern)):
        if not fpath.is_file() or fpath.name == "INDEX.md":
            continue
        relpath = fpath.relative_to(INTERMEDIATE_DIR)
        parts = relpath.parts
        if len(parts) < 3:
            logger.warning("SKIP %s: not under <visibility>/<category>/", relpath)
            continue
        visibility, category = parts[0], parts[1]
        if included and category not in included:
            continue
        if not included and category in excluded:
            continue

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
        docs.append((str(relpath), visibility, meta, body))
    return docs


def prune_collection(client, live_files):
    """Delete points whose source_file is not among the documents just
    ingested -- the standing fix for a document moving between categories."""
    stale = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=QDRANT_COLLECTION_NAME,
            limit=1000,
            offset=offset,
            with_payload=["source_file"],
            with_vectors=False,
        )
        for point in points:
            source_file = (point.payload or {}).get("source_file")
            if source_file and source_file not in live_files:
                stale.add(source_file)
        if offset is None:
            break

    for source_file in sorted(stale):
        client.delete(
            collection_name=QDRANT_COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="source_file", match=MatchValue(value=source_file)
                    )
                ]
            ),
        )
        logger.info("PRUNE %s", source_file)
    return len(stale)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--glob", default="**/*.md",
        help="Only ingest files under intermediate/ matching this glob, relative "
             "to intermediate/ (default: **/*.md, i.e. everything recursively)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse and chunk only; skip embedding and Qdrant writes",
    )
    parser.add_argument(
        "--recreate", action="store_true",
        help="Drop and recreate the collection before ingesting. Needed after "
             "any reorganization that changes file paths, since point IDs are "
             "derived from them",
    )
    parser.add_argument(
        "--prune", action="store_true",
        help="After ingesting, delete points whose source_file is no longer in "
             "intermediate/ (e.g. a document that changed category)",
    )
    parser.add_argument(
        "--exclude-category", action="append", metavar="NAME",
        help=f"Category to skip; repeatable. Default: "
             f"{', '.join(DEFAULT_EXCLUDED_CATEGORIES)}",
    )
    parser.add_argument(
        "--include-category", action="append", metavar="NAME",
        help="Only ingest these categories; repeatable. Overrides --exclude-category",
    )
    args = parser.parse_args()

    excluded = set(args.exclude_category or DEFAULT_EXCLUDED_CATEGORIES)
    included = set(args.include_category or ())

    docs = load_documents(args.glob, excluded, included)
    if not docs:
        logger.info("No documents to ingest.")
        return

    qdrant = None
    genai_client = None
    if not args.dry_run:
        qdrant = QdrantClient(url=QDRANT_URL)
        if args.recreate:
            recreate_collection(qdrant)
        else:
            ensure_collection(qdrant)
        genai_client = build_client()

    def embed(chunk):
        return embed_text(
            genai_client, chunk, output_dimensionality=QDRANT_VECTOR_SIZE
        )

    total_chunks = 0
    # One pool for the whole run: Vertex embeds one chunk per request, so most
    # documents are too small to saturate a pool of their own.
    pool = (
        None if args.dry_run
        else concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    )
    try:
        for fname, visibility, meta, body in docs:
            chunks = chunk_body(body)
            total_chunks += len(chunks)
            logger.info(
                "%s: %d word(s) -> %d chunk(s)", fname, len(body.split()), len(chunks)
            )

            if args.dry_run:
                continue

            vectors = list(pool.map(embed, chunks))

            points = []
            for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
                payload = {k: meta.get(k) for k in PAYLOAD_META_KEYS}
                payload.update({
                    "source_file": fname,
                    "visibility": visibility,
                    "chunk_index": i,
                    "chunk_count": len(chunks),
                    "text": chunk,
                })
                points.append(
                    PointStruct(
                        id=point_id(fname, i), vector=vector, payload=payload
                    )
                )

            qdrant.delete(
                collection_name=QDRANT_COLLECTION_NAME,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="source_file", match=MatchValue(value=fname)
                        )
                    ]
                ),
            )
            qdrant.upsert(collection_name=QDRANT_COLLECTION_NAME, points=points)
    finally:
        if pool is not None:
            pool.shutdown()

    logger.info(
        "\nDone. %d document(s), %d chunk(s) %s.",
        len(docs), total_chunks,
        "would be embedded (dry run)" if args.dry_run else "embedded and upserted",
    )

    if args.prune and not args.dry_run:
        # Pruning deletes every point this run didn't (re)ingest, so it is only
        # meaningful when the run covered the whole corpus. Narrowing to a glob
        # or a category allowlist would wipe everything outside it. Widening the
        # exclusions is allowed: dropping an excluded category's points is what
        # excluding it means.
        if args.glob != "**/*.md" or included:
            logger.warning(
                "Refusing to --prune after a --glob/--include-category run: it "
                "would delete points for every document those filters skipped."
            )
        else:
            removed = prune_collection(qdrant, {d[0] for d in docs})
            logger.info("Pruned %d stale source_file(s).", removed)


if __name__ == "__main__":
    main()
