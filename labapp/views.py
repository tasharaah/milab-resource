"""
Views for the MI Lab web application.

This module defines the request handlers for both research assistants
and faculty members. All views require the user to be authenticated.
Faculty (and staff/admin users) are able to access an aggregate
dashboard and create new user accounts. RAs can create and view their
own bookings and release resources when finished.
"""
from __future__ import annotations

from django.core.mail import send_mail
from django.conf import settings

from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db.models import Count
from django.utils.crypto import get_random_string
from typing import Any, Dict
import json

from .models import Booking, Resource, RegistrationRequest
from .forms import BookingForm, AddAdminForm, ResourceForm, RegistrationRequestForm


User = get_user_model()


def is_faculty_user(user) -> bool:
    """Return True if the user should access faculty functions."""
    return user.is_authenticated and (user.is_staff or user.is_superuser or getattr(user, 'is_faculty', lambda: False)())


@login_required
def home(request):
    """
    Redirect the user to the appropriate dashboard based on their role.
    Unauthenticated users are redirected to the login page automatically
    by the login_required decorator.
    """
    user: User = request.user  # type: ignore
    if is_faculty_user(user):
        return redirect('faculty_dashboard')
    return redirect('ra_dashboard')

@never_cache
@login_required
def ra_dashboard(request):
    """
    Render the dashboard for research assistants. The page includes
    summary statistics about resource availability and the user's
    current/past bookings.
    """
    # Compute overall and available resources more efficiently. Resources are
    # considered available if they are operational and have no active
    # overlapping booking for the current time window.
    total_resources = Resource.objects.count()
    now = timezone.now()
    # IDs of resources currently booked
    busy_resources = Booking.objects.filter(
        is_active=True,
        start_time__lte=now,
        end_time__gte=now,
    ).values_list('resource_id', flat=True).distinct()
    available_resources = Resource.objects.exclude(id__in=busy_resources).filter(status=Resource.Status.OK).count()
    # User's active and recent past bookings
    my_active_bookings = Booking.objects.filter(user=request.user, is_active=True)
    my_past_bookings = Booking.objects.filter(user=request.user, is_active=False).order_by('-created_at')[:5]

    context: Dict[str, Any] = {
        'total_resources': total_resources,
        'available_resources': available_resources,
        'my_active_bookings': my_active_bookings,
        'my_past_bookings': my_past_bookings,
    }
    return render(request, 'labapp/ra_dashboard.html', context)

@never_cache
@login_required
def dashboard(request):
    """
    Entry point for the dashboard route. Delegates to the RA or faculty
    dashboard depending on the current user's role.
    """
    user: User = request.user  # type: ignore
    if is_faculty_user(user):
        return redirect('faculty_dashboard')
    return redirect('ra_dashboard')

@never_cache
@login_required
def create_booking(request):
    """
    Allow a user to create a new booking. Only authenticated users can
    access this page. Validation is handled in the form. Upon success
    the user is redirected to their bookings overview.
    """
    form = BookingForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        booking = form.save(commit=False)
        booking.user = request.user  # type: ignore
        booking.save()
        return redirect('my_bookings')
    return render(request, 'labapp/create_booking.html', {'form': form})

@never_cache
@login_required
def my_bookings(request):
    """
    Display the current user's bookings. Active bookings come first.
    Users can release (end) an active booking from this page.
    """
    active_bookings = Booking.objects.filter(user=request.user, is_active=True)
    past_bookings = Booking.objects.filter(user=request.user, is_active=False)
    return render(
        request,
        'labapp/my_bookings.html',
        {
            'active_bookings': active_bookings,
            'past_bookings': past_bookings,
        },
    )

@never_cache
@login_required
def release_booking(request, booking_id: int):
    """
    Mark a booking as completed. The user can only release their own
    bookings unless they are faculty/staff. Once released, the end time
    is updated to the current time.
    """
    booking = get_object_or_404(Booking, pk=booking_id)
    user: User = request.user  # type: ignore
    # Allow release if the booking belongs to the user or if user has elevated permissions
    if booking.user == user or is_faculty_user(user):
        booking.end_booking()
    return redirect('my_bookings' if not is_faculty_user(user) else 'faculty_dashboard')

