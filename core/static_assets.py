from __future__ import annotations

import mimetypes
import re
from pathlib import PurePosixPath
from urllib.parse import unquote

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import HttpResponse


_FINGERPRINT_RE = re.compile(r"(?:^|[._-])[0-9a-f]{8,}(?:[._-]|$)", re.IGNORECASE)


def normalize_static_path(path: str) -> str | None:
    raw = (path or "").strip()
    if not raw:
        return None

    try:
        cleaned = PurePosixPath(unquote(raw).lstrip("/"))
    except Exception:
        return None

    parts: list[str] = []
    for part in cleaned.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            return None
        parts.append(part)

    if not parts:
        return None
    return "/".join(parts)


def read_static_asset(path: str) -> tuple[str, bytes] | None:
    normalized = normalize_static_path(path)
    if not normalized:
        return None

    try:
        found_path = finders.find(normalized)
        if found_path:
            with open(found_path, "rb") as f:
                return normalized, f.read()
    except Exception:
        pass

    try:
        with staticfiles_storage.open(normalized, "rb") as f:
            return normalized, f.read()
    except Exception:
        return None


def static_cache_control(path: str, *, is_versioned: bool = False) -> str:
    normalized = normalize_static_path(path) or ""
    filename = normalized.rsplit("/", 1)[-1]
    if is_versioned or _FINGERPRINT_RE.search(filename):
        return "public, max-age=31536000, immutable"
    return "public, max-age=86400"


def build_static_response(
    path: str,
    *,
    method: str = "GET",
    cache_control: str | None = None,
    is_versioned: bool = False,
) -> HttpResponse | None:
    loaded = read_static_asset(path)
    if not loaded:
        return None

    normalized, content = loaded
    content_type, content_encoding = mimetypes.guess_type(normalized)

    body = b"" if str(method).upper() == "HEAD" else content
    response = HttpResponse(body, content_type=content_type or "application/octet-stream")
    response["Content-Length"] = str(len(content))
    response["Cache-Control"] = cache_control or static_cache_control(
        normalized,
        is_versioned=is_versioned,
    )
    if content_encoding:
        response["Content-Encoding"] = content_encoding
    return response
