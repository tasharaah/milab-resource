"""
Django admin customisations for the MI Lab app.
"""
from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import User, Resource, Booking, Project, UserInvitation


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'phone')}),
        ('Permissions', {'fields': (
            'is_active', 'is_staff', 'is_superuser',
            'groups', 'user_permissions', 'role',
        )}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'role', 'is_staff', 'is_superuser'),
        }),
    )
    list_display  = ('username', 'email', 'first_name', 'last_name', 'role', 'is_staff')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering      = ('username',)


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display  = ('name', 'resource_type', 'status', 'available')
    list_filter   = ('resource_type', 'status')
    search_fields = ('name', 'description')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display  = ('id', 'user', 'resource', 'project_name', 'start_time', 'end_time', 'is_active', 'created_at')
    list_filter   = ('resource', 'is_active')
    search_fields = ('user__username', 'resource__name', 'project_name')
    autocomplete_fields = ('user', 'resource')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display  = ('name', 'principal_investigator', 'status', 'start_date', 'eta')
    list_filter   = ('status',)
    search_fields = ('name', 'grant')
    filter_horizontal = ('co_principal_investigators', 'research_assistants')


@admin.register(UserInvitation)
class UserInvitationAdmin(admin.ModelAdmin):
    list_display  = ('email', 'role', 'created_by', 'created_at', 'expires_at', 'used')
    list_filter   = ('role', 'used')
    search_fields = ('email',)
    readonly_fields = ('token', 'created_at', 'expires_at')
