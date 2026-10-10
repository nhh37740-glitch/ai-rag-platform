#!/bin/sh
set -eu

BUILD_NUMBER=${BUILD_NUMBER:?Jenkins BUILD_NUMBER is required}
PROJECT=ai-rag
IMAGE=ai-rag-platform:local
CANDIDATE="ai-rag-platform:candidate-${BUILD_NUMBER}"
BACKUP="ai-rag-platform:rollback-${BUILD_NUMBER}"
MODEL_ENV_FILE=${RAG_MODEL_ENV_FILE:-/home/ubuntu/.config/ai-rag/openrouter-runtime.env}
SMOKE_VOLUME=ai-rag-private-smoke-${BUILD_NUMBER}
SMOKE_CONTAINER=

docker() {
    sudo docker "$@"
}

compose() {
    sudo env RAG_MODEL_ENV_FILE="$MODEL_ENV_FILE" docker compose --project-name "$PROJECT" "$@"
}
cleanup() {
    if [ -n "$SMOKE_CONTAINER" ]; then docker rm -f "$SMOKE_CONTAINER" >/dev/null 2>&1 || true; fi
    docker volume rm "$SMOKE_VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

wait_for_health() {
    cid=${1:-$(compose ps -q agent 2>/dev/null || true)}
    [ -n "$cid" ] || return 1
    attempt=1
    while [ "$attempt" -le 72 ]; do
        status=$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || true)
        if [ "$status" = healthy ]; then
            return 0
        fi
        if [ "$status" = unhealthy ]; then
            return 1
        fi
        sleep 5
        attempt=$((attempt + 1))
    done
    return 1
}

show_logs() {
    compose logs --tail=100 agent || true
}

rollback_or_stop() {
    show_logs
    if [ -z "$OLD_IMAGE_ID" ]; then
        echo "No previously deployed image exists; stopping the failed first deployment." >&2
        compose stop agent || true
        docker image rm "$CANDIDATE" || true
        return 1
    fi

    echo "Restoring the previous image $OLD_IMAGE_ID." >&2
    if ! docker image tag "$BACKUP" "$IMAGE"; then
        echo "Could not restore the previous image tag; preserved backup $BACKUP." >&2
        return 1
    fi
    MODEL_ENV_FILE=$OLD_MODEL_ENV_FILE
    if compose up -d --no-build --force-recreate && wait_for_health; then
        docker image rm "$CANDIDATE" >/dev/null 2>&1 || true
        docker image rm "$BACKUP" >/dev/null 2>&1 || true
        echo "Previous image restored and healthy; named data volumes were left intact." >&2
        return 1
    fi
    show_logs
    echo "Rollback container did not become healthy; preserved $BACKUP for recovery." >&2
    return 1
}

OLD_CONTAINER_ID=$(compose ps -q agent 2>/dev/null || true)
OLD_MODEL_ENV_FILE=$MODEL_ENV_FILE
if [ -n "$OLD_CONTAINER_ID" ]; then
    OLD_IMAGE_ID=$(docker inspect --format '{{.Image}}' "$OLD_CONTAINER_ID")
    previous_model_env=$(docker inspect --format '{{index .Config.Labels "dev-knowledge.model-env-file"}}' "$OLD_CONTAINER_ID")
    [ -z "$previous_model_env" ] || OLD_MODEL_ENV_FILE=$previous_model_env
else
    OLD_IMAGE_ID=$(docker image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null || true)
fi
if [ -n "$OLD_IMAGE_ID" ]; then
    docker image tag "$OLD_IMAGE_ID" "$BACKUP"
fi

# Build the candidate under a separate tag. A build failure cannot move the
# active Compose tag or disturb the currently running service.
if ! docker build --target runtime --tag "$CANDIDATE" .; then
    docker image rm "$CANDIDATE" >/dev/null 2>&1 || true
    echo "Candidate image build failed; the active service was not changed." >&2
    exit 1
fi

sudo test -s "$MODEL_ENV_FILE"
sh scripts/prepare_web_quota.sh "$CANDIDATE"
SMOKE_CONTAINER=$(docker run -d --rm --read-only --tmpfs /tmp:size=32m \
    --tmpfs /opt/agent/data/kb/user-notebooks:uid=10001,gid=10001,mode=0700,size=8m \
    --tmpfs /opt/agent/data/agent-files:uid=10001,gid=10001,mode=0700,size=8m \
    --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 0.50 \
    --env-file "$MODEL_ENV_FILE" -e PUBLIC_DEMO=0 -e RAG_EMBED=hash \
    -e STATE_DIR=/opt/agent/state -v "$SMOKE_VOLUME:/opt/agent/state" \
    -e WEB_QUOTA_STATE_DIR=/opt/agent/web-quota -v ai-rag-web-quota:/opt/agent/web-quota \
    -p 127.0.0.1::8000 "$CANDIDATE")
wait_for_health "$SMOKE_CONTAINER"
PORT=$(docker port "$SMOKE_CONTAINER" 8000/tcp | sed -n 's/.*://p')
sudo python3 scripts/smoke_model_config.py "http://127.0.0.1:$PORT" "$MODEL_ENV_FILE"
docker rm -f "$SMOKE_CONTAINER" >/dev/null
SMOKE_CONTAINER=
if ! docker image tag "$CANDIDATE" "$IMAGE"; then
    rollback_or_stop
    exit 1
fi

if compose up -d --no-build --force-recreate && wait_for_health && \
    sudo python3 scripts/smoke_model_config.py http://127.0.0.1:18080 "$MODEL_ENV_FILE"; then
    docker image rm "$CANDIDATE" >/dev/null 2>&1 || true
    echo "Candidate image is healthy; rollback image and named data volumes were retained."
    exit 0
fi

echo "Candidate deployment failed its Compose or health check; rolling back." >&2
rollback_or_stop
exit 1
