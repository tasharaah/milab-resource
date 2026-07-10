"""
Views for the MI Lab web application.
"""
from __future__ import annotations

import json
from typing import Any, Dict
import requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail, EmailMultiAlternatives
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether,
)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from django.utils.html import strip_tags

from .models import (
    Booking, Resource, RegistrationRequest, Project, UserInvitation,
    Announcement, WeeklyUpdate, ProjectLink,
)
from .forms import (
    BookingForm, AddAdminForm, ResourceForm, AssignAdminForm,
    WeeklyUpdateForm, AnnouncementForm, ProjectForm,
    UserInvitationForm, InvitedRegistrationForm,
    ProjectLinkForm, UserProfileForm,
)

User = get_user_model()


def is_faculty_user(user) -> bool:
    return user.is_authenticated and (
        user.is_staff or user.is_superuser or
        getattr(user, 'is_faculty', lambda: False)()
    )

def _display_name(u) -> str:
    """Full name for display, falling back to username if not set."""
    return u.get_full_name() or u.username

def send_brevo_email(subject, message, recipients):
    if isinstance(recipients, str):
        recipients = [recipients]

    if not settings.BREVO_API_KEY:
        raise Exception("BREVO_API_KEY is missing")

    payload = {
        "sender": {
            "name": settings.BREVO_SENDER_NAME,
            "email": settings.BREVO_SENDER_EMAIL,
        },
        "to": [{"email": email} for email in recipients],
        "subject": subject,
        "textContent": message,
    }

    response = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "accept": "application/json",
            "api-key": settings.BREVO_API_KEY,
            "content-type": "application/json",
        },
        json=payload,
        timeout=20,
    )

    if response.status_code >= 400:
        raise Exception(f"Brevo API error {response.status_code}: {response.text}")

    return response.json()
# ── Dashboards ─────────────────────────────────────────────────────────────

@login_required
def home(request):
    return redirect('faculty_dashboard' if is_faculty_user(request.user) else 'ra_dashboard')


@never_cache
@login_required
def dashboard(request):
    return redirect('faculty_dashboard' if is_faculty_user(request.user) else 'ra_dashboard')


@never_cache
@login_required
def ra_dashboard(request):
    now = timezone.now()
    busy = Booking.objects.filter(is_active=True, start_time__lte=now, end_time__gte=now
                                  ).values_list('resource_id', flat=True).distinct()
    return render(request, 'labapp/ra_dashboard.html', {
        'available_resources': Resource.objects.exclude(id__in=busy).filter(status=Resource.Status.OK).count(),
        'my_active_bookings':  Booking.objects.filter(user=request.user, is_active=True,
                                                       start_time__lte=now, end_time__gte=now),
    })


