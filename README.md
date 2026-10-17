# Shizuha Admin

Organization, membership, team and service-access management for the Shizuha
platform, implemented in Django with a React frontend. Admin supplies organization
lifecycle and membership projection used by ID and the other platform services.

## Self hosting

Use the platform installer in [shizuha-labs/deploy](https://github.com/shizuha-labs/deploy)
with its approved source lock. The internal Forgejo workflows and Kubernetes
manifests describe the first-party deployment; configure your own environment.
The deployment installer and its acceptance results determine release readiness.

The backend requires PostgreSQL, Redis, and a configured Shizuha ID service.
Set `JWT_SECRET_KEY`, `POSTGRES_*`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`,
`ADMIN_CACHE_REDIS_URL`, `SHIZUHA_ID_API_URL`, `SHIZUHA_EXPECTED_ISSUER`,
`ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS`. Restrict browser origins with
`CORS_ALLOWED_ORIGINS`; wildcard CORS is disabled by default when `DEBUG=0`.

Route the external `/admin/api/` mount to internal `/api/`, and set
`ADMIN_PUBLIC_API_PREFIX` if using another public path. Keep `/api/internal/`
private to the service network. Configure service credentials and signing keys
through deployment secrets as documented in `shizuha_admin/settings.py`; never
commit them. The optional Connect security-event producer requires its URL and
origin secret. Kubernetes JIT dispatch requires a configured `ORIGIN_API_URL`
and dedicated dispatch credential.

Set `SYSTEM_HEALTH_SERVICES` to a JSON list of the services actually installed,
with `name`, `url`, and optional `enabled`/`optional` fields. Set `REDIS_HOST` for
the infrastructure health view. Localhost endpoints are development defaults.

## Development and validation

Dependencies are locked in `uv.lock`. Run `.ci-local-gate.sh` for the CI-equivalent
Django checks, migration check, full test suite and MCP contracts using isolated
PostgreSQL and Redis containers. Frontend commands are in `frontend/package.json`.

## License

Original Shizuha code is MIT licensed; see [LICENSE](LICENSE). Dependencies and
bundled third-party material retain their own licenses and attribution.

### Installation credentials

Set `POSTGRES_PASSWORD` and an explicit signing key before running Django.
`JWT_SECRET_KEY` keeps its existing precedence when present; otherwise supply
`SECRET_KEY`. Missing or blank selected keys/passwords refuse startup, including
with `DEBUG=False`. Explicit blank `JWT_SECRET_KEY` does not fall back to another
key. Configured bytes are preserved, so this change does not rotate keys.
Build-only static collection and disposable tests must supply their own explicit
fixtures; those fixtures are not runtime defaults.
