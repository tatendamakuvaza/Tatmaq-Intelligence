#!/bin/bash
# Runs the API and one worker in a single container: the leanest way to host the MVP.
# Applies database migrations first. If either process exits, the container exits, so
# the hosting platform restarts it rather than leaving half a service running.
set -euo pipefail

python /srv/scripts/migrate.py

python -m app.workers.worker &
worker=$!
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
api=$!

stop() { kill -TERM "$worker" "$api" 2>/dev/null || true; }
trap stop TERM INT

wait -n "$worker" "$api" || true
stop
wait || true
exit 1
