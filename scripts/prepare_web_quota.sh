#!/bin/sh
set -eu
# Only the shared counter volume is initialized; no private knowledge is mounted.
image=${1:?verified runtime image required}
sudo docker volume create ai-rag-web-quota >/dev/null
sudo docker run --rm --user 0 --entrypoint sh --network none \
    --read-only --cap-drop ALL --cap-add CHOWN --cap-add FOWNER --security-opt no-new-privileges \
    -v ai-rag-web-quota:/opt/agent/web-quota "$image" \
    -c 'chown 10001:10001 /opt/agent/web-quota; chmod 0700 /opt/agent/web-quota'
