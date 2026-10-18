"""
Organization and Project models for Shizuha Admin.
Jira-style multi-tenant structure with HR hierarchy support.
"""
from datetime import timedelta
import hashlib
import json

from django.db import models
from django.db.models import Q
from django.utils import timezone


# ==============================================================================
# HR Hierarchy Constants
# ==============================================================================

class EmploymentStatus:
    ACTIVE = 'active'
    ON_LEAVE = 'on_leave'
    PROBATION = 'probation'
    SUSPENDED = 'suspended'
    TERMINATED = 'terminated'
    RESIGNED = 'resigned'

    CHOICES = [
        (ACTIVE, 'Active'),
        (ON_LEAVE, 'On Leave'),
        (PROBATION, 'Probation'),
        (SUSPENDED, 'Suspended'),
        (TERMINATED, 'Terminated'),
        (RESIGNED, 'Resigned'),
    ]


class EmploymentType:
    FULL_TIME = 'full_time'
    PART_TIME = 'part_time'
    CONTRACTOR = 'contractor'
    INTERN = 'intern'
    CONSULTANT = 'consultant'
    TEMPORARY = 'temporary'

    CHOICES = [
        (FULL_TIME, 'Full-time'),
        (PART_TIME, 'Part-time'),
        (CONTRACTOR, 'Contractor'),
        (INTERN, 'Intern'),
        (CONSULTANT, 'Consultant'),
        (TEMPORARY, 'Temporary'),
    ]


class TeamType:
    PERMANENT = 'permanent'
    PROJECT = 'project'
    TASK_FORCE = 'task_force'
    COMMITTEE = 'committee'

    CHOICES = [
        (PERMANENT, 'Permanent'),
        (PROJECT, 'Project-based'),
        (TASK_FORCE, 'Task Force'),
        (COMMITTEE, 'Committee'),
    ]


class TeamRole:
    LEAD = 'lead'
    MEMBER = 'member'
    ADVISOR = 'advisor'

    CHOICES = [
        (LEAD, 'Team Lead'),
        (MEMBER, 'Member'),
        (ADVISOR, 'Advisor'),
    ]


class Organization(models.Model):
    """
    Top-level tenant container. All projects belong to an organization.
    Similar to Jira's organization/workspace concept.
    """
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('team', 'Team'),
        ('business', 'Business'),
        ('enterprise', 'Enterprise'),
    ]

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True, db_index=True)
    description = models.TextField(blank=True)

    # Branding
    logo_url = models.URLField(null=True, blank=True)
    website = models.URLField(null=True, blank=True)

    # Settings
    settings = models.JSONField(default=dict, blank=True, help_text="Organization-wide settings")

    # Billing (future use)
    plan = models.CharField(max_length=50, choices=PLAN_CHOICES, default='free')
    billing_email = models.EmailField(null=True, blank=True)

    # Ownership (user_id from shizuha-id)
    owner_id = models.IntegerField(help_text="Primary owner user ID")

    # Status
    is_active = models.BooleanField(default=True)
    is_personal = models.BooleanField(default=False, help_text="Auto-created personal workspace")

    # ── Company OS (PLAT-434 / EPIC PLAT-433: vision exposure) ──
    # Structured org strategy/identity, exposed read-only to all agents via the
    # `company_os` MCP tool. Long-form detail lives in the wiki (handbook_url).
    mission = models.TextField(blank=True, default="", help_text="Company-OS: mission statement")
    vision = models.TextField(blank=True, default="", help_text="Company-OS: vision statement")
    strategic_bets = models.JSONField(default=list, blank=True, help_text="Company-OS: list of strategic bets")
    values_summary = models.TextField(blank=True, default="", help_text="Company-OS: short values summary")
    handbook_url = models.URLField(null=True, blank=True, help_text="Company-OS: link to the long-form wiki handbook")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def setup_founder_employee_profile(self, owner_email=None):
        """
        Create the founder's employee profile for the org chart.
        Called after organization creation to set up the owner as top of hierarchy.
        """
        # Get the owner's membership
        try:
            owner_membership = self.memberships.get(
                user_id=self.owner_id,
                role='owner',
                is_active=True
            )
        except OrganizationMembership.DoesNotExist:
            return None

        # Check if employee profile already exists
        if hasattr(owner_membership, 'employee_profile'):
            return owner_membership.employee_profile

        # Create default Executive department if none exists
        exec_dept, _ = Department.objects.get_or_create(
            organization=self,
            code='EXEC',
            defaults={
                'name': 'Executive',
                'description': 'Executive leadership team',
                'head_id': self.owner_id,
                'head_email': owner_email or owner_membership.user_email,
            }
        )

        # Create default Founder position if none exists
        founder_position, _ = Position.objects.get_or_create(
            organization=self,
            code='FOUNDER',
            defaults={
                'title': 'Founder',
                'description': 'Organization founder and owner',
                'department': exec_dept,
                'level': 10,  # Highest level
            }
        )

        # Create the employee profile for the founder
        employee_profile = EmployeeProfile.objects.create(
            membership=owner_membership,
            position=founder_position,
            job_title='Founder',
            department=exec_dept,
            employment_status='active',
            employment_type='full_time',
            manager_id=None,  # No manager - top of hierarchy
            manager_email=None,
            start_date=timezone.now().date(),
        )

        return employee_profile

    class Meta:
        db_table = 'organizations_organization'
        ordering = ['name']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['owner_id']),
        ]


