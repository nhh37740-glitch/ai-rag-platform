#!/bin/sh
# 替换部署环境文件中的 OPENROUTER_API_KEY。
#
# 用法：
#   sudo scripts/set_openrouter_key.sh [选项]
#
# 选项：
#   --env-file PATH   要更新的环境文件（默认 RAG_MODEL_ENV_FILE 或
#                     /home/ubuntu/.config/ai-rag/openrouter-runtime.env）
#   --key-file PATH   从权限受限的文件读取 Key（默认从标准输入读取）
#   --no-verify       跳过 OpenRouter /api/v1/key 校验（不建议）
#   --no-restart      只更新文件，不重建 ai-rag-agent-1 容器
#   -h, --help        显示帮助
#
# Key 只从标准输入或 --key-file 读取，不接收位置参数，避免进入 shell 历史或
# 进程列表。脚本不会在终端、日志或错误信息中输出完整 Key。
set -eu

ENV_FILE=${RAG_MODEL_ENV_FILE:-/home/ubuntu/.config/ai-rag/openrouter-runtime.env}
KEY_FILE=
VERIFY=1
RESTART=1
CONTAINER=ai-rag-agent-1
PROJECT=ai-rag

usage() {
    cat <<'EOF'
用法：sudo scripts/set_openrouter_key.sh [选项]

  --env-file PATH   要更新的环境文件
  --key-file PATH   从权限受限的文件读取 Key（默认从标准输入）
  --no-verify       跳过 OpenRouter Key 校验
  --no-restart      只更新文件，不重建容器
  -h, --help        显示本帮助

默认流程：从标准输入读取 Key → 调用 OpenRouter /api/v1/key 校验 →
原子替换环境文件（保留权限和属主）→ 重建 ai-rag-agent-1 → 等待健康检查。
EOF
}

fail() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --env-file)
            [ "$#" -ge 2 ] || fail "--env-file 需要路径"
            ENV_FILE=$2
            shift 2
            ;;
        --key-file)
            [ "$#" -ge 2 ] || fail "--key-file 需要路径"
            KEY_FILE=$2
            shift 2
            ;;
        --no-verify)
            VERIFY=0
            shift
            ;;
        --no-restart)
            RESTART=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf '未知参数：%s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ -n "$KEY_FILE" ]; then
    [ -r "$KEY_FILE" ] || fail "无法读取 Key 文件：$KEY_FILE"
    KEY=$(tr -d '\r\n' < "$KEY_FILE")
else
    if [ -t 0 ]; then
        command -v stty >/dev/null 2>&1 || fail "交互输入需要 stty；请改用 --key-file"
        restore_echo() { stty echo 2>/dev/null || true; }
        trap 'restore_echo' EXIT
        trap 'restore_echo; exit 130' HUP INT TERM
        # Disable echo before the prompt so input typed immediately after it
        # cannot be echoed by the terminal.
        stty -echo
        printf '请输入新的 OpenRouter API Key（输入不回显）：' >&2
        IFS= read -r KEY || true
        restore_echo
        trap - EXIT HUP INT TERM
        printf '\n' >&2
    else
        IFS= read -r KEY || true
    fi
    KEY=$(printf '%s' "$KEY" | tr -d '\r\n')
fi

[ -n "$KEY" ] || fail "未读取到 Key"
case "$KEY" in
    sk-or-v1-*) ;;
    *) fail "Key 格式不正确：应以 sk-or-v1- 开头" ;;
esac
case "$KEY" in
    *[!A-Za-z0-9_-]*) fail "Key 包含非法字符（只允许字母、数字、下划线和连字符）" ;;
esac
[ "${#KEY}" -ge 32 ] || fail "Key 长度异常（${#KEY} 个字符）"

if [ "$VERIFY" -eq 1 ]; then
    command -v curl >/dev/null 2>&1 || fail "需要 curl 才能校验 Key；可加 --no-verify 跳过"
    # Key 通过标准输入传给 curl，不出现在命令行参数中。
    status=$(printf 'header = "Authorization: Bearer %s"\n' "$KEY" \
        | curl -sS -K - -o /dev/null -w '%{http_code}' https://openrouter.ai/api/v1/key 2>/dev/null || true)
    case "$status" in
        200) ;;
        401|403) fail "OpenRouter 拒绝该 Key（HTTP $status）" ;;
        *) fail "无法校验 Key（HTTP ${status:-无响应}）；确认服务器网络后重试，或加 --no-verify" ;;
    esac
fi

