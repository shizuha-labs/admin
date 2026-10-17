"""
Permission service for organization-based access control.

This service provides helper methods for checking user permissions
across organizations, similar to Jira's permission model.

Note: Project permissions have been removed. Projects are now managed by shizuha-pulse.
Use the Pulse API at /pulse/api/projects/ for project management.
"""
from django.db.models import Q
from ..models import Organization, OrganizationMembership


class PermissionService:
    """
    Service for checking and managing permissions across organizations.
    """

    @staticmethod
    def get_user_organizations(user_id, user_email=None):
        """
        Get all organizations a user belongs to.

        Args:
            user_id: The user's ID
            user_email: Optional user email to also match by email

        Returns:
            QuerySet of Organization objects
        """
        q_filter = Q(memberships__user_id=user_id)
        if user_email:
            q_filter |= Q(memberships__user_email=user_email)

        return Organization.objects.filter(
            q_filter,
            memberships__is_active=True,
            is_active=True
        ).distinct()

    @staticmethod
    def get_user_org_membership(user_id, organization):
        """
        Get user's membership in an organization.

        Args:
            user_id: The user's ID
            organization: Organization instance or ID

        Returns:
            OrganizationMembership or None
        """
        org_id = organization.id if hasattr(organization, 'id') else organization
        return OrganizationMembership.objects.filter(
            organization_id=org_id,
            user_id=user_id,
            is_active=True
        ).first()

    @staticmethod
    def can_access_organization(user_id, organization):
        """
        Check if user can access an organization.

        Args:
            user_id: The user's ID
            organization: Organization instance or ID

        Returns:
            bool
        """
        org_id = organization.id if hasattr(organization, 'id') else organization
        return OrganizationMembership.objects.filter(
            organization_id=org_id,
            user_id=user_id,
            is_active=True
        ).exists()

    @staticmethod
    def can_manage_organization(user_id, organization):
        """
        Check if user can manage an organization (owner or admin).

        Args:
            user_id: The user's ID
            organization: Organization instance or ID

        Returns:
            bool
        """
        org_id = organization.id if hasattr(organization, 'id') else organization
        return OrganizationMembership.objects.filter(
            organization_id=org_id,
            user_id=user_id,
            role__in=['owner', 'admin'],
            is_active=True
        ).exists()

    @staticmethod
    def check_permission(user_id, resource_type, resource_id, action):
        """
        Generic permission check for internal API calls.

        Args:
            user_id: The user's ID
            resource_type: 'organization' (project support removed - use Pulse API)
            resource_id: ID of the resource
            action: The action to check (browse, manage)

        Returns:
            dict with 'allowed' boolean and optional 'reason'
        """
        try:
            if resource_type == 'organization':
                org = Organization.objects.get(id=resource_id)
                if action == 'browse':
                    allowed = PermissionService.can_access_organization(user_id, org)
                else:
                    allowed = PermissionService.can_manage_organization(user_id, org)
            elif resource_type == 'project':
                # Projects are now managed by shizuha-pulse
                return {
                    'allowed': False,
                    'reason': 'Project permissions are now managed by shizuha-pulse. Use /pulse/api/projects/.'
                }
            else:
                return {'allowed': False, 'reason': f'Unknown resource type: {resource_type}'}

            return {'allowed': allowed}
        except Organization.DoesNotExist:
            return {'allowed': False, 'reason': 'Resource not found'}


# Singleton instance for convenience
permission_service = PermissionService()