class OrganizationMembership(models.Model):
    """
    Membership linking users to organizations with roles.

    Note: For pending invitations, user_id is NULL until the user accepts.
    The unique constraint only applies to non-null user_id values.
    """
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('admin', 'Admin'),
        ('member', 'Member'),
        ('viewer', 'Viewer'),
        ('auditor', 'Auditor'),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    # user_id is NULL for pending invitations, set when user accepts
    user_id = models.IntegerField(
        db_index=True,
        null=True,
        blank=True,
        help_text="User ID from auth service. NULL for pending invitations."
    )
    user_email = models.EmailField(null=True, blank=True)
    display_name = models.CharField(
        max_length=150, null=True, blank=True,
        help_text="Cached display name from auth service (username)."
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')

    # Invitation tracking
    invited_by_id = models.IntegerField(null=True, blank=True)
    invited_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    is_pending = models.BooleanField(default=False)

    # Status
    is_active = models.BooleanField(default=True)
    # HIVE-671: Hive personal-agent connectivity operation_id for provenance-scoped revoke
    source_operation_id = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user_email} in {self.organization.name} ({self.role})"

    def accept_invitation(self, user_id, display_name=None):
        """Accept a pending invitation and link to user."""
        if not self.is_pending:
            raise ValueError("Membership is not a pending invitation")
        self.user_id = user_id
        self.is_pending = False
        self.accepted_at = timezone.now()
        if display_name:
            self.display_name = display_name
        self.save()

    class Meta:
        db_table = 'organizations_membership'
        indexes = [
            models.Index(fields=['user_id', 'is_active']),
            models.Index(fields=['organization', 'role']),
            models.Index(fields=['user_email']),
        ]
        constraints = [
            # Unique user per org (only for non-null user_id)
            models.UniqueConstraint(
                fields=['organization', 'user_id'],
                name='unique_org_user',
                condition=models.Q(user_id__isnull=False)
            ),
            # Unique email per org for pending invitations
            models.UniqueConstraint(
                fields=['organization', 'user_email'],
                name='unique_org_pending_email',
                condition=models.Q(is_pending=True)
            ),
        ]


