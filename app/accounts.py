"""Multiple Smartlead accounts, for the Campaigns analysis surface.

The responder side of the app (inbox, drafts, daily scan, sending) is
single-account — it belongs to Mindaptive and uses `settings.smartlead_api_key`
throughout. Campaign *analysis*, though, is read-only and useful for any
Smartlead account Andrew runs, so the Campaigns tab can switch between accounts
and analyze each one's campaigns.

Accounts come from the environment so a new one is added on the droplet by
editing `.env`, no code change:

- the default account is `SMARTLEAD_API_KEY` (Mindaptive), labelled by
  `SMARTLEAD_ACCOUNT_LABEL` (default "Mindaptive");
- every `<NAME>_SMARTLEAD_API_KEY` env var adds another account — slug `<name>`
  lowercased, label `<name>` title-cased (or `SMARTLEAD_ACCOUNT_LABEL_<NAME>`).
  This reuses the existing `AERODEFENSE_SMARTLEAD_API_KEY` convention.
"""

import os
from dataclasses import dataclass

from app.config import settings

DEFAULT_SLUG = "default"
_SUFFIX = "_SMARTLEAD_API_KEY"


@dataclass(frozen=True)
class Account:
    slug: str
    label: str
    api_key: str


def _load_accounts() -> dict[str, Account]:
    accounts: dict[str, Account] = {}

    if settings.smartlead_api_key:
        accounts[DEFAULT_SLUG] = Account(
            slug=DEFAULT_SLUG,
            label=os.getenv("SMARTLEAD_ACCOUNT_LABEL", "Mindaptive"),
            api_key=settings.smartlead_api_key,
        )

    for name, value in os.environ.items():
        # Match `<NAME>_SMARTLEAD_API_KEY`, but never the bare `SMARTLEAD_API_KEY`
        # (which is the default account above and has no `<NAME>_` prefix).
        if not name.endswith(_SUFFIX) or name == _SUFFIX.lstrip("_"):
            continue
        prefix = name[: -len(_SUFFIX)]
        if not prefix or not value.strip():
            continue
        slug = prefix.lower()
        label = os.getenv(f"SMARTLEAD_ACCOUNT_LABEL_{prefix}") or prefix.replace("_", " ").title()
        accounts[slug] = Account(slug=slug, label=label, api_key=value.strip())

    return accounts


_ACCOUNTS = _load_accounts()


def list_accounts() -> list[Account]:
    """Default account first, then the rest alphabetically by label."""
    rest = sorted(
        (a for a in _ACCOUNTS.values() if a.slug != DEFAULT_SLUG),
        key=lambda a: a.label.lower(),
    )
    default = [_ACCOUNTS[DEFAULT_SLUG]] if DEFAULT_SLUG in _ACCOUNTS else []
    return default + rest


def get_account(slug: str | None) -> Account | None:
    """Resolve a slug to an account, falling back to the default. Returns None
    only if no accounts are configured at all."""
    if slug and slug in _ACCOUNTS:
        return _ACCOUNTS[slug]
    if DEFAULT_SLUG in _ACCOUNTS:
        return _ACCOUNTS[DEFAULT_SLUG]
    accounts = list_accounts()
    return accounts[0] if accounts else None
