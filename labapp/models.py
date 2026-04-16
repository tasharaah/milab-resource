"""
Database models for the MI Lab resource management application.
"""
from __future__ import annotations

import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import datetime
from django.contrib.auth.hashers import make_password


class User(AbstractUser):
    class Role(models.TextChoices):
        RA      = 'RA',      'Research Assistant'
        STUDENT = 'Student', 'Student'
        INTERN  = 'Intern',  'Intern'
        FACULTY = 'Faculty', 'Faculty'

    role  = models.CharField(max_length=10, choices=Role.choices, default=Role.RA)
    phone = models.CharField(max_length=20, blank=True)
    bio   = models.TextField(blank=True, help_text='Short bio or description')

    def is_ra(self)      -> bool: return self.role == self.Role.RA
    def is_student(self) -> bool: return self.role == self.Role.STUDENT
    def is_intern(self)  -> bool: return self.role == self.Role.INTERN
    def is_faculty(self) -> bool: return self.role == self.Role.FACULTY

    def __str__(self) -> str:
        return self.username


class Resource(models.Model):
    class ResourceType(models.TextChoices):
        PC     = 'PC',     'PC'
        RUNPOD = 'RUNPOD', 'RunPod'

    class Status(models.TextChoices):
        OK          = 'OK',          'OK'
        MAINTENANCE = 'MAINTENANCE', 'Maintenance'
        DISABLED    = 'DISABLED',    'Disabled'

    name          = models.CharField(max_length=100, unique=True)
    resource_type = models.CharField(max_length=20, choices=ResourceType.choices, default=ResourceType.PC)
    status        = models.CharField(max_length=20, choices=Status.choices, default=Status.OK)
    description   = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        # Always title-case the name before saving
        if self.name:
            self.name = self.name.strip().title()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name

    @property
    def available(self) -> bool:
        if self.status != self.Status.OK:
            return False
        now = timezone.now()
        return not self.bookings.filter(
            is_active=True, start_time__lte=now, end_time__gte=now,
        ).exists()


class Project(models.Model):
    class Status(models.TextChoices):
        UPCOMING  = 'UPCOMING',  'Upcoming'
        PROPOSED  = 'PROPOSED',  'Proposed'
        ONGOING   = 'ONGOING',   'Ongoing'
        COMPLETED = 'COMPLETED', 'Completed'

    name                       = models.CharField(max_length=200, unique=True)
    principal_investigator     = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pi_projects')
    co_principal_investigators = models.ManyToManyField(User, blank=True, related_name='co_pi_projects')
    research_assistants        = models.ManyToManyField(User, blank=True, related_name='ra_projects')
    grant                      = models.CharField(max_length=300, blank=True)
    status                     = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED)
    start_date                 = models.DateField(null=True, blank=True)
    estimated_budget_bdt       = models.BigIntegerField(null=True, blank=True)
    eta                        = models.DateField(null=True, blank=True, verbose_name='Estimated Completion')
    created_at                 = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return self.name

    def is_member(self, user) -> bool:
        """Return True if user has any role in this project."""
        if user.is_staff or user.is_superuser:
            return True
        if self.principal_investigator == user:
            return True
        if self.co_principal_investigators.filter(pk=user.pk).exists():
            return True
        if self.research_assistants.filter(pk=user.pk).exists():
            return True
        return False

    def can_edit_links(self, user) -> bool:
        """Only PI, co-PI, or admin can edit collaboration links."""
        if user.is_staff or user.is_superuser:
            return True
        if self.principal_investigator == user:
            return True
        if self.co_principal_investigators.filter(pk=user.pk).exists():
            return True
        return False


class ProjectLink(models.Model):
    """A collaboration link attached to a project (Overleaf, Drive, etc.)."""

    PLATFORM_CHOICES = [
        ('overleaf',    'Overleaf'),
        ('google_doc',  'Google Doc'),
        ('drive',       'Google Drive'),
        ('notion',      'Notion'),
        ('github',      'GitHub'),
        ('other',       'Other'),
    ]
    PLATFORM_ICONS = {
        'overleaf':   'fa-leaf',
        'google_doc': 'fa-file-word',
        'drive':      'fa-hard-drive',
        'notion':     'fa-n',
        'github':     'fa-brands fa-github',
        'other':      'fa-link',
    }

    project  = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='links')
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='other')
    url      = models.URLField(max_length=500)
    label    = models.CharField(max_length=100, blank=True, help_text='Optional display label')
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='added_links')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['platform', 'id']

    def __str__(self) -> str:
        return f"{self.get_platform_display()} – {self.project.name}"

    @property
    def display_label(self) -> str:
        return self.label or self.get_platform_display()

    @property
    def icon_class(self) -> str:
        return self.PLATFORM_ICONS.get(self.platform, 'fa-link')


class Booking(models.Model):
    user         = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings')
    resource     = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='bookings')
    start_time   = models.DateTimeField()
    end_time     = models.DateTimeField()
    project_name = models.CharField(max_length=200, blank=True)
    description  = models.TextField(blank=True)
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    released_at  = models.DateTimeField(null=True, blank=True)
    created_by   = models.ForeignKey(
        'User', on_delete=models.CASCADE, related_name='created_bookings', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gte=models.F('start_time')),
                name='booking_end_after_start'),
        ]
        indexes = [
            models.Index(fields=['resource', 'is_active', 'start_time', 'end_time']),
        ]

    def __str__(self) -> str:
        return f"{self.resource.name} booked by {self.user.username}"

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.is_active and not (self.end_time <= start or self.start_time >= end)

    def end_booking(self) -> None:
        now = timezone.now()
        self.end_time   = self.start_time if now <= self.start_time else min(now, self.end_time)
        self.is_active  = False
        self.released_at = timezone.now()
        self.save(update_fields=['end_time', 'is_active', 'released_at'])

    @property
    def currently_active(self) -> bool:
        now = timezone.now()
        return self.is_active and self.start_time <= now <= self.end_time


class UserInvitation(models.Model):
    email      = models.EmailField()
    role       = models.CharField(max_length=10, choices=User.Role.choices, default=User.Role.RA)
    token      = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sent_invitations')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used       = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.pk and not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=48)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool: return timezone.now() > self.expires_at
    @property
    def is_valid(self) -> bool: return not self.used and not self.is_expired

    def __str__(self) -> str:
        return f"Invite to {self.email} ({self.role})"


class RegistrationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING  = 'PENDING',  'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    username      = models.CharField(max_length=150)
    email         = models.EmailField()
    first_name    = models.CharField(max_length=150, blank=True)
    last_name     = models.CharField(max_length=150, blank=True)
    role          = models.CharField(max_length=10, choices=User.Role.choices, default=User.Role.RA)
    phone         = models.CharField(max_length=20, blank=True)
    status        = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at    = models.DateTimeField(auto_now_add=True)
    reviewed_at   = models.DateTimeField(null=True, blank=True)
    password_hash = models.CharField(max_length=128, blank=True)

    def __str__(self) -> str:
        return f"{self.username} ({self.email}) - {self.status}"


class WeeklyUpdate(models.Model):
    user         = models.ForeignKey(User, on_delete=models.CASCADE, related_name='weekly_updates')
    project_name = models.CharField(max_length=200)
    title        = models.CharField(max_length=200, blank=True)
    content      = models.TextField()
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Update by {self.user.username} on {self.project_name}"


class Announcement(models.Model):
    author     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='announcements')
    title      = models.CharField(max_length=200)
    content    = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Announcement: {self.title} ({self.created_at.date()})"
