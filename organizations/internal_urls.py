"""
Internal API URLs for service-to-service communication.

Note: Project-related internal APIs now proxy to shizuha-pulse, which is
the source of truth for projects. Organization membership checks remain here.
"""
import os
import logging
import re
import requests as http_requests

from django.urls import path
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

from django.db import transaction
from django.utils import timezone

from .models import Organization, OrganizationMembership, OrganizationServiceAccess, JITElevatedAccessGrant
from .serializers import OrganizationSerializer
from .internal_auth import InternalServicePermission, HiveSignedInternalPermission
from .membership_v2 import ProjectMembershipResolveV2View  # PLAT-5343 slice 1
from . import security_events
from .services.permissions import PermissionService

logger = logging.getLogger(__name__)


def _pulse_proxy_timeout():
    """Connect/read budget for proxying to Pulse — deliberately under the caller's.

    PLAT-5338: this used to be `timeout=10`, which inverted the budget. The only
    caller of the project-memberships endpoint is shizuha-id's token mint, and it
    gives up after 1.0s. Meanwhile gunicorn here serves :8003 from a small fixed
    worker pool, so a proxy call blocking for 10s on a slow Pulse holds a worker
    for ~10x longer than anyone is still waiting for the answer. While workers are
    held, every other request to :8003 queues behind them — including the
    kubelet's /api/health/ probe, which times out at 3s (readiness) and 5s
    (liveness). That is how a Pulse slowdown became admin liveness kills: a health
    endpoint that does no I/O at all was measured at 9.8s, just under this timeout.

    A budget under the caller's is also what makes failing closed useful: the
    view below answers a Pulse timeout with a typed 503 while shizuha-id is
    still listening, so the mint is refused and retried. At timeout=10 the
    caller had already given up and stamped an empty `project_ids` claim nine
    seconds earlier, and nothing admin returned could change that.
    """
    return (
        float(os.environ.get('SHIZUHA_PULSE_CONNECT_TIMEOUT', '0.25')),
        float(os.environ.get('SHIZUHA_PULSE_READ_TIMEOUT', '0.5')),
    )


# The other Pulse proxies in this module are not on the token-mint path, so they
# keep a generous READ budget — but the connect phase is bounded, because a bare
# `timeout=10` scalar applies to EACH phase independently: a Pulse that is slow
# to accept connections could hold an admin worker for up to 20s on one request.
# Connecting to an in-cluster Service is a sub-50ms operation when it works at
# all, so 0.5s is ~10x margin and never trips on a healthy path.
PULSE_PROXY_CONNECT_TIMEOUT = 0.5
PULSE_PROXY_READ_TIMEOUT = 10.0
PULSE_PROXY_TIMEOUT = (PULSE_PROXY_CONNECT_TIMEOUT, PULSE_PROXY_READ_TIMEOUT)


def _derive_workspace_name(display_name, email):
    """"<User>'s Workspace" — prefer a real display name, else the email local part."""
    base = (display_name or '').strip()
    if not base and email:
        base = email.split('@', 1)[0]
    base = base or 'My'
    return f"{base}'s Workspace"


def ensure_personal_workspace(user_id, email=None, display_name=None):
    """Idempotently guarantee a user has their personal workspace org.

    Canonical single implementation (operator 2026-07-11: every user gets a
    "<User>'s Workspace"). Keyed by owner membership + the stable slug
    personal-<user_id>, so it is safe to call from any path (JWT-claim mint,
    org list, signup hook, backfill). Returns the Organization or None.
    """
    existing = Organization.objects.filter(
        memberships__user_id=user_id,
        memberships__is_active=True,
        is_personal=True,
        is_active=True,
    ).first()
    if existing and (display_name or email):
        # Self-heal an AUTO-GENERATED name once we have a better display name.
        # Auto forms: the legacy "My Workspace" default and the email-local-part
        # fallback ("<prefix>'s Workspace"). A user's genuinely custom name is
        # never in this set, so it is preserved.
        auto_forms = {'My Workspace'}
        if email:
            auto_forms.add(_derive_workspace_name('', email))
        if existing.name in auto_forms:
            better = _derive_workspace_name(display_name, email)
            if better not in ("My's Workspace",) and better != existing.name:
                existing.name = better
                existing.save(update_fields=['name'])
                logger.info("self-healed personal workspace %s -> %r", existing.slug, better)
    if existing:
        return existing
    slug = f"personal-{user_id}"
    with transaction.atomic():
        org = Organization.objects.select_for_update().filter(slug=slug).first()
        if org is None:
            org = Organization.objects.create(
                name=_derive_workspace_name(display_name, email),
                slug=slug,
                owner_id=user_id,
                plan='free',
                is_personal=True,
            )
        OrganizationMembership.objects.get_or_create(
            organization=org,
            user_id=user_id,
            defaults=dict(
                user_email=email or '',
                display_name=display_name or '',
                role='owner',
                is_pending=False,
                accepted_at=timezone.now(),
            ),
        )
    logger.info("ensure_personal_workspace: %s ready for user %s", org.slug, user_id)
    return org


