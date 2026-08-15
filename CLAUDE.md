# writing-style

A RAG chat app over a corpus of Abigail Spanberger's public communications.

@CLAUDE.local.md

## Architecture

Five pieces, three of them containers (`docker-compose.yml`):

| Piece | What it is |
| --- | --- |
| `frontend/` | React 18 + Vite + TypeScript, served in prod by nginx, which also reverse-proxies `/api/` and `/health` to the api |
| `api/` | FastAPI wrapping a pydantic-ai `Agent` on Claude (Anthropic) |
| `qdrant` | Vector store, `qdrant/qdrant:latest`, named volume for storage |
| `tagging/` | Standalone pipeline run **on the host** — classifies `raw/**/*.md` with Claude Haiku and writes organized copies into `intermediate/` |
| `ingest/` | Standalone pipeline run **on the host** — chunks `intermediate/**/*.md`, embeds via Gemini on Vertex AI, upserts into Qdrant |

Request path: browser → nginx (`:3000`) → `/api/chat` → FastAPI → pydantic-ai agent
→ `search_corpus` tool → Gemini embedding → Qdrant search → Claude answers with
citations.

Corpus path: scrapers → `raw/` → `tagging/tag.py` → `intermediate/` →
`ingest/ingest.py` → Qdrant.

### Key files

- `api/app/agent.py` — system prompt and the single `search_corpus` tool. The
  prompt tells the model to search before answering anything about Spanberger's
  remarks, to cite title/speaker/date, and to weigh passages by their `voice`.
- `api/app/main.py` — `/health` and `/api/chat`. Conversation history lives in the
  in-process `_SESSIONS` dict keyed by `session_id`: single-replica and lost on
  restart, which is called out in a comment there.
- `api/app/config.py` — pydantic-settings `Settings`; every env var the api reads.
- `scrapers/corpus_lib.py` — the single home for frontmatter I/O
  (`parse_frontmatter` / `write_frontmatter`), the schema, and `ROLE_TIMELINE`.
- `tagging/taxonomy.py` — the closed category/voice/tag vocabularies, the
  classification prompt, and `TAXONOMY_VERSION`.
- `ingest/ingest.py` — chunking + upsert; re-running replaces a file's points
  rather than duplicating them.

## Data conventions

The corpus moves through two stages, both Markdown with frontmatter and
filenames `YYYY-MM-DD-slug.md`:

- `raw/{public,private}/` — exactly what the scrapers pulled, flat. `private/`
  is gitignored and currently empty; it exists so non-redistributable material
  can be added without restructuring.
- `intermediate/{public,private}/<category>/` — the classified copies that
  ingest actually reads. The category is a directory name.

Source frontmatter keys, written by the scrapers: `title`, `speaker`, `date`
(YYYY-MM-DD), `role`, `location`, `source_name`, `source_url`, `retrieved_date`,
`word_count`, optional `notes` and `duplicate_of`. Every one is read off the
source page or mechanically derived — `role` from the date via `ROLE_TIMELINE`,
`word_count` from the body, `duplicate_of` from exact-body-match detection.

Classification keys, added by `tagging/tag.py`: `display_title`, `category`,
`voice`, `tags`, `classifier`, `classifier_confidence`.

**Neither stage uses keyword heuristics.** Scrapers derive only what the source
states; classification is an explicit, versioned LLM stage, and `classifier`
records the model and taxonomy version so any label can be traced and
invalidated. Don't add hand-written classification fields to either stage — add
to the taxonomy and re-tag instead.

`scrapers/` holds only the scraper scripts; their output is `raw/public/`.

## Working on this

Run everything through compose; see the local notes above for the exact commands on
this machine. Ports: frontend `3000`, api `8000`, Qdrant `6333`/`6334`.

The `api` service reads secrets from `.env` via compose; never hardcode a key or
project id into `api/app/config.py` or the compose file. New config goes in
`Settings` with a default, gets passed through in `docker-compose.yml`, and is
documented in `.env.example`.

After changing anything under `raw/`, re-run `python tagging/tag.py` and then
`python ingest/ingest.py` so Qdrant matches the corpus. Both stages have a
`--dry-run` that skips the paid API calls; use them to sanity-check changes
cheaply. Tagging results are cached in `tagging/.tagcache.json`, so a re-run
after an unrelated edit costs nothing.

**Point IDs are derived from a document's path under `intermediate/`.** So when
a file moves — most often because the classifier changed its mind about the
category — its old vectors are not overwritten and survive as duplicates.
`ingest/ingest.py --prune` deletes points whose `source_file` no longer exists
and is the standing fix; `--recreate` drops and rebuilds the collection and is
the right move after any wholesale reorganization.
