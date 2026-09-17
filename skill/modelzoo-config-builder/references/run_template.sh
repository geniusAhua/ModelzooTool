#!/bin/bash
# ============================================================================
# ModelzooTool —— 容器内执行脚本模板（NVIDIA / MetaX 双厂商）
#
# 由宿主机编排脚本调用（见 references/run_host_template.sh），一般无需手动执行。
#
# 两阶段执行：
#   1) root 阶段   ：配 pip 源 → 装 ModelzooTool 依赖(json5) → 按宿主 uid/gid 建执行用户
#   2) 执行用户阶段：跑 ModelzooTool（MetaX 额外：export MACA_* 环境变量）
#
# 生成时按目标厂商保留对应分支、删掉另一厂商的分支：
#   NVIDIA → run_in_container_nvidia.sh      MetaX → run_in_container_metax.sh
#
# 为什么切用户：容器默认 root，直接跑会让 output/ 下的日志/结果变成 root 所有，
#   宿主机用户处理不了。这里按宿主机 uid/gid 建用户切过去，**只对齐 uid/gid，不对齐 HOME**
#   （HOME 留在容器内 /home/<user>，避免读写宿主的 ~/.bashrc、~/.config/pip、~/.cache、~/.local）。
#
# MetaX（沐曦）与 NVIDIA 的差异（全部是**镜像差异**，不是任务差异）：
#   ① 非交互 PATH 里只有 /usr/bin/python3（既无 pip 也无 vllm），真环境在 /opt/conda/bin
#      （交互式 shell 靠 /etc/profile.d/conda.sh 才把它加进 PATH；`docker exec … bash xx.sh`
#       这类非交互调用**不读**它）→ 先探测并前置，再用**与 vllm 同目录**的解释器装依赖/跑任务
#   ② /dev/dri/*、/dev/mxcd 属 root:video(660)，而 `su` 会按 /etc/group **重置补组**
#      → 执行用户必须 `usermod -aG video,root`，否则设备初始化失败：
#        `[MCTLASSEX][E]utils.cpp get device failed, ret=initialization error` → Segmentation fault
#   ③ 需要 MACA_* 环境变量（MACA_PATH / MACA_SMALL_PAGESIZE_ENABLE / MACA_DIRECT_DISPATCH /
#      LD_LIBRARY_PATH / PATH）—— 直接 export，**不要**写进 .bashrc（非交互路径不读它）
#
# 参数：任务名列表（config 里的任务段名，可多个）
# 由宿主机脚本经 docker run/exec -e 传入：CUDA_VISIBLE_DEVICES、MODELZOO_RUN_{UID,GID,USER}、
#                                        MODELZOO_BIN、CONFIG、LOG_DIR、MODELZOO_VENDOR
# ============================================================================
set -o pipefail

VENDOR="${MODELZOO_VENDOR:-nvidia}"        # nvidia | metax
TASKS="$*"
if [ -z "${TASKS}" ]; then
    echo "用法: <本脚本> <task> [task ...]" >&2
    exit 2
fi

SELF="$(readlink -f "${BASH_SOURCE[0]}")"

# ============================== TODO 1: 路径 ================================
MODELZOO_ENTRY="${MODELZOO_BIN:-<ModelzooTool>/bin/main.py}"   # 建议由宿主机脚本 -e 传入
CONFIG="${CONFIG:-<绝对路径>/config.jsonc}"
LOG_DIR="${LOG_DIR:-<绝对路径>/output/result}"                 # -o：结果再落 <config 名>/<任务名>/<时间戳>

# ============================== TODO 2: 执行用户 ============================
# 由宿主机脚本从宿主机传入，保证容器内产物属主 == 宿主机用户
RUN_UID="${MODELZOO_RUN_UID:-}"
RUN_GID="${MODELZOO_RUN_GID:-}"
RUN_USER="${MODELZOO_RUN_USER:-}"

# ============================== TODO 3: pip 源 ==============================
# 内网镜像（PyPI 直连可能超时）；公网机器换成公司/官方源或留空
PIP_INDEX="${PIP_INDEX_OVERRIDE:-https://repo.metax-tech.com/r/pypi/simple}"
PIP_TRUSTED="${PIP_TRUSTED_OVERRIDE:-repo.metax-tech.com}"

