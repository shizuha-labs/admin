"""
Serializers for Organization and HR Hierarchy models.

Note: Project and ProjectMembership serializers have been removed.
Projects are now solely managed by shizuha-pulse.
"""
import logging
import os

from rest_framework import serializers
from .models import (
    Organization, OrganizationMembership,
    JITElevatedAccessGrant,
    Department, Team, Position, EmployeeProfile, TeamMembership,
    OrganizationServiceAccess,
    EmploymentStatus, EmploymentType, TeamType, TeamRole
)

logger = logging.getLogger(__name__)


def _resolve_user_id_by_email(email):
    """
    Resolve an email to a shizuha-id user_id via the internal by-email endpoint.
    Returns the user_id as an int if resolved, else None.

    Used at employee-profile write time so that manager_email / dotted_line_manager_email
    get indexed on the corresponding *_id columns immediately (PLAT-18 / PLAT-5 bug class).
    Network / timeout / non-200 failures must NOT block the write — callers fall through
    to None and the email field remains on the row as a fallback for display.

    Mirrors the helper shape used by shizuha-labs/drive PR #3 (PLAT-14).
    """
    if not email:
        return None

    import requests  # local import so test suites can monkeypatch trivially

    id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
    try:
        resp = requests.get(
            f'{id_url}/internal/users/by-email/',
            params={'email': email},
            timeout=5,
        )
    except Exception as e:
        logger.info("shizuha-id by-email resolve failed for %s: %s", email, e)
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    uid = data.get('id')
    if uid is None:
        return None
    try:
        return int(uid)
    except (TypeError, ValueError):
        return None


# =============================================================================
# Organization Serializers
# =============================================================================

class OrganizationSerializer(serializers.ModelSerializer):
    """Serializer for Organization model."""
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'slug', 'description',
            'logo_url', 'website',
            'plan', 'billing_email',
            'owner_id', 'is_active', 'is_personal',
            'created_at', 'updated_at',
            'member_count'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'member_count', 'is_personal']

    def get_member_count(self, obj):
        return obj.memberships.filter(is_active=True).count()


class OrganizationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating organizations."""
    class Meta:
        model = Organization
        fields = ['name', 'slug', 'description', 'logo_url', 'website']

    def validate_slug(self, value):
        value = value.lower()
        if Organization.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Organization with this slug already exists")
        return value


class CompanyOSSerializer(serializers.ModelSerializer):
    """PLAT-434: read-only Company-OS view of an Organization (mission/vision/
    strategic bets/values + handbook link), surfaced to agents via the
    `company_os` MCP tool."""
    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'slug',
            'mission', 'vision', 'strategic_bets', 'values_summary', 'handbook_url',
        ]
        read_only_fields = fields


class OrganizationMembershipSerializer(serializers.ModelSerializer):
    """Serializer for OrganizationMembership."""
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    organization_slug = serializers.CharField(source='organization.slug', read_only=True)
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationMembership
        fields = [
            'id', 'organization', 'organization_name', 'organization_slug',
            'user_id', 'user_email', 'display_name', 'role',
            'is_pending', 'is_active',
            'invited_by_id', 'invited_at', 'accepted_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_display_name(self, obj):
        """Resolve full name from shizuha-id instead of stored username."""
        import os
        import requests as http_requests
        from django.core.cache import cache

        if obj.user_id:
            cache_key = f"admin_user_fullname:{obj.user_id}"
            cached = cache.get(cache_key)
            if cached:
                return cached
            try:
                id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
                resp = http_requests.get(f'{id_url}/internal/users/{obj.user_id}/', timeout=3)
                if resp.status_code == 200:
                    u = resp.json()
                    first = u.get('first_name', '').strip()
                    last = u.get('last_name', '').strip()
                    full = f"{first} {last}".strip()
                    if full:
                        cache.set(cache_key, full, 300)
                        return full
            except Exception:
                pass
        # Fallback to stored display_name or email prefix
        return obj.display_name or (obj.user_email.split('@')[0] if obj.user_email else 'Unknown')


class JITElevatedAccessGrantSerializer(serializers.ModelSerializer):
    """Serializer for PLAT-1346 scoped, time-bound elevated-access grants."""
    organization_slug = serializers.CharField(source='organization.slug', read_only=True)
    approver_team_name = serializers.CharField(source='approver_team.name', read_only=True, allow_null=True)
    target_team_name = serializers.CharField(source='target_team.name', read_only=True, allow_null=True)
    active = serializers.SerializerMethodField()

    class Meta:
        model = JITElevatedAccessGrant
        fields = [
            'id', 'organization', 'organization_slug',
            'requester_user_id', 'requester_email',
            'scope', 'requested_role', 'reason', 'task_key', 'ttl_seconds',
            'status', 'approval_path', 'owning_team', 'risk_level', 'policy_slug',
            'approver_team', 'approver_team_name', 'target_team', 'target_team_name',
            'target_user_id', 'target_role', 'policy_key', 'policy_version',
            'policy_digest', 'target_constraints', 'constraint_digest',
            'max_uses', 'uses_consumed',
            'decided_by_user_id', 'decided_by_email', 'decision_note', 'decided_at',
            'expires_at', 'revoked_at', 'created_at', 'updated_at', 'active',
        ]
        read_only_fields = fields

    def get_active(self, obj):
        return obj.is_active_now()


class OrganizationMemberInviteSerializer(serializers.Serializer):
    """Serializer for inviting members to an organization."""
    user_email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=['admin', 'member', 'viewer'],
        default='member'
    )


# =============================================================================
# HR Hierarchy Serializers - Department
# =============================================================================

class DepartmentMinimalSerializer(serializers.ModelSerializer):
    """Minimal department serializer for nested views."""
    class Meta:
        model = Department
        fields = ['id', 'name', 'code']


class DepartmentSerializer(serializers.ModelSerializer):
    """Full serializer for Department model."""
    parent_name = serializers.CharField(source='parent.name', read_only=True, allow_null=True)
    head_name = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    children_count = serializers.SerializerMethodField()
    full_path = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = [
            'id', 'organization', 'name', 'code', 'description',
            'parent', 'parent_name',
            'head_id', 'head_email', 'head_name',
            'cost_center_code', 'budget',
            'sort_order', 'is_active',
            'member_count', 'children_count', 'full_path',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'organization', 'created_at', 'updated_at',
            'parent_name', 'head_name', 'member_count', 'children_count', 'full_path'
        ]

    def validate(self, data):
        org = self.context.get('organization') or getattr(self.instance, 'organization', None)
        parent = data.get('parent')
        if parent and (org is None or parent.organization_id != org.id):
            raise serializers.ValidationError({
                'parent': 'Parent department must belong to the same organization'
            })
        return data

    def get_head_name(self, obj):
        if obj.head_email:
            return obj.head_email.split('@')[0]
        return None

    def get_member_count(self, obj):
        return obj.employees.filter(membership__is_active=True).count()

    def get_children_count(self, obj):
        return obj.children.filter(is_active=True).count()

    def get_full_path(self, obj):
        return obj.get_full_path()


class DepartmentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating departments."""
    class Meta:
        model = Department
        fields = [
            'name', 'code', 'description', 'parent',
            'head_id', 'head_email',
            'cost_center_code', 'budget', 'sort_order'
        ]

    def validate_code(self, value):
        if value:
            value = value.upper()
        return value

    def validate(self, data):
        # Validate parent belongs to same organization
        parent = data.get('parent')
        if parent:
            org = self.context.get('organization')
            if parent.organization_id != org.id:
                raise serializers.ValidationError({
                    'parent': 'Parent department must belong to the same organization'
                })

        # PLAT-18: resolve head_email -> head_id at write time so the record
        # is indexed on head_id from day one. Network/timeout/missing-user
        # failures leave head_id=None and keep head_email for display
        # fallback (mirrors the EmployeeProfile path).
        if not data.get('head_id') and data.get('head_email'):
            resolved = _resolve_user_id_by_email(data['head_email'])
            if resolved is not None:
                data['head_id'] = resolved

        return data


