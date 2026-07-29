"""Which client's prompt, knowledge base and signatures this process serves.

The responder is deliberately one-account-per-process (see app/accounts.py —
only Campaigns analysis is multi-account). A second client is therefore a second
container with its own `.env`: its own Smartlead key, database, model, cadence
and category, all of which are already env vars. The only things that weren't
configurable were the *asset* paths and the persona list, which is what this
module fixes.

    CLIENT_DIR unset          -> prompts/, knowledge/, signatures/ at the repo
                                 root. Exactly today's behaviour, byte for byte.
    CLIENT_DIR=clients/aerodefense
                              -> clients/aerodefense/{prompts,knowledge,signatures}

Files fall back to the repo root when the client folder doesn't provide them, so
a client only has to override what actually differs (AeroDefense ships its own
system prompt and knowledge base, but shares prompts/human-writing.md).
"""
import json
import logging
import os
from pathlib import Path

log = logging.getLogger("client_assets")

REPO_ROOT = Path(__file__).resolve().parent.parent

_raw = os.getenv("CLIENT_DIR", "").strip()
CLIENT_DIR = (REPO_ROOT / _raw).resolve() if _raw else REPO_ROOT

# Shown in the UI/logs so it's obvious which client a container is serving.
CLIENT_LABEL = os.getenv("CLIENT_LABEL", "Mindaptive" if CLIENT_DIR == REPO_ROOT else CLIENT_DIR.name.title())

PROMPTS_DIR = CLIENT_DIR / "prompts"
KNOWLEDGE_DIR = CLIENT_DIR / "knowledge"
SIGNATURES_DIR = CLIENT_DIR / "signatures"


def resolve(*parts: str) -> Path:
    """Client's copy of a file if it has one, otherwise the repo-root default."""
    client_copy = CLIENT_DIR.joinpath(*parts)
    if client_copy.exists():
        return client_copy
    return REPO_ROOT.joinpath(*parts)


def read_text(*parts: str, default: str = "") -> str:
    path = resolve(*parts)
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def personas() -> list[dict]:
    """Sending personas for this client, from `<CLIENT_DIR>/personas.json`:

        [{"from_name": "Amy Muschler",       # must match Smartlead's from_name
          "signature_file": "amy-muschler.html",
          "calendar_link": "https://meetings.hubspot.com/amy-muschler",
          "name_hints": ["amy"]}]            # optional, for retired mailboxes

    Returns [] when the file is absent, which keeps Mindaptive on the hardcoded
    map in app/signatures.py.
    """
    path = CLIENT_DIR / "personas.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.exception("could not read %s — falling back to built-in personas", path)
        return []
    return data if isinstance(data, list) else []


def describe() -> str:
    return f"client={CLIENT_LABEL} dir={CLIENT_DIR}"
