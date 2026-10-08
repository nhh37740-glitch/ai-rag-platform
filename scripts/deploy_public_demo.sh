#!/bin/sh
set -eu

BUILD_NUMBER=${BUILD_NUMBER:?Jenkins BUILD_NUMBER is required}
IMAGE=ai-rag-public:local
CANDIDATE=ai-rag-public:candidate-${BUILD_NUMBER}
BACKUP=ai-rag-public:rollback-${BUILD_NUMBER}
ENV_FILE=${PUBLIC_DEMO_ENV_FILE:-/home/ubuntu/.config/ai-rag/public-demo.env}
SMOKE_VOLUME=ai-rag-public-smoke-${BUILD_NUMBER}
SMOKE_CONTAINER=
docker() { sudo docker "$@"; }
compose() { docker compose -f compose.public-demo.yaml --project-name ai-rag-public "$@"; }
cleanup() {
    if [ -n "$SMOKE_CONTAINER" ]; then docker rm -f "$SMOKE_CONTAINER" >/dev/null 2>&1 || true; fi
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

# Only the public image/service is selected. The private ai-rag project is untouched.
OLD_CONTAINER=$(compose ps -q agent 2>/dev/null || true)
OLD_IMAGE=
if [ -n "$OLD_CONTAINER" ]; then
    OLD_IMAGE=$(docker inspect --format '{{.Image}}' "$OLD_CONTAINER")
    docker image tag "$OLD_IMAGE" "$BACKUP"
fi
sudo test -s "$ENV_FILE"
docker build --target runtime --tag "$CANDIDATE" .
SMOKE_CONTAINER=$(docker run -d --rm --read-only --tmpfs /tmp:size=32m --cap-drop ALL \
    --security-opt no-new-privileges --memory 384m --cpus 0.50 \
    --env-file "$ENV_FILE" -e PUBLIC_DEMO=1 -e DEMO_PROVIDER=deepseek -e RAG_EMBED=hash \
    -e STATE_DIR=/opt/agent/state -v "$SMOKE_VOLUME:/opt/agent/state" \
    -p 127.0.0.1::8000 "$CANDIDATE")
wait_for_health "$SMOKE_CONTAINER"
PORT=$(docker port "$SMOKE_CONTAINER" 8000/tcp | sed -n 's/.*://p')
python3 scripts/smoke_public_demo.py "http://127.0.0.1:$PORT"
docker rm -f "$SMOKE_CONTAINER" >/dev/null
SMOKE_CONTAINER=
docker image tag "$CANDIDATE" "$IMAGE"

if compose up -d --no-build --force-recreate && \
    wait_for_health "$(compose ps -q agent)" && \
    python3 scripts/smoke_public_demo.py http://127.0.0.1:18106; then
    docker image inspect "$IMAGE" --format 'Public demo image={{.Id}}'
    echo 'Public demo deployed; private service and private volumes preserved.'
    exit 0
fi

echo 'Public demo deployment failed; restoring previous public image.' >&2
if [ -n "$OLD_IMAGE" ]; then
    docker image tag "$BACKUP" "$IMAGE"
    compose up -d --no-build --force-recreate
    wait_for_health "$(compose ps -q agent)"
    python3 scripts/smoke_public_demo.py http://127.0.0.1:18106
else
    compose stop agent || true
fi
exit 1
