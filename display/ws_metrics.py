"""
WebSocket metrics and monitoring utilities.

Tracks connection counts, broadcast success/failure rates, and performance.
Critical for production monitoring with 500+ schools.
"""

import logging
import time
from threading import Lock
from typing import Dict, Any

logger = logging.getLogger(__name__)


class WSMetrics:
    """
    Thread-safe WebSocket metrics tracker.
    
    Metrics tracked:
    - Connection count (current active)
    - Total connections (lifetime)
    - Broadcast success/failure counts
    - Average broadcast latency
    """
    
    def __init__(self):
        self._lock = Lock()
        self._metrics: Dict[str, Any] = {
            "connections_active": 0,
            "connections_total": 0,
            "connections_failed": 0,
            "broadcasts_sent": 0,
            "broadcasts_failed": 0,
            "broadcast_latency_sum": 0.0,
            "broadcast_latency_count": 0,
            "last_logged": 0,
        }
    
    def connection_opened(self):
        """Called when WS connection established."""
        with self._lock:
            self._metrics["connections_active"] += 1
            self._metrics["connections_total"] += 1
    
    def connection_closed(self):
        """Called when WS connection closed."""
        with self._lock:
            self._metrics["connections_active"] = max(0, self._metrics["connections_active"] - 1)
    
    def connection_failed(self):
        """Called when WS connection fails during handshake."""
        with self._lock:
            self._metrics["connections_failed"] += 1
    
    def broadcast_sent(self, latency_ms: float = 0.0):
        """Called when broadcast successfully sent."""
        with self._lock:
            self._metrics["broadcasts_sent"] += 1
            if latency_ms > 0:
                self._metrics["broadcast_latency_sum"] += latency_ms
                self._metrics["broadcast_latency_count"] += 1
    
    def broadcast_failed(self):
        """Called when broadcast fails."""
        with self._lock:
            self._metrics["broadcasts_failed"] += 1
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get current metrics snapshot (thread-safe)."""
        with self._lock:
            return self._metrics.copy()
    
    def log_if_needed(self, interval_seconds: int = 300):
        """
        Log metrics if enough time has passed.
        
        Args:
            interval_seconds: Log every N seconds (default 5 min)
        """
        now = time.time()
        with self._lock:
            last = self._metrics["last_logged"]
            if now - last < interval_seconds:
                return
            
            self._metrics["last_logged"] = now
            active = self._metrics["connections_active"]
            total = self._metrics["connections_total"]
            failed = self._metrics["connections_failed"]
            sent = self._metrics["broadcasts_sent"]
            b_failed = self._metrics["broadcasts_failed"]
            
            avg_latency = 0.0
            if self._metrics["broadcast_latency_count"] > 0:
                avg_latency = (
                    self._metrics["broadcast_latency_sum"] / 
                    self._metrics["broadcast_latency_count"]
                )
            
            logger.info(
                f"[WS Metrics] Active: {active} | Total: {total} | Failed: {failed} | "
                f"Broadcasts: {sent} (failed: {b_failed}) | Avg Latency: {avg_latency:.1f}ms"
            )


# Global metrics instance
ws_metrics = WSMetrics()