@never_cache
@login_required
def faculty_dashboard(request):
    if not is_faculty_user(request.user):
        return redirect('ra_dashboard')

    now = timezone.now()
    busy = Booking.objects.filter(is_active=True, start_time__lte=now, end_time__gte=now
                                  ).values_list('resource_id', flat=True).distinct()

    def parse_range(s, e, p):
        n  = timezone.now()
        sd = ed = None
        try:
            if s: sd = timezone.make_aware(timezone.datetime.fromisoformat(s))
            if e: ed = timezone.make_aware(timezone.datetime.fromisoformat(e)) + timezone.timedelta(days=1)
        except Exception:
            sd = ed = None
        if p:
            if   p == 'last_week':     sd, ed = n - timezone.timedelta(days=7),   n
            elif p == 'last_month':    sd, ed = n - timezone.timedelta(days=30),  n
            elif p == 'last_3_months': sd, ed = n - timezone.timedelta(days=90),  n
            elif p == 'last_year':     sd, ed = n - timezone.timedelta(days=365), n
            elif p == 'all':           sd = ed = None
        if sd is None and ed is None and not p:
            sd, ed = n - timezone.timedelta(days=30), n
        return sd, ed

    ra_list       = User.objects.filter(role=User.Role.RA, is_superuser=False).order_by('username')
    resource_list = Resource.objects.all().order_by('name')

    def chart_data(bookings_qs, sd, ed):
        by_res:  dict[str, float] = {}
        by_user: dict[str, float] = {}
        hours = [0] * 24
        for b in bookings_qs.select_related('resource', 'user'):
            s, e = b.start_time, b.end_time or now
            if sd: s = max(s, sd)
            if ed: e = min(e, ed)
            d = (e - s).total_seconds() / 3600
            by_res[b.resource.name]  = by_res.get(b.resource.name,  0.0) + d
            by_user[_display_name(b.user)] = by_user.get(_display_name(b.user), 0.0) + d
            hours[b.start_time.astimezone(timezone.get_current_timezone()).hour] += 1
        return by_res, by_user, hours

    # Pie chart
    ps, pe = parse_range(request.GET.get('pie_start'), request.GET.get('pie_end'), request.GET.get('pie_period', ''))
    pb = Booking.objects.all()
    if ps: pb = pb.filter(start_time__gte=ps)
    if pe: pb = pb.filter(start_time__lte=pe)
    pra = request.GET.get('pie_ra', 'all')
    if pra != 'all':
        try: pb = pb.filter(user__id=int(pra))
        except ValueError: pass
    pie_c: dict[str, int] = {}
    for b in pb.select_related('resource'):
        pie_c[b.resource.name] = pie_c.get(b.resource.name, 0) + 1
    sp = sorted(pie_c.items(), key=lambda x: x[1], reverse=True)

    # Resource durations
    rs, re = parse_range(request.GET.get('res_start'), request.GET.get('res_end'), request.GET.get('res_period', ''))
    rb = Booking.objects.all()
    if rs: rb = rb.filter(start_time__gte=rs)
    if re: rb = rb.filter(start_time__lte=re)
    rra = request.GET.get('res_ra', 'all')
    if rra != 'all':
        try: rb = rb.filter(user__id=int(rra))
        except ValueError: pass
    dur_res: dict[str, float] = {}
    for b in rb.select_related('resource'):
        s, e = b.start_time, b.end_time or now
        if rs: s = max(s, rs)
        if re: e = min(e, re)
        dur_res[b.resource.name] = dur_res.get(b.resource.name, 0.0) + (e - s).total_seconds() / 3600
    sr = sorted(dur_res.items(), key=lambda x: x[1], reverse=True)

    # Top users
    us, ue = parse_range(request.GET.get('user_start'), request.GET.get('user_end'), request.GET.get('user_period', ''))
    ub = Booking.objects.all()
    if us: ub = ub.filter(start_time__gte=us)
    if ue: ub = ub.filter(start_time__lte=ue)
    dur_usr: dict[str, float] = {}
    for b in ub.select_related('user'):
        s, e = b.start_time, b.end_time or now
        if us: s = max(s, us)
        if ue: e = min(e, ue)
        dur_usr[_display_name(b.user)] = dur_usr.get(_display_name(b.user), 0.0) + (e - s).total_seconds() / 3600
    top5 = sorted(dur_usr.items(), key=lambda x: x[1], reverse=True)[:5]

    # Hours
    hs, he = parse_range(request.GET.get('time_start'), request.GET.get('time_end'), request.GET.get('time_period', ''))
    hb = Booking.objects.all()
    if hs: hb = hb.filter(start_time__gte=hs)
    if he: hb = hb.filter(start_time__lte=he)
    tres = request.GET.get('time_resource', 'all')
    if tres != 'all':
        try: hb = hb.filter(resource__id=int(tres))
        except ValueError: pass
    hcounts = [0] * 24
    for b in hb:
        hcounts[b.start_time.astimezone(timezone.get_current_timezone()).hour] += 1

    ctx: Dict[str, Any] = {
        'total_resources': Resource.objects.count(),
        'available_resources': Resource.objects.exclude(id__in=busy).filter(status=Resource.Status.OK).count(),
        'total_users':    User.objects.filter(is_superuser=False).count(),
        'total_faculty':  User.objects.filter(role=User.Role.FACULTY, is_superuser=False).count(),
        'active_bookings_count': Booking.objects.filter(is_active=True, start_time__lte=now, end_time__gte=now).count(),
        'ra_list': ra_list, 'resource_list': resource_list,
        'pie_selected_ra': pra,
        'pie_start_date': ps.date() if ps else '',
        'pie_end_date': (pe - timezone.timedelta(days=1)).date() if pe else '',
        'res_selected_ra': rra,
        'res_start_date': rs.date() if rs else '',
        'res_end_date': (re - timezone.timedelta(days=1)).date() if re else '',
        'user_start_date': us.date() if us else '',
        'user_end_date': (ue - timezone.timedelta(days=1)).date() if ue else '',
        'time_selected_resource': tres,
        'time_start_date': hs.date() if hs else '',
        'time_end_date': (he - timezone.timedelta(days=1)).date() if he else '',
        'pie_labels_json': json.dumps([r for r, _ in sp]),
        'pie_values_json': json.dumps([c for _, c in sp]),
        'resource_labels_json': json.dumps([r for r, _ in sr]),
        'resource_durations_json': json.dumps([round(d, 2) for _, d in sr]),
        'user_labels_json': json.dumps([u for u, _ in top5]),
        'user_durations_json': json.dumps([round(d, 2) for _, d in top5]),
        'hour_labels_json': json.dumps(list(range(24))),
        'hour_counts_json': json.dumps(hcounts),
    }
    return render(request, 'labapp/faculty_dashboard.html', ctx)


# ── Bookings ───────────────────────────────────────────────────────────────

@never_cache
@login_required
def create_booking(request):
    initial = {}
    rid = request.GET.get('resource')
    if rid:
        try: initial['resource'] = Resource.objects.get(pk=rid)
        except Resource.DoesNotExist: pass
    form = BookingForm(request.POST or None, initial=initial)
    if request.method == 'POST':
        if form.is_valid():
            b = form.save(commit=False)
            assignee = form.cleaned_data.get('assignee')
            if assignee and is_faculty_user(request.user):
                b.user, b.created_by = assignee, request.user
            else:
                b.user = b.created_by = request.user
            b.start_time   = form.cleaned_data['start_time']
            b.project_name = form.cleaned_data.get('project_name', '')
            b.save()
            messages.success(request, 'Booking created successfully.')
            return redirect('all_bookings' if is_faculty_user(request.user) else 'my_bookings')
        for field, errs in form.errors.items():
            for e in errs: messages.error(request, e)
    return render(request, 'labapp/create_booking.html', {
        'form': form, 'now_local': timezone.localtime()})


@never_cache
@login_required
def my_bookings(request):
    now = timezone.now()
    return render(request, 'labapp/my_bookings.html', {
        'active_bookings': Booking.objects.filter(user=request.user, is_active=True,
                                                   start_time__lte=now, end_time__gte=now),
        'past_bookings':   Booking.objects.filter(user=request.user).exclude(
            start_time__lte=now, end_time__gte=now),
    })


@never_cache
@login_required
def release_booking(request, booking_id: int):
    b = get_object_or_404(Booking, pk=booking_id)
    if b.user == request.user or is_faculty_user(request.user):
        b.end_booking()
    nxt = request.GET.get('next')
    return redirect(nxt) if nxt else redirect(
        'my_bookings' if not is_faculty_user(request.user) else 'faculty_dashboard')


@never_cache
@login_required
def all_bookings(request):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    return render(request, 'labapp/all_bookings.html', {
        'bookings': Booking.objects.select_related('user', 'resource').order_by('-created_at')})


@never_cache
@login_required
def active_bookings_admin(request):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    now = timezone.now()
    return render(request, 'labapp/active_bookings_admin.html', {
        'bookings': Booking.objects.filter(is_active=True, start_time__lte=now, end_time__gte=now
                                           ).select_related('user', 'resource').order_by('-start_time')})


@never_cache
@login_required
def active_resources(request):
    now = timezone.now()
    return render(request, 'labapp/active_resources.html', {
        'bookings': Booking.objects.filter(is_active=True, start_time__lte=now, end_time__gte=now
                                           ).select_related('user', 'resource').order_by('-start_time')})


