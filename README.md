# writing-style chat

A chat app: React frontend, FastAPI backend running a pydantic-ai agent (Claude via Anthropic), with Qdrant running alongside as a vector store, populated by a standalone ingest pipeline (see `ingest/`).

## Setup

```sh
cp .env.example .env
# edit .env and set a real ANTHROPIC_API_KEY
docker compose up --build
```

## Ingest the corpus into Qdrant

`data/` holds the curated speech/communication corpus as Markdown files with
YAML frontmatter (see `scraping/corpus_lib.py` for the schema). `ingest/`
chunks each file's body and embeds it with a Gemini embedding model via
Vertex AI, then upserts the vectors into Qdrant.

```sh
docker compose up -d qdrant
pip install -r ingest/requirements.txt
gcloud auth application-default login   # once, for Vertex AI ADC auth
python ingest/ingest.py --dry-run       # parse/chunk data/*.md only, no embedding/writes -- sanity check
python ingest/ingest.py                 # embed and upsert into Qdrant
```

Requires `GOOGLE_CLOUD_PROJECT` set (in `.env` or exported) for ADC to know
which GCP project to authorize against. Re-running is safe — each file's
points are replaced, not duplicated.

## Scraping the corpus

`scraping/` holds the scrapers that build the raw corpus in
`scraping/speeches/` (curated files are promoted into `data/` by hand):

```sh
python scraping/scrape_awpc.py                  # Catt Center AWPC directory (2018 + 2025 campaign ads, speeches)
python scraping/scrape_governor_va.py           # governor.virginia.gov press releases (Jan 2026-present)
python scraping/scrape_campaign_site.py         # abigailspanberger.com WP REST API (Nov 2023-present)
python scraping/scrape_congressional_record.py  # her floor speeches/statements in the Congressional Record (2019-2024)
python scraping/build_index.py                  # regenerate scraping/speeches/INDEX.md
```

Campaign-site posts are tagged by category in `notes` — the `news` ones are
reposted third-party coverage, not her own words. Congressional Record files
contain only her extracted speaking blocks; `notes` says whether each is
floor remarks or a written Extension of Remarks.

## URLs

- Frontend: http://localhost:3000
- API: http://localhost:8000 (docs at /docs, health at /health)
- Qdrant dashboard: http://localhost:6333/dashboard
