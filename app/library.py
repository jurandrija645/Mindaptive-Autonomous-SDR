"""The attachment library: files Andrew sends often, kept on the server.

Smartlead does not take an upload. `reply-email-thread`'s `attachments[]` wants
a `file_url` that **Smartlead's own servers fetch** (verified 2026-07-31, see
docs/smartlead-api.md), so every attachable file has to sit behind a public,
sessionless URL — the same constraint that makes `GET /i/{name}` the one
unauthenticated read route in the app. `GET /f/{slug}` is the second, for the
same reason and with the same reasoning: the recipient's mail server is not
logged in, and neither is Smartlead's.

Two sources, one list:

    clients/<slug>/source-docs/   shipped in the image (Dockerfile COPY clients)
                                  and versioned in git. The partner-program PDF
                                  and friends live here, so they are simply
                                  *present* on a fresh container with nothing to
                                  upload first.
    /data/library/                uploaded from the dashboard, on the same
                                  Docker volume as the database, so it survives
                                  a redeploy. This is how a new PDF gets added
                                  without a code change or a deploy.

A file is addressed by a **slug** derived from its name ("AeroDefense Partner
Program (1).pdf" -> "aerodefense-partner-program-1.pdf") because the real names
carry spaces and parentheses that have no business in a URL. The slug is never
joined onto a path: `resolve()` looks it up in a freshly-built mapping of files
that actually exist, so a traversal attempt simply isn't in the dict. That is
the same property `uploads.resolve` gets from its regex, arrived at differently
because these names are human, stable and not secret.

Stable is the point — the URL of a library file has to keep working, since a
previously sent email references it forever.
"""

import logging
import re
import unicodedata
from pathlib import Path

from app import client_assets
from app.config import settings

log = logging.getLogger("library")

# Uploaded files. Sits next to /data/uploads on the same volume; kept separate
# so the image directory stays exactly what it was.
LIBRARY_DIR = Path(settings.upload_dir).parent / "library"

# Repo-shipped collateral for this client. Read-only: nothing writes here at
# runtime, it changes by committing a file.
SOURCE_DOCS_DIR = client_assets.CLIENT_DIR / "source-docs"

MAX_BYTES = 25 * 1024 * 1024

# Magic-byte sniffing, same reasoning as uploads.py: the browser's declared
# Content-Type is not evidence. Office formats are ZIPs, so PK.. is as far as
# sniffing gets us and the extension decides which of them it is — that's fine,
# because nothing here is ever executed or rendered as HTML; it is written to
# disk and later streamed back with an explicit Content-Type.
_MAGIC = (
    (b"%PDF-", {"pdf"}),
    (b"PK\x03\x04", {"docx", "xlsx", "pptx", "zip"}),
    (b"\x89PNG\r\n\x1a\n", {"png"}),
    (b"\xff\xd8\xff", {"jpg", "jpeg"}),
    (b"GIF87a", {"gif"}),
    (b"GIF89a", {"gif"}),
    (b"\xd0\xcf\x11\xe0", {"doc", "xls", "ppt"}),
)

_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    "ppt": "application/vnd.ms-powerpoint",
    "zip": "application/zip",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
}

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")


def content_type_for(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def slugify(name: str) -> str:
    """"AeroDefense Partner Program (1).pdf" -> "aerodefense-partner-program-1.pdf".

    Keeps the extension, since that is what picks the Content-Type on the way
    back out and what a mail client uses to choose an icon.
    """
    stem, _, ext = name.rpartition(".")
    if not stem:  # no extension at all
        stem, ext = name, ""
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", stem).strip("-").lower()
    ext = re.sub(r"[^a-zA-Z0-9]+", "", ext).lower()
    stem = stem or "file"
    return f"{stem}.{ext}" if ext else stem


def _sniff_ok(data: bytes, ext: str) -> bool:
    for magic, exts in _MAGIC:
        if data.startswith(magic):
            return ext in exts
    return False


def _entries() -> dict[str, Path]:
    """slug -> path, for every file in either source. Rebuilt per call: the
    library is a handful of files and a stale cache would hide a just-uploaded
    one. Uploads win a slug collision, so replacing a shipped file is possible
    without a deploy."""
    found: dict[str, Path] = {}
    for directory in (SOURCE_DOCS_DIR, LIBRARY_DIR):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and not path.name.startswith("."):
                found[slugify(path.name)] = path
    return found


def listing() -> list[dict]:
    """Everything attachable, newest-looking name first is not useful here — so
    plain alphabetical, with the shipped docs and the uploads interleaved."""
    out = []
    for slug, path in sorted(_entries().items()):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        out.append(
            {
                "slug": slug,
                "file_name": path.name,
                "file_type": content_type_for(path.name),
                "file_size": size,
                "url": public_url(slug),
                "source": "uploaded" if path.parent == LIBRARY_DIR else "shipped",
            }
        )
    return out


def public_url(slug: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/f/{slug}"


def resolve(slug: str) -> tuple[Path, str, str] | None:
    """(path, content-type, original file name) for a library slug, else None.

    The slug is matched against the regex and then *looked up* — never joined
    onto a directory — so "../responder.db" fails twice over.
    """
    if not _SLUG_RE.match(slug or ""):
        return None
    path = _entries().get(slug)
    if not path or not path.is_file():
        return None
    return path, content_type_for(path.name), path.name


def save(data: bytes, filename: str) -> dict:
    """Write an uploaded file into the library and return its listing entry.

    Raises ValueError on anything unsupported or oversized; the caller turns
    that into a 400.
    """
    if not data:
        raise ValueError("Empty file")
    if len(data) > MAX_BYTES:
        raise ValueError(f"File is too large (max {MAX_BYTES // (1024 * 1024)} MB)")

    slug = slugify(filename or "file")
    ext = slug.rsplit(".", 1)[-1] if "." in slug else ""
    if ext not in _CONTENT_TYPES:
        raise ValueError(f"Unsupported file type '.{ext}' — PDF, Office documents and images only")
    if not _sniff_ok(data, ext):
        raise ValueError(f"File does not look like a real .{ext}")

    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    path = LIBRARY_DIR / slug
    # Never silently overwrite a file a previously sent email still points at.
    if path.exists():
        stem, _, suffix = slug.rpartition(".")
        n = 2
        while path.exists():
            slug = f"{stem}-{n}.{suffix}" if suffix else f"{stem}-{n}"
            path = LIBRARY_DIR / slug
            n += 1

    path.write_bytes(data)
    log.info("library: stored %s (%d bytes) as %s", filename, len(data), slug)
    return {
        "slug": slug,
        "file_name": filename or path.name,
        "file_type": content_type_for(slug),
        "file_size": len(data),
        "url": public_url(slug),
        "source": "uploaded",
    }


def delete(slug: str) -> bool:
    """Remove an uploaded file. Shipped source-docs are not deletable from the
    dashboard — they come back on the next deploy, so pretending otherwise
    would be a lie."""
    if not _SLUG_RE.match(slug or ""):
        return False
    path = LIBRARY_DIR / slug
    if not path.is_file():
        return False
    path.unlink()
    log.info("library: deleted %s", slug)
    return True
