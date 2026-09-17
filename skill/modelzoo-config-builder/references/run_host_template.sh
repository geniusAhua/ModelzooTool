#!/bin/bash
# ============================================================================
# ModelzooTool —— 宿主机编排脚本模板（NVIDIA / MetaX 双厂商）
#
# 作用：在宿主机上起「跑任务的容器」，把任务名交给**容器内脚本**执行
#       （容器内脚本见 references/run_template.sh）。
#
# 两个厂商的差别**只在「起容器」这一段**（镜像 / 设备节点 / 环境变量），
# 任务名、配置文件、结果目录完全共用 —— 所以按厂商各生成一份：
#   NVIDIA → run_nvidia.sh        MetaX → run_metax.sh
#
# 生成时：填好 TODO，然后**删掉另一个厂商的分支**（留着也能跑，VENDOR 决定走哪支）。
#
# 用法（宿主机上执行，不需要先进容器）：
#   bash run_nvidia.sh <task> [task ...]      # 可多个任务，按顺序跑
#   bash run_nvidia.sh --list                 # 列出 config 里的可用任务
#   bash run_nvidia.sh <task> --dry-run       # 只打印将执行的 docker 动作
#   bash run_nvidia.sh <task> --keep          # 跑完保留容器（调试）
# ============================================================================
set -uo pipefail

# ============================== TODO 1: 厂商与镜像 ==========================
VENDOR="${VENDOR:-nvidia}"                    # nvidia | metax
IMAGE_NVIDIA="${IMAGE_NVIDIA:-<nvidia 镜像>}"
IMAGE_METAX="${IMAGE_METAX:-<metax 镜像，需含对应框架版本>}"   # 例：带 vllm_metax 的 DSv4.1 镜像

# ============================== TODO 2: 路径 ===============================
WORKDIR="/abs/path/to/workdir"
SCRIPT_DIR="${WORKDIR}"
# 容器内脚本（按厂商对应）
IN_CONTAINER_NVIDIA="${SCRIPT_DIR}/run_in_container_nvidia.sh"
IN_CONTAINER_METAX="${SCRIPT_DIR}/run_in_container_metax.sh"
CONFIG="${CONFIG_FILE:-${SCRIPT_DIR}/config.jsonc}"
MODELZOO_ENTRY="/abs/path/to/ModelzooTool/bin/main.py"
LOG_DIR="${WORKDIR}/output/result"            # -o 目录：结果会再落 <config 名>/<任务名>/<时间戳>

# 执行用户（容器内按这个 uid/gid 建用户，产物属主与宿主机一致）
RUN_UID="$(id -u)"; RUN_GID="$(id -g)"; RUN_USER="$(id -un)"

# ============================== 可选参数（按需保留） =======================
CONTAINER="${CONTAINER:-mz-run-${RUN_USER}}"
KEEP="${KEEP:-0}"
DRY_RUN="${DRY_RUN:-0}"
TASKS=()

# =================== TODO 3: 选加速卡（配置里不要写死） ====================
# NVIDIA：docker --gpus '"device=0,1"'（或 --gpus all）
# MetaX ：设备节点 + CUDA_VISIBLE_DEVICES（die 号）
GPU_NVIDIA="${GPU_NVIDIA:-all}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3,4,5,6,7}"
export CUDA_VISIBLE_DEVICES

usage() {
    cat <<'EOF'
用法:
  bash <本脚本> <task> [task ...]     # 跑指定任务（可多个，按顺序）
  bash <本脚本> --list                # 列出 config 里的可用任务
  bash <本脚本> <task> --dry-run      # 只打印将执行的 docker 动作
  bash <本脚本> <task> --keep         # 跑完保留容器
  bash <本脚本> --help

可选参数: --task <name...> | --image <img> | --name <容器名> | --config <path> | --keep | --dry-run
EOF
}

die()  { echo "[error] $*" >&2; exit 1; }
warn() { echo "[warn ] $*" >&2; }
info() { echo "[info ] $*"; }

available_tasks() {
    [ -f "${CONFIG}" ] || return 0
    sed -nE 's/^ {4}"([A-Za-z0-9_-]+)": \{.*/\1/p' "${CONFIG}" | grep -vxE 'task_info|server|client'
}

# ============================== 参数解析 ===================================
LIST=0
while [ $# -gt 0 ]; do
    case "$1" in
        --task)  shift; while [ $# -gt 0 ]; do case "$1" in -*) break ;; *) TASKS+=("$1"); shift ;; esac; done ;;
        --image) IMAGE_OVERRIDE="$2"; shift 2 ;;
        --name)  CONTAINER="$2"; shift 2 ;;
        --config) CONFIG="$2"; shift 2 ;;
        --keep)  KEEP=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --list)  LIST=1; shift ;;
        -h|--help) usage; exit 0 ;;
        -*) die "未知参数: $1" ;;
        *)  TASKS+=("$1"); shift ;;
    esac
done

if [ "${LIST}" = "1" ]; then
    available_tasks | sed 's/^/  /'
    exit 0