class JITElevatedAccessGrant(models.Model):
    """
    Time-bound privileged access for scoped organization actions.

    This is the Shizuha Admin half of PLAT-1346's JIT/PAM mechanism:
    agents request a scoped role elevation for a task, low-risk requests can
    be policy-approved immediately, higher-risk requests remain pending for
    the owning team, and approved grants expire automatically by query.
    """
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_DENIED = 'denied'
    STATUS_REVOKED = 'revoked'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_DENIED, 'Denied'),
        (STATUS_REVOKED, 'Revoked'),
    ]

    APPROVAL_POLICY = 'policy'
    APPROVAL_TEAM = 'owning_team'

    APPROVAL_CHOICES = [
        (APPROVAL_POLICY, 'Policy auto-approved'),
        (APPROVAL_TEAM, 'Owning-team approval'),
    ]

    RISK_LOW = 'low'
    RISK_MEDIUM = 'medium'
    RISK_HIGH = 'high'

    ROLE_PRIORITY = {'viewer': 1, 'member': 2, 'admin': 3, 'owner': 4}
    LOW_RISK_AUTO_SCOPES = {
        'org.members.add',
        'organization.members.add',
    }
    VERIFIED_AUTO_POLICY_SLUGS = {
        'passed-it-audit-org-member-add',
    }
    # PLAT-8895: target-constrained team member-add carries its own predicate
    # allowlist, separate from the org-level low-risk slugs. Auto-approval on
    # this scope additionally requires the admission adapter's validated exact
    # target constraints (team/user/role — proven by the constraint digest) and
    # the scope policy's own TTL ceiling (1h, tighter than the org-level 2h
    # low-risk cap). Absence of the predicate preserves the pending
    # owning-team behavior byte-for-byte.
    ROUTINE_TARGET_CONSTRAINED_POLICY_SLUGS = {
        'routine-target-constrained-team-member-add',
    }
    MAX_TTL_SECONDS = 4 * 60 * 60
    LOW_RISK_MAX_TTL_SECONDS = 2 * 60 * 60

    # ADR-0048: target-constrained capabilities are registered by Admin, not
    # selected by the requester.  The policy digest is snapshotted on each
    # grant for audit, then re-validated against this live registry at decision
    # and consumption time.  Removing/disabling/changing a policy therefore
    # fails closed without turning the snapshot into executable authority.
    TEAM_MEMBER_ADD_SCOPE = 'org.teams.members.add'
    KUBERNETES_RBAC_APPLY_SCOPE = 'kubernetes.rbac.apply'
    KUBERNETES_SELECTED_FRAGMENT = 'infra-recovery-owner-read'

    @classmethod
    def normalize_kubernetes_selected_fragment(cls, value):
        """Keep the historical all contract unchanged; allow one fixed subset."""
        if not isinstance(value, str):
            raise ValueError('selected_fragment must be all or infra-recovery-owner-read')
        if value in ('', 'all'):
            return ''
        if value == cls.KUBERNETES_SELECTED_FRAGMENT:
            return value
        raise ValueError('selected_fragment must be all or infra-recovery-owner-read')
    EXACT_SCOPE_POLICIES = {
        TEAM_MEMBER_ADD_SCOPE: {
            'key': 'admin.team-roster.member-add',
            'version': 1,
            'enabled': True,
            'approver_team_name': 'Platform',
            'max_ttl_seconds': 3600,
            'max_uses': 1,
            'target_fields': ['organization_id', 'team_id', 'user_id', 'role'],
        },
        KUBERNETES_RBAC_APPLY_SCOPE: {
            'key': 'origin.deploy.ci-rbac-canonical-apply',
            'version': 1,
            'enabled': True,
            'approver_team_name': 'Platform',
            'max_ttl_seconds': 900,
            'max_uses': 1,
            'target_fields': [
                'repository', 'ref', 'commit_sha', 'workflow', 'script',
                'namespace_envelope', 'resource_envelope',
            ],
            'fixed_constraints': {
                'repository': 'shizuha-labs/deploy',
                'ref': 'refs/heads/master',
                'workflow': 'apply-origin-ci-deployer-rbac.yml',
                'script': 'k3s/origin/apply-ci-deployer-rbac.sh',
                'namespace_envelope': ['origin', 'shizuha', 'shizuha-fleet', 'registry'],
                'resource_envelope': ['rbac.authorization.k8s.io'],
            },
        },
    }

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='jit_elevation_grants',
    )
    requester_user_id = models.IntegerField(db_index=True)
    requester_email = models.EmailField(blank=True, default='')
    scope = models.CharField(max_length=100, db_index=True)
    requested_role = models.CharField(max_length=20, choices=OrganizationMembership.ROLE_CHOICES)
    reason = models.TextField()
    task_key = models.CharField(max_length=32, db_index=True)
    ttl_seconds = models.PositiveIntegerField(default=3600)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    approval_path = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default=APPROVAL_TEAM)
    owning_team = models.CharField(max_length=64, default='admin-platform', db_index=True)
    approver_team = models.ForeignKey(
        'Team',
        on_delete=models.PROTECT,
        related_name='jit_grants_to_approve',
        null=True,
        blank=True,
    )
    target_team = models.ForeignKey(
        'Team',
        on_delete=models.PROTECT,
        related_name='jit_grants_targeting_team',
        null=True,
        blank=True,
    )
    target_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    target_role = models.CharField(max_length=20, choices=TeamRole.CHOICES, blank=True, default='')
    policy_key = models.CharField(max_length=100, blank=True, default='', db_index=True)
    policy_version = models.PositiveIntegerField(null=True, blank=True)
    policy_digest = models.CharField(max_length=64, blank=True, default='')
    target_constraints = models.JSONField(default=dict, blank=True)
    constraint_digest = models.CharField(max_length=64, blank=True, default='')
    max_uses = models.PositiveIntegerField(default=1)
    uses_consumed = models.PositiveIntegerField(default=0)
    risk_level = models.CharField(
        max_length=20,
        choices=[(RISK_LOW, 'Low'), (RISK_MEDIUM, 'Medium'), (RISK_HIGH, 'High')],
        default=RISK_MEDIUM,
    )
    policy_slug = models.CharField(max_length=100, blank=True, default='')

    decided_by_user_id = models.IntegerField(null=True, blank=True)
    decided_by_email = models.EmailField(blank=True, default='')
    decision_note = models.TextField(blank=True, default='')
    decided_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organizations_jit_elevated_access_grant'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['requester_user_id', 'status', 'expires_at']),
            models.Index(fields=['organization', 'scope', 'status']),
            models.Index(fields=['task_key']),
        ]

    def __str__(self):
        return (
            f"JIT {self.requester_email or self.requester_user_id} "
            f"{self.requested_role}@{self.organization.slug} {self.status}"
        )

    @classmethod
    def role_priority(cls, role):
        return cls.ROLE_PRIORITY.get(role or '', 0)

    @classmethod
    def exact_policy_for_scope(cls, scope):
        policy = cls.EXACT_SCOPE_POLICIES.get(scope)
        return dict(policy) if policy else None

    @staticmethod
    def _canonical_digest(value):
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def exact_policy_digest(cls, policy):
        authoritative = {
            key: policy[key]
            for key in (
                'key', 'version', 'enabled', 'approver_team_name',
                'max_ttl_seconds', 'max_uses', 'target_fields',
            )
        }
        if 'fixed_constraints' in policy:
            authoritative['fixed_constraints'] = policy['fixed_constraints']
        return cls._canonical_digest(authoritative)

    @classmethod
    def constraint_digest_for(cls, constraints):
        return cls._canonical_digest(constraints)

    def has_complete_current_exact_authority(self):
        """Return whether every ADR-0048 authority field is present and live."""
        policy = self.exact_policy_for_scope(self.scope)
        if not policy or not policy.get('enabled'):
            return False
        if not self.approver_team_id:
            return False
        if self.approver_team.organization_id != self.organization_id:
            return False
        if not self.approver_team.is_active:
            return False
        if self.scope == self.TEAM_MEMBER_ADD_SCOPE:
            if not self.target_team_id or self.target_user_id is None:
                return False
            if self.target_team.organization_id != self.organization_id:
                return False
            if not self.target_team.is_active or not self.target_role:
                return False
        if (
            self.policy_key != policy['key']
            or self.policy_version != policy['version']
            or self.policy_digest != self.exact_policy_digest(policy)
            or self.max_uses != policy['max_uses']
        ):
            return False
        if not self.target_constraints:
            return False
        if self.constraint_digest != self.constraint_digest_for(self.target_constraints):
            return False
        expected_fields = set(policy['target_fields'])
        if self.scope == self.KUBERNETES_RBAC_APPLY_SCOPE and 'selected_fragment' in self.target_constraints:
            if self.target_constraints['selected_fragment'] != self.KUBERNETES_SELECTED_FRAGMENT:
                return False
            expected_fields.add('selected_fragment')
        if set(self.target_constraints) != expected_fields:
            return False
        fixed = policy.get('fixed_constraints') or {}
        return all(self.target_constraints.get(key) == value for key, value in fixed.items())

    @classmethod
    def active_queryset(cls, *, user_id=None, email=None, organization=None, scope=None):
        q = cls.objects.filter(
            status=cls.STATUS_APPROVED,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
            organization__is_active=True,
        )
        if organization is not None:
            q = q.filter(organization=organization)
        if scope:
            q = q.filter(scope=scope)
        if user_id is not None and email:
            q = q.filter(Q(requester_user_id=user_id) | Q(requester_email=email))
        elif user_id is not None:
            q = q.filter(requester_user_id=user_id)
        elif email:
            q = q.filter(requester_email=email)
        else:
            q = q.none()
        return q

    @classmethod
    def can_auto_approve(cls, *, scope, requested_role, ttl_seconds, policy_slug='',
                         policy_verified=False, has_exact_constraints=False):
        """PLAT-8895: the target-constrained team member-add scope gains a
        trusted internal policy predicate leg. Fail-closed conjunction: the
        admission adapter's validated exact target constraints (proven by the
        constraint digest), the minimal org elevation (admin), the scope
        policy's TTL ceiling, Admin-verified staff actor, and an allowlisted
        predicate slug. Every absent leg fails closed to today's pending
        owning-team behavior; the org-level low-risk path is byte-identical."""
        if scope == cls.TEAM_MEMBER_ADD_SCOPE:
            policy = cls.exact_policy_for_scope(scope)
            return (
                bool(policy and policy.get('enabled'))
                and has_exact_constraints
                and requested_role == 'admin'
                and int(ttl_seconds) <= policy['max_ttl_seconds']
                and policy_verified
                and policy_slug in cls.ROUTINE_TARGET_CONSTRAINED_POLICY_SLUGS
            )
        return (
            scope in cls.LOW_RISK_AUTO_SCOPES
            and requested_role == 'admin'
            and int(ttl_seconds) <= cls.LOW_RISK_MAX_TTL_SECONDS
            and policy_verified
            and policy_slug in cls.VERIFIED_AUTO_POLICY_SLUGS
        )

    @classmethod
    def risk_for(cls, *, scope, requested_role):
        if requested_role == 'owner':
            return cls.RISK_HIGH
        if scope in cls.LOW_RISK_AUTO_SCOPES and requested_role == 'admin':
            return cls.RISK_LOW
        return cls.RISK_MEDIUM

    def is_active_now(self):
        return (
            self.status == self.STATUS_APPROVED
            and self.revoked_at is None
            and self.expires_at is not None
            and self.expires_at > timezone.now()
        )

    def approve(self, *, actor_user_id=None, actor_email='', note='', approval_path=None):
        now = timezone.now()
        self.status = self.STATUS_APPROVED
        self.approval_path = approval_path or self.approval_path
        self.decided_by_user_id = actor_user_id
        self.decided_by_email = actor_email or ''
        self.decision_note = note or ''
        self.decided_at = now
        self.expires_at = now + timedelta(seconds=int(self.ttl_seconds))
        self.save(update_fields=[
            'status', 'approval_path', 'decided_by_user_id', 'decided_by_email',
            'decision_note', 'decided_at', 'expires_at', 'updated_at'
        ])

    def deny(self, *, actor_user_id=None, actor_email='', note=''):
        self.status = self.STATUS_DENIED
        self.decided_by_user_id = actor_user_id
        self.decided_by_email = actor_email or ''
        self.decision_note = note or ''
        self.decided_at = timezone.now()
        self.save(update_fields=[
            'status', 'decided_by_user_id', 'decided_by_email',
            'decision_note', 'decided_at', 'updated_at'
        ])

    def revoke(self, *, actor_user_id=None, actor_email='', note=''):
        self.status = self.STATUS_REVOKED
        self.decided_by_user_id = actor_user_id
        self.decided_by_email = actor_email or ''
        self.decision_note = note or ''
        self.revoked_at = timezone.now()
        self.save(update_fields=[
            'status', 'decided_by_user_id', 'decided_by_email',
            'decision_note', 'revoked_at', 'updated_at'
        ])


