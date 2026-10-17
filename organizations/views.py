"""
Views for Organization and HR Hierarchy management.

Note: ProjectViewSet has been removed. Projects are now solely managed by shizuha-pulse.
Use /pulse/api/projects/ for project management.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.db import transaction
from django.db.models import Q, Count, Prefetch
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes as perm_classes
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Organization, OrganizationMembership,
    MembershipChange,
    JITElevatedAccessGrant, JITElevatedAccessGrantEvent,
    JITElevatedAccessGrantUse,
    Department, Team, Position, EmployeeProfile, TeamMembership,
    OrganizationServiceAccess,
)
from .serializers import (
    OrganizationSerializer, OrganizationCreateSerializer, CompanyOSSerializer,
    OrganizationMembershipSerializer, OrganizationMemberInviteSerializer,
    JITElevatedAccessGrantSerializer,
    # HR Hierarchy serializers
    DepartmentSerializer, DepartmentCreateSerializer, DepartmentTreeSerializer,
    TeamSerializer, TeamCreateSerializer,
    PositionSerializer, PositionCreateSerializer,
    EmployeeProfileSerializer, EmployeeProfileCreateSerializer, EmployeeProfileUpdateSerializer,
    EmployeeProfileMinimalSerializer,
    TeamMembershipSerializer, TeamMemberAddSerializer,
    OrgChartSerializer, OrgChartNodeSerializer,
    OrganizationServiceAccessSerializer, OrganizationServiceToggleSerializer,
    MemberServiceAccessSerializer,
)
from .permissions import OrganizationPermission
from .services.permissions import PermissionService
from .services.team_roster_authority import (
    FleetIdentityUnavailable,
    _canonical_team,
    fetch_authoritative_team_members,
    fetch_fleet_agent_emails,
    fleet_agent_write_denial,
)
from .security_events import emit_boundary_denial, record_jit_invariant_failure
from .service_display import serialize_org_service

logger = logging.getLogger(__name__)


def _normalize_user_id(raw_id):
    """Coerce JWT/FederatedUser ids to int so they compare equal to IntegerField.

    PLAT-5042: JWT claims and FederatedUser may surface user_id as str while
    JITElevatedAccessGrant.requester_user_id is IntegerField. A bare ``!=``
    then fails for every requester even when the principal is correct.

    Applied once in ``_actor_identity`` so all five store/compare sites that
    resolve the actor through that helper share one normalisation boundary
    (store at create, list filter, decision TEAM_MEMBER_ADD, decision legacy,
    consume gate).
    """
    if raw_id is None or isinstance(raw_id, bool):
        # bool is a subclass of int; reject rather than coerce True→1.
        return None
    if isinstance(raw_id, int):
        return raw_id
    try:
        return int(str(raw_id).strip())
    except (TypeError, ValueError):
        return None


def _actor_identity(request):
    """Return (user_id:int|None, email:str) for the authenticated principal."""
    user = request.user
    return (
        _normalize_user_id(getattr(user, 'id', None)),
        (getattr(user, 'email', '') or '').strip(),
    )


def _matches_requester(user_id, email, grant):
    """Is the actor the grant's requester? Match by user_id OR email.

    PLAT-4952: a federated/non-staff user's local ``request.user.id`` is not a
    stable key, so the recorded ``requester_user_id`` may not equal the same
    user's id at a later call. Fall back to the recorded ``requester_email``
    (case-insensitive) — mirroring the ``Q(requester_user_id=user_id) |
    Q(requester_email=email)`` lookup used for JIT grant queries. Used for BOTH
    the revoke-allow branch and the SoD self-action block so the identity is
    reliable and neither fails open.
    """
    if (
        user_id is not None
        and grant.requester_user_id is not None
        and user_id == grant.requester_user_id
    ):
        return True
    e = (email or '').strip().lower()
    return bool(e) and e == (grant.requester_email or '').strip().lower()


def _active_approver_team_ids(user_id):
    """Team ids where the actor is an active lead/member, never an advisor."""
    if user_id is None:
        return Team.objects.none().values_list('id', flat=True)
    return Team.objects.filter(
        Q(
            lead_id=user_id,
            organization__memberships__user_id=user_id,
            organization__memberships__is_active=True,
            organization__memberships__is_pending=False,
        )
        | Q(
            memberships__is_active=True,
            memberships__role__in=['lead', 'member'],
            memberships__employee_profile__membership__user_id=user_id,
            memberships__employee_profile__membership__is_active=True,
            memberships__employee_profile__membership__is_pending=False,
        ),
        is_active=True,
        organization__is_active=True,
    ).values_list('id', flat=True).distinct()


def _is_active_team_approver(user_id, team, *, lock_membership=False):
    if user_id is None or team is None or not team.is_active or not team.organization.is_active:
        return False
    org_memberships = OrganizationMembership.objects
    if lock_membership:
        org_memberships = org_memberships.select_for_update()
    if not org_memberships.filter(
        organization=team.organization,
        user_id=user_id,
        is_active=True,
        is_pending=False,
    ).exists():
        return False
    if team.lead_id == user_id:
        return True
    memberships = TeamMembership.objects
    if lock_membership:
        memberships = memberships.select_for_update()
    return memberships.filter(
        team=team,
        is_active=True,
        role__in=['lead', 'member'],
        employee_profile__membership__user_id=user_id,
        employee_profile__membership__is_active=True,
        employee_profile__membership__is_pending=False,
    ).exists()


def _audit_jit(grant, event_type, request, *, source='api', detail=None):
    actor_user_id, actor_email = _actor_identity(request)
    return JITElevatedAccessGrantEvent.objects.create(
        grant=grant,
        event_type=event_type,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        source=source,
        detail=detail or {},
    )


def _jit_identity_evidence(actor_user_id, grant):
    """PLAT-5042: the compared pair, with the namespace each side came from.

    The identity check at the consume gate and the decision views compares two
    integers and returns 403 without recording either, so a denial is
    indistinguishable from having no grant at all. That cost ~40h of wrong
    diagnosis across two architects, for values that were in scope at the
    moment of failure. Emitting both sides -- and naming which id space each
    came from -- is what lets the NEXT occurrence be read off a row instead of
    re-derived.

    Deliberately NOT routed through _audit_jit_invariant_failure: that helper
    pages, and its exclusion of authorization denials is intentional. Wiring
    identity denials into it would page on every legitimate SoD refusal.

    §4: requester_email is reported only; never compared in any gate.
    """
    return {
        'actor_user_id': actor_user_id,
        'actor_user_id_source': 'request.user.id',
        'grant_requester_user_id': grant.requester_user_id,
        'grant_requester_user_id_source': 'JITElevatedAccessGrant.requester_user_id',
        'grant_requester_email': getattr(grant, 'requester_email', '') or '',
        'identity_match': actor_user_id == grant.requester_user_id,
    }


def _audit_jit_invariant_failure(
    request, *, code, operation, organization, grant=None, detail=None,
):
    """Persist and page on mechanism failures, not expected authorization denials."""
    evidence = {
        'code': code,
        'operation': operation,
        'organization_id': organization.id,
        **(detail or {}),
    }
    _audit_jit(
        grant,
        'invariant_failed',
        request,
        source='validator',
        detail=evidence,
    )
    def notify_owner():
        record_jit_invariant_failure()
        emit_boundary_denial(
            request=request,
            service='admin',
            operation=operation,
            reason=code,
            target_org_id=organization.id,
            source_org_ids=[organization.id],
            owner_team='platform',
            dedupe_key=f'{operation}:{code}:{organization.id}',
        )

    # Keep network/Redis I/O outside the grant/Team row-lock transaction and
    # never page on an invariant event that later rolls back.
    transaction.on_commit(notify_owner)


def _user_has_active_jit_grant(request, org, *, scope, min_role='admin'):
    """Return True when request.user has an unexpired scoped JIT grant."""
    user_id, email = _actor_identity(request)
    min_priority = JITElevatedAccessGrant.role_priority(min_role)
    grants = JITElevatedAccessGrant.active_queryset(
        user_id=user_id,
        email=email,
        organization=org,
        scope=scope,
    )
    return any(
        JITElevatedAccessGrant.role_priority(grant.requested_role) >= min_priority
        for grant in grants
    )


class CurrentUserView(APIView):
    """Get current user info including staff/superuser status."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            'id': user.id,
            'email': user.email,
            'username': getattr(user, 'username', user.email),
            'first_name': getattr(user, 'first_name', ''),
            'last_name': getattr(user, 'last_name', ''),
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
        })


