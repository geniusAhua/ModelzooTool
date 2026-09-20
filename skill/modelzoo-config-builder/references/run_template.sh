#!/bin/bash
# ============================================================================
# ModelzooTool —— 容器内执行脚本模板（NVIDIA / MetaX 双厂商）
#
# 由宿主机编排脚本调用（见 references/run_host_template.sh），一般无需手动执行。
#
# 两阶段执行：
#   1) root 阶段   ：前置环境 → 装 ModelzooTool 依赖(json5) → 按宿主 uid/gid 建执行用户 → 补属组
#   2) 执行用户阶段：su - <user>（login shell，注入 USER_ENV）→ 跑 ModelzooTool
#
# 生成时按目标厂商保留对应分支、删掉另一厂商的分支：
#   NVIDIA → run_in_container_nvidia.sh      MetaX → run_in_container_metax.sh
#
# 切用户（两平台统一，用户 2026-09-18 定）：
#   * 一律 **`su - <user>`（login shell）**，**不要**用 `su -s /bin/bash <user> -c "PATH='$PATH' …"`
#   * 属组统一 **video + root**；要再加别的组（如 /dev/mem 需要的 kmem）**必须先问用户**
#   * **只对齐 uid/gid、不对齐 HOME**（`useradd -m`，容器内 /home/<user>；绝不用 -d 指到宿主共享盘）
#   * 切用户后要 export 的环境变量集中成一份 `USER_ENV`，并提供 `--print-user-env`
#     子命令给宿主 dry-run 展示（单一来源，详见 SKILL.md §4.2）
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
# 参数：任务名列表（config 里的任务段名，可多个）；另有子命令：
#   --print-user-env   # 只打印「切用户后要 export 的环境变量」，不执行任务
# 由宿主机脚本经 docker run/exec -e 传入：CUDA_VISIBLE_DEVICES、MODELZOO_RUN_{UID,GID,USER}、
#                                        MODELZOO_BIN、CONFIG、LOG_DIR、MODELZOO_VENDOR、MODELZOO_TAG
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

# ====================== 切用户后要配置的环境变量（USER_ENV） ================
# 统一模式：把“切用户后要 export 的那一组”集中在这里，由下面的 `su -c "${USER_ENV} …"` 注入；
# 同一个变量也被 `--print-user-env` 打印（供宿主脚本 dry-run 展示，**单一来源**）。
if [ "${VENDOR}" = "metax" ]; then
    # MetaX：`su -` 是 login shell，会清掉 Docker ENV 里追加的 /opt/maca/*、/opt/mxdriver/bin
    #   → 这里补回（顺序与写法照拄；/opt/conda/bin 会由 login shell 保留，不用补）
    USER_ENV="export MACA_PATH=/opt/maca; \
export MACA_SMALL_PAGESIZE_ENABLE=1; \
export LD_LIBRARY_PATH=/opt/mxdriver/lib:\${MACA_PATH}/lib:\${MACA_PATH}/ompi/lib:\${MACA_PATH}/mxgpu_llvm/lib:\${LD_LIBRARY_PATH}; \
export PATH=\${MACA_PATH}/bin/:\$PATH; \
export MACA_DIRECT_DISPATCH=1;"
else
    # NVIDIA：无平台专用变量；login shell 会重置 PATH，只需把「框架 CLI / python 所在目录」补回
    #   （login PATH 本就含这些目录时，只是重复，无副作用）
    _fw_dirs=""
    for _c in vllm sglang python3; do
        _b="$(command -v "${_c}" 2>/dev/null)" || continue
        [ -n "${_b}" ] || continue
        _d="$(dirname "${_b}")"
        case ":${_fw_dirs}:" in *":${_d}:"*) ;; *) _fw_dirs="${_d}:${_fw_dirs}" ;; esac
    done
    _fw_dirs="${_fw_dirs%:}"
    USER_ENV="${_fw_dirs:+export PATH='${_fw_dirs}':\$PATH;}"
fi

# --print-user-env：只打印上面这一组，不执行任务（宿主 dry-run 用）
if [ "${1:-}" = "--print-user-env" ]; then
    printf '%s\n' "${USER_ENV}" | tr ';' '\n' | sed 's/^[[:space:]]*//; /^$/d'
    exit 0
fi

