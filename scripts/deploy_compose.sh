#!/bin/sh
set -eu

BUILD_NUMBER=${BUILD_NUMBER:?Jenkins BUILD_NUMBER is required}
PROJECT=ai-rag
IMAGE=ai-rag-platform:local
CANDIDATE="ai-rag-platform:candidate-${BUILD_NUMBER}"
MODEL_ENV_FILE=${RAG_MODEL_ENV_FILE:-/home/ubuntu/.config/ai-rag/openrouter-runtime.env}
BOOTSTRAP_ENV_FILE=${RAG_BOOTSTRAP_ENV_FILE:-/home/ubuntu/.config/ai-rag/bootstrap-admin.env}
STATE_VOLUME_NAME=${RAG_STATE_VOLUME_NAME:-ai-rag-ragnotebook-state}
SMOKE_VOLUME=ai-rag-private-smoke-${BUILD_NUMBER}
SMOKE_CONTAINER=

docker() {
    sudo docker "$@"
}

compose() {
    sudo env RAG_MODEL_ENV_FILE="$MODEL_ENV_FILE" RAG_BOOTSTRAP_ENV_FILE="$BOOTSTRAP_ENV_FILE" RAG_STATE_VOLUME_NAME="$STATE_VOLUME_NAME" docker compose --project-name "$PROJECT" "$@"
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

# Build the candidate under a separate tag. A build failure cannot move the
# active Compose tag or disturb the currently running service.
if ! docker build --target runtime --tag "$CANDIDATE" .; then
    docker image rm "$CANDIDATE" >/dev/null 2>&1 || true
    echo "Candidate image build failed; the active service was not changed." >&2
    exit 1
fi

sudo test -s "$MODEL_ENV_FILE"
sudo test -s "$BOOTSTRAP_ENV_FILE"
SMOKE_CONTAINER=$(docker run -d --rm --read-only --tmpfs /tmp:size=32m \
    --tmpfs /opt/agent/data/kb/user-notebooks:uid=10001,gid=10001,mode=0700,size=8m \
    --tmpfs /opt/agent/data/agent-files:uid=10001,gid=10001,mode=0700,size=8m \
    --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 0.50 \
    --env-file "$MODEL_ENV_FILE" --env-file "$BOOTSTRAP_ENV_FILE" -e PUBLIC_DEMO=0 -e RAG_EMBED=fastembed \
    -e BGE_MODEL=BAAI/bge-small-zh-v1.5 -e FASTEMBED_CACHE_PATH=/opt/agent/models/fastembed_cache \
    -e STATE_DIR=/opt/agent/state -v "$SMOKE_VOLUME:/opt/agent/state" \
    -v "${PROJECT}_model-cache:/opt/agent/models/fastembed_cache" \
    -p 127.0.0.1::8000 "$CANDIDATE")
wait_for_health "$SMOKE_CONTAINER"
PORT=$(docker port "$SMOKE_CONTAINER" 8000/tcp | sed -n 's/.*://p')
sudo python3 scripts/smoke_model_config.py "http://127.0.0.1:$PORT" "$MODEL_ENV_FILE"
docker rm -f "$SMOKE_CONTAINER" >/dev/null
SMOKE_CONTAINER=
docker image tag "$CANDIDATE" "$IMAGE"

if ! compose up -d --no-build --force-recreate || ! wait_for_health || \
    ! sudo python3 scripts/smoke_model_config.py http://127.0.0.1:18080 "$MODEL_ENV_FILE"; then
    show_logs
    compose stop agent || true
    echo "Unified RAGnotebook deployment failed; no old service was restored. Data volumes were preserved." >&2
    exit 1
fi

# Route the existing RAG web URL to this service before removing its old
# upstreams. The gateway script checks and reloads only the RAG route.
if ! sudo python3 scripts/switch_rag_gateway.py; then
    echo "Unified service is healthy, but RAG gateway switch failed; legacy containers remain." >&2
    exit 1
fi

# The new application serves guest and admin traffic in one process. Retire
# only the three former RAG containers; Docker volumes are never removed here.
for legacy in ai-rag-public-agent-1 ai-rag-admin-agent-1 ai-rag-admin-login-1; do
    if docker container inspect "$legacy" >/dev/null 2>&1; then
        docker rm -f "$legacy" >/dev/null
    fi
done

docker image rm "$CANDIDATE" >/dev/null 2>&1 || true
echo "Unified RAGnotebook is healthy; legacy RAG containers removed and data volumes preserved."