class JITElevatedAccessGrantEvent(models.Model):
    """Append-only audit evidence for ADR-0048 grant lifecycle and use."""

    grant = models.ForeignKey(
        JITElevatedAccessGrant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
    )
    event_type = models.CharField(max_length=40, db_index=True)
    actor_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    actor_email = models.EmailField(blank=True, default='')
    source = models.CharField(max_length=40, default='api')
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'organizations_jit_elevated_access_grant_event'
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(
                fields=['grant', 'event_type', 'created_at'],
                name='jit_event_grant_type_idx',
            ),
        ]


class JITElevatedAccessGrantUse(models.Model):
    """A committed, idempotently replayable use of a one-action JIT grant."""

    grant = models.ForeignKey(
        JITElevatedAccessGrant,
        on_delete=models.CASCADE,
        related_name='uses',
    )
    idempotency_key = models.CharField(max_length=100)
    request_digest = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    actor_user_id = models.IntegerField()
    actor_email = models.EmailField(blank=True, default='')
    dispatch_status = models.CharField(max_length=20, default='pending', db_index=True)
    dispatch_attempts = models.PositiveIntegerField(default=0)
    origin_run_id = models.BigIntegerField(null=True, blank=True, unique=True)
    origin_run_number = models.BigIntegerField(null=True, blank=True)
    last_dispatch_error = models.TextField(blank=True, default='')
    dispatched_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'organizations_jit_elevated_access_grant_use'
        constraints = [
            models.UniqueConstraint(
                fields=['grant', 'idempotency_key'],
                name='unique_jit_grant_idempotency_key',
            ),
        ]
        indexes = [
            models.Index(fields=['grant', 'created_at'], name='jit_use_grant_created_idx'),
        ]


