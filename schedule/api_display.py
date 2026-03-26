# schedule/api_display.py
from __future__ import annotations

from typing import Optional

from django.views.decorators.http import require_GET

from . import api_views


@require_GET
def snapshot(request, token: Optional[str] = None):
    """
    Legacy compatibility wrapper.

    Source of truth for display snapshot logic is `schedule.api_views.snapshot`.
    Keeping this wrapper avoids drift if any old import/path still points here.
    """
    return api_views.snapshot(request, token=token)
