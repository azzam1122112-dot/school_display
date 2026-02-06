"""
WebSocket URL routing for display screens.

All realtime invalidations are sent through:
    ws://domain/ws/display/
"""

from django.urls import path

from .consumers import DisplayConsumer

websocket_urlpatterns = [
    path("ws/display/", DisplayConsumer.as_asgi()),
]