# ==============================================================================
# HR Hierarchy Models
# ==============================================================================
# Note: Project and ProjectMembership models have been removed.
# Projects are now solely managed by shizuha-pulse.
# Use the Pulse API at /pulse/api/projects/ for project management.

class Department(models.Model):
    """
    Hierarchical department structure within an organization.
    Supports parent-child relationships for nested departments (e.g., Engineering > Backend > API Team).
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='departments'
    )

    name = models.CharField(max_length=255)
    code = models.CharField(
        max_length=50,
        blank=True,
        help_text="Department code (e.g., ENG, HR, FIN)"
    )
    description = models.TextField(blank=True)

    # Hierarchy - self-referential for nested departments
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children'
    )

    # Leadership (user_id from shizuha-id)
    head_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="Department head user ID"
    )
    head_email = models.EmailField(null=True, blank=True)

    # Budget/Cost Center (for future financial tracking)
    cost_center_code = models.CharField(max_length=50, blank=True)
    budget = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Annual department budget"
    )

    # Display order within parent
    sort_order = models.PositiveIntegerField(default=0)

    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    def get_ancestors(self):
        """Get all ancestor departments (parent chain up to root)."""
        ancestors = []
        current = self.parent
        while current:
            ancestors.append(current)
            current = current.parent
        return ancestors

    def get_descendants(self):
        """Get all descendant departments (children, grandchildren, etc.)."""
        descendants = list(self.children.filter(is_active=True))
        for child in list(descendants):
            descendants.extend(child.get_descendants())
        return descendants

    def get_full_path(self):
        """Get full department path (e.g., 'Engineering > Backend > API')."""
        ancestors = self.get_ancestors()
        path = [a.name for a in reversed(ancestors)] + [self.name]
        return ' > '.join(path)

    class Meta:
        db_table = 'organizations_department'
        ordering = ['organization', 'sort_order', 'name']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['parent']),
            models.Index(fields=['head_id']),
            models.Index(fields=['code']),
        ]
        constraints = [
            # Unique code per organization (if code is provided)
            models.UniqueConstraint(
                fields=['organization', 'code'],
                name='unique_dept_code',
                condition=~models.Q(code='')
            ),
        ]


class Team(models.Model):
    """
    Cross-functional teams that can span departments.
    Can be permanent (e.g., Platform Team) or project-based (e.g., Q1 Launch Team).
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='teams'
    )

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    team_type = models.CharField(
        max_length=20,
        choices=TeamType.CHOICES,
        default=TeamType.PERMANENT
    )

    # Leadership
    lead_id = models.IntegerField(null=True, blank=True, help_text="Team lead user ID")
    lead_email = models.EmailField(null=True, blank=True)

    # Optional department association (team can be under a department)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='teams'
    )

    # Note: project FK removed - projects are now managed by shizuha-pulse
    # For project-based teams, use pulse_project_id to reference Pulse projects
    pulse_project_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="Project ID in shizuha-pulse (for project-based teams)"
    )

    # Time bounds (especially for project teams or task forces)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # Appearance
    color = models.CharField(max_length=7, default='#6366f1')  # Hex color

    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    @property
    def member_count(self):
        return self.memberships.filter(is_active=True).count()

    class Meta:
        db_table = 'organizations_team'
        ordering = ['organization', 'name']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['department']),
            models.Index(fields=['lead_id']),
            models.Index(fields=['team_type']),
        ]