class InternalPermissionCheckView(APIView):
    """
    Check permissions for internal service-to-service calls.

    Note: Project permissions now redirect to Pulse API.
    """
    permission_classes = [InternalServicePermission]

    def post(self, request):
        user_id = request.data.get('user_id')
        resource_type = request.data.get('resource_type')
        resource_id = request.data.get('resource_id')
        action = request.data.get('action', 'browse')

        if not all([user_id, resource_type, resource_id]):
            return Response(
                {'error': 'user_id, resource_type, and resource_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        result = PermissionService.check_permission(
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action
        )

        return Response(result)


class InternalUserOrganizationsView(APIView):
    """
    Get organizations for a user (internal API).
    Auto-creates a personal workspace if the user has no organizations.
    """
    permission_classes = [InternalServicePermission]

    def get(self, request, user_id):
        user_email = request.query_params.get('email')
        # Canonical "<User>'s Workspace" invariant (shared helper).
        try:
            ensure_personal_workspace(
                user_id, email=user_email,
                display_name=request.query_params.get('name') or None,
            )
        except Exception:
            logger.exception("ensure_personal_workspace failed for user %s (organizations)", user_id)
        organizations = PermissionService.get_user_organizations(user_id, user_email)

        return Response({
            'count': organizations.count(),
            'organizations': OrganizationSerializer(organizations, many=True).data
        })


class InternalUserProjectsView(APIView):
    """
    Get projects for a user (internal API).

    Proxies to shizuha-pulse which is the source of truth for projects.
    """
    permission_classes = [InternalServicePermission]

    def get(self, request, user_id):
        user_email = request.query_params.get('email')
        organization_id = request.query_params.get('organization_id')

        try:
            pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')

            params = {'user_id': user_id}
            if organization_id:
                params['organization'] = organization_id

            response = http_requests.get(
                f'{pulse_url}/projects/',
                params=params,
                timeout=PULSE_PROXY_TIMEOUT
            )

            if response.status_code == 200:
                return Response(response.json())
            else:
                return Response(
                    {'error': 'Failed to fetch projects from Pulse'},
                    status=response.status_code
                )
        except Exception as e:
            logger.error(f"Failed to proxy projects request to Pulse: {e}")
            return Response(
                {'error': 'Failed to fetch projects', 'detail': str(e)},
                status=status.HTTP_502_BAD_GATEWAY
            )


class InternalProjectView(APIView):
    """
    Get project by ID (internal API).

    Proxies to shizuha-pulse which is the source of truth for projects.
    """
    permission_classes = [InternalServicePermission]

    def get(self, request, project_id):
        try:
            pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')

            response = http_requests.get(
                f'{pulse_url}/projects/{project_id}/',
                timeout=PULSE_PROXY_TIMEOUT
            )

            if response.status_code == 200:
                return Response(response.json())
            elif response.status_code == 404:
                return Response(
                    {'error': 'Project not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            else:
                return Response(
                    {'error': 'Failed to fetch project from Pulse'},
                    status=response.status_code
                )
        except Exception as e:
            logger.error(f"Failed to proxy project request to Pulse: {e}")
            return Response(
                {'error': 'Failed to fetch project', 'detail': str(e)},
                status=status.HTTP_502_BAD_GATEWAY
            )


class InternalOrganizationView(APIView):
    """
    Get organization by ID or slug (internal API).
    """
    permission_classes = [InternalServicePermission]

    def get(self, request, org_identifier):
        try:
            # Try as ID first, then as slug
            if org_identifier.isdigit():
                org = Organization.objects.get(id=int(org_identifier))
            else:
                org = Organization.objects.get(slug=org_identifier)
            return Response(OrganizationSerializer(org).data)
        except Organization.DoesNotExist:
            return Response(
                {'error': 'Organization not found'},
                status=status.HTTP_404_NOT_FOUND
            )


# HIVE-2715: same slug grammar the hive saga enforces
# (claws/models.py ORG_TEMPLATE_SLUG_RE) — symmetric charset guard (SCS-229
# doctrine): server-side validation, never trust the caller's slug as-is.
ORG_SLUG_RE = re.compile(r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$')


def _hive_provisioning_provenance(operation_id: str) -> dict:
    """Refuse-by-default marker proving an org was minted by THIS surface.

    The saga-minted org carries provisioning provenance in its settings JSON;
    the DELETE path (saga deprovision, HIVE-2697 cleanup contract) refuses any
    org that lacks it.
    """
    return {'service': 'shizuha-hive', 'operation_id': operation_id}


class InternalOrgCreateView(APIView):
    """POST — create-or-attach an organization (HIVE-2715 / HIVE-320 id_org leg).

    Hive-scoped provisioning surface with the SAME fail-closed signed envelope
    as the HIVE-671 membership mutations (``HiveSignedInternalPermission``):
    ``X-Internal-Service: shizuha-hive`` + token + X-Hive-* HMAC + durable
    nonce + ``operation_id`` bound into the signed body. This endpoint is the
    least-privilege provisioning surface — it never accepts a tenant JWT as
    proof and grants nothing beyond org + owner membership.

    Idempotent + saga-resumable: keyed on the unique slug, so a crash after the
    side effect but before the caller records the result replays to the SAME
    org. Replay with the SAME (slug, name, owner_id) returns 200 with the
    existing row; a slug reused for different immutable fields is a 409
    conflict, mirroring the saga's ``ProvisioningIdempotencyConflict``. Owner
    membership is get_or_create-keyed (org, user_id) and never elevates an
    existing member's role (HIVE-671 pattern).
    """

    def get_permissions(self):
        return [HiveSignedInternalPermission()]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        operation_id = str(getattr(request, 'hive_operation_id', '') or '').strip()
        name = str(data.get('name') or '').strip()
        slug = str(data.get('slug') or '').strip().lower()
        try:
            owner_id = int(data.get('owner_id'))
        except (TypeError, ValueError):
            return Response({'error': 'owner_id (int) is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not name:
            return Response({'error': 'name is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not slug or not ORG_SLUG_RE.match(slug):
            return Response(
                {'error': 'slug must match ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        owner_email = str(data.get('owner_email') or '').strip()
        owner_username = str(data.get('owner_username') or '').strip()
        existing = Organization.objects.filter(slug=slug).first()
        if existing is not None:
            immutable_conflict = (
                existing.name != name
                or (existing.owner_id and existing.owner_id != owner_id)
            )
            if immutable_conflict:
                return Response(
                    {'error': f'Organization slug "{slug}" already exists for a different provisioning request.'},
                    status=status.HTTP_409_CONFLICT,
                )
            membership, membership_created = OrganizationMembership.objects.get_or_create(
                organization=existing,
                user_id=owner_id,
                defaults=dict(
                    user_email=owner_email,
                    display_name=owner_username,
                    role='owner',
                    is_pending=False,
                    is_active=True,
                    accepted_at=timezone.now(),
                    source_operation_id=operation_id,
                ),
            )
            return Response(
                {
                    'id': existing.id,
                    'name': existing.name,
                    'slug': existing.slug,
                    'plan': existing.plan,
                    'owner_id': existing.owner_id,
                    'created': False,
                    'owner_membership_created': membership_created,
                    'owner_membership_role': membership.role,
                    'operation_id': operation_id,
                },
                status=status.HTTP_200_OK,
            )

        settings_payload = dict(existing.settings or {}) if existing else {}
        with transaction.atomic():
            org = Organization.objects.create(
                name=name,
                slug=slug,
                owner_id=owner_id,
                plan=str(data.get('plan') or 'free'),
                description=str(data.get('description') or ''),
                settings={
                    **settings_payload,
                    'provisioning': _hive_provisioning_provenance(operation_id),
                },
            )
            OrganizationMembership.objects.create(
                organization=org,
                user_id=owner_id,
                user_email=owner_email,
                display_name=owner_username,
                role='owner',
                is_pending=False,
                is_active=True,
                accepted_at=timezone.now(),
                source_operation_id=operation_id,
            )
        logger.info(
            'hive-provisioning created organization: %s (operation_id=%s)', slug, operation_id,
        )
        return Response(
            {
                'id': org.id,
                'name': org.name,
                'slug': org.slug,
                'plan': org.plan,
                'owner_id': org.owner_id,
                'created': True,
                'operation_id': operation_id,
            },
            status=status.HTTP_201_CREATED,
        )


class InternalOrgDeleteView(APIView):
    """DELETE — saga teardown of a saga-minted organization (HIVE-2715).

    The Hive-2697 cleanup contract extended to the new resource class: only an
    org PROVABLY minted by this provisioning surface (settings.provisioning
    provenance marker) may be torn down, and only through the signed envelope.
    Refuse-by-default on everything else (hard 409 with a structured detail).
    """

    def get_permissions(self):
        return [HiveSignedInternalPermission()]

    def post(self, request, org_id):
        operation_id = str(getattr(request, 'hive_operation_id', '') or '').strip()
        try:
            org = Organization.objects.get(id=int(org_id))
        except (Organization.DoesNotExist, ValueError, TypeError):
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        provenance = (org.settings or {}).get('provisioning') or {}
        if provenance.get('service') != 'shizuha-hive':
            return Response(
                {
                    'error': 'Refusing to delete: organization was not minted by the Hive provisioning surface.',
                    'organization_id': org.id,
                    'slug': org.slug,
                },
                status=status.HTTP_409_CONFLICT,
            )
        # Never tear down an org that gained members beyond the saga-minted
        # owner row — real activity must win over fixture cleanup (the saga
        # refuses such runs hive-side; the server enforces it too).
        member_count = OrganizationMembership.objects.filter(
            organization=org, is_active=True,
        ).count()
        if member_count > 1:
            return Response(
                {
                    'error': 'Refusing to delete: organization has active members beyond the minted owner row.',
                    'organization_id': org.id,
                    'member_count': member_count,
                },
                status=status.HTTP_409_CONFLICT,
            )
        org.delete()
        logger.info(
            'hive-provisioning deleted organization: %s (operation_id=%s)',
            org.slug, operation_id or provenance.get('operation_id'),
        )
        return Response(
            {'status': 'deleted', 'organization_id': int(org_id), 'operation_id': operation_id},
            status=status.HTTP_200_OK,
        )


class InternalNextItemKeyView(APIView):
    """
    Get next item key for a project (internal API).

    Proxies to shizuha-pulse which manages projects now.
    """
    permission_classes = [InternalServicePermission]

    def post(self, request, project_id):
        try:
            pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')

            response = http_requests.post(
                f'{pulse_url}/projects/{project_id}/next_item_key/',
                timeout=PULSE_PROXY_TIMEOUT
            )

            if response.status_code == 200:
                return Response(response.json())
            elif response.status_code == 404:
                return Response(
                    {'error': 'Project not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            else:
                return Response(
                    {'error': 'Failed to get next item key from Pulse'},
                    status=response.status_code
                )
        except Exception as e:
            logger.error(f"Failed to proxy next_item_key request to Pulse: {e}")
            return Response(
                {'error': 'Failed to get next item key', 'detail': str(e)},
                status=status.HTTP_502_BAD_GATEWAY
            )


class InternalOrgMembershipCheckView(APIView):
    def get_permissions(self):
        if self.request.method == 'DELETE':
            return [HiveSignedInternalPermission()]
        return [InternalServicePermission()]
    """
    Check if a user is a member of an organization (internal API).
    Returns membership details including role.
    """
    permission_classes = [InternalServicePermission]

    def get(self, request, org_id, user_id):
        """Check membership by user_id and org_id."""
        user_email = request.query_params.get('email')

        # Build query
        from django.db.models import Q
        q_filter = Q(user_id=user_id)
        if user_email:
            q_filter |= Q(user_email=user_email)

        membership = OrganizationMembership.objects.filter(
            q_filter,
            organization_id=org_id,
            is_active=True
        ).first()

        if membership:
            return Response({
                'is_member': True,
                'role': membership.role,
                'user_id': membership.user_id,
                'user_email': membership.user_email,
                'organization_id': org_id,
                'is_pending': membership.is_pending,
            })
        else:
            return Response({
                'is_member': False,
                'organization_id': org_id,
                'user_id': user_id,
            })


    def delete(self, request, org_id, user_id):
        """Revoke membership created by Hive personal-agent connectivity (HIVE-671).

        Requires X-Hive-Operation-Id matching create-time hive_op: notes provenance.
        Foreign/pre-existing memberships without that provenance are left untouched.
        """
        data = request.data if isinstance(getattr(request, 'data', None), dict) else {}
        operation_id = (
            str(getattr(request, 'hive_operation_id', '') or '').strip()
            or str(data.get('operation_id') or '').strip()
        )
        if not operation_id:
            return Response(
                {'error': 'operation_id required', 'code': 'operation_id_required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership = OrganizationMembership.objects.filter(
            organization_id=org_id,
            user_id=user_id,
            is_active=True,
        ).first()
        if membership is None:
            return Response({
                'status': 'absent',
                'already_revoked': True,
                'organization_id': org_id,
                'user_id': user_id,
            }, status=status.HTTP_200_OK)
        stored = str(getattr(membership, 'source_operation_id', '') or '')
        if not stored or stored != operation_id:
            return Response(
                {
                    'error': 'membership_not_hive_owned',
                    'code': 'membership_not_hive_owned',
                    'organization_id': org_id,
                    'user_id': user_id,
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        membership.is_active = False
        membership.save(update_fields=['is_active'])
        return Response({
            'status': 'revoked',
            'organization_id': org_id,
            'user_id': user_id,
            'operation_id': operation_id,
        }, status=status.HTTP_200_OK)


class InternalOrgMembersView(APIView):
    """
    Get organization members by org ID (internal API).
    Supports optional search filtering.
    POST (HIVE-671) requires Hive signed envelope.
    """
    def get_permissions(self):
        if self.request.method == 'POST':
            return [HiveSignedInternalPermission()]
        return [InternalServicePermission()]

    def post(self, request, org_id):
        """Idempotently add a user to an organization (internal API).

        HIVE-620/624: used to make a user's PERSONAL AGENT a member of the
        owner's personal workspace, so owner↔own-agent DMs pass the CON-129
        shared-org gate WITHOUT any tenancy exemption. Keyed on (org, user_id) so
        repeated calls are safe. Never elevates an existing member's role.
        """
        try:
            org = Organization.objects.get(id=org_id, is_active=True)
        except Organization.DoesNotExist:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            user_id = int(data.get('user_id'))
        except (TypeError, ValueError):
            return Response({'error': 'user_id (int) is required'}, status=status.HTTP_400_BAD_REQUEST)
        role = str(data.get('role') or 'member').strip() or 'member'
        operation_id = str(getattr(request, 'hive_operation_id', '') or data.get('operation_id') or '').strip()
        defaults = dict(
            user_email=str(data.get('user_email') or '').strip(),
            display_name=str(data.get('display_name') or '').strip(),
            role=role,
            is_pending=False,
            is_active=True,
            accepted_at=timezone.now(),
        )
        if operation_id:
            defaults['source_operation_id'] = operation_id
        membership, created = OrganizationMembership.objects.get_or_create(
            organization=org,
            user_id=user_id,
            defaults=defaults,
        )
        if not created and not membership.is_active:
            # HIVE-671 revi P1: do not silently reopen inactive/withdrawn rows.
            # Only exact same-operation receipt is idempotent success.
            stored_op = str(getattr(membership, 'source_operation_id', '') or '')
            if operation_id and stored_op and stored_op == operation_id:
                return Response(
                    {
                        'status': 'exists',
                        'created': False,
                        'already_applied': True,
                        'organization_id': org.id,
                        'user_id': user_id,
                        'role': membership.role,
                        'operation_id': operation_id,
                        'is_active': False,
                    },
                    status=status.HTTP_200_OK,
                )
            return Response(
                {
                    'error': 'membership_inactive_conflict',
                    'code': 'membership_inactive_conflict',
                    'organization_id': org.id,
                    'user_id': user_id,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                'status': 'created' if created else 'exists',
                'created': bool(created),
                'organization_id': org.id,
                'user_id': user_id,
                'role': membership.role,
                'operation_id': operation_id or None,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def get(self, request, org_id):
        """Get all members of an organization, optionally filtered by search."""
        search = request.query_params.get('search', '').strip()

        try:
            org = Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            return Response(
                {'error': 'Organization not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        memberships = OrganizationMembership.objects.filter(
            organization=org,
            is_active=True
        )

        # Apply search filter if provided (searches by email)
        if search:
            memberships = memberships.filter(user_email__icontains=search)

        # This internal list is an authorization/control-plane projection.  Its
        # consumers need membership identity and role, not a fresh profile read.
        # Resolving every name synchronously through Shizuha ID made this an
        # O(member-count) chain of HTTP requests (up to five seconds each).  The
        # primary organization consequently exceeded Hive's bounded repair
        # window and left the natural org-membership reconciler permanently red.
        #
        # Keep the response shape stable while deriving the display value from
        # Admin's stored membership projection.  Profile-rich user interfaces
        # use the public member APIs; this internal endpoint must remain bounded
        # to its two local database reads.
        members = []
        for m in memberships.only(
            'user_id', 'user_email', 'display_name', 'role', 'is_pending'
        ):
            user_name = (
                (m.display_name or '').strip()
                or (m.user_email.split('@')[0] if m.user_email else 'Unknown')
            )
            members.append({
                'user_id': m.user_id,
                'user_email': m.user_email,
                'user_name': user_name,
                'role': m.role,
                'is_pending': m.is_pending,
            })

        return Response({
            'count': len(members),
            'members': members
        })


class InternalOrgServicesView(APIView):
    """
    Get enabled service slugs for an organization (internal API).
    """
    permission_classes = [InternalServicePermission]

    def get(self, request, org_id):
        try:
            org = Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        enabled_slugs = list(
            OrganizationServiceAccess.objects.filter(
                organization=org, is_enabled=True
            ).values_list('service_slug', flat=True)
        )
        return Response({
            'organization_id': org_id,
            'services': enabled_slugs,
        })


class InternalUserMembershipsView(APIView):
    """
    Return a user's active org memberships as a compact {org_id: role} dict.

    Used by shizuha-id to stamp the `organization_memberships` claim onto
    newly minted JWTs so downstream services (pulse, connect, wiki, drive)
    can resolve tenant-scoped role checks without an admin-service round-trip
    per request. Matches the multi-tenant RBAC pattern used by Linear / WorkOS.
    """
    permission_classes = [InternalServicePermission]

    def get(self, request, user_id):
        user_email = request.query_params.get('email') or None
        # Guarantee the personal workspace exists so no user's JWT claim is ever
        # empty (operator 2026-07-11: "no org" must not show; every user has a
        # "<User>'s Workspace"). Idempotent; self-heals on every token mint.
        try:
            ensure_personal_workspace(
                user_id, email=user_email,
                display_name=request.query_params.get('name') or None,
            )
        except Exception:
            logger.exception("ensure_personal_workspace failed for user %s (memberships)", user_id)
        q = Q(user_id=user_id)
        if user_email:
            q |= Q(user_email=user_email)
        memberships = OrganizationMembership.objects.filter(
            q,
            is_active=True,
            organization__is_active=True,
        ).values_list('organization_id', 'role')
        # If the same user_id+email appears in two rows for one org (can
        # happen during account merges), keep the highest role. Role order:
        # owner > admin > auditor > member > viewer > guest. Auditor is
        # explicit here so an account-merge duplicate cannot silently replace
        # the audit role with a weaker member/viewer projection in the JWT.
        priority = {
            'owner': 5,
            'admin': 4,
            'auditor': 3,
            'member': 2,
            'viewer': 1,
            'guest': 0,
        }
        dedup: dict[int, str] = {}
        for org_id, role in memberships:
            existing = dedup.get(org_id)
            if existing is None or priority.get(role, 0) > priority.get(existing, 0):
                dedup[org_id] = role
        # JIT grants are action-scoped authorisations — they must NOT be projected
        # into the generic org-role memberships dict or JWT claim.  Scoped checks
        # must use _user_has_active_jit_grant(scope=...) at the endpoint layer.
        # Return active grants in a separate field so callers can do targeted
        # action-level checks without conflating scope with org role.
        jit_active = JITElevatedAccessGrant.active_queryset(
            user_id=user_id,
            email=user_email,
        ).exclude(
            # ADR-0048 hardened floor: this target-constrained, one-use roster
            # action is consumed only by TeamViewSet.members.  It must never be
            # projected into the generic JWT/lookup capability list, including
            # during a mixed-version rollout or application rollback.
            scope=JITElevatedAccessGrant.TEAM_MEMBER_ADD_SCOPE,
        ).values('organization_id', 'scope', 'requested_role')
        jit_scoped_grants = [
            {'org_id': str(g['organization_id']), 'scope': g['scope'], 'role': g['requested_role']}
            for g in jit_active
        ]
        # JSON object keys must be strings — client (shizuha-id) will
        # reserialize into the JWT as-is.
        return Response({
            'memberships': {str(k): v for k, v in dedup.items()},
            'jit_scoped_grants': jit_scoped_grants,
        })


# Q lives in PermissionService module normally; import locally to avoid
# polluting the module globals.

class InternalUserProjectMembershipsView(APIView):
    """
    Return a compact {pulse_project_id: role} dict for a user (internal API).

    Used by shizuha-id to stamp `project_ids` and `project_roles` claims onto
    newly minted JWTs so SCS (and other services) can validate project-scoped
    requests from the JWT alone (SCS-31 / SCS-20).

    shizuha-pulse is the ONLY source of truth for project membership, so this
    endpoint has exactly one success case: Pulse answered, and the answer is
    the claim shape. Everything else is a typed failure.

    PLAT-5338 — why there is no local fallback any more:

    This response is an AUTHORIZATION claim, and `200 {'project_ids': []}` is
    indistinguishable, at every consumer, from "this user genuinely has no
    projects". shizuha-id's `_fetch_project_memberships(required=True)` raises
    on a non-200 and refuses to mint, but it accepts any well-shaped 200 — so a
    success-shaped empty is stamped straight into a JWT and silently removes
    every project grant the user has, for the 15-minute life of that token.

    The old degradation path returned exactly that. It read the local
    `ProjectMember` shadow table, which no code path in this repo writes — the
    single remaining reference was this read, and no data migration populates
    it either. Production holds exactly two rows (measured, not grepped:
    `ProjectMember.objects.count() == 2`, both user 110, projects 342 and 350,
    written out-of-band on 2026-06-27, five days after migration 0011 added
    the model and with `django_admin_log` empty, so neither a seed nor the
    admin form).

    So the fallback did not degrade the answer, it fabricated one, in two
    different ways. For every user but 110 the table is empty, so a Pulse
    timeout produced `200 {'project_ids': []}` — all-or-nothing, which is the
    shape of the failure measured on the live endpoint (a user with 21
    memberships getting 21 or 0, never a partial set, on the responses that
    took ~0.5s longer than the median: the Pulse read timeout). For user 110
    it produced a *plausible* two-project claim bearing no relation to what
    Pulse holds — the worse case of the two, because nothing about it looks
    wrong. Both are answers admin invented.

    Failing closed here is safe precisely because the caller is fail-closed:
    a typed 503 makes shizuha-id refuse the mint and retry, which costs a
    round-trip on a transient Pulse blip instead of issuing a token whose
    authorization claims are wrong and unrecoverable until it expires.
    """
    permission_classes = [InternalServicePermission]

    def _unavailable(self, user_id, reason):
        security_events.record_project_membership_projection('unavailable')
        logger.error(
            'PLAT-5338 project-membership projection unavailable for user %s (%s); '
            'refusing to answer with a non-authoritative projection',
            user_id, reason,
        )
        response = Response(
            {
                'error': 'project_membership_unavailable',
                'detail': (
                    'shizuha-pulse is the source of truth for project membership '
                    'and did not answer. admin has no authoritative projection to '
                    'return, and will not answer with an empty one. Retry.'
                ),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        response['Retry-After'] = '1'
        return response

    def _malformed(self, user_id, body):
        # Mirrors _unavailable deliberately: the 502 must not carry
        # `project_memberships`/`project_ids` either. An error body shaped like
        # a well-formed empty projection is the exact artifact this view exists
        # to stop emitting, and leaving it here would put a caller's status
        # check between a fabricated projection and a stamped JWT claim.
        security_events.record_project_membership_projection('malformed')
        logger.warning(
            'PLAT-5338 pulse project-memberships returned an unusable payload '
            'for user %s: %r',
            user_id, body,
        )
        return Response(
            {
                'error': 'project_membership_malformed',
                'detail': (
                    'shizuha-pulse answered, but not with the agreed '
                    '{project_memberships, project_ids} shape. admin will not '
                    'coerce an unusable payload into a projection.'
                ),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    def get(self, request, user_id):
        user_email = request.query_params.get('email') or None

        # The only source of truth for project membership.
        try:
            pulse_url = os.environ.get('SHIZUHA_PULSE_API_URL', 'http://shizuha-pulse:8002/api')
            params = {}
            if user_email:
                params['email'] = user_email
            resp = http_requests.get(
                f'{pulse_url}/internal/users/{user_id}/project-memberships/',
                params=params,
                timeout=_pulse_proxy_timeout(),
            )
        except Exception as exc:
            return self._unavailable(user_id, f'{type(exc).__name__}: {exc}')

        if resp.status_code != 200:
            return self._unavailable(user_id, f'pulse HTTP {resp.status_code}')

        try:
            data = resp.json()
        except Exception as exc:
            data = None
            logger.warning(
                f"Pulse project-memberships returned unparseable body for user {user_id}: {exc}"
            )
        if not (
            isinstance(data, dict)
            and isinstance(data.get('project_memberships'), dict)
            and isinstance(data.get('project_ids'), list)
        ):
            return self._malformed(user_id, data)

        # An empty projection is only legitimate when Pulse itself says so.
        # Counted (never alerted on by itself) so that an operator looking at a
        # user with no project claims can tell "Pulse said none" apart from
        # "admin could not ask" without re-deriving it from logs.
        if not data['project_ids']:
            security_events.record_project_membership_projection('authoritative_empty')
        return Response(data)


class InternalUserAgentProfileView(APIView):
    """Return an agent's ownership binding for a service caller (internal API).

    HIVE-671: before honouring a service-authenticated connection, Connect must
    verify the peer is an owner-bound *personal-default* agent.  Instead of
    guessing from a reserved user-id band, Connect asks Admin, which sources the
    authoritative binding from Shizuha ID and projects only the security-relevant
    fields (``account_type``/``ownership_class``/``owner_id``/``is_active``).
    Fail-closed: any inability to positively establish the binding returns a
    non-200 so the caller denies rather than defaults-open.
    """
    permission_classes = [InternalServicePermission]

    def get(self, request, user_id):
        id_url = os.environ.get(
            'SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api'
        ).rstrip('/')
        try:
            resp = http_requests.get(
                f'{id_url}/internal/users/{user_id}/', timeout=5
            )
        except Exception as exc:
            logger.warning(
                "agent-profile: ID fetch failed for user %s: %s", user_id, exc
            )
            return Response(
                {'error': 'identity service unavailable'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if resp.status_code == 404:
            return Response(
                {'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND
            )
        if resp.status_code != 200:
            logger.warning(
                "agent-profile: ID returned HTTP %s for user %s",
                resp.status_code, user_id,
            )
            return Response(
                {'error': 'identity service error'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        try:
            user = resp.json() or {}
        except ValueError:
            return Response(
                {'error': 'identity service returned malformed body'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        owner_id = user.get('owner_id')
        try:
            owner_id = int(owner_id) if owner_id is not None else None
        except (TypeError, ValueError):
            owner_id = None

        return Response({
            'user_id': int(user_id),
            'account_type': (user.get('account_type') or '').strip(),
            'ownership_class': (user.get('ownership_class') or '').strip(),
            'owner_id': owner_id,
            'is_active': bool(user.get('is_active', False)),
        })


from django.db.models import Q  # noqa: E402


urlpatterns = [
    path('permissions/check/', InternalPermissionCheckView.as_view(), name='internal-permission-check'),
    path('users/<int:user_id>/organizations/', InternalUserOrganizationsView.as_view(), name='internal-user-organizations'),
    path('users/<int:user_id>/memberships/', InternalUserMembershipsView.as_view(), name='internal-user-memberships'),
    path('users/<int:user_id>/projects/', InternalUserProjectsView.as_view(), name='internal-user-projects'),
    path('projects/<int:project_id>/', InternalProjectView.as_view(), name='internal-project'),
    path('projects/<int:project_id>/next-item-key/', InternalNextItemKeyView.as_view(), name='internal-next-item-key'),
    path('organizations/', InternalOrgCreateView.as_view(), name='internal-org-create'),
    # HIVE-2869: this specific route must be registered before the
    # <str:org_identifier> catch-all. Otherwise POST
    # /api/internal/organizations/<id>/delete/ resolves as a GET-only lookup
    # of identifier "<id>/delete" and DRF returns 401 before the signed
    # Hive permission on InternalOrgDeleteView can run.
    path('organizations/<int:org_id>/delete/', InternalOrgDeleteView.as_view(), name='internal-org-delete'),
    path('organizations/<str:org_identifier>/', InternalOrganizationView.as_view(), name='internal-organization'),
    path('organizations/<int:org_id>/members/', InternalOrgMembersView.as_view(), name='internal-org-members'),
    path('organizations/<int:org_id>/members/<int:user_id>/', InternalOrgMembershipCheckView.as_view(), name='internal-org-membership-check'),
    path('organizations/<int:org_id>/services/', InternalOrgServicesView.as_view(), name='internal-org-services'),
    path('users/<int:user_id>/project-memberships/', InternalUserProjectMembershipsView.as_view(), name='internal-user-project-memberships'),
    # PLAT-5343 slice 1: acyclic v2 composition (HLD §4.3). Fail-closed auth
    # in-view; exactly one local query + one Pulse v2 call. No fallback to the
    # circular v1 path once selected (§4.4 step 3); v1 above is retained until
    # caller inventory proves zero users (§4.4 steps 4-5).
    path('v2/project-memberships:resolve', ProjectMembershipResolveV2View.as_view(), name='internal-v2-project-memberships-resolve'),
    path('users/<int:user_id>/agent-profile/', InternalUserAgentProfileView.as_view(), name='internal-user-agent-profile'),
]
