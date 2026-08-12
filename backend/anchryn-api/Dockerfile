FROM python:3.13-slim

WORKDIR /app

# libgomp is required by onnxruntime, which fastembed uses to run the embedding
# model. Without it the import fails at runtime rather than at build time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user, created before the model download so the cache it
# writes is owned by the account that later reads it.
RUN useradd --create-home --uid 10001 anchryn
ENV HOME=/home/anchryn \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

USER anchryn

# Bake the embedding model into the image. It is ~67MB and fastembed downloads
# it on first use otherwise — which on a free instance with an ephemeral disk
# means every cold start pays for it, and the first upload after each restart
# appears to hang.
#
# HF_HUB_DISABLE_XET forces the plain HTTPS transfer. Hugging Face's newer Xet
# backend uses a separate CAS service that failed here mid-download; the classic
# path fetches the same files and tolerates restrictive networks better.
#
# Deliberately not fatal. Behind a TLS-inspecting corporate proxy the container
# does not trust the intercepting root and this download cannot succeed — but
# the image is still perfectly usable, it just fetches the model on first use.
# Failing the build would block local development for an optimisation. CI and
# the deployment platform have clean networks, so the images that actually
# matter do get the model baked in.
RUN HF_HUB_DISABLE_XET=1 python -c \
    "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')" \
    && echo "Embedding model cached in the image." \
    || echo "WARNING: could not pre-cache the embedding model; it will download on first use."

COPY --chown=anchryn:anchryn app ./app
COPY --chown=anchryn:anchryn alembic ./alembic
COPY --chown=anchryn:anchryn alembic.ini ./
COPY --chown=anchryn:anchryn docker-entrypoint.sh ./

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
