from django.urls import re_path
from .consumers import AgentConsumer

websocket_urlpatterns = [
    re_path(r'^ws/agent/$', AgentConsumer.as_asgi()),
]