class DepartmentTreeSerializer(serializers.ModelSerializer):
    """Nested serializer for department hierarchy tree."""
    children = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    head_name = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = [
            'id', 'name', 'code', 'description',
            'head_id', 'head_email', 'head_name',
            'member_count', 'children'
        ]

    def get_children(self, obj):
        children = obj.children.filter(is_active=True).order_by('sort_order', 'name')
        return DepartmentTreeSerializer(children, many=True).data

    def get_member_count(self, obj):
        return obj.employees.filter(membership__is_active=True).count()

    def get_head_name(self, obj):
        if obj.head_email:
            return obj.head_email.split('@')[0]
        return None


# =============================================================================
# HR Hierarchy Serializers - Team
# =============================================================================

class TeamMinimalSerializer(serializers.ModelSerializer):
    """Minimal team serializer for nested views."""
    class Meta:
        model = Team
        fields = ['id', 'name', 'team_type', 'color']


class TeamSerializer(serializers.ModelSerializer):
    """Full serializer for Team model."""
    department_name = serializers.CharField(source='department.name', read_only=True, allow_null=True)
    lead_name = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = [
            'id', 'organization', 'name', 'description', 'team_type',
            'lead_id', 'lead_email', 'lead_name',
            'department', 'department_name',
            'pulse_project_id',
            'start_date', 'end_date', 'color',
            'is_active', 'member_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'organization', 'created_at', 'updated_at',
            'department_name', 'lead_name', 'member_count'
        ]

    def validate(self, data):
        org = self.context.get('organization') or getattr(self.instance, 'organization', None)
        department = data.get('department')
        if department and (org is None or department.organization_id != org.id):
            raise serializers.ValidationError({
                'department': 'Department must belong to the same organization'
            })
        return data

    def get_lead_name(self, obj):
        if obj.lead_email:
            return obj.lead_email.split('@')[0]
        return None

    def get_member_count(self, obj):
        # PLS-770: summary counts must agree with the authoritative Pulse
        # TeamRoster projection the detail reads use. When the roster snapshot
        # is provided in request context (fetched once per list read) use the
        # projected routing set size; otherwise fall back to the local active
        # directory memberships so counts never silently disagree with detail.
        roster_all = (self.context or {}).get('authoritative_roster_all')
        if roster_all is not None:
            org = getattr(obj, 'organization', None)
            if org is not None:
                from organizations.services.team_roster_authority import _canonical_team
                key = (org.id, (org.slug or '').strip().lower(), _canonical_team(obj.name))
                return len(roster_all.get(key, set()))
        return obj.memberships.filter(is_active=True).count()


class TeamCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating teams."""
    class Meta:
        model = Team
        fields = [
            'name', 'description', 'team_type',
            'lead_id', 'lead_email',
            'department', 'pulse_project_id',
            'start_date', 'end_date', 'color'
        ]

    def validate(self, data):
        org = self.context.get('organization')

        # Validate department belongs to same organization
        department = data.get('department')
        if department and department.organization_id != org.id:
            raise serializers.ValidationError({
                'department': 'Department must belong to the same organization'
            })

        # Note: pulse_project_id references shizuha-pulse projects
        # We could validate against Pulse API here if needed

        # PLAT-18: resolve lead_email -> lead_id at write time so the record
        # is indexed on lead_id from day one. Network/timeout/missing-user
        # failures leave lead_id=None and keep lead_email for display
        # fallback (mirrors the EmployeeProfile path).
        if not data.get('lead_id') and data.get('lead_email'):
            resolved = _resolve_user_id_by_email(data['lead_email'])
            if resolved is not None:
                data['lead_id'] = resolved

        return data


# =============================================================================
# HR Hierarchy Serializers - Position (Stubbed)
# =============================================================================

class PositionSerializer(serializers.ModelSerializer):
    """Serializer for Position model."""
    department_name = serializers.CharField(source='department.name', read_only=True, allow_null=True)
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            'id', 'organization', 'title', 'code', 'description',
            'department', 'department_name',
            'level', 'pay_grade',
            'required_skills', 'qualifications',
            'is_active', 'employee_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'organization', 'created_at', 'updated_at',
            'department_name', 'employee_count'
        ]

    def validate(self, data):
        org = self.context.get('organization') or getattr(self.instance, 'organization', None)
        department = data.get('department')
        if department and (org is None or department.organization_id != org.id):
            raise serializers.ValidationError({
                'department': 'Department must belong to the same organization'
            })
        return data

    def get_employee_count(self, obj):
        return obj.employees.filter(membership__is_active=True).count()


class PositionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating positions."""
    class Meta:
        model = Position
        fields = [
            'title', 'code', 'description',
            'department', 'level', 'pay_grade',
            'required_skills', 'qualifications'
        ]

    def validate_code(self, value):
        if value:
            value = value.upper()
        return value

    def validate(self, data):
        org = self.context.get('organization')
        department = data.get('department')
        if department and (org is None or department.organization_id != org.id):
            raise serializers.ValidationError({
                'department': 'Department must belong to the same organization'
            })
        return data


# =============================================================================
# HR Hierarchy Serializers - Employee Profile
# =============================================================================

class EmployeeProfileMinimalSerializer(serializers.ModelSerializer):
    """Minimal employee profile for listing."""
    user_id = serializers.IntegerField(source='membership.user_id', read_only=True)
    user_email = serializers.EmailField(source='membership.user_email', read_only=True)
    role = serializers.CharField(source='membership.role', read_only=True)
    display_name = serializers.CharField(read_only=True)
    team_memberships_list = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeProfile
        fields = [
            'id', 'user_id', 'user_email', 'role',
            'display_name', 'job_title', 'avatar_url',
            'employment_status', 'employment_type',
            'team_memberships_list',
        ]

    def get_team_memberships_list(self, obj):
        memberships = obj.team_memberships.filter(is_active=True).select_related('team')
        return [
            {
                'team_id': membership.team_id,
                'team_name': membership.team.name,
                'role': membership.role,
            }
            for membership in memberships
        ]


