# Setup

Getting this project running from a fresh clone. The end state is three
containers (frontend, api, Qdrant) plus a Qdrant collection populated from the
committed corpus.

Roughly 15 minutes, most of it waiting on the first container build and on the
embedding run.

## 1. What you need

| Requirement | Why |
| --- | --- |
| Docker with Compose v2 (`docker compose`) | runs the frontend, api, and Qdrant |
| Python 3.10+ on the host | the `tagging/` and `ingest/` pipelines run outside the containers |
| An Anthropic API key | the drafting and brief agents, and the corpus classifier |
| A Google Cloud project with billing | Gemini embeddings on Vertex AI, used by ingest and by corpus search |
| `gcloud` CLI | Application Default Credentials for the above |

The api and frontend build inside containers (python 3.12-slim, node 20-alpine),
so you don't need a matching Python or any Node on the host unless you want to
run the frontend dev server.


## 2. Google Cloud credentials

`setup/setup.sh` is re-runnable and does the whole Google side: picks or creates
a project, optionally links billing, enables `aiplatform.googleapis.com`, runs
`gcloud auth application-default login`, sets the ADC quota project, and writes
`GOOGLE_CLOUD_PROJECT` and `GOOGLE_GENAI_USE_VERTEXAI` into `.env`.

```sh
./setup/setup.sh
```