@never_cache
@login_required
def faculty_dashboard(request):
    """
    Display high-level statistics and charts for faculty and staff.
    This view aggregates booking data to reveal usage patterns.
    Only faculty, staff and superusers can access this page.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')

    total_resources = Resource.objects.count()
    total_ras = User.objects.filter(role=User.Role.RA).count()
    total_faculty = User.objects.filter(role=User.Role.FACULTY).count()
    active_bookings_count = Booking.objects.filter(is_active=True).count()
    now = timezone.now()
    busy_resources = Booking.objects.filter(
        is_active=True,
        start_time__lte=now,
        end_time__gte=now,
    ).values_list('resource_id', flat=True).distinct()
    available_resources = Resource.objects.exclude(id__in=busy_resources).filter(status=Resource.Status.OK).count()

    # Aggregate bookings by resource, user and software for top charts
    bookings_by_resource_qs = (
        Booking.objects.values('resource__name')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )
    bookings_by_user_qs = (
        Booking.objects.values('user__username')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )
    bookings_by_software_qs = (
        Booking.objects.values('software')
        .exclude(software="")
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )

    # Prepare JSON‑serialisable lists for Chart.js. Use json.dumps to
    # render as JS arrays in templates.
    resource_labels = [b['resource__name'] for b in bookings_by_resource_qs]
    resource_counts = [b['count'] for b in bookings_by_resource_qs]
    user_labels = [b['user__username'] for b in bookings_by_user_qs]
    user_counts = [b['count'] for b in bookings_by_user_qs]
    software_labels = [b['software'] or 'Unspecified' for b in bookings_by_software_qs]
    software_counts = [b['count'] for b in bookings_by_software_qs]

    context: Dict[str, Any] = {
        'total_resources': total_resources,
        'available_resources': available_resources,
        'total_ras': total_ras,
        'total_faculty': total_faculty,
        'active_bookings_count': active_bookings_count,
        'bookings_by_resource': list(bookings_by_resource_qs),
        'bookings_by_user': list(bookings_by_user_qs),
        'bookings_by_software': list(bookings_by_software_qs),
        'resource_labels_json': json.dumps(resource_labels),
        'resource_counts_json': json.dumps(resource_counts),
        'user_labels_json': json.dumps(user_labels),
        'user_counts_json': json.dumps(user_counts),
        'software_labels_json': json.dumps(software_labels),
        'software_counts_json': json.dumps(software_counts),
        'active_bookings': Booking.objects.filter(is_active=True).select_related('user', 'resource'),
    }
    return render(request, 'labapp/faculty_dashboard.html', context)

@never_cache
@login_required
def add_admin(request):
    """
    Allow faculty/staff to create new user accounts. This can be used
    both to onboard new RAs and to grant administrative privileges to
    other faculty members. Only accessible to faculty/staff.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    form = AddAdminForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        new_user = form.save(commit=False)
        new_user.role = form.cleaned_data['role']
        new_user.is_staff = form.cleaned_data['is_staff']
        new_user.save()
        messages.success(request, f"User {new_user.username} created successfully")
        return redirect('faculty_dashboard')
    return render(request, 'labapp/add_admin.html', {'form': form})


def register_request(request):
    if request.method == 'POST':
        form = RegistrationRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.role = User.Role.RA
            req.save()
            messages.success(request, "Registration request submitted! An admin will review and approve it.")
        else:
            messages.error(request, "Please correct the errors in the form.")
    return redirect('login')

@never_cache
@login_required
def registration_requests_admin(request):
    """
    Display a list of pending registration requests to administrators. Only
    staff, superusers and faculty members can access this view.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    pending = RegistrationRequest.objects.filter(status=RegistrationRequest.Status.PENDING).order_by('-created_at')
    return render(request, 'labapp/registration_requests.html', {'pending_requests': pending})

@never_cache
@login_required
def approve_registration(request, req_id: int):
    """
    Approve a pending registration request. Creates a new user with RA role
    and marks the request as approved. The user is created with an
    unusable password; they must reset their password via the 'forgot
    password' flow. Only faculty or staff can approve requests.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    reg_req = get_object_or_404(RegistrationRequest, pk=req_id, status=RegistrationRequest.Status.PENDING)
    # Create the new user
    new_user = User.objects.create(
    username=reg_req.username,
    email=reg_req.email,
    first_name=reg_req.first_name,
    last_name=reg_req.last_name,
    role=User.Role.RA,
    is_active=True,
)

    # set hashed password from request
    new_user.password = reg_req.password_hash
    new_user.save()
    send_mail(
    subject="MI Lab | Your account has been approved",
    message=(
        f"Hi {new_user.first_name or new_user.username},\n\n"
        "Your MI Lab account has been approved.\n"
        "You can now log in.\n\n"
        "If you forgot your password, use the 'Forgot password' option on the login page.\n\n"
        "— MI Lab"
    ),
    from_email=settings.DEFAULT_FROM_EMAIL,
    recipient_list=[new_user.email],
    fail_silently=False,
)


    # Update request status
    reg_req.status = RegistrationRequest.Status.APPROVED
    reg_req.reviewed_at = timezone.now()
    reg_req.save(update_fields=['status', 'reviewed_at'])
    messages.success(request, f"Registration request for {new_user.username} approved.")
    return redirect('registration_requests_admin')

@never_cache
@login_required
def reject_registration(request, req_id: int):
    """
    Reject a pending registration request. Marks the request as rejected.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    reg_req = get_object_or_404(RegistrationRequest, pk=req_id, status=RegistrationRequest.Status.PENDING)
    reg_req.status = RegistrationRequest.Status.REJECTED
    reg_req.reviewed_at = timezone.now()
    reg_req.save(update_fields=['status', 'reviewed_at'])
    messages.info(request, f"Registration request for {reg_req.username} rejected.")
    return redirect('registration_requests_admin')

@never_cache
@login_required
def add_resource(request):
    """
    Allow faculty/staff to add new resources to the lab. Displays a list
    of existing resources and a form for creating a new resource. Only
    accessible to faculty or staff.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    form = ResourceForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Resource added successfully.')
        return redirect('add_resource')
    resources = Resource.objects.all().order_by('name')
    return render(request, 'labapp/add_resource.html', {'form': form, 'resources': resources})

@never_cache
@login_required
def all_bookings(request):
    """
    Display a table of all bookings for administrators. This view lists
    active and past bookings with details on user, resource, software,
    start and end times. Only accessible to faculty or staff.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    bookings = Booking.objects.select_related('user', 'resource').order_by('-created_at')
    return render(request, 'labapp/all_bookings.html', {'bookings': bookings})