class AuditorRoleGrantView(APIView):
    """Grant or revoke the read-only auditor role through the tenant API."""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, slug, user_id):
        role = request.data.get('role')
        if not role:
            return Response({'error': 'role is required'}, status=status.HTTP_400_BAD_REQUEST)
        if role not in ('auditor', 'member', 'viewer'):
            return Response(
                {'error': 'Only auditor grants or member/viewer auditor revocations are allowed through this endpoint'},
                status=status.HTTP_403_FORBIDDEN,
            )
        with transaction.atomic():
            org = Organization.objects.select_for_update().filter(
                slug=slug, is_active=True,
            ).first()
            if org is None:
                return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)
            actor_membership = OrganizationMembership.objects.select_for_update().filter(
                user_id=request.user.id, organization=org, is_active=True, is_pending=False,
            ).first()
            if actor_membership is None or actor_membership.role not in ('owner', 'admin'):
                return Response({'error': 'Organization owner or admin role required'}, status=status.HTTP_403_FORBIDDEN)
            membership = OrganizationMembership.objects.select_for_update().filter(
                user_id=user_id, organization=org, is_active=True, is_pending=False,
            ).first()
            if membership is None:
                return Response({'error': 'Membership not found'}, status=status.HTTP_404_NOT_FOUND)
            user_email = request.data.get('email')
            if user_email and membership.user_email != user_email:
                return Response({'error': 'Email does not match the specified membership'}, status=status.HTTP_400_BAD_REQUEST)
            if membership.role in ('owner', 'admin'):
                return Response(
                    {'error': 'Owner and admin memberships cannot be changed through this endpoint'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if membership.role == role:
                return Response({'updated': False, 'role': role, 'user_id': membership.user_id, 'user_email': membership.user_email, 'organization_id': org.id})
            if role != 'auditor' and membership.role != 'auditor':
                return Response(
                    {'error': 'Only an auditor membership may be restored to member or viewer'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            previous_role = membership.role
            # Deliberately bypass the generic post_save signal: this privileged
            # grant owns a fail-closed mutation + audit transaction and must not
            # inherit the signal's best-effort/fail-open semantics.
            OrganizationMembership.objects.filter(pk=membership.pk).update(
                role=role,
                updated_at=timezone.now(),
            )
            MembershipChange.objects.create(
                organization=org,
                target_user_id=membership.user_id,
                target_user_email=membership.user_email,
                actor_user_id=request.user.id,
                actor_user_email=getattr(request.user, 'email', None),
                actor_source='api',
                action='role_changed',
                previous_role=previous_role,
                new_role=role,
            )
        return Response({'updated': True, 'role': role, 'user_id': membership.user_id, 'user_email': membership.user_email, 'organization_id': org.id})


class JITElevatedAccessGrantView(APIView):
    """
    Request/list scoped, time-bound elevated access (PLAT-1346).

    Low-risk requests are approved immediately only when a trusted internal
    policy predicate is machine-verified. Other requests remain pending for the
    owning team; no path routes to the operator by default.
    """
    permission_classes = [permissions.IsAuthenticated]

    DEFAULT_TTL_SECONDS = 3600

    def _visible_queryset(self, request):
        user_id, email = _actor_identity(request)
        qs = JITElevatedAccessGrant.objects.select_related(
            'organization', 'approver_team', 'target_team',
        )
        if getattr(request.user, 'is_superuser', False):
            return qs

        requester_q = Q(requester_user_id=user_id)
        if email:
            requester_q |= Q(requester_email=email)
        exact_scopes = tuple(JITElevatedAccessGrant.EXACT_SCOPE_POLICIES)
        exact_approver_q = Q(
            scope__in=exact_scopes,
            approver_team_id__in=_active_approver_team_ids(user_id),
            policy_key__gt='',
            policy_version__isnull=False,
            policy_digest__gt='',
            constraint_digest__gt='',
        )

        # ADR-0048 removes blanket staff authority only for the new exact,
        # target-constrained contract.  Keep the v2 compatibility rules for
        # existing scopes while they migrate independently.
        legacy_scope_q = ~Q(scope__in=exact_scopes)
        if getattr(request.user, 'is_staff', False):
            return qs.filter(requester_q | exact_approver_q | legacy_scope_q)

        admin_org_ids = OrganizationMembership.objects.filter(
            user_id=user_id,
            role__in=['owner', 'admin'],
            is_active=True,
            organization__is_active=True,
        ).values_list('organization_id', flat=True)
        return qs.filter(
            requester_q
            | exact_approver_q
            | (legacy_scope_q & Q(organization_id__in=admin_org_ids))
        )

    def get(self, request):
        qs = self._visible_queryset(request)
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response({
            'count': qs.count(),
            'results': JITElevatedAccessGrantSerializer(qs[:100], many=True).data,
        })

    def post(self, request):
        org_slug = request.data.get('org_slug') or request.data.get('organization_slug')
        scope = (request.data.get('scope') or '').strip()
        requested_role = (request.data.get('role') or request.data.get('requested_role') or 'admin').strip()
        reason = (request.data.get('reason') or '').strip()
        task_key = (request.data.get('task_key') or request.data.get('task') or '').strip()
        owning_team = (request.data.get('owning_team') or 'admin-platform').strip()
        policy_slug = (request.data.get('policy_slug') or '').strip()

        try:
            ttl_seconds = int(request.data.get('ttl_seconds') or self.DEFAULT_TTL_SECONDS)
        except (TypeError, ValueError):
            return Response({'error': 'ttl_seconds must be an integer'}, status=status.HTTP_400_BAD_REQUEST)

        if not org_slug or not scope or not reason or not task_key:
            return Response(
                {'error': 'org_slug, scope, reason, and task_key are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if requested_role not in dict(OrganizationMembership.ROLE_CHOICES):
            return Response({'error': 'requested role is invalid'}, status=status.HTTP_400_BAD_REQUEST)
        if ttl_seconds <= 0 or ttl_seconds > JITElevatedAccessGrant.MAX_TTL_SECONDS:
            return Response(
                {'error': f'ttl_seconds must be between 1 and {JITElevatedAccessGrant.MAX_TTL_SECONDS}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            org = Organization.objects.get(slug=org_slug, is_active=True)
        except Organization.DoesNotExist:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        requester_user_id, requester_email = _actor_identity(request)
        if requester_user_id is None:
            return Response({'error': 'Authenticated user id is required'}, status=status.HTTP_400_BAD_REQUEST)

        is_member = OrganizationMembership.objects.filter(
            organization=org,
            user_id=requester_user_id,
            is_active=True,
            is_pending=False,
        ).exists()
        if not is_member and not getattr(request.user, 'is_staff', False):
            return Response(
                {'error': 'Requester must already belong to the organization'},
                status=status.HTTP_403_FORBIDDEN,
            )

        exact_policy = JITElevatedAccessGrant.exact_policy_for_scope(scope)
        # ORIG-361: this mistaken runbook alias created generic pending grants
        # with no exact policy or target constraints. They cannot be consumed by
        # the Kubernetes adapter even after approval. Require a fresh canonical
        # request; never silently upgrade an alias into executable authority.
        if scope == 'kubernetes.ci_deployer_rbac.apply':
            return Response(
                {
                    'error': 'Unsupported Kubernetes JIT scope; request kubernetes.rbac.apply with commit_sha',
                    'code': 'jit_scope_alias_unsupported',
                    'supported_scope': JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        exact_values = {}
        if exact_policy:
            if not exact_policy.get('enabled'):
                _audit_jit_invariant_failure(
                    request,
                    code='jit_exact_policy_disabled',
                    operation='admin.jit.admission',
                    organization=org,
                    detail={'scope': scope, 'task_key': task_key},
                )
                return Response({'error': 'JIT scope policy is disabled'}, status=status.HTTP_403_FORBIDDEN)
            if ttl_seconds > exact_policy['max_ttl_seconds']:
                return Response(
                    {'error': f'ttl_seconds exceeds policy maximum {exact_policy["max_ttl_seconds"]}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            approver_teams = list(Team.objects.filter(
                organization=org,
                name__iexact=exact_policy['approver_team_name'],
                is_active=True,
            )[:2])
            if len(approver_teams) != 1:
                _audit_jit_invariant_failure(
                    request,
                    code='jit_approver_team_not_unique',
                    operation='admin.jit.admission',
                    organization=org,
                    detail={
                        'scope': scope,
                        'task_key': task_key,
                        'candidate_count': len(approver_teams),
                    },
                )
                return Response(
                    {'error': 'Registered approver team is not uniquely resolvable'},
                    status=status.HTTP_409_CONFLICT,
                )
            approver_team = approver_teams[0]
            accepted_owner_names = {
                approver_team.name.casefold(),
                'admin-platform',
                'platform',
            }
            if owning_team and owning_team.casefold() not in accepted_owner_names:
                return Response(
                    {'error': 'owning_team is policy-derived for this scope'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            exact_values = {
                'owning_team': approver_team.name,
                'approver_team': approver_team,
                'policy_key': exact_policy['key'],
                'policy_version': exact_policy['version'],
                'policy_digest': JITElevatedAccessGrant.exact_policy_digest(exact_policy),
                'max_uses': exact_policy['max_uses'],
                'policy_slug': exact_policy['key'],
            }
            if scope == JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE:
                try:
                    target_team_id = int(request.data.get('target_team_id') or request.data.get('team_id'))
                    target_user_id = int(request.data.get('target_user_id') or request.data.get('user_id'))
                except (TypeError, ValueError):
                    return Response(
                        {'error': 'target_team_id and target_user_id are required integers'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                target_role = (request.data.get('target_role') or request.data.get('team_role') or '').strip()
                if target_role not in ['lead', 'member']:
                    return Response({'error': 'target_role must be lead or member'}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    target_team = Team.objects.get(pk=target_team_id, organization=org, is_active=True)
                except Team.DoesNotExist:
                    return Response({'error': 'Target team not found'}, status=status.HTTP_404_NOT_FOUND)
                target_profile = EmployeeProfile.objects.filter(
                    membership__organization=org,
                    membership__user_id=target_user_id,
                    membership__is_active=True,
                    membership__is_pending=False,
                ).first()
                if target_profile is None:
                    return Response({'error': 'Target user is not an active employee'}, status=status.HTTP_404_NOT_FOUND)
                constraints = {
                    'organization_id': org.id,
                    'team_id': target_team.id,
                    'user_id': target_user_id,
                    'role': target_role,
                }
                exact_values.update({
                    'target_team': target_team,
                    'target_user_id': target_user_id,
                    'target_role': target_role,
                })
            elif scope == JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE:
                commit_sha = (request.data.get('commit_sha') or '').strip().lower()
                if not re.fullmatch(r'[0-9a-f]{40}', commit_sha):
                    return Response(
                        {'error': 'commit_sha must be the full 40-character deploy default-branch SHA'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                constraints = {**exact_policy['fixed_constraints'], 'commit_sha': commit_sha}
            else:  # registry presence plus missing adapter is an invariant fault
                return Response({'error': 'Exact JIT scope has no admission adapter'}, status=status.HTTP_409_CONFLICT)
            exact_values.update({
                'target_constraints': constraints,
                'constraint_digest': JITElevatedAccessGrant.constraint_digest_for(constraints),
            })

        # Fail closed: a caller's assertion that work is "low risk" is not a
        # policy proof. Auto-approval requires an allowlisted policy predicate
        # from a trusted staff/internal actor; ordinary org members get a pending
        # owning-team request even for org.members.add.
        policy_verified = bool(policy_slug and getattr(request.user, 'is_staff', False))
        auto_approved = JITElevatedAccessGrant.can_auto_approve(
            scope=scope,
            requested_role=requested_role,
            ttl_seconds=ttl_seconds,
            policy_slug=policy_slug,
            policy_verified=policy_verified,
            # PLAT-8895: the exact-target proof — the admission adapter's
            # validated team/user/role constraints, snapshotted with a
            # constraint digest. Absent for non-exact scopes; required for the
            # target-constrained predicate leg.
            has_exact_constraints=bool(exact_values.get('constraint_digest')),
        )
        grant = JITElevatedAccessGrant.objects.create(
            organization=org,
            requester_user_id=requester_user_id,
            requester_email=requester_email,
            scope=scope,
            requested_role=requested_role,
            reason=reason,
            task_key=task_key,
            ttl_seconds=ttl_seconds,
            approval_path=(
                JITElevatedAccessGrant.APPROVAL_POLICY
                if auto_approved else JITElevatedAccessGrant.APPROVAL_TEAM
            ),
            owning_team=exact_values.get('owning_team', owning_team),
            risk_level=JITElevatedAccessGrant.risk_for(scope=scope, requested_role=requested_role),
            policy_slug=(
                exact_values.get('policy_slug', '')
                or (policy_slug if auto_approved else '')
            ),
            **{key: value for key, value in exact_values.items() if key not in {'owning_team', 'policy_slug'}},
        )
        _audit_jit(
            grant,
            'requested',
            request,
            detail={
                'task_key': task_key,
                'scope': scope,
                'policy_key': grant.policy_key,
                'policy_version': grant.policy_version,
                'constraint_digest': grant.constraint_digest,
                # PLAT-8895: record which predicate discharged the lane.
                **({'auto_policy_slug': policy_slug} if auto_approved else {}),
            },
        )
        if auto_approved:
            grant.approve(
                actor_user_id=None,
                actor_email=f'policy:{policy_slug}',
                note='Policy auto-approved verified low-risk scoped organization-member administration.',
                approval_path=JITElevatedAccessGrant.APPROVAL_POLICY,
            )
            _audit_jit(grant, 'approved', request, source='policy', detail={'policy_slug': policy_slug})

        return Response({
            'auto_approved': auto_approved,
            'owning_team': grant.owning_team,
            'grant': JITElevatedAccessGrantSerializer(grant).data,
        }, status=status.HTTP_201_CREATED)


class JITElevatedAccessGrantDetailView(APIView):
    """PLAT-5079: read a single JIT grant plus its decision-event history.

    Read/observability only — no new write capability. Scoped to the same
    visible queryset as the list endpoint, so a seat not entitled to the grant
    still cannot read it (negative control preserved).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        try:
            grant = JITElevatedAccessGrantView()._visible_queryset(request).get(pk=pk)
        except JITElevatedAccessGrant.DoesNotExist:
            return Response(
                {'error': 'JIT grant not found or not visible to you'},
                status=status.HTTP_404_NOT_FOUND,
            )
        events = JITElevatedAccessGrantEvent.objects.filter(
            grant=grant,
        ).order_by('created_at', 'id').values(
            'id', 'event_type', 'actor_user_id', 'actor_email',
            'source', 'detail', 'created_at',
        )
        return Response({
            'grant': JITElevatedAccessGrantSerializer(grant).data,
            'events': list(events),
        })


class JITElevatedAccessGrantDecisionView(APIView):
    """Approve, deny, or revoke a JIT grant by the owning org/team."""
    permission_classes = [permissions.IsAuthenticated]

    def _get_grant_for_decision(self, request, pk, action_name):
        try:
            # Nullable Team FKs would turn select_related into OUTER JOINs;
            # PostgreSQL cannot apply FOR UPDATE to their nullable side.  Lock
            # only the grant row and resolve those relations lazily in the same
            # transaction.
            grant = JITElevatedAccessGrant.objects.select_for_update().select_related(
                'organization',
            ).get(pk=pk)
        except JITElevatedAccessGrant.DoesNotExist:
            return None, Response({'error': 'JIT grant not found'}, status=status.HTTP_404_NOT_FOUND)

        user_id, actor_email = _actor_identity(request)

        if grant.scope in JITElevatedAccessGrant.EXACT_SCOPE_POLICIES:
            # PLAT-4952 identity semantics apply to every exact scope: match
            # the requester by user_id OR recorded email (federated local ids
            # are not stable), never by team string.
            requester = _matches_requester(user_id, actor_email, grant)
            locked_approver_team = None
            if grant.approver_team_id:
                locked_approver_team = Team.objects.select_for_update().select_related(
                    'organization',
                ).filter(pk=grant.approver_team_id).first()
            approver = _is_active_team_approver(
                user_id,
                locked_approver_team,
                lock_membership=True,
            )
            break_glass = bool(getattr(request.user, 'is_superuser', False))
            # Revocation is authority-reducing and remains available when a
            # policy is disabled/stale.  This lets the requester, exact team,
            # or explicit superuser break-glass remove a pending/unconsumed
            # capability without treating its stale snapshot as approval
            # authority.
            if action_name == 'revoke':
                if requester or approver or break_glass:
                    return grant, None
                # Polarity pair for id-space faults: a false-negative requester
                # (match expected, match not seen) lands here instead of the
                # SoD path. Record the compared pair so the next occurrence is
                # diagnosable (PLAT-5042).
                _audit_jit(
                    grant,
                    'decision_authority_denied',
                    request,
                    detail=_jit_identity_evidence(user_id, grant),
                )
                return None, Response(
                    {'error': 'Requester, exact owning team, or superuser break-glass required'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if action_name not in {'approve', 'deny'}:
                return None, Response({'error': 'Unknown JIT decision action'}, status=status.HTTP_404_NOT_FOUND)
            # Legacy free-form rows never become authority merely because the
            # old owning_team string happens to resolve.  They remain visible
            # only to their requester and must be re-requested under v3.
            if not grant.has_complete_current_exact_authority():
                if not (requester or approver or break_glass):
                    return None, Response(
                        {'error': 'Exact owning-team approval required'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                _audit_jit_invariant_failure(
                    request,
                    code='jit_exact_contract_stale',
                    operation='admin.jit.decision',
                    organization=grant.organization,
                    grant=grant,
                    detail={'action': action_name},
                )
                return None, Response(
                    {'error': 'JIT grant lacks a current complete policy contract; re-request it'},
                    status=status.HTTP_409_CONFLICT,
                )

            if requester:
                # SoD negative control (PLAT-5042 AC4 / PLAT-4878): requester
                # deciding own grant must stay refused after id normalisation.
                _audit_jit(
                    grant,
                    'requester_self_decide_denied',
                    request,
                    detail=_jit_identity_evidence(user_id, grant),
                )
                return None, Response(
                    {'error': 'Requester cannot approve or deny their own JIT grant'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if not approver:
                return None, Response(
                    {'error': 'Exact owning-team approval required'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            return grant, None

        # Requesters cannot approve, deny, or revoke their own grants — applies to everyone
        # including staff to enforce separation of duties. Match by user_id OR email
        # (PLAT-4952) so a federated requester whose local id shifted can't slip past.
        if _matches_requester(user_id, actor_email, grant):
            _audit_jit(
                grant,
                'requester_self_decide_denied',
                request,
                detail=_jit_identity_evidence(user_id, grant),
            )
            return None, Response(
                {'error': 'Requester cannot approve or deny their own JIT grant'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if getattr(request.user, 'is_staff', False):
            return grant, None

        # High/medium-risk grants require staff; org admins may only decide low-risk grants.
        if grant.risk_level != JITElevatedAccessGrant.RISK_LOW:
            return None, Response(
                {'error': 'Only staff can approve or revoke high/medium-risk JIT grants'},
                status=status.HTTP_403_FORBIDDEN,
            )

        can_decide = OrganizationMembership.objects.filter(
            organization=grant.organization,
            user_id=user_id,
            role__in=['owner', 'admin'],
            is_active=True,
        ).exists()
        if not can_decide:
            return None, Response(
                {'error': 'Owning-team/org admin approval required'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return grant, None

    def post(self, request, pk, action_name):
        note = (request.data.get('note') or '').strip()
        if action_name == 'revoke' and not note:
            return Response({'error': 'Revocation reason is required'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            grant, error = self._get_grant_for_decision(request, pk, action_name)
            if error is not None:
                return error

            actor_user_id, actor_email = _actor_identity(request)

            if action_name == 'approve':
                if grant.status != JITElevatedAccessGrant.STATUS_PENDING:
                    return Response({'error': 'Only pending grants can be approved'}, status=status.HTTP_400_BAD_REQUEST)
                grant.approve(
                    actor_user_id=actor_user_id,
                    actor_email=actor_email,
                    note=note,
                    approval_path=JITElevatedAccessGrant.APPROVAL_TEAM,
                )
                event_type = 'approved'
            elif action_name == 'deny':
                if grant.status != JITElevatedAccessGrant.STATUS_PENDING:
                    return Response({'error': 'Only pending grants can be denied'}, status=status.HTTP_400_BAD_REQUEST)
                grant.deny(actor_user_id=actor_user_id, actor_email=actor_email, note=note)
                event_type = 'denied'
            elif action_name == 'revoke':
                if grant.status not in {
                    JITElevatedAccessGrant.STATUS_PENDING,
                    JITElevatedAccessGrant.STATUS_APPROVED,
                }:
                    return Response(
                        {'error': 'Only pending or approved grants can be revoked'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if grant.uses_consumed:
                    return Response(
                        {'error': 'A consumed grant cannot be revoked before use'},
                        status=status.HTTP_409_CONFLICT,
                    )
                grant.revoke(actor_user_id=actor_user_id, actor_email=actor_email, note=note)
                event_type = 'revoked'
            else:
                return Response({'error': 'Unknown JIT decision action'}, status=status.HTTP_404_NOT_FOUND)

            _audit_jit(
                grant,
                event_type,
                request,
                source=('superuser-break-glass' if getattr(request.user, 'is_superuser', False) else 'api'),
                detail={'note': note},
            )

        return Response({'grant': JITElevatedAccessGrantSerializer(grant).data})


class KubernetesJITConsumeView(APIView):
    """Consume one exact Kubernetes grant into an Origin workflow outbox."""

    permission_classes = [permissions.IsAuthenticated]
    ACTION = 'apply-origin-ci-deployer-rbac'

    def post(self, request, pk):
        idempotency_key = (
            request.data.get('idempotency_key')
            or request.headers.get('Idempotency-Key')
            or ''
        ).strip()
        action = (request.data.get('action') or '').strip()
        expected_sha = (request.data.get('expected_sha') or '').strip().lower()
        if not idempotency_key or len(idempotency_key) > 100:
            return Response(
                {'error': 'An idempotency key of at most 100 characters is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if action != self.ACTION:
            return Response({'error': 'Unsupported Kubernetes JIT action'}, status=status.HTTP_400_BAD_REQUEST)
        if not re.fullmatch(r'[0-9a-f]{40}', expected_sha):
            return Response({'error': 'expected_sha must be a full commit SHA'}, status=status.HTTP_400_BAD_REQUEST)
        canonical_request = {'action': action, 'expected_sha': expected_sha}
        request_digest = JITElevatedAccessGrant.constraint_digest_for(canonical_request)

        with transaction.atomic():
            try:
                grant = JITElevatedAccessGrant.objects.select_for_update().select_related(
                    'organization',
                ).get(pk=pk)
            except (JITElevatedAccessGrant.DoesNotExist, ValueError):
                return Response({'error': 'JIT grant not found'}, status=status.HTTP_404_NOT_FOUND)

            actor_user_id, actor_email = _actor_identity(request)
            if actor_user_id is None:
                return Response({'error': 'Authenticated actor could not be resolved'}, status=status.HTTP_401_UNAUTHORIZED)
            if actor_user_id != grant.requester_user_id:
                _audit_jit(grant, 'identity_denied', request, detail=_jit_identity_evidence(actor_user_id, grant))
                return Response({'error': 'Grant requester identity mismatch'}, status=status.HTTP_403_FORBIDDEN)
            if grant.scope != JITElevatedAccessGrant.KUBERNETES_RBAC_APPLY_SCOPE:
                return Response({'error': 'Grant scope does not authorize this action'}, status=status.HTTP_403_FORBIDDEN)

            prior_use = JITElevatedAccessGrantUse.objects.filter(
                grant=grant, idempotency_key=idempotency_key,
            ).first()
            if prior_use is not None:
                if prior_use.request_digest != request_digest:
                    return Response(
                        {'error': 'Idempotency key was already used for a different request'},
                        status=status.HTTP_409_CONFLICT,
                    )
                return Response(prior_use.result, status=status.HTTP_202_ACCEPTED)

            if not grant.has_complete_current_exact_authority():
                _audit_jit_invariant_failure(
                    request, code='jit_exact_contract_stale',
                    operation='admin.jit.kubernetes.consume',
                    organization=grant.organization, grant=grant,
                )
                return Response({'error': 'Grant policy is incomplete, disabled, or stale'}, status=status.HTTP_403_FORBIDDEN)
            if grant.status != JITElevatedAccessGrant.STATUS_APPROVED:
                return Response({'error': 'Grant is not approved'}, status=status.HTTP_403_FORBIDDEN)
            if grant.revoked_at is not None or grant.expires_at is None or grant.expires_at <= timezone.now():
                return Response({'error': 'Grant is expired or revoked'}, status=status.HTTP_403_FORBIDDEN)
            if grant.uses_consumed >= grant.max_uses:
                return Response({'error': 'Grant use limit is exhausted'}, status=status.HTTP_403_FORBIDDEN)
            constraints = grant.target_constraints
            if expected_sha != constraints.get('commit_sha'):
                return Response({'error': 'Grant target constraints do not match'}, status=status.HTTP_403_FORBIDDEN)

            consumed_at = timezone.now()
            use = JITElevatedAccessGrantUse.objects.create(
                grant=grant, idempotency_key=idempotency_key,
                request_digest=request_digest, actor_user_id=actor_user_id,
                actor_email=actor_email, result={}, dispatch_status='pending',
            )
            result = {
                'grant_id': grant.pk,
                'use_id': use.pk,
                'task_key': grant.task_key,
                'action': self.ACTION,
                'expected_sha': expected_sha,
                'dispatch_status': 'pending',
            }
            use.result = result
            use.save(update_fields=['result'])
            JITElevatedAccessGrant.objects.filter(pk=grant.pk).update(
                uses_consumed=grant.uses_consumed + 1,
                status=JITElevatedAccessGrant.STATUS_REVOKED,
                revoked_at=consumed_at,
                updated_at=consumed_at,
            )
            grant.uses_consumed += 1
            grant.status = JITElevatedAccessGrant.STATUS_REVOKED
            grant.revoked_at = consumed_at
            _audit_jit(
                grant, 'consumed', request,
                detail={
                    'use_id': use.pk,
                    'constraint_digest': grant.constraint_digest,
                    'idempotency_key_digest': JITElevatedAccessGrant._canonical_digest(idempotency_key),
                    'auto_revoked': True,
                },
            )
            _audit_jit(grant, 'dispatch_queued', request, detail={'use_id': use.pk})
            _audit_jit(grant, 'auto_revoked', request, detail={'use_id': use.pk})

            from .tasks import dispatch_kubernetes_jit_use_task
            transaction.on_commit(lambda: dispatch_kubernetes_jit_use_task.delay(use.pk))

        return Response(result, status=status.HTTP_202_ACCEPTED)


class SuperuserUserDeletePreviewView(APIView):
    """
    Superuser-only view to preview the impact of deleting a user.

    Returns counts of:
    - Assigned tasks (from shizuha-pulse)
    - Organization memberships
    - Team memberships
    - Warnings (e.g., user is org owner)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        import requests
        import os

        if not request.user.is_superuser:
            return Response(
                {'error': 'Only superusers can delete users'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Cannot delete yourself
        if user_id == request.user.id:
            return Response(
                {'error': 'Cannot delete your own account'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Fetch user info from shizuha-id
        user_info = None
        try:
            shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
            response = requests.get(f'{shizuha_id_url}/internal/users/{user_id}/', timeout=5)
            if response.status_code == 200:
                user_info = response.json()
        except Exception as e:
            logger.warning(f"Failed to fetch user {user_id} from Shizuha ID: {e}")

        if not user_info:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Count organization memberships
        org_memberships = OrganizationMembership.objects.filter(
            user_id=user_id,
            is_active=True
        )
        org_membership_count = org_memberships.count()

        # Count team memberships
        team_membership_count = TeamMembership.objects.filter(
            employee_profile__membership__user_id=user_id,
            is_active=True
        ).count()

        # Count assigned tasks from Pulse
        assigned_tasks_count = 0
        try:
            pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            headers = {'Authorization': auth_header} if auth_header else {}

            # Query items assigned to this user
            tasks_response = requests.get(
                f'{pulse_url}/items/',
                params={'assignee_id': user_id},
                headers=headers,
                timeout=10
            )
            if tasks_response.status_code == 200:
                tasks_data = tasks_response.json()
                assigned_tasks_count = tasks_data.get('count', len(tasks_data.get('results', [])))
        except Exception as e:
            logger.warning(f"Failed to count tasks for user {user_id} from Pulse: {e}")

        # Build warnings
        warnings = []

        # Check if user owns any organizations
        owned_orgs = Organization.objects.filter(owner_id=user_id, is_active=True)
        if owned_orgs.exists():
            warnings.append(f"User is owner of {owned_orgs.count()} organization(s). Ownership should be transferred first.")

        # Check if user is a department head
        dept_heads = Department.objects.filter(head_id=user_id, is_active=True)
        if dept_heads.exists():
            warnings.append(f"User is head of {dept_heads.count()} department(s).")

        # Check if user is a team lead
        team_leads = Team.objects.filter(lead_id=user_id, is_active=True)
        if team_leads.exists():
            warnings.append(f"User is lead of {team_leads.count()} team(s).")

        # Check if user manages employees
        manages = EmployeeProfile.objects.filter(
            manager_id=user_id,
            membership__is_active=True
        )
        if manages.exists():
            warnings.append(f"User manages {manages.count()} employee(s). Their manager will be set to null.")

        return Response({
            'user': user_info,
            'impact': {
                'assigned_tasks_count': assigned_tasks_count,
                'organization_memberships_count': org_membership_count,
                'team_memberships_count': team_membership_count,
            },
            'warnings': warnings,
            'can_delete': True  # Always allow, warnings are informational
        })


class SuperuserUserDeleteView(APIView):
    """
    Superuser-only view to delete a user.

    Orchestrates:
    1. Unassign all tasks in shizuha-pulse
    2. Remove organization memberships, team memberships, employee profiles
    3. Delete user in shizuha-id
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, user_id):
        import requests
        import os

        if not request.user.is_superuser:
            return Response(
                {'error': 'Only superusers can delete users'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Cannot delete yourself
        if user_id == request.user.id:
            return Response(
                {'error': 'Cannot delete your own account'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify user exists in shizuha-id
        shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        try:
            response = requests.get(f'{shizuha_id_url}/internal/users/{user_id}/', timeout=5)
            if response.status_code != 200:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            user_info = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch user {user_id} from Shizuha ID: {e}")
            return Response(
                {'error': 'Failed to verify user exists'},
                status=status.HTTP_502_BAD_GATEWAY
            )

        deleted_data = {
            'tasks_unassigned': 0,
            'organization_memberships_removed': 0,
            'team_memberships_removed': 0,
            'employee_profiles_removed': 0,
        }

        # Step 1: Unassign all tasks in shizuha-pulse
        try:
            pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')
            unassign_response = requests.post(
                f'{pulse_url}/internal/users/{user_id}/unassign/',
                timeout=30
            )
            if unassign_response.status_code == 200:
                pulse_data = unassign_response.json()
                deleted_data['tasks_unassigned'] = pulse_data.get('items_unassigned', 0)
                logger.info(f"Unassigned {deleted_data['tasks_unassigned']} tasks from user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to unassign tasks for user {user_id}: {e}")
            # Continue with deletion - tasks can be manually reassigned later

        # Step 2: Remove local memberships in shizuha-admin
        with transaction.atomic():
            # Update employees who report to this user
            EmployeeProfile.objects.filter(
                manager_id=user_id
            ).update(manager_id=None, manager_email=None)

            EmployeeProfile.objects.filter(
                dotted_line_manager_id=user_id
            ).update(dotted_line_manager_id=None, dotted_line_manager_email=None)

            # Update departments where user is head
            Department.objects.filter(head_id=user_id).update(head_id=None, head_email=None)

            # Update teams where user is lead
            Team.objects.filter(lead_id=user_id).update(lead_id=None, lead_email=None)

            # Get organization memberships
            org_memberships = OrganizationMembership.objects.filter(
                user_id=user_id,
                is_active=True
            )

            for membership in org_memberships:
                # Delete team memberships through employee profile
                if hasattr(membership, 'employee_profile') and membership.employee_profile:
                    team_count = TeamMembership.objects.filter(
                        employee_profile=membership.employee_profile
                    ).delete()[0]
                    deleted_data['team_memberships_removed'] += team_count

                    # Delete employee profile
                    membership.employee_profile.delete()
                    deleted_data['employee_profiles_removed'] += 1

            # Delete organization memberships
            deleted_data['organization_memberships_removed'] = org_memberships.count()
            org_memberships.delete()

            logger.info(f"Removed local memberships for user {user_id}: "
                       f"{deleted_data['organization_memberships_removed']} org memberships, "
                       f"{deleted_data['team_memberships_removed']} team memberships")

        # Step 3: Delete user in shizuha-id
        try:
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            headers = {'Authorization': auth_header} if auth_header else {}

            delete_response = requests.delete(
                f'{shizuha_id_url}/internal/admin/users/{user_id}/delete/',
                headers=headers,
                timeout=10
            )
            if delete_response.status_code not in [200, 204]:
                logger.error(f"Failed to delete user {user_id} in Shizuha ID: {delete_response.text}")
                return Response(
                    {'error': 'Failed to delete user from identity service',
                     'partial_cleanup': deleted_data},
                    status=status.HTTP_502_BAD_GATEWAY
                )
            logger.info(f"Deleted user {user_id} from Shizuha ID")
        except Exception as e:
            logger.error(f"Failed to delete user {user_id} from Shizuha ID: {e}")
            return Response(
                {'error': 'Failed to delete user from identity service',
                 'partial_cleanup': deleted_data},
                status=status.HTTP_502_BAD_GATEWAY
            )

        return Response({
            'success': True,
            'message': f'User "{user_info.get("username")}" deleted successfully',
            'deleted_data': deleted_data
        })


class SuperuserUserDetailView(APIView):
    """
    Superuser-only view to get detailed information about a specific user.

    Shows all organizations, projects, departments, and reporting relationships.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        import requests
        import os

        if not request.user.is_superuser:
            return Response(
                {'error': 'You do not have permission to access this resource'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Fetch user info from shizuha-id
        user_info = None
        try:
            shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
            response = requests.get(f'{shizuha_id_url}/internal/users/{user_id}/', timeout=5)
            if response.status_code == 200:
                user_info = response.json()
        except Exception as e:
            logger.warning(f"Failed to fetch user {user_id} from Shizuha ID: {e}")

        if not user_info:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get all organization memberships for this user
        org_memberships = OrganizationMembership.objects.filter(
            user_id=user_id,
            is_active=True
        ).select_related(
            'organization',
            'employee_profile',
            'employee_profile__department',
            'employee_profile__position'
        )

        organizations = []
        for membership in org_memberships:
            org = membership.organization

            # Get employee profile info
            employee_info = None
            if hasattr(membership, 'employee_profile') and membership.employee_profile:
                ep = membership.employee_profile
                # Get direct reports
                direct_reports = EmployeeProfile.objects.filter(
                    manager_id=user_id,
                    membership__organization=org,
                    membership__is_active=True
                ).values('membership__user_id', 'membership__user_email', 'job_title')

                # Get management chain
                management_chain = []
                current = ep
                visited = set()
                while current.manager_id and current.manager_id not in visited:
                    visited.add(current.manager_id)
                    manager_profile = EmployeeProfile.objects.filter(
                        membership__user_id=current.manager_id,
                        membership__organization=org
                    ).select_related('membership').first()
                    if manager_profile:
                        management_chain.append({
                            'user_id': manager_profile.membership.user_id,
                            'email': manager_profile.membership.user_email,
                            'job_title': manager_profile.job_title,
                        })
                        current = manager_profile
                    else:
                        break

                employee_info = {
                    'job_title': ep.job_title,
                    'department': {
                        'id': ep.department.id,
                        'name': ep.department.name,
                        'code': ep.department.code,
                    } if ep.department else None,
                    'position': {
                        'id': ep.position.id,
                        'title': ep.position.title,
                    } if ep.position else None,
                    'manager': {
                        'user_id': ep.manager_id,
                        'email': ep.manager_email,
                    } if ep.manager_id else None,
                    'employment_status': ep.employment_status,
                    'employment_type': ep.employment_type,
                    'bio': ep.bio,
                    'direct_reports': list(direct_reports),
                    'management_chain': management_chain,
                }

            # Fetch project memberships from Pulse (projects are now managed by Pulse)
            projects = []
            try:
                pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')
                auth_header = request.META.get('HTTP_AUTHORIZATION', '')
                headers = {'Authorization': auth_header} if auth_header else {}

                # Get user's projects from Pulse (source of truth for projects)
                pulse_response = requests.get(
                    f'{pulse_url}/projects/',
                    params={'organization': org.id},
                    headers=headers,
                    timeout=5
                )
                if pulse_response.status_code == 200:
                    pulse_data = pulse_response.json()
                    pulse_projects = pulse_data.get('results', pulse_data) if isinstance(pulse_data, dict) else pulse_data

                    # For each project, check if user is a member
                    for project in pulse_projects if isinstance(pulse_projects, list) else []:
                        # Fetch members for this project to see if user is in it
                        try:
                            members_response = requests.get(
                                f'{pulse_url}/projects/{project["id"]}/members/',
                                headers=headers,
                                timeout=5
                            )
                            if members_response.status_code == 200:
                                members_data = members_response.json()
                                members = members_data.get('members', [])
                                # Check if user is a member
                                user_membership = next(
                                    (m for m in members if m.get('user_id') == user_id or m.get('user_email') == user_info.get('email')),
                                    None
                                )
                                if user_membership:
                                    projects.append({
                                        'id': project['id'],
                                        'name': project['name'],
                                        'key': project.get('key', ''),
                                        'role': user_membership.get('role', 'member'),
                                        'source': 'pulse',
                                    })
                        except Exception as e:
                            logger.debug(f"Failed to fetch members for project {project.get('id')}: {e}")
            except Exception as e:
                logger.warning(f"Failed to fetch Pulse projects for org {org.slug}: {e}")

            # Get team memberships in this org
            team_memberships = TeamMembership.objects.filter(
                employee_profile__membership__user_id=user_id,
                team__organization=org,
                is_active=True
            ).select_related('team')

            teams = []
            for tm in team_memberships:
                teams.append({
                    'id': tm.team.id,
                    'name': tm.team.name,
                    'role': tm.role,
                    'team_type': tm.team.team_type,
                })

            organizations.append({
                'id': org.id,
                'name': org.name,
                'slug': org.slug,
                'role': membership.role,
                'joined_at': membership.accepted_at or membership.created_at,
                'employee_profile': employee_info,
                'projects': projects,
                'teams': teams,
            })

        # Fetch tasks assigned to this user from Shizuha Pulse
        assigned_tasks = []
        try:
            pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            headers = {'Authorization': auth_header} if auth_header else {}

            # Use the my_tasks endpoint with user_id parameter (staff can query any user)
            tasks_response = requests.get(
                f'{pulse_url}/items/my_tasks/',
                params={'user_id': user_id},
                headers=headers,
                timeout=10
            )
            if tasks_response.status_code == 200:
                tasks_data = tasks_response.json()
                assigned_tasks = tasks_data.get('items', [])
        except Exception as e:
            logger.warning(f"Failed to fetch tasks for user {user_id} from Pulse: {e}")

        return Response({
            'user': user_info,
            'organizations': organizations,
            'assigned_tasks': assigned_tasks,
        })


class SuperuserDashboardView(APIView):
    """
    Superuser-only Overview payload.

    This is a page-path endpoint. It must not serialize every org/member/
    department row and must not fan out to Pulse per organization — that
    blocked `/admin/superuser` behind an N+1 of 5s timeouts. Counts stay
    local; recent users come from one short ID admin list.
    """
    permission_classes = [permissions.IsAuthenticated]
    ID_USERS_TIMEOUT = 3
    RECENT_USER_LIMIT = 8

    def get(self, request):
        if not request.user.is_superuser:
            emit_boundary_denial(
                request=request,
                service='admin',
                operation='admin.su_dashboard',
                reason='superuser_endpoint',
            )
            return Response(
                {'error': 'You do not have permission to access this resource'},
                status=status.HTTP_403_FORBIDDEN
            )

        total_orgs = Organization.objects.filter(is_active=True).count()
        total_members = OrganizationMembership.objects.filter(is_active=True).count()
        total_departments = Department.objects.filter(is_active=True).count()

        users_data, total_users = self._recent_users(request)

        stats = {
            'total_users': total_users,
            'total_organizations': total_orgs,
            'total_members': total_members,
            'total_departments': total_departments,
            # Pulse project lists live on Pulse. Do not N+1 them here.
            'total_pulse_projects': 0,
        }
        return Response({
            'stats': stats,
            'users': users_data,
            # Keep the key so a rolling old frontend reduce() does not throw.
            'organizations': [],
            'total_users': total_users,
            'total_organizations': total_orgs,
            'active_organizations': total_orgs,
        })

    def _recent_users(self, request):
        import os
        import requests as http_requests

        users_data = []
        total_users = 0
        try:
            shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            response = http_requests.get(
                f'{shizuha_id_url}/internal/admin/users/',
                params={
                    'limit': self.RECENT_USER_LIMIT,
                    'order_by': '-date_joined',
                },
                headers={'Authorization': auth_header} if auth_header else {},
                timeout=self.ID_USERS_TIMEOUT,
            )
            if response.status_code != 200:
                logger.warning(
                    'Failed to fetch users from Shizuha ID: HTTP %s',
                    response.status_code,
                )
                return users_data, total_users

            payload = response.json()
            if isinstance(payload, dict):
                raw_users = payload.get('results') or payload.get('users') or []
                total_users = int(
                    payload.get('count', payload.get('total', len(raw_users))) or 0
                )
            elif isinstance(payload, list):
                raw_users = payload
                total_users = len(raw_users)
            else:
                raw_users = []

            for row in raw_users[:self.RECENT_USER_LIMIT]:
                if not isinstance(row, dict) or row.get('id') is None:
                    continue
                users_data.append({
                    'id': row.get('id'),
                    'username': row.get('username') or '',
                    'email': row.get('email') or '',
                    'is_staff': bool(row.get('is_staff')),
                    'is_superuser': bool(row.get('is_superuser')),
                })
        except Exception as exc:
            logger.warning('Failed to fetch users from Shizuha ID: %s', exc)
        return users_data, total_users


class SuperuserUserListView(APIView):
    """
    Proxy to shizuha-id internal admin API to list users with search/filter.
    Supports: search, is_staff, is_superuser, is_active, order_by, limit, offset.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        import requests as http_requests
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        params = {}
        for key in ('search', 'is_staff', 'is_superuser', 'is_active', 'order_by', 'limit', 'offset'):
            val = request.query_params.get(key)
            if val is not None:
                params[key] = val

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        try:
            resp = http_requests.get(
                f'{shizuha_id_url}/internal/admin/users/',
                params=params,
                headers={'Authorization': auth_header},
                timeout=10,
            )
            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.error(f"Failed to proxy user list to shizuha-id: {e}")
            return Response({'error': 'Failed to reach identity service'}, status=status.HTTP_502_BAD_GATEWAY)


class SuperuserUserCreateView(APIView):
    """
    Proxy to shizuha-id to create a new user (superuser only).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        import requests as http_requests
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        try:
            resp = http_requests.post(
                f'{shizuha_id_url}/internal/admin/users/create/',
                json=request.data,
                headers={'Authorization': auth_header},
                timeout=10,
            )
            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.error(f"Failed to proxy user create to shizuha-id: {e}")
            return Response({'error': 'Failed to reach identity service'}, status=status.HTTP_502_BAD_GATEWAY)


class SuperuserUserUpdateView(APIView):
    """
    Proxy to shizuha-id to update a user (superuser only).
    Supports updating all user fields including password reset.
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, user_id):
        import requests as http_requests
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        try:
            resp = http_requests.patch(
                f'{shizuha_id_url}/internal/admin/users/{user_id}/',
                json=request.data,
                headers={'Authorization': auth_header},
                timeout=10,
            )
            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.error(f"Failed to proxy user update to shizuha-id: {e}")
            return Response({'error': 'Failed to reach identity service'}, status=status.HTTP_502_BAD_GATEWAY)


class SuperuserOrgListView(APIView):
    """
    List all organizations with member counts, plan, and status.
    Supports search by name/slug.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        queryset = Organization.objects.filter(is_active=True).order_by('name')

        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(slug__icontains=search)
            )

        # Annotate member counts
        queryset = queryset.annotate(
            member_count=Count('memberships', filter=Q(memberships__is_active=True))
        )

        # Pagination
        limit = int(request.query_params.get('limit', 50))
        offset = int(request.query_params.get('offset', 0))
        total = queryset.count()

        orgs = queryset[offset:offset + limit]

        results = []
        for org in orgs:
            results.append({
                'id': org.id,
                'name': org.name,
                'slug': org.slug,
                'plan': org.plan,
                'description': org.description,
                'owner_id': org.owner_id,
                'billing_email': org.billing_email,
                'is_active': org.is_active,
                'member_count': org.member_count,
                'created_at': org.created_at,
                'updated_at': org.updated_at,
            })

        return Response({
            'count': total,
            'results': results,
        })


class SuperuserOrgCreateView(APIView):
    """
    Create a new organization (superuser only).
    Auto-creates owner membership.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        import requests as http_requests
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        name = request.data.get('name')
        slug = request.data.get('slug')
        owner_id = request.data.get('owner_id')
        plan = request.data.get('plan', 'free')
        description = request.data.get('description', '')

        if not name or not slug or not owner_id:
            return Response(
                {'error': 'name, slug, and owner_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check slug uniqueness
        if Organization.objects.filter(slug=slug).exists():
            return Response(
                {'error': f'Organization with slug "{slug}" already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify owner exists in shizuha-id
        owner_email = None
        owner_username = None
        try:
            shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
            resp = http_requests.get(f'{shizuha_id_url}/internal/users/{owner_id}/', timeout=5)
            if resp.status_code != 200:
                return Response({'error': 'Owner user not found'}, status=status.HTTP_400_BAD_REQUEST)
            user_data = resp.json()
            owner_email = user_data.get('email')
            owner_username = user_data.get('username', '')
        except Exception as e:
            logger.warning(f"Failed to verify owner {owner_id}: {e}")

        with transaction.atomic():
            org = Organization.objects.create(
                name=name,
                slug=slug,
                owner_id=owner_id,
                plan=plan,
                description=description,
            )

            OrganizationMembership.objects.create(
                organization=org,
                user_id=owner_id,
                user_email=owner_email,
                display_name=owner_username or '',
                role='owner',
                is_pending=False,
                accepted_at=timezone.now(),
            )

        logger.info(f"Superuser {request.user.id} created organization: {slug}")

        return Response({
            'id': org.id,
            'name': org.name,
            'slug': org.slug,
            'plan': org.plan,
            'owner_id': org.owner_id,
            'created_at': org.created_at,
        }, status=status.HTTP_201_CREATED)


class SuperuserOrgUpdateView(APIView):
    """
    Update an organization's fields (superuser only).
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, slug):
        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        try:
            org = Organization.objects.get(slug=slug)
        except Organization.DoesNotExist:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        allowed_fields = ('name', 'description', 'plan', 'billing_email', 'is_active')
        updated = []
        for field in allowed_fields:
            if field in request.data:
                setattr(org, field, request.data[field])
                updated.append(field)

        if updated:
            org.save()
            logger.info(f"Superuser {request.user.id} updated org {slug}: {', '.join(updated)}")

        return Response({
            'id': org.id,
            'name': org.name,
            'slug': org.slug,
            'plan': org.plan,
            'description': org.description,
            'billing_email': org.billing_email,
            'is_active': org.is_active,
            'updated_at': org.updated_at,
        })


class SuperuserOrgDetailView(APIView):
    """
    Full organization detail: members with user info, departments, teams.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        try:
            org = Organization.objects.get(slug=slug)
        except Organization.DoesNotExist:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        # Members with employee profile info
        memberships = OrganizationMembership.objects.filter(
            organization=org, is_active=True
        ).select_related('employee_profile', 'employee_profile__department', 'employee_profile__position')

        members = []
        for m in memberships:
            member = {
                'id': m.id,
                'user_id': m.user_id,
                'user_email': m.user_email,
                'role': m.role,
                'is_pending': m.is_pending,
                'accepted_at': m.accepted_at,
                'created_at': m.created_at,
            }
            if hasattr(m, 'employee_profile') and m.employee_profile:
                ep = m.employee_profile
                member['employee_profile'] = {
                    'job_title': ep.job_title,
                    'department': ep.department.name if ep.department else None,
                    'position': ep.position.title if ep.position else None,
                    'employment_status': ep.employment_status,
                    'employment_type': ep.employment_type,
                }
            members.append(member)

        # Departments
        departments = Department.objects.filter(
            organization=org, is_active=True
        ).order_by('sort_order', 'name')
        dept_data = [{
            'id': d.id,
            'name': d.name,
            'code': d.code,
            'parent_id': d.parent_id,
            'head_id': d.head_id,
            'head_email': d.head_email,
            'employee_count': d.employees.filter(membership__is_active=True).count(),
        } for d in departments]

        # Teams
        teams = Team.objects.filter(
            organization=org, is_active=True
        ).order_by('name')
        team_data = [{
            'id': t.id,
            'name': t.name,
            'team_type': t.team_type,
            'lead_id': t.lead_id,
            'lead_email': t.lead_email,
            'member_count': t.member_count,
        } for t in teams]

        # Service access
        services = OrganizationServiceAccess.objects.filter(organization=org)
        service_data = [{
            'service_slug': s.service_slug,
            'is_enabled': s.is_enabled,
        } for s in services]

        return Response({
            'id': org.id,
            'name': org.name,
            'slug': org.slug,
            'plan': org.plan,
            'description': org.description,
            'billing_email': org.billing_email,
            'owner_id': org.owner_id,
            'is_active': org.is_active,
            'created_at': org.created_at,
            'updated_at': org.updated_at,
            'members': members,
            'departments': dept_data,
            'teams': team_data,
            'services': service_data,
        })


class SuperuserSystemHealthView(APIView):
    """
    Check health of deployed services and infrastructure.

    The target list is intentionally configuration-backed so the Admin dashboard
    follows the deployed topology instead of freezing old compose-era DNS names
    and ports in code. Operators may override the whole list with
    SYSTEM_HEALTH_SERVICES (JSON list of {name, url, enabled, optional, note})
    or individual URLs with SHIZUHA_<SERVICE>_HEALTH_URL.
    """
    permission_classes = [permissions.IsAuthenticated]

    DEFAULT_SERVICE_TARGETS = [
        {
            'name': 'shizuha-id',
            'url_env': 'SHIZUHA_ID_HEALTH_URL',
            'default_url': 'http://localhost:8001/api/health/',
        },
        {
            'name': 'shizuha-pulse',
            'url_env': 'SHIZUHA_PULSE_HEALTH_URL',
            'default_url': 'http://localhost:8002/api/health/',
        },
        {
            'name': 'shizuha-admin',
            'url_env': 'SHIZUHA_ADMIN_HEALTH_URL',
            'default_url': 'http://localhost:8003/api/health/',
        },
        {
            'name': 'shizuha-notes',
            'url_env': 'SHIZUHA_NOTES_HEALTH_URL',
            'default_url': 'http://localhost:8012/api/health/',
        },
        {
            'name': 'shizuha-wiki',
            'url_env': 'SHIZUHA_WIKI_HEALTH_URL',
            'default_url': 'http://localhost:8013/api/health/',
        },
        {
            'name': 'shizuha-mail',
            'url_env': 'SHIZUHA_MAIL_HEALTH_URL',
            'default_url': 'http://localhost:8014/api/health/',
        },
        {
            'name': 'shizuha-inventory',
            'url_env': 'SHIZUHA_INVENTORY_HEALTH_URL',
            'default_url': 'http://localhost:8016/api/health/',
        },
        {
            'name': 'shizuha-drive',
            'url_env': 'SHIZUHA_DRIVE_HEALTH_URL',
            'default_url': 'http://localhost:8018/api/health/',
        },
        {
            'name': 'shizuha-connect',
            'url_env': 'SHIZUHA_CONNECT_HEALTH_URL',
            'default_url': 'http://localhost:8019/api/health/',
        },
        {
            'name': 'shizuha-finance',
            'url_env': 'SHIZUHA_FINANCE_HEALTH_URL',
            'default_url': 'http://localhost:8020/api/health/',
        },
        {
            'name': 'shizuha-books',
            'url_env': 'SHIZUHA_BOOKS_HEALTH_URL',
            'default_url': 'http://localhost:8021/api/health/',
        },
        {
            'name': 'shizuha-agent',
            'url_env': 'SHIZUHA_AGENT_HEALTH_URL',
            'default_url': None,
            'optional': True,
            'note': 'No agent health endpoint is configured.',
        },
        {
            'name': 'shizuha-hr',
            'url_env': 'SHIZUHA_HR_HEALTH_URL',
            'default_url': None,
            'optional': True,
            'note': 'No HR health endpoint is configured.',
        },
        {
            'name': 'shizuha-time',
            'url_env': 'SHIZUHA_TIME_HEALTH_URL',
            'default_url': None,
            'optional': True,
            'note': 'No Time health endpoint is configured.',
        },
    ]

    @classmethod
    def _configured_service_targets(cls):
        import json
        import os

        raw = os.environ.get('SYSTEM_HEALTH_SERVICES')
        if raw:
            try:
                configured = json.loads(raw)
                if isinstance(configured, list):
                    return configured
                logger.warning('SYSTEM_HEALTH_SERVICES must be a JSON list; using defaults')
            except ValueError as exc:
                logger.warning('Invalid SYSTEM_HEALTH_SERVICES JSON: %s; using defaults', exc)

        targets = []
        for target in cls.DEFAULT_SERVICE_TARGETS:
            item = target.copy()
            env_url = os.environ.get(item.get('url_env', ''))
            if env_url:
                item['default_url'] = env_url
                item['enabled'] = True
            targets.append(item)
        return targets

    @staticmethod
    def _looks_like_dns_absence(exc):
        error = str(exc).lower()
        return (
            'name or service not known' in error
            or 'temporary failure in name resolution' in error
            or 'failed to resolve' in error
            or 'nameresolutionerror' in error
            or 'nodename nor servname provided' in error
        )

    @staticmethod
    def _redis_host():
        import os

        return os.environ.get('REDIS_HOST', 'localhost')

    @staticmethod
    def _service_summary(results):
        healthy_count = sum(1 for s in results if s['status'] == 'healthy')
        not_deployed_count = sum(1 for s in results if s['status'] == 'not_deployed')
        unhealthy_count = sum(
            1 for s in results
            if s['status'] not in ('healthy', 'not_deployed')
        )
        return {
            'total': len(results),
            'healthy': healthy_count,
            'unhealthy': unhealthy_count,
            'not_deployed': not_deployed_count,
        }

    @staticmethod
    def _aggregate_status(results, infra):
        """
        Roll component states into the top-level health verdict.

        Optional services that are intentionally not deployed are informational:
        they should not turn an otherwise healthy platform into unknown/degraded.
        """
        service_failures = [
            s for s in results
            if s.get('status') not in ('healthy', 'not_deployed')
        ]
        required_service_failures = [
            s for s in service_failures
            if not s.get('optional')
        ]
        infra_failures = [
            item for item in infra
            if item.get('status') != 'healthy'
        ]

        if infra_failures or required_service_failures:
            return 'unhealthy'
        if service_failures:
            return 'degraded'
        return 'healthy'

    @classmethod
    def _health_payload(cls, results, infra):
        return {
            'status': cls._aggregate_status(results, infra),
            'timestamp': timezone.now().isoformat(),
            'services': results,
            'infrastructure': infra,
            'summary': cls._service_summary(results),
        }

    def _check_service(self, http_requests, target):
        import time

        name = target.get('name')
        url = target.get('url') or target.get('default_url')
        enabled = target.get('enabled', True)
        optional = bool(target.get('optional', False))
        note = target.get('note')

        if not enabled or not url:
            return {
                'name': name,
                'url': url,
                'status': 'not_deployed',
                'status_code': None,
                'response_ms': 0,
                'optional': optional,
                'note': note or 'No health URL is configured for this service.',
            }

        start = time.time()
        try:
            resp = http_requests.get(url, timeout=3)
            elapsed = round((time.time() - start) * 1000)
            return {
                'name': name,
                'url': url,
                'status': 'healthy' if resp.status_code < 500 else 'unhealthy',
                'status_code': resp.status_code,
                'response_ms': elapsed,
                'optional': optional,
            }
        except http_requests.exceptions.Timeout:
            elapsed = round((time.time() - start) * 1000)
            return {
                'name': name,
                'url': url,
                'status': 'timeout',
                'status_code': None,
                'response_ms': elapsed,
                'optional': optional,
            }
        except http_requests.exceptions.ConnectionError as e:
            elapsed = round((time.time() - start) * 1000)
            if optional and self._looks_like_dns_absence(e):
                return {
                    'name': name,
                    'url': url,
                    'status': 'not_deployed',
                    'status_code': None,
                    'response_ms': elapsed,
                    'optional': optional,
                    'note': note or 'Configured optional service is not present in DNS.',
                    'error': str(e),
                }
            return {
                'name': name,
                'url': url,
                'status': 'unreachable',
                'status_code': None,
                'response_ms': elapsed,
                'optional': optional,
                'error': str(e),
            }
        except Exception as e:
            elapsed = round((time.time() - start) * 1000)
            return {
                'name': name,
                'url': url,
                'status': 'unreachable',
                'status_code': None,
                'response_ms': elapsed,
                'optional': optional,
                'error': str(e),
            }

    def get(self, request):
        import requests as http_requests
        import time
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        results = [
            self._check_service(http_requests, target)
            for target in self._configured_service_targets()
        ]

        # Infrastructure checks
        infra = []

        # PostgreSQL
        from django.db import connection
        try:
            start = time.time()
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
            elapsed = round((time.time() - start) * 1000)
            infra.append({'name': 'PostgreSQL', 'status': 'healthy', 'response_ms': elapsed})
        except Exception as e:
            infra.append({'name': 'PostgreSQL', 'status': 'unhealthy', 'error': str(e)})

        # Redis
        try:
            import redis
            start = time.time()
            r = redis.Redis(
                host=self._redis_host(),
                port=int(os.environ.get('REDIS_PORT', 6379)),
                socket_timeout=3,
            )
            r.ping()
            elapsed = round((time.time() - start) * 1000)
            infra.append({'name': 'Redis', 'status': 'healthy', 'response_ms': elapsed})
        except Exception as e:
            infra.append({'name': 'Redis', 'status': 'unhealthy', 'error': str(e)})

        # MinIO
        try:
            start = time.time()
            minio_url = os.environ.get('MINIO_ENDPOINT', 'http://minio:9000')
            resp = http_requests.get(f'{minio_url}/minio/health/live', timeout=3)
            elapsed = round((time.time() - start) * 1000)
            infra.append({
                'name': 'MinIO',
                'status': 'healthy' if resp.status_code == 200 else 'unhealthy',
                'response_ms': elapsed,
            })
        except Exception as e:
            infra.append({'name': 'MinIO', 'status': 'unhealthy', 'error': str(e)})

        return Response(self._health_payload(results, infra))


class OrganizationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for organization management.

    Users can:
    - List organizations they belong to
    - Create new organizations (becomes owner)
    - View/update organizations they're admin/owner of
    - Manage members (owners/admins only)
    """
    queryset = Organization.objects.filter(is_active=True)
    serializer_class = OrganizationSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationPermission]
    lookup_field = 'slug'

    def get_serializer_class(self):
        if self.action == 'create':
            return OrganizationCreateSerializer
        return OrganizationSerializer

    @action(detail=True, methods=['get'], url_path='company-os',
            permission_classes=[permissions.IsAuthenticated])
    def company_os(self, request, slug=None):
        """PLAT-434: read-only Company-OS (mission/vision/strategic bets/values +
        handbook link) for any org. Vision is non-sensitive and exposed to all
        authenticated agents, so this bypasses the membership filter and reads the
        org directly by slug."""
        org = Organization.objects.filter(slug=slug, is_active=True).first()
        if org is None:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(CompanyOSSerializer(org).data)

    def get_queryset(self):
        """Filter to persistent memberships and exact-org active JIT grants."""
        user = self.request.user

        # Auto-resolve pending invitations for this user's email
        self._resolve_pending_invitations(user)

        jit_org_ids = JITElevatedAccessGrant.active_queryset(
            user_id=getattr(user, 'id', None),
            email=getattr(user, 'email', '') or '',
            scope='org.members.add',
        ).filter(
            requested_role__in=('admin', 'owner'),
        ).values('organization_id')

        # Only the exact member-add capability projects its organization into
        # lookup. Other scopes and weaker roles must not disclose the tenant.
        member_filter = (
            Q(memberships__is_active=True)
            & (
                Q(memberships__user_id=user.id)
                | Q(memberships__user_email=user.email)
            )
        )
        qs = Organization.objects.filter(
            member_filter | Q(id__in=jit_org_ids),
            is_active=True
        ).distinct()
        return qs

    def _resolve_pending_invitations(self, user):
        """Auto-resolve any pending invitations for this user's email."""
        username = getattr(user, 'username', None) or ''
        pending_memberships = OrganizationMembership.objects.filter(
            user_email=user.email,
            is_pending=True,
            is_active=True
        )
        for membership in pending_memberships:
            try:
                membership.accept_invitation(user.id, display_name=username)
                logger.info(f"Auto-accepted org invitation for {user.email} to org {membership.organization.slug}")
            except Exception as e:
                logger.warning(f"Failed to auto-accept invitation: {e}")

        # Lazy-populate display_name on existing memberships for this user
        if username:
            OrganizationMembership.objects.filter(
                user_id=user.id,
                is_active=True,
                display_name__isnull=True,
            ).update(display_name=username)
            # Also update if display_name is empty string
            OrganizationMembership.objects.filter(
                user_id=user.id,
                is_active=True,
                display_name='',
            ).update(display_name=username)

    def _ensure_personal_workspace(self, user):
        """Auto-create a personal workspace if user doesn't have one yet."""
        has_personal = Organization.objects.filter(
            memberships__user_id=user.id,
            memberships__is_active=True,
            is_personal=True,
            is_active=True,
        ).exists()
        if has_personal:
            return

        name_part = getattr(user, 'first_name', '') or getattr(user, 'username', '') or 'My'
        with transaction.atomic():
            slug = f"personal-{user.id}"
            if Organization.objects.filter(slug=slug).exists():
                return
            org = Organization.objects.create(
                name=f"{name_part}'s Workspace",
                slug=slug,
                owner_id=user.id,
                plan='free',
                is_personal=True,
            )
            OrganizationMembership.objects.create(
                organization=org,
                user_id=user.id,
                user_email=user.email,
                display_name=getattr(user, 'username', '') or '',
                role='owner',
                is_pending=False,
                accepted_at=timezone.now(),
            )
            logger.info(f"Auto-created personal workspace '{org.slug}' for user {user.id}")

    def list(self, request, *args, **kwargs):
        """List organizations, auto-creating personal workspace if needed."""
        self._ensure_personal_workspace(request.user)
        response = super().list(request, *args, **kwargs)

        # This list is authenticated tenant data and is also the Books
        # bootstrap authority. Never let a browser or intermediary reuse it
        # across sessions or organization memberships.
        patch_cache_control(
            response,
            private=True,
            no_store=True,
            no_cache=True,
            must_revalidate=True,
            max_age=0,
        )
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        patch_vary_headers(response, ['Authorization'])

        return response

    def perform_create(self, serializer):
        """Create organization and add creator as owner (atomic transaction)."""
        with transaction.atomic():
            org = serializer.save(owner_id=self.request.user.id)

            # Add creator as owner member
            OrganizationMembership.objects.create(
                organization=org,
                user_id=self.request.user.id,
                user_email=self.request.user.email,
                display_name=getattr(self.request.user, 'username', '') or '',
                role='owner',
                is_pending=False,
                accepted_at=timezone.now()
            )
            logger.info(f"Organization created: {org.slug} by user {self.request.user.id}")

    def perform_destroy(self, instance):
        """Prevent deletion of personal workspaces."""
        if instance.is_personal:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Cannot delete your personal workspace.")
        super().perform_destroy(instance)

    @action(detail=True, methods=['get', 'post'])
    def members(self, request, slug=None):
        """List or add organization members."""
        org = self.get_object()

        if request.method == 'GET':
            memberships = OrganizationMembership.objects.filter(
                organization=org,
                is_active=True
            )
            serializer = OrganizationMembershipSerializer(memberships, many=True)
            return Response({
                'count': memberships.count(),
                'members': serializer.data
            })

        elif request.method == 'POST':
            # Check if user can manage members
            membership = OrganizationMembership.objects.filter(
                organization=org,
                user_id=request.user.id,
                role__in=['owner', 'admin'],
                is_active=True
            ).first()

            if (
                not membership
                and not request.user.is_superuser
                and not _user_has_active_jit_grant(
                    request, org, scope='org.members.add', min_role='admin'
                )
            ):
                return Response(
                    {'error': 'You do not have permission to add members'},
                    status=status.HTTP_403_FORBIDDEN
                )

            serializer = OrganizationMemberInviteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            user_email = serializer.validated_data['user_email']
            role = serializer.validated_data['role']

            # Check if already a member
            if OrganizationMembership.objects.filter(
                organization=org,
                user_email=user_email
            ).exists():
                return Response(
                    {'error': 'User is already a member'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if user already exists in shizuha-id
            existing_user_id = None
            existing_username = None
            try:
                import os
                import requests
                shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
                response = requests.get(
                    f'{shizuha_id_url}/internal/users/by-email/',
                    params={'email': user_email},
                    timeout=5
                )
                if response.status_code == 200:
                    user_data = response.json()
                    existing_user_id = user_data.get('id')
                    existing_username = user_data.get('username', '')
            except Exception as e:
                logger.warning(f"Failed to lookup user by email: {e}")

            # Auto-accept if user exists OR if requester is superuser
            # Superuser invitations should never be "pending"
            should_auto_accept = existing_user_id is not None or request.user.is_superuser

            if should_auto_accept:
                new_membership = OrganizationMembership.objects.create(
                    organization=org,
                    user_id=existing_user_id,  # May be None for superuser inviting non-existent user
                    user_email=user_email,
                    display_name=existing_username or '',
                    role=role,
                    invited_by_id=request.user.id,
                    invited_at=timezone.now(),
                    accepted_at=timezone.now(),
                    is_pending=False
                )
                if existing_user_id:
                    logger.info(f"Organization member added (auto-accepted): {user_email} to {org.slug}")
                else:
                    logger.info(f"Organization member added by superuser (no user account yet): {user_email} to {org.slug}")
            else:
                # Create pending invitation (user_id is NULL until accepted)
                new_membership = OrganizationMembership.objects.create(
                    organization=org,
                    user_id=None,
                    user_email=user_email,
                    role=role,
                    invited_by_id=request.user.id,
                    invited_at=timezone.now(),
                    is_pending=True
                )
                logger.info(f"Organization invite sent: {user_email} to {org.slug}")
            return Response({
                'message': 'Invitation sent',
                'membership': OrganizationMembershipSerializer(new_membership).data
            }, status=status.HTTP_201_CREATED)

    def _can_remove_member(self, requester, requester_membership, target_membership, org):
        """
        Check if requester can remove target member from the organization.

        Permission Logic:
        | Requester | Can Remove | Cannot Remove |
        |-----------|------------|---------------|
        | Superuser | Anyone (except last owner) | Last owner |
        | Owner | Admins, auditors, members, viewers | Last owner (self if sole) |
        | Admin | Auditors, members, viewers | Owners, other admins |
        | Member/Viewer | Nobody | Everyone |

        Returns: (can_remove: bool, error_message: str or None)
        """
        target_role = target_membership.role
        target_user_id = target_membership.user_id

        # Count owners in the organization
        owner_count = OrganizationMembership.objects.filter(
            organization=org,
            role='owner',
            is_active=True,
            is_pending=False
        ).count()

        # Cannot remove the last owner
        if target_role == 'owner' and owner_count <= 1:
            return False, 'Cannot remove the last owner of the organization'

        # Superuser can remove anyone (except last owner - already checked)
        if requester.is_superuser:
            return True, None

        # No membership means no permission (unless superuser, already checked)
        if not requester_membership:
            return False, 'You do not have permission to remove members'

        requester_role = requester_membership.role

        # Self-removal should use /leave endpoint
        if target_user_id and target_user_id == requester.id:
            return False, 'Use the leave endpoint to remove yourself from the organization'

        # Owners can remove admins, members, viewers (not other owners unless multiple)
        if requester_role == 'owner':
            if target_role == 'owner':
                # Can only remove other owners if there are multiple
                return True, None
            return True, None

        # Admins can remove non-privileged members, including auditors.
        if requester_role == 'admin':
            if target_role in ['auditor', 'member', 'viewer']:
                return True, None
            return False, 'Admins cannot remove owners or other admins'

        # Members and viewers cannot remove anyone
        return False, 'You do not have permission to remove members'

    @action(detail=True, methods=['delete'], url_path='members/(?P<member_id>[^/.]+)')
    def remove_member(self, request, slug=None, member_id=None):
        """
        Remove a member from the organization.

        Permissions:
        - Superusers can remove anyone except the last owner
        - Owners can remove admins, members, viewers
        - Admins can remove members and viewers
        - Members/viewers cannot remove anyone
        - Last owner cannot be removed
        - Self-removal should use /leave endpoint
        """
        org = self.get_object()

        # Get target membership
        try:
            target_membership = OrganizationMembership.objects.get(
                id=member_id,
                organization=org,
                is_active=True
            )
        except OrganizationMembership.DoesNotExist:
            return Response(
                {'error': 'Member not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get requester's membership (may be None for superusers not in org)
        requester_membership = OrganizationMembership.objects.filter(
            organization=org,
            user_id=request.user.id,
            is_active=True
        ).first()

        # Check permissions
        can_remove, error = self._can_remove_member(
            request.user, requester_membership, target_membership, org
        )

        if not can_remove:
            return Response(
                {'error': error},
                status=status.HTTP_403_FORBIDDEN
            )

        # Remove the member
        with transaction.atomic():
            target_email = target_membership.user_email
            target_user_id = target_membership.user_id

            # Clean up employee profile and team memberships if exists
            if hasattr(target_membership, 'employee_profile') and target_membership.employee_profile:
                ep = target_membership.employee_profile
                # Remove team memberships
                TeamMembership.objects.filter(employee_profile=ep).update(
                    is_active=False,
                    left_at=timezone.now()
                )
                # Delete employee profile
                ep.delete()

            # Soft delete the membership
            target_membership.is_active = False
            target_membership.save()

            logger.info(f"Member removed: {target_email} from org {org.slug} by user {request.user.id}")

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def leave(self, request, slug=None):
        """
        Leave an organization (self-removal).

        - Users can leave organizations voluntarily
        - Last owner cannot leave (must transfer ownership first)
        - Cleans up employee profile and team memberships
        """
        org = self.get_object()

        # Get user's membership
        membership = OrganizationMembership.objects.filter(
            organization=org,
            user_id=request.user.id,
            is_active=True
        ).first()

        if not membership:
            return Response(
                {'error': 'You are not a member of this organization'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if user is the last owner
        if membership.role == 'owner':
            owner_count = OrganizationMembership.objects.filter(
                organization=org,
                role='owner',
                is_active=True,
                is_pending=False
            ).count()

            if owner_count <= 1:
                return Response(
                    {'error': 'You are the last owner. Transfer ownership before leaving.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Remove the member
        with transaction.atomic():
            # Clean up employee profile and team memberships if exists
            if hasattr(membership, 'employee_profile') and membership.employee_profile:
                ep = membership.employee_profile
                # Remove team memberships
                TeamMembership.objects.filter(employee_profile=ep).update(
                    is_active=False,
                    left_at=timezone.now()
                )
                # Delete employee profile
                ep.delete()

            # Soft delete the membership
            membership.is_active = False
            membership.save()

            logger.info(f"User {request.user.id} left organization {org.slug}")

        return Response({
            'message': f'Successfully left {org.name}'
        })

    @action(detail=True, methods=['get'])
    def projects(self, request, slug=None):
        """
        Proxy to Pulse API for organization projects.

        Projects are now managed by shizuha-pulse. This endpoint proxies
        requests to the Pulse API for backward compatibility.
        """
        import os
        import requests as http_requests

        org = self.get_object()

        try:
            pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            headers = {'Authorization': auth_header} if auth_header else {}

            response = http_requests.get(
                f'{pulse_url}/projects/',
                params={'organization': org.id},
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                pulse_data = response.json()
                projects_list = pulse_data.get('results', pulse_data) if isinstance(pulse_data, dict) else pulse_data
                return Response({
                    'count': len(projects_list) if isinstance(projects_list, list) else 0,
                    'projects': projects_list
                })
            else:
                return Response(
                    {'error': 'Failed to fetch projects from Pulse', 'status': response.status_code},
                    status=response.status_code
                )
        except Exception as e:
            logger.error(f"Failed to proxy projects request to Pulse: {e}")
            return Response(
                {'error': 'Failed to fetch projects', 'detail': str(e)},
                status=status.HTTP_502_BAD_GATEWAY
            )


# =============================================================================
# HR Hierarchy ViewSets
# =============================================================================

class OrganizationHRMixin:
    """Mixin for HR-related views that need organization context."""

    def get_organization(self):
        """Get organization from URL kwargs.

        The top-level organization list exposes both ``id`` and ``slug``. The
        nested HR routes historically named the path parameter
        ``organization_slug``, but dashboards/truth-audits may pass the visible
        numeric id from ``/organizations/``. Resolve either form so all endpoints
        use the same visibility contract.
        """
        org_ref = self.kwargs.get('organization_slug')
        if not org_ref:
            return None
        try:
            lookup = {'id': int(org_ref)} if str(org_ref).isdigit() else {'slug': org_ref}
            org = Organization.objects.get(is_active=True, **lookup)

            # Verify user has access. ID-15: match membership by user_id OR
            # user_email, exactly like OrganizationPermissions.get_user_organizations
            # (the list endpoint). A normal login token whose membership row is
            # keyed by email (with a null/mismatched user_id) could LIST the org
            # but got a 404 here because this check matched user_id only — the
            # docstring's "same visibility contract" promise was unmet.
            if not self.request.user.is_superuser:
                access_q = Q(user_id=self.request.user.id)
                user_email = (getattr(self.request.user, 'email', '') or '').strip()
                if user_email:
                    access_q |= Q(user_email=user_email)
                membership = OrganizationMembership.objects.filter(
                    access_q,
                    organization=org,
                    is_active=True,
                ).first()
                if not membership:
                    return None
            return org
        except Organization.DoesNotExist:
            return None

    def check_hr_permission(self, org, require_admin=False):
        """Check if user has HR management permission."""
        if self.request.user.is_superuser:
            return True

        membership = OrganizationMembership.objects.filter(
            organization=org,
            user_id=self.request.user.id,
            is_active=True
        ).first()

        if not membership:
            return False

        if require_admin:
            return membership.role in ['owner', 'admin']

        return True


class DepartmentViewSet(OrganizationHRMixin, viewsets.ModelViewSet):
    """
    ViewSet for department management.

    Nested under organization: /organizations/{slug}/departments/
    """
    serializer_class = DepartmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = self.get_organization()
        if not org:
            return Department.objects.none()
        return Department.objects.filter(
            organization=org,
            is_active=True
        ).select_related('parent').order_by('sort_order', 'name')

    def get_serializer_class(self):
        if self.action == 'create':
            return DepartmentCreateSerializer
        if self.action == 'tree':
            return DepartmentTreeSerializer
        return DepartmentSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['organization'] = self.get_organization()
        return context

    def create(self, request, *args, **kwargs):
        org = self.get_organization()
        if not org:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        department = Department.objects.create(
            organization=org,
            **serializer.validated_data
        )

        logger.info(f"Department created: {department.name} in {org.slug}")
        return Response(
            DepartmentSerializer(department).data,
            status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        org = self.get_organization()
        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        org = self.get_organization()
        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        department = self.get_object()

        # Check if department has children
        if department.children.filter(is_active=True).exists():
            return Response(
                {'error': 'Cannot delete department with child departments'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if department has employees
        if department.employees.filter(membership__is_active=True).exists():
            return Response(
                {'error': 'Cannot delete department with assigned employees'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Soft delete
        department.is_active = False
        department.save()
        logger.info(f"Department deleted: {department.name} in {org.slug}")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'])
    def tree(self, request, *args, **kwargs):
        """Get department hierarchy as a tree structure."""
        org = self.get_organization()
        if not org:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get root departments (no parent)
        root_departments = Department.objects.filter(
            organization=org,
            parent__isnull=True,
            is_active=True
        ).order_by('sort_order', 'name')

        serializer = DepartmentTreeSerializer(root_departments, many=True)
        return Response({
            'organization': org.slug,
            'departments': serializer.data
        })

    @action(detail=True, methods=['get'])
    def employees(self, request, *args, **kwargs):
        """List employees in this department."""
        department = self.get_object()
        employees = department.employees.filter(
            membership__is_active=True
        ).select_related('membership', 'position')

        serializer = EmployeeProfileMinimalSerializer(employees, many=True)
        return Response({
            'department': department.name,
            'count': employees.count(),
            'employees': serializer.data
        })


class TeamViewSet(OrganizationHRMixin, viewsets.ModelViewSet):
    """
    ViewSet for team management.

    Nested under organization: /organizations/{slug}/teams/
    """
    serializer_class = TeamSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = self.get_organization()
        if not org:
            return Team.objects.none()
        return Team.objects.filter(
            organization=org,
            is_active=True
        ).select_related('department').order_by('name')

    def get_serializer_class(self):
        if self.action == 'create':
            return TeamCreateSerializer
        return TeamSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['organization'] = self.get_organization()
        # PLS-770: fetch the authoritative Pulse TeamRoster projection once per
        # list/retrieve and hand it to the serializer so summary member counts
        # agree with the detail read's source of truth (authoritative empty
        # included). A degraded/unavailable roster must not break the list — the
        # serializer falls back to local directory counts.
        if self.action in ('list', 'retrieve'):
            try:
                from organizations.services.team_roster_authority import (
                    fetch_authoritative_roster_all,
                )
                context['authoritative_roster_all'] = fetch_authoritative_roster_all()
            except Exception:
                context['authoritative_roster_all'] = None
        return context

    @staticmethod
    def _reject_fleet_agent_write(profile):
        """Reject Admin-local agent placement before any row/grant mutation."""
        email = profile.membership.user_email
        try:
            denial = fleet_agent_write_denial(email)
        except FleetIdentityUnavailable as exc:
            return Response(
                {'error': 'fleet_identity_unavailable', 'detail': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if denial:
            return Response(denial, status=status.HTTP_409_CONFLICT)
        return None

    def _consume_jit_member_add(self, request, team, org):
        """Atomically consume an exact ADR-0048 roster capability."""
        grant_id = request.data.get('jit_grant_id') or request.data.get('grant_id')
        idempotency_key = (
            request.data.get('jit_idempotency_key')
            or request.headers.get('Idempotency-Key')
            or ''
        ).strip()
        if not grant_id:
            # PLAT-5042 §1 / AC1: bare call with an approved-but-uncited grant
            # must not look identical to having no grant at all.
            actor_user_id, actor_email = _actor_identity(request)
            uncited = False
            if actor_user_id is not None:
                uncited = JITElevatedAccessGrant.active_queryset(
                    user_id=actor_user_id,
                    email=actor_email or None,
                    organization=org,
                    scope=JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
                ).exists()
            if uncited:
                return Response(
                    {
                        'error': (
                            'An approved JIT grant exists for this action but was not '
                            'cited. Pass jit_grant_id (and jit_idempotency_key) to consume it.'
                        ),
                        'code': 'jit_grant_not_cited',
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        if not idempotency_key or len(idempotency_key) > 100:
            return Response(
                {'error': 'A JIT idempotency key of at most 100 characters is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            employee_profile_id = int(request.data.get('employee_profile_id'))
        except (TypeError, ValueError):
            return Response(
                {'error': 'employee_profile_id must be an integer'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        role = (request.data.get('role') or 'member').strip()
        profile = EmployeeProfile.objects.select_related('membership').filter(
            pk=employee_profile_id,
            membership__organization=org,
            membership__is_active=True,
            membership__is_pending=False,
        ).first()
        if profile is None or profile.membership.user_id is None:
            return Response({'error': 'Target employee not found'}, status=status.HTTP_404_NOT_FOUND)

        constraints = {
            'organization_id': org.id,
            'team_id': team.id,
            'user_id': profile.membership.user_id,
            'role': role,
        }
        request_digest = JITElevatedAccessGrant.constraint_digest_for(constraints)

        fleet_denial = self._reject_fleet_agent_write(profile)
        if fleet_denial is not None:
            if fleet_denial.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                # Fleet identity registry unavailable — fail closed rather
                # than guessing whether the target is a fleet agent.
                return fleet_denial
            # PLAT-6071 Option A: fleet-agent placement is owned by the Pulse
            # TeamRoster. Admin validates + consumes the JIT grant, then
            # forwards the mutation to Pulse's internal endpoint and consumes
            # the grant only after Pulse confirms.
            return self._consume_jit_fleet_member_add(
                request, team, org, profile, grant_id, idempotency_key,
                role, request_digest,
            )

        with transaction.atomic():
            grant, actor_user_id, actor_email, response = (
                self._load_and_validate_jit_grant(
                    request, org, grant_id, idempotency_key, request_digest,
                    team,
                )
            )
            if response is not None:
                return response

            serializer = TeamMemberAddSerializer(data=request.data, context={'team': team})
            serializer.is_valid(raise_exception=True)
            membership = serializer.save()
            result = TeamMembershipSerializer(membership).data
            return self._consume_jit_grant(
                grant, request, actor_user_id, actor_email,
                idempotency_key, request_digest, result,
            )

    def _load_and_validate_jit_grant(self, request, org, grant_id,
                                     idempotency_key, request_digest, team):
        """Lock + validate a JIT grant for a team-member-add consumption.

        Returns ``(grant, actor_user_id, actor_email, response)``. On success
        ``response`` is None and ``grant`` is ``select_for_update``-locked and
        fully validated for consumption. On failure OR an idempotent replay,
        ``grant`` is None and ``response`` is the Response to return (an error,
        or the stored replay result).
        """
        try:
            grant = JITElevatedAccessGrant.objects.select_for_update().select_related(
                'organization',
            ).get(pk=grant_id)
        except (JITElevatedAccessGrant.DoesNotExist, ValueError):
            return None, None, None, Response(
                {'error': 'JIT grant not found'}, status=status.HTTP_404_NOT_FOUND,
            )

        actor_user_id, actor_email = _actor_identity(request)
        # Immutable subject/resource binding is checked before even an
        # idempotent replay can disclose the stored result.  Lifecycle,
        # policy, expiry, and remaining-use checks intentionally follow
        # the replay lookup below.
        if actor_user_id is None:
            # A null actor is an AUTHENTICATION failure, not an authorization
            # one. Rendering it 403 preserves a weaker form of the same
            # conflation this ticket is about. (PLAT-5042 item 2; note the
            # state is believed unreachable -- a token without a user_id
            # claim 401s earlier -- so this is clarity, not an experiment.)
            return None, None, None, Response(
                {'error': 'Authenticated actor could not be resolved'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if actor_user_id != grant.requester_user_id:
            _audit_jit(
                grant,
                'identity_denied',
                request,
                detail=_jit_identity_evidence(actor_user_id, grant),
            )
            return None, None, None, Response(
                {'error': 'Grant requester identity mismatch'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if (
            grant.scope != JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE
            or grant.organization_id != org.id
        ):
            return None, None, None, Response(
                {'error': 'Grant scope does not authorize this action'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ADR-0048 replay ordering is deliberate: identical committed
        # retries return their stored result even after the one-use grant
        # is exhausted or its policy is later disabled.  A reused key with
        # a different canonical request conflicts.
        prior_use = JITElevatedAccessGrantUse.objects.filter(
            grant=grant,
            idempotency_key=idempotency_key,
        ).first()
        if prior_use is not None:
            if prior_use.request_digest != request_digest:
                return None, None, None, Response(
                    {'error': 'Idempotency key was already used for a different target'},
                    status=status.HTTP_409_CONFLICT,
                )
            return None, None, None, Response(
                prior_use.result, status=status.HTTP_201_CREATED,
            )

        # Lock both policy/target Team rows in stable order before checking
        # their active state; roster/team changes then serialize with this
        # one-action consumption transaction.
        locked_teams = {
            row.id: row
            for row in Team.objects.select_for_update().select_related('organization')
            .filter(id__in=[grant.approver_team_id, grant.target_team_id])
            .order_by('id')
        }
        if grant.approver_team_id in locked_teams:
            grant.approver_team = locked_teams[grant.approver_team_id]
        if grant.target_team_id in locked_teams:
            grant.target_team = locked_teams[grant.target_team_id]
        if not grant.has_complete_current_exact_authority():
            _audit_jit_invariant_failure(
                request,
                code='jit_exact_contract_stale',
                operation='admin.jit.consume',
                organization=org,
                grant=grant,
            )
            return None, None, None, Response(
                {'error': 'Grant policy is incomplete, disabled, or stale'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if grant.status != JITElevatedAccessGrant.STATUS_APPROVED:
            return None, None, None, Response(
                {'error': 'Grant is not approved'}, status=status.HTTP_403_FORBIDDEN,
            )
        if grant.revoked_at is not None or grant.expires_at is None or grant.expires_at <= timezone.now():
            return None, None, None, Response(
                {'error': 'Grant is expired or revoked'}, status=status.HTTP_403_FORBIDDEN,
            )
        if grant.uses_consumed >= grant.max_uses:
            return None, None, None, Response(
                {'error': 'Grant use limit is exhausted'}, status=status.HTTP_403_FORBIDDEN,
            )
        if grant.constraint_digest != request_digest:
            return None, None, None, Response(
                {'error': 'Grant target constraints do not match'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return grant, actor_user_id, actor_email, None

    def _consume_jit_grant(self, grant, request, actor_user_id, actor_email,
                           idempotency_key, request_digest, result):
        """Consume one grant use and record the audit trail (ADR-0048)."""
        consumed_at = timezone.now()
        next_use_count = grant.uses_consumed + 1
        auto_revoked = next_use_count >= grant.max_uses
        update_values = {
            'uses_consumed': next_use_count,
            'updated_at': consumed_at,
        }
        if auto_revoked:
            update_values.update({
                'status': JITElevatedAccessGrant.STATUS_REVOKED,
                'revoked_at': consumed_at,
            })
        JITElevatedAccessGrant.objects.filter(pk=grant.pk).update(**update_values)
        grant.uses_consumed += 1
        if auto_revoked:
            grant.status = JITElevatedAccessGrant.STATUS_REVOKED
            grant.revoked_at = consumed_at
        JITElevatedAccessGrantUse.objects.create(
            grant=grant,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result=result,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
        )
        _audit_jit(
            grant,
            'consumed',
            request,
            detail={
                'constraint_digest': request_digest,
                'idempotency_key_digest': JITElevatedAccessGrant._canonical_digest(idempotency_key),
                'use_number': grant.uses_consumed,
                'auto_revoked': auto_revoked,
            },
        )
        if auto_revoked:
            _audit_jit(
                grant,
                'auto_revoked',
                request,
                source='consumer',
                detail={'reason': 'use limit exhausted'},
            )
        return Response(result, status=status.HTTP_201_CREATED)

    def _consume_jit_fleet_member_add(self, request, team, org, profile,
                                      grant_id, idempotency_key, role,
                                      request_digest):
        """PLAT-6071 Option A: forward a fleet-agent roster mutation to Pulse
        and consume the JIT grant only after Pulse confirms.

        Admin stays the single authority for JIT grants (validate + consume +
        TTL + idempotency + audit); Pulse stays the single authority for roster
        membership. A stale ``expected_version`` fails WITHOUT consuming the
        grant or partially mutating either store (acceptance #4).
        """
        with transaction.atomic():
            grant, actor_user_id, actor_email, response = (
                self._load_and_validate_jit_grant(
                    request, org, grant_id, idempotency_key, request_digest,
                    team,
                )
            )
            if response is not None:
                return response

            email = (profile.membership.user_email or '').strip().lower()
            forward_result, forward_response = self._forward_fleet_roster_mutation(
                org=org,
                team_name=team.name,
                email=email,
                idempotency_key=idempotency_key,
                actor_email=actor_email or '',
            )
            if forward_response is not None:
                # Pulse did not confirm the mutation (e.g. stale version 409).
                # Leave the grant approved — no partial mutation, no consumption.
                return forward_response

            return self._consume_jit_grant(
                grant, request, actor_user_id, actor_email,
                idempotency_key, request_digest, forward_result,
            )

    def _forward_fleet_roster_mutation(self, *, org, team_name, email,
                                       idempotency_key, actor_email):
        """Forward a fleet-agent roster mutation to Pulse's internal endpoint.

        Returns ``(result_dict, error_response)``. On success ``error_response``
        is None. A stale ``expected_version`` (409) or any Pulse non-2xx leaves
        the grant unconsumed (``error_response`` set).
        """
        import os
        import requests
        import uuid as _uuid

        base = os.environ.get(
            'SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api',
        ).rstrip('/')
        # command_id is derived deterministically from the JIT idempotency key
        # so a retry of the same consume replays the same Pulse receipt.
        command_id = str(_uuid.uuid5(
            _uuid.NAMESPACE_URL, f'jit:fleet-member-add:{idempotency_key}',
        ))

        # Read the current CAS version for this org/team from the internal
        # roster (PLS-745 contract: writes are keyed on version).
        try:
            roster_resp = requests.get(f'{base}/internal/team-roster/', timeout=5)
            roster_resp.raise_for_status()
            roster_payload = roster_resp.json()
        except (requests.RequestException, ValueError) as exc:
            return None, Response(
                {'error': 'pulse_team_roster_unavailable', 'detail': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        teams = roster_payload.get('teams', []) if isinstance(roster_payload, dict) else []
        canonical = _canonical_team(team_name)
        slug = (org.slug or '').strip().lower()
        version = 0
        for row in teams:
            if not isinstance(row, dict):
                continue
            if int(row.get('organization_id') or 0) != int(org.id):
                continue
            if (row.get('organization_slug') or '').strip().lower() != slug:
                continue
            if _canonical_team(row.get('team_name')) != canonical:
                continue
            version = int(row.get('version') or 0)
            break

        payload = {
            'command_id': command_id,
            'action': 'add',
            'organization_id': org.id,
            'organization_slug': org.slug,
            'team_name': team_name,
            'email': email,
            'expected_version': version,
            'actor_email': actor_email,
        }
        try:
            resp = requests.post(
                f'{base}/internal/team-roster/members/',
                json=payload,
                timeout=10,
            )
        except requests.RequestException as exc:
            return None, Response(
                {'error': 'pulse_team_roster_unavailable', 'detail': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if resp.status_code == 409:
            # Stale expected_version — Pulse did NOT mutate. Leave the grant
            # approved; the client can re-read the roster and retry.
            return None, Response(
                {'error': 'pulse_roster_version_conflict', 'detail': resp.text[:500]},
                status=status.HTTP_409_CONFLICT,
            )
        if resp.status_code != 200:
            return None, Response(
                {'error': 'pulse_roster_mutation_failed', 'detail': resp.text[:500]},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        try:
            result = resp.json()
        except ValueError:
            result = {'detail': resp.text[:500]}
        return result, None

    def create(self, request, *args, **kwargs):
        org = self.get_organization()
        if not org:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        team = Team.objects.create(
            organization=org,
            **serializer.validated_data
        )

        logger.info(f"Team created: {team.name} in {org.slug}")
        return Response(
            TeamSerializer(team).data,
            status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        org = self.get_organization()
        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        org = self.get_organization()
        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        team = self.get_object()
        team.is_active = False
        team.save()
        logger.info(f"Team deleted: {team.name} in {org.slug}")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get', 'post'])
    def members(self, request, *args, **kwargs):
        """List or add team members."""
        team = self.get_object()
        org = self.get_organization()

        if request.method == 'GET':
            try:
                fleet_agents = fetch_fleet_agent_emails()
                authoritative_members = fetch_authoritative_team_members(
                    organization_id=org.id,
                    organization_slug=org.slug,
                    team_name=team.name,
                )
            except FleetIdentityUnavailable as exc:
                return Response(
                    {'error': 'team_roster_unavailable', 'detail': str(exc)},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            local_memberships = list(
                team.memberships.filter(is_active=True).select_related(
                    'employee_profile__membership'
                )
            )
            directory_rows = []
            for membership in local_memberships:
                email = (
                    membership.employee_profile.membership.user_email or ''
                ).strip().lower()
                if email in fleet_agents:
                    # Legacy fleet edges are quarantined from reads.  Their
                    # presence in this table never overlays authoritative empty.
                    continue
                row = dict(TeamMembershipSerializer(membership).data)
                row.update({'source': 'admin-directory', 'routing_member': False})
                directory_rows.append(row)

            profiles = {
                profile.membership.user_email.strip().lower(): profile
                for profile in EmployeeProfile.objects.select_related('membership').filter(
                    membership__organization=org,
                    membership__user_email__in=authoritative_members,
                    membership__is_active=True,
                )
            }
            routing_rows = []
            for email in sorted(authoritative_members):
                profile = profiles.get(email)
                routing_rows.append({
                    'id': None,
                    'routing_identity': f'pulse:{email}',
                    'team': team.id,
                    'team_name': team.name,
                    'employee_profile': profile.id if profile else None,
                    'employee_name': profile.display_name if profile else email.split('@')[0],
                    'employee_email': email,
                    'employee_title': profile.effective_job_title if profile else '',
                    'role': 'member',
                    'joined_at': None,
                    'left_at': None,
                    'is_active': True,
                    'source': 'pulse-team-roster',
                    'routing_member': True,
                })
            rows = routing_rows + directory_rows
            return Response({
                'team': team.name,
                'count': len(rows),
                'routing_count': len(routing_rows),
                'directory_count': len(directory_rows),
                'authoritative_empty': not routing_rows,
                'members': rows,
            })

        elif request.method == 'POST':
            if not self.check_hr_permission(org, require_admin=True):
                return self._consume_jit_member_add(request, team, org)

            try:
                profile = EmployeeProfile.objects.select_related('membership').get(
                    pk=request.data.get('employee_profile_id'),
                    membership__organization=org,
                    membership__is_active=True,
                )
            except (EmployeeProfile.DoesNotExist, ValueError, TypeError):
                profile = None
            if profile is not None:
                fleet_denial = self._reject_fleet_agent_write(profile)
                if fleet_denial is not None:
                    return fleet_denial

            serializer = TeamMemberAddSerializer(
                data=request.data,
                context={'team': team}
            )
            serializer.is_valid(raise_exception=True)
            membership = serializer.save()

            logger.info(f"Team member added: {membership.employee_profile.display_name} to {team.name}")
            return Response(
                TeamMembershipSerializer(membership).data,
                status=status.HTTP_201_CREATED
            )

    @action(detail=True, methods=['delete'], url_path='members/(?P<member_id>[^/.]+)')
    def remove_member(self, request, member_id=None, *args, **kwargs):
        """Remove a member from the team."""
        team = self.get_object()
        org = self.get_organization()

        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        try:
            membership = TeamMembership.objects.get(
                id=member_id,
                team=team,
                is_active=True
            )
            fleet_denial = self._reject_fleet_agent_write(membership.employee_profile)
            if fleet_denial is not None:
                return fleet_denial
            membership.is_active = False
            membership.left_at = timezone.now()
            membership.save()
            logger.info(f"Team member removed from {team.name}")
            return Response(status=status.HTTP_204_NO_CONTENT)
        except TeamMembership.DoesNotExist:
            return Response({'error': 'Member not found'}, status=status.HTTP_404_NOT_FOUND)


class PositionViewSet(OrganizationHRMixin, viewsets.ModelViewSet):
    """
    ViewSet for position (job title) management.

    Nested under organization: /organizations/{slug}/positions/
    """
    serializer_class = PositionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = self.get_organization()
        if not org:
            return Position.objects.none()
        return Position.objects.filter(
            organization=org,
            is_active=True
        ).select_related('department').order_by('level', 'title')

    def get_serializer_class(self):
        if self.action == 'create':
            return PositionCreateSerializer
        return PositionSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['organization'] = self.get_organization()
        return context

    def create(self, request, *args, **kwargs):
        org = self.get_organization()
        if not org:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        position = Position.objects.create(
            organization=org,
            **serializer.validated_data
        )

        logger.info(f"Position created: {position.title} in {org.slug}")
        return Response(
            PositionSerializer(position).data,
            status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        org = self.get_organization()
        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        org = self.get_organization()
        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        position = self.get_object()

        # Check if position is in use
        if position.employees.filter(membership__is_active=True).exists():
            return Response(
                {'error': 'Cannot delete position that is assigned to employees'},
                status=status.HTTP_400_BAD_REQUEST
            )

        position.is_active = False
        position.save()
        logger.info(f"Position deleted: {position.title} in {org.slug}")
        return Response(status=status.HTTP_204_NO_CONTENT)


class EmployeeProfileViewSet(OrganizationHRMixin, viewsets.ModelViewSet):
    """
    ViewSet for employee profile management.

    Nested under organization: /organizations/{slug}/employees/
    """
    serializer_class = EmployeeProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = self.get_organization()
        if not org:
            return EmployeeProfile.objects.none()

        queryset = EmployeeProfile.objects.filter(
            membership__organization=org,
            membership__is_active=True
        ).select_related(
            'membership', 'membership__organization',
            'department', 'position'
        ).prefetch_related('team_memberships__team')

        # Filter by department
        department_id = self.request.query_params.get('department')
        if department_id:
            queryset = queryset.filter(department_id=department_id)

        # Filter by employment status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(employment_status=status_filter)

        # Filter by employment type
        type_filter = self.request.query_params.get('type')
        if type_filter:
            queryset = queryset.filter(employment_type=type_filter)

        # Filter by manager
        manager_id = self.request.query_params.get('manager')
        if manager_id:
            queryset = queryset.filter(manager_id=manager_id)

        # Search by email or employee_id
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(membership__user_email__icontains=search) |
                Q(employee_id__icontains=search) |
                Q(job_title__icontains=search)
            )

        return queryset.order_by('membership__user_email')

    def get_serializer_class(self):
        if self.action == 'create':
            return EmployeeProfileCreateSerializer
        if self.action in ['update', 'partial_update']:
            return EmployeeProfileUpdateSerializer
        if self.action == 'list':
            return EmployeeProfileMinimalSerializer
        return EmployeeProfileSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['organization'] = self.get_organization()
        return context

    def create(self, request, *args, **kwargs):
        org = self.get_organization()
        if not org:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()

        logger.info(f"Employee profile created: {profile.membership.user_email} in {org.slug}")
        return Response(
            EmployeeProfileSerializer(profile).data,
            status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        org = self.get_organization()
        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        org = self.get_organization()
        if not self.check_hr_permission(org, require_admin=True):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get'])
    def direct_reports(self, request, *args, **kwargs):
        """Get direct reports for this employee."""
        profile = self.get_object()
        reports = profile.get_direct_reports()
        serializer = EmployeeProfileMinimalSerializer(reports, many=True)
        return Response({
            'manager': profile.display_name,
            'count': reports.count(),
            'direct_reports': serializer.data
        })

    @action(detail=True, methods=['get'])
    def management_chain(self, request, *args, **kwargs):
        """Get management chain (all managers up to CEO)."""
        profile = self.get_object()
        chain = profile.get_management_chain()
        serializer = EmployeeProfileMinimalSerializer(chain, many=True)
        return Response({
            'employee': profile.display_name,
            'chain_length': len(chain),
            'management_chain': serializer.data
        })


class OrgChartViewSet(OrganizationHRMixin, viewsets.ViewSet):
    """
    ViewSet for organization chart data.

    Nested under organization: /organizations/{slug}/org-chart/
    """
    permission_classes = [permissions.IsAuthenticated]

    # PLAT-527 (F4): map Pulse status slugs → workload bucket, matching
    # OrgChartSnapshotView._bucket() in shizuha-tasks so per-node counts
    # are consistent across both UIs.
    _F4_SLUG_BUCKET = {
        'open': 'open', 'todo': 'open', 'pending': 'open', 'unstarted': 'open',
        'backlog': 'backlog', 'scheduled': 'scheduled',
        'blocked': 'blocked', 'waiting': 'blocked', 'on_hold': 'blocked', 'stalled': 'blocked',
        'in_review': 'in_review', 'review': 'in_review', 'awaiting_merge': 'in_review',
        'awaiting_review': 'in_review', 'in_review_architect': 'in_review', 'verification': 'in_review',
        'in_progress': 'in_progress', 'started': 'in_progress', 'active': 'in_progress', 'doing': 'in_progress',
    }
    _F4_CAT_BUCKET = {
        'todo': 'open', 'open': 'open', 'backlog': 'backlog', 'scheduled': 'scheduled',
        'in_progress': 'in_progress',
        'blocked': 'blocked',
        'in_review': 'in_review', 'review': 'in_review',
    }

    def _f4_bucket(self, slug, category=None):
        return self._F4_SLUG_BUCKET.get(slug) or self._F4_CAT_BUCKET.get(category, 'open')

    def _fetch_workload(self, org, request):
        """Fetch per-member task workload counts from Pulse in two bulk calls."""
        import requests as _http
        import os
        from datetime import datetime, timezone as _tz

        emails = list(
            EmployeeProfile.objects.filter(
                membership__organization=org,
                membership__is_active=True,
            ).values_list('membership__user_email', flat=True)
        )
        if not emails:
            return {}

        workload = {
            e: {
                'open': 0, 'in_progress': 0, 'in_review': 0, 'blocked': 0,
                'scheduled': 0, 'backlog': 0, 'completed': 0, 'overdue': 0,
            }
            for e in emails
        }
        pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        headers = {'Authorization': auth_header} if auth_header else {}
        email_param = ','.join(emails)
        today = datetime.now(_tz.utc).date().isoformat()

        # Call 1: all active tasks for org members — one request, no per-node queries.
        try:
            resp = _http.get(
                f'{pulse_url}/items/',
                params={'mode': 'task', 'is_active': 'true', 'assignee_email': email_param, 'page_size': '500'},
                headers=headers, timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('results', data) if isinstance(data, dict) else data
                for item in (items if isinstance(items, list) else []):
                    email = (item.get('assignee_email') or '').strip().lower()
                    if email not in workload:
                        continue
                    bucket = self._f4_bucket(item.get('status', ''), item.get('status_category'))
                    workload[email][bucket] += 1
                    due = (item.get('due_date') or '')[:10]
                    if due and due < today:
                        workload[email]['overdue'] += 1
        except Exception as exc:
            logger.warning('OrgChart F4 workload (active): Pulse call failed: %s', exc)

        # Call 2: completed tasks in the last 30 days.
        try:
            resp = _http.get(
                f'{pulse_url}/items/',
                params={
                    'mode': 'task', 'status_category': 'done', 'done_recent_days': '30',
                    'assignee_email': email_param, 'page_size': '500',
                },
                headers=headers, timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('results', data) if isinstance(data, dict) else data
                for item in (items if isinstance(items, list) else []):
                    email = (item.get('assignee_email') or '').strip().lower()
                    if email in workload:
                        workload[email]['completed'] += 1
        except Exception as exc:
            logger.warning('OrgChart F4 workload (completed): Pulse call failed: %s', exc)

        return workload

    def _compute_dept_workload(self, org, workload):
        """Aggregate per-member workload into per-department totals (including sub-departments)."""
        _KEYS = ('open', 'in_progress', 'in_review', 'blocked', 'scheduled', 'backlog', 'completed', 'overdue')

        # Direct member workload per department ID
        emp_depts = EmployeeProfile.objects.filter(
            membership__organization=org,
            membership__is_active=True,
            department__isnull=False,
        ).values_list('membership__user_email', 'department_id')

        dept_direct = {}
        for email, dept_id in emp_depts:
            if email not in workload:
                continue
            if dept_id not in dept_direct:
                dept_direct[dept_id] = {k: 0 for k in _KEYS}
            wl = workload[email]
            for k in _KEYS:
                dept_direct[dept_id][k] += wl.get(k, 0)

        # Build parent map for ancestor propagation
        all_depts = list(Department.objects.filter(
            organization=org, is_active=True,
        ).values('id', 'parent_id'))
        parent_of = {d['id']: d['parent_id'] for d in all_depts}

        # Initialize totals with direct counts for each dept
        dept_workload = {d['id']: {k: 0 for k in _KEYS} for d in all_depts}
        for dept_id, counts in dept_direct.items():
            if dept_id in dept_workload:
                for k in _KEYS:
                    dept_workload[dept_id][k] += counts[k]

        # Propagate direct counts up to all ancestors (no double-counting)
        for dept_id, counts in dept_direct.items():
            ancestor = parent_of.get(dept_id)
            while ancestor is not None:
                if ancestor in dept_workload:
                    for k in _KEYS:
                        dept_workload[ancestor][k] += counts[k]
                ancestor = parent_of.get(ancestor)

        # Stringify keys for JSON (dept IDs are ints, JS needs them as strings to key a lookup)
        return {str(k): v for k, v in dept_workload.items()}

    def list(self, request, *args, **kwargs):
        """Get full org chart data."""
        org = self.get_organization()
        if not org:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get root employees (no manager)
        root_employees = EmployeeProfile.objects.filter(
            membership__organization=org,
            membership__is_active=True,
            membership__user_id__isnull=False,
            manager_id__isnull=True
        ).select_related('membership', 'department')

        # Get department tree
        root_departments = Department.objects.filter(
            organization=org,
            parent__isnull=True,
            is_active=True
        ).order_by('sort_order', 'name')

        # Get total employee count
        total_employees = EmployeeProfile.objects.filter(
            membership__organization=org,
            membership__is_active=True,
            membership__user_id__isnull=False
        ).count()

        # PLAT-3192: `departments` is the ROOT-department tree, so its length is
        # the root count, not the org's department count. Ship the flat total
        # (same query as org-chart/stats) so the UI header can't conflate them.
        total_departments = Department.objects.filter(
            organization=org,
            is_active=True
        ).count()

        # PLAT-527 (F4): per-member workload from Pulse (two bulk calls, no per-node requests).
        workload = self._fetch_workload(org, request)
        dept_workload = self._compute_dept_workload(org, workload)

        return Response({
            'organization': OrganizationSerializer(org).data,
            'root_employees': OrgChartNodeSerializer(root_employees, many=True).data,
            'departments': DepartmentTreeSerializer(root_departments, many=True).data,
            'total_employees': total_employees,
            'total_departments': total_departments,
            'workload': workload,
            'department_workload': dept_workload,
        })

    @action(detail=False, methods=['get'], url_path='by-department', url_name='by-department')
    def by_department(self, request, *args, **kwargs):
        """Get org chart filtered by department."""
        org = self.get_organization()
        if not org:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        department_id = request.query_params.get('department_id')
        if not department_id:
            return Response({'error': 'department_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            department = Department.objects.get(
                id=department_id,
                organization=org,
                is_active=True
            )
        except Department.DoesNotExist:
            return Response({'error': 'Department not found'}, status=status.HTTP_404_NOT_FOUND)

        # Get department head or top employees in department
        employees = EmployeeProfile.objects.filter(
            membership__organization=org,
            membership__is_active=True,
            membership__user_id__isnull=False,
            department=department
        ).select_related('membership', 'department')

        return Response({
            'department': DepartmentSerializer(department).data,
            'employees': OrgChartNodeSerializer(employees, many=True).data,
            'count': employees.count()
        })

    @action(detail=False, methods=['get'], url_path='by_department', url_name='by-department-legacy')
    def by_department_legacy(self, request, *args, **kwargs):
        """Backward-compatible alias for the historical underscore route."""
        return self.by_department(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def stats(self, request, *args, **kwargs):
        """Get organization hierarchy statistics."""
        org = self.get_organization()
        if not org:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        # Aggregate statistics
        total_employees = EmployeeProfile.objects.filter(
            membership__organization=org,
            membership__is_active=True
        ).count()

        total_departments = Department.objects.filter(
            organization=org,
            is_active=True
        ).count()

        total_teams = Team.objects.filter(
            organization=org,
            is_active=True
        ).count()

        # Employment status breakdown
        status_breakdown = EmployeeProfile.objects.filter(
            membership__organization=org,
            membership__is_active=True
        ).values('employment_status').annotate(count=Count('id'))

        # Employment type breakdown
        type_breakdown = EmployeeProfile.objects.filter(
            membership__organization=org,
            membership__is_active=True
        ).values('employment_type').annotate(count=Count('id'))

        # Department size breakdown
        dept_sizes = Department.objects.filter(
            organization=org,
            is_active=True
        ).annotate(
            employee_count=Count('employees', filter=Q(employees__membership__is_active=True))
        ).values('name', 'employee_count').order_by('-employee_count')[:10]

        return Response({
            'organization': org.slug,
            'total_employees': total_employees,
            'total_departments': total_departments,
            'total_teams': total_teams,
            'status_breakdown': {item['employment_status']: item['count'] for item in status_breakdown},
            'type_breakdown': {item['employment_type']: item['count'] for item in type_breakdown},
            'largest_departments': list(dept_sizes)
        })


# =============================================================================
# Service Access Management Views
# =============================================================================

class SuperuserServiceListView(APIView):
    """
    List all services with per-org enablement counts (platform superuser only).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        # Get per-org enablement counts from OrganizationServiceAccess
        service_stats = {}
        for access in OrganizationServiceAccess.objects.filter(is_enabled=True):
            service_stats.setdefault(access.service_slug, 0)
            service_stats[access.service_slug] += 1

        # Fetch full service catalog from shizuha-id so all services appear
        # (even those not yet granted to any org)
        import os, requests as http_requests
        shizuha_id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        catalog = {}
        try:
            resp = http_requests.get(
                f"{shizuha_id_url}/auth/admin/services/",
                headers={"Authorization": request.META.get("HTTP_AUTHORIZATION", "")},
                timeout=10,
            )
            if resp.status_code == 200:
                for svc in resp.json():
                    catalog[svc['slug']] = svc
        except Exception:
            pass  # Fall back to local data only

        # Merge: catalog services + any local-only slugs
        all_slugs = sorted(set(list(catalog.keys()) + list(service_stats.keys())))
        result = []
        for slug in all_slugs:
            entry = {
                'service_slug': slug,
                'slug': slug,
                'enabled_org_count': service_stats.get(slug, 0),
            }
            if slug in catalog:
                entry.update({
                    'name': catalog[slug].get('display_name', slug),
                    'is_default_enabled': catalog[slug].get('is_default_enabled', False),
                    'requires_approval': catalog[slug].get('requires_approval', False),
                    'is_active': catalog[slug].get('is_active', True),
                    'user_count': catalog[slug].get('enabled_user_count'),
                })
            result.append(entry)
        return Response(result)


class SuperuserOrgServicesView(APIView):
    """
    Get or modify an org's enabled services (platform superuser only).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        try:
            org = Organization.objects.get(slug=slug)
        except Organization.DoesNotExist:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        access_list = OrganizationServiceAccess.objects.filter(organization=org)
        return Response({
            'organization': slug,
            'services': OrganizationServiceAccessSerializer(access_list, many=True).data,
        })

    def post(self, request, slug):
        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        try:
            org = Organization.objects.get(slug=slug)
        except Organization.DoesNotExist:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = OrganizationServiceToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        slugs = serializer.validated_data['service_slugs']
        action = serializer.validated_data['action']

        if action == 'grant':
            for svc_slug in slugs:
                OrganizationServiceAccess.objects.update_or_create(
                    organization=org,
                    service_slug=svc_slug,
                    defaults={
                        'is_enabled': True,
                        'granted_by_id': request.user.id,
                    },
                )
        else:
            OrganizationServiceAccess.objects.filter(
                organization=org,
                service_slug__in=slugs,
            ).update(is_enabled=False)

        access_list = OrganizationServiceAccess.objects.filter(organization=org)
        return Response({
            'organization': slug,
            'services': OrganizationServiceAccessSerializer(access_list, many=True).data,
        })


class SuperuserUserServicesProxyView(APIView):
    """
    Proxy to shizuha-id admin API for user-level service management (platform superuser only).
    """
    permission_classes = [permissions.IsAuthenticated]

    def _proxy(self, request, user_id, method='get', data=None):
        import requests as http_requests
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        url = f'{id_url}/auth/admin/users/{user_id}/services/'
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        try:
            if method == 'get':
                resp = http_requests.get(url, headers={'Authorization': auth_header}, timeout=10)
            else:
                resp = http_requests.post(url, json=data, headers={'Authorization': auth_header}, timeout=10)

            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.error(f"Failed to proxy user services to shizuha-id: {e}")
            return Response({'error': 'Failed to reach identity service'}, status=status.HTTP_502_BAD_GATEWAY)

    def get(self, request, user_id):
        return self._proxy(request, user_id, 'get')

    def post(self, request, user_id):
        return self._proxy(request, user_id, 'post', request.data)


class SuperuserAccessRequestsProxyView(APIView):
    """
    Proxy to shizuha-id for access request management (platform superuser only).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        import requests as http_requests
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        params = dict(request.query_params)

        try:
            resp = http_requests.get(
                f'{id_url}/auth/admin/requests/',
                params=params,
                headers={'Authorization': auth_header},
                timeout=10,
            )
            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.error(f"Failed to proxy access requests to shizuha-id: {e}")
            return Response({'error': 'Failed to reach identity service'}, status=status.HTTP_502_BAD_GATEWAY)


class SuperuserAccessRequestReviewProxyView(APIView):
    """
    Proxy to shizuha-id for reviewing a specific access request (platform superuser only).
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        import requests as http_requests
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        try:
            resp = http_requests.patch(
                f'{id_url}/auth/admin/requests/{pk}/',
                json=request.data,
                headers={'Authorization': auth_header},
                timeout=10,
            )
            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.error(f"Failed to proxy request review to shizuha-id: {e}")
            return Response({'error': 'Failed to reach identity service'}, status=status.HTTP_502_BAD_GATEWAY)


class SuperuserPendingUsersProxyView(APIView):
    """
    Proxy to shizuha-id for listing pending user approvals (platform superuser only).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        import requests as http_requests
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        try:
            resp = http_requests.get(
                f'{id_url}/auth/admin/users/pending/',
                headers={'Authorization': auth_header},
                timeout=10,
            )
            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.error(f"Failed to proxy pending users to shizuha-id: {e}")
            return Response({'error': 'Failed to reach identity service'}, status=status.HTTP_502_BAD_GATEWAY)


class SuperuserPendingUsersCountProxyView(APIView):
    """
    Proxy to shizuha-id for pending user approval count (platform superuser only).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        import requests as http_requests
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        try:
            resp = http_requests.get(
                f'{id_url}/auth/admin/users/pending/count/',
                headers={'Authorization': auth_header},
                timeout=10,
            )
            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.error(f"Failed to proxy pending users count to shizuha-id: {e}")
            return Response({'error': 'Failed to reach identity service'}, status=status.HTTP_502_BAD_GATEWAY)


class SuperuserUserApprovalProxyView(APIView):
    """
    Proxy to shizuha-id for approving/denying a user account (platform superuser only).
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, user_id):
        import requests as http_requests
        import os

        if not request.user.is_superuser:
            return Response({'error': 'Superuser access required'}, status=status.HTTP_403_FORBIDDEN)

        id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        try:
            resp = http_requests.patch(
                f'{id_url}/auth/admin/users/{user_id}/approve/',
                json=request.data,
                headers={'Authorization': auth_header},
                timeout=10,
            )
            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.error(f"Failed to proxy user approval to shizuha-id: {e}")
            return Response({'error': 'Failed to reach identity service'}, status=status.HTTP_502_BAD_GATEWAY)


class OrgServiceListView(APIView):
    """
    List an org's enabled services (for org members).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        try:
            org = Organization.objects.get(slug=slug)
        except Organization.DoesNotExist:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        # Verify membership
        if not request.user.is_superuser:
            is_member = OrganizationMembership.objects.filter(
                organization=org, user_id=request.user.id, is_active=True
            ).exists()
            if not is_member:
                return Response({'error': 'Not a member of this organization'}, status=status.HTTP_403_FORBIDDEN)

        access_list = OrganizationServiceAccess.objects.filter(
            organization=org,
        ).order_by('service_slug')
        return Response({
            'organization': slug,
            'services': [serialize_org_service(access) for access in access_list],
        })


class OrgMemberServicesView(APIView):
    """
    Org admin: view and manage member service access.
    """
    permission_classes = [permissions.IsAuthenticated]

    # Keep the cross-service fan-out finite even for unexpectedly large orgs.
    # The member list is page-bounded, so every member remains observable via
    # offset pagination without making one request fan out across the whole org.
    MEMBER_PAGE_LIMIT = 32
    IDENTITY_LOOKUP_WORKERS = 8
    IDENTITY_LOOKUP_TIMEOUT = 3

    def _check_admin(self, request, org):
        """Check that request user is org admin/owner or platform superuser."""
        if request.user.is_superuser:
            return True
        membership = OrganizationMembership.objects.filter(
            organization=org,
            user_id=request.user.id,
            role__in=['owner', 'admin'],
            is_active=True,
        ).first()
        return membership is not None

    def _member_service_slugs(self, id_url, auth_header, user_id):
        """Read a member's effective grants from ID's canonical admin API."""
        import requests as http_requests

        resp = http_requests.get(
            f'{id_url}/auth/admin/users/{user_id}/services/',
            headers={'Authorization': auth_header},
            timeout=self.IDENTITY_LOOKUP_TIMEOUT,
        )
        if resp.status_code != 200:
            raise RuntimeError(f'identity service returned {resp.status_code}')
        payload = resp.json()
        if not isinstance(payload, dict) or 'enabled_services' not in payload:
            raise ValueError('identity response is missing enabled_services')
        if payload.get('user_id') != user_id:
            raise ValueError('identity response user does not match request')
        enabled_services = payload['enabled_services']
        if not isinstance(enabled_services, list) or any(
            not isinstance(slug, str) or not slug
            for slug in enabled_services
        ):
            raise ValueError('identity enabled_services must be a list of slugs')
        return set(enabled_services)

    def get(self, request, slug):
        """List members' service access within this org."""
        import os

        try:
            org = Organization.objects.get(slug=slug)
        except Organization.DoesNotExist:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        if not self._check_admin(request, org):
            return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

        # Get org's enabled services
        org_services = set(
            OrganizationServiceAccess.objects.filter(
                organization=org, is_enabled=True
            ).values_list('service_slug', flat=True)
        )

        try:
            limit = min(
                max(int(request.query_params.get('limit', self.MEMBER_PAGE_LIMIT)), 1),
                self.MEMBER_PAGE_LIMIT,
            )
            offset = max(int(request.query_params.get('offset', 0)), 0)
        except (TypeError, ValueError):
            return Response(
                {'error': 'limit and offset must be integers'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Page before crossing the service boundary. This makes the maximum
        # lookup count and latency deterministic while preserving a path to
        # every member instead of permanently skipping rows past a hard cap.
        member_qs = OrganizationMembership.objects.filter(
            organization=org, is_active=True
        ).order_by('user_email', 'id')
        count = member_qs.count()
        members = list(member_qs[offset:offset + limit])

        result = []
        pending_lookups = []
        for m in members:
            entry = {
                'user_id': m.user_id,
                'user_email': m.user_email,
                'role': m.role,
            }
            # PLAT-4927: grants live in shizuha-id, so a listing without them
            # cannot verify that a grant landed. Fail soft per member — one
            # identity error degrades that row visibly (services=null +
            # services_error) instead of hiding the whole org or claiming
            # "no grants".
            if m.user_id is None:
                entry['services'] = None
                entry['services_error'] = 'identity lookup skipped: missing user id'
            else:
                pending_lookups.append((m.user_id, entry))
            result.append(entry)

        id_url = os.environ.get(
            'SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api'
        )
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if pending_lookups:
            workers = min(self.IDENTITY_LOOKUP_WORKERS, len(pending_lookups))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_entries = {
                    executor.submit(
                        self._member_service_slugs,
                        id_url,
                        auth_header,
                        user_id,
                    ): (user_id, entry)
                    for user_id, entry in pending_lookups
                }
                for future in as_completed(future_entries):
                    user_id, entry = future_entries[future]
                    try:
                        user_slugs = future.result()
                        entry['services'] = sorted(user_slugs & org_services)
                    except ValueError as e:
                        logger.error(
                            f"Invalid identity service response for user {user_id}: {e}"
                        )
                        entry['services'] = None
                        entry['services_error'] = 'identity service response invalid'
                    except Exception as e:
                        logger.error(
                            f"Failed to fetch service grants for user {user_id}: {e}"
                        )
                        entry['services'] = None
                        entry['services_error'] = 'identity service unavailable'

        return Response({
            'organization': slug,
            'org_services': sorted(org_services),
            'count': count,
            'limit': limit,
            'offset': offset,
            'next_offset': (
                offset + len(members)
                if offset + len(members) < count
                else None
            ),
            'members': result,
        })

    def post(self, request, slug, user_id):
        """Grant/revoke service access for a member within org's allowed services."""
        import requests as http_requests
        import os

        try:
            org = Organization.objects.get(slug=slug)
        except Organization.DoesNotExist:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        if not self._check_admin(request, org):
            return Response({'error': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

        # Verify the target user is a member
        if not OrganizationMembership.objects.filter(
            organization=org, user_id=user_id, is_active=True
        ).exists():
            return Response({'error': 'User is not a member of this organization'}, status=status.HTTP_404_NOT_FOUND)

        serializer = MemberServiceAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        slugs = serializer.validated_data['service_slugs']
        action = serializer.validated_data['action']

        # Validate org has these services
        org_services = set(
            OrganizationServiceAccess.objects.filter(
                organization=org, is_enabled=True
            ).values_list('service_slug', flat=True)
        )
        invalid = set(slugs) - org_services
        if invalid:
            return Response(
                {'error': f'Organization does not have access to: {", ".join(invalid)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Proxy to shizuha-id
        id_url = os.environ.get('SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        try:
            resp = http_requests.post(
                f'{id_url}/auth/admin/users/{user_id}/services/',
                json={'service_slugs': slugs, 'action': action},
                headers={'Authorization': auth_header},
                timeout=10,
            )
            return Response(resp.json(), status=resp.status_code)
        except Exception as e:
            logger.error(f"Failed to proxy member service access to shizuha-id: {e}")
            return Response({'error': 'Failed to reach identity service'}, status=status.HTTP_502_BAD_GATEWAY)
