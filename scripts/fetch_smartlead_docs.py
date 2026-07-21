"""Mirror the Smartlead API reference pages we depend on into docs/smartlead/.

Why this exists: the published docs are the only description of an API this whole
app is built on, and they have been wrong in ways that cost real debugging time
(see docs/smartlead-api.md). Having them in the repo means they can be grepped
offline, and a `git diff` after re-running this shows exactly what Smartlead
changed under us.

How it works: every docs page is served as its own MDX source by appending
`.md` to the URL (Mintlify), e.g.

    https://api.smartlead.ai/api-reference/campaigns/reply-email-thread.md

That's the exact source — parameter names, types and required flags — rather than
a rendered 600 KB HTML page. The complete page list lives at
https://api.smartlead.ai/sitemap.xml if you need to add one below.

Run:  ./.venv/Scripts/python -m scripts.fetch_smartlead_docs
"""

import sys
from pathlib import Path

import httpx

BASE = "https://api.smartlead.ai"
OUT_DIR = Path("docs/smartlead")

# The endpoints this app actually calls, plus a few adjacent ones worth having
# on hand. Keep this list tight — it's a working reference, not a full mirror.
PAGES = [
    # --- endpoints app/smartlead.py calls today ---
    "api-reference/campaigns/get-all",
    "api-reference/campaigns/get-leads",
    "api-reference/campaigns/get-lead-history",
    "api-reference/campaigns/reply-email-thread",
    "api-reference/campaigns/update-lead-category",
    "api-reference/leads/categories",
    "api-reference/email-accounts/get-all",
    "api-reference/webhooks/create",
    "api-reference/webhooks/get",
    "api-reference/webhooks/events",
    # --- available, not wired up yet (see docs/smartlead-api.md) ---
    "api-reference/campaigns/update-lead",
    "api-reference/campaigns/get-lead-by-id",
    "api-reference/campaigns/forward-email",
    "api-reference/leads/get-by-email",
    "api-reference/inbox/get-messages",
    "api-reference/inbox/reply",
    "api-reference/inbox/update-category",
    # --- behaviour we have to respect ---
    "guides/error-handling",
    "guides/rate-limits",
    "core/leads",
    "core/webhooks",
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failures = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for page in PAGES:
            url = f"{BASE}/{page}.md"
            try:
                resp = client.get(url)
            except Exception as exc:  # network flake shouldn't abort the run
                failures.append((page, repr(exc)))
                continue
            content_type = resp.headers.get("content-type", "")
            # A wrong slug does not 404 reliably — it can return the rendered
            # HTML shell instead. Only markdown is a real hit.
            if resp.status_code != 200 or "markdown" not in content_type:
                failures.append((page, f"{resp.status_code} {content_type}"))
                continue
            dest = OUT_DIR / f"{page.replace('/', '__')}.md"
            dest.write_text(
                f"<!-- Mirrored from {BASE}/{page} — regenerate with "
                f"scripts/fetch_smartlead_docs.py, do not hand-edit. -->\n\n{resp.text}",
                encoding="utf-8",
            )
            print(f"  ok  {page}  ({len(resp.text):,} bytes)")

    for page, why in failures:
        print(f"  FAIL {page}: {why}", file=sys.stderr)
    print(f"\n{len(PAGES) - len(failures)}/{len(PAGES)} pages written to {OUT_DIR}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
