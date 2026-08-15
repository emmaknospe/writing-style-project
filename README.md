# writing-style chat

A chat app: React frontend, FastAPI backend running a pydantic-ai agent (Claude via Anthropic), with Qdrant running alongside as a vector store, populated by a standalone ingest pipeline (see `ingest/`).

## Setup

```sh
cp .env.example .env
# edit .env and set a real ANTHROPIC_API_KEY
docker compose up --build
```

## The corpus pipeline

The corpus moves through three stages, all Markdown with frontmatter (see
`scrapers/corpus_lib.py` for the schema):

| Stage | Directory | Produced by |
| --- | --- | --- |
| raw | `raw/{public,private}/` | the scrapers |
| classified | `intermediate/{public,private}/<category>/` | `tagging/tag.py` |
| vectors | Qdrant | `ingest/ingest.py` |

`raw/private/` is gitignored and empty; it exists so non-redistributable
material can be added later without restructuring.

### 1. Classify

`tagging/tag.py` asks Claude Haiku to assign each document a category (which
becomes its directory), a `voice` (whether the words are actually hers), topic
tags, and a cleaned-up title, then writes the classified copy into
`intermediate/`.

```sh
pip install -r tagging/requirements.txt
python tagging/tag.py --sample 40 --dry-run   # classify 40 random docs, print the distribution
python tagging/tag.py                         # classify everything, write intermediate/
```

Results are cached in `tagging/.tagcache.json` keyed by document body, model,
and taxonomy version, so re-runs are free unless something actually changed.
Editing `tagging/taxonomy.py` should come with a `TAXONOMY_VERSION` bump, which
deliberately invalidates the whole cache.

### 2. Ingest into Qdrant

`ingest/` chunks each classified file's body, embeds it with a Gemini embedding
model via Vertex AI, and upserts the vectors into Qdrant.

```sh
docker compose up -d qdrant
pip install -r ingest/requirements.txt
gcloud auth application-default login   # once, for Vertex AI ADC auth
python ingest/ingest.py --dry-run       # parse/chunk only, no embedding/writes -- sanity check
python ingest/ingest.py                 # embed and upsert into Qdrant
python ingest/ingest.py --prune         # also drop points for files that no longer exist
```

Requires `GOOGLE_CLOUD_PROJECT` set (in `.env` or exported) for ADC to know
which GCP project to authorize against. Re-running is safe — each file's points
are replaced, not duplicated. But point IDs are derived from a document's path,
so a document that *moves* between categories leaves its old vectors behind:
use `--prune` to clean those up, or `--recreate` to rebuild from scratch.

`media-coverage` (third-party reporting reposted onto the campaign site, not her
words) is excluded from ingest by default; see `--include-category`.

## Scraping the corpus

`scrapers/` holds the scrapers that build the raw corpus in `raw/public/`:

```sh
python scrapers/scrape_awpc.py                  # Catt Center AWPC directory (2018 + 2025 campaign ads, speeches)
python scrapers/scrape_governor_va.py           # governor.virginia.gov press releases (Jan 2026-present)
python scrapers/scrape_campaign_site.py         # abigailspanberger.com WP REST API (Nov 2023-present)
python scrapers/scrape_congressional_record.py  # her floor speeches/statements in the Congressional Record (2019-2024)
python scrapers/build_index.py                  # regenerate raw/public/INDEX.md
```

Campaign-site posts are tagged by category in `notes` — the `news` ones are
reposted third-party coverage, not her own words. Congressional Record files
contain only her extracted speaking blocks; `notes` says whether each is
floor remarks or a written Extension of Remarks.

## URLs

- Frontend: http://localhost:3000
- API: http://localhost:8000 (docs at /docs, health at /health)
- Qdrant dashboard: http://localhost:6333/dashboard
