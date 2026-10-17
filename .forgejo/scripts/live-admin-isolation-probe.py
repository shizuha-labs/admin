#!/usr/bin/env python3
"""Read-only live isolation probe for Shizuha Admin (PLAT-4200).

The probe deliberately prints only case names and HTTP status codes.  It never
prints request URLs, bearer/service tokens, tenant markers, or response bodies.
All public ``/api/internal/*`` checks use ``OPTIONS`` so a failed guard cannot
reach a state-changing view (two legacy GET handlers can create workspaces).
``http.client`` is used instead of urllib so adversarial request targets retain
encoded slashes and duplicate slashes exactly as written on the wire.

Environment contract
--------------------

Baseline edge checks need no secret and target ``https://shizuha.com``.  The
origin can be overridden with ``ADMIN_PROBE_EXTERNAL_BASE_URL``.

Set ``ADMIN_PROBE_ACTOR_TOKEN`` to add the tenant-bearer edge matrix, verify the
token is for an ordinary (non-staff, non-superuser) user, and prove that every
read-only superuser route rejects it.  Set all three variables below to also
run the real two-organization lane (partial configuration is an error):

* ``ADMIN_PROBE_ACTOR_ORG_SLUG`` -- an organization visible to the actor;
* ``ADMIN_PROBE_OTHER_ORG_SLUG`` -- an organization not visible to the actor;
* ``ADMIN_PROBE_OTHER_ORG_MARKER`` -- a unique, non-secret fixture marker from
  the other organization (minimum eight characters).

The optional authenticated ClusterIP lane requires both
``ADMIN_PROBE_INTERNAL_BASE_URL`` and ``ADMIN_PROBE_SERVICE_TOKEN``.  The token
is sent only to a loopback/private/``*.svc`` destination.  The caller name is
``ADMIN_PROBE_SERVICE_NAME`` (default ``plat4200-live-probe``).

``ADMIN_PROBE_SAFE_USER_ID``, ``ADMIN_PROBE_SAFE_ORG_ID``, and
``ADMIN_PROBE_SAFE_PROJECT_ID`` may override the non-mutating route placeholders
(defaults are deliberately nonexistent high integers).  Use
``--require-actor``, ``--require-cross-tenant``, and ``--require-internal`` in a
deployment gate to turn optional-lane skips into failures.
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
import ssl
import sys
from dataclasses import dataclass
from typing import Iterable, Mapping
from urllib.parse import quote, urlsplit


DENIED_STATUSES = frozenset({401, 403})
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PUBLIC_ALIASES = ("admin", "shizuha-admin")


class ProbeFailure(RuntimeError):
    """A failure whose message is guaranteed not to contain probe secrets."""


@dataclass(frozen=True)
class Origin:
    scheme: str
    hostname: str
    port: int | None


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    truncated: bool


@dataclass(frozen=True)
class InternalRoute:
    name: str
    method: str
    suffix: str


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _safe_positive_int_env(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ProbeFailure(f"configuration-invalid field={name}") from exc
    if value <= 0:
        raise ProbeFailure(f"configuration-invalid field={name}")
    return value


def _timeout_default() -> float:
    raw = _env("ADMIN_PROBE_TIMEOUT_SECONDS") or "10"
    try:
        return float(raw)
    except ValueError as exc:
        raise ProbeFailure("configuration-invalid field=ADMIN_PROBE_TIMEOUT_SECONDS") from exc


def parse_origin(raw: str, *, label: str) -> Origin:
    """Parse an origin-only URL without retaining userinfo/path/query data."""
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ProbeFailure(f"configuration-invalid field={label}") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ProbeFailure(f"configuration-invalid field={label}")
    return Origin(parsed.scheme, parsed.hostname, port)


def _is_private_destination(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    if host in {"localhost", "shizuha-admin"} or host.endswith(".svc") or host.endswith(".svc.cluster.local"):
        return True
    try:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _connection(origin: Origin, *, timeout: float, context: ssl.SSLContext):
    if origin.scheme == "https":
        return http.client.HTTPSConnection(
            origin.hostname,
            origin.port,
            timeout=timeout,
            context=context,
        )
    return http.client.HTTPConnection(origin.hostname, origin.port, timeout=timeout)


def request_exact(
    origin: Origin,
    target: str,
    *,
    method: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    context: ssl.SSLContext,
) -> Response:
    """Send an exact HTTP request target without redirecting or normalizing it."""
    if not target.startswith("/") or "\r" in target or "\n" in target:
        raise ProbeFailure("configuration-invalid field=request-target")
    merged_headers = {
        "Accept": "application/json",
        "Cache-Control": "no-store",
        "Connection": "close",
        "User-Agent": "shizuha-admin-isolation-probe/PLAT-4200",
    }
    merged_headers.update(headers or {})
    connection = _connection(origin, timeout=timeout, context=context)
    try:
        connection.request(method, target, headers=merged_headers)
        raw = connection.getresponse()
        body = raw.read(MAX_RESPONSE_BYTES + 1)
        return Response(
            status=raw.status,
            body=body[:MAX_RESPONSE_BYTES],
            truncated=len(body) > MAX_RESPONSE_BYTES,
        )
    finally:
        connection.close()


def _print_result(outcome: str, case: str, status: int | str) -> None:
    print(f"{outcome} case={case} status={status}")


def expect_status(
    response: Response,
    *,
    case: str,
    expected: Iterable[int],
) -> None:
    allowed = frozenset(expected)
    if response.status not in allowed:
        expected_text = "/".join(str(value) for value in sorted(allowed))
        raise ProbeFailure(
            f"case={case} expected={expected_text} status={response.status}"
        )
    _print_result("PASS", case, response.status)


def expect_not_status(response: Response, *, case: str, forbidden: int) -> None:
    if response.status == forbidden:
        raise ProbeFailure(f"case={case} unexpected-status={response.status}")
    _print_result("PASS", case, response.status)


def _payload_contains_marker(body: bytes, marker: str) -> bool:
    """Search decoded JSON scalar values without ever returning their content."""
    folded = marker.casefold()
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return folded in body.decode("utf-8", errors="ignore").casefold()

    def walk(value: object) -> bool:
        if isinstance(value, dict):
            return any(walk(key) or walk(child) for key, child in value.items())
        if isinstance(value, list):
            return any(walk(child) for child in value)
        if isinstance(value, str):
            return folded in value.casefold()
        return False

    return walk(payload)


def _is_empty_collection(body: bytes) -> bool:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if isinstance(payload, list):
        return not payload
    if not isinstance(payload, dict):
        return False
    collection_keys = {
        "results", "members", "departments", "teams", "positions", "employees"
    }
    lists = [value for key, value in payload.items() if key in collection_keys]
    if not lists or not all(isinstance(value, list) and not value for value in lists):
        return False
    if payload.get("count", 0) != 0:
        return False
    # Do not accept a nominally empty list alongside an unclassified payload.
    # DRF pagination metadata is the only additional response shape allowed.
    allowed_metadata = {"count", "next", "previous"}
    return all(
        key in collection_keys
        or (key in allowed_metadata and (value is None or value == 0))
        for key, value in payload.items()
    )


def expect_other_org_hidden(
    response: Response,
    *,
    case: str,
    marker: str,
    allow_empty_collection: bool,
) -> None:
    if response.truncated:
        raise ProbeFailure(f"case={case} response-too-large")
    if _payload_contains_marker(response.body, marker):
        raise ProbeFailure(f"case={case} other-org-marker-visible status={response.status}")
    if response.status in {403, 404}:
        _print_result("PASS", case, response.status)
        return
    if response.status == 200 and allow_empty_collection and _is_empty_collection(response.body):
        _print_result("PASS", case, response.status)
        return
    raise ProbeFailure(f"case={case} cross-tenant-read-visible status={response.status}")


def _internal_routes(user_id: int, org_id: int, project_id: int) -> list[InternalRoute]:
    # Every concrete route family from organizations/internal_urls.py.  Use the
    # real read/check method where it is side-effect free.  OPTIONS is mandatory
    # for the two workspace-creating GETs and the next-key POST: it reaches DRF's
    # permission gate without invoking their view code.
    return [
        InternalRoute("permission-check", "POST", "permissions/check/"),
        InternalRoute("user-organizations", "OPTIONS", f"users/{user_id}/organizations/"),
        InternalRoute("user-memberships", "OPTIONS", f"users/{user_id}/memberships/"),
        InternalRoute("user-projects", "GET", f"users/{user_id}/projects/"),
        InternalRoute("project-detail", "GET", f"projects/{project_id}/"),
        InternalRoute("project-next-item-key", "OPTIONS", f"projects/{project_id}/next-item-key/"),
        InternalRoute("organization-detail", "GET", f"organizations/{org_id}/"),
        InternalRoute("organization-members", "GET", f"organizations/{org_id}/members/"),
        InternalRoute(
            "organization-membership",
            "GET",
            f"organizations/{org_id}/members/{user_id}/",
        ),
        InternalRoute("organization-services", "GET", f"organizations/{org_id}/services/"),
        InternalRoute(
            "user-project-memberships",
            "GET",
            f"users/{user_id}/project-memberships/",
        ),
    ]


def run_public_internal_matrix(
    *,
    origin: Origin,
    routes: list[InternalRoute],
    modes: list[tuple[str, Mapping[str, str]]],
    timeout: float,
    context: ssl.SSLContext,
) -> None:
    for alias in PUBLIC_ALIASES:
        for mode, headers in modes:
            for route in routes:
                response = request_exact(
                    origin,
                    f"/{alias}/api/internal/{route.suffix}",
                    method=route.method,
                    headers=headers,
                    timeout=timeout,
                    context=context,
                )
                expect_status(
                    response,
                    case=f"edge-{alias}-{mode}-{route.name}",
                    expected=DENIED_STATUSES,
                )


def run_adversarial_edge_cases(
    *,
    origin: Origin,
    user_id: int,
    timeout: float,
    context: ssl.SSLContext,
) -> None:
    for alias in PUBLIC_ALIASES:
        suffix = f"users/{user_id}/memberships/"
        cases = [
            ("encoded-slash", f"/{alias}/api%2Finternal/{suffix}"),
            ("duplicate-slash", f"/{alias}/api//internal/{suffix}"),
            ("uppercase", f"/{alias.upper()}/API/INTERNAL/{suffix}"),
            ("bare-internal", f"/{alias}/api/internal"),
            ("query-string", f"/{alias}/api/internal?probe=plat4200"),
        ]
        for name, target in cases:
            response = request_exact(
                origin,
                target,
                method="OPTIONS",
                headers={},
                timeout=timeout,
                context=context,
            )
            expect_status(
                response,
                case=f"edge-{alias}-adversarial-{name}",
                expected=DENIED_STATUSES,
            )

        # The guard is anchored at /internal(?:/|$); a broader match would break
        # ordinary future routes such as /internality/.
        response = request_exact(
            origin,
            f"/{alias}/api/internality/",
            method="OPTIONS",
            headers={},
            timeout=timeout,
            context=context,
        )
        expect_not_status(
            response,
            case=f"edge-{alias}-nonmatching-internality",
            forbidden=403,
        )

        # Proves containment did not blanket-block either Admin alias.  The
        # legacy /shizuha-admin mount intentionally has no health route and
        # returns 404, while the canonical /admin mount returns 200.
        response = request_exact(
            origin,
            f"/{alias}/api/health/",
            method="GET",
            headers={},
            timeout=timeout,
            context=context,
        )
        if alias == "admin":
            expect_status(
                response,
                case=f"edge-{alias}-unaffected-health",
                expected={200},
            )
        else:
            expect_not_status(
                response,
                case=f"edge-{alias}-unaffected-health",
                forbidden=403,
            )


def _bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def verify_ordinary_actor(
    *,
    origin: Origin,
    token: str,
    timeout: float,
    context: ssl.SSLContext,
) -> None:
    response = request_exact(
        origin,
        "/admin/api/me/",
        method="GET",
        headers=_bearer_headers(token),
        timeout=timeout,
        context=context,
    )
    if response.status != 200 or response.truncated:
        raise ProbeFailure(f"case=actor-ordinary-proof expected=200 status={response.status}")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeFailure("case=actor-ordinary-proof invalid-json") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("is_staff") is not False
        or payload.get("is_superuser") is not False
    ):
        raise ProbeFailure("case=actor-ordinary-proof token-not-ordinary")
    _print_result("PASS", "actor-ordinary-proof", response.status)


def run_superuser_denials(
    *,
    origin: Origin,
    token: str,
    timeout: float,
    context: ssl.SSLContext,
) -> None:
    read_only_routes = [
        ("dashboard", "superuser/dashboard/"),
        ("users", "superuser/users/"),
        ("organizations", "superuser/organizations/"),
        ("system-health", "superuser/system/health/"),
        ("services", "superuser/services/"),
        ("requests", "superuser/requests/"),
        ("pending-users", "superuser/users/pending/"),
        ("pending-users-count", "superuser/users/pending/count/"),
    ]
    headers = _bearer_headers(token)
    # /admin is the routed application mount.  /shizuha-admin is covered by
    # the internal-path containment matrix but intentionally 404s for ordinary
    # application paths, so it cannot prove the Django superuser checks.
    for name, suffix in read_only_routes:
        response = request_exact(
            origin,
            f"/admin/api/{suffix}",
            method="GET",
            headers=headers,
            timeout=timeout,
            context=context,
        )
        expect_status(
            response,
            case=f"ordinary-superuser-{name}",
            expected={403},
        )


def run_cross_tenant_lane(
    *,
    origin: Origin,
    token: str,
    actor_org_slug: str,
    other_org_slug: str,
    other_org_marker: str,
    timeout: float,
    context: ssl.SSLContext,
) -> None:
    headers = _bearer_headers(token)
    actor_slug = quote(actor_org_slug, safe="")
    other_slug = quote(other_org_slug, safe="")

    # Positive controls prove the actor and canonical alias can read the
    # organization it actually belongs to.
    positive_paths = [
        ("organization", f"organizations/{actor_slug}/"),
        ("members", f"organizations/{actor_slug}/members/"),
        ("departments", f"organizations/{actor_slug}/departments/"),
    ]
    for name, suffix in positive_paths:
        response = request_exact(
            origin,
            f"/admin/api/{suffix}",
            method="GET",
            headers=headers,
            timeout=timeout,
            context=context,
        )
        expect_status(response, case=f"actor-org-positive-{name}", expected={200})

    hidden_paths = [
        ("organization", f"organizations/{other_slug}/", False),
        ("members", f"organizations/{other_slug}/members/", False),
        ("services", f"organizations/{other_slug}/services/", False),
        ("departments", f"organizations/{other_slug}/departments/", True),
        ("teams", f"organizations/{other_slug}/teams/", True),
        ("positions", f"organizations/{other_slug}/positions/", True),
        ("employees", f"organizations/{other_slug}/employees/", True),
        ("org-chart", f"organizations/{other_slug}/org-chart/", False),
        ("org-chart-stats", f"organizations/{other_slug}/org-chart/stats/", False),
    ]
    for name, suffix, allow_empty in hidden_paths:
        response = request_exact(
            origin,
            f"/admin/api/{suffix}",
            method="GET",
            headers=headers,
            timeout=timeout,
            context=context,
        )
        expect_other_org_hidden(
            response,
            case=f"actor-cross-org-{name}",
            marker=other_org_marker,
            allow_empty_collection=allow_empty,
        )


def run_internal_service_lane(
    *,
    origin: Origin,
    service_token: str,
    service_name: str,
    org_id: int,
    user_id: int,
    timeout: float,
    context: ssl.SSLContext,
) -> None:
    if not _is_private_destination(origin.hostname):
        raise ProbeFailure("configuration-invalid field=ADMIN_PROBE_INTERNAL_BASE_URL")
    if any(character in service_name for character in "\r\n"):
        raise ProbeFailure("configuration-invalid field=ADMIN_PROBE_SERVICE_NAME")
    response = request_exact(
        origin,
        f"/api/internal/organizations/{org_id}/members/{user_id}/",
        method="GET",
        headers={
            "X-Internal-Service": service_name,
            "X-Internal-Service-Token": service_token,
        },
        timeout=timeout,
        context=context,
    )
    expect_status(response, case="clusterip-valid-service-token", expected={200})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--external-base-url",
        default=_env("ADMIN_PROBE_EXTERNAL_BASE_URL") or "https://shizuha.com",
        help="Admin public origin only; may also be set by ADMIN_PROBE_EXTERNAL_BASE_URL",
    )
    parser.add_argument("--timeout", type=float, default=_timeout_default())
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for a test environment")
    parser.add_argument("--require-actor", action="store_true")
    parser.add_argument("--require-cross-tenant", action="store_true")
    parser.add_argument("--require-internal", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        raise ProbeFailure("configuration-invalid field=timeout")

    external = parse_origin(args.external_base_url, label="ADMIN_PROBE_EXTERNAL_BASE_URL")
    actor_token = _env("ADMIN_PROBE_ACTOR_TOKEN")
    if actor_token and external.scheme != "https":
        raise ProbeFailure("configuration-invalid field=ADMIN_PROBE_EXTERNAL_BASE_URL")
    if args.require_actor and not actor_token:
        raise ProbeFailure("configuration-missing lane=actor")

    actor_org = _env("ADMIN_PROBE_ACTOR_ORG_SLUG")
    other_org = _env("ADMIN_PROBE_OTHER_ORG_SLUG")
    other_marker = _env("ADMIN_PROBE_OTHER_ORG_MARKER")
    cross_values = (actor_org, other_org, other_marker)
    if any(cross_values) and not all(cross_values):
        raise ProbeFailure("configuration-incomplete lane=cross-tenant")
    if all(cross_values) and not actor_token:
        raise ProbeFailure("configuration-missing lane=actor")
    if other_marker and len(other_marker) < 8:
        raise ProbeFailure("configuration-invalid field=ADMIN_PROBE_OTHER_ORG_MARKER")
    if actor_org and actor_org == other_org:
        raise ProbeFailure("configuration-invalid lane=cross-tenant")
    if args.require_cross_tenant and not all(cross_values):
        raise ProbeFailure("configuration-missing lane=cross-tenant")

    internal_raw = _env("ADMIN_PROBE_INTERNAL_BASE_URL")
    service_token = _env("ADMIN_PROBE_SERVICE_TOKEN")
    if bool(internal_raw) != bool(service_token):
        raise ProbeFailure("configuration-incomplete lane=internal-service")
    if args.require_internal and not internal_raw:
        raise ProbeFailure("configuration-missing lane=internal-service")

    user_id = _safe_positive_int_env("ADMIN_PROBE_SAFE_USER_ID", 2_147_483_647)
    org_id = _safe_positive_int_env("ADMIN_PROBE_SAFE_ORG_ID", 2_147_483_647)
    project_id = _safe_positive_int_env("ADMIN_PROBE_SAFE_PROJECT_ID", 2_147_483_647)
    routes = _internal_routes(user_id, org_id, project_id)

    context = ssl.create_default_context()
    if args.insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    modes: list[tuple[str, Mapping[str, str]]] = [
        ("anonymous", {}),
        ("spoofed-service-name", {"X-Internal-Service": "plat4200-probe-spoof"}),
    ]
    if actor_token:
        modes.append(("tenant-bearer", _bearer_headers(actor_token)))

    run_public_internal_matrix(
        origin=external,
        routes=routes,
        modes=modes,
        timeout=args.timeout,
        context=context,
    )
    run_adversarial_edge_cases(
        origin=external,
        user_id=user_id,
        timeout=args.timeout,
        context=context,
    )

    if actor_token:
        verify_ordinary_actor(origin=external, token=actor_token, timeout=args.timeout, context=context)
        run_superuser_denials(origin=external, token=actor_token, timeout=args.timeout, context=context)
    else:
        _print_result("SKIP", "tenant-bearer-and-superuser-lanes", "not-configured")

    if all(cross_values):
        run_cross_tenant_lane(
            origin=external,
            token=actor_token,
            actor_org_slug=actor_org,
            other_org_slug=other_org,
            other_org_marker=other_marker,
            timeout=args.timeout,
            context=context,
        )
    else:
        _print_result("SKIP", "cross-tenant-lane", "not-configured")

    if internal_raw:
        internal = parse_origin(internal_raw, label="ADMIN_PROBE_INTERNAL_BASE_URL")
        run_internal_service_lane(
            origin=internal,
            service_token=service_token,
            service_name=_env("ADMIN_PROBE_SERVICE_NAME") or "plat4200-live-probe",
            org_id=org_id,
            user_id=user_id,
            timeout=args.timeout,
            context=context,
        )
    else:
        _print_result("SKIP", "clusterip-service-token-lane", "not-configured")

    print("PLAT-4200 live Admin isolation probe: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeFailure as exc:
        print(f"PLAT-4200 live Admin isolation probe: FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ssl.SSLError, http.client.HTTPException):
        # Network exceptions can contain URLs in their text; keep the diagnostic
        # deliberately type-only so tenant slugs and tokens never reach logs.
        print("PLAT-4200 live Admin isolation probe: FAIL network-error", file=sys.stderr)
        raise SystemExit(1)
