"""PLAT-13057: JIT decision-hook notifications (requester + owning-team lead).

Root cure for the PLAT-13056 TTL-rot finding: grants rot because requesters
never learn their grant is pending or actioned (reporter's own grants
#978/#979 sat pending since Oct 31 with zero notifications). Every JIT grant
decision transition now emits one notification to the requester and one to
the owning-team lead (when a lead is resolvable), landing in each recipient's
dedicated Connect system DM — the same lane the original JIT page would use.

Message content carries the reporter-spec-mandated fields: grant_id,
decision, actor, timestamp (plus scope and a bounded decision note).
Delivery is fail-soft and idempotent per (grant, decision, recipient) via
Connect's ``client_message_id`` contract: a retry or replay never mints a
second notification, and a Connect outage never changes the decision the
caller sees. Network I/O is scheduled via ``transaction.on_commit`` at the
call sites so a rolled-back decision never notifies.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_SYSTEM_MESSAGE_TIMEOUT_SECONDS = 1.0
_NOTE_BOUND = 200


def _system_message_secret() -> str:
    return str(getattr(settings, 'CONNECT_SYSTEM_MESSAGE_ORIGIN_SECRET', '') or '')


def system_message_origin_token(
    *, sender_service: str, recipient_user_id: int, content: str,
) -> str:
    """Build Connect's short-lived HMAC origin token.

    Contract (connect/views/internal_api.py::_validate_system_origin_token):
    ``<unix_ts>:<hex_hmac>`` over
    ``sender_service|recipient_user_id|sha256(content)|ts``.
    """
    secret = _system_message_secret()
    ts = int(time.time())
    body_hash = hashlib.sha256((content or '').encode('utf-8')).hexdigest()
    payload = f'{sender_service}|{int(recipient_user_id)}|{body_hash}|{ts}'
    digest = hmac.new(
        secret.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256,
    ).hexdigest()
    return f'{ts}:{digest}'


def jit_decision_content(
    *, grant, decision: str, actor: str, decided_at, note: str = '',
) -> str:
    """One bounded, control-safe notification body with the four spec fields."""
    scope = str(getattr(grant, 'scope', '') or '')[:160]
    note_text = str(note or getattr(grant, 'decision_note', '') or '').strip()[:_NOTE_BOUND]
    lines = [
        f'JIT elevation grant {grant.pk}: {decision}',
        f'grant_id: {grant.pk}',
        f'decision: {decision}',
        f'actor: {actor or "system"}',
        f'timestamp: {decided_at.isoformat() if decided_at else "unknown"}',
        f'scope: {scope}',
    ]
    if note_text:
        lines.append(f'note: {note_text}')
    return '\n'.join(lines)


def _resolve_team_lead_user_id(grant) -> int | None:
    """Best-effort owning-team lead resolution (fail-soft).

    ``JITElevatedAccessGrant.owning_team`` is a free-form slug; ``Team``
    carries the lead (``lead_id``). Match the org's team by exact name
    (case-insensitive); an unresolvable lead emits nothing rather than
    guessing a recipient.
    """
    try:
        from organizations.models import Team
        team = Team.objects.filter(
            organization=getattr(grant, 'organization', None),
            name__iexact=str(getattr(grant, 'owning_team', '') or ''),
        ).first()
        if team is None or not team.lead_id:
            return None
        lead_id = int(team.lead_id)
        return lead_id if lead_id > 0 else None
    except Exception:
        logger.exception('PLAT-13057 team-lead resolution failed; skipping lead notification')
        return None


def _post_system_message(
    *, recipient_user_id: int, content: str, client_message_id: str,
) -> bool:
    sender_service = 'shizuha-admin'
    url = str(getattr(
        settings,
        'SHIZUHA_CONNECT_SYSTEM_MESSAGE_URL',
        'http://localhost:8019/api/internal/system-message/',
    ))
    try:
        response = requests.post(
            url,
            json={
                'recipient_user_id': int(recipient_user_id),
                'content': content,
                'sender_name': 'Admin JIT',
                'sender_service': sender_service,
                'client_message_id': client_message_id,
                'notification_class': 'informational',
            },
            headers={
                'X-Internal-Service': sender_service,
                'X-System-Message-Token': system_message_origin_token(
                    sender_service=sender_service,
                    recipient_user_id=int(recipient_user_id),
                    content=content,
                ),
            },
            timeout=_SYSTEM_MESSAGE_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        logger.warning(
            'PLAT-13057 JIT decision notification timed out recipient=%s', recipient_user_id,
        )
        return False
    except Exception:
        logger.exception(
            'PLAT-13057 JIT decision notification failed recipient=%s', recipient_user_id,
        )
        return False
    if response.status_code not in (200, 201):
        logger.error(
            'PLAT-13057 JIT decision notification rejected recipient=%s status=%s',
            recipient_user_id, response.status_code,
        )
        return False
    return True


def emit_jit_pending_notification(*, grant) -> bool:
    """Tell the owning-team lead a grant is waiting, at mint time.

    PLAT-13342: a pending grant only notified anyone once a decision landed,
    so a grant whose approver team had nobody online aged silently until its
    TTL. This fires once, when the grant is minted and not auto-approved, to
    the owning-team lead. Idempotent per grant: the deterministic
    ``client_message_id`` collapses a replayed mint onto one message. Never
    raises; a grant with no resolvable lead emits nothing.
    """
    if not bool(getattr(settings, 'JIT_DECISION_NOTIFICATIONS_ENABLED', True)):
        return False
    lead_id = _resolve_team_lead_user_id(grant)
    if lead_id is None:
        return False
    content = jit_decision_content(
        grant=grant, decision='pending', actor='mint',
        decided_at=getattr(grant, 'created_at', None),
        note='Awaiting an entitled approver on the owning team.',
    )
    namespace = uuid.UUID('9f2b1c3e-6a57-4d0e-9b8a-1c2d3e4f5a6b')
    client_message_id = str(uuid.uuid5(namespace, f'{grant.pk}|pending|{lead_id}'))
    return _post_system_message(
        recipient_user_id=lead_id, content=content, client_message_id=client_message_id,
    )


def emit_jit_decision_notification(
    *, grant, decision: str, actor_email: str = '', decided_at=None, note: str = '',
) -> bool:
    """Notify the requester (always) and the owning-team lead (resolvable).

    Idempotent per (grant, decision, recipient): the deterministic
    ``client_message_id`` makes Connect collapse retries/replays onto one
    message. Never raises; returns True when every attempted notification
    was accepted (or replayed).
    """
    if not bool(getattr(settings, 'JIT_DECISION_NOTIFICATIONS_ENABLED', True)):
        return False
    if decision not in ('approved', 'denied', 'revoked', 'expired'):
        logger.error('PLAT-13057 refusing to notify unknown decision %r', decision)
        return False
    decided_at = decided_at or getattr(grant, 'decided_at', None)
    actor = str(actor_email or getattr(grant, 'decided_by_email', '') or 'system')
    content = jit_decision_content(
        grant=grant, decision=decision, actor=actor, decided_at=decided_at, note=note,
    )

    recipients: list[int] = []
    requester_id = int(getattr(grant, 'requester_user_id', 0) or 0)
    if requester_id > 0:
        recipients.append(requester_id)
    lead_id = _resolve_team_lead_user_id(grant)
    if lead_id is not None and lead_id != requester_id:
        recipients.append(lead_id)
    if not recipients:
        logger.warning('PLAT-13057 no resolvable notification recipient for grant %s', grant.pk)
        return False

    namespace = uuid.UUID('9f2b1c3e-6a57-4d0e-9b8a-1c2d3e4f5a6b')
    ok = True
    for recipient_user_id in recipients:
        client_message_id = str(uuid.uuid5(
            namespace, f'{grant.pk}|{decision}|{recipient_user_id}|'
                       f'{decided_at.isoformat() if decided_at else "none"}',
        ))
        if not _post_system_message(
            recipient_user_id=recipient_user_id,
            content=content,
            client_message_id=client_message_id,
        ):
            ok = False
    return ok
