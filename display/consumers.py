"""
WebSocket consumer for display screens.

Phase 1 (Server-Side Readiness):
    - Token validation (query param: token=xxx)
    - Device binding enforcement (dk required)
    - Tenant isolation (server-derived group: school:<id>)
    - Broadcast handler for invalidation messages
    - Ping/pong keepalive

Phase 2 (Dark Launch):
    - Clients may connect (optional), but polling remains active
    
Security:
    - Token is sole source of identity
    - No client-supplied school_id accepted
    - Server derives group from screen.school_id only
    - dk binding prevents multi-device access (respects DISPLAY_ALLOW_MULTI_DEVICE)
"""

import json
import logging
import time
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

from display.services import (
    ScreenBoundError,
    ScreenNotFoundError,
    bind_device_atomic,
)
from display.ws_metrics import ws_metrics

logger = logging.getLogger(__name__)


class DisplayConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for realtime display screen updates.
    
    Connection URL: ws://domain/ws/display/?token=<token>&dk=<device_id>
    
    Lifecycle:
        1. connect() → validate token + bind device → join school group
        2. receive() → handle ping/pong keepalive
        3. broadcast_invalidate() → send {type: "invalidate", revision: X}
        4. disconnect() → leave group
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.screen = None
        self.school_group_name = None
        self.device_id = None
    
    async def connect(self):
        """
        Validate token + device binding, then join school group.
        
        Close codes:
            4400: Missing token or dk
            4403: Token invalid or screen inactive
            4408: Screen bound to different device
        """
        # Parse query params
        query_string = self.scope.get("query_string", b"").decode()
        query_params = parse_qs(query_string)
        
        token = query_params.get("token", [None])[0]
        self.device_id = query_params.get("dk", [None])[0]
        
        # Validate required params
        if not token or not self.device_id:
            logger.warning("WS connect rejected: missing token or dk")
            ws_metrics.connection_failed()
            await self.close(code=4400)
            return
        
        # Bind device atomically (thread-safe)
        try:
            # Synchronous call wrapped in sync_to_async (Channels does this automatically for DB)
            from channels.db import database_sync_to_async
            self.screen = await database_sync_to_async(bind_device_atomic)(
                token=token,
                device_id=self.device_id
            )
        except ScreenNotFoundError:
            logger.warning(f"WS connect rejected: token not found {token[:8]}...")
            ws_metrics.connection_failed()
            await self.close(code=4403)
            return
        except ScreenBoundError:
            logger.warning(
                f"WS connect rejected: screen {token[:8]}... bound to different device"
            )
            ws_metrics.connection_failed()
            await self.close(code=4408)
            return
        except Exception as e:
            logger.exception(f"WS connect error: {e}")
            ws_metrics.connection_failed()
            await self.close(code=4500)
            return
        
        # Server-derived group (tenant isolation)
        self.school_group_name = f"school:{self.screen.school_id}"
        
        # Join school group
        await self.channel_layer.group_add(
            self.school_group_name,
            self.channel_name
        )
        
        # Accept connection
        await self.accept()
        
        # Track successful connection
        ws_metrics.connection_opened()
        
        logger.info(
            f"WS connected: screen {self.screen.id} (school {self.screen.school_id}) "
            f"device {self.device_id[:8]}... group {self.school_group_name}"
        )
        
        # Log metrics periodically (every 5 minutes)
        ws_metrics.log_if_needed(interval_seconds=300)
    
    async def disconnect(self, close_code):
        """Leave school group on disconnect."""
        # Track disconnection
        ws_metrics.connection_closed()
        
        if self.school_group_name:
            await self.channel_layer.group_discard(
                self.school_group_name,
                self.channel_name
            )
            logger.info(
                f"WS disconnected: screen {self.screen.id if self.screen else '?'} "
                f"code {close_code} group {self.school_group_name}"
            )
    
    async def receive(self, text_data=None, bytes_data=None):
        """
        Handle client messages (ping/pong keepalive only).
        
        Client may send: {"type": "ping"}
        Server responds: {"type": "pong"}
        """
        if not text_data:
            return
        
        try:
            data = json.loads(text_data)
            msg_type = data.get("type")
            
            if msg_type == "ping":
                await self.send(text_data=json.dumps({"type": "pong"}))
            else:
                logger.debug(f"WS received unknown message type: {msg_type}")
        except json.JSONDecodeError:
            logger.warning(f"WS received invalid JSON: {text_data[:100]}")
        except Exception as e:
            logger.exception(f"WS receive error: {e}")
    
    async def broadcast_invalidate(self, event):
        """
        Handle broadcast message from signals.
        
        Event structure (from channel_layer.group_send):
        {
            "type": "broadcast_invalidate",  # method name (snake_case)
            "revision": 123,
            "school_id": 5
        }
        
        Sends to client:
        {
            "type": "invalidate",
            "revision": 123
        }
        """
        revision = event.get("revision")
        school_id = event.get("school_id")
        
        # Sanity check: only send if school_id matches (defensive)
        if self.screen and school_id != self.screen.school_id:
            logger.warning(
                f"WS broadcast mismatch: screen school {self.screen.school_id} "
                f"got message for school {school_id}"
            )
            return
        
        # Send invalidate message to client
        start_time = time.time()
        try:
            await self.send(text_data=json.dumps({
                "type": "invalidate",
                "revision": revision
            }))
            
            # Track successful broadcast
            latency_ms = (time.time() - start_time) * 1000
            ws_metrics.broadcast_sent(latency_ms)
            
            logger.debug(
                f"WS sent invalidate: screen {self.screen.id if self.screen else '?'} "
                f"revision {revision} latency {latency_ms:.1f}ms"
            )
        except Exception as e:
            ws_metrics.broadcast_failed()
            logger.exception(f"WS broadcast send failed: {e}")

