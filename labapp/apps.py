"""
AppConfig for the labapp application. This class informs Django about
the application and can be used to configure application-level
settings.
"""
from __future__ import annotations

from django.apps import AppConfig


class LabappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'labapp'
    verbose_name = 'MI Lab Resource Manager'