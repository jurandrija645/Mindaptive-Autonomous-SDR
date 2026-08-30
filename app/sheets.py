"""Minimal Google Sheets v4 client — just what the LinkedIn export needs.

Plain httpx rather than google-api-python-client/gspread: five REST calls, all
JSON, and adding an SDK would mean a new pin in requirements.txt and a rebuilt
pip layer for every deploy. Auth comes from app/google_oauth.py.

Everything here is additive. `append_row` writes below the last used row and
nothing else is ever written, so the hand-kept parts of Andrew's sheets — the
un-headered notes column, the green fills, the struck-through rows — are
untouched by an export.
"""

import logging
import time
from urllib.parse import quote

import httpx

from app import google_oauth

log = logging.getLogger("sheets")

BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"
REQUEST_TIMEOUT = 30.0


class SheetsError(RuntimeError):
    pass


def _request(method: str, path: str, params: dict | None = None, json: dict | None = None):
    """One Sheets call, retried on the transient statuses only.

    Mirrors smartlead._request: 429 (quota) and 5xx back off and retry, every
    other 4xx is a real error and raises immediately with the body truncated.
    """
    max_attempts = 4
    backoff = 1.5
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        headers = {"Authorization": f"Bearer {google_oauth.access_token()}"}
        try:
            resp = httpx.request(
                method,
                f"{BASE_URL}{path}",
                params=params,
                json=json,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise SheetsError(f"Could not reach Google Sheets: {exc}") from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = f"{resp.status_code} {resp.text[:200]}"
            if attempt == max_attempts:
                break
            time.sleep(backoff ** attempt)
            continue
        if resp.status_code == 403:
            raise SheetsError(
                "Google refused access to the spreadsheet — check the Google Sheets API "
                f"is enabled and the connected account can edit it. ({resp.text[:300]})"
            )
        if resp.status_code == 404:
            raise SheetsError(
                f"Spreadsheet not found — check LINKEDIN_SHEET_ID. ({resp.text[:200]})"
            )
        if resp.status_code >= 400:
            raise SheetsError(f"Sheets {method} {path} failed: {resp.status_code} {resp.text[:500]}")
        return resp.json() if resp.content else {}
    raise SheetsError(f"Sheets {method} {path} failed after {max_attempts} attempts: {last_error}")


def _range(tab: str, cells: str) -> str:
    """URL path segment for an A1 range on a tab, e.g. "'Mia'!A1".

    Two encodings, both required. Sheets wraps a tab title in `'` and escapes a
    literal apostrophe by doubling it. Then the whole thing is percent-encoded
    with nothing left safe, because tab titles come out of Andrew's spreadsheet
    rather than from here: a title containing `?` or `#` would otherwise be
    parsed as the start of the query or fragment, and the request would quietly
    read or write a different range than the one asked for — which, since the
    header row is what places every value, is how data ends up in the wrong
    column. httpx leaves valid percent-escapes alone, so this isn't doubled up.
    """
    return quote(f"'{tab.replace(chr(39), chr(39) * 2)}'!{cells}", safe="")


def list_tabs(sheet_id: str) -> list[str]:
    data = _request("GET", f"/{sheet_id}", params={"fields": "sheets.properties.title"})
    return [
        (sheet.get("properties") or {}).get("title", "")
        for sheet in data.get("sheets") or []
        if (sheet.get("properties") or {}).get("title")
    ]


def read_range(sheet_id: str, tab: str, cells: str) -> list[list[str]]:
    data = _request("GET", f"/{sheet_id}/values/{_range(tab, cells)}")
    return data.get("values") or []


def read_header(sheet_id: str, tab: str) -> list[str]:
    """Row 1 of the tab, as written. The export maps values onto these by name,
    so a reordered or extra column can't push data into the wrong place."""
    rows = read_range(sheet_id, tab, "1:1")
    return [str(cell).strip() for cell in (rows[0] if rows else [])]


def read_column(sheet_id: str, tab: str, column: str) -> list[str]:
    """One column, top to bottom, including the header cell. Index in the
    returned list + 1 is the sheet row number."""
    rows = read_range(sheet_id, tab, f"{column}1:{column}")
    return [str(row[0]).strip() if row else "" for row in rows]


def append_row(sheet_id: str, tab: str, values: list[str]) -> int | None:
    """Append below the last used row. Returns the row number it landed on.

    USER_ENTERED (not RAW) so URLs become real links and dates/phone numbers are
    typed the way the rows Andrew added by hand already are. INSERT_ROWS so the
    write can never land on top of anything below the table.
    """
    data = _request(
        "POST",
        f"/{sheet_id}/values/{_range(tab, 'A1')}:append",
        params={
            "valueInputOption": "USER_ENTERED",
            "insertDataOption": "INSERT_ROWS",
        },
        json={"values": [values]},
    )
    updated = (data.get("updates") or {}).get("updatedRange") or ""
    log.info("sheets: appended a row to %s (%s)", tab, updated or "range unknown")
    return _row_from_range(updated)


def create_tab(sheet_id: str, title: str) -> None:
    _request(
        "POST",
        f"/{sheet_id}:batchUpdate",
        json={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    )
    log.info("sheets: created tab %r", title)


def write_range(sheet_id: str, tab: str, cells: str, values: list[str], raw: bool = False) -> None:
    """PUT a single row of values into cells, e.g. "A1" or "G16".

    USER_ENTERED by default so a boolean-looking value like "TRUE" becomes a
    real checkbox value rather than the literal string, same as append_row.
    raw=True keeps write_header's original RAW behavior for plain header text.
    """
    _request(
        "PUT",
        f"/{sheet_id}/values/{_range(tab, cells)}",
        params={"valueInputOption": "RAW" if raw else "USER_ENTERED"},
        json={"values": [values]},
    )


def write_header(sheet_id: str, tab: str, header: list[str]) -> None:
    write_range(sheet_id, tab, "A1", header, raw=True)


def _row_from_range(a1: str) -> int | None:
    """Row number out of an updatedRange like "'Max'!A16:J16"."""
    cell = a1.rsplit("!", 1)[-1].split(":", 1)[0]
    digits = "".join(ch for ch in cell if ch.isdigit())
    return int(digits) if digits else None