@never_cache
@login_required
def update_booking_description(request, booking_id: int):
    b = get_object_or_404(Booking, pk=booking_id)
    if b.user != request.user and not is_faculty_user(request.user):
        messages.error(request, 'Not authorized.')
        return redirect('my_bookings')
    if request.method == 'POST':
        b.description = request.POST.get('description', '')
        b.save(update_fields=['description'])
        messages.success(request, 'Description updated.')
        nxt = request.GET.get('next')
        return redirect(nxt) if nxt else redirect(
            'my_bookings' if not is_faculty_user(request.user) else 'all_bookings')
    return render(request, 'labapp/update_booking_description.html', {'booking': b})


# ── Resources ──────────────────────────────────────────────────────────────

@never_cache
@login_required
def add_resource(request):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    form = ResourceForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Resource added successfully.')
        return redirect('add_resource')
    return render(request, 'labapp/add_resource.html', {
        'form': form, 'resources': Resource.objects.all().order_by('name')})


@never_cache
@login_required
def delete_resource(request, resource_id: int):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    r = get_object_or_404(Resource, pk=resource_id)
    if request.method == 'POST':
        name = r.name; r.delete()
        messages.success(request, f'Resource "{name}" deleted.')
    return redirect('add_resource')


@never_cache
@login_required
def update_resource(request, resource_id: int):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    r = get_object_or_404(Resource, pk=resource_id)
    if request.method == 'POST':
        s = request.POST.get('status')
        if s in Resource.Status.values:
            r.status = s; r.save(update_fields=['status'])
            messages.success(request, f'Resource "{r.name}" updated.')
    return redirect('add_resource')


@never_cache
@login_required
def list_resources(request):
    return render(request, 'labapp/list_resources.html', {
        'resources': Resource.objects.all().order_by('name')})


@never_cache
@login_required
def available_resources(request):
    now = timezone.now()
    busy_ids = list(Booking.objects.filter(
        is_active=True, start_time__lte=now, end_time__gte=now
    ).values_list('resource_id', flat=True).distinct())
    return render(request, 'labapp/available_resources.html', {
        'resources': Resource.objects.all().order_by('name'), 'busy_ids': busy_ids})


# ── Projects ───────────────────────────────────────────────────────────────

@never_cache
@login_required
def projects_list(request):
    qs = Project.objects.select_related('principal_investigator').all()
    # Filters
    pi_filter     = request.GET.get('pi', '')
    status_filter = request.GET.get('status', '')
    grant_filter  = request.GET.get('grant', '').strip()
    if pi_filter:
        try: qs = qs.filter(principal_investigator__id=int(pi_filter))
        except ValueError: pass
    if status_filter:
        qs = qs.filter(status=status_filter)
    if grant_filter:
        qs = qs.filter(grant__icontains=grant_filter)
    all_pis = User.objects.filter(pi_projects__isnull=False).distinct().order_by('username')
    return render(request, 'labapp/projects.html', {
        'projects': qs, 'all_pis': all_pis,
        'pi_filter': pi_filter, 'status_filter': status_filter, 'grant_filter': grant_filter,
        'status_choices': Project.Status.choices,
    })


@never_cache
@login_required
def project_detail(request, project_id: int):
    project = get_object_or_404(Project, pk=project_id)
    user    = request.user
    is_member   = project.is_member(user)
    can_edit    = is_faculty_user(user)
    can_edit_links = project.can_edit_links(user)
    link_form = ProjectLinkForm() if can_edit_links else None
    return render(request, 'labapp/project_detail.html', {
        'project': project, 'is_member': is_member,
        'can_edit': can_edit, 'can_edit_links': can_edit_links,
        'link_form': link_form,
        'links': project.links.all() if is_member else [],
    })


@never_cache
@login_required
def add_project(request):
    if not is_faculty_user(request.user): return redirect('projects_list')
    form = ProjectForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Project added successfully.')
        return redirect('projects_list')
    return render(request, 'labapp/add_project.html', {'form': form})


@never_cache
@login_required
def edit_project(request, project_id: int):
    if not is_faculty_user(request.user): return redirect('projects_list')
    project = get_object_or_404(Project, pk=project_id)
    form    = ProjectForm(request.POST or None, instance=project)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Project updated.')
        return redirect('projects_list')
    return render(request, 'labapp/edit_project.html', {'form': form, 'project': project})


@never_cache
@login_required
def delete_project(request, project_id: int):
    if not is_faculty_user(request.user): return redirect('projects_list')
    project = get_object_or_404(Project, pk=project_id)
    if request.method == 'POST':
        name = project.name
        project.delete()
        messages.success(request, f'Project "{name}" deleted.')
    return redirect('projects_list')


@never_cache
@login_required
def add_project_link(request, project_id: int):
    project = get_object_or_404(Project, pk=project_id)
    if not project.can_edit_links(request.user):
        messages.error(request, 'Only project members with link permission can add links.')
        return redirect('project_detail', project_id=project_id)
    if request.method == 'POST':
        form = ProjectLinkForm(request.POST)
        if form.is_valid():
            link = form.save(commit=False)
            link.project  = project
            link.added_by = request.user
            link.save()
            messages.success(request, 'Collaboration link added.')
        else:
            messages.error(request, 'Invalid link data.')
    return redirect('project_detail', project_id=project_id)


@never_cache
@login_required
def delete_project_link(request, link_id: int):
    link = get_object_or_404(ProjectLink, pk=link_id)
    if not link.project.can_edit_links(request.user):
        messages.error(request, 'Not authorized.')
        return redirect('project_detail', project_id=link.project_id)
    if request.method == 'POST':
        pid = link.project_id
        link.delete()
        messages.success(request, 'Link removed.')
        return redirect('project_detail', project_id=pid)
    return redirect('project_detail', project_id=link.project_id)


# ── Profile ────────────────────────────────────────────────────────────────

