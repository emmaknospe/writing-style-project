#!/usr/bin/env python3
"""Classify the raw corpus with Claude and write organized copies into
intermediate/.

Reads every .md file under raw/<visibility>/, asks Claude Haiku to assign a
category, a voice, topic tags, and a cleaned-up display title (see
tagging/taxonomy.py for the vocabularies), then writes the document -- original
frontmatter plus the classification fields -- to

    intermediate/<visibility>/<category>/<filename>

Re-running is cheap: every classification is cached in tagging/.tagcache.json
keyed by the document body, the taxonomy version, and the model, so a re-run
with nothing changed makes zero API calls. Bumping TAXONOMY_VERSION or the
model invalidates the whole cache on purpose.

Files under intermediate/ that this run did not produce are deleted, so a
document that changes category moves rather than existing in both folders.

Usage:
  python tagging/tag.py                        # classify everything, write intermediate/
  python tagging/tag.py --dry-run              # classify, print the distribution, write nothing
  python tagging/tag.py --sample 40 --dry-run  # 40 random docs -- for tuning the taxonomy
  python tagging/tag.py --only 'crec-*'        # just the Congressional Record files
  python tagging/tag.py --force                # ignore the cache and re-classify

Env vars (see .env.example), loaded from .env if present:
  ANTHROPIC_API_KEY (required)
  TAGGER_MODEL (default claude-haiku-4-5)
"""
import argparse
import concurrent.futures
import fnmatch
import hashlib
import json
import logging
import os
import random
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import anthropic

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scrapers"))
from corpus_lib import (
    INTERMEDIATE_DIR,
    RAW_DIR,
    normalize_location,
    read_document,
    write_frontmatter,
)
from taxonomy import (
    CLASSIFY_TOOL,
    SYSTEM_PROMPT,
    TAXONOMY_VERSION,
    UNCLASSIFIED,
    validate,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tag")
# One INFO line per HTTP request is a thousand lines of noise on a full run.
logging.getLogger("httpx").setLevel(logging.WARNING)

MODEL = os.environ.get("TAGGER_MODEL", "claude-haiku-4-5")
CACHE_PATH = Path(__file__).parent / ".tagcache.json"
VISIBILITIES = ("public", "private")

# Long documents are truncated before classification: the form and voice of a
# document are established in its opening and confirmed by its close, and the
# middle costs tokens without changing the answer.
HEAD_WORDS = 1200
TAIL_WORDS = 300

MAX_WORKERS = 8
# One retry, with the validator's complaint fed back. Beyond that the document
# goes to unclassified/ rather than burning more calls on a document the model
# has already failed twice on.
MAX_ATTEMPTS = 2


def truncate(body):
    words = body.split()
    if len(words) <= HEAD_WORDS + TAIL_WORDS:
        return body
    head = " ".join(words[:HEAD_WORDS])
    tail = " ".join(words[-TAIL_WORDS:])
    omitted = len(words) - HEAD_WORDS - TAIL_WORDS
    return f"{head}\n\n[... {omitted} words omitted ...]\n\n{tail}"


def build_prompt(meta, body):
    fields = [
        f"Title: {meta.get('title', '')}",
        f"Date: {meta.get('date', '')}",
        f"Role at the time: {meta.get('role', '')}",
        f"Source: {meta.get('source_name', '')}",
        f"Location: {meta.get('location', '') or '(none given)'}",
        f"Word count: {meta.get('word_count', '')}",
    ]
    if meta.get("notes"):
        fields.append(f"Scraper notes: {meta['notes']}")
    return (
        "Classify this document.\n\n"
        + "\n".join(fields)
        + "\n\n--- BODY ---\n"
        + truncate(body)
    )


def cache_key(body):
    digest = hashlib.sha256(
        f"{TAXONOMY_VERSION}\0{MODEL}\0{body}".encode()
    ).hexdigest()
    return digest


def classify(client, meta, body):
    """Call Claude and return a validated result dict. Raises on repeated
    failure so the caller can route the document to unclassified/."""
    messages = [{"role": "user", "content": build_prompt(meta, body)}]
    problems = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            tools=[CLASSIFY_TOOL],
            tool_choice={"type": "tool", "name": CLASSIFY_TOOL["name"]},
            messages=messages,
        )
        block = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if block is None:
            problems = ["the model returned no tool call"]
        else:
            problems = validate(block.input)
            if not problems:
                return block.input

        if attempt >= MAX_ATTEMPTS:
            break

        # Feed the validator's complaint back rather than retrying blind. A
        # tool_use block must be answered by a tool_result in the very next
        # message, so the complaint rides in as an errored result.
        complaint = (
            "Rejected: " + "; ".join(problems)
            + ". Call classify_document again with valid values."
        )
        if block is None:
            follow_up = {"role": "user", "content": complaint}
        else:
            follow_up = {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "is_error": True,
                    "content": complaint,
                }],
            }
        messages = messages + [
            {"role": "assistant", "content": response.content},
            follow_up,
        ]

    raise ValueError("; ".join(problems))


def load_cache(force):
    if force or not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        logger.warning("Ignoring corrupt %s", CACHE_PATH.name)
        return {}


