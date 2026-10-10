#!/bin/sh
set -eu

BUILD_NUMBER=${BUILD_NUMBER:?Jenkins BUILD_NUMBER is required}
ENV_FILE=${RAG_ADMIN_ENV_FILE:-/home/ubuntu/.config/ai-rag/admin-workspace.env}
MODEL_ENV_FILE=${RAG_MODEL_ENV_FILE:-/home/ubuntu/.config/ai-rag/openrouter-runtime.env}
IMAGE=ai-rag-admin:local
CANDIDATE=ai-rag-admin:candidate-${BUILD_NUMBER}
BACKUP=ai-rag-admin:rollback-${BUILD_NUMBER}
SMOKE_VOLUME=ai-rag-admin-smoke-${BUILD_NUMBER}
SMOKE_AGENT=
SMOKE_LOGIN=
docker() { sudo docker "$@"; }
compose() {
    sudo env RAG_ADMIN_ENV_FILE="$ENV_FILE" RAG_MODEL_ENV_FILE="$MODEL_ENV_FILE" \
        docker compose -f compose.admin.yaml --project-name ai-rag-admin "$@"
}
cleanup() {
    if [ -n "$SMOKE_AGENT" ]; then docker rm -f "$SMOKE_AGENT" >/dev/null 2>&1 || true; fi
    if [ -n "$SMOKE_LOGIN" ]; then docker rm -f "$SMOKE_LOGIN" >/dev/null 2>&1 || true; fi
    docker volume rm "$SMOKE_VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM
wait_for_health() {
    candidate_id=$1
    attempt=1
    while [ "$attempt" -le 60 ]; do
        status=$(docker inspect --format '{{.State.Health.Status}}' "$candidate_id" 2>/dev/null || true)
        [ "$status" != unhealthy ] || return 1
        [ "$status" != healthy ] || return 0
        sleep 3
        attempt=$((attempt + 1))
    done
    return 1
}

# This project never selects the original ai-rag or public ai-rag-public services.
sudo test -s "$ENV_FILE"
sudo test -s "$MODEL_ENV_FILE"
OLD_CONTAINER=$(compose ps -q agent 2>/dev/null || true)
OLD_IMAGE=
OLD_ENV_FILE=$ENV_FILE
OLD_MODEL_ENV_FILE=$MODEL_ENV_FILE
if [ -n "$OLD_CONTAINER" ]; then
    OLD_IMAGE=$(docker inspect --format '{{.Image}}' "$OLD_CONTAINER")
    OLD_ENV_FILE=$(docker inspect --format '{{index .Config.Labels "dev-knowledge.admin-env-file"}}' "$OLD_CONTAINER")
    OLD_MODEL_ENV_FILE=$(docker inspect --format '{{index .Config.Labels "dev-knowledge.admin-model-env-file"}}' "$OLD_CONTAINER")
    # Legacy releases have only the private auth environment, without an LLM file.
    [ -n "$OLD_MODEL_ENV_FILE" ] || OLD_MODEL_ENV_FILE=$OLD_ENV_FILE
    [ -n "$OLD_ENV_FILE" ] && sudo test -s "$OLD_ENV_FILE"
    docker image tag "$OLD_IMAGE" "$BACKUP"
fi
VERIFIED_IMAGE=${RAG_ADMIN_VERIFIED_IMAGE:-}
if [ -n "$VERIFIED_IMAGE" ]; then
    case "$VERIFIED_IMAGE" in sha256:*) ;; *) echo 'Verified image must be an immutable SHA256 ID' >&2; exit 1 ;; esac
    [ "${#VERIFIED_IMAGE}" -eq 71 ] || exit 1
    case "${VERIFIED_IMAGE#sha256:}" in *[!0-9a-f]*) exit 1 ;; esac
    [ "$(docker image inspect --format '{{.Id}}' "$VERIFIED_IMAGE")" = "$VERIFIED_IMAGE" ] || exit 1
    # Caller must verify this exact image passed the complete Jenkins gates.
    # Candidate write/retrieval and final smoke below still execute afresh.
    docker image tag "$VERIFIED_IMAGE" "$CANDIDATE"
