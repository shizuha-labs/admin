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
