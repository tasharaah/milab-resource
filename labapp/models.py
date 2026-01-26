"""
Database models for the MI Lab resource management application.

This module defines three primary models:

* User – a custom user model inheriting from AbstractUser with an
  additional role field indicating whether the account belongs to a
  Research Assistant (RA) or a Faculty member. A superuser can act
  as an administrator.
* Resource – represents a physical or virtual resource available in
  the laboratory (for example, a specific computer or GPU). Each
  resource has a name, description, GPU identifier and optionally
  other characteristics.
* Booking – records a reservation of a resource by a user for a given
  time window. Each booking is marked as active or inactive and has
  timestamps for tracking creation.

These models are designed to work with Django's ORM, enabling the
database engine to be swapped easily. When deploying to Cloud Run
against Postgres, the same code can be reused without modification.
"""
from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import datetime
from django.contrib.auth.hashers import make_password, check_password


class User(AbstractUser):
    """Custom user model with a role field for RA and faculty."""

    class Role(models.TextChoices):
        RA = 'RA', 'Research Assistant'
        FACULTY = 'Faculty', 'Faculty'

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.RA,
        help_text='Designates whether the user is a research assistant or faculty member.',
    )

    def is_ra(self) -> bool:
        return self.role == self.Role.RA

    def is_faculty(self) -> bool:
        return self.role == self.Role.FACULTY

    def __str__(self) -> str:
        return self.username


class Resource(models.Model):
    """
    Represents a physical or virtual resource in the lab. Resources can be
    computers, GPUs or other specialised equipment. Each resource carries
    metadata describing its type, unique code, GPU model (if any), a human
    readable name and optional description. Resources also have a status
    indicating whether they are operational or out of service. When
    deploying to a multi‑instance environment, a resource's availability
    should be determined by its status and any overlapping bookings.
    """

    class ResourceType(models.TextChoices):
        COMPUTER = "COMPUTER", "Computer"
        GPU = "GPU", "GPU"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        OK = "OK", "OK"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        DISABLED = "DISABLED", "Disabled"

    name = models.CharField(max_length=100, unique=True)
    # type of resource (computer/GPU/other) for categorisation
    resource_type = models.CharField(max_length=20, choices=ResourceType.choices, default=ResourceType.COMPUTER)
    # operational status (disabled resources are not bookable)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OK)
    # optional machine or GPU identifiers
    computer_code = models.CharField(max_length=50, blank=True)
    gpu = models.CharField(
        max_length=100,
        blank=True,
        help_text='Identifier of the GPU associated with this resource, if any.',
    )
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name

    @property
    def available(self) -> bool:
        """
        Determine if the resource is currently available. A resource is
        unavailable if it is not marked as OK or if there exists any
        overlapping active booking for the present time window. This
        property is computed on demand and should not be used for bulk
        availability checks; aggregate queries should be performed in
        views for efficiency.
        """
        # If the resource is not OK, it cannot be used
        if self.status != self.Status.OK:
            return False
        now = timezone.now()
        # Check for any active bookings overlapping the current time
        return not self.bookings.filter(
            is_active=True,
            start_time__lte=now,
            end_time__gte=now,
        ).exists()


class Booking(models.Model):
    """
    Represents a time‑bounded reservation of a resource by a user. Bookings
    include start and end times, an optional description and the software
    required for the task. A booking can be ended early, which records
    when it was actually released. Overlap checks should be enforced at
    the form/validation level and optionally at the database level for
    production deployments.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookings")
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="bookings")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    # what software or tool the user intends to use on this resource
    software = models.CharField(max_length=100, blank=True, help_text="Name of software or tool to be used.")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(end_time__gte=models.F('start_time')), name='booking_end_after_start'),
        ]
        indexes = [
            models.Index(fields=['resource', 'is_active', 'start_time', 'end_time']),
        ]

    def __str__(self) -> str:
        return f"{self.resource.name} booked by {self.user.username}"

    def overlaps(self, start: datetime, end: datetime) -> bool:
        """
        Return True if this booking overlaps the given time window. A booking
        overlaps when it is active and its time window intersects the
        candidate window. This helper is primarily used in form
        validation; aggregate queries are more efficient for bulk checks.
        """
        return self.is_active and not (self.end_time <= start or self.start_time >= end)

    def end_booking(self) -> None:
        now = timezone.now()

        # If booking hasn't started yet, end it at start_time (valid, and means "cancelled/ended")
        if now <= self.start_time:
            self.end_time = self.start_time
        else:
            # booking started -> end at now, but not beyond planned end
            self.end_time = min(now, self.end_time)

        self.is_active = False
        self.released_at = timezone.now()
        self.save(update_fields=["end_time", "is_active", "released_at"])

    @property
    def currently_active(self) -> bool:
        """
        Determine if this booking is currently in progress. A booking is
        considered active only if it is marked as active and the current
        time falls within its start and end window. This property does
        not modify the stored `is_active` flag but provides a
        real‑time check used by views and templates to hide bookings
        whose scheduled end has passed.
        """
        now = timezone.now()
        return self.is_active and self.start_time <= now <= self.end_time



class RegistrationRequest(models.Model):
    """
    Stores a pending request for a new account. When a user submits a
    registration request via the public registration form, an instance of
    this model is created with status set to pending. An administrator
    reviews the request and either approves or rejects it. Upon approval,
    a new User is created with the specified role.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    username = models.CharField(max_length=150)
    email = models.EmailField()
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=10, choices=User.Role.choices, default=User.Role.RA)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    password_hash = models.CharField(max_length=128, blank=True)


    def __str__(self) -> str:
        return f"{self.username} ({self.email}) - {self.status}"