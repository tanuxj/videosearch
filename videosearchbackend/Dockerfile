# ── Production image for the VideoSearch backend ─────────────────────────────
FROM python:3.12.7-slim

# Official uv binary (pinned for reproducibility)
COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /uvx /bin/

WORKDIR /app

# System ffmpeg, dynamically linked.
#
# `imageio-ffmpeg` already ships a static build, and it is fine for local files
# — but static glibc cannot resolve hostnames (`getaddrinfo` has to `dlopen` the
# NSS modules, which a static binary has no loader for), so it **segfaults** on
# any http(s) input. Clip extraction needs URL input: it lets ffmpeg range-
# request the few seconds it is cutting instead of downloading the whole object,
# which took ~16 minutes on a 1.4 GB video and now takes ~6 seconds.
#
# Above the dependency layer on purpose: this rarely changes, so it stays cached.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install dependencies first (better layer caching); requires uv.lock.
# Nothing that changes per-commit may be copied above this line: `uv sync` is
# the expensive layer, and copying application code first invalidates it on
# every edit, forcing a full dependency reinstall (and a PyPI round trip).
COPY pyproject.toml uv.lock README.md ./
# `--no-install-project` builds only the dependency tree; hatchling would
# otherwise need ./app, which is exactly the thing we don't want in this layer.
RUN uv sync --frozen --no-dev --no-install-project

# Application code last — these layers are cheap to rebuild.
COPY app ./app
# Shipped so migrations can be applied from the running container:
#   docker compose run --rm backend alembic upgrade head
COPY alembic.ini ./
COPY migrations ./migrations
# Now install the project itself (fast: dependencies are already in place).
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Run as an unprivileged user
RUN useradd --create-home --uid 10001 appuser

# CLIP weights (~1.2 GB) live here. Created with appuser ownership *before* the
# volume is mounted so a fresh named volume inherits it — otherwise Docker
# creates the mountpoint root-owned and the download fails with EACCES.
ENV HF_HOME=/models
RUN mkdir -p /models && chown appuser:appuser /models

USER appuser

EXPOSE 3006

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3006/api/v1/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3006"]
