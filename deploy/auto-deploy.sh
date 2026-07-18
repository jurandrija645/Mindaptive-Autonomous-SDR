#!/bin/bash
# Polls origin/main for new commits and redeploys via docker compose if needed.
# Runs from cron on the droplet — see README.md "Auto-deploy" section for setup.
#
# Tracks the last *successfully built* commit in .deployed-sha so a failed
# build (common under cron: missing docker on PATH) is retried on the next
# run even after git is already up to date.
set -euo pipefail

cd "$(dirname "$0")/.."

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
docker compose up -d --build
echo "$LOCAL" > "$DEPLOYED_SHA_FILE"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — deploy complete ($LOCAL)"
