"""
WSGI config for the MI Lab project.

It exposes the WSGI callable as a module-level variable named
``application``. Django’s deployment documentation provides more
information:
https://docs.djangoproject.com/en/stable/howto/deployment/wsgi/
"""
from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application  # type: ignore

# Set the default settings module for the 'application' object.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mi_lab.settings')

application = get_wsgi_application()