@never_cache
@login_required
def user_profile(request, user_id: int = None):
    if user_id:
        profile_user = get_object_or_404(User, pk=user_id)
        # Only admin/faculty can view others' profiles
        if profile_user != request.user and not is_faculty_user(request.user):
            messages.error(request, 'Not authorized.')
            return redirect('dashboard')
    else:
        profile_user = request.user

    is_own = profile_user == request.user
    # Projects by role
    pi_projects    = Project.objects.filter(principal_investigator=profile_user)
    copi_projects  = profile_user.co_pi_projects.all()
    ra_projects    = profile_user.ra_projects.all()
    recent_bookings = Booking.objects.filter(user=profile_user).order_by('-created_at')[:10]

    return render(request, 'labapp/profile.html', {
        'profile_user':  profile_user,
        'is_own':        is_own,
        'pi_projects':   pi_projects,
        'copi_projects': copi_projects,
        'ra_projects':   ra_projects,
        'recent_bookings': recent_bookings,
    })


@never_cache
@login_required
def edit_profile(request):
    form = UserProfileForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Profile updated successfully.')
        return redirect('user_profile_self')
    return render(request, 'labapp/edit_profile.html', {'form': form})


# ── Users & Invitations ────────────────────────────────────────────────────

@never_cache
@login_required
def manage_users(request):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    role_filter = request.GET.get('role', 'all')
    qs = User.objects.filter(is_superuser=False)
    valid = [r for r, _ in User.Role.choices]
    if role_filter in valid:
        qs = qs.filter(role=role_filter)
    users = sorted(qs, key=lambda u: _display_name(u).lower())
    return render(request, 'labapp/manage_users.html', {
        'users':            users,
        'roles_for_filter': [('all', 'All Roles')] + list(User.Role.choices),
        'selected_role':    role_filter,
    })


@never_cache
@login_required
def delete_user(request, user_id: int):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    target = get_object_or_404(User, pk=user_id, is_superuser=False)
    if request.method == 'POST':
        if target == request.user:
            messages.warning(request, 'You cannot delete your own account.')
        else:
            uname = target.username; target.delete()
            messages.success(request, f'User "{uname}" deleted.')
    return redirect('manage_users')


