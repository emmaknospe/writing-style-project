# writing-style

Drafts speeches in Abigail Spanberger's voice from a corpus of her public
communications, and generates event talking-point briefs grounded in that
corpus plus live web search.

@CLAUDE.local.md

## Architecture

Five pieces, three of them containers (`docker-compose.yml`):

| Piece | What it is |
| --- | --- |
| `frontend/` | React 18 + Vite + TypeScript, served in prod by nginx, which also reverse-proxies `/api/` and `/health` to the api |
| `api/` | FastAPI wrapping pydantic-ai `Agent`s on Claude (Anthropic), plus the app database (SQLite via `aiosqlite`, Alembic migrations run on boot) |
| `qdrant` | Vector store, `qdrant/qdrant:latest`, named volume for storage |
| `tagging/` | Standalone pipeline run **on the host** — classifies `raw/**/*.md` with Claude Haiku and writes organized copies into `intermediate/` |
| `ingest/` | Standalone pipeline run **on the host** — chunks `intermediate/**/*.md`, embeds via Gemini on Vertex AI, upserts into Qdrant |

Two grounding sources, deliberately split:

- `search_corpus` (a normal client-side tool) → Gemini embedding → Qdrant — what
  she has *already said*. The corpus is a fixed snapshot.
- Anthropic's **server-side** web search (`web_search_20260209`) — what is
  *currently true*. It executes on Anthropic's infrastructure, so there is no
  tool function for it in this repo.

### A brief is a speech

Talking-point briefs reuse the speech tables rather than paralleling them:

| Brief concept | Storage |
| --- | --- |
| the brief | a `speeches` row, plus a `briefs` row for what that table can't hold |
| a talking point | a `sections` row (`heading`, `text`, `intent` = rationale) |
| a corpus citation | a `section_sources` row, pinned to a `qdrant_point_id` |
| a web citation | a `section_web_sources` row |

So outline editing needs no bespoke endpoints — the ordinary
`PATCH /api/sections/{id}`, `DELETE`, append and reorder routes in
`routers/speeches.py` do it, and a finished brief is already a speech with
sourced sections.

### The approval gate

`briefs.status` runs `researching → outline_proposed → drafting → ready`,
returning to `drafting` on each revision. Two agents enforce it:

- `outline_agent` researches and proposes an outline. Its output type has no
  field capable of holding a talking point, so it **cannot** skip ahead — the
  gate holds even if the prompt is ignored.
- `draft_agent` writes prose over the outline *as the user left it*, replaying
  the outline run's `agent_messages` so the research isn't repeated.

Prose is only ever written in the `drafting` transition.

### Citations are verified, not trusted

The model supplies a **Qdrant point id and a quote** — never bibliographic
metadata. `verify_corpus_citations` in `api/app/agent.py` resolves the id via
`vector_store.get_by_ids()`, checks the quote word-for-word with
`app/quotes.py`, and fills title/speaker/date/url **from the stored payload**.
So a real passage cannot be misattributed to the wrong speech or date.

Web results are only readable as `NativeToolReturnPart`s in the message history,
so web citations are filtered against the URLs a search actually returned
(`_searched_web_urls` in `routers/briefs.py`).

Both log what they drop. A non-zero drop count means the prompt needs
tightening, not that the filter is misbehaving.

### Streaming

The two agent-running endpoints stream SSE over **POST** (`EventSource` is
GET-only, so the frontend reads the body with `fetch` + `ReadableStream`).
Events: `activity`, `outline`, `brief`, `error`, `done`.

Two things are easy to get wrong here:

- **nginx buffers proxied responses by default.** `proxy_buffering off` is set
  in `frontend/nginx.conf`; without it the feed works against `:8000` and
  silently arrives in one lump through `:3000`.
- A web-search **call**'s arguments stream in as JSON deltas, so the query is
  only complete at `PartEndEvent`; a **result** block arrives whole and is read
  at `PartStartEvent`. Matching each on one event kind avoids duplicate lines.

Corpus path: scrapers → `raw/` → `tagging/tag.py` → `intermediate/` →
`ingest/ingest.py` → Qdrant.

### Key files

- `api/app/agent.py` — the two agents, the `search_corpus` tool, the `WebSearch`
  capability, and `verify_corpus_citations`.
- `api/app/agent_outputs.py` — LLM output contracts. Every `Field` description
  is **prompt surface** the model reads; keep them consistent with the system
  prompts when editing either.
- `api/app/routers/briefs.py` — brief endpoints, the SSE event mapping, and
  persistence of outlines and drafts.
- `api/app/schemas.py` — wire DTOs (main's speech/voice-profile models plus the
  brief ones). Distinct from `agent_outputs.py` on purpose.
- `api/app/models.py` / `api/migrations/` — the app database.
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

- `raw/public/` — exactly what the scrapers pulled, flat.
- `raw/private/` — synthetic internal documents, grouped in subfolders by kind
  (`fact_sheets/`, `briefing_memos/`, `background/`, `synthetic_people/`).
  Committed and reviewed like the public half; `tag.py` recurses, and the
  subfolders disappear at the `intermediate/` stage anyway, which is organized
  by category.
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

### Synthetic material

Everything under `raw/private/` is **synthetic** — staff-style documents written
to look like a governor's office's working material. The content is grounded in
the real record in `raw/public/`, but these are not real records and not
Spanberger's words. They classify as `category: internal-document` and
`voice: third-party`.

They must stay identifiable from metadata alone: `chunk_body` splits on a
220-word window, so a document's in-body disclaimer only reaches its first
chunk, while `_format_hit` labels every chunk. So keep the `[SYNTHETIC] ` title
prefix, keep `speaker` set to the synthetic authoring office rather than
`Abigail Spanberger`, and keep the disclaimer in `notes`.

## Working on this

Run everything through compose; see the local notes above for the exact commands on
this machine. Ports: frontend `3000`, api `8000`, Qdrant `6333`/`6334`.

The `api` service reads secrets from `.env` via compose; never hardcode a key or
project id into `api/app/config.py` or the compose file. New config goes in
`Settings` with a default, gets passed through in `docker-compose.yml`, and is
documented in `.env.example`.

Briefs cost money per run, and web search is billed **per search** ($10 per 1,000)
on top of tokens. `WEB_SEARCH_MAX_USES` caps that; set it to `0` to iterate on
prompts or the UI using the corpus alone.

`pydantic-ai` is pinned `>=2.31,<3.0` — 2.31 is where web search became a
*capability* (`Agent(capabilities=[WebSearch(...)])`). Older releases used a
`builtin_tools=` parameter that no longer exists, so don't loosen that floor.

The compose project is shared with the other worktrees and the container names
are fixed, so the *running* api may be another checkout's build. Rebuild with
`podman compose build api` then `up -d --force-recreate api`: a bare
`up -d --build` has silently served a stale image.

`api/tests/` runs on the host with `pip install -r api/requirements-dev.txt`
then `cd api && python -m pytest tests/`. It covers `app/quotes.py` — the
verbatim check that keeps invented words out of quotations — and needs no
credentials, which is why that module is kept free of config imports.

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