It needs [`gum`](https://github.com/charmbracelet/gum) for its prompts and will
offer to install it. It also creates `.env` from `.env.example` if you don't
already have one.

Billing must be linked, or every Vertex AI call fails and ingest produces no
vectors. The script lets you skip that step and warns you when you do.

Doing it by hand instead:

```sh
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

The api container reads ADC by bind-mounting `~/.config/gcloud` read-only — no
service account key or API key is involved.

## 3. `.env`

If `setup.sh` didn't already make it:

```sh
cp .env.example .env
```

Then edit in the anthropic api key:

- **`ANTHROPIC_API_KEY`** — set it to your real key.


Everything else in `.env.example` has a working default in `docker-compose.yml`;
a minimal `.env` is just `ANTHROPIC_API_KEY`, `GOOGLE_CLOUD_PROJECT`, and
`GOOGLE_GENAI_USE_VERTEXAI`. Ports (`API_PORT`, `FRONTEND_PORT`,
`QDRANT_HTTP_PORT`, `QDRANT_GRPC_PORT`) are there if 8000/3000/6333/6334 are
taken. 

Two settings worth knowing before your first brief, since both cost money:

- `WEB_SEARCH_MAX_USES` (default 5) caps Anthropic server-side web searches per
  brief. Those are billed **per search** ($10 per 1,000) on top of tokens. Set
  it to `0` to build briefs from the corpus alone while you iterate on prompts
  or UI.
- `MAX_OUTPUT_TOKENS` (default 16000) is the per-brief output ceiling. Too low
  truncates the brief mid-JSON, and the failure surfaces as missing fields in
  validation rather than as a length error.

## 4. Start the stack

```sh
docker compose up --build
```

Or detached, which is easier to follow:

```sh
docker compose up -d --build
docker compose logs -f api
```

On boot the api creates the Qdrant collection if it's missing and runs Alembic
migrations against the SQLite app database (on the `writing-style-app-db` named
volume). Both are automatic — there's no separate migrate step.

Services:

| Service | URL |
| --- | --- |
| frontend | http://localhost:3000 |
| api | http://localhost:8000 |
| Qdrant | http://localhost:6333 |

## 5. Populate Qdrant

**The app will start without this, but corpus search returns nothing, so every
brief is ungrounded.** The vector store is the one piece of state not carried by
the repo or created on boot.

The corpus itself *is* committed — `raw/` (~1,080 documents) and the classified
copies in `intermediate/` are both in git. So a fresh clone does **not** need to
run the scrapers or the tagging pass. It only needs to embed `intermediate/`
into Qdrant, which happens on the host:

```sh
pip install -r ingest/requirements.txt   # a virtualenv is a good idea
docker compose up -d qdrant              # ingest only needs Qdrant, not the api
python ingest/ingest.py
```

Ingest creates the collection itself if it doesn't exist, so this works before
the api has ever run. It skips `media-coverage` and `unclassified` by default.

Check what it will do without paying for embeddings first:

```sh
python ingest/ingest.py --dry-run        # parse and chunk only, no API calls
```

Useful flags: `--glob` to limit to a subset of `intermediate/`,
`--include-category` / `--exclude-category` to change the category filter,
`--prune` to drop points whose source file no longer exists, and `--recreate` to
drop and rebuild the collection — the right move after any wholesale
reorganization, since point IDs are derived from a document's path under
`intermediate/`.

## 6. Verify

```sh
curl -s localhost:8000/health        # api directly    -> {"status":"ok"}
curl -s localhost:3000/health        # through nginx   -> {"status":"ok"}
curl -s localhost:6333/collections   # qdrant          -> writing_style
docker compose ps
```

If `localhost:3000` serves the app but `localhost:3000/health` doesn't, nginx is
up but can't reach the api on `writing-style-network`.

Confirm the collection actually has vectors, not just that it exists:

```sh
curl -s localhost:6333/collections/writing_style | grep -o '"points_count":[0-9]*'
```

A zero here means ingest didn't run or its embedding calls failed — check
billing on the Google project.

Then open http://localhost:3000 and generate a brief.

There are a number of example briefs I was testing with in samples.txt which are usable. 

## 7. Optional

### Changing the corpus

After editing anything under `raw/`, re-run both stages so Qdrant matches:

```sh
pip install -r tagging/requirements.txt
python tagging/tag.py                    # raw/ -> intermediate/, via Claude Haiku
python ingest/ingest.py                  # intermediate/ -> Qdrant
```

Tagging reuses `ANTHROPIC_API_KEY` and caches results in
`tagging/.tagcache.json`, so a re-run after an unrelated edit costs nothing.
Both stages take `--dry-run` to skip the paid calls. `tag.py` also takes
`--sample N` and `--limit N` for cheap taxonomy tuning, `--force` to ignore the
cache, and `--visibility {public,private}` / `--only GLOB` to narrow the input.

If the classifier changes its mind about a document's category, the file moves
and its old vectors survive as duplicates — `python ingest/ingest.py --prune`
is the standing fix.

### Frontend dev server

Hot reload against the containerized api:

```sh
cd frontend
npm install
npm run dev                              # http://localhost:5173
```

Vite proxies `/api` to `http://localhost:8000`, and `CORS_ALLOW_ORIGINS` in
`.env.example` already includes `:5173`.

### Tests

`api/tests/` runs on the host and needs no credentials:

```sh
pip install -r api/requirements-dev.txt
cd api && python -m pytest tests/
```

It covers `app/quotes.py`, the verbatim check that keeps invented words out of
quotations.

## Troubleshooting

**Ingest can't reach Qdrant.** `QDRANT_URL` is set in `.env`. See step 3 — the
fix is to remove it, not to change its value.

**Embeddings fail, or the collection stays at zero points.** Either ADC isn't
configured (`gcloud auth application-default login`), `aiplatform.googleapis.com`
isn't enabled, or the project has no billing account linked. Re-running
`./setup/setup.sh` covers all three.

**The api serves stale code after a rebuild.** A bare `up -d --build` has
silently served a stale image. Use:

```sh
docker compose build api
docker compose up -d --force-recreate api
```

This matters more than usual here: the compose project name and container names
are fixed, so if you have multiple worktrees of this repo, the *running* api may
be another checkout's build.

**Dimension mismatch on ingest.** `QDRANT_VECTOR_SIZE` (1536) is both the
collection's dimension and the `output_dimensionality` requested from Gemini.
Changing it requires `python ingest/ingest.py --recreate`, since the existing
collection is fixed at the old size.

**Starting over.** `docker compose down -v` removes the named volumes —
`writing-style-qdrant-storage` and `writing-style-app-db` — which discards both
the embedded corpus and every saved speech and brief. Without `-v` the data
survives.
