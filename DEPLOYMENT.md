# Deploying Anchryn

Backend on **Render**, database on **Neon**, frontend on **Vercel**.

There is a chicken-and-egg step: the frontend needs the backend's URL, and the
backend needs the frontend's origin for CORS. Deploy the backend first, then the
frontend, then come back and set CORS. Steps 4 and 5.

---

## 1. Push to GitHub

```bash
cd anchryn-doc-chat
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

Confirm no secrets went with it — `.env` holds your Hugging Face token and JWT
signing key, and is gitignored:

```bash
git ls-files | grep -E '\.env$|\.env\.'   # must print nothing
```

## 2. Database on Neon

Create a project at https://neon.tech, then in the **Connect** dialog **turn off
the "Connection pooling" toggle** and copy the direct connection string.

> The pooled endpoint is PgBouncer in transaction mode, which breaks psycopg's
> prepared statements. SQLAlchemy pools connections itself, so the direct host is
> the right one here.

You do **not** need to create the `vector` extension by hand — the first
migration does it.

## 3. Backend on Render

Either use the [`render.yaml`](render.yaml) blueprint (**New → Blueprint**), or
create a Web Service manually:

| Field | Value |
|---|---|
| Language / Runtime | Docker |
| Root Directory | `backend/anchryn-api` |
| Dockerfile Path | `Dockerfile` |
| Health Check Path | `/api/health` |

Root Directory is the one people miss — it becomes the Docker build context,
which is what the `COPY requirements.txt .` line expects.

Environment variables:

```
DATABASE_URL         = postgresql://user:pw@ep-xxx.region.aws.neon.tech/neondb?sslmode=require
JWT_SECRET           = <generate one, see below>
HF_TOKEN             = your Hugging Face token
CORS_ALLOWED_ORIGINS = http://localhost:4200        (fixed in step 5)
```

Paste the Neon string **exactly as given** — the psycopg driver is filled in
automatically.

Generate a signing key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Anyone who knows it can mint a token for any account. The blueprint uses
Render's `generateValue: true` so it is never a value you have to handle.
`/api/health` reports `auth_secret_is_default` — if that is ever `true` in
production, the development key is in use.

Check it:

```bash
curl https://<your-service>.onrender.com/api/health
```

`hf_configured: false` means the token did not reach the service.

### What happens on start

The container runs `alembic upgrade head` before serving, so a deploy can never
answer requests against a schema it does not match. A failed migration stops the
container rather than starting it with the wrong tables.

## 4. Frontend on Vercel

1. **Add New → Project**, import the repo.
2. **Set Root Directory to `frontend/anchryn-web`.** Without it Vercel builds the
   repo root and finds no `package.json`.
3. Deploy. Everything else comes from [`vercel.json`](frontend/anchryn-web/vercel.json).

Then set the backend URL in
[`environment.prod.ts`](frontend/anchryn-web/src/environments/environment.prod.ts):

```ts
export const environment = {
  production: true,
  apiBaseUrl: 'https://your-service.onrender.com',   // no trailing slash
};
```

Commit and push. This is baked in at build time, which is why it lives in source
rather than a Vercel environment variable — it is a public URL, not a secret.

## 5. Let the browser call it (CORS)

Render → Environment:

```
CORS_ALLOWED_ORIGINS = https://your-app.vercel.app
```

Save; the service restarts. **Skip this and the site loads but every request
fails**, while `curl` against the backend works fine. That combination always
means CORS.

---

## 6. CI/CD — independent pipelines

Two workflows, each filtered by path. A backend-only commit never runs the
frontend pipeline, and vice versa.

| Workflow | Triggers on | Jobs |
|---|---|---|
| [`backend.yml`](.github/workflows/backend.yml) | `backend/**`, `render.yaml` | `test` (pgvector service, ruff, pytest) → `docker` (image build) → `deploy` |
| [`frontend.yml`](.github/workflows/frontend.yml) | `frontend/**` | `test` (headless Chrome, production build) → `deploy` |

Both accept **workflow_dispatch**, so either side can be redeployed from the
Actions tab without a commit.

The backend job runs Postgres from the `pgvector/pgvector:pg17` image — plain
`postgres` has no `vector` type and every migration would fail. It needs no
Hugging Face token: generation is stubbed in tests, and the only `/api/answer`
case is the refusal path, which returns before any model call.

### ⚠️ Switch off the platforms' own auto-deploy

Render and Vercel both redeploy on **any** push, ignoring which files changed.
Leave them on and a backend-only commit still rebuilds the frontend — exactly
what the split workflows prevent — and you get two deploys per push.

- **Render** → Settings → **Auto-Deploy → No**
- **Vercel** → Settings → Git → turn off automatic production deployments

### Secrets

| Secret | Where to get it |
|---|---|
| `RENDER_DEPLOY_HOOK_URL` | Render → Settings → Deploy Hook |
| `VERCEL_TOKEN` | Vercel → Account Settings → Tokens |
| `VERCEL_ORG_ID` | `npx vercel link` in `frontend/anchryn-web`, then read `.vercel/project.json` |
| `VERCEL_PROJECT_ID` | same file |

Both deploy jobs fail with an explicit message when their secrets are missing,
rather than passing while silently doing nothing.

---

## Free-tier realities

- **The backend sleeps.** Render's free web services spin down after ~15 minutes
  idle and take about a minute to wake. Neon suspends after ~5 minutes. The first
  request after a quiet spell wakes both.
- **512 MB of RAM.** The embedding model runs in-process. It fits, but do not
  raise the connection pool or run a larger model without checking.
- **The embedding model is baked into the image** so a cold start does not spend
  a 67MB download before the first upload can finish. If the build log says
  `WARNING: could not pre-cache the embedding model`, the build was on a network
  that blocked Hugging Face — the image still works, the first request is just
  slower.
- **Hugging Face inference credits are small** on a free account. A quota
  rejection surfaces as HTTP 429 with a readable message.

## Still not production-grade

- **No rate limiting.** Anyone can register and upload until the disk or the
  inference quota runs out.
- **No email verification.** Registration accepts any well-formed address.
- **No password reset.** A forgotten password means a lost account.
- Uploads are capped at 25MB each but there is no per-account storage limit.

The multi-tenancy itself is solid — documents, chunks, pages and retrieval are
all filtered by owner, with tests asserting one account cannot reach another's
data. What is missing above is abuse prevention, not isolation.
