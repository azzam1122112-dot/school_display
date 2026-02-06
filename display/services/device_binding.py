"""
Device binding utilities for display screens.

Enforces atomic single-device binding to prevent race conditions.
Used by both HTTP snapshot endpoint and WebSocket consumer.
"""

import logging
from typing import Optional

from django.conf import settings
from django.utils import timezone

from core.models import DisplayScreen

logger = logging.getLogger(__name__)


class DeviceBindingError(Exception):
    """Base exception for device binding failures."""
    pass


class ScreenBoundError(DeviceBindingError):
    """Screen is already bound to a different device."""
    pass


class ScreenNotFoundError(DeviceBindingError):
    """Screen token not found."""
    pass


def bind_device_atomic(
    token: str, 
    device_id: str, 
    allow_multi_device: Optional[bool] = None
) -> DisplayScreen:
    """
    Atomically bind a device to a display screen.
    
    Args:
        token: Screen token (DisplayScreen.token)
        device_id: Client device identifier (browser fingerprint)
        allow_multi_device: Override for DISPLAY_ALLOW_MULTI_DEVICE
        
    Returns:
        DisplayScreen instance (bound or already bound to this device)
        
    Raises:
        ScreenNotFoundError: Token not found or inactive
        ScreenBoundError: Screen already bound to different device
    
    Thread-safe: Uses conditional UPDATE (WHERE bound_device_id IS NULL)
    """
    if allow_multi_device is None:
        allow_multi_device = getattr(settings, "DISPLAY_ALLOW_MULTI_DEVICE", False)
    
    try:
        screen = DisplayScreen.objects.select_related("school").get(
            token=token,
            is_active=True
        )
    except DisplayScreen.DoesNotExist:
        logger.warning(f"bind_device_atomic: token not found: {token[:8]}...")
        raise ScreenNotFoundError(f"Screen token not found or inactive")
    
    # If multi-device allowed, skip binding enforcement
    if allow_multi_device:
        logger.info(f"Multi-device enabled for screen {screen.id}, skipping binding")
        return screen
    
    # Check if already bound to THIS device
    if screen.bound_device_id == device_id:
        logger.debug(f"Screen {screen.id} already bound to device {device_id[:8]}...")
        return screen
    
    # Check if bound to DIFFERENT device
    if screen.bound_device_id and screen.bound_device_id != device_id:
        logger.warning(
            f"Screen {screen.id} bound to {screen.bound_device_id[:8]}..., "
            f"rejecting {device_id[:8]}..."
        )
        raise ScreenBoundError(
            f"This screen is already active on another device. "
            f"Only one device can display a screen at a time."
        )
    
    # Atomic binding: UPDATE only if bound_device_id IS NULL
    rows_updated = DisplayScreen.objects.filter(
        id=screen.id,
        bound_device_id__isnull=True
    ).update(
        bound_device_id=device_id,
        bound_at=timezone.now()
    )
    
    if rows_updated == 0:
        # Race condition: another device bound it between SELECT and UPDATE
        screen.refresh_from_db()
        if screen.bound_device_id == device_id:
            # We won! (unlikely but possible if multiple requests from same device)
            logger.info(f"Screen {screen.id} bound to device {device_id[:8]}... (race won)")
            return screen
        else:
            # Another device won the race
            logger.warning(
                f"Screen {screen.id} bound to {screen.bound_device_id[:8]}... "
                f"during race, rejecting {device_id[:8]}..."
            )
            raise ScreenBoundError(
                f"This screen was just activated on another device. "
                f"Only one device can display a screen at a time."
            )
    
    # Success: we bound it
    screen.refresh_from_db()
    logger.info(f"Screen {screen.id} newly bound to device {device_id[:8]}...")
    return screen


def unbind_device(screen_id: int) -> bool:
    """
    Unbind device from screen (for admin/debug purposes).
    
    Returns:
        True if unbound, False if screen not found
    """
    rows_updated = DisplayScreen.objects.filter(id=screen_id).update(
        bound_device_id=None,
        bound_at=None
    )
    if rows_updated:
        logger.info(f"Unbound device from screen {screen_id}")
        return True
    return False
