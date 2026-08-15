# writing-style

A RAG chat app over a corpus of Abigail Spanberger's speeches and campaign ads.

@CLAUDE.local.md

## Architecture

Four pieces, three of them containers (`docker-compose.yml`):

| Piece | What it is |
| --- | --- |
| `frontend/` | React 18 + Vite + TypeScript, served in prod by nginx, which also reverse-proxies `/api/` and `/health` to the api |
| `api/` | FastAPI wrapping a pydantic-ai `Agent` on Claude (Anthropic) |
| `qdrant` | Vector store, `qdrant/qdrant:latest`, named volume for storage |
| `ingest/` | Standalone pipeline run **on the host**, not a container — chunks `data/*.md`, embeds via Gemini on Vertex AI, upserts into Qdrant |

Request path: browser → nginx (`:3000`) → `/api/chat` → FastAPI → pydantic-ai agent
→ `search_corpus` tool → Gemini embedding → Qdrant search → Claude answers with
citations.

### Key files

- `api/app/agent.py` — system prompt and the single `search_corpus` tool. The
  prompt tells the model to search before answering anything about Spanberger's
  remarks, and to cite title/speaker/date.
- `api/app/main.py` — `/health` and `/api/chat`. Conversation history lives in the
  in-process `_SESSIONS` dict keyed by `session_id`: single-replica and lost on
  restart, which is called out in a comment there.
- `api/app/config.py` — pydantic-settings `Settings`; every env var the api reads.
- `scraping/corpus_lib.py` — the corpus frontmatter schema and `ROLE_TIMELINE`.
- `ingest/ingest.py` — chunking + upsert; re-running replaces a file's points
  rather than duplicating them.

## Data conventions

`data/` holds the curated corpus: Markdown with YAML frontmatter, filenames
`YYYY-MM-DD-slug.md`, split into `data/speeches/` and `data/ads/`.

Frontmatter keys: `title`, `speaker`, `date` (YYYY-MM-DD), `role`, `location`,
`source_name`, `source_url`, `retrieved_date`, `word_count`, optional `notes` and
`duplicate_of`.

Every field is read off the source page or mechanically derived — `role` from the
date via `ROLE_TIMELINE`, `word_count` from the body, `duplicate_of` from
exact-body-match detection. **Don't add keyword-guessed classification fields.**

`scraping/` is the raw scrape output (`scrape_awpc.py`, `scrape_governor_va.py`)
and is a superset of `data/` — `data/` is the hand-curated subset that actually
gets ingested.

## Working on this

Run everything through compose; see the local notes above for the exact commands on
this machine. Ports: frontend `3000`, api `8000`, Qdrant `6333`/`6334`.

The `api` service reads secrets from `.env` via compose; never hardcode a key or
project id into `api/app/config.py` or the compose file. New config goes in
`Settings` with a default, gets passed through in `docker-compose.yml`, and is
documented in `.env.example`.

After changing anything under `data/`, re-run ingest so Qdrant matches the corpus.
`python ingest/ingest.py --dry-run` parses and chunks without embedding or writing —
use it to sanity-check frontmatter changes cheaply, since embedding calls cost money.