@never_cache
@login_required
def user_invitations(request):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    form = UserInvitationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        role  = form.cleaned_data['role']
        inv   = UserInvitation.objects.create(
            email=email, role=role, created_by=request.user,
            expires_at=timezone.now() + timezone.timedelta(hours=48))
        reg_url = request.build_absolute_uri(f'/register/invite/{inv.token}/')
        try:
            send_mail(
                subject='MI Lab | You have been invited to register',
                message=(
                    f"You have been invited to join MI Lab Resource Manager.\n\n"
                    f"Role: {inv.get_role_display()}\n\n"
                    f"Register here (valid 48 hours):\n{reg_url}\n\n— MI Lab, NSU"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
            inv.email_sent = True
            inv.save(update_fields=['email_sent'])
            messages.success(request, f'Invitation sent to {email}.')
        except Exception as e:
            messages.warning(request, f'Could not send the invitation email: {e}')
        return redirect('user_invitations')
    return render(request, 'labapp/user_invitations.html', {
        'form': form,
        'invitations': UserInvitation.objects.filter(
            email_sent=True).order_by('-created_at'),
    })


def register_via_invite(request, token):
    invitation = get_object_or_404(UserInvitation, token=token)
    if not invitation.is_valid:
        return render(request, 'labapp/invite_invalid.html', {'invitation': invitation})
    form = InvitedRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        u = User.objects.create_user(
            username=form.cleaned_data['username'],
            email=invitation.email,
            first_name=form.cleaned_data['first_name'],
            last_name=form.cleaned_data['last_name'],
            password=form.cleaned_data['password1'],
            role=invitation.role,
        )
        u.phone = form.cleaned_data.get('phone', '')
        u.is_active = True; u.save()
        invitation.used = True; invitation.save(update_fields=['used'])
        messages.success(request, 'Registration complete! You can now log in.')
        return redirect('login')
    return render(request, 'labapp/register_invite.html', {'form': form, 'invitation': invitation})


@never_cache
@login_required
def add_admin(request):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    form = AssignAdminForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        su = form.cleaned_data['user']
        g  = form.cleaned_data['make_admin']
        su.is_staff = g; su.save(update_fields=['is_staff'])
        messages.success(request, f"{su.username} {'granted' if g else 'revoked'} admin privileges.")
        return redirect('faculty_dashboard')
    admin_statuses = {str(u.id): u.is_staff for u in form.fields['user'].queryset}
    return render(request, 'labapp/add_admin.html', {
        'form': form, 'admin_statuses_json': json.dumps(admin_statuses)})


@never_cache
@login_required
def list_ras(request):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    return render(request, 'labapp/list_ras.html', {
        'users': User.objects.filter(role=User.Role.RA, is_superuser=False).order_by('username'),
        'title': 'Research Assistants'})


@never_cache
@login_required
def list_faculty(request):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    return render(request, 'labapp/list_ras.html', {
        'users': User.objects.filter(role=User.Role.FACULTY, is_superuser=False).order_by('username'),
        'title': 'Faculty Members'})


@never_cache
@login_required
def delete_ra(request, user_id: int):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    u = get_object_or_404(User, pk=user_id, role=User.Role.RA, is_superuser=False)
    if request.method == 'POST':
        uname = u.username; u.delete()
        messages.success(request, f'User "{uname}" deleted.')
    return redirect('list_ras')


# ── Stats & Reports ────────────────────────────────────────────────────────

@never_cache
@login_required
def stats(request):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    now = timezone.now()
    sp = request.GET.get('period', '')
    sd = ed = None
    try:
        if request.GET.get('start'): sd = timezone.make_aware(timezone.datetime.fromisoformat(request.GET['start']))
        if request.GET.get('end'):   ed = timezone.make_aware(timezone.datetime.fromisoformat(request.GET['end'])) + timezone.timedelta(days=1)
    except Exception: sd = ed = None
    sel = sp
    if sp:
        if   sp == 'last_week':     sd, ed = now - timezone.timedelta(days=7),   now
        elif sp == 'last_month':    sd, ed = now - timezone.timedelta(days=30),  now
        elif sp == 'last_3_months': sd, ed = now - timezone.timedelta(days=90),  now
        elif sp == 'last_year':     sd, ed = now - timezone.timedelta(days=365), now
        elif sp == 'all':           sd = ed = None
    if sd is None and ed is None and not sel:
        sd, ed = now - timezone.timedelta(days=7), now; sel = 'last_week'
    ra_p = request.GET.get('ra', 'all')
    re_p = request.GET.get('resource', 'all')
    bqs = Booking.objects.all().select_related('user', 'resource')
    if ed:
        bqs = bqs.filter(start_time__lt=ed)

    if sd:
        bqs = bqs.filter(
            Q(end_time__isnull=True) |
            Q(end_time__gt=sd)
        )
    if ra_p != 'all':
        try: bqs = bqs.filter(user__id=int(ra_p))
        except ValueError: pass
    if re_p != 'all':
        try: bqs = bqs.filter(resource__id=int(re_p))
        except ValueError: pass
    by_res: dict[str, float] = {}; by_usr: dict[str, float] = {}; hc = [0] * 24
    for b in bqs:
        s, e = b.start_time, b.end_time or now
        if sd: s = max(s, sd)
        if ed: e = min(e, ed)
        d = (e - s).total_seconds() / 3600
        by_res[b.resource.name]  = by_res.get(b.resource.name,  0.0) + d
        by_usr[_display_name(b.user)]  = by_usr.get(_display_name(b.user),  0.0) + d
        hc[b.start_time.astimezone(timezone.get_current_timezone()).hour] += 1
    sr = sorted(by_res.items(), key=lambda x: x[1], reverse=True)
    su = sorted(by_usr.items(), key=lambda x: x[1], reverse=True)[:5]
    return render(request, 'labapp/stats.html', {
        'ra_list':       User.objects.filter(role=User.Role.RA, is_superuser=False).order_by('username'),
        'resource_list': Resource.objects.all().order_by('name'),
        'selected_ra': ra_p, 'selected_resource': re_p,
        'start_date': sd.date() if sd else '',
        'end_date': (ed - timezone.timedelta(days=1)).date() if ed else '',
        'selected_period': sel,
        'user_labels_json':       json.dumps([u for u, _ in su]),
        'user_durations_json':    json.dumps([round(d, 2) for _, d in su]),
        'resource_labels_json':   json.dumps([r for r, _ in sr]),
        'resource_durations_json':json.dumps([round(d, 2) for _, d in sr]),
        'pie_labels_json':        json.dumps([r for r, _ in sr]),
        'pie_values_json':        json.dumps([round(d, 2) for _, d in sr]),
        'hour_labels_json':       json.dumps(list(range(24))),
        'hour_counts_json':       json.dumps(hc),
    })


def _build_report_data(ra_param, resource_param, project_param, period, start_param, end_param):
    """Compute aggregated data for the report (shared by preview and PDF)."""
    now = timezone.now()
    sd = ed = None
    try:
        if start_param: sd = timezone.make_aware(timezone.datetime.fromisoformat(start_param))
        if end_param:   ed = timezone.make_aware(timezone.datetime.fromisoformat(end_param)) + timezone.timedelta(days=1)
    except Exception:
        sd = ed = None
    if period:
        if   period == 'last_week':     sd, ed = now - timezone.timedelta(days=7),   now
        elif period == 'last_month':    sd, ed = now - timezone.timedelta(days=30),  now
        elif period == 'last_3_months': sd, ed = now - timezone.timedelta(days=90),  now
        elif period == 'last_year':     sd, ed = now - timezone.timedelta(days=365), now
        elif period == 'all':           sd = ed = None
    if sd is None and ed is None and period != 'all':
        sd, ed = now - timezone.timedelta(days=7), now

    bqs = Booking.objects.all().select_related('user', 'resource')
    if ed:
        bqs = bqs.filter(start_time__lt=ed)

    if sd:
        bqs = bqs.filter(
            Q(end_time__isnull=True) |
            Q(end_time__gt=sd)
        )
    if ra_param != 'all':
        try: bqs = bqs.filter(user__id=int(ra_param))
        except ValueError: pass
    if resource_param != 'all':
        try: bqs = bqs.filter(resource__id=int(resource_param))
        except ValueError: pass
    if project_param != 'all' and project_param:
        bqs = bqs.filter(project_name__iexact=project_param)

    by_res:  dict[str, float] = {}
    by_user: dict[str, float] = {}
    hcounts = [0] * 24
    bookings_list = list(bqs.order_by('start_time'))
    for b in bookings_list:
        s, e = b.start_time, b.end_time or now
        if sd: s = max(s, sd)
        if ed: e = min(e, ed)
        d = (e - s).total_seconds() / 3600
        by_res[b.resource.name]  = by_res.get(b.resource.name,  0.0) + d
        by_user[_display_name(b.user)] = by_user.get(_display_name(b.user), 0.0) + d
        hcounts[b.start_time.astimezone(timezone.get_current_timezone()).hour] += 1
        # Precompute for display so templates never have to do date arithmetic.
        b.duration_hours = d

    return {
        'bookings': bookings_list,
        'by_res':   sorted(by_res.items(),  key=lambda x: x[1], reverse=True),
        'by_user':  sorted(by_user.items(), key=lambda x: x[1], reverse=True),
        'hcounts':  hcounts,
        'sd': sd, 'ed': ed, 'now': now,
    }


def _hbar_chart(labels, values, width, height, value_fmt='%.1fh'):
    d = Drawing(width, height)

    left_margin = min(140, max(70, width * 0.32))

    bc = HorizontalBarChart()
    bc.x = left_margin
    bc.y = 14
    bc.height = max(20, height - 30)
    bc.width = max(40, width - left_margin - 45)

    bc.data = [values]

    bc.categoryAxis.categoryNames = [
        str(l)[:24] for l in labels
    ]

    bc.categoryAxis.labels.fontName = 'Helvetica'
    bc.categoryAxis.labels.fontSize = 8
    bc.categoryAxis.labels.fillColor = colors.HexColor('#1E293B')

    bc.valueAxis.valueMin = 0

    # Give labels space after the longest bar
    max_val = max(values) if values else 0
    bc.valueAxis.valueMax = max(max_val * 1.25, 1)

    bc.valueAxis.labels.fontSize = 7.5
    bc.valueAxis.labels.fillColor = colors.HexColor('#475569')

    bc.bars[0].fillColor = colors.HexColor('#334155')
    bc.bars.strokeColor = None

    bc.barLabelFormat = value_fmt
    bc.barLabels.fontSize = 7.5
    bc.barLabels.fillColor = colors.HexColor('#1E293B')
    bc.barLabels.nudge = 8
    bc.barLabels.boxAnchor = 'w'

    d.add(bc)
    return d


def _vbar_chart(
    labels,
    values,
    width,
    height,
    value_fmt='%.1f',
    hide_zero_labels=False,
):
    """A simple grayscale vertical bar chart (reportlab native, no images)."""
    d = Drawing(width, height)
    bottom_margin = 55
    bc = VerticalBarChart()
    bc.x = 45
    bc.y = bottom_margin
    bc.height = max(20, height - bottom_margin - 20)
    bc.width = max(40, width - 70)
    bc.data = [values]
    bc.categoryAxis.categoryNames = [str(l)[:16] for l in labels]
    bc.categoryAxis.labels.fontName = 'Helvetica'
    bc.categoryAxis.labels.fontSize = 7.5
    bc.categoryAxis.labels.fillColor = colors.HexColor('#1E293B')
    bc.categoryAxis.labels.angle = 30
    bc.categoryAxis.labels.dy = -4
    bc.categoryAxis.labels.dx = -4
    bc.categoryAxis.labels.boxAnchor = 'ne'
    bc.valueAxis.valueMin = 0
    max_val = max(values) if values else 0
    bc.valueAxis.valueMax = max(max_val * 1.15, 1)
    bc.valueAxis.labels.fontSize = 7.5
    bc.valueAxis.labels.fillColor = colors.HexColor('#475569')
    bc.bars[0].fillColor = colors.HexColor('#334155')
    bc.bars.strokeColor = None
    if hide_zero_labels:
        bc.barLabelFormat = lambda v: '' if v == 0 else value_fmt % v
    else:
        bc.barLabelFormat = value_fmt
    bc.barLabels.fontSize = 7.5
    bc.barLabels.fillColor = colors.HexColor('#1E293B')
    bc.barLabels.dy = 6
    d.add(bc)
    return d


@never_cache
@login_required
def print_usage_stats(request):
    if not is_faculty_user(request.user): return redirect('ra_dashboard')
    ra_list       = User.objects.filter(
        role__in=[User.Role.RA, User.Role.STUDENT, User.Role.INTERN], is_superuser=False
    ).order_by('username')
    resource_list = Resource.objects.all().order_by('name')
    project_list  = Project.objects.all().order_by('name')

    # ── Preview (GET with params or POST with action=preview) ──
    if request.method == 'GET' and request.GET.get('preview'):
        params = request.GET
        data = _build_report_data(
            params.get('ra', 'all'), params.get('resource', 'all'),
            params.get('project', 'all'), params.get('period', ''),
            params.get('start', ''), params.get('end', ''),
        )
        return render(request, 'labapp/report_preview.html', {
            'data': data, 'params': params,
            'ra_list': ra_list, 'resource_list': resource_list, 'project_list': project_list,
            'by_res_json':  json.dumps([{'k': r, 'v': round(v, 2)} for r, v in data['by_res']]),
            'by_user_json': json.dumps([{'k': u, 'v': round(v, 2)} for u, v in data['by_user']]),
            'hour_json':    json.dumps(data['hcounts']),
        })

    # ── PDF download ──
    if request.method == 'POST':
        P = request.POST
        data = _build_report_data(
            P.get('ra', 'all'), P.get('resource', 'all'),
            P.get('project', 'all'), P.get('period', ''),
            P.get('start', ''), P.get('end', ''),
        )
        sd, ed, now = data['sd'], data['ed'], data['now']

        response = HttpResponse(content_type='application/pdf')
        ts = now.strftime('%Y%m%d%H%M%S')
        response['Content-Disposition'] = f'attachment; filename="mi_lab_report_{ts}.pdf"'

        doc  = SimpleDocTemplate(response, pagesize=A4,
                                  leftMargin=1.5*cm, rightMargin=1.5*cm,
                                  topMargin=2*cm, bottomMargin=2*cm)
        W, H = A4
        styles = getSampleStyleSheet()

        # Custom styles — a clean black & white report (no images, no color
        # dependency, so nothing can distort or render oddly across viewers).
        title_style = ParagraphStyle(
            'ReportTitle',
            fontSize=20,
            leading=24,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#0F172A'),
            spaceAfter=6,
            alignment=TA_LEFT,
        )

        sub_style = ParagraphStyle(
            'ReportSub',
            fontSize=10,
            leading=13,
            fontName='Helvetica',
            textColor=colors.HexColor('#475569'),
            spaceAfter=16,
        )

        section_style = ParagraphStyle(
            'Section',
            fontSize=13,
            leading=16,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#0F172A'),
            spaceBefore=16,
            spaceAfter=8,
            keepWithNext=True,
        )
        body_style  = ParagraphStyle('Body', fontSize=9, fontName='Helvetica',
                                      textColor=colors.HexColor('#475569'), leading=14)

        cell_style = ParagraphStyle('Cell', fontSize=8.5, fontName='Helvetica',
                                     textColor=colors.HexColor('#1E293B'), leading=11)
        cell_style_muted = ParagraphStyle('CellMuted', parent=cell_style,
                                            textColor=colors.HexColor('#64748B'))

        def cell(text):
            """Wrap a table cell's text in a Paragraph so long values wrap
            instead of overflowing into neighbouring columns."""
            return Paragraph(str(text) if text not in (None, '') else '—', cell_style)

        def cell_muted(text):
            return Paragraph(str(text) if text not in (None, '') else '—', cell_style_muted)

        INK      = colors.HexColor('#0F172A')  # near-black for headers/rules
        SLATE    = colors.HexColor('#334155')
        MUTED    = colors.HexColor('#64748B')
        BORDER   = colors.HexColor('#CBD5E1')
        STRIPE   = colors.HexColor('#F1F5F9')

        story = []

        # ── Header ──
        period_str = ''
        if sd and ed:
            period_str = f"{sd.date()} — {(ed - timezone.timedelta(days=1)).date()}"
        story.append(Paragraph('MI Lab Resource Manager', title_style))
        story.append(Paragraph(f'Usage Report  ·  {period_str}  ·  Generated {now.strftime("%d %b %Y, %I:%M %p")}', sub_style))
        story.append(HRFlowable(width='100%', thickness=1.4, color=INK))
        story.append(Spacer(1, 0.3*cm))

        # ── Summary stat boxes ──
        total_hrs = sum(v for _, v in data['by_res'])
        stat_data = [
            ['Total Bookings', 'Total Hours', 'Resources Used', 'Users Active'],
            [
                str(len(data['bookings'])),
                f"{total_hrs:.1f} hrs",
                str(len(data['by_res'])),
                str(len(data['by_user'])),
            ]
        ]
        stat_table = Table(stat_data, colWidths=[(W - 3*cm) / 4] * 4)
        stat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), INK),
            ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
            ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, 0), 9),
            ('FONTNAME',   (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 1), (-1, 1), 18),
            ('TEXTCOLOR',  (0, 1), (-1, 1), INK),
            ('BACKGROUND', (0, 1), (-1, 1), STRIPE),
            ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX',        (0, 0), (-1, -1), 1, BORDER),
            ('INNERGRID',  (0, 0), (-1, -1), 0.5, BORDER),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        story.append(stat_table)
        story.append(Spacer(1, 0.4*cm))

        # ── Chart: Resource Usage Bar (native vector chart — no distortion) ──
        if data['by_res']:
            story.append(Paragraph('Resource Usage (Hours)', section_style))
            res_names = [r for r, _ in data['by_res'][:10]]
            res_vals  = [round(v, 2) for _, v in data['by_res'][:10]]
            chart_h = max(2.2*cm, min(7*cm, len(res_names) * 1.1*cm))
            story.append(_hbar_chart(res_names, res_vals, width=16.5*cm, height=chart_h, value_fmt='%.1fh'))
            story.append(Spacer(1, 0.3*cm))

        # ── Chart: Top Users ──
        if data['by_user']:
            story.append(Paragraph('Top Users by Hours', section_style))

            top = data['by_user'][:8]
            user_names = [u for u, _ in top]
            user_vals = [round(v, 2) for _, v in top]

            story.append(
                _vbar_chart(
                    user_names,
                    user_vals,
                    width=16.5*cm,
                    height=6.2*cm,
                    value_fmt='%.1f',
                )
            )

            story.append(Spacer(1, 0.3*cm))

        # ── Chart: Hour Distribution ──
        hour_labels = [
            f'{h:02d}:00' if h % 2 == 0 else ''
            for h in range(24)
        ]

        hour_chart = _vbar_chart(
            hour_labels,
            data['hcounts'],
            width=16.5*cm,
            height=5.5*cm,
            value_fmt='%.0f',
            hide_zero_labels=True,
        )

        story.append(
            KeepTogether([
                Paragraph('Booking Activity by Hour of Day', section_style),
                hour_chart,
                Spacer(1, 0.3*cm),
            ])
        )
        story.append(Spacer(1, 0.3*cm))

        # ── Resource hours table ──
        if data['by_res']:
            story.append(Paragraph('Hours by Resource', section_style))
            tdata = [['Resource', 'Total Hours', 'Share']]
            total = sum(v for _, v in data['by_res']) or 1
            for rname, hrs in data['by_res']:
                tdata.append([cell(rname), f'{hrs:.2f}', f'{hrs/total*100:.1f}%'])
            t = Table(tdata, colWidths=[9*cm, 3*cm, 3*cm])
            t.setStyle(TableStyle([
                ('BACKGROUND',  (0, 0), (-1, 0), INK),
                ('TEXTCOLOR',   (0, 0), (-1, 0), colors.white),
                ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE',    (0, 0), (-1, -1), 9),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, STRIPE]),
                ('ALIGN',       (1, 0), (-1, -1), 'CENTER'),
                ('GRID',        (0, 0), (-1, -1), 0.5, BORDER),
                ('TOPPADDING',  (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(t)
            story.append(Spacer(1, 0.3*cm))

        # ── Top users table ──
        if data['by_user']:
            story.append(Paragraph('Hours by User', section_style))
            udata = [['User', 'Total Hours', 'Share']]
            total = sum(v for _, v in data['by_user']) or 1
            for uname, hrs in data['by_user']:
                udata.append([cell(uname), f'{hrs:.2f}', f'{hrs/total*100:.1f}%'])
            ut = Table(udata, colWidths=[9*cm, 3*cm, 3*cm])
            ut.setStyle(TableStyle([
                ('BACKGROUND',  (0, 0), (-1, 0), SLATE),
                ('TEXTCOLOR',   (0, 0), (-1, 0), colors.white),
                ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE',    (0, 0), (-1, -1), 9),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, STRIPE]),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN',       (1, 0), (-1, -1), 'CENTER'),
                ('GRID',        (0, 0), (-1, -1), 0.5, BORDER),
                ('TOPPADDING',  (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(ut)
            story.append(Spacer(1, 0.3*cm))

        # ── Detailed bookings table ──
        story.append(Paragraph('Detailed Booking Log', section_style))
        bdata = [['#', 'User', 'Resource', 'Project', 'Start', 'End', 'Duration']]
        tz = timezone.get_current_timezone()
        for i, b in enumerate(data['bookings'], 1):
            d = getattr(b, 'duration_hours', None)
            if d is None:
                s = b.start_time; e = b.end_time or now
                if sd: s = max(s, sd)
                if ed: e = min(e, ed)
                d = (e - s).total_seconds() / 3600
            bdata.append([
                str(i),
                cell(_display_name(b.user)),
                cell(b.resource.name),
                cell_muted(b.project_name),
                cell_muted(b.start_time.astimezone(tz).strftime('%d-%b %H:%M')),
                cell_muted(b.end_time.astimezone(tz).strftime('%d-%b %H:%M') if b.end_time else '—'),
                f'{d:.1f}h',
            ])
        bt = Table(
            bdata,
            colWidths=[
                1*cm,
                3.5*cm,
                3*cm,
                3.5*cm,
                2.5*cm,
                2.5*cm,
                1.5*cm,
            ],
            repeatRows=1,
            splitByRow=1,
        )
        bt.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0), INK),
            ('TEXTCOLOR',     (0, 0), (-1, 0), colors.white),
            ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1, -1), 8),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, STRIPE]),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID',          (0, 0), (-1, -1), 0.3, BORDER),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(bt)

        doc.build(story)
        return response

    # ── GET: Show config form ──
    return render(request, 'labapp/print_usage_stats.html', {
        'ra_list': ra_list, 'resource_list': resource_list, 'project_list': project_list,
        'selected_ra': 'all', 'selected_resource': 'all', 'selected_project': 'all',
        'selected_period': 'last_week', 'start_date': '', 'end_date': '',
    })


# ── Announcements ──────────────────────────────────────────────────────────

@never_cache
@login_required
def announcements(request):
    from .models import Announcement
    ann_list = Announcement.objects.select_related('author').all().order_by('-created_at')
    request.user.last_seen_announcements = timezone.now()
    request.user.save(update_fields=['last_seen_announcements'])
    return render(request, 'labapp/announcements.html', {'announcements': ann_list})


@never_cache
@login_required
def add_announcement(request):
    if not is_faculty_user(request.user): return redirect('announcements')
    form = AnnouncementForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ann = form.save(commit=False)
        ann.author = request.user
        ann.save()
        # Email all users
        recipients = list(User.objects.filter(is_active=True).exclude(email='').values_list('email', flat=True))
        if recipients:
            try:
                plain = f"{ann.title}\n\n{strip_tags(ann.content)}\n\n— MI Lab, NSU"

                send_mail(
                    subject=f'MI Lab Announcement: {ann.title}',
                    message=plain,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=recipients,
                    fail_silently=False,
                )

            except Exception:
                pass
        messages.success(request, 'Announcement posted and users notified.')
        return redirect('announcements')
    elif request.method == 'POST':
        messages.error(request, 'Please fix the errors below.')
    return render(request, 'labapp/add_announcement.html', {'form': form})


@never_cache
@login_required
def edit_announcement(request, ann_id: int):
    from .models import Announcement
    ann = get_object_or_404(Announcement, pk=ann_id)
    if not is_faculty_user(request.user) and ann.author != request.user:
        messages.error(request, 'Not authorized.')
        return redirect('announcements')
    form = AnnouncementForm(request.POST or None, instance=ann)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Announcement updated.')
        return redirect('announcements')
    return render(request, 'labapp/add_announcement.html', {'form': form, 'editing': True, 'ann': ann})


@never_cache
@login_required
def delete_announcement(request, ann_id: int):
    from .models import Announcement
    ann = get_object_or_404(Announcement, pk=ann_id)
    if not is_faculty_user(request.user) and ann.author != request.user:
        messages.error(request, 'Not authorized.')
        return redirect('announcements')
    if request.method == 'POST':
        ann.delete()
        messages.success(request, 'Announcement deleted.')
    return redirect('announcements')


# ── Weekly Updates ──────────────────────────────────────────────────────────

@never_cache
@login_required
def weekly_updates(request):
    from .models import WeeklyUpdate
    if is_faculty_user(request.user):
        updates = WeeklyUpdate.objects.select_related('user').all().order_by('-created_at')
    else:
        updates = WeeklyUpdate.objects.filter(user=request.user).order_by('-created_at')
    request.user.last_seen_weekly_updates = timezone.now()
    request.user.save(update_fields=['last_seen_weekly_updates'])
    return render(request, 'labapp/weekly_updates.html', {'updates': updates})


@never_cache
@login_required
def add_weekly_update(request):
    if is_faculty_user(request.user):
        messages.info(request, 'Faculty cannot submit weekly updates.')
        return redirect('weekly_updates')
    form = WeeklyUpdateForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        u = form.save(commit=False); u.user = request.user; u.save()
        messages.success(request, 'Weekly update submitted.')
        return redirect('weekly_updates')
    elif request.method == 'POST':
        messages.error(request, 'Please correct the errors.')
    return render(request, 'labapp/add_weekly_update.html', {'form': form})


@never_cache
@login_required
def edit_weekly_update(request, update_id: int):
    from .models import WeeklyUpdate
    upd = get_object_or_404(WeeklyUpdate, pk=update_id)
    if upd.user != request.user:
        messages.error(request, 'Not authorized.')
        return redirect('weekly_updates')
    form = WeeklyUpdateForm(request.POST or None, instance=upd, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Weekly update updated.')
        return redirect('weekly_updates')
    elif request.method == 'POST':
        messages.error(request, 'Please correct the errors.')
    return render(request, 'labapp/add_weekly_update.html', {'form': form, 'editing': True, 'upd': upd})


@never_cache
@login_required
def delete_weekly_update(request, update_id: int):
    from .models import WeeklyUpdate
    upd = get_object_or_404(WeeklyUpdate, pk=update_id)
    if not is_faculty_user(request.user):
        messages.error(request, 'Not authorized.')
        return redirect('weekly_updates')
    if request.method == 'POST':
        upd.delete()
        messages.success(request, 'Weekly update deleted.')
    return redirect('weekly_updates')


# ── Backwards-compat stubs ──────────────────────────────────────────────────

def register_request(request):              return redirect('login')
def registration_requests_admin(request):   return redirect('user_invitations')
def approve_registration(request, req_id):  return redirect('user_invitations')
def reject_registration(request, req_id):   return redirect('user_invitations')