def load_documents(visibilities, only):
    """Walk raw/ and return [(visibility, filename, meta, body)], applying the
    same skip rules as ingest: no INDEX.md, no duplicates, no empty bodies."""
    docs = []
    for visibility in visibilities:
        root = RAW_DIR / visibility
        if not root.is_dir():
            continue
        for fpath in sorted(root.rglob("*.md")):
            if fpath.name == "INDEX.md":
                continue
            if only and not fnmatch.fnmatch(fpath.name, only):
                continue
            parsed = read_document(fpath)
            if parsed is None:
                logger.warning("SKIP %s: no frontmatter", fpath.name)
                continue
            meta, body = parsed
            if meta.get("duplicate_of"):
                logger.info("SKIP %s: duplicate_of", fpath.name)
                continue
            if not body.strip():
                logger.warning("SKIP %s: empty body", fpath.name)
                continue
            docs.append((visibility, fpath.name, meta, body))
    return docs


def prune(written):
    """Delete intermediate/ files this run didn't write, so a reclassified
    document moves between category folders instead of existing in both."""
    removed = 0
    for visibility in VISIBILITIES:
        root = INTERMEDIATE_DIR / visibility
        if not root.is_dir():
            continue
        for fpath in root.rglob("*.md"):
            if fpath not in written:
                fpath.unlink()
                removed += 1
    # Clean up category folders left empty by the deletions.
    for visibility in VISIBILITIES:
        root = INTERMEDIATE_DIR / visibility
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and not any(child.iterdir()):
                child.rmdir()
    return removed


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Classify and report the distribution; write nothing to disk",
    )
    parser.add_argument(
        "--sample", type=int, metavar="N",
        help="Classify N randomly chosen documents (for tuning the taxonomy)",
    )
    parser.add_argument(
        "--limit", type=int, metavar="N",
        help="Classify only the first N documents",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Ignore cached classifications and re-call the API",
    )
    parser.add_argument(
        "--visibility", choices=[*VISIBILITIES, "all"], default="all",
        help="Which half of raw/ to classify (default: all)",
    )
    parser.add_argument(
        "--only", metavar="GLOB",
        help="Only files whose name matches this glob, e.g. '*crec*'",
    )
    args = parser.parse_args()

    visibilities = (
        VISIBILITIES if args.visibility == "all" else (args.visibility,)
    )
    docs = load_documents(visibilities, args.only)
    if args.sample:
        docs = random.sample(docs, min(args.sample, len(docs)))
    if args.limit:
        docs = docs[: args.limit]
    if not docs:
        logger.info("No documents to classify.")
        return

    # A sample or a glob only ever sees part of the corpus, so pruning would
    # delete everything it didn't look at. Only a full pass may prune.
    partial = bool(args.sample or args.limit or args.only) or (
        args.visibility != "all"
    )

    cache = load_cache(args.force)
    cached_before = len(cache)
    misses = [d for d in docs if cache_key(d[3]) not in cache]
    logger.info(
        "%d document(s); %d cached, %d to classify with %s",
        len(docs), len(docs) - len(misses), len(misses), MODEL,
    )

    failures = []
    if misses:
        client = anthropic.Anthropic()

        def work(doc):
            visibility, fname, meta, body = doc
            try:
                return cache_key(body), classify(client, meta, body), None
            except Exception as exc:
                return cache_key(body), None, f"{fname}: {exc}"

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=MAX_WORKERS
        ) as pool:
            for i, (key, result, error) in enumerate(
                pool.map(work, misses), start=1
            ):
                if error:
                    failures.append(error)
                    logger.warning("FAIL %s", error)
                else:
                    cache[key] = result
                if i % 50 == 0:
                    logger.info("  ... %d/%d", i, len(misses))

    if len(cache) != cached_before and not args.force:
        CACHE_PATH.write_text(json.dumps(cache, indent=1, sort_keys=True))

    categories = Counter()
    voices = Counter()
    low_confidence = []
    written = set()

    for visibility, fname, meta, body in docs:
        result = cache.get(cache_key(body))
        if result is None:
            category = UNCLASSIFIED
            result = {}
        else:
            category = result["category"]
            voices[result["voice"]] += 1
            if result["confidence"] < 0.5:
                low_confidence.append((fname, category, result["confidence"]))
        categories[category] += 1

        if args.dry_run:
            continue

        out = dict(meta)
        out["location"] = normalize_location(meta.get("location"))
        out.update({
            "display_title": result.get("display_title") or meta.get("title"),
            "category": category,
            "voice": result.get("voice"),
            "tags": result.get("tags") or [],
            "classifier": f"{MODEL}/{TAXONOMY_VERSION}",
            "classifier_confidence": result.get("confidence"),
        })
        fpath = INTERMEDIATE_DIR / visibility / category / fname
        write_frontmatter(fpath, out, body)
        written.add(fpath)

    logger.info("\nCategory:")
    for name, count in categories.most_common():
        logger.info("  %-22s %4d", name, count)
    logger.info("Voice:")
    for name, count in voices.most_common():
        logger.info("  %-22s %4d", name, count)

    if low_confidence:
        logger.info("\n%d classification(s) below 0.5 confidence:", len(low_confidence))
        for fname, category, confidence in sorted(
            low_confidence, key=lambda r: r[2]
        )[:15]:
            logger.info("  %.2f  %-22s %s", confidence, category, fname)

    if args.dry_run:
        logger.info("\nDry run: nothing written.")
        return

    if partial:
        logger.info(
            "\nPartial run (--sample/--limit/--only/--visibility): skipping prune."
        )
    else:
        removed = prune(written)
        logger.info("\nPruned %d stale file(s) from intermediate/.", removed)

    logger.info("Wrote %d file(s) to intermediate/.", len(written))
    if failures:
        logger.warning(
            "%d document(s) failed classification and are in %s/: %s",
            len(failures), UNCLASSIFIED, "; ".join(failures[:5]),
        )


if __name__ == "__main__":
    main()
