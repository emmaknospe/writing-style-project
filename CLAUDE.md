# writing-style

Generates event talking-point briefs for Abigail Spanberger, grounded in a RAG
corpus of her speeches and campaign ads plus live web search.

@CLAUDE.local.md

## Architecture

Four pieces, three of them containers (`docker-compose.yml`):

| Piece | What it is |
| --- | --- |
| `frontend/` | React 18 + Vite + TypeScript, served in prod by nginx, which also reverse-proxies `/api/` and `/health` to the api |
| `api/` | FastAPI wrapping a pydantic-ai `Agent` on Claude (Anthropic) |
| `qdrant` | Vector store, `qdrant/qdrant:latest`, named volume for storage |
| `ingest/` | Standalone pipeline run **on the host**, not a container — chunks `data/*.md`, embeds via Gemini on Vertex AI, upserts into Qdrant |

Request path: browser → nginx (`:3000`) → `/api/talking-points` → FastAPI →
pydantic-ai agent → **two** grounding sources in parallel:

- `search_corpus` (a normal client-side tool) → Gemini embedding → Qdrant — what
  she has *already said*. The corpus is a fixed snapshot.
- Anthropic's **server-side** web search (`web_search_20260209`) — what is
  *currently true*. It executes on Anthropic's infrastructure, so there is no
  tool function for it in this repo.

The agent returns a typed `TalkingPointsBrief`, not prose.

The endpoint is **stateless** — one prompt in, one brief out, no conversation
history and so no session store.

### Citations are filtered, not trusted

Both citation kinds are checked against what the tools actually returned before
the brief leaves the API, so the model cannot invent a source URL:

- **Corpus** — `search_corpus` records every `source_url` it returned into
  `BriefDeps`; an `@agent.output_validator` in `api/app/agent.py` drops
  citations pointing anywhere else.
- **Web** — results come back as `NativeToolReturnPart`s in the message history
  (the only place server-side tool output is readable), so the equivalent
  filtering lives in `_drop_unbacked_web_citations` in `api/app/main.py`.

Both log what they drop. A non-zero drop count in the api logs means the prompt
needs tightening, not that the filter is misbehaving.

### Key files

- `api/app/agent.py` — system prompt, the `search_corpus` tool, the `WebSearch`
  capability, and the corpus-citation validator.
- `api/app/schemas.py` — the brief's pydantic models. These double as the agent's
  `output_type`, so their `Field` descriptions are **part of the prompt** — keep
  them consistent with the system prompt when editing either.
- `api/app/main.py` — `/health` and `/api/talking-points`, plus web-citation
  filtering.
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

Briefs cost money per run, and web search is billed **per search** ($10 per 1,000)
on top of tokens. `WEB_SEARCH_MAX_USES` caps that; set it to `0` to iterate on
prompts or the UI using the corpus alone.

`pydantic-ai` is pinned `>=2.31,<3.0` — 2.31 is where web search became a
*capability* (`Agent(capabilities=[WebSearch(...)])`). Older releases used a
`builtin_tools=` parameter that no longer exists, so don't loosen that floor.
