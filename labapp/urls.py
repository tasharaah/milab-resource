from __future__ import annotations

from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from django.conf import settings

urlpatterns = [
    # Home/dashboards
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/ra/', views.ra_dashboard, name='ra_dashboard'),
    path('dashboard/faculty/', views.faculty_dashboard, name='faculty_dashboard'),

    # Booking management
    path('bookings/', views.my_bookings, name='my_bookings'),
    path('bookings/create/', views.create_booking, name='create_booking'),
    path('bookings/release/<int:booking_id>/', views.release_booking, name='release_booking'),

    # User/admin management
    path('add-admin/', views.add_admin, name='add_admin'),
    path('add-resource/', views.add_resource, name='add_resource'),
    path('all-bookings/', views.all_bookings, name='all_bookings'),
    path('registration-requests/', views.registration_requests_admin, name='registration_requests_admin'),
    path('registration-requests/<int:req_id>/approve/', views.approve_registration, name='approve_registration'),
    path('registration-requests/<int:req_id>/reject/', views.reject_registration, name='reject_registration'),
    path('register-request/', views.register_request, name='register_request'),

    # Additional admin/RA list and resource pages
    path('users/ras/', views.list_ras, name='list_ras'),
    path('users/faculty/', views.list_faculty, name='list_faculty'),
    path('resources/all/', views.list_resources, name='list_resources'),
    path('resources/available/', views.available_resources, name='available_resources'),
    path('bookings/active/', views.active_bookings_admin, name='active_bookings_admin'),

    # Resource and user management actions
    path('resources/<int:resource_id>/delete/', views.delete_resource, name='delete_resource'),
    path('resources/<int:resource_id>/update/', views.update_resource, name='update_resource'),
    path('users/ras/delete/<int:user_id>/', views.delete_ra, name='delete_ra'),
    # Active resources view accessible to all authenticated users
    path('resources/active/', views.active_resources, name='active_resources'),
    # Statistics dashboard for admins
    path('stats/', views.stats, name='stats'),

    # Authentication
    path('login/', auth_views.LoginView.as_view(template_name='labapp/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    # Password reset flows
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="labapp/password_reset_form.html",
            email_template_name="labapp/emails/password_reset_email.txt",   # plain text fallback
            html_email_template_name="labapp/emails/password_reset_email.html",  # ✅ HTML
            subject_template_name="labapp/emails/password_reset_subject.txt",
            from_email=settings.DEFAULT_FROM_EMAIL,
        ),
        name="password_reset",
),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='labapp/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='labapp/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='labapp/password_reset_complete.html'), name='password_reset_complete'),
]