from __future__ import annotations

import hashlib
from typing import Optional

from django.core.cache import cache
from django.utils import timezone

from core.models import DisplayScreen

from .cache_utils import keys


TOKEN_SCHOOL_TTL = 60 * 60  # 1 hour


def get_school_id_by_token(token: str) -> int | None:
    """Resolve school_id for a display token with a short cache.

    - Reads a dedicated token->school cache first.
    - Falls back to existing token_map cache (if present) without overriding its TTL.
    - Touches DB only on first miss.
    """
    token = (token or "").strip()
    if not token:
        return None

    ck = keys.token_school(token)
    cached = cache.get(ck)
    if cached is not None:
        try:
            return int(cached)
        except Exception:
            return None

    # Reuse existing project-wide token_map cache if available.
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    map_key = f"display:token_map:{token_hash}"
    cached_map = cache.get(map_key)
    if isinstance(cached_map, dict) and cached_map.get("school_id"):
        try:
            school_id = int(cached_map.get("school_id"))
            cache.set(ck, str(school_id), timeout=TOKEN_SCHOOL_TTL)
            return school_id
        except Exception:
            pass
    elif isinstance(cached_map, (int, str)):
        try:
            school_id = int(cached_map)
            cache.set(ck, str(school_id), timeout=TOKEN_SCHOOL_TTL)
            return school_id
        except Exception:
            pass

    # DB lookup (first request per token).
    qs = DisplayScreen.objects.filter(token__iexact=token)
    try:
        qs = qs.filter(is_active=True)
    except Exception:
        pass

    obj = qs.only("id", "school_id").first()
    if not obj or not getattr(obj, "school_id", None):
        return None

    school_id = int(obj.school_id)
    cache.set(ck, str(school_id), timeout=TOKEN_SCHOOL_TTL)
    return school_id


def get_day_key() -> str:
    # Local day (Asia/Riyadh configured in settings)
    return timezone.localdate().strftime("%Y%m%d")
