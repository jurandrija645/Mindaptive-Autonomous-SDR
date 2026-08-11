FROM python:3.11-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY prompts ./prompts
COPY knowledge ./knowledge
COPY signatures ./signatures
# Per-client prompt/knowledge/signature overrides. One image serves every
# client; which one a container is depends on CLIENT_DIR in its env file.
COPY clients ./clients
# One-off maintenance commands, run as `docker compose exec app python -m
# scripts.<name>`. Without this they simply aren't in the image, which is only
# discovered at the moment you need one against production.
COPY scripts ./scripts

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
