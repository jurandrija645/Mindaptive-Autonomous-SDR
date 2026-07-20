"""Self-hosted image hosting for draft attachments.

Images pasted or dropped into the draft editor are saved under /data/uploads
(the same Docker volume as the SQLite db, so they survive redeploys) and served
back at an absolute PUBLIC_BASE_URL/i/<name> URL. That URL has to be reachable
*without a session* — the recipient's mail client fetches it, and it has no
cookie — which is why GET /i/{name} is the one unauthenticated read route in
the app. The filename is a random token, so the URL is the capability: nothing
can be enumerated by guessing.
"""

import logging
import re
import secrets
from pathlib import Path

from app.config import settings

log = logging.getLogger("uploads")

UPLOAD_DIR = Path(settings.upload_dir)
MAX_BYTES = 8 * 1024 * 1024

# Sniffed from the bytes themselves rather than trusting the browser's
# Content-Type — an <img src> is only ever going to render these four, and
# anything else (svg especially, which can carry script) has no business being
# written into a public directory.
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{8,64}\.(png|jpg|gif|webp)$")


def _sniff(data: bytes) -> tuple[str, str] | None:
    """(extension, content-type) for a supported image, else None."""
    for magic, ext, ctype in _SIGNATURES:
        if data.startswith(magic):
            return ext, ctype
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def save_image(data: bytes) -> tuple[str, str]:
    """Write an uploaded image and return (public_url, filename).

    Raises ValueError on anything that isn't a supported image within the size
    cap — the caller turns that into a 400.
    """
    if not data:
        raise ValueError("Empty file")
    if len(data) > MAX_BYTES:
        raise ValueError(f"Image is too large (max {MAX_BYTES // (1024 * 1024)} MB)")
    sniffed = _sniff(data)
    if not sniffed:
        raise ValueError("Unsupported file type — use PNG, JPG, GIF or WEBP")
    ext, _ctype = sniffed

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_urlsafe(16)}.{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    log.info("stored upload %s (%d bytes)", name, len(data))
    return f"{settings.public_base_url.rstrip('/')}/i/{name}", name


def resolve(name: str) -> tuple[Path, str] | None:
    """(path, content-type) for a stored upload, or None if it isn't one.

    The name pattern is validated before it ever touches the filesystem, so a
    traversal attempt ("../responder.db") fails the regex rather than the path
    check.
    """
    if not _SAFE_NAME.match(name or ""):
        return None
    path = UPLOAD_DIR / name
    if not path.is_file():
        return None
    ext = name.rsplit(".", 1)[1]
    ctype = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }[ext]
    return path, ctype
