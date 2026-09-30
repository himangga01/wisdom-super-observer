#!/usr/bin/env bash
# Synthetic fixture smoke only. T05 worker delivery/reconciliation is a later gate.
set -euo pipefail
[[ "${CI:-}" == true ]] || { printf 'Disposable CI opt-in is required.\n' >&2; exit 1; }
task_owner="$(python -c 'import uuid; print(uuid.uuid4().hex)')"
task_container="wso-ci-valkey-${task_owner}"
task_empty_container="wso-ci-valkey-empty-${task_owner}"
task_volume="wso-ci-valkey-data-${task_owner}"
task_empty_volume="wso-ci-valkey-empty-data-${task_owner}"
task_tag='valkey/valkey:9.1.2-alpine3.24'

cleanup() {
  local task_resource task_label
  for task_resource in "$task_container" "$task_empty_container"; do
    if docker container inspect "$task_resource" >/dev/null 2>&1; then
      task_label="$(docker container inspect --format '{{index .Config.Labels "wso.ci.owner"}}' "$task_resource")"
      if [[ "$task_label" != "$task_owner" ]]; then
        printf 'Cleanup refused: container ownership mismatch.\n' >&2
        return 1
      fi
      docker container rm --force "$task_resource" >/dev/null
    fi
  done
  for task_resource in "$task_volume" "$task_empty_volume"; do
    if docker volume inspect "$task_resource" >/dev/null 2>&1; then
      task_label="$(docker volume inspect --format '{{index .Labels "wso.ci.owner"}}' "$task_resource")"
      if [[ "$task_label" != "$task_owner" ]]; then
        printf 'Cleanup refused: volume ownership mismatch.\n' >&2
        return 1
      fi
      docker volume rm "$task_resource" >/dev/null
    fi
  done
}
trap cleanup EXIT

ready() {
  local task_attempt
  for task_attempt in $(seq 1 45); do
    if timeout 5 docker exec "$1" valkey-cli ping 2>/dev/null | tr -d '\r' | grep -qx PONG; then
      return 0
    fi
    sleep 1
  done
  printf 'Valkey readiness deadline exceeded.\n' >&2
  return 1
}

start_fixture() {
  docker volume create --label "wso.ci.owner=$task_owner" "$2" >/dev/null
  docker run --detach --name "$1" --label "wso.ci.owner=$task_owner" \
    --publish 127.0.0.1::6379 --log-driver none \
    --mount "type=volume,source=$2,target=/data" \
    "$task_image" valkey-server --appendonly yes --appendfsync always \
    --save '' --maxmemory 128mb --maxmemory-policy noeviction >/dev/null
  ready "$1"
}

timeout 180 docker pull "$task_tag"
task_image="$(docker image inspect --format '{{index .RepoDigests 0}}' "$task_tag")"
[[ "$task_image" =~ ^valkey/valkey@sha256:[0-9a-f]{64}$ ]] || {
  printf 'Pulled Valkey digest identity is invalid.\n' >&2; exit 1;
}
start_fixture "$task_container" "$task_volume"
docker exec "$task_container" valkey-cli INFO server | tr -d '\r' | grep -qx 'valkey_version:9.1.2'
docker exec "$task_container" valkey-cli INFO persistence | tr -d '\r' | grep -qx 'aof_enabled:1'
[[ "$(docker exec "$task_container" valkey-cli SET wso:ci:restart preserved | tr -d '\r')" == OK ]]
[[ "$(docker exec "$task_container" valkey-cli RPUSH wso:ci:queue synthetic-reference | tr -d '\r')" == 1 ]]
docker kill --signal KILL "$task_container" >/dev/null
docker start "$task_container" >/dev/null
ready "$task_container"
[[ "$(docker exec "$task_container" valkey-cli GET wso:ci:restart | tr -d '\r')" == preserved ]]
[[ "$(docker exec "$task_container" valkey-cli LPOP wso:ci:queue | tr -d '\r')" == synthetic-reference ]]

# Prove that a separately owned new volume supplies an empty broker fixture.
# T05 must later prove DB reconciliation through this loss, with real workers.
start_fixture "$task_empty_container" "$task_empty_volume"
[[ "$(docker exec "$task_empty_container" valkey-cli DBSIZE | tr -d '\r')" == 0 ]]
[[ "$(docker exec "$task_container" valkey-cli GET wso:ci:restart | tr -d '\r')" == preserved ]]
mkdir -p .superpowers/verification
printf 'Valkey 9.1.2\nPulled image: %s\nPING, AOF SIGKILL/restart, isolated empty volume: passed\nT05 worker delivery and DB reconciliation: pending\n' \
  "$task_image" | tee .superpowers/verification/valkey-runtime.txt
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  cat .superpowers/verification/valkey-runtime.txt >> "$GITHUB_STEP_SUMMARY"
fi
