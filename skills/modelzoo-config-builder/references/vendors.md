# 双厂商：NVIDIA / MetaX

> 由 `SKILL.md` 按需加载。**生成的 bash 必须两家都能跑。**

> **先看 [gate.md](./gate.md) §0-B**：不管 NVIDIA 还是 MetaX，脚本数量规则一样——**host 两个、分两步**（① 起容器 + ② 容器内），
> **container 一个**（直接用 ②）。下表给的是 **host 形态**两个脚本的名字；container 形态只取「容器内脚本」那一列。
> 起容器前**必须问用户用哪个镜像**；镜像名不确定时做成 `--image` / `IMAGE` 变量，不要写死一个猜的。

**同一份 `config.jsonc` 两家共用**（任务名、server/client 命令、`task_info` 都不变），
差别只在「容器怎么起、容器里的环境怎么准备」，所以**宿主机形态下**脚本按厂商各出一套。
唯一会写进 config 的平台相关内容是 **MetaX 自己的性能开关**（`MACA_*` → `server.env`，见 §7.4），
它在 NVIDIA 上被忽略、设了也无害，因此不需要平台分支。

| 厂商 | 宿主机脚本 | 容器内脚本 |
|------|-----------|-----------|
| NVIDIA | `run_nvidia.sh` | `run_in_container_nvidia.sh` |
| MetaX（沐曦） | `run_metax.sh` | `run_in_container_metax.sh` |

模板：[run_host_template.sh](./run_host_template.sh)（宿主机）+ [run_template.sh](./run_template.sh)（容器内），
两者都用 `VENDOR=nvidia|metax` 分支；生成时按目标厂商裁剪。

## 7.1 差异对照（照这张表生成）

| 事项 | NVIDIA | MetaX |
|------|--------|-------|
| 选卡 | `--gpus all` / `--gpus '"device=0,1"'` | `--device=/dev/dri --device=/dev/mxcd --device=/dev/infiniband` + `--group-add video`；die 号用 `CUDA_VISIBLE_DEVICES` |
| 其它容器参数 | `--network host --ipc host --shm-size 64g --privileged` | 同上，另加 `--uts=host --device=/dev/mem --security-opt apparmor=unconfined --security-opt seccomp=unconfined --shm-size 100gb --ulimit memlock=-1` |
| 框架命令的 PATH | 镜像 ENV 里已有 `sglang` / `vllm` | **非交互路径没有**：`vllm`/`pip`/`python3` 在 `/opt/conda/bin`（交互式才由 `/etc/profile.d/conda.sh` 加进去）→ 容器内先探测并前置，再用与 vllm 同目录的解释器 |
| 设备权限 | `--gpus` 已处理 | `/dev/dri`、`/dev/mxcd` 属 `root:video(660)`，而 `su` 会按 `/etc/group` **重置补组** → 执行用户必须 `usermod -aG video,root`（缺组会 `get device failed` → Segmentation fault） |
| 厂商环境变量 | 一般不需要 | 默认 export `MACA_*`（见 §7.2） |
| pip 源 | 视机器而定 | 机器可达的 pip 源（如内网源，需同时设 `install.trusted-host <host>`） |
| 容器生命周期 | `--rm`，退出即删 | `docker run -dit` + `docker exec`，跑完 `docker rm -f`（`--keep` 可留） |

两家都要遵守的：**只对齐 uid/gid、不对齐 HOME**；切用户统一用 **`su - <user>`（login shell）**，
切用户后要 export 的环境变量集中成 `USER_ENV`（模式与硬性规则见 [delivery.md](./delivery.md) §4.2）。

## 7.2 MetaX 的环境变量（即 `USER_ENV` 的内容）

在容器内「执行用户阶段」export（**不要**写进 `.bashrc` —— 非交互路径不读它）。顺序与写法照抄：

```bash
export MACA_PATH=/opt/maca
export MACA_SMALL_PAGESIZE_ENABLE=1
export LD_LIBRARY_PATH=/opt/mxdriver/lib:${MACA_PATH}/lib:${MACA_PATH}/ompi/lib:${MACA_PATH}/mxgpu_llvm/lib:${LD_LIBRARY_PATH}
export PATH=${MACA_PATH}/bin/:$PATH
export MACA_DIRECT_DISPATCH=1
```

- **为什么必须 export**：`su -` 是 login shell，会把 Docker ENV 里追加的 `/opt/maca/*`、
  `/opt/mxdriver/bin` 清掉（实测）；而 `/opt/conda/bin` **会**保留（镜像的 conda 配置在
  `/etc/profile.d/`，login shell 会读）⇒ `python3`/`pip3`/`vllm`/`sglang` 不会丢。
- **NVIDIA 平台没有这类专用变量** ⇒ 它的 `USER_ENV` 只需把「框架 CLI / python 所在目录」补回 PATH：

```bash
# 在容器内（PATH 还是 Docker ENV 那份）探测一次，去重后前置回 PATH
_fw_dirs=""
for _c in vllm sglang python3; do
    _b="$(command -v "${_c}" 2>/dev/null)" || continue
    [ -n "${_b}" ] || continue
    _d="$(dirname "${_b}")"
    case ":${_fw_dirs}:" in *":${_d}:"*) ;; *) _fw_dirs="${_d}:${_fw_dirs}" ;; esac
done
USER_ENV="export PATH='${_fw_dirs%:}':\$PATH;"   # 该目录本来就在 login PATH 里时只是重复，无副作用
```

## 7.3 MetaX 侧的常见坑

