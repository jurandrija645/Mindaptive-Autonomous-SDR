#!/bin/bash
# Polls origin/main for new commits and redeploys via docker compose if needed.
# Runs from cron on the droplet — see README.md "Auto-deploy" section for setup.
#
# Tracks the last *successfully built* commit in .deployed-sha so a failed
# build (common under cron: missing docker on PATH) is retried on the next
# run even after git is already up to date.
set -euo pipefail

cd "$(dirname "$0")/.."

# One deploy at a time. A build takes longer than the 2-minute cron interval,
# and two overlapping runs recreated the same containers at once: "container
# name ... is already in use" (26 Oct and 18 Nov 2026).
exec 9>/tmp/mindaptive-responder-deploy.lock
flock -n 9 || exit 0

# Cron has a minimal PATH — docker / docker compose often live outside it.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

if ! command -v docker >/dev/null 2>&1; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — ERROR: docker not found on PATH=$PATH" >&2
    exit 1
fi

DEPLOYED_SHA_FILE=".deployed-sha"

git fetch origin main --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

# Code on the droplet comes only from git. Files copied in by hand (or with
# CRLF line endings from Windows) made every pull abort from 18 Nov 2026 while
# the log only said "Aborting". Say why, loudly, and stop.
if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — ERROR: working tree is not clean, not deploying:" >&2
    git status --short >&2
    exit 1
fi

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — new commit detected ($LOCAL -> $REMOTE), pulling"
    git pull --ff-only origin main
    LOCAL=$(git rev-parse HEAD)
fi

DEPLOYED=$(cat "$DEPLOYED_SHA_FILE" 2>/dev/null || echo "none")

if [ "$LOCAL" = "$DEPLOYED" ]; then
    exit 0
fi

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — building/redeploying $DEPLOYED -> $LOCAL"
# --build alone rebuilt the image but reported the app containers as
# "Running" and left them on the old code (seen 2026-09-23: a push built at
# 07:02 while every app container still dated from the day before), so the
# app services are recreated explicitly. cloudflared is left alone.
docker compose build
docker compose up -d --force-recreate --no-deps $(docker compose config --services | grep '^app')
docker compose up -d
echo "$LOCAL" > "$DEPLOYED_SHA_FILE"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — deploy complete ($LOCAL)"
