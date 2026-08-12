# Anchryn

Ask questions of your own documents, and get answers that cite the exact passage
they came from — or an honest "the documents don't cover this".

```
anchryn-doc-chat/
├── backend/anchryn-api     FastAPI · Python 3.13 · PostgreSQL + pgvector
├── frontend/anchryn-web    Angular 20
├── docker-compose.yml      pgvector Postgres for local development
├── render.yaml             Render blueprint for the backend
└── .github/workflows/      Path-filtered pipelines, one per side
```

Deploying it? See **[DEPLOYMENT.md](DEPLOYMENT.md)**.

## What makes it different from "chat with your PDF"

**It refuses.** When retrieval finds nothing close enough, the answer is a
refusal — decided in code, before any model call. Asking a model to decline and
trusting it to comply is the failure this project exists to avoid.

**Citations land on the passage.** Every chunk stores the exact character range
it occupies in its page, so clicking a citation highlights the precise text that
was retrieved. Not a keyword re-search that drifts — the stored offsets, sliced
back out of the stored page.

**It shows its work.** "Why this answer" lists every retrieved passage with its
similarity score and marks the ones actually cited. You can see why it answered,
or why it refused.

**Documents are private.** Every document, chunk, page and search is filtered by
owner. One account cannot see, search, or delete another's data — asserted by
tests, not just intended.

## Running locally

**1. Database**

```bash
docker compose up -d
```

pgvector Postgres on host port **5434**.

**2. Backend**

```bash
cd backend/anchryn-api
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # then fill in HF_TOKEN and JWT_SECRET
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Interactive API docs at http://localhost:8000/docs.

Use Python **3.13**, not 3.14 — `onnxruntime` has no wheels for it yet and pip
falls back to compiling from source.

**3. Frontend**

```bash
cd frontend/anchryn-web
npm install
npm start
```

http://localhost:4200, proxying `/api` to port 8000.

## How it works

| Step | What happens |
|---|---|
| Upload | pypdf extracts text per page; pages are stored verbatim |
| Chunk | Split on paragraph → sentence → word, ~1000 chars with 150 overlap, never across a page |
| Embed | `bge-small-en-v1.5` via fastembed, in-process — 384 dimensions |
| Retrieve | pgvector cosine search with an HNSW index, filtered to the owner |
| Answer | Retrieved passages only, with `[n]` citations, via Hugging Face |

The invariant everything rests on: `page_text[chunk.char_start:chunk.char_end]
== chunk.text`. Text is only ever sliced, never rewritten — normalising it would
break the mapping and citations would silently point at the wrong words.

Embeddings run **locally** rather than through an API. They are called once per
chunk at ingest and once per question at search, so a rate-limited network call
there would be the first thing to break. fastembed uses ONNX instead of PyTorch,
which is ~50MB rather than ~800MB and fits a small container.

## Configuration

`backend/anchryn-api/.env`:

| Key | Default | Notes |
|---|---|---|
| `DATABASE_URL` | — | A bare `postgresql://` URL gets the psycopg driver filled in |
| `JWT_SECRET` | dev placeholder | Must be replaced in production |
| `HF_TOKEN` | — | Needs the "Make calls to Inference Providers" permission |
| `HF_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Changing it needs a migration and a re-embed |
| `GROUNDING_THRESHOLD` | `0.45` | Below this, the answer is a refusal |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:4200` | Comma-separated |
| `CA_BUNDLE` / `TLS_STRICT` | — / `true` | Only needed behind a TLS-inspecting proxy |

**The threshold is corpus-specific.** 0.45 came from measuring a sample: answerable
questions scored 0.62–0.86, unanswerable ones 0.33–0.36. Re-check it on your own
documents — ask a few questions you know are covered and a few that are not, and
look at `best_similarity` in the response.

## Tests

```bash
cd backend/anchryn-api && pytest -q          # 88 tests
cd frontend/anchryn-web && npm test          # 17 tests
```

Backend tests need the Postgres container running. They use the real embedding
model rather than a mock — a mocked embedder proves the plumbing works while
saying nothing about whether the vectors mean anything.

## Known limitations

- **No rate limiting, email verification or password reset.** The isolation
  between accounts is solid; abuse prevention is not there.
- **Two-column PDFs extract badly.** pypdf reads drawing order, not visual
  order, so columns interleave. Check `/api/documents/{id}/chunks` if answers
  look wrong.
- **Scanned PDFs are rejected** with a message pointing at OCR — there is no
  text layer to read.
- Ingestion is synchronous, so a very large PDF holds the request open.