- **镜像版本要对**：镜像必须带目标模型实现与所需参数，否则会报 `unrecognized arguments: <某参数>`。
  别把镜像名写死不给退路 → 提供 `--image`。
- **`vllm --help` 报 `pymxsml.NVMLError_InvalidArgument`**：是设备没挂进容器（缺 `/dev/dri`、
  `/dev/mxcd`、`--group-add video`），不是环境变量问题。
- **权重加载完（如 `48/48 shards`）后静默几分钟**：在编译 kernel（TileLang），不是卡死。
- **单 die 显存要按 `mx-smi` 实际值算**，别把多个 die 当成共享显存；起服务前确认这些 die 空闲。
- **client 侧外部工具（AISBench 等）的环境变量集中在自己的 `xxx_env.sh`**（见 [pitfalls.md](./pitfalls.md)），不写进 jsonc ——
  这类配置两家机器一模一样，放脚本里才能两家共用一份 jsonc。

## 7.4 MetaX 性能环境变量（写进 config 的 `server.env`，与模型绑定，必须问）

有些环境变量**只影响 MetaX 上的性能**，而且**与模型绑定** —— 不是每个模型都需要，所以不能默认写死；
生成时按 [heuristics.md](./heuristics.md) 第 4 条**启发式问一句**。写法是 config 的 `server.env`（顶层默认即可、全部任务生效，
任务段可用同名键覆盖）：

```jsonc
"server": {
    "cmd": null,
    "env": {
        "MACA_VLLM_ENABLE_MCTLASS_FUSED_MOE": 1,    // 沐曦 vLLM：MCTLASS 融合 MoE
        "MACA_VLLM_ENABLE_MCTLASS_PYTHON_API": 1,   // 沐曦 vLLM：MCTLASS Python API
        "MACA_SMALL_PAGESIZE_ENABLE": 1,            // MACA 驱动：小页
        "MACA_DIRECT_DISPATCH": 1                   // MACA 驱动：直连分发
    }
}
```

- 上面这 4 个只是写作模板：不同模型/平台需要的开关不同，**必须按目标模型重新确认，不要照抄**。
- **对 NVIDIA 无效但无害**：被框架忽略，不影响执行与性能 ⇒ 不做平台分支，两家共用一份 config。
- 值写 `1`（数字）或 `"1"`（字符串）都行：ModelzooTool `_merge_env`
  （`bin/utils/command_builder.py`）会把 int/float 转成 str。
- 与 §7.2 的区别：**§7.2 那些是"让 MACA 环境跑起来"的容器级变量，由容器内脚本 export；
  本节这些是"让模型跑得快"的模型/平台开关，写在 config 里、随配置走**。
  `MACA_SMALL_PAGESIZE_ENABLE` / `MACA_DIRECT_DISPATCH` 两处都出现是正常的（一个管容器环境、
  一个管 server 进程），值保持一致即可。
- 换模型/换平台时回头核对这一段：它属于"模型专属配置"，**不要**照抄到别的模型配置里。

### 7.5 MetaX 抓取类任务的环境变量（attn / mcblas / mctlass）

> 三类抓取各自依赖一组日志开关，**写进 config 的 `server.env`（任务级）**，不是容器级 `USER_ENV`。
> ⚠️ **写进配置前，必须把下表逐条发给用户审核（必问项 ⑥），确认后才落盘/开跑。**
> ⚠️ **这三类任务一律不开 `warmup`**（见 §7.6）。

| 抓什么 | `type` | `server.env` | `server.extra_args` |
|--------|--------|--------------|---------------------|
| **attn**（FlashAttention / MHA） | `pair` | `MACA_LAUNCH_BLOCKING=1`<br>`MHA_LOG_ENABLE=1`<br>`MHA_PRINT_PARA="ON"`<br>`MHA_INPUT_COLLECTION="{__LOG_PATH__}/{__FILE_NAME__}-bs{bs}-in{input}-out{output}"` | `--enforce-eager` |
| **mcblas**（MCBLAS / MCBLASLT） | `pair` | `MACA_LAUNCH_BLOCKING=1`<br>`MXLOG_LEVEL="err,MCBLAS=info,MCBLASLT=info"` | `--enforce-eager` |
| **mctlass**（MCTLASS / MCTLASSEX） | `pair` | `MACA_LAUNCH_BLOCKING=1`<br>`MCTLASS_LOG_ENABLE="ON"`<br>`MXLOG_LEVEL="err,MCTLASSEX=debug"` | `--enforce-eager` |

- `MHA_INPUT_COLLECTION` 决定 attn 打点落盘位置：用 `{__LOG_PATH__}` 保证**每 case 独立**，建议带上 `{bs}{input}{output}`（也可用固定后缀如 `-FA`）。
- `MACA_LAUNCH_BLOCKING=1` 三类都要：同步执行才能保证打点顺序、避免丢日志。
- 抓 shape / kernel 一律 `--enforce-eager`（关 cudagraph），否则 capture 之后 Python 层不执行，**打点全丢**。
- 值写 `1`（数字）或 `"1"`（字符串）都行（`_merge_env` 会转成字符串）。

### 7.6 `warmup` 只给 profile 抓取用

`client.warmup` 为 `true` 时，client 会变成「先跑一遍热身 → 再跑带 `--profile` 的目标命令」。

| 任务 | 要不要 `warmup` |
|------|------------------|
| **profile 抓取**（server `--profiler-config` + client `--profile`） | **要** |
| **attn / mcblas / mctlass 三类抓取** | **不要**（多跑一遍会污染打点与耗时） |
| e2e 压测 / 精度评测 | 不要 |
