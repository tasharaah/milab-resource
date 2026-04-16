"""
Forms for the MI Lab application.
"""
from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Booking, Resource, RegistrationRequest, Project, UserInvitation, ProjectLink
from django.contrib.auth.hashers import make_password

User = get_user_model()


class BookingForm(forms.ModelForm):
    start_time = forms.DateTimeField(required=False, widget=forms.HiddenInput())
    end_time   = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        label='End Time',
    )
    PROJECT_OTHER  = '__OTHER__'
    project_select = forms.ChoiceField(
        label='Project', required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_project_select'}),
    )
    project_name_custom = forms.CharField(
        label='Project Name', required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Enter project name',
            'id': 'id_project_name_custom',
        }),
    )
    assignee = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, label='Assign To',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model  = Booking
        fields = ['resource', 'end_time', 'project_name', 'description']
        widgets = {
            'resource':     forms.Select(attrs={'class': 'form-select'}),
            'project_name': forms.HiddenInput(),
            'description':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['start_time'].initial = timezone.localtime().replace(second=0, microsecond=0)
        try:
            now      = timezone.now()
            busy_ids = Booking.objects.filter(
                is_active=True, start_time__lte=now, end_time__gte=now,
            ).values_list('resource_id', flat=True)
            self.fields['resource'].queryset = (
                Resource.objects.filter(status=Resource.Status.OK)
                .exclude(id__in=busy_ids).order_by('name')
            )
        except Exception:
            pass
        try:
            self.fields['assignee'].queryset = User.objects.filter(
                role__in=[User.Role.RA, User.Role.STUDENT, User.Role.INTERN]
            ).order_by('username')
        except Exception:
            pass
        choices = [('', '— Select a project —')]
        for p in Project.objects.order_by('name'):
            choices.append((p.name, p.name))
        choices.append((self.PROJECT_OTHER, 'Others'))
        self.fields['project_select'].choices = choices

    def clean(self):
        cd  = super().clean()
        end = cd.get('end_time')
        res = cd.get('resource')
        now = timezone.now()
        if end and end <= now:
            raise forms.ValidationError('End time must be in the future.')
        if res and end:
            if res.bookings.filter(is_active=True, start_time__lt=end, end_time__gt=now).exists():
                raise forms.ValidationError('This resource is already booked for that time range.')
        ps = cd.get('project_select', '')
        pc = cd.get('project_name_custom', '').strip()
        cd['project_name'] = pc if ps == self.PROJECT_OTHER else (ps or '')
        return cd


class ResourceForm(forms.ModelForm):
    class Meta:
        model   = Resource
        fields  = ['name', 'resource_type', 'status', 'description']
        widgets = {
            'name':          forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. MILab PC1'}),
            'resource_type': forms.Select(attrs={'class': 'form-select'}),
            'status':        forms.Select(attrs={'class': 'form-select'}),
            'description':   forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip().title()
        qs   = Resource.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('A resource with this name already exists.')
        return name


class ProjectForm(forms.ModelForm):
    class Meta:
        model  = Project
        fields = [
            'name', 'principal_investigator', 'co_principal_investigators',
            'research_assistants', 'grant', 'status',
            'start_date', 'estimated_budget_bdt', 'eta',
        ]
        widgets = {
            'name':                        forms.TextInput(attrs={'class': 'form-control'}),
            'principal_investigator':      forms.Select(attrs={'class': 'form-select'}),
            'co_principal_investigators':  forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'research_assistants':         forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
            'grant':                       forms.TextInput(attrs={'class': 'form-control'}),
            'status':                      forms.Select(attrs={'class': 'form-select'}),
            'start_date':                  forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'estimated_budget_bdt':        forms.NumberInput(attrs={'class': 'form-control'}),
            'eta':                         forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
        labels = {
            'eta':                       'Estimated Completion Date',
            'estimated_budget_bdt':      'Estimated Budget (BDT)',
            'co_principal_investigators':'Co-Principal Investigators',
            'research_assistants':       'Research Assistants',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        all_users = User.objects.filter(is_superuser=False).order_by('username')
        self.fields['principal_investigator'].queryset    = all_users
        self.fields['principal_investigator'].empty_label = '— Select PI —'
        self.fields['co_principal_investigators'].queryset = all_users
        self.fields['research_assistants'].queryset        = all_users
        self.fields['principal_investigator'].required     = False
        self.fields['co_principal_investigators'].required = False
        self.fields['research_assistants'].required        = False


class ProjectLinkForm(forms.ModelForm):
    class Meta:
        model  = ProjectLink
        fields = ['platform', 'url', 'label']
        widgets = {
            'platform': forms.Select(attrs={'class': 'form-select'}),
            'url':      forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'label':    forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional display name'}),
        }


class UserProfileForm(forms.ModelForm):
    class Meta:
        model  = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'bio']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name':  forms.TextInput(attrs={'class': 'form-control'}),
            'email':      forms.EmailInput(attrs={'class': 'form-control'}),
            'phone':      forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+880...'}),
            'bio':        forms.Textarea(attrs={'class': 'form-control', 'rows': 3,
                                                'placeholder': 'A short bio about yourself...'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').lower().strip()
        qs    = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('This email is already used by another account.')
        return email


class UserInvitationForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'user@northsouth.edu'}))
    role  = forms.ChoiceField(
        choices=User.Role.choices,
        widget=forms.Select(attrs={'class': 'form-select'}))

    def clean_email(self):
        email = self.cleaned_data.get('email', '').lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('A user with this email already exists.')
        return email


class InvitedRegistrationForm(forms.Form):
    username   = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Choose a username'}))
    first_name = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}))
    last_name  = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}))
    phone      = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+880...'}))
    password1  = forms.CharField(label='Password', strip=False,
                                 widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Create password'}))
    password2  = forms.CharField(label='Confirm Password', strip=False,
                                 widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm password'}))

    def clean_username(self):
        u = self.cleaned_data.get('username', '').strip()
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError('This username is already taken.')
        return u

    def clean(self):
        cd = super().clean()
        p1, p2 = cd.get('password1'), cd.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Passwords do not match.')
        return cd


class AddAdminForm(UserCreationForm):
    role     = forms.ChoiceField(choices=User.Role.choices, widget=forms.Select(attrs={'class': 'form-select'}))
    is_staff = forms.BooleanField(required=False, initial=True)

    class Meta(UserCreationForm.Meta):
        model  = User
        fields = ('username', 'role', 'is_staff')


class AssignAdminForm(forms.Form):
    user       = forms.ModelChoiceField(
        queryset=User.objects.filter(is_superuser=False),
        widget=forms.Select(attrs={'class': 'form-select'}))
    make_admin = forms.BooleanField(required=False, initial=False, label='Grant Admin Privileges')


class WeeklyUpdateForm(forms.ModelForm):
    class Meta:
        from .models import WeeklyUpdate
        model   = WeeklyUpdate
        fields  = ['project_name', 'title', 'content']
        widgets = {
            'project_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Project name'}),
            'title':        forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Update title (optional)'}),
            'content':      forms.HiddenInput(),
        }


class AnnouncementForm(forms.ModelForm):
    class Meta:
        from .models import Announcement
        model   = Announcement
        fields  = ['title', 'content']
        widgets = {
            'title':   forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Announcement title'}),
            'content': forms.HiddenInput(),
        }