class Position(models.Model):
    """
    Job title/position catalog for the organization.
    Stubbed for future HR features - currently provides basic job title management.
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='positions'
    )

    title = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True, help_text="Position code (e.g., SWE-L5)")
    description = models.TextField(blank=True)

    # Classification
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='positions',
        help_text="Primary department for this position"
    )
    level = models.PositiveIntegerField(
        default=1,
        help_text="Job level/grade (1=entry, higher=senior)"
    )
    pay_grade = models.CharField(max_length=50, blank=True, help_text="Pay grade/band")

    # Requirements (JSON for flexibility) - Stubbed for future
    required_skills = models.JSONField(default=list, blank=True)
    qualifications = models.JSONField(default=list, blank=True)

    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} (Level {self.level})"

    class Meta:
        db_table = 'organizations_position'
        ordering = ['organization', 'level', 'title']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['department']),
            models.Index(fields=['level']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'code'],
                name='unique_position_code',
                condition=~models.Q(code='')
            ),
        ]


class EmployeeProfile(models.Model):
    """
    Extended employee information for organization members.
    One-to-one with OrganizationMembership to keep membership lightweight
    while supporting rich HR data when needed.
    """
    membership = models.OneToOneField(
        OrganizationMembership,
        on_delete=models.CASCADE,
        related_name='employee_profile'
    )

    # Position (optional FK to position catalog, or can specify job_title directly)
    position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees'
    )
    job_title = models.CharField(
        max_length=255,
        blank=True,
        help_text="Job title (can override position title)"
    )

    # Department assignment (optional for founders/top-level)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees',
        help_text="Primary department (optional for founders)"
    )

    # Employment details
    employment_status = models.CharField(
        max_length=20,
        choices=EmploymentStatus.CHOICES,
        default=EmploymentStatus.ACTIVE
    )
    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentType.CHOICES,
        default=EmploymentType.FULL_TIME
    )

    # Employment dates
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    probation_end_date = models.DateField(null=True, blank=True)

    # Reporting structure (optional for founders/top-level)
    # manager_id references a user_id, not an EmployeeProfile
    manager_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="Direct manager user ID (null for top-level/founders)"
    )
    manager_email = models.EmailField(null=True, blank=True)

    # Dotted line reporting (for matrix organizations)
    dotted_line_manager_id = models.IntegerField(null=True, blank=True)
    dotted_line_manager_email = models.EmailField(null=True, blank=True)

    # Contact information
    work_phone = models.CharField(max_length=50, blank=True)
    work_email = models.EmailField(blank=True, help_text="Organization-specific work email")
    extension = models.CharField(max_length=20, blank=True)

    # Location
    office_location = models.CharField(max_length=255, blank=True)
    desk_number = models.CharField(max_length=50, blank=True)
    timezone = models.CharField(max_length=50, blank=True, default='UTC')

    # Employee ID (org-specific identifier)
    employee_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="Organization employee ID (e.g., EMP001)"
    )

    # Profile
    bio = models.TextField(blank=True)
    avatar_url = models.URLField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.membership.user_email} - {self.job_title or 'No title'}"

    @property
    def display_name(self):
        """Get display name from membership display_name, falling back to email prefix."""
        if self.membership.display_name:
            return self.membership.display_name
        return self.membership.user_email.split('@')[0] if self.membership.user_email else 'Unknown'

    @property
    def effective_job_title(self):
        """Get job title from profile or position."""
        return self.job_title or (self.position.title if self.position else '')

    def get_direct_reports(self):
        """Get all employees who report to this person."""
        if not self.membership.user_id:
            return EmployeeProfile.objects.none()
        return EmployeeProfile.objects.filter(
            manager_id=self.membership.user_id,
            membership__organization=self.membership.organization,
            membership__is_active=True
        )

    def get_management_chain(self):
        """Get the full management chain up to CEO/top."""
        chain = []
        current_manager_id = self.manager_id
        org = self.membership.organization
        visited = set()  # Prevent infinite loops

        while current_manager_id and current_manager_id not in visited:
            visited.add(current_manager_id)
            try:
                manager_profile = EmployeeProfile.objects.get(
                    membership__user_id=current_manager_id,
                    membership__organization=org,
                    membership__is_active=True
                )
                chain.append(manager_profile)
                current_manager_id = manager_profile.manager_id
            except EmployeeProfile.DoesNotExist:
                break

        return chain

    class Meta:
        db_table = 'organizations_employee_profile'
        indexes = [
            models.Index(fields=['department']),
            models.Index(fields=['manager_id']),
            models.Index(fields=['employment_status']),
            models.Index(fields=['employee_id']),
        ]
        constraints = [
            # Unique employee_id per organization
            models.UniqueConstraint(
                fields=['membership', 'employee_id'],
                name='unique_employee_id',
                condition=~models.Q(employee_id='')
            ),
        ]


class OrganizationServiceAccess(models.Model):
    """
    Tracks which services are enabled for an organization.
    Superusers can grant/revoke services per org.
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='service_access'
    )
    service_slug = models.CharField(max_length=50, db_index=True)
    is_enabled = models.BooleanField(default=True)
    granted_by_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['organization', 'service_slug']
        ordering = ['service_slug']
        db_table = 'organizations_service_access'

    def __str__(self):
        status = 'enabled' if self.is_enabled else 'disabled'
        return f"{self.organization.name} - {self.service_slug} ({status})"


