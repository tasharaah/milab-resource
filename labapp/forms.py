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
    start_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        label='Start Time',
    )
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
            self.fields['resource'].queryset = (
                Resource.objects.filter(status=Resource.Status.OK).order_by('name')
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
        cd    = super().clean()
        start = cd.get('start_time')
        end   = cd.get('end_time')
        res   = cd.get('resource')
        now   = timezone.now()

        if start and start < now - timezone.timedelta(minutes=5):
            raise forms.ValidationError('Start time cannot be in the past.')
        if start and end and end <= start:
            raise forms.ValidationError('End time must be after the start time.')

        if res and start and end:
            conflict = res.bookings.filter(
                is_active=True, start_time__lt=end, end_time__gt=start,
            ).order_by('start_time').first()
            if conflict:
                cs = timezone.localtime(conflict.start_time)
                ce = timezone.localtime(conflict.end_time)
                # Stashed so the view/template can render a clear popup.
                self.conflict_info = {'resource': res.name, 'start': cs, 'end': ce}
                msg = (
                    res.name + ' is already booked from ' + cs.strftime('%d %b %Y, %I:%M %p') +
                    ' to ' + ce.strftime('%d %b %Y, %I:%M %p') +
                    '. Please choose a different time or resource.'
                )
                raise forms.ValidationError(msg, code='conflict')

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


class FullNameModelChoiceField(forms.ModelChoiceField):
    """Displays a user's full name (falling back to username) in dropdown options."""
    def label_from_instance(self, obj):
        return obj.get_full_name() or obj.username


class FullNameModelMultipleChoiceField(forms.ModelMultipleChoiceField):
    """Displays a user's full name (falling back to username) in dropdown options."""
    def label_from_instance(self, obj):
        return obj.get_full_name() or obj.username


def _users_by_full_name():
    """All non-superuser users, ordered alphabetically by full name (falls back to username)."""
    from django.db.models import Case, When, Value, CharField
    from django.db.models.functions import Concat, Trim

    return User.objects.filter(is_superuser=False).annotate(
        sort_name=Case(
            When(first_name='', last_name='', then='username'),
            default=Trim(Concat('first_name', Value(' '), 'last_name', output_field=CharField())),
            output_field=CharField(),
        )
    ).order_by('sort_name')


class ProjectForm(forms.ModelForm):
    principal_investigator = FullNameModelChoiceField(
        queryset=User.objects.none(), required=False, label='Principal Investigator',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    co_principal_investigators = FullNameModelMultipleChoiceField(
        queryset=User.objects.none(), required=False, label='Co-Principal Investigators',
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
    )
    research_assistants = FullNameModelMultipleChoiceField(
        queryset=User.objects.none(), required=False, label='Research Assistants',
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
    )

    class Meta:
        model  = Project
        fields = [
            'name', 'principal_investigator', 'co_principal_investigators',
            'research_assistants', 'grant', 'status',
            'start_date', 'estimated_budget_bdt', 'eta',
        ]
        widgets = {
            'name':                        forms.TextInput(attrs={'class': 'form-control'}),
            'grant':                       forms.TextInput(attrs={'class': 'form-control'}),
            'status':                      forms.Select(attrs={'class': 'form-select'}),
            'start_date':                  forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'estimated_budget_bdt':        forms.NumberInput(attrs={'class': 'form-control'}),
            'eta':                         forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
        labels = {
            'eta':                       'Estimated Completion Date',
            'estimated_budget_bdt':      'Estimated Budget (BDT)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        all_users = _users_by_full_name()
        self.fields['principal_investigator'].queryset    = all_users
        self.fields['principal_investigator'].empty_label = '— Select PI —'
        self.fields['co_principal_investigators'].queryset = all_users
        self.fields['research_assistants'].queryset        = all_users


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
    PROJECT_OTHER = '__OTHER__'
    project_select = forms.ChoiceField(
        label='Project', required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_project_select'}),
    )
    project_name_custom = forms.CharField(
        label='Project Title', required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Enter project title',
            'id': 'id_project_name_custom',
        }),
    )

    class Meta:
        from .models import WeeklyUpdate
        model   = WeeklyUpdate
        fields  = ['project_name', 'title', 'content']
        widgets = {
            'project_name': forms.HiddenInput(),
            'title':        forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Update title (optional)'}),
            'content':      forms.HiddenInput(),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['project_name'].required = False
        from django.db.models import Q
        choices = [('', '— Select a project —')]
        project_names = []
        if user is not None:
            projects = Project.objects.filter(
                Q(principal_investigator=user) |
                Q(co_principal_investigators=user) |
                Q(research_assistants=user)
            ).distinct().order_by('name')
            for p in projects:
                project_names.append(p.name)
                choices.append((p.name, p.name))
        choices.append((self.PROJECT_OTHER, 'Other'))
        self.fields['project_select'].choices = choices

        existing = (self.instance.project_name if self.instance and self.instance.pk else '')
        if existing:
            if existing in project_names:
                self.fields['project_select'].initial = existing
            else:
                self.fields['project_select'].initial = self.PROJECT_OTHER
                self.fields['project_name_custom'].initial = existing

    def clean(self):
        cd = super().clean()
        ps = cd.get('project_select', '')
        pc = cd.get('project_name_custom', '').strip()
        if ps == self.PROJECT_OTHER:
            if not pc:
                self.add_error('project_name_custom', 'Please enter a project title.')
            cd['project_name'] = pc
        elif not ps:
            self.add_error('project_select', 'Please select a project.')
        else:
            cd['project_name'] = ps
        return cd


class AnnouncementForm(forms.ModelForm):
    class Meta:
        from .models import Announcement
        model   = Announcement
        fields  = ['title', 'content']
        widgets = {
            'title':   forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Announcement title'}),
            'content': forms.HiddenInput(),
        }
