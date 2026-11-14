from celery import shared_task

from .jit_dispatch import (
    dispatch_kubernetes_jit_use_fail_loud,
    release_expired_kubernetes_jit_consumes,
    reconcile_pending_kubernetes_jit_uses,
)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=12,
)
def dispatch_kubernetes_jit_use_task(self, use_id):
    return dispatch_kubernetes_jit_use_fail_loud(use_id)


@shared_task
def reconcile_pending_kubernetes_jit_uses_task():
    return reconcile_pending_kubernetes_jit_uses()


@shared_task
def release_expired_kubernetes_jit_consumes_task():
    """ORIG-412: explicit release-on-expiry; same beat as the dispatch reconcile."""
    return release_expired_kubernetes_jit_consumes()


def notify_expired_jit_grants_task():
    """PLAT-13057: TTL lapse is a decision — notify on approved→expired.

    Bounded, idempotent sweeper: finds approved grants past ``expires_at``
    that have no prior ``expired`` event row (the row is the notify-once
    marker), records the ``expired`` event, and emits the decision-hook
    notification (requester + resolvable owning-team lead) on Connect's
    system-DM lane. Never raises into the beat loop.
    """
    import logging

    from django.db import transaction
    from django.utils import timezone

    from . import jit_notifications
    from .models import JITElevatedAccessGrant, JITElevatedAccessGrantEvent

    logger = logging.getLogger(__name__)
    batch_bound = 100
    notified = 0
    try:
        expired = JITElevatedAccessGrant.objects.filter(
            status=JITElevatedAccessGrant.STATUS_APPROVED,
            expires_at__lt=timezone.now(),
        ).select_related('organization').order_by('expires_at')[:batch_bound]
    except Exception:
        logger.exception('PLAT-13057 expired-JIT query failed')
        return {'notified': 0}

    for grant in expired:
        try:
            already = JITElevatedAccessGrantEvent.objects.filter(
                grant=grant, event_type='expired',
            ).exists()
            if already:
                continue
            with transaction.atomic():
                JITElevatedAccessGrantEvent.objects.create(
                    grant=grant,
                    event_type='expired',
                    actor_user_id=None,
                    actor_email='system',
                    source='sweeper',
                    detail={'expires_at': grant.expires_at.isoformat() if grant.expires_at else None},
                )
                result = jit_notifications.emit_jit_decision_notification(
                    grant=grant, decision='expired', actor_email='system',
                    decided_at=grant.expires_at,
                )
            if result:
                notified += 1
        except Exception:
            logger.exception('PLAT-13057 expired-JIT notification failed grant=%s', grant.pk)
    if notified:
        logger.info('PLAT-13057 expired-JIT notifications sent: %s', notified)
    return {'notified': notified}