[ -f "$ENV_FILE" ] || fail "环境文件不存在：$ENV_FILE（请先用部署流程创建）"
ENV_DIR=$(dirname "$ENV_FILE")
ENV_BASE=$(basename "$ENV_FILE")

KEY_TMP=$(mktemp "${TMPDIR:-/tmp}/openrouter-key.XXXXXX")
TMP_FILE=$(mktemp "$ENV_DIR/.${ENV_BASE}.XXXXXX")
cleanup() {
    rm -f "$KEY_TMP" "$TMP_FILE"
}
trap cleanup EXIT HUP INT TERM

umask 077
printf '%s\n' "$KEY" > "$KEY_TMP"
chmod 600 "$KEY_TMP"

# 只替换 OPENROUTER_API_KEY 行，保留其余配置和注释。Key 通过临时文件传给
# awk，避免出现在 awk 的命令行参数中。
awk -v keyfile="$KEY_TMP" '
    BEGIN { getline key < keyfile; close(keyfile); done = 0 }
    /^[[:space:]]*OPENROUTER_API_KEY[[:space:]]*=/ {
        print "OPENROUTER_API_KEY=" key
        done = 1
        next
    }
    { print }
    END { if (!done) print "OPENROUTER_API_KEY=" key }
' "$ENV_FILE" > "$TMP_FILE"

[ -s "$TMP_FILE" ] || fail "生成的新配置为空，未修改 $ENV_FILE"
if [ "$(id -u)" -eq 0 ]; then
    chown "$(stat -c '%u:%g' "$ENV_FILE")" "$TMP_FILE"
fi
chmod "$(stat -c '%a' "$ENV_FILE")" "$TMP_FILE"
mv -f "$TMP_FILE" "$ENV_FILE"
trap - EXIT HUP INT TERM
rm -f "$KEY_TMP"

printf 'OPENROUTER_API_KEY 已更新：%s（长度 %s，内容未输出）\n' "$ENV_FILE" "${#KEY}"

if [ "$RESTART" -eq 0 ]; then
    cat <<EOF
未重启服务。使新 Key 生效：

  cd <compose 工作目录>
  RAG_MODEL_ENV_FILE=$ENV_FILE docker compose --project-name $PROJECT up -d --no-build --force-recreate agent

或重新执行本脚本并去掉 --no-restart。
EOF
    exit 0
fi

[ "$(id -u)" -eq 0 ] || fail "重建容器需要 root；请用 sudo 运行，或加 --no-restart"
command -v docker >/dev/null 2>&1 || fail "未找到 docker；可加 --no-restart 仅更新文件"
docker container inspect "$CONTAINER" >/dev/null 2>&1 \
    || fail "未找到容器 $CONTAINER；可加 --no-restart 仅更新文件"

WORKDIR=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$CONTAINER" 2>/dev/null || true)
[ -n "$WORKDIR" ] && [ -f "$WORKDIR/compose.yaml" ] \
    || fail "无法定位 compose 工作目录（${WORKDIR:-空}）；请按部署流程重建容器"

BOOTSTRAP_ENV_FILE=${RAG_BOOTSTRAP_ENV_FILE:-/home/ubuntu/.config/ai-rag/bootstrap-admin.env}
STATE_VOLUME_NAME=${RAG_STATE_VOLUME_NAME:-ai-rag-ragnotebook-state}

printf '重建容器 %s …\n' "$CONTAINER"
(
    cd "$WORKDIR"
    RAG_MODEL_ENV_FILE=$ENV_FILE \
    RAG_BOOTSTRAP_ENV_FILE=$BOOTSTRAP_ENV_FILE \
    RAG_STATE_VOLUME_NAME=$STATE_VOLUME_NAME \
        docker compose --project-name "$PROJECT" up -d --no-build --force-recreate agent
)

attempt=0
status=unknown
while [ "$attempt" -lt 60 ]; do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo unknown)
    [ "$status" = healthy ] && break
    [ "$status" = unhealthy ] && fail "新容器健康检查失败；查看 docker logs $CONTAINER"
    sleep 5
    attempt=$((attempt + 1))
done
[ "$status" = healthy ] || fail "等待容器健康超时；查看 docker logs $CONTAINER"

config=$(curl -fsS http://127.0.0.1:18080/api/llm/config 2>/dev/null || true)
case "$config" in
    *'"server_key_configured":true'*|*'"server_key_configured": true'*) ;;
    *) fail "服务已启动，但 /api/llm/config 未报告 server_key_configured=true" ;;
esac

printf '完成：Key 已更新，容器健康，服务已加载新配置。\n'
