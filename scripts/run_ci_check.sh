#!/bin/sh
# 每个测试步骤保留失败容器的 JUnit，再清理容器；不把凭据写入镜像。
set -eu
image=${1:?测试镜像必填}
shift
mkdir -p reports
cid=
cleanup() {
    if [ -n "$cid" ]; then sudo docker rm -f "$cid" >/dev/null; fi
}
trap cleanup EXIT HUP INT TERM
if [ -n "${CI_ENV_FILE:-}" ]; then
    cid=$(sudo docker create --env RAG_EMBED=hash --env-file "$CI_ENV_FILE" --entrypoint python "$image" "$@")
else
    cid=$(sudo docker create --env RAG_EMBED=hash --entrypoint python "$image" "$@")
fi
status=0
sudo docker start -a "$cid" || status=$?
container_status=$(sudo docker inspect --format '{{.State.ExitCode}}' "$cid")
if [ "$container_status" -ne 0 ]; then status=$container_status; fi
# A syntax/import failure can happen before pytest creates a report.
sudo docker cp "$cid:/opt/agent/reports/." reports/ || true
exit "$status"
