# =============================================================================
# fpl-grounded-assistant — production Dockerfile
# =============================================================================
#
# Build context must be the repository root so sibling packages are reachable.
# fpl_server.py inserts eight sibling packages into sys.path at startup; they
# must all be physically present in the container.
#
# BUILD (from repo root):
#   docker build -t fpl-backend:local \
#     -f packages/fpl-grounded-assistant/Dockerfile .
#
# RUN:
#   docker run --rm -p 8000:8000 \
#     -e DEFAULT_PROVIDER=gemini \
#     -e GOOGLE_API_KEY=<your-key> \
#     fpl-backend:local
#
# RAILWAY: set Dockerfile Path = packages/fpl-grounded-assistant/Dockerfile
#          and leave Root Directory as the repository root (default).
#          Railway injects PORT automatically; CMD uses ${PORT:-8000}.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — builder: create a venv and install all Python dependencies
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /build

# gcc + libffi-dev needed for packages with C extensions (e.g. pydantic, cryptography).
# Kept only in the builder so the runtime image stays lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY packages/fpl-grounded-assistant/requirements.txt ./requirements.txt

RUN python -m venv /venv \
    && /venv/bin/pip install --upgrade pip --no-cache-dir \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 — runtime: lean image with venv + source packages only
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Add venv to PATH — applies to RUN, CMD, and ENTRYPOINT without shell wrapping.
ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /venv /venv

# Copy only the nine packages fpl_server.py inserts into sys.path at startup.
# Layout mirrors the monorepo so the existing path logic works unchanged:
#   _HERE  = /app/packages/fpl-grounded-assistant
#   _PKGS  = /app/packages
#   _SIB() = /app/packages/<name>
COPY packages/fpl-grounded-assistant/ /app/packages/fpl-grounded-assistant/
COPY packages/fpl-api-client/         /app/packages/fpl-api-client/
COPY packages/fpl-data-core/          /app/packages/fpl-data-core/
COPY packages/fpl-player-registry/    /app/packages/fpl-player-registry/
COPY packages/fpl-query-tools/        /app/packages/fpl-query-tools/
COPY packages/fpl-tool-contract/      /app/packages/fpl-tool-contract/
COPY packages/fpl-tool-runner/        /app/packages/fpl-tool-runner/
COPY packages/fpl-captain-engine/     /app/packages/fpl-captain-engine/
COPY packages/fpl-pipeline/           /app/packages/fpl-pipeline/

WORKDIR /app/packages/fpl-grounded-assistant

EXPOSE 8000

# Readiness probe — uses /ready (not /health) so the container is only marked
# healthy after the FPL bootstrap has been fetched.  /health is liveness-only
# and is always 200; probing it here would pass traffic before data is ready.
# start-period gives the bootstrap fetch (+ up to 3 retries) time to complete.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready', timeout=5)" \
    || exit 1

# Railway injects PORT; default 8000 for local runs.
# Using sh -c so ${PORT} shell expansion works.
CMD ["sh", "-c", "uvicorn fpl_server:app --host 0.0.0.0 --port ${PORT:-8000}"]
