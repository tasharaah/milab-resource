"""
Django admin customisations for the MI Lab app.

This module registers the custom User, Resource and Booking models
with the Django admin site to allow superusers and authorised staff
members to manage them easily. Additional configuration of list
display and search fields make the admin interface more helpful.
"""
from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import User, Resource, Booking


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Define the admin pages for our custom User model."""
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        (
            'Permissions',
            {
                'fields': (
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'groups',
                    'user_permissions',
                    'role',
                ),
            },
        ),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': (
                    'username',
                    'password1',
                    'password2',
                    'role',
                    'is_staff',
                    'is_superuser',
                ),
            },
        ),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_staff')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('username',)


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'resource_type', 'computer_code', 'gpu', 'status', 'available')
    list_filter = ('resource_type', 'status')
    search_fields = ('name', 'description', 'computer_code', 'gpu')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'resource',
        'software',
        'start_time',
        'end_time',
        'is_active',
        'created_at',
    )
    list_filter = ('resource', 'is_active', 'software')
    search_fields = ('user__username', 'resource__name', 'software')
    autocomplete_fields = ('user', 'resource')