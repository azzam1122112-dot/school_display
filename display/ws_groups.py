from __future__ import annotations

import hashlib
import re

# Channels group names must be < 100 chars and contain only [A-Za-z0-9_.-].
_GROUP_RE = re.compile(r"^[A-Za-z0-9_.-]{1,99}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def is_valid_ws_group_name(name: str) -> bool:
    return bool(_GROUP_RE.fullmatch((name or "").strip()))


def _safe_fragment(value: object, *, fallback: str) -> str:
    raw = str(value if value is not None else "").strip()
    if not raw:
        return fallback
    # Replace invalid characters (including ':') with '_'.
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", raw)
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def school_group_name(school_id: object) -> str:
    base = _safe_fragment(school_id, fallback="0")
    name = f"school_{base}"
    return name[:99]


def token_group_name(token: str, *, hash_len: int = 16) -> str:
    raw = str(token or "").strip().lower()
    if _SHA256_HEX_RE.fullmatch(raw):
        digest = raw
    else:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    n = max(8, min(int(hash_len or 16), 64))
    name = f"token_{digest[:n]}"
    return name[:99]
