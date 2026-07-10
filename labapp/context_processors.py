"""
Template context processors for the MI Lab app.
"""
from __future__ import annotations

from .models import Announcement, WeeklyUpdate


def unread_updates(request):
    """Expose unread counts for Announcements / Weekly Updates / their total,
    similar to the unread-message badges used in mobile apps.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}

    is_faculty = user.is_staff or user.is_superuser or (
        getattr(user, 'is_faculty', lambda: False)())

    ann_since = user.last_seen_announcements or user.date_joined
    unread_announcements = Announcement.objects.filter(created_at__gt=ann_since).count()

    wu_since = user.last_seen_weekly_updates or user.date_joined
    wu_qs = WeeklyUpdate.objects.all() if is_faculty else WeeklyUpdate.objects.filter(user=user)
    unread_weekly_updates = wu_qs.filter(created_at__gt=wu_since).count()

    return {
        'unread_announcements_count': unread_announcements,
        'unread_weekly_updates_count': unread_weekly_updates,
        'unread_updates_total': unread_announcements + unread_weekly_updates,
    }
