#!/usr/bin/env bash
# Disposable Linux CI only. The calling checkout supplies its reviewed migration.
set -euo pipefail

[[ "$(uname -s)" == Linux && "${CI:-}" == true && "${WSO_CI_DISPOSABLE_POSTGRES:-}" == 1 ]] || {
  printf 'Owned PostgreSQL requires explicit disposable Linux CI.\n' >&2
  exit 1
}

cleanup_owned() {
  local task_owner="$1"
  [[ "$task_owner" =~ ^[0-9a-f]{32}$ ]] || return 1
  local task_container="wso-ci-postgres-${task_owner}"
  local task_volume="wso-ci-postgres-data-${task_owner}"
  if docker container inspect "$task_container" >/dev/null 2>&1; then
    [[ "$(docker container inspect --format '{{index .Config.Labels "wso.ci.owner"}}' "$task_container")" == "$task_owner" ]] || return 1
    [[ "$(docker container inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' "$task_container")" == "$task_volume" ]] || return 1
    docker container rm --force "$task_container" >/dev/null
  fi
  if docker volume inspect "$task_volume" >/dev/null 2>&1; then
    [[ "$(docker volume inspect --format '{{index .Labels "wso.ci.owner"}}' "$task_volume")" == "$task_owner" ]] || return 1
    docker volume rm "$task_volume" >/dev/null
  fi
}

case "${1:-}" in
  cleanup)
    [[ -n "${WSO_CI_RUNTIME_OWNER:-}" ]] || exit 0
    cleanup_owned "$WSO_CI_RUNTIME_OWNER"
    ;;
  start)
    [[ -n "${GITHUB_ENV:-}" && -f "$GITHUB_ENV" && -n "${GITHUB_STEP_SUMMARY:-}" ]] || {
      printf 'Missing owned runner environment.\n' >&2; exit 1;
    }
    task_owner="$(python -c 'import uuid; print(uuid.uuid4().hex)')"
    [[ "$task_owner" =~ ^[0-9a-f]{32}$ ]]
    task_container="wso-ci-postgres-${task_owner}"
    task_volume="wso-ci-postgres-data-${task_owner}"
    export POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(36))')"
    printf '::add-mask::%s\n' "$POSTGRES_PASSWORD"
    printf 'WSO_CI_RUNTIME_OWNER=%s\n' "$task_owner" >> "$GITHUB_ENV"
    cleanup_failed_setup() {
      if [[ "${task_ready:-false}" != true ]]; then cleanup_owned "$task_owner"; fi
    }
    trap cleanup_failed_setup EXIT
    task_image='postgres@sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f'
    timeout 180 docker pull "$task_image"
    [[ "$(docker image inspect --format '{{index .RepoDigests 0}}' "$task_image")" == "$task_image" ]]
    printf 'PostgreSQL pulled image: %s\n' "$task_image" >> "$GITHUB_STEP_SUMMARY"
    docker volume create --label "wso.ci.owner=$task_owner" "$task_volume" >/dev/null
    docker run --detach --name "$task_container" --label "wso.ci.owner=$task_owner" \
      --env POSTGRES_PASSWORD --env POSTGRES_DB=wso_ci_test \
      --publish 127.0.0.1::5432 --log-driver none \
      --mount "type=volume,source=$task_volume,target=/var/lib/postgresql/data" \
      "$task_image" postgres -c log_statement=none -c log_min_error_statement=panic \
      -c log_connections=off -c log_disconnections=off >/dev/null
    task_started=false
    for task_attempt in $(seq 1 45); do
      if timeout 5 docker exec "$task_container" pg_isready -h 127.0.0.1 -U postgres -d wso_ci_test >/dev/null 2>&1; then
        task_started=true; break
      fi
      sleep 1
    done
    [[ "$task_started" == true ]]
    task_endpoint="$(docker port "$task_container" 5432/tcp)"
    [[ "$task_endpoint" =~ ^127\.0\.0\.1:[0-9]+$ ]]
    export WSO_CI_RUNTIME_OWNER="$task_owner"
    export WSO_CI_ADMIN_DATABASE_URL="postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@${task_endpoint}/wso_ci_test"
    printf '::add-mask::%s\n' "$WSO_CI_ADMIN_DATABASE_URL"
    .venv/bin/python scripts/dev/provision-ci-postgres.py
    unset POSTGRES_PASSWORD WSO_CI_ADMIN_DATABASE_URL
    task_ready=true
    ;;
  *) printf 'Expected start or cleanup.\n' >&2; exit 1 ;;
esac
