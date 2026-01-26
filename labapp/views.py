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
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

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
from .forms import BookingForm, AddAdminForm, ResourceForm, RegistrationRequestForm, AssignAdminForm


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
    # Preselect resource if passed via GET
    initial = {}
    resource_id = request.GET.get('resource')
    if resource_id:
        try:
            resource_obj = Resource.objects.get(pk=resource_id)
            initial['resource'] = resource_obj
        except Resource.DoesNotExist:
            pass
    form = BookingForm(request.POST or None, initial=initial)
    if request.method == 'POST':
        if form.is_valid():
            booking = form.save(commit=False)
            booking.user = request.user  # type: ignore
            # Always set the start time to now. This ensures bookings
            # start immediately and are not scheduled for the future.
            booking.start_time = timezone.now()
            booking.save()
            messages.success(request, 'Booking created successfully.')
            return redirect('my_bookings')
        else:
            # show validation errors using messages
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
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
    # Redirect to a specified next page if provided, otherwise use role‑based defaults
    next_page = request.GET.get('next')
    if next_page:
        return redirect(next_page)
    # Non‑faculty users return to their bookings page; faculty to dashboard
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
    # Exclude superusers from counts
    total_ras = User.objects.filter(role=User.Role.RA, is_superuser=False).count()
    total_faculty = User.objects.filter(role=User.Role.FACULTY, is_superuser=False).count()
    active_bookings_count = Booking.objects.filter(is_active=True).count()
    now = timezone.now()
    busy_resources = Booking.objects.filter(
        is_active=True,
        start_time__lte=now,
        end_time__gte=now,
    ).values_list('resource_id', flat=True).distinct()
    available_resources = Resource.objects.exclude(id__in=busy_resources).filter(status=Resource.Status.OK).count()

    # Helper to parse date range for each chart
    def parse_range(start_param: str | None, end_param: str | None, period: str) -> tuple[timezone.datetime | None, timezone.datetime | None]:
        """
        Parse start and end dates from query parameters. If both dates are
        missing and no period is specified, default to the last 30 days.
        Supported periods: last_week, last_month, last_3_months, last_year, all.
        Returns aware datetimes or None.
        """
        n = timezone.now()
        start_date = None
        end_date = None
        # Parse explicit dates
        try:
            if start_param:
                start_date = timezone.make_aware(timezone.datetime.fromisoformat(start_param))
            if end_param:
                # include full day for end
                end_date = timezone.make_aware(timezone.datetime.fromisoformat(end_param)) + timezone.timedelta(days=1)
        except Exception:
            start_date = None
            end_date = None
        # Apply period overrides
        if period:
            if period == 'last_week':
                start_date = n - timezone.timedelta(days=7)
                end_date = n
            elif period == 'last_month':
                start_date = n - timezone.timedelta(days=30)
                end_date = n
            elif period == 'last_3_months':
                start_date = n - timezone.timedelta(days=90)
                end_date = n
            elif period == 'last_year':
                start_date = n - timezone.timedelta(days=365)
                end_date = n
            elif period == 'all':
                start_date = None
                end_date = None
        # Default if none provided
        if start_date is None and end_date is None and not period:
            start_date = n - timezone.timedelta(days=30)
            end_date = n
        return start_date, end_date

    # Prepare RA and resource lists for filter forms
    ra_list = User.objects.filter(role=User.Role.RA, is_superuser=False).order_by('username')
    resource_list = Resource.objects.all().order_by('name')

    # ------------------------------------------------------------------
    # Pie chart: which resources a RA used (count of bookings per resource)
    pie_ra_param = request.GET.get('pie_ra', 'all')
    pie_start_param = request.GET.get('pie_start')
    pie_end_param = request.GET.get('pie_end')
    pie_period = request.GET.get('pie_period', '')
    pie_start, pie_end = parse_range(pie_start_param, pie_end_param, pie_period)
    pie_bookings = Booking.objects.all().select_related('resource', 'user')
    if pie_start is not None:
        pie_bookings = pie_bookings.filter(start_time__gte=pie_start)
    if pie_end is not None:
        pie_bookings = pie_bookings.filter(start_time__lte=pie_end)
    if pie_ra_param != 'all':
        try:
            pie_ra_id = int(pie_ra_param)
            pie_bookings = pie_bookings.filter(user__id=pie_ra_id)
        except ValueError:
            pass
    # Count bookings per resource
    pie_counts: dict[str, int] = {}
    for b in pie_bookings:
        res_name = b.resource.name
        pie_counts[res_name] = pie_counts.get(res_name, 0) + 1
    # Sort results
    sorted_pie = sorted(pie_counts.items(), key=lambda x: x[1], reverse=True)
    pie_labels = [res for res, _ in sorted_pie]
    pie_values = [count for _, count in sorted_pie]

    # ------------------------------------------------------------------
    # Resource durations chart: time spent in each resource (hours)
    res_ra_param = request.GET.get('res_ra', 'all')
    res_start_param = request.GET.get('res_start')
    res_end_param = request.GET.get('res_end')
    res_period = request.GET.get('res_period', '')
    res_start, res_end = parse_range(res_start_param, res_end_param, res_period)
    res_bookings = Booking.objects.all().select_related('resource', 'user')
    if res_start is not None:
        res_bookings = res_bookings.filter(start_time__gte=res_start)
    if res_end is not None:
        res_bookings = res_bookings.filter(start_time__lte=res_end)
    if res_ra_param != 'all':
        try:
            res_ra_id = int(res_ra_param)
            res_bookings = res_bookings.filter(user__id=res_ra_id)
        except ValueError:
            pass
    durations_by_resource: dict[str, float] = {}
    for b in res_bookings:
        s = b.start_time
        e = b.end_time or now
        if res_start:
            s = max(s, res_start)
        if res_end:
            e = min(e, res_end)
        dur = (e - s).total_seconds() / 3600.0
        res_name = b.resource.name
        durations_by_resource[res_name] = durations_by_resource.get(res_name, 0.0) + dur
    sorted_res = sorted(durations_by_resource.items(), key=lambda x: x[1], reverse=True)
    res_labels = [r for r, _ in sorted_res]
    res_durations = [round(d, 2) for _, d in sorted_res]

    # ------------------------------------------------------------------
    # Top users chart: time spent per RA (hours)
    user_start_param = request.GET.get('user_start')
    user_end_param = request.GET.get('user_end')
    user_period = request.GET.get('user_period', '')
    user_start, user_end = parse_range(user_start_param, user_end_param, user_period)
    user_bookings = Booking.objects.all().select_related('user', 'resource')
    if user_start is not None:
        user_bookings = user_bookings.filter(start_time__gte=user_start)
    if user_end is not None:
        user_bookings = user_bookings.filter(start_time__lte=user_end)
    durations_by_user: dict[str, float] = {}
    for b in user_bookings:
        s = b.start_time
        e = b.end_time or now
        if user_start:
            s = max(s, user_start)
        if user_end:
            e = min(e, user_end)
        dur = (e - s).total_seconds() / 3600.0
        uname = b.user.username
        durations_by_user[uname] = durations_by_user.get(uname, 0.0) + dur
    sorted_users = sorted(durations_by_user.items(), key=lambda x: x[1], reverse=True)
    top_users = sorted_users[:5]
    user_labels = [u for u, _ in top_users]
    user_durations = [round(d, 2) for _, d in top_users]

    # ------------------------------------------------------------------
    # Hour distribution chart: bookings start times distribution (counts)
    time_resource_param = request.GET.get('time_resource', 'all')
    time_start_param = request.GET.get('time_start')
    time_end_param = request.GET.get('time_end')
    time_period = request.GET.get('time_period', '')
    time_start, time_end = parse_range(time_start_param, time_end_param, time_period)
    hour_bookings = Booking.objects.all().select_related('resource', 'user')
    if time_start is not None:
        hour_bookings = hour_bookings.filter(start_time__gte=time_start)
    if time_end is not None:
        hour_bookings = hour_bookings.filter(start_time__lte=time_end)
    if time_resource_param != 'all':
        try:
            t_res_id = int(time_resource_param)
            hour_bookings = hour_bookings.filter(resource__id=t_res_id)
        except ValueError:
            pass
    hour_counts = [0] * 24
    for b in hour_bookings:
        local_hour = b.start_time.astimezone(timezone.get_current_timezone()).hour
        hour_counts[local_hour] += 1
    hour_labels = list(range(24))

    import json
    context: Dict[str, Any] = {
        'total_resources': total_resources,
        'available_resources': available_resources,
        'total_ras': total_ras,
        'total_faculty': total_faculty,
        'active_bookings_count': active_bookings_count,
        'ra_list': ra_list,
        'resource_list': resource_list,
        # Selected filter values for forms
        'pie_selected_ra': pie_ra_param,
        'pie_start_date': pie_start.date() if pie_start else '',
        'pie_end_date': (pie_end - timezone.timedelta(days=1)).date() if pie_end else '',
        'res_selected_ra': res_ra_param,
        'res_start_date': res_start.date() if res_start else '',
        'res_end_date': (res_end - timezone.timedelta(days=1)).date() if res_end else '',
        'user_start_date': user_start.date() if user_start else '',
        'user_end_date': (user_end - timezone.timedelta(days=1)).date() if user_end else '',
        'time_selected_resource': time_resource_param,
        'time_start_date': time_start.date() if time_start else '',
        'time_end_date': (time_end - timezone.timedelta(days=1)).date() if time_end else '',
        # Chart data JSON
        'pie_labels_json': json.dumps(pie_labels),
        'pie_values_json': json.dumps(pie_values),
        'resource_labels_json': json.dumps(res_labels),
        'resource_durations_json': json.dumps(res_durations),
        'user_labels_json': json.dumps(user_labels),
        'user_durations_json': json.dumps(user_durations),
        'hour_labels_json': json.dumps(hour_labels),
        'hour_counts_json': json.dumps(hour_counts),
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
    # Instead of creating new users, allow assigning admin privileges to existing users
    form = AssignAdminForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        selected_user: User = form.cleaned_data['user']  # type: ignore
        grant = form.cleaned_data['make_admin']
        selected_user.is_staff = grant
        selected_user.save(update_fields=["is_staff"])
        if grant:
            messages.success(request, f"{selected_user.username} has been granted admin privileges.")
        else:
            messages.success(request, f"{selected_user.username}'s admin privileges have been revoked.")
        return redirect('faculty_dashboard')
    # Prepare a mapping of user IDs to their current admin status for client‑side checkbox update.
    admin_statuses = {str(u.id): u.is_staff for u in form.fields['user'].queryset}
    import json as _json
    return render(request, 'labapp/add_admin.html', {
        'form': form,
        'admin_statuses_json': _json.dumps(admin_statuses),
    })


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
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect("ra_dashboard")

    reg_req = get_object_or_404(
        RegistrationRequest,
        pk=req_id,
        status=RegistrationRequest.Status.PENDING
    )

    new_user = User.objects.create_user(
        username=reg_req.username,
        email=reg_req.email,
        first_name=reg_req.first_name,
        last_name=reg_req.last_name,
        role=User.Role.RA,
        password=None,
    )
    new_user.password = reg_req.password_hash  # stored Django hash
    new_user.is_active = True
    new_user.save()

    try:
        send_mail(
            subject="MI Lab | Your account has been approved",
            message=(
                f"Hi {new_user.first_name or new_user.username},\n\n"
                "Your MI Lab account has been approved.\n"
                "You can now log in.\n\n"
                "— MI Lab"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[new_user.email],
            fail_silently=False,
        )
    except Exception as e:
        messages.warning(request, f"Approved, but approval email failed: {e}")

    reg_req.status = RegistrationRequest.Status.APPROVED
    reg_req.reviewed_at = timezone.now()
    reg_req.save(update_fields=["status", "reviewed_at"])

    messages.success(request, f"Registration request for {new_user.username} approved.")
    return redirect("registration_requests_admin")

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

# New list and resource views
@never_cache
@login_required
def list_ras(request):
    """
    Display a list of all research assistants (excluding superusers) for administrators.
    Only faculty, staff and superusers can access this page.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    ras = User.objects.filter(role=User.Role.RA, is_superuser=False).order_by('username')
    return render(request, 'labapp/list_ras.html', {'users': ras, 'title': 'Research Assistants'})


@never_cache
@login_required
def list_faculty(request):
    """
    Display a list of all faculty (excluding superusers) for administrators.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    faculty = User.objects.filter(role=User.Role.FACULTY, is_superuser=False).order_by('username')
    return render(request, 'labapp/list_ras.html', {'users': faculty, 'title': 'Faculty Members'})


@never_cache
@login_required
def list_resources(request):
    """
    Display a table of all resources. Accessible to any authenticated user.
    """
    resources = Resource.objects.all().order_by('name')
    return render(request, 'labapp/list_resources.html', {'resources': resources})


# ----------------------------------------------------------------------
# New view functions for resource and user management and statistics
#

@never_cache
@login_required
def delete_resource(request, resource_id: int):
    """
    Delete a resource from the system. Only faculty, staff or superusers
    may perform this action. Deleting a resource will also cascade
    deletion of any associated bookings due to the foreign key definition.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    resource = get_object_or_404(Resource, pk=resource_id)
    if request.method == 'POST':
        name = resource.name
        resource.delete()
        messages.success(request, f'Resource "{name}" deleted.')
    return redirect('add_resource')


@never_cache
@login_required
def update_resource(request, resource_id: int):
    """
    Update a resource's status. Only faculty, staff or superusers may
    modify resources. Expects a POST with a `status` field containing
    one of the valid Resource.Status values. After updating, the user
    is redirected back to the manage resources page.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    resource = get_object_or_404(Resource, pk=resource_id)
    if request.method == 'POST':
        status = request.POST.get('status')
        # Only update if the provided value is a valid choice
        if status in Resource.Status.values:
            resource.status = status  # type: ignore
            resource.save(update_fields=['status'])
            messages.success(request, f'Resource "{resource.name}" updated.')
    return redirect('add_resource')


@never_cache
@login_required
def delete_ra(request, user_id: int):
    """
    Delete a research assistant account. Only faculty, staff or superusers
    can perform this operation. Superusers and non‑RA accounts are
    protected from deletion via this view. The deletion will also
    cascade to any related bookings.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    # Only allow deleting RA accounts that are not superusers
    ra_user = get_object_or_404(User, pk=user_id, role=User.Role.RA, is_superuser=False)
    if request.method == 'POST':
        username = ra_user.username
        ra_user.delete()
        messages.success(request, f'User "{username}" deleted.')
    return redirect('list_ras')


@never_cache
@login_required
def active_resources(request):
    """
    Display the list of resources that are currently booked. Unlike
    `active_bookings_admin`, this view is accessible to all
    authenticated users and does not allow ending bookings. Each row
    shows the user occupying the resource, the resource name, software
    and start/end times.
    """
    now = timezone.now()
    # Select active bookings overlapping the present moment
    active_bookings = Booking.objects.filter(
        is_active=True,
        start_time__lte=now,
        end_time__gte=now,
    ).select_related('user', 'resource').order_by('-start_time')
    return render(request, 'labapp/active_resources.html', {'bookings': active_bookings})


@never_cache
@login_required
def stats(request):
    """
    Render a statistics dashboard with configurable filters. Only
    faculty, staff or superusers may access this page. The dashboard
    provides several charts: a pie chart of resource usage per RA, a
    bar chart of resource usage durations, a bar chart of top users by
    time spent and a line chart showing the distribution of booking
    start times across the day. Filters include date range, research
    assistant and resource. Charts are powered by Chart.js.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')

    # Determine date range based on query parameters
    # Accept start and end dates in ISO format (YYYY-MM-DD)
    start_param = request.GET.get('start')
    end_param = request.GET.get('end')
    period = request.GET.get('period', '')
    now = timezone.now()
    # Compute default range if none provided: last 30 days
    default_start = now - timezone.timedelta(days=30)
    default_end = now
    start_date = None
    end_date = None
    try:
        if start_param:
            start_date = timezone.make_aware(timezone.datetime.fromisoformat(start_param))
        if end_param:
            # Interpret end date at end of day
            end_date = timezone.make_aware(timezone.datetime.fromisoformat(end_param)) + timezone.timedelta(days=1)
    except Exception:
        start_date = None
        end_date = None
    # Predefined periods override explicit dates
    if period:
        if period == 'last_week':
            start_date = now - timezone.timedelta(days=7)
            end_date = now
        elif period == 'last_month':
            start_date = now - timezone.timedelta(days=30)
            end_date = now
        elif period == 'last_3_months':
            start_date = now - timezone.timedelta(days=90)
            end_date = now
        elif period == 'last_year':
            start_date = now - timezone.timedelta(days=365)
            end_date = now
        elif period == 'all':
            start_date = None
            end_date = None

    # Use default if still missing
    if start_date is None and end_date is None:
        start_date = default_start
        end_date = default_end

    # Filter by RA
    ra_param = request.GET.get('ra', 'all')
    resource_param = request.GET.get('resource', 'all')
    bookings = Booking.objects.all().select_related('user', 'resource')
    if start_date is not None:
        bookings = bookings.filter(start_time__gte=start_date)
    if end_date is not None:
        bookings = bookings.filter(start_time__lte=end_date)
    if ra_param != 'all':
        try:
            ra_id = int(ra_param)
            bookings = bookings.filter(user__id=ra_id)
        except ValueError:
            pass
    if resource_param != 'all':
        try:
            res_id = int(resource_param)
            bookings = bookings.filter(resource__id=res_id)
        except ValueError:
            pass

    # Prepare aggregates
    durations_by_resource: dict[str, float] = {}
    durations_by_user: dict[str, float] = {}
    start_hour_counts = [0] * 24
    for booking in bookings:
        b_start = booking.start_time
        b_end = booking.end_time or now
        # Clip to selected range if necessary
        if start_date:
            b_start = max(b_start, start_date)
        if end_date:
            b_end = min(b_end, end_date)
        duration_hours = (b_end - b_start).total_seconds() / 3600.0
        # Accumulate resource duration
        res_name = booking.resource.name
        durations_by_resource[res_name] = durations_by_resource.get(res_name, 0.0) + duration_hours
        # Accumulate user duration
        usr_name = booking.user.username
        durations_by_user[usr_name] = durations_by_user.get(usr_name, 0.0) + duration_hours
        # Count start hour for line chart
        local_hour = booking.start_time.astimezone(timezone.get_current_timezone()).hour
        start_hour_counts[local_hour] += 1

    # Sort results for top charts
    # Top RA by duration
    sorted_users = sorted(durations_by_user.items(), key=lambda x: x[1], reverse=True)
    top_users = sorted_users[:5]
    user_labels = [u for u, _ in top_users]
    user_durations = [round(d, 2) for _, d in top_users]
    # Resource durations (can be many; show all or top N)
    sorted_resources = sorted(durations_by_resource.items(), key=lambda x: x[1], reverse=True)
    res_labels = [r for r, _ in sorted_resources]
    res_durations = [round(d, 2) for _, d in sorted_resources]

    # Prepare RA resource distribution (pie). If a specific RA was selected
    # (ra_param != 'all'), durations_by_resource already reflects the filter.
    pie_labels = res_labels
    pie_values = res_durations

    import json
    context: Dict[str, Any] = {
        'ra_list': User.objects.filter(role=User.Role.RA, is_superuser=False).order_by('username'),
        'resource_list': Resource.objects.all().order_by('name'),
        'selected_ra': ra_param,
        'selected_resource': resource_param,
        'start_date': start_date.date() if start_date else '',
        'end_date': (end_date - timezone.timedelta(days=1)).date() if end_date else '',
        'user_labels_json': json.dumps(user_labels),
        'user_durations_json': json.dumps(user_durations),
        'resource_labels_json': json.dumps(res_labels),
        'resource_durations_json': json.dumps(res_durations),
        'pie_labels_json': json.dumps(pie_labels),
        'pie_values_json': json.dumps(pie_values),
        'hour_labels_json': json.dumps(list(range(24))),
        'hour_counts_json': json.dumps(start_hour_counts),
    }
    return render(request, 'labapp/stats.html', context)


@never_cache
@login_required
def available_resources(request):
    """
    Display a list of currently available resources (status OK and not booked).
    Users can navigate to the booking page from here. Accessible to any authenticated user.
    """
    now = timezone.now()
    busy_ids = Booking.objects.filter(
        is_active=True,
        start_time__lte=now,
        end_time__gte=now,
    ).values_list('resource_id', flat=True).distinct()
    available = Resource.objects.exclude(id__in=busy_ids).filter(status=Resource.Status.OK).order_by('name')
    return render(request, 'labapp/available_resources.html', {'resources': available})


@never_cache
@login_required
def active_bookings_admin(request):
    """
    Display a list of all active bookings. Only accessible to faculty or staff users.
    """
    user: User = request.user  # type: ignore
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    active_bookings = Booking.objects.filter(is_active=True).select_related('user', 'resource').order_by('-start_time')
    return render(request, 'labapp/active_bookings_admin.html', {'bookings': active_bookings})