"""
Django Admin configuration for organizations app.

Note: Project creation/listing is managed by shizuha-pulse.
ProjectMember is a shadow table with no live role: no code path in this repo
writes it, and since PLAT-5338 nothing reads it either (the project-membership
projection comes from Pulse or fails closed). Production does hold two rows,
written out-of-band on 2026-06-27 — measured, not inferred from a grep, which
cannot see a write that goes through a form or a shell. Add is disabled on the
ModelAdmin below because a row here now grants nothing; change and delete are
kept so those two rows stay visible and removable. Not a live access-control
source.
"""
from django.contrib import admin
from .models import (
    Organization, OrganizationMembership,
    Department, Team, Position, EmployeeProfile, TeamMembership,
    ProjectMember,
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'owner_id', 'plan', 'is_active', 'created_at']
    list_filter = ['plan', 'is_active', 'created_at']
    search_fields = ['name', 'slug', 'billing_email']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ['organization', 'user_email', 'user_id', 'role', 'is_pending', 'is_active', 'created_at']
    list_filter = ['role', 'is_pending', 'is_active', 'created_at']
    search_fields = ['user_email', 'organization__name']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'organization', 'parent', 'head_email', 'is_active']
    list_filter = ['is_active', 'organization']
    search_fields = ['name', 'code', 'organization__name']
    ordering = ['organization', 'name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'team_type', 'lead_email', 'department', 'is_active']
    list_filter = ['team_type', 'is_active', 'organization']
    search_fields = ['name', 'organization__name']
    ordering = ['organization', 'name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ['title', 'code', 'organization', 'department', 'level', 'is_active']
    list_filter = ['level', 'is_active', 'organization']
    search_fields = ['title', 'code', 'organization__name']
    ordering = ['organization', 'level', 'title']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ['get_user_email', 'job_title', 'department', 'employment_status', 'manager_email']
    list_filter = ['employment_status', 'employment_type']
    search_fields = ['membership__user_email', 'job_title', 'employee_id']
    ordering = ['membership__user_email']
    readonly_fields = ['created_at', 'updated_at']

    def get_user_email(self, obj):
        return obj.membership.user_email
    get_user_email.short_description = 'User Email'


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    """Read/remove legacy directory edges; placement writes belong to Pulse."""
    list_display = ['team', 'get_employee_email', 'role', 'is_active', 'joined_at']
    list_filter = ['role', 'is_active']
    search_fields = ['team__name', 'employee_profile__membership__user_email']
    ordering = ['team', 'joined_at']

    def get_employee_email(self, obj):
        return obj.employee_profile.membership.user_email
    get_employee_email.short_description = 'Employee Email'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ProjectMember)
class ProjectMemberAdmin(admin.ModelAdmin):
    """Read-and-remove only. Adding a row here would grant nothing, silently.

    PLAT-5338 (reika P2-2): this form was the one write path into the shadow
    table reachable from a running deployment, and it is invisible to a source
    grep — a ModelAdmin insert produces neither `ProjectMember(` nor
    `ProjectMember.objects.` anywhere in the tree. (The two rows actually in
    production did not come through here — `django_admin_log` is empty — so
    something wrote them out-of-band, which makes the point rather than
    weakening it: the grep was never going to find any of these paths.)

    Since nothing reads the table any more, a staff user filling in `role` and
    `is_active` here would believe they had granted project access and would
    have changed nothing at all. Add is therefore disabled; change and delete
    stay, so the existing rows remain visible and removable.
    """
    list_display = ['organization', 'user_email', 'user_id', 'pulse_project_id', 'role', 'is_active', 'created_at']
    list_filter = ['role', 'is_active', 'organization']
    search_fields = ['user_email', 'organization__name']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']

    def has_add_permission(self, request):
        return False
