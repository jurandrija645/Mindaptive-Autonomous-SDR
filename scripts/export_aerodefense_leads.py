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

import os

from app.exports.lead_export import ExportConfig, run_export

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

REPO_ROOT = Path(__file__).resolve().parent.parent

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
)


def main() -> None:
    rows_by_persona = run_export(CONFIG)
    total = sum(len(rows) for rows in rows_by_persona.values())
    print(f"\n{total} qualifying leads written to {CONFIG.output_dir}")
    for persona, rows in sorted(rows_by_persona.items()):
        print(f"  {persona}: {len(rows)}")


if __name__ == "__main__":
    main()
