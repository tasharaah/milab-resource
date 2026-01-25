"""
ASGI config for the MI Lab project.

This file defines the ASGI callable so that Django can serve HTTP and
WebSocket requests. For more information on deploying with ASGI see
https://docs.djangoproject.com/en/stable/howto/deployment/asgi/
"""
from __future__ import annotations

import os

from django.core.asgi import get_asgi_application  # type: ignore

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mi_lab.settings')

application = get_asgi_application()