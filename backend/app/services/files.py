"""Storing and serving uploaded submission files safely.

Threats handled here: path traversal (files are stored under random
names, never the client's), type confusion (extension allow-list AND a
magic-byte check), oversized uploads (hard byte cap), and inline
execution (downloads are always sent as attachments with nosniff).
NOT handled: malware scanning -- there is no offline scanner. That gap is
stated in THREAT-MODEL.md.
"""

import asyncio
import re
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

# Hard ceiling regardless of what a round asks for.
GLOBAL_MAX_MB = 50
ALLOWED_EXTS = {"pdf", "ppt", "pptx", "key", "doc", "docx", "png", "jpg", "jpeg", "gif", "webp", "zip", "md", "txt"}

_ZIPLIKE = {"pptx", "docx", "zip", "key"}
_MAGIC = {
    "pdf": [b"%PDF"],
    "png": [b"\x89PNG"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],
    "ppt": [b"\xd0\xcf\x11\xe0"],
    "doc": [b"\xd0\xcf\x11\xe0"],
}
_CONTENT_TYPES = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "zip": "application/zip",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/markdown", "txt": "text/plain", "key": "application/octet-stream",
}


def upload_root() -> Path:
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def clean_filename(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^\w.\- ]+", "_", name).strip(" .")
    return (name or "file")[:200]


def content_type_for(ext: str) -> str:
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def magic_ok(ext: str, head: bytes, data_has_nul: bool) -> bool:
    if ext in _ZIPLIKE:
        return head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06")
    if ext in _MAGIC:
        return any(head.startswith(sig) for sig in _MAGIC[ext])
    if ext in ("md", "txt"):
        return not data_has_nul
    return True


async def save_upload(file: UploadFile, allowed_exts: set[str], max_mb: int) -> tuple[str, str, str, int]:
    """Validate and store an upload. Returns (stored_name, clean_filename,
    content_type, size_bytes). Raises 400/413 with a clear message."""
    filename = clean_filename(file.filename or "file")
    ext = extension_of(filename)
    if ext not in ALLOWED_EXTS or ext not in allowed_exts:
        allowed = ", ".join(sorted(allowed_exts & ALLOWED_EXTS)) or "none"
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'.{ext or '?'}' files aren't allowed in this round. Allowed: {allowed}.")

    limit = min(max_mb, GLOBAL_MAX_MB) * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"That file is over the {min(max_mb, GLOBAL_MAX_MB)} MB limit.")
    if len(data) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That file is empty.")
    if not magic_ok(ext, data[:8], b"\x00" in data[:4096]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"That doesn't look like a real .{ext} file.")

    stored = secrets.token_hex(16)
    await asyncio.to_thread((upload_root() / stored).write_bytes, data)
    return stored, filename, content_type_for(ext), len(data)


def delete_stored(stored_name: str) -> None:
    try:
        (upload_root() / stored_name).unlink(missing_ok=True)
    except OSError:
        pass


def stored_path(stored_name: str) -> Path:
    path = upload_root() / stored_name
    # Belt and braces: stored names are random hex, but never serve
    # anything outside the upload directory.
    if path.resolve().parent != upload_root().resolve():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    return path
