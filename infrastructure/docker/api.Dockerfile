# The API and the background worker share this image; they differ only in the command.
#   API:     uvicorn app.main:app --host 0.0.0.0 --port 8000      (default)
#   worker:  python -m app.workers.worker
#   both:    /srv/infrastructure/docker/start-all.sh               (one small container)
# Build from the repository root:
#   docker build -f infrastructure/docker/api.Dockerfile -t tatmaq-api .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv/apps/api \
    STORAGE_LOCAL_DIR=/srv/var/storage \
    WORK_DIR=/srv/var/work

WORKDIR /srv

# Dependencies first, so this layer is rebuilt only when the lockfile changes.
COPY apps/api/requirements.lock apps/api/requirements.lock
RUN pip install -r apps/api/requirements.lock

COPY packages/analytics-core packages/analytics-core
RUN pip install --no-deps ./packages/analytics-core

COPY apps/api apps/api
COPY database database
COPY scripts scripts
COPY infrastructure/docker/start-all.sh infrastructure/docker/start-all.sh

# Run as an unprivileged user; it owns only the data directory.
RUN useradd --uid 10001 --create-home tatmaq \
    && mkdir -p /srv/var/storage /srv/var/work \
    && chown -R tatmaq:tatmaq /srv/var \
    && chmod +x infrastructure/docker/start-all.sh
USER tatmaq

WORKDIR /srv/apps/api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/healthz', timeout=4)" || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
