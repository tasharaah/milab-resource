from __future__ import annotations
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from django.conf import settings

urlpatterns = [
    path('',               views.home,              name='home'),
    path('dashboard/',     views.dashboard,          name='dashboard'),
    path('dashboard/ra/',  views.ra_dashboard,       name='ra_dashboard'),
    path('dashboard/faculty/', views.faculty_dashboard, name='faculty_dashboard'),

    # Auth
    path('login/',   auth_views.LoginView.as_view(template_name='labapp/login.html'), name='login'),
    path('logout/',  auth_views.LogoutView.as_view(next_page='login'),                name='logout'),
    path('logout-auto/', views.auto_logout, name='auto_logout'),

    # Bookings
    path('bookings/',                               views.my_bookings,            name='my_bookings'),
    path('bookings/create/',                        views.create_booking,         name='create_booking'),
    path('bookings/release/<int:booking_id>/',      views.release_booking,        name='release_booking'),
    path('bookings/all/',                           views.all_bookings,           name='all_bookings'),
    path('bookings/active/',                        views.active_bookings_admin,  name='active_bookings_admin'),
    path('bookings/update-description/<int:booking_id>/', views.update_booking_description, name='update_booking_description'),

    # Resources
    path('resources/add/',                          views.add_resource,       name='add_resource'),
    path('resources/all/',                          views.list_resources,     name='list_resources'),
    path('resources/available/',                    views.available_resources,name='available_resources'),
    path('resources/active/',                       views.active_resources,   name='active_resources'),
    path('resources/<int:resource_id>/delete/',     views.delete_resource,    name='delete_resource'),
    path('resources/<int:resource_id>/update/',     views.update_resource,    name='update_resource'),

    # Projects
    path('projects/',                               views.projects_list,          name='projects_list'),
    path('projects/add/',                           views.add_project,            name='add_project'),
    path('projects/<int:project_id>/',              views.project_detail,         name='project_detail'),
    path('projects/<int:project_id>/edit/',         views.edit_project,           name='edit_project'),
    path('projects/<int:project_id>/links/add/',    views.add_project_link,       name='add_project_link'),
    path('projects/links/<int:link_id>/delete/',    views.delete_project_link,    name='delete_project_link'),

    # Profile
    path('profile/',                                views.user_profile,     name='user_profile_self'),
    path('profile/<int:user_id>/',                  views.user_profile,     name='user_profile'),
    path('profile/edit/',                           views.edit_profile,     name='edit_profile'),

    # Users
    path('users/manage/',                           views.manage_users,        name='manage_users'),
    path('users/delete/<int:user_id>/',             views.delete_user,         name='delete_user'),
    path('users/ras/',                              views.list_ras,            name='list_ras'),
    path('users/faculty/',                          views.list_faculty,        name='list_faculty'),
    path('users/ras/delete/<int:user_id>/',         views.delete_ra,           name='delete_ra'),
    path('users/invitations/',                      views.user_invitations,    name='user_invitations'),
    path('add-admin/',                              views.add_admin,           name='add_admin'),

    # Stats
    path('stats/',                                  views.stats,              name='stats'),
    path('stats/print/',                            views.print_usage_stats,  name='print_usage_stats'),

    # Updates & Announcements
    path('updates/',                                views.weekly_updates,         name='weekly_updates'),
    path('updates/new/',                            views.add_weekly_update,      name='add_weekly_update'),
    path('announcements/',                          views.announcements,          name='announcements'),
    path('announcements/new/',                      views.add_announcement,       name='add_announcement'),
    path('announcements/<int:ann_id>/edit/',        views.edit_announcement,      name='edit_announcement'),
    path('announcements/<int:ann_id>/delete/',      views.delete_announcement,    name='delete_announcement'),

    # Backwards compat
    path('registration-requests/',                          views.registration_requests_admin,  name='registration_requests_admin'),
    path('registration-requests/<int:req_id>/approve/',     views.approve_registration,         name='approve_registration'),
    path('registration-requests/<int:req_id>/reject/',      views.reject_registration,          name='reject_registration'),
    path('register-request/',                               views.register_request,             name='register_request'),

    # Invitation
    path('register/invite/<uuid:token>/',           views.register_via_invite, name='register_via_invite'),

    # Password reset
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='labapp/password_reset_form.html',
        email_template_name='labapp/emails/password_reset_email.txt',
        html_email_template_name='labapp/emails/password_reset_email.html',
        subject_template_name='labapp/emails/password_reset_subject.txt',
        from_email=settings.DEFAULT_FROM_EMAIL,
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='labapp/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='labapp/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='labapp/password_reset_complete.html'), name='password_reset_complete'),
]