else
    docker build --target runtime --tag "$CANDIDATE" .
fi
sh scripts/prepare_web_quota.sh "$CANDIDATE"
SMOKE_AGENT=$(docker run -d --rm --read-only --tmpfs /tmp:size=32m \
    --tmpfs /opt/agent/data/kb/user-notebooks:uid=10001,gid=10001,mode=0700,size=8m \
    --tmpfs /opt/agent/data/agent-files:uid=10001,gid=10001,mode=0700,size=8m \
    --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 0.50 \
    --env-file "$ENV_FILE" --env-file "$MODEL_ENV_FILE" \
    -e PUBLIC_DEMO=0 -e RAG_ADMIN_AUTH=proxy -e RAG_EMBED=hash \
    -e DEEPSEEK_API_KEY= -e STATE_DIR=/opt/agent/state \
    -v "$SMOKE_VOLUME:/opt/agent/state" \
    -e WEB_QUOTA_STATE_DIR=/opt/agent/web-quota -v ai-rag-web-quota:/opt/agent/web-quota \
    -p 127.0.0.1::8000 "$CANDIDATE")
SMOKE_LOGIN=$(docker run -d --rm --read-only --tmpfs /tmp:size=8m \
    --cap-drop ALL --security-opt no-new-privileges --memory 128m --cpus 0.25 \
    --add-host host.docker.internal:host-gateway --env-file "$ENV_FILE" \
    --health-cmd "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).read()\"" \
    --health-start-period 15s --health-interval 10s \
    -p 127.0.0.1::8000 "$CANDIDATE" python -m uvicorn --app-dir apps/agent-server \
    admin_login:app_factory --factory --host 0.0.0.0 --port 8000)
wait_for_health "$SMOKE_AGENT"
wait_for_health "$SMOKE_LOGIN"
AGENT_PORT=$(docker port "$SMOKE_AGENT" 8000/tcp | sed -n 's/.*://p')
LOGIN_PORT=$(docker port "$SMOKE_LOGIN" 8000/tcp | sed -n 's/.*://p')
sudo python3 scripts/smoke_admin_workspace.py "http://127.0.0.1:$AGENT_PORT" "http://127.0.0.1:$LOGIN_PORT" "$ENV_FILE" --model-env-file "$MODEL_ENV_FILE" --write
docker rm -f "$SMOKE_AGENT" "$SMOKE_LOGIN" >/dev/null
SMOKE_AGENT=
SMOKE_LOGIN=
docker image tag "$CANDIDATE" "$IMAGE"
if compose up -d --no-build --force-recreate && \
    wait_for_health "$(compose ps -q agent)" && wait_for_health "$(compose ps -q login)" && \
    sudo python3 scripts/smoke_admin_workspace.py http://127.0.0.1:18108 http://127.0.0.1:18107 "$ENV_FILE" --model-env-file "$MODEL_ENV_FILE"; then
    echo 'Owner workspace deployed on loopback 18108/18107; public and original private data preserved.'
    exit 0
fi
echo 'Owner workspace deployment failed; restoring previous administrator services.' >&2
if [ -n "$OLD_IMAGE" ]; then
    ENV_FILE=$OLD_ENV_FILE
    MODEL_ENV_FILE=$OLD_MODEL_ENV_FILE
    docker image tag "$BACKUP" "$IMAGE"
    compose up -d --no-build --force-recreate
    wait_for_health "$(compose ps -q agent)"
    wait_for_health "$(compose ps -q login)"
    sudo python3 scripts/smoke_admin_workspace.py http://127.0.0.1:18108 http://127.0.0.1:18107 "$ENV_FILE" --model-env-file "$MODEL_ENV_FILE"
else
    compose stop || true
fi
exit 1
