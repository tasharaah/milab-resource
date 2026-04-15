"""
Views for the MI Lab web application.
"""
from __future__ import annotations

from django.core.mail import send_mail
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db.models import Count
from typing import Any, Dict
import json
from django.http import HttpResponse
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .models import Booking, Resource, RegistrationRequest, Project, UserInvitation
from .forms import (
    BookingForm,
    AddAdminForm,
    ResourceForm,
    AssignAdminForm,
    WeeklyUpdateForm,
    AnnouncementForm,
    ProjectForm,
    UserInvitationForm,
    InvitedRegistrationForm,
)

User = get_user_model()


def is_faculty_user(user) -> bool:
    return user.is_authenticated and (
        user.is_staff or user.is_superuser or
        getattr(user, 'is_faculty', lambda: False)()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def home(request):
    user = request.user
    if is_faculty_user(user):
        return redirect('faculty_dashboard')
    return redirect('ra_dashboard')


@never_cache
@login_required
def dashboard(request):
    user = request.user
    if is_faculty_user(user):
        return redirect('faculty_dashboard')
    return redirect('ra_dashboard')


@never_cache
@login_required
def ra_dashboard(request):
    total_resources = Resource.objects.count()
    now = timezone.now()
    busy_resources = Booking.objects.filter(
        is_active=True, start_time__lte=now, end_time__gte=now,
    ).values_list('resource_id', flat=True).distinct()
    available_resources = Resource.objects.exclude(id__in=busy_resources).filter(
        status=Resource.Status.OK
    ).count()
    my_active_bookings = Booking.objects.filter(
        user=request.user, is_active=True, start_time__lte=now, end_time__gte=now,
    )
    context: Dict[str, Any] = {
        'total_resources':    total_resources,
        'available_resources': available_resources,
        'my_active_bookings': my_active_bookings,
    }
    return render(request, 'labapp/ra_dashboard.html', context)


@never_cache
@login_required
def faculty_dashboard(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')

    total_resources = Resource.objects.count()
    total_users     = User.objects.filter(is_superuser=False).count()
    total_faculty   = User.objects.filter(role=User.Role.FACULTY, is_superuser=False).count()
    now             = timezone.now()
    active_bookings_count = Booking.objects.filter(
        is_active=True, start_time__lte=now, end_time__gte=now,
    ).count()
    busy_resources = Booking.objects.filter(
        is_active=True, start_time__lte=now, end_time__gte=now,
    ).values_list('resource_id', flat=True).distinct()
    available_resources = Resource.objects.exclude(id__in=busy_resources).filter(
        status=Resource.Status.OK
    ).count()

    def parse_range(s, e, p):
        n = timezone.now()
        sd, ed = None, None
        try:
            if s: sd = timezone.make_aware(timezone.datetime.fromisoformat(s))
            if e: ed = timezone.make_aware(timezone.datetime.fromisoformat(e)) + timezone.timedelta(days=1)
        except Exception:
            sd, ed = None, None
        if p:
            if   p == 'last_week':     sd, ed = n - timezone.timedelta(days=7),   n
            elif p == 'last_month':    sd, ed = n - timezone.timedelta(days=30),   n
            elif p == 'last_3_months': sd, ed = n - timezone.timedelta(days=90),   n
            elif p == 'last_year':     sd, ed = n - timezone.timedelta(days=365),  n
            elif p == 'all':           sd, ed = None, None
        if sd is None and ed is None and not p:
            sd, ed = n - timezone.timedelta(days=30), n
        return sd, ed

    ra_list       = User.objects.filter(role=User.Role.RA, is_superuser=False).order_by('username')
    resource_list = Resource.objects.all().order_by('name')

    # Pie chart
    pie_ra_param   = request.GET.get('pie_ra', 'all')
    pie_start, pie_end = parse_range(
        request.GET.get('pie_start'), request.GET.get('pie_end'), request.GET.get('pie_period', ''))
    pie_bookings = Booking.objects.all()
    if pie_start: pie_bookings = pie_bookings.filter(start_time__gte=pie_start)
    if pie_end:   pie_bookings = pie_bookings.filter(start_time__lte=pie_end)
    if pie_ra_param != 'all':
        try: pie_bookings = pie_bookings.filter(user__id=int(pie_ra_param))
        except ValueError: pass
    pie_counts: dict[str, int] = {}
    for b in pie_bookings.select_related('resource'):
        pie_counts[b.resource.name] = pie_counts.get(b.resource.name, 0) + 1
    sorted_pie = sorted(pie_counts.items(), key=lambda x: x[1], reverse=True)
    pie_labels = [r for r, _ in sorted_pie]
    pie_values = [c for _, c in sorted_pie]

    # Resource durations
    res_ra_param  = request.GET.get('res_ra', 'all')
    res_start, res_end = parse_range(
        request.GET.get('res_start'), request.GET.get('res_end'), request.GET.get('res_period', ''))
    res_bookings = Booking.objects.all()
    if res_start: res_bookings = res_bookings.filter(start_time__gte=res_start)
    if res_end:   res_bookings = res_bookings.filter(start_time__lte=res_end)
    if res_ra_param != 'all':
        try: res_bookings = res_bookings.filter(user__id=int(res_ra_param))
        except ValueError: pass
    dur_by_res: dict[str, float] = {}
    for b in res_bookings.select_related('resource'):
        s, e = b.start_time, b.end_time or now
        if res_start: s = max(s, res_start)
        if res_end:   e = min(e, res_end)
        dur_by_res[b.resource.name] = dur_by_res.get(b.resource.name, 0.0) + (e - s).total_seconds() / 3600
    sorted_res = sorted(dur_by_res.items(), key=lambda x: x[1], reverse=True)
    res_labels    = [r for r, _ in sorted_res]
    res_durations = [round(d, 2) for _, d in sorted_res]

    # Top users
    user_start, user_end = parse_range(
        request.GET.get('user_start'), request.GET.get('user_end'), request.GET.get('user_period', ''))
    u_bookings = Booking.objects.all()
    if user_start: u_bookings = u_bookings.filter(start_time__gte=user_start)
    if user_end:   u_bookings = u_bookings.filter(start_time__lte=user_end)
    dur_by_user: dict[str, float] = {}
    for b in u_bookings.select_related('user'):
        s, e = b.start_time, b.end_time or now
        if user_start: s = max(s, user_start)
        if user_end:   e = min(e, user_end)
        dur_by_user[b.user.username] = dur_by_user.get(b.user.username, 0.0) + (e - s).total_seconds() / 3600
    top_users    = sorted(dur_by_user.items(), key=lambda x: x[1], reverse=True)[:5]
    user_labels   = [u for u, _ in top_users]
    user_durations = [round(d, 2) for _, d in top_users]

    # Hour distribution
    time_res_param = request.GET.get('time_resource', 'all')
    time_start, time_end = parse_range(
        request.GET.get('time_start'), request.GET.get('time_end'), request.GET.get('time_period', ''))
    h_bookings = Booking.objects.all()
    if time_start: h_bookings = h_bookings.filter(start_time__gte=time_start)
    if time_end:   h_bookings = h_bookings.filter(start_time__lte=time_end)
    if time_res_param != 'all':
        try: h_bookings = h_bookings.filter(resource__id=int(time_res_param))
        except ValueError: pass
    hour_counts = [0] * 24
    for b in h_bookings:
        hour_counts[b.start_time.astimezone(timezone.get_current_timezone()).hour] += 1

    context: Dict[str, Any] = {
        'total_resources':       total_resources,
        'available_resources':   available_resources,
        'total_users':           total_users,
        'total_faculty':         total_faculty,
        'active_bookings_count': active_bookings_count,
        'ra_list':               ra_list,
        'resource_list':         resource_list,
        'pie_selected_ra':       pie_ra_param,
        'pie_start_date':        pie_start.date() if pie_start else '',
        'pie_end_date':          (pie_end - timezone.timedelta(days=1)).date() if pie_end else '',
        'res_selected_ra':       res_ra_param,
        'res_start_date':        res_start.date() if res_start else '',
        'res_end_date':          (res_end - timezone.timedelta(days=1)).date() if res_end else '',
        'user_start_date':       user_start.date() if user_start else '',
        'user_end_date':         (user_end - timezone.timedelta(days=1)).date() if user_end else '',
        'time_selected_resource': time_res_param,
        'time_start_date':       time_start.date() if time_start else '',
        'time_end_date':         (time_end - timezone.timedelta(days=1)).date() if time_end else '',
        'pie_labels_json':       json.dumps(pie_labels),
        'pie_values_json':       json.dumps(pie_values),
        'resource_labels_json':  json.dumps(res_labels),
        'resource_durations_json': json.dumps(res_durations),
        'user_labels_json':      json.dumps(user_labels),
        'user_durations_json':   json.dumps(user_durations),
        'hour_labels_json':      json.dumps(list(range(24))),
        'hour_counts_json':      json.dumps(hour_counts),
    }
    return render(request, 'labapp/faculty_dashboard.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# Bookings
# ─────────────────────────────────────────────────────────────────────────────

@never_cache
@login_required
def create_booking(request):
    initial = {}
    resource_id = request.GET.get('resource')
    if resource_id:
        try:
            initial['resource'] = Resource.objects.get(pk=resource_id)
        except Resource.DoesNotExist:
            pass

    now_local = timezone.localtime()
    form = BookingForm(request.POST or None, initial=initial)

    if request.method == 'POST':
        if form.is_valid():
            booking = form.save(commit=False)
            assignee = form.cleaned_data.get('assignee')
            if assignee and is_faculty_user(request.user):
                booking.user       = assignee
                booking.created_by = request.user
            else:
                booking.user       = request.user
                booking.created_by = request.user
            booking.start_time     = timezone.now()
            # Apply resolved project_name from form clean()
            booking.project_name   = form.cleaned_data.get('project_name', '')
            booking.save()
            if assignee and is_faculty_user(request.user):
                try:
                    send_mail(
                        subject="MI Lab | A resource has been booked for you",
                        message=(
                            f"Hello {assignee.first_name or assignee.username},\n\n"
                            f"{request.user.get_full_name() or request.user.username} has booked "
                            f"{booking.resource.name} for you until {booking.end_time}.\n\n— MI Lab"
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[assignee.email],
                        fail_silently=True,
                    )
                except Exception:
                    pass
            messages.success(request, 'Booking created successfully.')
            return redirect('all_bookings' if is_faculty_user(request.user) else 'my_bookings')
        else:
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, e)

    return render(request, 'labapp/create_booking.html', {
        'form': form,
        'now_local': now_local,
    })


@never_cache
@login_required
def my_bookings(request):
    now = timezone.now()
    active_bookings = Booking.objects.filter(
        user=request.user, is_active=True, start_time__lte=now, end_time__gte=now,
    )
    past_bookings = Booking.objects.filter(user=request.user).exclude(
        start_time__lte=now, end_time__gte=now,
    )
    return render(request, 'labapp/my_bookings.html', {
        'active_bookings': active_bookings,
        'past_bookings':   past_bookings,
    })


@never_cache
@login_required
def release_booking(request, booking_id: int):
    booking = get_object_or_404(Booking, pk=booking_id)
    user    = request.user
    if booking.user == user or is_faculty_user(user):
        booking.end_booking()
    next_page = request.GET.get('next')
    if next_page:
        return redirect(next_page)
    return redirect('my_bookings' if not is_faculty_user(user) else 'faculty_dashboard')


@never_cache
@login_required
def all_bookings(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    bookings = Booking.objects.select_related('user', 'resource').order_by('-created_at')
    return render(request, 'labapp/all_bookings.html', {'bookings': bookings})


@never_cache
@login_required
def active_bookings_admin(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    now = timezone.now()
    active = Booking.objects.filter(
        is_active=True, start_time__lte=now, end_time__gte=now,
    ).select_related('user', 'resource').order_by('-start_time')
    return render(request, 'labapp/active_bookings_admin.html', {'bookings': active})


@never_cache
@login_required
def active_resources(request):
    now = timezone.now()
    active_bookings = Booking.objects.filter(
        is_active=True, start_time__lte=now, end_time__gte=now,
    ).select_related('user', 'resource').order_by('-start_time')
    return render(request, 'labapp/active_resources.html', {'bookings': active_bookings})


@never_cache
@login_required
def update_booking_description(request, booking_id: int):
    booking = get_object_or_404(Booking, pk=booking_id)
    current_user = request.user
    if booking.user != current_user and not is_faculty_user(current_user):
        messages.error(request, 'You are not authorized to edit this booking.')
        return redirect('my_bookings')
    if request.method == 'POST':
        booking.description = request.POST.get('description', '')
        booking.save(update_fields=['description'])
        messages.success(request, 'Booking description updated.')
        next_page = request.GET.get('next')
        if next_page:
            return redirect(next_page)
        return redirect('my_bookings' if not is_faculty_user(current_user) else 'all_bookings')
    return render(request, 'labapp/update_booking_description.html', {'booking': booking})


# ─────────────────────────────────────────────────────────────────────────────
# Resources
# ─────────────────────────────────────────────────────────────────────────────

@never_cache
@login_required
def add_resource(request):
    user = request.user
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
def delete_resource(request, resource_id: int):
    user = request.user
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
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    resource = get_object_or_404(Resource, pk=resource_id)
    if request.method == 'POST':
        status = request.POST.get('status')
        if status in Resource.Status.values:
            resource.status = status
            resource.save(update_fields=['status'])
            messages.success(request, f'Resource "{resource.name}" updated.')
    return redirect('add_resource')


@never_cache
@login_required
def list_resources(request):
    resources = Resource.objects.all().order_by('name')
    return render(request, 'labapp/list_resources.html', {'resources': resources})


@never_cache
@login_required
def available_resources(request):
    now = timezone.now()
    busy_ids = list(Booking.objects.filter(
        is_active=True, start_time__lte=now, end_time__gte=now,
    ).values_list('resource_id', flat=True).distinct())
    resources = Resource.objects.all().order_by('name')
    return render(request, 'labapp/available_resources.html', {
        'resources': resources,
        'busy_ids':  busy_ids,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Projects
# ─────────────────────────────────────────────────────────────────────────────

@never_cache
@login_required
def projects_list(request):
    projects = Project.objects.select_related('principal_investigator').all()
    return render(request, 'labapp/projects.html', {'projects': projects})


@never_cache
@login_required
def project_detail(request, project_id: int):
    project = get_object_or_404(Project, pk=project_id)
    return render(request, 'labapp/project_detail.html', {'project': project})


@never_cache
@login_required
def add_project(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('projects_list')
    form = ProjectForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Project added successfully.')
        return redirect('projects_list')
    return render(request, 'labapp/add_project.html', {'form': form})


@never_cache
@login_required
def edit_project(request, project_id: int):
    user    = request.user
    if not is_faculty_user(user):
        return redirect('projects_list')
    project = get_object_or_404(Project, pk=project_id)
    form    = ProjectForm(request.POST or None, instance=project)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Project updated successfully.')
        return redirect('projects_list')
    # Return JSON for AJAX modal or render full page
    return render(request, 'labapp/edit_project.html', {'form': form, 'project': project})


# ─────────────────────────────────────────────────────────────────────────────
# Users & Invitations
# ─────────────────────────────────────────────────────────────────────────────

@never_cache
@login_required
def manage_users(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    role_filter = request.GET.get('role', 'all')
    users_qs    = User.objects.filter(is_superuser=False).order_by('username')
    # Build dynamic filter from all Role choices
    valid_roles = [r for r, _ in User.Role.choices]
    if role_filter in valid_roles:
        users_qs = users_qs.filter(role=role_filter)
    roles_for_filter = [('all', 'All Roles')] + list(User.Role.choices)
    return render(request, 'labapp/manage_users.html', {
        'users':            users_qs,
        'roles_for_filter': roles_for_filter,
        'selected_role':    role_filter,
    })


@never_cache
@login_required
def delete_user(request, user_id: int):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    target = get_object_or_404(User, pk=user_id, is_superuser=False)
    if request.method == 'POST':
        if target == user:
            messages.warning(request, 'You cannot delete your own account.')
        else:
            username = target.username
            target.delete()
            messages.success(request, f'User "{username}" deleted.')
    return redirect('manage_users')


@never_cache
@login_required
def user_invitations(request):
    """Send invitations and list current pending ones."""
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    form = UserInvitationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        role  = form.cleaned_data['role']
        inv   = UserInvitation.objects.create(
            email=email, role=role, created_by=request.user,
            expires_at=timezone.now() + timezone.timedelta(hours=48),
        )
        # Build registration link
        register_url = request.build_absolute_uri(f'/register/invite/{inv.token}/')
        try:
            send_mail(
                subject='MI Lab | You have been invited to register',
                message=(
                    f"Hello,\n\nYou have been invited to join MI Lab Resource Manager.\n\n"
                    f"Role: {inv.get_role_display()}\n\n"
                    f"Click the link below to complete your registration (valid for 48 hours):\n"
                    f"{register_url}\n\n— MI Lab, North South University"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
            messages.success(request, f'Invitation sent to {email}.')
        except Exception as e:
            messages.warning(request, f'Invitation created but email failed: {e}')
        return redirect('user_invitations')

    # List only pending, non-expired invitations
    now = timezone.now()
    invitations = UserInvitation.objects.filter(
        used=False, expires_at__gt=now
    ).order_by('-created_at')
    return render(request, 'labapp/user_invitations.html', {
        'form':        form,
        'invitations': invitations,
    })


def register_via_invite(request, token):
    """Registration page accessed via an invitation link."""
    invitation = get_object_or_404(UserInvitation, token=token)

    if not invitation.is_valid:
        return render(request, 'labapp/invite_invalid.html', {'invitation': invitation})

    form = InvitedRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        new_user = User.objects.create_user(
            username   = form.cleaned_data['username'],
            email      = invitation.email,
            first_name = form.cleaned_data['first_name'],
            last_name  = form.cleaned_data['last_name'],
            password   = form.cleaned_data['password1'],
            role       = invitation.role,
        )
        new_user.phone     = form.cleaned_data.get('phone', '')
        new_user.is_active = True
        new_user.save()
        invitation.used = True
        invitation.save(update_fields=['used'])
        messages.success(request, 'Registration complete! You can now log in.')
        return redirect('login')

    return render(request, 'labapp/register_invite.html', {
        'form':       form,
        'invitation': invitation,
    })


@never_cache
@login_required
def add_admin(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    form = AssignAdminForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        selected_user = form.cleaned_data['user']
        grant         = form.cleaned_data['make_admin']
        selected_user.is_staff = grant
        selected_user.save(update_fields=['is_staff'])
        msg = f"{selected_user.username} {'granted' if grant else 'revoked'} admin privileges."
        messages.success(request, msg)
        return redirect('faculty_dashboard')
    admin_statuses = {str(u.id): u.is_staff for u in form.fields['user'].queryset}
    return render(request, 'labapp/add_admin.html', {
        'form':                form,
        'admin_statuses_json': json.dumps(admin_statuses),
    })


@never_cache
@login_required
def list_ras(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    ras = User.objects.filter(role=User.Role.RA, is_superuser=False).order_by('username')
    return render(request, 'labapp/list_ras.html', {'users': ras, 'title': 'Research Assistants'})


@never_cache
@login_required
def list_faculty(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    faculty = User.objects.filter(role=User.Role.FACULTY, is_superuser=False).order_by('username')
    return render(request, 'labapp/list_ras.html', {'users': faculty, 'title': 'Faculty Members'})


@never_cache
@login_required
def delete_ra(request, user_id: int):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    ra_user = get_object_or_404(User, pk=user_id, role=User.Role.RA, is_superuser=False)
    if request.method == 'POST':
        username = ra_user.username
        ra_user.delete()
        messages.success(request, f'User "{username}" deleted.')
    return redirect('list_ras')


# ─────────────────────────────────────────────────────────────────────────────
# Stats & Reports
# ─────────────────────────────────────────────────────────────────────────────

@never_cache
@login_required
def stats(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')

    start_param    = request.GET.get('start')
    end_param      = request.GET.get('end')
    period         = request.GET.get('period', '')
    ra_param       = request.GET.get('ra', 'all')
    resource_param = request.GET.get('resource', 'all')
    now            = timezone.now()

    start_date = end_date = None
    try:
        if start_param: start_date = timezone.make_aware(timezone.datetime.fromisoformat(start_param))
        if end_param:   end_date   = timezone.make_aware(timezone.datetime.fromisoformat(end_param)) + timezone.timedelta(days=1)
    except Exception:
        start_date = end_date = None

    selected_period = period
    if period:
        if   period == 'last_week':     start_date, end_date = now - timezone.timedelta(days=7),   now
        elif period == 'last_month':    start_date, end_date = now - timezone.timedelta(days=30),  now
        elif period == 'last_3_months': start_date, end_date = now - timezone.timedelta(days=90),  now
        elif period == 'last_year':     start_date, end_date = now - timezone.timedelta(days=365), now
        elif period == 'all':           start_date = end_date = None

    if start_date is None and end_date is None and not selected_period:
        start_date, end_date = now - timezone.timedelta(days=7), now
        selected_period = 'last_week'

    bookings = Booking.objects.all().select_related('user', 'resource')
    if start_date: bookings = bookings.filter(start_time__gte=start_date)
    if end_date:   bookings = bookings.filter(start_time__lte=end_date)
    if ra_param != 'all':
        try: bookings = bookings.filter(user__id=int(ra_param))
        except ValueError: pass
    if resource_param != 'all':
        try: bookings = bookings.filter(resource__id=int(resource_param))
        except ValueError: pass

    dur_by_res: dict[str, float]  = {}
    dur_by_user: dict[str, float] = {}
    hour_counts = [0] * 24
    for b in bookings:
        s, e = b.start_time, b.end_time or now
        if start_date: s = max(s, start_date)
        if end_date:   e = min(e, end_date)
        d = (e - s).total_seconds() / 3600
        dur_by_res[b.resource.name]  = dur_by_res.get(b.resource.name, 0.0)  + d
        dur_by_user[b.user.username] = dur_by_user.get(b.user.username, 0.0) + d
        hour_counts[b.start_time.astimezone(timezone.get_current_timezone()).hour] += 1

    sorted_users     = sorted(dur_by_user.items(), key=lambda x: x[1], reverse=True)[:5]
    sorted_resources = sorted(dur_by_res.items(),  key=lambda x: x[1], reverse=True)

    context: Dict[str, Any] = {
        'ra_list':               User.objects.filter(role=User.Role.RA, is_superuser=False).order_by('username'),
        'resource_list':         Resource.objects.all().order_by('name'),
        'selected_ra':           ra_param,
        'selected_resource':     resource_param,
        'start_date':            start_date.date() if start_date else '',
        'end_date':              (end_date - timezone.timedelta(days=1)).date() if end_date else '',
        'selected_period':       selected_period,
        'user_labels_json':      json.dumps([u for u, _ in sorted_users]),
        'user_durations_json':   json.dumps([round(d, 2) for _, d in sorted_users]),
        'resource_labels_json':  json.dumps([r for r, _ in sorted_resources]),
        'resource_durations_json': json.dumps([round(d, 2) for _, d in sorted_resources]),
        'pie_labels_json':       json.dumps([r for r, _ in sorted_resources]),
        'pie_values_json':       json.dumps([round(d, 2) for _, d in sorted_resources]),
        'hour_labels_json':      json.dumps(list(range(24))),
        'hour_counts_json':      json.dumps(hour_counts),
    }
    return render(request, 'labapp/stats.html', context)


@never_cache
@login_required
def print_usage_stats(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('ra_dashboard')
    ra_list = User.objects.filter(
        role__in=[User.Role.RA, User.Role.STUDENT, User.Role.INTERN], is_superuser=False
    ).order_by('username')

    if request.method == 'POST':
        ra_param    = request.POST.get('ra', 'all')
        period      = request.POST.get('period', '')
        start_param = request.POST.get('start')
        end_param   = request.POST.get('end')
        now         = timezone.now()
        start_date = end_date = None
        try:
            if start_param: start_date = timezone.make_aware(timezone.datetime.fromisoformat(start_param))
            if end_param:   end_date   = timezone.make_aware(timezone.datetime.fromisoformat(end_param)) + timezone.timedelta(days=1)
        except Exception:
            start_date = end_date = None
        if period:
            if   period == 'last_week':     start_date, end_date = now - timezone.timedelta(days=7),   now
            elif period == 'last_month':    start_date, end_date = now - timezone.timedelta(days=30),  now
            elif period == 'last_3_months': start_date, end_date = now - timezone.timedelta(days=90),  now
            elif period == 'last_year':     start_date, end_date = now - timezone.timedelta(days=365), now
            elif period == 'all':           start_date = end_date = None
        if start_date is None and end_date is None:
            start_date, end_date = now - timezone.timedelta(days=7), now

        bookings = Booking.objects.all().select_related('user', 'resource')
        if start_date: bookings = bookings.filter(start_time__gte=start_date)
        if end_date:   bookings = bookings.filter(start_time__lte=end_date)
        if ra_param != 'all':
            try: bookings = bookings.filter(user__id=int(ra_param))
            except ValueError: pass

        dur_by_res: Dict[str, float]  = {}
        dur_by_user: Dict[str, float] = {}
        for b in bookings:
            s, e = b.start_time, b.end_time or now
            if start_date: s = max(s, start_date)
            if end_date:   e = min(e, end_date)
            d = (e - s).total_seconds() / 3600
            dur_by_res[b.resource.name]  = dur_by_res.get(b.resource.name, 0.0)  + d
            dur_by_user[b.user.username] = dur_by_user.get(b.user.username, 0.0) + d

        response = HttpResponse(content_type='application/pdf')
        fn_parts = ['usage_stats']
        if ra_param != 'all':
            su = User.objects.filter(pk=ra_param).first()
            if su: fn_parts.append(su.username)
        fn_parts.append(now.strftime('%Y%m%d%H%M%S'))
        response['Content-Disposition'] = f"attachment; filename={'_'.join(fn_parts)}.pdf"
        p = canvas.Canvas(response, pagesize=letter)
        W, H = letter
        y = H - 50
        p.setFont('Helvetica-Bold', 16)
        p.drawString(50, y, 'MI Lab Usage Statistics')
        y -= 30
        p.setFont('Helvetica', 10)
        if start_date: p.drawString(50, y, f"Period: {start_date.date()} – {(end_date - timezone.timedelta(days=1)).date()}"); y -= 20
        p.setFont('Helvetica-Bold', 12); p.drawString(50, y, 'Hours by Resource:'); y -= 18
        p.setFont('Helvetica', 10)
        for r, h in sorted(dur_by_res.items(), key=lambda x: -x[1]):
            p.drawString(60, y, f"{r}: {h:.2f} hrs"); y -= 14
            if y < 80: p.showPage(); y = H - 50; p.setFont('Helvetica', 10)
        y -= 10
        p.setFont('Helvetica-Bold', 12); p.drawString(50, y, 'Hours by User:'); y -= 18
        p.setFont('Helvetica', 10)
        for u, h in sorted(dur_by_user.items(), key=lambda x: -x[1]):
            p.drawString(60, y, f"{u}: {h:.2f} hrs"); y -= 14
            if y < 80: p.showPage(); y = H - 50; p.setFont('Helvetica', 10)
        p.showPage(); p.save()
        return response
    else:
        return render(request, 'labapp/print_usage_stats.html', {
            'ra_list':         ra_list,
            'selected_ra':     'all',
            'selected_period': 'last_week',
            'start_date':      '',
            'end_date':        '',
        })


# ─────────────────────────────────────────────────────────────────────────────
# Updates & Announcements
# ─────────────────────────────────────────────────────────────────────────────

@never_cache
@login_required
def weekly_updates(request):
    from .models import WeeklyUpdate
    user = request.user
    if is_faculty_user(user):
        updates = WeeklyUpdate.objects.select_related('user').all().order_by('-created_at')
    else:
        updates = WeeklyUpdate.objects.filter(user=user).order_by('-created_at')
    return render(request, 'labapp/weekly_updates.html', {'updates': updates})


@never_cache
@login_required
def add_weekly_update(request):
    user = request.user
    if is_faculty_user(user):
        messages.info(request, 'Faculty cannot submit weekly updates.')
        return redirect('weekly_updates')
    form = WeeklyUpdateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        u = form.save(commit=False)
        u.user = user
        u.save()
        messages.success(request, 'Weekly update submitted.')
        return redirect('weekly_updates')
    elif request.method == 'POST':
        messages.error(request, 'Please correct the errors in the form.')
    return render(request, 'labapp/add_weekly_update.html', {'form': form})


@never_cache
@login_required
def announcements(request):
    from .models import Announcement
    all_ann = Announcement.objects.select_related('author').all().order_by('-created_at')
    return render(request, 'labapp/announcements.html', {'announcements': all_ann})


@never_cache
@login_required
def add_announcement(request):
    user = request.user
    if not is_faculty_user(user):
        return redirect('announcements')
    form = AnnouncementForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ann        = form.save(commit=False)
        ann.author = user
        ann.save()
        messages.success(request, 'Announcement posted.')
        return redirect('announcements')
    elif request.method == 'POST':
        messages.error(request, 'Please correct the errors in the form.')
    return render(request, 'labapp/add_announcement.html', {'form': form})


# kept for backwards-compat URL references (now unused)
def register_request(request):
    return redirect('login')


@never_cache
@login_required
def registration_requests_admin(request):
    return redirect('user_invitations')


@never_cache
@login_required
def approve_registration(request, req_id):
    return redirect('user_invitations')


@never_cache
@login_required
def reject_registration(request, req_id):
    return redirect('user_invitations')