fi
[ ${#TASKS[@]} -gt 0 ] || { echo "未指定任务名，可用任务：" >&2; available_tasks | sed 's/^/  /' >&2; exit 2; }

# 任务名先在本地校验，避免拼错后白起一次容器
AVAIL="$(available_tasks)"
if [ -n "${AVAIL}" ]; then
    for t in "${TASKS[@]}"; do
        printf '%s\n' "${AVAIL}" | grep -Fxq "${t}" \
            || die "config 里没有任务: ${t}（可用: $(printf '%s ' ${AVAIL})）"
    done
fi

# ============================== TODO 4: 厂商分支 ===========================
case "${VENDOR}" in
    nvidia)
        IMAGE="${IMAGE_OVERRIDE:-${IMAGE_NVIDIA}}"
        IN_CONTAINER="${IN_CONTAINER_NVIDIA}"
        # NVIDIA：--gpus 选卡；默认 --rm（退出即删），--keep 时不加
        rm_arg=(); [ "${KEEP}" = "1" ] || rm_arg=(--rm)
        docker_args=(
            "${rm_arg[@]}" --gpus "${GPU_NVIDIA}"
            --network host --ipc host --shm-size 64g --privileged
            --ulimit memlock=-1:-1
            -v /sw_home:/sw_home -v /mxstorage:/mxstorage
            -e http_proxy="${PROXY:-}" -e https_proxy="${PROXY:-}"
            -e no_proxy="${NO_PROXY:-localhost,127.0.0.1}"
            -e MODELZOO_RUN_UID="${RUN_UID}" -e MODELZOO_RUN_GID="${RUN_GID}"
            -e MODELZOO_RUN_USER="${RUN_USER}"
            -e PYTHONUNBUFFERED=1
        )
        ;;
    metax)
        IMAGE="${IMAGE_OVERRIDE:-${IMAGE_METAX}}"
        IN_CONTAINER="${IN_CONTAINER_METAX}"
        # MetaX：设备节点必须挂（/dev/dri /dev/mxcd /dev/infiniband）+ --group-add video
        #   --device=/dev/mem：部分算子/工具需要；--network=host：client 直连 127.0.0.1
        docker_args=(
            -dit --name "${CONTAINER}"
            --device=/dev/dri --device=/dev/mxcd --device=/dev/infiniband --group-add video
            --uts=host --ipc=host --device=/dev/mem --network=host
            --security-opt apparmor=unconfined --security-opt seccomp=unconfined
            --shm-size 100gb --ulimit memlock=-1
            -v /sw_home:/sw_home -v /mxstorage:/mxstorage
            -e CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES}"
            -e MODELZOO_RUN_UID="${RUN_UID}" -e MODELZOO_RUN_GID="${RUN_GID}" -e MODELZOO_RUN_USER="${RUN_USER}"
            -e PYTHONUNBUFFERED=1
        )
        ;;
    *) die "VENDOR 只能是 nvidia | metax（当前 ${VENDOR}）" ;;
esac

# 前置检查：镜像要先在本机存在（离线机器尤其容易漏）
if [ "${DRY_RUN}" = "0" ]; then
    docker image inspect "${IMAGE}" >/dev/null 2>&1 || die "本机没有镜像 ${IMAGE}"
fi

# ============================== TODO 5: 起容器并跑 =========================
if [ "${DRY_RUN}" = "1" ]; then
    echo "[dry-run] docker run"; printf ' %q' "${docker_args[@]}"; echo " ${IMAGE}"
    printf '  docker exec -i %q bash %q' "${CONTAINER}" "${IN_CONTAINER}"; printf ' %q' "${TASKS[@]}"; echo
    exit 0
fi

case "${VENDOR}" in
    nvidia)
        # 注意：vLLM 镜像 entrypoint 是 "vllm serve"，务必 --entrypoint /bin/bash 覆盖
        docker rm -f "${CONTAINER}" >/dev/null 2>&1
        docker run "${docker_args[@]}" --name "${CONTAINER}" --entrypoint /bin/bash "${IMAGE}" \
            /bin/bash "${IN_CONTAINER}" "${TASKS[@]}"
        RC=$?
        ;;
    metax)
        docker rm -f "${CONTAINER}" >/dev/null 2>&1
        docker run "${docker_args[@]}" "${IMAGE}" bash >/dev/null || die "docker run 失败"
        docker exec -i \
            -e CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES}" \
            -e MODELZOO_RUN_UID="${RUN_UID}" -e MODELZOO_RUN_GID="${RUN_GID}" -e MODELZOO_RUN_USER="${RUN_USER}" \
            -e MODELZOO_BIN="${MODELZOO_ENTRY}" -e CONFIG="${CONFIG}" -e LOG_DIR="${LOG_DIR}" \
            "${CONTAINER}" bash "${IN_CONTAINER}" "${TASKS[@]}"
        RC=$?
        [ "${KEEP}" = "1" ] || docker rm -f "${CONTAINER}" >/dev/null 2>&1
        ;;
esac

echo "结果目录: ${LOG_DIR}/<config 名>/<任务名>/<时间戳>/"
exit "${RC}"
