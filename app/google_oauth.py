"""Google OAuth for the Sheets export (app/exports/sheet_export.py).

OAuth as Andrew's own Google account rather than a service account: he already
owns both LinkedIn spreadsheets, so acting as him means nothing to share and no
JSON key file to place on the droplet by hand. The client id/secret are the ones
his n8n instance already uses.

The refresh token is kept in `app_settings` (the same key/value table as
`default_model`), not in a file — it survives a restart and a redeploy with
nothing mounted, and `docker_copy_gotcha` can't bite a row in the database. The
two containers have separate databases, so GOOGLE_REFRESH_TOKEN in .env is an
override that lets the second one reuse the consent the first already gave.

No SDK: the token endpoint and Sheets v4 are plain JSON over HTTPS, so this is
httpx like every other outbound call here (see app/openrouter.py). That keeps
requirements.txt — and the pip layer of the image — untouched.
"""

import logging
import time

import httpx

from app import db
from app.config import settings

log = logging.getLogger("google_oauth")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
# Read *and* write: the export appends rows, and reads the header row and the
# email column to place them correctly and to spot a duplicate.
SCOPE = "https://www.googleapis.com/auth/spreadsheets"

REQUEST_TIMEOUT = 30.0

SETTING_KEY = "google_refresh_token"

# Access token + the epoch second it stops being usable. Process-local by
# design: it's a 60-minute credential that costs one POST to re-mint, so there's
# nothing to gain from persisting it and one more secret at rest if we did.
_access_token: str | None = None
_expires_at: float = 0.0

# Re-mint this many seconds before Google's stated expiry, so a token can't go
# stale between the check and the request that uses it.
_EXPIRY_MARGIN = 60


class GoogleAuthError(RuntimeError):
    pass


def is_configured() -> bool:
    """True when the OAuth client exists — i.e. connecting is even possible."""
    return bool(settings.google_client_id and settings.google_client_secret)


def stored_refresh_token() -> str:
    if settings.google_refresh_token:
        return settings.google_refresh_token
    with db.db_session() as conn:
        return db.get_setting(conn, SETTING_KEY) or ""


def is_connected() -> bool:
    return is_configured() and bool(stored_refresh_token())


def redirect_uri() -> str:
    """Must match one of the Authorized redirect URIs on the OAuth client in
    Google Cloud Console, character for character — including the scheme and
    port. Derived from PUBLIC_BASE_URL so local dev and the droplet each use
    their own, and both need registering there once."""
    base = (settings.public_base_url or "http://localhost:8080").rstrip("/")
    return f"{base}/oauth/google/callback"


def authorize_url(state: str) -> str:
    """Consent URL to send the browser to.

    `access_type=offline` + `prompt=consent` is what makes Google return a
    refresh token. Without the prompt, a second consent for an already-approved
    scope comes back with an access token only, so a reconnect after a revoke
    would silently leave us with nothing to refresh from.
    """
    if not is_configured():
        raise GoogleAuthError(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set — add them to .env."
        )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return str(httpx.URL(AUTH_URL, params=params))


def exchange_code(code: str) -> None:
    """Trade the callback's one-time code for a refresh token and store it."""
    data = _token_request(
        {
            "code": code,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        }
    )
    refresh = data.get("refresh_token")
    if not refresh:
        raise GoogleAuthError(
            "Google didn't return a refresh token. Revoke this app's access at "
            "myaccount.google.com/permissions and connect again."
        )
    with db.db_session() as conn:
        db.set_setting(conn, SETTING_KEY, refresh)
    _cache(data.get("access_token"), data.get("expires_in"))
    log.info("google: connected, refresh token stored")


def disconnect() -> None:
    global _access_token, _expires_at
    with db.db_session() as conn:
        db.set_setting(conn, SETTING_KEY, None)
    _access_token, _expires_at = None, 0.0
    log.info("google: disconnected")


def access_token() -> str:
    global _access_token
    if _access_token and time.time() < _expires_at:
        return _access_token

    refresh = stored_refresh_token()
    if not refresh:
        raise GoogleAuthError("Not connected to Google — click Connect Google Sheets.")
    data = _token_request({"refresh_token": refresh, "grant_type": "refresh_token"})
    token = data.get("access_token")
    if not token:
        raise GoogleAuthError(f"Google returned no access token: {str(data)[:300]}")
    _cache(token, data.get("expires_in"))
    return token


def _cache(token: str | None, expires_in) -> None:
    global _access_token, _expires_at
    if not token:
        return
    try:
        lifetime = int(expires_in)
    except (TypeError, ValueError):
        lifetime = 3600
    _access_token = token
    _expires_at = time.time() + max(lifetime - _EXPIRY_MARGIN, 0)


def _token_request(extra: dict) -> dict:
    payload = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        **extra,
    }
    try:
        resp = httpx.post(TOKEN_URL, data=payload, timeout=REQUEST_TIMEOUT)
    except httpx.HTTPError as exc:
        raise GoogleAuthError(f"Could not reach Google: {exc}") from exc
    if resp.status_code >= 400:
        body = resp.text[:500]
        # The one failure worth naming: a revoked/expired refresh token. Google
        # says "invalid_grant", which tells Andrew nothing about what to do.
        if "invalid_grant" in body:
            raise GoogleAuthError(
                "Google connection expired or was revoked — click Connect Google Sheets again."
            )
        raise GoogleAuthError(f"Google token request failed: {resp.status_code} {body}")
    return resp.json()
