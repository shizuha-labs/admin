"""
Signals for organization events.
"""
import logging
import threading
from django.db.models import QuerySet
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.utils import timezone

from .models import Organization, OrganizationMembership, EmployeeProfile, OrganizationServiceAccess, MembershipChange

logger = logging.getLogger(__name__)


# Default services enabled for new organizations
DEFAULT_ORG_SERVICES = [
    'admin', 'id', 'pulse', 'notes', 'mail', 'time',
    'connect', 'wiki', 'finance', 'books', 'inventory', 'hr', 'home',
]


@receiver(post_save, sender=Organization)
def auto_populate_org_services(sender, instance, created, **kwargs):
    """Auto-populate default service access entries when an organization is created."""
    if not created:
        return

    for slug in DEFAULT_ORG_SERVICES:
        OrganizationServiceAccess.objects.get_or_create(
            organization=instance,
            service_slug=slug,
            defaults={'is_enabled': True},
        )
    logger.info(f"Auto-populated {len(DEFAULT_ORG_SERVICES)} default services for org {instance.name}")


# ── Membership audit trail ───────────────────────────────────────────────
#
# Every mutation on OrganizationMembership emits an immutable MembershipChange
# row so the org admin / security team has a first-class audit answer to
# "who promoted whom, when, and why". We stamp the pre-save state onto
# thread-local storage in a pre_save receiver, then diff against the
# post-save instance to decide which action occurred (created / role_changed
# / deactivated / reactivated). See GitHub org audit log + AWS CloudTrail
# for the pattern.

_membership_audit_state = threading.local()


def _get_actor_from_context():
    """
    Resolve the actor for the current mutation. View code sets this via
    `MembershipChange.set_actor(user)`. Unset = system-initiated (bootstrap,
    migration, signal-triggered auto-enrollment).
    """
    info = getattr(_membership_audit_state, 'actor', None)
    if info is None:
        return (None, None, 'system')
    return (info.get('user_id'), info.get('user_email'), info.get('source', 'api'))


def set_membership_audit_actor(user_id=None, user_email=None, source='api'):
    """Called by views to tag subsequent membership mutations with an actor."""
    _membership_audit_state.actor = {
        'user_id': user_id,
        'user_email': user_email,
        'source': source,
    }


def clear_membership_audit_actor():
    _membership_audit_state.actor = None


@receiver(pre_save, sender=OrganizationMembership)
def _capture_membership_pre_state(sender, instance, **kwargs):
    """Snapshot the membership's current state before save so post_save can diff."""
    if instance.pk is None:
        instance._audit_prev = None
        return
    try:
        prev = OrganizationMembership.objects.only('role', 'is_active').get(pk=instance.pk)
        instance._audit_prev = {'role': prev.role, 'is_active': prev.is_active}
    except OrganizationMembership.DoesNotExist:
        instance._audit_prev = None


@receiver(post_save, sender=OrganizationMembership)
def _emit_membership_change(sender, instance, created, **kwargs):
    """Write a MembershipChange row for every creation, role change, or (de)activation."""
    try:
        prev = getattr(instance, '_audit_prev', None)
        actor_id, actor_email, actor_source = _get_actor_from_context()
        base = dict(
            organization=instance.organization,
            target_user_id=instance.user_id,
            target_user_email=instance.user_email,
            actor_user_id=actor_id,
            actor_user_email=actor_email,
            actor_source=actor_source,
            new_role=instance.role,
        )
        if created:
            MembershipChange.objects.create(
                action='created', previous_role=None, **base,
            )
            return
        if prev is None:
            # update without readable pre-state (shouldn't happen but safe)
            return
        # Deactivation / reactivation take priority over role-change so we
        # don't double-emit for a single save that flipped both.
        if prev['is_active'] and not instance.is_active:
            MembershipChange.objects.create(
                action='deactivated', previous_role=prev['role'], **base,
            )
        elif not prev['is_active'] and instance.is_active:
            MembershipChange.objects.create(
                action='reactivated', previous_role=prev['role'], **base,
            )
        elif prev['role'] != instance.role:
            MembershipChange.objects.create(
                action='role_changed', previous_role=prev['role'], **base,
            )
    except Exception as exc:
        # Audit log failure must never break the actual mutation.
        logger.exception(f"Failed to record MembershipChange for {instance.pk}: {exc}")


