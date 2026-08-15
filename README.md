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

## URLs

- Frontend: http://localhost:3000
- API: http://localhost:8000 (docs at /docs, health at /health)
- Qdrant dashboard: http://localhost:6333/dashboard
