"""
Permission classes for organization access control.

Note: Project permissions have been removed. Projects are now managed by shizuha-pulse.
"""
from rest_framework import permissions
from .models import JITElevatedAccessGrant, OrganizationMembership


class OrganizationPermission(permissions.BasePermission):
    """
    Permission for organization-level access.

    - All authenticated users can create organizations
    - Organization members can view their organizations
    - Only owners/admins can modify organizations
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        # A scoped JIT grant must be checked before the persistent-membership
        # gate: cross-org JIT grantees intentionally are not org members.
        if getattr(view, 'action', None) == 'members' and request.method == 'POST':
            grants = JITElevatedAccessGrant.active_queryset(
                user_id=getattr(request.user, 'id', None),
                email=getattr(request.user, 'email', '') or '',
                organization=obj,
                scope='org.members.add',
            )
            if any(
                JITElevatedAccessGrant.role_priority(grant.requested_role)
                >= JITElevatedAccessGrant.role_priority('admin')
                for grant in grants
            ):
                return True

        # Check if user is a member of the organization
        membership = OrganizationMembership.objects.filter(
            organization=obj,
            user_id=request.user.id,
            is_active=True
        ).first()

        if not membership:
            return False

        # Read access for all members
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write access requires a persistent admin/owner membership.
        if membership.role in ['owner', 'admin']:
            return True

        return False
