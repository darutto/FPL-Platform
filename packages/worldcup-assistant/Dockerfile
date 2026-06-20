# =============================================================================
# worldcup-assistant — production Dockerfile
# =============================================================================
#
# Build context must be the repository root so sibling packages are reachable.
# wc_server.py inserts three packages into sys.path at startup; all must be
# physically present in the container:
#   worldcup-assistant (self) · llm-orchestrator-core · worldcup-api-client
#
# BUILD (from repo root):
#   docker build -t wc-backend:local \
#     -f packages/worldcup-assistant/Dockerfile .
#
# RUN:
#   docker run --rm -p 8100:8100 \
#     -e WC_PROVIDER=gemini \
#     -e WC_ORCH_MODEL=gemini-2.5-pro \
#     -e GOOGLE_API_KEY=<your-key> \
#     -e TAVILY_API_KEY=<your-key> \
#     wc-backend:local
#
# RAILWAY (separate service from the FPL backend): in the service settings set
#   Dockerfile Path  = packages/worldcup-assistant/Dockerfile
#   Root Directory   = repository root (default)
#   Healthcheck Path = /ready
# Railway injects PORT automatically; the CMD binds ${PORT:-8100}.
#
# Required env vars (set real values in the Railway dashboard, NOT here):
#   WC_PROVIDER=gemini            LLM provider token
#   WC_ORCH_MODEL=gemini-2.5-pro  orchestrator/gatekeeper model
#   GOOGLE_API_KEY=...            Gemini API key
#   TAVILY_API_KEY=...            web-search backend (premium feature)
# Optional:
#   WORLDCUP_API_KEY=...          paid sports-data feed (else free FIFA feed)
#   WC_MAX_ITERATIONS / WC_MAX_TOKENS / WC_TIMEOUT_S  tool-loop tuning
# Do NOT set WC_DEV_TIER in production — tier arrives per-request via the
# X-User-Tier header (Clerk → quota bucket); WC_DEV_TIER is a local-dev-only
# fallback and would otherwise grant a fixed tier to every anonymous caller.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — builder: create a venv and install all Python dependencies
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /build

# gcc + libffi-dev for any C-extension wheels (pydantic core, etc.).
# Kept only in the builder so the runtime image stays lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY packages/worldcup-assistant/requirements.txt ./requirements.txt

RUN python -m venv /venv \
    && /venv/bin/pip install --upgrade pip --no-cache-dir \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 — runtime: lean image with venv + the three source packages only
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /venv /venv

# Mirror the monorepo layout so wc_server.py's sys.path logic works unchanged:
#   _HERE     = /app/packages/worldcup-assistant/worldcup_assistant
#   _PKG_ROOT = /app/packages/worldcup-assistant
#   _PKGS     = /app/packages
COPY packages/worldcup-assistant/    /app/packages/worldcup-assistant/
COPY packages/llm-orchestrator-core/ /app/packages/llm-orchestrator-core/
COPY packages/worldcup-api-client/   /app/packages/worldcup-api-client/

WORKDIR /app/packages/worldcup-assistant

EXPOSE 8100

# Readiness probe — /ready flips to 200 only after the startup grounding
# context is built (see wc_server). /health is liveness-only. The hardcoded
# 8100 matches the local default; on Railway, Railway's own healthcheckPath
# (/ready) is used against the injected PORT instead of this directive.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8100/ready', timeout=5)" \
    || exit 1

# Web search / sessions hold per-process state; keep a single worker until any
# of it moves to a shared store. Railway injects PORT; default 8100 for local.
# sh -c so ${PORT} expands.
CMD ["sh", "-c", "uvicorn worldcup_assistant.wc_server:app --host 0.0.0.0 --port ${PORT:-8100} --workers 1"]