class EmployeeProfileSerializer(serializers.ModelSerializer):
    """Full serializer for EmployeeProfile model."""
    # From membership
    user_id = serializers.IntegerField(source='membership.user_id', read_only=True)
    user_email = serializers.EmailField(source='membership.user_email', read_only=True)
    org_role = serializers.CharField(source='membership.role', read_only=True)
    organization_id = serializers.IntegerField(source='membership.organization_id', read_only=True)
    organization_name = serializers.CharField(source='membership.organization.name', read_only=True)

    # Related names
    department_name = serializers.CharField(source='department.name', read_only=True, allow_null=True)
    position_title = serializers.CharField(source='position.title', read_only=True, allow_null=True)
    manager_name = serializers.SerializerMethodField()
    dotted_line_manager_name = serializers.SerializerMethodField()

    # Computed fields
    display_name = serializers.CharField(read_only=True)
    effective_job_title = serializers.CharField(read_only=True)
    direct_reports_count = serializers.SerializerMethodField()
    team_memberships_list = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeProfile
        fields = [
            'id', 'membership',
            # From membership
            'user_id', 'user_email', 'org_role', 'organization_id', 'organization_name',
            # Position
            'position', 'position_title', 'job_title', 'effective_job_title',
            # Department
            'department', 'department_name',
            # Employment
            'employment_status', 'employment_type',
            'start_date', 'end_date', 'probation_end_date',
            # Reporting
            'manager_id', 'manager_email', 'manager_name',
            'dotted_line_manager_id', 'dotted_line_manager_email', 'dotted_line_manager_name',
            # Contact
            'work_phone', 'work_email', 'extension',
            # Location
            'office_location', 'desk_number', 'timezone',
            # ID
            'employee_id',
            # Profile
            'bio', 'avatar_url', 'display_name',
            # Computed
            'direct_reports_count', 'team_memberships_list',
            # Timestamps
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'created_at', 'updated_at',
            'user_id', 'user_email', 'org_role', 'organization_id', 'organization_name',
            'department_name', 'position_title',
            'manager_name', 'dotted_line_manager_name',
            'display_name', 'effective_job_title',
            'direct_reports_count', 'team_memberships_list'
        ]

    def get_manager_name(self, obj):
        if obj.manager_id:
            # Try to get display name from the manager's membership
            try:
                manager_membership = OrganizationMembership.objects.filter(
                    user_id=obj.manager_id,
                    organization=obj.membership.organization,
                    is_active=True,
                ).first()
                if manager_membership and manager_membership.display_name:
                    return manager_membership.display_name
            except Exception:
                pass
        if obj.manager_email:
            return obj.manager_email.split('@')[0]
        return None

    def get_dotted_line_manager_name(self, obj):
        if obj.dotted_line_manager_email:
            return obj.dotted_line_manager_email.split('@')[0]
        return None

    def get_direct_reports_count(self, obj):
        return obj.get_direct_reports().count()

    def get_team_memberships_list(self, obj):
        memberships = obj.team_memberships.filter(is_active=True).select_related('team')
        return [
            {
                'team_id': m.team_id,
                'team_name': m.team.name,
                'role': m.role
            }
            for m in memberships
        ]


class EmployeeProfileCreateSerializer(serializers.Serializer):
    """Serializer for creating employee profiles from org membership."""
    membership_id = serializers.IntegerField(required=True)

    # Department and manager are optional for founders/top-level
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(),
        required=False,
        allow_null=True
    )
    manager_id = serializers.IntegerField(required=False, allow_null=True)
    manager_email = serializers.EmailField(required=False, allow_blank=True)

    # Optional fields
    position = serializers.PrimaryKeyRelatedField(queryset=Position.objects.all(), required=False, allow_null=True)
    job_title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    employment_status = serializers.ChoiceField(choices=EmploymentStatus.CHOICES, default=EmploymentStatus.ACTIVE)
    employment_type = serializers.ChoiceField(choices=EmploymentType.CHOICES, default=EmploymentType.FULL_TIME)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    probation_end_date = serializers.DateField(required=False, allow_null=True)
    dotted_line_manager_id = serializers.IntegerField(required=False, allow_null=True)
    dotted_line_manager_email = serializers.EmailField(required=False, allow_blank=True)
    work_phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    work_email = serializers.EmailField(required=False, allow_blank=True)
    extension = serializers.CharField(max_length=20, required=False, allow_blank=True)
    office_location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    desk_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=50, required=False, default='UTC')
    employee_id = serializers.CharField(max_length=50, required=False, allow_blank=True)
    bio = serializers.CharField(required=False, allow_blank=True)
    avatar_url = serializers.URLField(required=False, allow_blank=True)

    def validate(self, data):
        org = self.context.get('organization')

        # Validate membership belongs to organization
        try:
            membership = OrganizationMembership.objects.get(
                id=data['membership_id'],
                organization=org,
                is_active=True
            )
            data['membership'] = membership
        except OrganizationMembership.DoesNotExist:
            raise serializers.ValidationError({
                'membership_id': 'Membership not found in this organization'
            })

        # Check if profile already exists
        if hasattr(membership, 'employee_profile'):
            raise serializers.ValidationError({
                'membership_id': 'Employee profile already exists for this membership'
            })

        # Validate department belongs to organization
        department = data.get('department')
        if department and department.organization_id != org.id:
            raise serializers.ValidationError({
                'department': 'Department must belong to the same organization'
            })

        # Validate position belongs to organization
        position = data.get('position')
        if position and position.organization_id != org.id:
            raise serializers.ValidationError({
                'position': 'Position must belong to the same organization'
            })

        # PLAT-18: resolve *_email -> *_id at write time so downstream queries
        # keyed on manager_id don't silently miss rows written by email only.
        # If the caller already supplied the *_id explicitly, we trust it.
        if not data.get('manager_id') and data.get('manager_email'):
            resolved = _resolve_user_id_by_email(data['manager_email'])
            if resolved is not None:
                data['manager_id'] = resolved
        if not data.get('dotted_line_manager_id') and data.get('dotted_line_manager_email'):
            resolved = _resolve_user_id_by_email(data['dotted_line_manager_email'])
            if resolved is not None:
                data['dotted_line_manager_id'] = resolved

        return data

    def create(self, validated_data):
        membership = validated_data.pop('membership')
        validated_data.pop('membership_id')
        return EmployeeProfile.objects.create(membership=membership, **validated_data)


class EmployeeProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating employee profiles."""
    class Meta:
        model = EmployeeProfile
        fields = [
            'position', 'job_title', 'department',
            'employment_status', 'employment_type',
            'start_date', 'end_date', 'probation_end_date',
            'manager_id', 'manager_email',
            'dotted_line_manager_id', 'dotted_line_manager_email',
            'work_phone', 'work_email', 'extension',
            'office_location', 'desk_number', 'timezone',
            'employee_id', 'bio', 'avatar_url'
        ]

    def validate(self, data):
        org = self.instance.membership.organization

        # Validate department belongs to organization
        department = data.get('department')
        if department and department.organization_id != org.id:
            raise serializers.ValidationError({
                'department': 'Department must belong to the same organization'
            })

        # Validate position belongs to organization
        position = data.get('position')
        if position and position.organization_id != org.id:
            raise serializers.ValidationError({
                'position': 'Position must belong to the same organization'
            })

        # PLAT-18: resolve *_email -> *_id on update. Same rules as the create
        # serializer — explicit *_id wins, otherwise try to resolve, and a
        # failed resolve falls through to leave *_id unchanged.
        if 'manager_email' in data and not data.get('manager_id') and data.get('manager_email'):
            resolved = _resolve_user_id_by_email(data['manager_email'])
            if resolved is not None:
                data['manager_id'] = resolved
        if ('dotted_line_manager_email' in data
                and not data.get('dotted_line_manager_id')
                and data.get('dotted_line_manager_email')):
            resolved = _resolve_user_id_by_email(data['dotted_line_manager_email'])
            if resolved is not None:
                data['dotted_line_manager_id'] = resolved

        return data


# =============================================================================
# HR Hierarchy Serializers - Team Membership
# =============================================================================

class TeamMembershipSerializer(serializers.ModelSerializer):
    """Serializer for TeamMembership model."""
    team_name = serializers.CharField(source='team.name', read_only=True)
    employee_name = serializers.CharField(source='employee_profile.display_name', read_only=True)
    employee_email = serializers.EmailField(source='employee_profile.membership.user_email', read_only=True)
    employee_title = serializers.CharField(source='employee_profile.effective_job_title', read_only=True)

    class Meta:
        model = TeamMembership
        fields = [
            'id', 'team', 'team_name',
            'employee_profile', 'employee_name', 'employee_email', 'employee_title',
            'role', 'joined_at', 'left_at', 'is_active'
        ]
        read_only_fields = ['id', 'joined_at', 'team_name', 'employee_name', 'employee_email', 'employee_title']


class TeamMemberAddSerializer(serializers.Serializer):
    """Serializer for adding members to a team."""
    employee_profile_id = serializers.IntegerField()
    role = serializers.ChoiceField(choices=TeamRole.CHOICES, default=TeamRole.MEMBER)

    def validate(self, data):
        team = self.context.get('team')
        org = team.organization

        # Validate employee profile belongs to organization
        try:
            profile = EmployeeProfile.objects.get(
                id=data['employee_profile_id'],
                membership__organization=org,
                membership__is_active=True
            )
            data['employee_profile'] = profile
        except EmployeeProfile.DoesNotExist:
            raise serializers.ValidationError({
                'employee_profile_id': 'Employee not found in this organization'
            })

        # Check for existing membership
        if TeamMembership.objects.filter(team=team, employee_profile=profile, is_active=True).exists():
            raise serializers.ValidationError({
                'employee_profile_id': 'Employee is already a member of this team'
            })

        return data

    def create(self, validated_data):
        team = self.context.get('team')
        profile = validated_data.pop('employee_profile')
        validated_data.pop('employee_profile_id')
        return TeamMembership.objects.create(
            team=team,
            employee_profile=profile,
            **validated_data
        )


# =============================================================================
# Org Chart Serializers
# =============================================================================

class OrgChartNodeSerializer(serializers.Serializer):
    """Serializer for org chart nodes (employees in hierarchy)."""
    id = serializers.IntegerField(source='membership.user_id')
    name = serializers.SerializerMethodField()
    email = serializers.EmailField(source='membership.user_email')
    title = serializers.CharField(source='effective_job_title')
    department = serializers.CharField(source='department.name', allow_null=True)
    avatar_url = serializers.URLField(allow_blank=True)
    direct_reports = serializers.SerializerMethodField()

    def get_name(self, obj):
        """Resolve full name from shizuha-id, falling back to display_name."""
        import os
        import requests as http_requests
        from django.core.cache import cache

        user_id = obj.membership.user_id
        if user_id:
            cache_key = f"admin_user_fullname:{user_id}"
            cached = cache.get(cache_key)
            if cached:
                return cached
            try:
                id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
                resp = http_requests.get(f'{id_url}/internal/users/{user_id}/', timeout=3)
                if resp.status_code == 200:
                    u = resp.json()
                    first = u.get('first_name', '').strip()
                    last = u.get('last_name', '').strip()
                    full = f"{first} {last}".strip()
                    if full:
                        cache.set(cache_key, full, 300)
                        return full
            except Exception:
                pass
        return obj.display_name

    def get_direct_reports(self, obj):
        reports = obj.get_direct_reports().filter(membership__user_id__isnull=False)
        return OrgChartNodeSerializer(reports, many=True).data


class OrgChartSerializer(serializers.Serializer):
    """Serializer for full org chart data."""
    organization = OrganizationSerializer()
    root_employees = serializers.SerializerMethodField()
    departments = DepartmentTreeSerializer(many=True)
    total_employees = serializers.IntegerField()

    def get_root_employees(self, obj):
        """Get employees with no manager (top of hierarchy)."""
        org = obj['organization']
        root_profiles = EmployeeProfile.objects.filter(
            membership__organization=org,
            membership__is_active=True,
            membership__user_id__isnull=False,
            manager_id__isnull=True
        ).select_related('membership', 'department')
        return OrgChartNodeSerializer(root_profiles, many=True).data


# =============================================================================
# Service Access Serializers
# =============================================================================

class OrganizationServiceAccessSerializer(serializers.ModelSerializer):
    """Serializer for OrganizationServiceAccess."""

    class Meta:
        model = OrganizationServiceAccess
        fields = ['id', 'service_slug', 'is_enabled', 'granted_by_id', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class OrganizationServiceToggleSerializer(serializers.Serializer):
    """For superuser grant/revoke services for an org."""
    service_slugs = serializers.ListField(child=serializers.SlugField())
    action = serializers.ChoiceField(choices=['grant', 'revoke'])


class MemberServiceAccessSerializer(serializers.Serializer):
    """For org admin member-level service management."""
    service_slugs = serializers.ListField(child=serializers.SlugField())
    action = serializers.ChoiceField(choices=['grant', 'revoke'])
