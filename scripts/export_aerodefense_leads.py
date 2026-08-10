"""One-off worklist generator for Aerodefense's Smartlead account: pulls every
Interested / Lead Done lead that's gone quiet after 3+ of our follow-ups since
their own last message, summarizes the thread with Haiku, and writes
Andrew.csv / Amy.csv / Max.csv (one row per lead, grouped by which mailbox
carried the thread) for manual LinkedIn outreach.

Run from the repo root:
    ./.venv/Scripts/python -m scripts.export_aerodefense_leads
"""
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import json
import os

from app.exports.lead_export import ExportConfig, run_export

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

REPO_ROOT = Path(__file__).resolve().parent.parent

# Retired mailboxes, shared with the dashboard's per-lead export (which reads
# the same file through client_assets.prior_senders — scripts/ isn't in the
# Docker image, so the map can't live here alone). Read directly rather than via
# client_assets because this script runs against AeroDefense regardless of what
# CLIENT_DIR the local .env happens to say.
_PRIOR_SENDERS = {
    key: value
    for key, value in json.loads(
        (REPO_ROOT / "clients" / "aerodefense" / "prior-senders.json").read_text(encoding="utf-8")
    ).items()
    if not key.startswith("_")
}

CONFIG = ExportConfig(
    label="aerodefense",
    api_key=os.environ["AERODEFENSE_SMARTLEAD_API_KEY"],
    category_names=["Interested", "Lead Done"],
    persona_from_names={
        "Andrew Grasso": "Andrew",
        "Amy Muschler": "Amy",
        "Max West": "Max",
    },
    output_dir=REPO_ROOT / "exports" / "aerodefense",
    known_prior_senders=_PRIOR_SENDERS,
)


def main() -> None:
    rows_by_persona = run_export(CONFIG)
    total = sum(len(rows) for rows in rows_by_persona.values())
    print(f"\n{total} qualifying leads written to {CONFIG.output_dir}")
    for persona, rows in sorted(rows_by_persona.items()):
        print(f"  {persona}: {len(rows)}")


if __name__ == "__main__":
    main()
