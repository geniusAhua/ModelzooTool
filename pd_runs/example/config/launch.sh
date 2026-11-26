#!/bin/bash
# 通用入口：PATH/vendor -> 依赖检查 -> 网卡探测 -> 按 topology 启动本节点。
# 一般用每机入口脚本（start.sh、nodes/*/*.sh）；自定义节点：
#   NODE_ID=p1 PD_TOPOLOGY=/path/topology.yaml bash config/launch.sh
# 常用 env：PD_RUN_DIR、PD_TOPOLOGY、MODEL_PATH、GATEWAY_HOST/PORT、
#          LOCAL_IP/SOCKET_IFNAME/HCA_LIST、PD_PYTHON。
set -u

# 与 sglang 服务脚本一致：优先用镜像里的 conda python / mx-smi
export PATH="/opt/conda/bin:/opt/conda/condabin:/opt/maca/bin:/opt/maca/mxgpu_llvm/bin:/opt/maca/ompi/bin:/opt/maca/ucx/bin:/opt/mxdriver/bin:${PATH}"

CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="$(cd "$CONFIG_DIR/.." && pwd)"
TOOLS_DIR="$BUNDLE_DIR/tools"
export BUNDLE_DIR CONFIG_DIR

# json5/pyyaml 随包提供
export PYTHONPATH="$BUNDLE_DIR/vendor${PYTHONPATH:+:$PYTHONPATH}"

NODE_ID="${NODE_ID:-}"
if [ -z "$NODE_ID" ]; then
    echo "[launch] 必须设置 NODE_ID（或直接调 launch.py --node）" >&2
    exit 2
fi
export NODE_ID

PD_TOPOLOGY="${PD_TOPOLOGY:-$CONFIG_DIR/topology-1p1d.yaml}"
case "$PD_TOPOLOGY" in
    /*) ;;
    *) [ -f "$CONFIG_DIR/$PD_TOPOLOGY" ] && PD_TOPOLOGY="$CONFIG_DIR/$PD_TOPOLOGY" ;;
esac
export PD_TOPOLOGY
if [ ! -f "$PD_TOPOLOGY" ]; then
    echo "[launch] topology 不存在: $PD_TOPOLOGY" >&2
    exit 2
fi

# 默认放部署包内、与 ModelzooTool/ 同级的 pd-run/：包在共享盘，日志和会合文件都在共享盘
RUN_DIR="${PD_RUN_DIR:-${RUN_DIR:-$BUNDLE_DIR/pd-run}}"
if ! mkdir -p "$RUN_DIR" || ! RUN_DIR="$(cd "$RUN_DIR" && pwd)"; then
    echo "[launch] RUN_DIR 不可用: $RUN_DIR" >&2
    exit 2
fi
export PD_RUN_DIR="$RUN_DIR"
export RUN_DIR
echo "[launch] NODE_ID=$NODE_ID RUN_DIR=$RUN_DIR"

PYTHON_BIN="${PD_PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [ ! -x "$PYTHON_BIN" ]; then
    echo "[launch] 找不到 python3: $PYTHON_BIN" >&2
    exit 2
fi

check_deps() {
    "$PYTHON_BIN" -c 'import json5, yaml' >/dev/null 2>&1
}
if ! check_deps; then
    echo "[launch] 缺少 Python 依赖 (json5/pyyaml)，尝试用内网源安装 ..." >&2
    "$PYTHON_BIN" -m pip config set global.index-url https://repo.metax-tech.com/r/pypi/simple >/dev/null 2>&1 || true
    "$PYTHON_BIN" -m pip config set install.trusted-host repo.metax-tech.com >/dev/null 2>&1 || true
    timeout 180 "$PYTHON_BIN" -m pip install -q json5 pyyaml >&2 || true
fi
if ! check_deps; then
    echo "[launch] 依赖仍缺失：vendor/ 未生效或内网源不可达" >&2
    echo "[launch] 手动安装：" >&2
    echo "[launch]   pip config set global.index-url https://repo.metax-tech.com/r/pypi/simple" >&2
    echo "[launch]   pip config set install.trusted-host repo.metax-tech.com" >&2
    echo "[launch]   pip install json5 pyyaml" >&2
    exit 2
fi

# 网卡 / HCA / 本机 IP 自动探测（失败时各脚本回退默认值）；明细由 launch.py 落盘
source "$TOOLS_DIR/detect_nic.sh"

exec "$PYTHON_BIN" "$CONFIG_DIR/launch.py" \
    --node "$NODE_ID" --config "$PD_TOPOLOGY" "$@"
