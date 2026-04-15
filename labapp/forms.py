"""
Forms for the MI Lab application.
"""
from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import Booking, Resource, RegistrationRequest, Project, UserInvitation
from django.contrib.auth.hashers import make_password

User = get_user_model()


class BookingForm(forms.ModelForm):
    """Form for creating a new booking."""

    start_time = forms.DateTimeField(
        required=False,
        widget=forms.HiddenInput(),
    )
    end_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        label='End Time',
    )

    # Project selection: dropdown of existing projects + 'Others'
    PROJECT_OTHER = '__OTHER__'
    project_select = forms.ChoiceField(
        label='Project',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_project_select'}),
    )
    # Custom project name shown when 'Others' is selected
    project_name_custom = forms.CharField(
        label='Project Name',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter project name',
            'id': 'id_project_name_custom',
        }),
    )

    class Meta:
        model = Booking
        fields = ['resource', 'end_time', 'project_name', 'description']
        widgets = {
            'resource':     forms.Select(attrs={'class': 'form-select'}),
            'project_name': forms.HiddenInput(),
            'description':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    assignee = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label='Assign To',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.localtime().replace(second=0, microsecond=0)
        self.fields['start_time'].initial = now

        try:
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
            pass

        try:
            self.fields['assignee'].queryset = User.objects.filter(
                role__in=[User.Role.RA, User.Role.STUDENT, User.Role.INTERN]
            ).order_by('username')
        except Exception:
            pass

        # Build project dropdown choices
        project_choices = [('', '— Select a project —')]
        for p in Project.objects.order_by('name'):
            project_choices.append((p.name, p.name))
        project_choices.append((self.PROJECT_OTHER, 'Others'))
        self.fields['project_select'].choices = project_choices

    def clean(self):
        cleaned_data = super().clean()
        end      = cleaned_data.get('end_time')
        resource = cleaned_data.get('resource')
        now      = timezone.now()

        if end and end <= now:
            raise forms.ValidationError('End time must be in the future.')
        if resource and end:
            overlapping = resource.bookings.filter(
                is_active=True,
                start_time__lt=end,
                end_time__gt=now,
            )
            if overlapping.exists():
                raise forms.ValidationError('This resource is already booked for the selected time range.')

        # Resolve project_name from the two-field pattern
        proj_select = cleaned_data.get('project_select', '')
        proj_custom = cleaned_data.get('project_name_custom', '').strip()
        if proj_select == self.PROJECT_OTHER:
            cleaned_data['project_name'] = proj_custom
        elif proj_select:
            cleaned_data['project_name'] = proj_select
        else:
            cleaned_data['project_name'] = ''

        return cleaned_data


class ResourceForm(forms.ModelForm):
    """Form for creating or updating a lab resource."""

    class Meta:
        model = Resource
        fields = ['name', 'resource_type', 'status', 'description']
        widgets = {
            'name':          forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. MILab PC1'}),
            'resource_type': forms.Select(attrs={'class': 'form-select'}),
            'status':        forms.Select(attrs={'class': 'form-select'}),
            'description':   forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        # Capitalize each word
        name = name.title()
        # Uniqueness check (exclude self on edit)
        qs = Resource.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('A resource with this name already exists.')
        return name


class ProjectForm(forms.ModelForm):
    """Form for adding or editing a lab project."""

    class Meta:
        model = Project
        fields = [
            'name', 'principal_investigator', 'co_principal_investigators',
            'research_assistants', 'grant', 'status',
            'start_date', 'estimated_budget_bdt', 'eta',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Project name'}),
            'principal_investigator': forms.Select(attrs={'class': 'form-select'}),
            'co_principal_investigators': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'research_assistants': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'grant': forms.TextInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'estimated_budget_bdt': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Amount in BDT'}),
            'eta': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
        labels = {
            'eta': 'Estimated Completion Date',
            'estimated_budget_bdt': 'Estimated Budget (BDT)',
            'co_principal_investigators': 'Co-Principal Investigators',
            'research_assistants': 'Research Assistants',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        all_users = User.objects.filter(is_superuser=False).order_by('username')
        self.fields['principal_investigator'].queryset = all_users
        self.fields['principal_investigator'].empty_label = '— Select PI —'
        self.fields['co_principal_investigators'].queryset = all_users
        self.fields['research_assistants'].queryset = all_users
        self.fields['principal_investigator'].required = False
        self.fields['co_principal_investigators'].required = False
        self.fields['research_assistants'].required = False


class UserInvitationForm(forms.Form):
    """Form for admins to send user invitations."""

    email = forms.EmailField(
        label='Email Address',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'user@northsouth.edu'}),
    )
    role = forms.ChoiceField(
        label='Role',
        choices=User.Role.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def clean_email(self):
        email = self.cleaned_data.get('email', '').lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('A user with this email already exists.')
        return email


class InvitedRegistrationForm(forms.Form):
    """Registration form completed via an invitation link."""

    username   = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Choose a username'}),
    )
    first_name = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
    )
    last_name  = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
    )
    phone      = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+880...'}),
        max_length=20,
    )
    password1  = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Create password'}),
        strip=False,
    )
    password2  = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm password'}),
        strip=False,
    )

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Passwords do not match.')
        return cleaned


class AddAdminForm(UserCreationForm):
    role = forms.ChoiceField(
        choices=User.Role.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    is_staff = forms.BooleanField(required=False, initial=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'role', 'is_staff')


class AssignAdminForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=User.objects.filter(is_superuser=False),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    make_admin = forms.BooleanField(required=False, initial=False, label='Grant Admin Privileges')


class WeeklyUpdateForm(forms.ModelForm):
    class Meta:
        from .models import WeeklyUpdate
        model = WeeklyUpdate
        fields = ['project_name', 'title', 'content']
        widgets = {
            'project_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Project name'}),
            'title':        forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Update title (optional)'}),
            'content':      forms.HiddenInput(),
        }


class AnnouncementForm(forms.ModelForm):
    class Meta:
        from .models import Announcement
        model = Announcement
        fields = ['title', 'content']
        widgets = {
            'title':   forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Announcement title'}),
            'content': forms.HiddenInput(),
        }