@receiver(post_delete, sender=OrganizationMembership)
def _emit_membership_deleted(sender, instance, **kwargs):
    """Hard deletes are rare but audit them as tombstones."""
    origin = kwargs.get('origin')
    if isinstance(origin, Organization) or (
        isinstance(origin, QuerySet) and issubclass(origin.model, Organization)
    ):
        # Organization deletion also deletes its audit history (the existing
        # CASCADE contract). The collector already removed those rows before
        # this signal; adding a new tombstone would reference the deleted org
        # and fail PostgreSQL's deferred FK check at COMMIT. Django's deletion
        # origin distinguishes this cascade from a membership-only delete,
        # whose tombstone must still be retained under the surviving org.
        return
    try:
        actor_id, actor_email, actor_source = _get_actor_from_context()
        MembershipChange.objects.create(
            organization=instance.organization,
            target_user_id=instance.user_id,
            target_user_email=instance.user_email,
            actor_user_id=actor_id,
            actor_user_email=actor_email,
            actor_source=actor_source,
            action='deleted',
            previous_role=instance.role,
            new_role=None,
        )
    except Exception as exc:
        logger.exception(f"Failed to record MembershipChange delete for {instance.pk}: {exc}")


@receiver(post_save, sender=OrganizationMembership)
def setup_founder_on_owner_membership(sender, instance, created, **kwargs):
    """
    When an owner membership is created (i.e., org founder joins),
    automatically set up their employee profile for the org chart.
    """
    if not created:
        return

    # Only for owner role, non-pending memberships
    if instance.role != 'owner' or instance.is_pending:
        return

    # Check if this is the organization's owner
    if instance.user_id != instance.organization.owner_id:
        return

    try:
        employee_profile = instance.organization.setup_founder_employee_profile(
            owner_email=instance.user_email
        )
        if employee_profile:
            logger.info(
                f"Created founder employee profile for {instance.user_email} "
                f"in organization {instance.organization.name}"
            )
    except Exception as e:
        logger.error(f"Failed to create founder employee profile: {e}")


@receiver(post_save, sender=OrganizationMembership)
def auto_create_employee_profile(sender, instance, created, **kwargs):
    """
    Automatically create an employee profile when a member joins an organization.

    This ensures all org members are also employees, which enables:
    - Appearing in the org chart
    - Having a reporting structure (reports_to)
    - Being assigned to teams
    - Being visible in HR management

    Founders are handled separately by setup_founder_on_owner_membership.
    """
    # Skip if pending invitation
    if instance.is_pending:
        return

    # Skip if no user_id yet
    if not instance.user_id:
        return

    # Skip founders (handled by the other signal)
    if instance.role == 'owner' and instance.user_id == instance.organization.owner_id:
        return

    # Check if employee profile already exists
    if EmployeeProfile.objects.filter(membership=instance).exists():
        return

    try:
        # Determine job title based on role
        role_titles = {
            'owner': 'Owner',
            'admin': 'Administrator',
            'member': 'Team Member',
            'viewer': 'Observer',
        }
        job_title = role_titles.get(instance.role, 'Team Member')

        # Find the organization owner to set as default manager
        owner_membership = OrganizationMembership.objects.filter(
            organization=instance.organization,
            role='owner',
            is_active=True,
            is_pending=False
        ).first()

        manager_id = owner_membership.user_id if owner_membership else None
        manager_email = owner_membership.user_email if owner_membership else None

        # Create the employee profile
        employee = EmployeeProfile.objects.create(
            membership=instance,
            job_title=job_title,
            employment_status='active',
            employment_type='full_time',
            start_date=timezone.now().date(),
            manager_id=manager_id,
            manager_email=manager_email,
        )

        logger.info(
            f"Auto-created employee profile for {instance.user_email} "
            f"in organization {instance.organization.name} "
            f"(reports to: {manager_email})"
        )
    except Exception as e:
        logger.error(f"Failed to auto-create employee profile for {instance.user_email}: {e}")