# ---------- 第一阶段（root）：前置环境 + 装依赖 + 建执行用户，再以执行用户重跑本脚本 ----------
if [ "$(id -u)" = "0" ] && [ -n "${RUN_UID}" ] && [ "${RUN_UID}" != "0" ]; then
    # ★ Metax 镜像的非交互 PATH 可能不含 /opt/conda/bin（vllm/sglang/pip/python3 都在那里）
    #   → 找不到框架 CLI 时探测并前置（NVIDIA 镜像通常已在 PATH 里，探测直接通过）
    if ! command -v vllm >/dev/null 2>&1 && ! command -v sglang >/dev/null 2>&1; then
        for d in /opt/conda/bin /usr/local/bin; do
            if [ -x "$d/vllm" ] || [ -x "$d/sglang" ]; then
                export PATH="$d:$PATH"
                echo "[env] PATH 前置 $d（提供框架 CLI / pip / python3）"
                break
            fi
        done
    fi
    FW_BIN="$(command -v vllm 2>/dev/null || command -v sglang 2>/dev/null || true)"
    if [ -n "${FW_BIN}" ]; then
        FW_DIR="$(dirname "${FW_BIN}")"
        echo "[env] 框架 CLI: ${FW_BIN}"
        if [ -x "${FW_DIR}/python3" ]; then PY="${FW_DIR}/python3"; else PY="$(command -v python3)"; fi
    else
        echo "[env] 未找到 vllm / sglang CLI，跳过框架探测（ModelzooTool 只需 python3+pip）"
        PY="$(command -v python3)"
    fi
    [ -n "${PY}" ] || { echo "[env] 容器里找不到 python3，请检查镜像" >&2; exit 3; }
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

    # 属组：两平台统一 video + root（/dev/dri、/dev/mxcd 属 root:video(660)，而 su 会重置补组；
    #   要再加别的组（如 /dev/mem 需要的 kmem）必须先问用户）
    usermod -aG video,root "${EXEC_USER}" 2>/dev/null || true

    echo "[user] 以 ${EXEC_USER} (uid=${RUN_UID}, gid=${RUN_GID}, home=${EXEC_HOME}，容器内) 执行任务（非 root）"
    echo "[user] 补组: $(id -Gn "${EXEC_USER}" 2>/dev/null | tr ' ' ',')"
    echo "[env ] 切用户后要配置: ${USER_ENV:-<无>}"
    # 切用户：`su - <user>`（login shell，两平台统一）。不传 PATH/HOME：
    #   HOME 由 passwd 决定（容器内 /home/<user>，不会指到宿主目录）；
    #   PATH 由 login shell + 上面 USER_ENV 决定（MACA / 框架目录都在里面）。
    exec su - "${EXEC_USER}" -c \
        "${USER_ENV} CUDA_VISIBLE_DEVICES='${CUDA_VISIBLE_DEVICES}' \
         MODELZOO_RUN_UID='${RUN_UID}' MODELZOO_RUN_GID='${RUN_GID}' MODELZOO_RUN_USER='${EXEC_USER}' \
         MODELZOO_VENDOR='${VENDOR}' MODELZOO_PY='${PY}' MODELZOO_TAG='${MODELZOO_TAG:-}' bash '${SELF}' ${TASKS}"
fi

# ---------- 第二阶段（执行用户） ----------
# 环境变量已由第一阶段的 `su -c "${USER_ENV} …"` 注入，这里只打印诊断信息
echo "[user] 当前执行用户: $(id -un) (uid=$(id -u), gid=$(id -g)), HOME=${HOME}"
echo "[env ] VENDOR=${VENDOR}  CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-<未设置>}  MACA_PATH=${MACA_PATH:-<未设置>}"
echo "[env ] 框架 CLI: $(command -v vllm 2>/dev/null || command -v sglang 2>/dev/null || echo '<none>')"
echo "[env ] PATH=${PATH}"

# ============================== 校验 + 跑任务 ==============================
[ -f "${CONFIG}" ] || { echo "[data] 配置文件不存在: ${CONFIG}" >&2; exit 1; }
[ -f "${MODELZOO_ENTRY}" ] || { echo "[data] ModelzooTool 不存在: ${MODELZOO_ENTRY}" >&2; exit 1; }

PY_BIN="${MODELZOO_PY:-$(command -v python3)}"
echo ">>> ModelzooTool: ${CONFIG}"
echo ">>> tasks: ${TASKS}"
echo ">>> log dir: ${LOG_DIR}"
# --tag（可选）：给结果目录名加后缀（ModelzooTool 的 --tag），由宿主脚本经 MODELZOO_TAG 传入。
#   值为空时**不要**传 --tag ""（否则目录名会多一个 + 尾巴）
TAG_ARGS=()
[ -n "${MODELZOO_TAG:-}" ] && TAG_ARGS=(--tag "${MODELZOO_TAG}")
"${PY_BIN}" "${MODELZOO_ENTRY}" --config "${CONFIG}" --task ${TASKS} -o "${LOG_DIR}" "${TAG_ARGS[@]}"
rc=$?
echo ">>> 完成 (exit=${rc})，结果目录: ${LOG_DIR}"
exit ${rc}
