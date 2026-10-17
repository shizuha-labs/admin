#!/bin/bash
# Local mirror of ci-test-admin's Postgres/Redis dependencies and test extras.
# Full Django discovery includes organizations.test_ci_job_cleanup_policy and
# every CI authz module. Keep the cached database and serial execution because
# the authorization tests exercise shared Redis nonce state.
set -euo pipefail
# Concurrent gate runs share the admin-gate-pgdata volume: two postgres
# containers on one data dir corrupt it (then every later run wedges in crash
# recovery). flock queues concurrent pushes; 15min cap then fail loud.
exec 9>/tmp/admin-gate.volume.lock
flock -w 900 9 || { echo "gate: another gate run held the lock >15min — investigate (docker ps | grep admin-gate)" >&2; exit 1; }
cd "$(git rev-parse --show-toplevel)"
echo "gate: uv lock consistency"
command -v uv >/dev/null 2>&1 || {
  echo "gate: uv is required to verify pyproject.toml against uv.lock" >&2
  exit 1
}
env -u UV_DEFAULT_INDEX -u UV_INDEX_URL -u UV_INSECURE_HOST \
  uv lock --check --no-progress
IMG="${SHIZUHA_CI_IMAGE:-}"
[ -z "$IMG" ] && command -v kubectl >/dev/null 2>&1 && IMG=$(kubectl get deploy -n shizuha shizuha-admin -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)
IMG="${IMG:-localhost:30500/shizuha-admin:admin-ba8f1ac}"
NET="admin-gate-$$"; PG="admin-gate-pg-$$"; REDIS="admin-gate-redis-$$"
cleanup() { docker stop -t 20 "$PG" "$REDIS" >/dev/null 2>&1 || true; docker rm -f "$PG" "$REDIS" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker volume create admin-gate-pgdata >/dev/null
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -v admin-gate-pgdata:/var/lib/postgresql/data -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=shizuha_admin_ci postgres:16-alpine >/dev/null
wait_pg() {
  for _i in $(seq 1 90); do
    docker exec "$PG" psql -U postgres -h 127.0.0.1 -c "SELECT 1" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}
if ! wait_pg; then
  # Cached volume wedged (interrupted WAL recovery etc.) — it is only a cache:
  # recreate it fresh and retry once (next run repays migrations, then warm again).
  echo "gate: postgres not ready — recreating cache volume admin-gate-pgdata and retrying" >&2
  docker rm -f "$PG" >/dev/null 2>&1
  docker volume rm admin-gate-pgdata >/dev/null 2>&1
  docker volume create admin-gate-pgdata >/dev/null
  docker run -d --name "$PG" --network "$NET" -v admin-gate-pgdata:/var/lib/postgresql/data -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=shizuha_admin_ci postgres:16-alpine >/dev/null
  wait_pg || { echo "gate: postgres STILL not ready — aborting" >&2; exit 1; }
fi
docker run -d --name "$REDIS" --network "$NET" redis:7-alpine >/dev/null
wait_redis() {
  for _i in $(seq 1 30); do
    docker exec "$REDIS" redis-cli ping 2>/dev/null | grep -qx PONG && return 0
    sleep 1
  done
  return 1
}
wait_redis || { echo "gate: Redis not ready — aborting" >&2; exit 1; }
echo "gate: image=$IMG"
docker run --rm --network "$NET" \
  -v "$PWD/organizations":/app/organizations -v "$PWD/shizuha_admin":/app/shizuha_admin \
  -v "$PWD/.forgejo":/app/.forgejo:ro \
  -v "$PWD/.ci-local-gate.sh":/app/.ci-local-gate.sh:ro \
  -v "$PWD/scripts":/app/scripts:ro -v "$PWD/mcp-server":/app/mcp-server:ro \
  -e POSTGRES_HOST="$PG" -e POSTGRES_PORT=5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=shizuha_admin_ci \
  -e ADMIN_CACHE_REDIS_URL="redis://$REDIS:6379/3" -e CELERY_BROKER_URL="redis://$REDIS:6379/3" \
  -e DEBUG=0 -e SECRET_KEY=ci-secret -e JWT_SECRET_KEY=ci-secret \
  "$IMG" bash -c '
    set -euo pipefail
    python manage.py check
    python manage.py makemigrations --check --dry-run
    python manage.py test --noinput --keepdb
    python scripts/test_plat4779_ledger_dedup.py
    cd mcp-server
    SHIZUHA_ADMIN_URL=http://admin-ci.invalid python -m unittest \
      test_plat4927_org_service_member test_plat5096_su_set_user_services test_token_verifier
  '