# ---------- 第一阶段（root）：前置环境 + 装依赖 + 建执行用户，再以执行用户重跑本脚本 ----------
if [ "$(id -u)" = "0" ] && [ -n "${RUN_UID}" ] && [ "${RUN_UID}" != "0" ]; then
    # ★ MetaX 分支 ①：非交互 PATH 不含 /opt/conda/bin（vllm / pip / python3 都在那里）→ 探测并前置
    if [ "${VENDOR}" = "metax" ] && ! command -v vllm >/dev/null 2>&1; then
        for d in /opt/conda/bin /usr/local/bin; do
            if [ -x "$d/vllm" ]; then
                export PATH="$d:$PATH"
                echo "[env] PATH 前置 $d（提供 vllm / pip / python3）"
                break
            fi
        done
    fi
    VLLM_DIR="$(dirname "$(command -v vllm 2>/dev/null || echo /usr/bin/vllm)")"
    if [ -x "${VLLM_DIR}/python3" ]; then PY="${VLLM_DIR}/python3"; else PY="$(command -v python3)"; fi
    echo "[env] python: ${PY} ($("${PY}" -V 2>&1))"

    # ModelzooTool 依赖 json5：以 root 装到系统 site-packages（容器每次重建都会丢，所以每次检查）
    if ! "${PY}" -c "import json5" >/dev/null 2>&1; then
        echo "[dep] 安装 ModelzooTool 依赖 json5 ...（内网源）"
        "${PY}" -m pip config set global.index-url "${PIP_INDEX}" >/dev/null
        "${PY}" -m pip config set install.trusted-host "${PIP_TRUSTED}" >/dev/null
        "${PY}" -m pip install json5 || { echo "[dep] json5 安装失败" >&2; exit 4; }
    fi

    # 建用户（uid 已存在则直接复用）
    #   -o：宿主 UID 常远超镜像 /etc/login.defs 的 UID_MAX=60000，不加会报错
    #   -l：不写 lastlog/faillog（大 UID 写 lastlog 会 seek 出巨大稀疏文件）
    #   -m：home 建在**容器内**；★不要用 -d 指到宿主 HOME（会读/写宿主 ~/.config、~/.local）
    if ! getent passwd "${RUN_UID}" >/dev/null 2>&1; then
        getent group "${RUN_GID}" >/dev/null 2>&1 || groupadd -o -g "${RUN_GID}" "${RUN_USER}"
        useradd -l -o -u "${RUN_UID}" -g "${RUN_GID}" -m -s /bin/bash "${RUN_USER}"
    fi
    EXEC_USER="$(getent passwd "${RUN_UID}" | cut -d: -f1)"
    EXEC_HOME="$(getent passwd "${RUN_UID}" | cut -d: -f6)"

    # ★ MetaX 分支 ②：/dev/dri、/dev/mxcd 属 root:video(660)，su 会重置补组 → 必须补 video,root
    if [ "${VENDOR}" = "metax" ]; then
        usermod -aG video,root "${EXEC_USER}" 2>/dev/null || true
    fi

    echo "[user] 以 ${EXEC_USER} (uid=${RUN_UID}, gid=${RUN_GID}, home=${EXEC_HOME}，容器内) 执行任务（非 root）"
    # su 用**非 login**（不加 -）：login shell 会读 /etc/profile 的硬编码 PATH，把镜像额外追加的
    #   PATH 段（如 SGLang 的 /opt/sglang/bin、CUDA 的 /usr/local/nvidia/bin）整个覆盖掉。
    # 不传 HOME：让 su 按 passwd 取容器内的 /home/<user>，别指到宿主目录。
    exec su -s /bin/bash "${EXEC_USER}" -c \
        "PATH='${PATH}' CUDA_VISIBLE_DEVICES='${CUDA_VISIBLE_DEVICES}' \
         MODELZOO_RUN_UID='${RUN_UID}' MODELZOO_RUN_GID='${RUN_GID}' MODELZOO_RUN_USER='${EXEC_USER}' \
         MODELZOO_VENDOR='${VENDOR}' MODELZOO_PY='${PY}' bash '${SELF}' ${TASKS}"
fi

# ---------- 第二阶段（执行用户） ----------
echo "[user] 当前执行用户: $(id -un) (uid=$(id -u), gid=$(id -g)), HOME=${HOME}"

# ★ MetaX 分支 ③：MACA 环境变量（NVIDIA 厂商可整段删除）
if [ "${VENDOR}" = "metax" ]; then
    export MACA_PATH=/opt/maca
    export MACA_SMALL_PAGESIZE_ENABLE=1
    export MACA_DIRECT_DISPATCH=1
    export LD_LIBRARY_PATH=/opt/mxdriver/lib:${MACA_PATH}/lib:${MACA_PATH}/ompi/lib:${MACA_PATH}/mxgpu_llvm/lib:${LD_LIBRARY_PATH:-}
    export PATH=${MACA_PATH}/bin:${PATH}
    echo "[env] CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-<未设置>}  MACA_PATH=${MACA_PATH}"
fi

# ============================== 校验 + 跑任务 ==============================
[ -f "${CONFIG}" ] || { echo "[data] 配置文件不存在: ${CONFIG}" >&2; exit 1; }
[ -f "${MODELZOO_ENTRY}" ] || { echo "[data] ModelzooTool 不存在: ${MODELZOO_ENTRY}" >&2; exit 1; }

PY_BIN="${MODELZOO_PY:-$(command -v python3)}"
echo ">>> ModelzooTool: ${CONFIG}"
echo ">>> tasks: ${TASKS}"
echo ">>> log dir: ${LOG_DIR}"
"${PY_BIN}" "${MODELZOO_ENTRY}" --config "${CONFIG}" --task ${TASKS} -o "${LOG_DIR}"
rc=$?
echo ">>> 完成 (exit=${rc})，结果目录: ${LOG_DIR}"
exit ${rc}