class TeamMembership(models.Model):
    """
    Many-to-many relationship between employees and teams.
    Allows employees to be members of multiple teams with different roles.
    """
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    employee_profile = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name='team_memberships'
    )

    role = models.CharField(
        max_length=20,
        choices=TeamRole.CHOICES,
        default=TeamRole.MEMBER
    )

    # Membership dates
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.employee_profile.display_name} in {self.team.name} ({self.role})"

    class Meta:
        db_table = 'organizations_team_membership'
        ordering = ['team', 'role', 'joined_at']
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'employee_profile'],
                name='unique_team_member',
                condition=models.Q(is_active=True)
            ),
        ]
        indexes = [
            models.Index(fields=['team', 'is_active']),
            models.Index(fields=['employee_profile', 'is_active']),
        ]


class MembershipChange(models.Model):
    """
    Immutable audit trail for organization membership changes.

    Every role grant, revocation, role-change, or deactivation on an
    OrganizationMembership emits one row. This is the "who promoted whom,
    when" record that compliance reviews, security incidents, and
    least-privilege audits rely on. Modelled after AWS CloudTrail /
    GitHub's audit log for orgs.

    Rows are append-only: we never UPDATE or DELETE. The `previous_role`
    and `new_role` fields capture the full state transition so a diff is
    self-contained and doesn't require join-in-time queries back to the
    membership row (which itself may have moved on).
    """
    ACTION_CHOICES = [
        ('created',    'Created'),    # new membership (invite accepted, auto-enroll)
        ('role_changed', 'Role changed'),  # promote / demote
        ('deactivated', 'Deactivated'),    # soft-removed
        ('reactivated', 'Reactivated'),    # restored
        ('deleted',    'Deleted'),     # hard delete (rare — tombstone only)
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='membership_changes',
    )
    # Subject: the user whose membership changed. user_id may be NULL for
    # invitations that were revoked before acceptance.
    target_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    target_user_email = models.EmailField(null=True, blank=True)

    # Actor: who made the change. NULL if system-initiated (bootstrap,
    # auto-personal-workspace, migration).
    actor_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    actor_user_email = models.EmailField(null=True, blank=True)
    actor_source = models.CharField(
        max_length=50, default='api',
        help_text="'api' for user action, 'system' for bootstrap, 'migration' for data-fix.",
    )

    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    previous_role = models.CharField(max_length=20, null=True, blank=True)
    new_role = models.CharField(max_length=20, null=True, blank=True)
    reason = models.TextField(blank=True, help_text="Optional human-provided rationale.")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        prev = self.previous_role or '—'
        nxt = self.new_role or '—'
        subject = self.target_user_email or f'user_{self.target_user_id}'
        return f"[{self.action}] {subject} {prev}→{nxt} in {self.organization_id} @ {self.created_at.isoformat()}"

    class Meta:
        db_table = 'organizations_membership_change'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', '-created_at']),
            models.Index(fields=['target_user_id', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]



# ==============================================================================
# Project Membership (SCS-31 / SCS-20)
# ==============================================================================
# Thin join table: user ↔ Pulse project ↔ role within an organization.
# PLAT-5338: this comment used to say admin was the source of truth for *who*
# is a member of a project, and that shizuha-id read this table. Neither has
# been true for a long time. shizuha-pulse owns both the project definition and
# its membership; `/internal/users/{user_id}/project-memberships/` proxies to
# Pulse, and NOTHING in this codebase writes a ProjectMember row. The table is
# an unpopulated shadow, kept only so the schema and any manually-entered rows
# survive; it is not read on the token-mint path, because an unwritten table
# answering an authorization question returns "no access" for everyone.


class ProjectMemberRole:
    OWNER = 'owner'
    MEMBER = 'member'
    VIEWER = 'viewer'

    CHOICES = [
        (OWNER, 'Owner'),
        (MEMBER, 'Member'),
        (VIEWER, 'Viewer'),
    ]


class ProjectMember(models.Model):
    """
    Membership linking a user to a Pulse project within an organization.

    Pulse owns the project definition (id, name, key) AND the membership rows
    that `/internal/users/{user_id}/project-memberships/` returns; shizuha-id
    stamps that projection into JWTs as `project_ids` / `project_roles`
    (SCS-31).

    This model is not on that path. No code writes it and, since PLAT-5338, no
    code reads it either — it is retained as schema only. Do not reintroduce it
    as a fallback for the projection endpoint: an authorization answer derived
    from a table nothing populates is a fabricated "no access", not a
    degradation. If a genuine offline projection is ever needed, it has to be
    written by something and labelled non-authoritative at the API boundary.
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='project_memberships',
        help_text="The organization that owns the project.",
    )
    # user_id references a user in shizuha-id; no local FK by design.
    user_id = models.IntegerField(
        db_index=True,
        help_text="User ID from shizuha-id.",
    )
    user_email = models.EmailField(
        null=True, blank=True,
        help_text="Cached email for display / fallback lookups.",
    )
    # pulse_project_id is the integer primary key of the project row in
    # shizuha-pulse. Not a DB FK (cross-service boundary).
    pulse_project_id = models.IntegerField(
        db_index=True,
        help_text="Project ID in shizuha-pulse.",
    )
    role = models.CharField(
        max_length=20,
        choices=ProjectMemberRole.CHOICES,
        default=ProjectMemberRole.MEMBER,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.user_email or self.user_id} → project {self.pulse_project_id}"
            f" ({self.role}) in {self.organization_id}"
        )

    class Meta:
        db_table = 'organizations_project_member'
        ordering = ['organization', 'pulse_project_id', 'user_id']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'user_id', 'pulse_project_id'],
                name='unique_project_member',
                condition=models.Q(is_active=True),
            ),
        ]
        indexes = [
            models.Index(fields=['user_id', 'is_active'], name='org_projmem_user_active_idx'),
            models.Index(fields=['pulse_project_id', 'is_active'], name='org_projmem_proj_active_idx'),
            models.Index(fields=['organization', 'pulse_project_id'], name='org_projmem_org_proj_idx'),
        ]
