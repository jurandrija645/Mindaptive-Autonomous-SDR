#!/bin/bash
# Polls origin/main for new commits and redeploys via docker compose if found.
# Runs from cron on the droplet — see README.md "Auto-deploy" section for setup.
set -euo pipefail

cd "$(dirname "$0")/.."

git fetch origin main --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — new commit detected ($LOCAL -> $REMOTE), deploying"
    git pull origin main
    docker compose up -d --build
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — deploy complete"
fi
