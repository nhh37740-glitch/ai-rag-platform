#!/bin/sh
set -eu

BUILD_NUMBER=${BUILD_NUMBER:?Jenkins BUILD_NUMBER is required}
PROJECT=ai-rag
IMAGE=ai-rag-platform:local
CANDIDATE="ai-rag-platform:candidate-${BUILD_NUMBER}"
BACKUP="ai-rag-platform:rollback-${BUILD_NUMBER}"

docker() {
    sudo docker "$@"
}

compose() {
    docker compose --project-name "$PROJECT" "$@"
}

wait_for_health() {
    cid=$(compose ps -q agent 2>/dev/null || true)
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
if [ -n "$OLD_CONTAINER_ID" ]; then
    OLD_IMAGE_ID=$(docker inspect --format '{{.Image}}' "$OLD_CONTAINER_ID")
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

if ! docker image tag "$CANDIDATE" "$IMAGE"; then
    rollback_or_stop
    exit 1
fi

if compose up -d --no-build --force-recreate && wait_for_health; then
    docker image rm "$BACKUP" >/dev/null 2>&1 || true
    docker image rm "$CANDIDATE" >/dev/null 2>&1 || true
    echo "Candidate image is healthy; named data volumes were left intact."
    exit 0
fi

echo "Candidate deployment failed its Compose or health check; rolling back." >&2
rollback_or_stop
exit 1
