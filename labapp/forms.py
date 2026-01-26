"""
Forms for the MI Lab application.

This module defines model and custom forms used throughout the web
application. Using Django's forms framework provides automatic
validation and integration with templates.
"""
from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import Booking, Resource, RegistrationRequest

from django.contrib.auth.hashers import make_password

User = get_user_model()


class BookingForm(forms.ModelForm):
    """
    Form for creating a new booking. The booking always starts
    immediately, so the start time field is hidden and automatically
    populated. Users only need to select the resource, end time,
    software and an optional description.
    """

    # Hide start_time and prepopulate it with the current local time. The
    # field is not required because we will set it in the view when
    # saving the booking.
    start_time = forms.DateTimeField(
        required=False,
        widget=forms.HiddenInput(),
    )
    end_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        label='End Time',
    )

    class Meta:
        model = Booking
        # We intentionally exclude start_time from the form fields list
        fields = ['resource', 'end_time', 'software', 'description']
        widgets = {
            'resource': forms.Select(attrs={'class': 'form-select'}),
            'software': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Software/Tool'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Prepopulate start_time with current local time to assist hidden field
        now = timezone.localtime().replace(second=0, microsecond=0)
        self.fields['start_time'].initial = now

        # Restrict resource choices to only those that are operational (status OK) and
        # not currently booked. A resource is considered unavailable if there is
        # an active booking overlapping the present moment. We avoid presenting
        # resources that are in use so users cannot double book them. This
        # complements the overlap validation logic in `clean()`.
        try:
            from .models import Resource, Booking
            # Determine resources currently in use
            current_time = timezone.now()
            busy_ids = Booking.objects.filter(
                is_active=True,
                start_time__lte=current_time,
                end_time__gte=current_time,
            ).values_list('resource_id', flat=True)
            self.fields['resource'].queryset = (
                Resource.objects.filter(status=Resource.Status.OK)
                .exclude(id__in=busy_ids)
                .order_by('name')
            )
        except Exception:
            # Fallback: show all resources
            pass

    def clean(self):
        """
        Validate the booking form. Ensures end time is after the
        current time and there are no overlapping active bookings for
        the chosen resource. The start time is not editable by the
        user and is set to the current time when the booking is saved.
        """
        cleaned_data = super().clean()
        end = cleaned_data.get('end_time')
        resource = cleaned_data.get('resource')
        now = timezone.now()
        # End time must be in the future relative to now
        if end and end <= now:
            raise forms.ValidationError('End time must be in the future.')
        # Check overlapping bookings (from now to end)
        if resource and end:
            overlapping = resource.bookings.filter(
                is_active=True,
                start_time__lt=end,
                end_time__gt=now,
            )
            if overlapping.exists():
                raise forms.ValidationError('This resource is already booked for the selected time range.')
        return cleaned_data


class AddAdminForm(UserCreationForm):
    """Form for faculty to create new users (RAs or faculty)."""

    role = forms.ChoiceField(
        choices=User.Role.choices,
        label='Role',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    is_staff = forms.BooleanField(
        required=False,
        initial=True,
        label='Staff/Admin',
        help_text='Designates whether the user can log into the admin site.',
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'role', 'is_staff')


# New form to assign admin privileges to existing users
class AssignAdminForm(forms.Form):
    """Form to grant or revoke admin status for existing users."""
    user = forms.ModelChoiceField(
        queryset=User.objects.filter(is_superuser=False),
        label='User',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    make_admin = forms.BooleanField(
        required=False,
        initial=False,
        label='Grant Admin Privileges',
    )


class ResourceForm(forms.ModelForm):
    """Form for creating or updating a lab resource. Only accessible to admins."""

    class Meta:
        model = Resource
        fields = ['name', 'resource_type', 'computer_code', 'gpu', 'status', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'resource_type': forms.Select(attrs={'class': 'form-select'}),
            'computer_code': forms.TextInput(attrs={'class': 'form-control'}),
            'gpu': forms.TextInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class RegistrationRequestForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Create password"}),
        strip=False,
    )
    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Confirm password"}),
        strip=False,
    )

    class Meta:
        model = RegistrationRequest
        fields = ["username", "email", "first_name", "last_name"]
        widgets = { ... }  # keep yours

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        # Uniqueness checks for username and email
        username = cleaned.get("username")
        email = cleaned.get("email")
        if username:
            # Check against existing users and pending requests
            if User.objects.filter(username=username).exists() or RegistrationRequest.objects.filter(username=username, status=RegistrationRequest.Status.PENDING).exists():
                self.add_error("username", "A user with this username already exists. Please choose another.")
        if email:
            if User.objects.filter(email=email).exists() or RegistrationRequest.objects.filter(email=email, status=RegistrationRequest.Status.PENDING).exists():
                self.add_error("email", "A user with this email already exists. Please choose another.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.password_hash = make_password(self.cleaned_data["password1"])
        if commit:
            obj.save()
        return obj
