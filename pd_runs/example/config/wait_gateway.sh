#!/bin/bash
# ModelzooTool 的 server.cmd：等 gateway 就绪后打印 readyTag，并常驻。
# 必须常驻：e2e 的第 2 个 case 会复用这个“server”，提前退出会报
# “没有可复用的存活 server”。
#
# 用法：wait_gateway.sh <gateway_host> <gateway_port>
# 参数为空时回退环境变量，再回退 127.0.0.1:8001
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
host="${1:-${GATEWAY_HOST:-127.0.0.1}}"
port="${2:-${GATEWAY_PORT:-8001}}"
# 0.0.0.0/:: 是监听地址，不能作为连接目标
case "$host" in 0.0.0.0|::) host=127.0.0.1 ;; esac

until python3 "$SCRIPT_DIR/http_ok.py" "http://${host}:${port}/v1/models" >/dev/null 2>&1; do
    sleep 5
done
echo "GATEWAY-READY"
exec sleep infinity
