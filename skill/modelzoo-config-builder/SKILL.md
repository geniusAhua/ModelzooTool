---
name: modelzoo-config-builder
description: 为 ModelzooTool 启发式生成 config.jsonc 与执行 bash 脚本。当用户想跑 vllm/推理服务的端到端压测、Profiler 或 TlasShape/BlasShape/FlashAttnShape/Triton 抓取，或提到"生成 Modelzoo config""写个跑 ModelzooTool 的脚本""server 命令 + client 命令""--task"时使用。用户只需提供环境变量、server 命令、client 命令，其余通过启发式提问与自动推导补全。
---

# ModelzooTool 配置生成器

本技能把「一堆散乱的 server/client 命令」变成 ModelzooTool 可直接运行的
`config.jsonc` + 一键执行脚本。脚本按**厂商**各一套（同一份 config 两家共用）：
NVIDIA 用 `run_nvidia.sh` + `run_in_container_nvidia.sh`，
MetaX（沐曦）用 `run_metax.sh` + `run_in_container_metax.sh` —— 差异与生成要点见 §7。

核心原则：**用户只提供三样东西 —— 环境变量、server 命令、client 命令。**
其余字段（`modelPath`、`task_info`、`readyTag`、任务段（名字与 `type`）、
`bs_in_out`、`extra_args`、脚本骨架）由你**先从命令里推导，再启发式补问**，
不要一上来就让用户填 JSON。

## 0. 用户输入（只问这三样）

| 输入 | 说明 | 去哪 |
|------|------|------|
| server 命令 | 启动推理服务的那条命令 | 默认 `server.cmd`（或任务级 `cmd`） |
| client 命令 | 打流/压测/测量脚本命令 | 默认 `client.cmd`（或任务级 `cmd`） |
| 环境变量 | server / client 各自需要 export 的变量 | `server.env` / `client.env` |

如果用户已经给了这三样，**不要重新索要整份配置**，直接进入推导。

## 1. 启发式推导（先做，能推的绝不问）

拿到三条命令后，先扫描命令文本，按下表自动落位；只有推不出来时才问。

| 命令里的线索 | 推导结果 |
|--------------|----------|
| 模型路径（`vllm serve <PATH>` 或 `--model <PATH>`） | 顶层 `modelPath`，命令中替换为 `{modelPath}` |
| `--port <N>` / `-p <N>` | `task_info.port`，替换为 `{port}` |
| `-tp <N>` / `--tensor-parallel-size <N>` | `task_info.tp`，替换为 `{tp}` |
| `--max-num-batched-tokens $((<N> * 1024))` 之类换算系数 | `task_info.chunk_size` |
| `--random-input-len <N>` / `--random-output-len <N>` / `--max-concurrency <N>` | **case 变量**：改为 `{input}` / `{output}` / `{bs}` |
| `--num-prompts <N>` | 若与 bs 同比，用内置 `{prompts}`（= bs × `task_info.promptRatio`，默认 1） |
| client 里输出目录/落盘路径参数 | 改为 `{__LOG_PATH__}/{__FILE_NAME__}-...`，保证每 case 独立 |
| server/client 里出现的**固定**魔法参数（如 `--attention-backend`） | 留在默认命令里，不抽变量 |
| 明显的抓取开关（`--enforce-eager`、`--profile` 等） | 判断属于哪个任务，落到该任务 `extra_args` |

**任务段与类型**：配置顶层除保留键 `modelPath`、`modelName`、`readyTag`、
`task_info`、`server`、`client` 外，**任意顶层 object 都是任务段**（名字自定）。
每个任务段**必须**写 `type`，用 `--task <任务名> [<任务名> ...]` 选择执行。
类型决定调度行为，与任务名解耦：

| `type` | 作用 | 线程模型 |
|--------|------|----------|
| `e2e` | 端到端，**只启一次 server**，串行跑完所有 case | Single server |
| `pair` | 每个 case 一对 server+client（每个 case 重启 server） | 每 case 一对 |

> 任务名只是标签，可自定（例如 `e2e` / `profiler` / `tlas` / `blas` / `flash` / `triton`）；
> 老版本那些固定任务名（E2E/Profiler/TlasShape/BlasShape/FlashAttnShape/TritonDump）
> 与固定 flag（`-E` / `-p` / `-t` / `-b` / `-f` / `-d` / `-ptfb`）**都已移除**，
> 不要再生成这类写法。默认只启用一个 `type: e2e` 任务（名字 `e2e`），其余按需追问。

任务段可选 `cleanTritonCache`（与 `type` 同级）：`true` 表示任务开始前清理
triton 编译缓存（老版本固定名 `TritonDump` 的自动清缓存行为已移除，改为这个开关）。

**case 列表（`bs_in_out`）**：每个元素是 `[bs, input, output]`。`e2e` 若不需要这些值，
用 `[[0, 0, 0]]` 占位即可（client 侧可用自定义脚本替代）。

### 只有这些情况才提问

1. 要跑哪些任务（任务名 + `type`）？（默认一个 `e2e` 任务；用户提到 profile/抓 shape 再追加 `pair` 任务）
2. `bs_in_out` 的 case 组合？（给默认建议，如 `[[1,1000,16],[4,3000,16]]`）
3. 部署脚本参数：执行用户 `user` + `uid`、日志目录 `LOG_DIR`、工具入口 `ModelzooTool_entry_PATH`。
4. **跑在哪家厂商（NVIDIA / MetaX）？有没有要加到 `server.env` 的平台/模型相关开关？**
   MetaX 上这类开关**直接影响性能、且与模型绑定**（不是每个模型都需要），必须问一句，别自己猜。
   例（本工作区 DeepSeek-V4.1-Flash 实测需要）：`MACA_VLLM_ENABLE_MCTLASS_FUSED_MOE`、
   `MACA_VLLM_ENABLE_MCTLASS_PYTHON_API`、`MACA_SMALL_PAGESIZE_ENABLE`、`MACA_DIRECT_DISPATCH`
   —— 它们对 NVIDIA 无效但无害，所以写进共用 config、不做平台分支，详见 §7.4。
5. 命令里含义不明的参数：不确定是"固定参数"还是"随 case 变"时，问一句，别猜。

一次问齐，别来回拉扯；能默认的给默认值让用户确认。

## 2. 配置心智模型（写 config 前必须理解）

**魔法变量渲染**发生在 `bin/utils/command_builder.py`：命令、`env` 里的每个
字符串都会做 `{key}` 替换。可用变量：

| 变量 | 来源 | 备注 |
|------|------|------|
| `{bs}` `{input}` `{output}` | 当前 case | 由 `bs_in_out` 注入 |
| `{prompts}` | 工具计算 | = `bs × task_info.promptRatio`（默认 1） |
| `{modelPath}` | 顶层 `modelPath` | 也可直接写死在命令里 |
| `{__LOG_PATH__}` | 工具计算 | 当前 case 的日志目录，**每 case 独立** |
| `{__FILE_NAME__}` | 工具计算 | 当前 config 文件名（不含扩展名） |
| `{任意task_info键}` | `task_info` | 自定义魔法变量 |

> 注意：`bs/input/output/prompts/modelPath/__LOG_PATH__/__FILE_NAME__` 是**保留名**，
> 即使写进 `task_info` 也会被覆盖。

**命令拼装规则**（server 与 client 同规则）：

```
最终命令 = (任务级 cmd 若非 null ? 任务级 cmd : 默认 cmd) + 渲染后的 extra_args
```

- 任务级 `cmd: null` → 用默认命令；给了字符串 → **整条覆盖**默认命令。
- `extra_args` 永远追加在末尾。
- `env`：默认 env 与任务级 env 合并，任务级同名键覆盖默认。

**client 的 `warmup`**：为 `true` 时，client 变成 `基础命令 && 基础命令+extra_args`
（先跑一遍热身，再跑带 `--profile` 等的目标命令）。Profiler 场景常用。

**`readyTag`（server 启动完成标志）**：工具靠匹配 server 日志来判断「服务已就绪、
可以开始打流」。

- 顶层 `readyTag` 是全局默认，默认值 `"Application startup complete"`（vLLM 适用）。
- 任务段内写 `readyTag` 可覆盖默认，**写在任务段这一层（与 `type` 同级），
  不是写在 `server` 里**。
- 值可以是**字符串**，也可以是**字符串数组**（命中任意一个即视为就绪）。
- **等非 vLLM 服务（如基于 uvicorn 的 SGLang）就绪，靠的就是它**：不同服务的
  就绪日志不一样，别去翻源码，直接在任务段里配置与服务日志对应的关键字；
  拿不准就多写几个放进数组兜底。

示例：

```jsonc
"task_info": { "tp": 4, "port": 1136 },
"readyTag": "Application startup complete",   // 顶层全局默认
"sglang": {
    "type": "e2e",
    "readyTag": ["Uvicorn running on", "The server is fired up and ready to go!"],
    "bs_in_out": [[1, 1000, 16]],
    "server": { "cmd": null, "env": {}, "extra_args": [] },
    "client": { "cmd": null, "env": {}, "extra_args": [] }
}
```

**`cleanTritonCache`（可选）**：任务段里（与 `type` 同级）写
`"cleanTritonCache": true`，任务开始前会清 `/root/.triton/*` 与 vLLM 缓存后再启动，
抓 triton kernel 的场景需要。

**转义**：字符串里想要字面量 `{}`，必须写成 `{{}}`；否则会被当魔法变量渲染并报
`Missing`。例如 `--profiler-config '{{"profiler":"torch"}}'`。

## 3. 生成流程

1. 确认三样输入，扫描命令做第 1 节的推导，列出「推导结果 + 待确认项」给用户。
2. 复制 `references/config_template.jsonc`，按推导结果填充：
   - 顶层 `modelPath`、`task_info`、`readyTag`（非 vLLM 服务记得改）
   - 默认 `server` / `client`（cmd + env），把会变的参数替换成 `{...}`
   - 每个任务段都写 `type`（`e2e` 或 `pair`）；需要覆盖的 task 段落才写，
     不需要的任务段**整段删掉**（工具对缺失任务会跳过）
   - 任务级 `env` / `extra_args` / `readyTag` / `cleanTritonCache` 按需填
3. 复制 `references/run_host_template.sh`（宿主机编排）与 `references/run_template.sh`（容器内），
   **按目标厂商各生成一套**（`VENDOR=nvidia|metax` 分支，见 §7），填 `user` / `uid` / `configs` /
   `ModelzooTool_entry_PATH` / `LOG_DIR` 等；外部评测工具（AISBench 等）的环境变量放它自己的
   `xxx_env.sh`，**不**放 jsonc 的 `client.env`（理由见 §6）。
   ★ 模板已内置 **`--tag` 透传** 与 **两层 `--dry-run`**（含 `--print-user-env`，见 §4.1/§4.2），
   生成时**不要删掉**这两项能力；也不要为了省事把 `su -` 改回 `su -s /bin/bash`。
4. 给用户一份「如何跑 + 如何回退」说明。

## 4. 交付物

| 文件 | 内容 |
|------|------|
| `config.jsonc` | ModelzooTool 配置（JSON5，支持 `//` 注释），**两个厂商共用** |
| `run_nvidia.sh` | 【NVIDIA】宿主机：起容器（`--gpus`）→ 调容器内脚本 |
| `run_in_container_nvidia.sh` | 【NVIDIA】容器内：装依赖 → 建用户 → `su` 切用户 → 跑各 config |
| `run_metax.sh` | 【沐曦】宿主机：起容器（设备节点 + die）→ 调容器内脚本 |
| `run_in_container_metax.sh` | 【沐曦】容器内：前置 `/opt/conda/bin` → 装依赖 → 建用户（补 `video,root`）→ `su` 切用户 → export `MACA_*` → 跑各 config |

> 只做一家也可以，但**先问清楚跑在哪家**，别默认只有 NVIDIA（差异见 §7）。

模板见：
- `references/config_template.jsonc`
- `references/run_host_template.sh`（宿主机，`VENDOR` 分支）
- `references/run_template.sh`（容器内，`VENDOR` 分支）

执行入口为：

```bash
python "<ModelzooTool>/bin/main.py" --config "<config.jsonc>" --task <NAME> [<NAME> ...] -o "<LOG_DIR>"
```

- `--task` 可跟**多个任务名**，按顺序执行；任务名取自 config 里的自定义任务段。
- 某任务失败**只记录、不中断**，后续任务继续执行；全部跑完后若有失败，以**退出码 1** 结束。

### 4.1 生成的脚本必须透传 ModelzooTool 的 CLI 参数

`main.py` 的完整 CLI（`--help` 实测）：

```
usage: main.py [-h] [--config CONFIG] [--tag TAG] [--task NAME [NAME ...]]
               [-o OUTPUT_DIR] [--dry-run] [--list]
```

生成的宿主机脚本**必须让用户能用上这些开关**（不能写死），职责划分：

| CLI 参数 | 宿主机脚本要做什么 | 透传链路 |
|---------|-------------------|----------|
| **`--list`** | **建议支持**：列出 config 里的任务名后退出（工具层 cmd 是 `main.py --config <cfg> --list`，**必须**同时给 `--config`，不会回落默认配置；不创建目录、不跑任务） | 宿主脚本可自己静态解析任务名（不依赖 python/json5，适合裸宿主机），也可在容器里调 `main.py --list`；两者必须一致 |
| `--task <name...>` | 接受位置参数或 `--task`，**可多个**（按顺序跑） | 位置参数 → 容器内脚本 → `main.py --task <name...>` |
| `--config <path>` | 默认取同目录 `config.jsonc`，允许覆盖 | 环境变量 `CONFIG` → `main.py --config` |
| `-o <dir>` | 脚本内定为 `LOG_DIR`（结果落点），允许覆盖 | 环境变量 `LOG_DIR` → `main.py -o` |
| **`--tag <suffix>`** | **必须支持**：结果目录名后缀，同名任务跑多次时区分批次 | 宿主 `--tag` → `docker exec -e MODELZOO_TAG=<v>` → 容器内脚本 → `main.py --tag <v>`（**值为空时不传**） |
| **`--dry-run`** | **必须支持**，且要做**两层**预演（见下） | **不进**容器内脚本 |
| `--keep` | 跑完保留容器（调试）；两厂商语义不同，见 §7.1 | —— |

#### `--tag` 的实现要点

- 结果目录名会变成 `<时间戳>+<tag>`（ModelzooTool 行为），是区分同名任务多次运行**最省事**的办法。
- **值为空时不要传** `--tag ""`（会生成带 `+` 结尾的怪目录）：容器内脚本里写
  `[ -n "${MODELZOO_TAG}" ] && TAG_ARGS=(--tag "${MODELZOO_TAG}")`，然后 `"${TAG_ARGS[@]}"`。

#### `--dry-run` 的实现要点（两层，缺一不可）

| 层 | 做什么 | 为什么 |
|----|--------|--------|
| ① 宿主编排层 | 打印将执行的 `docker run` / `docker exec`（`printf ' %q'` 展开数组），**不 mkdir、不删容器、跳过镜像存在性检查** | 看清编排动作 |
| ② 工具层 | 起一个**临时容器**跑 `main.py --dry-run`，打印渲染后的 server/client 命令 + 将注入的环境变量 | 只看①仍然不知道“真正会跑什么” |

② 的三个坑：

- **必须在容器里跑**：宿主机常常没有 ModelzooTool 的硬依赖 `json5`（沐曦机宿主 python3 就没有）
  → 临时容器里按需 `pip install json5`（内网源）。
- 临时容器用 `docker run --rm` + **不带 `--name`**，只挂共享盘 + 透传 `CUDA_VISIBLE_DEVICES`，
  不建用户、不碰设备节点、不加载权重 ⇒ 不会撞同名正式容器。
- 顺便把「**切用户后要配置的环境变量**」也打出来（调容器内脚本的 `--print-user-env`，见 §4.2）
  —— 这样展示的内容与真实执行的**单一来源**，不会两边不同步。

`main.py --dry-run` 自身保证：只渲染命令与环境变量，**不创建日志目录、不清 triton 缓存、不起 server/client**。

#### ⚠️ `--dry-run` 验不到 `su -` 那条链

宿主的 `--dry-run` **不经过容器内脚本**（它只在临时容器里跑 `main.py`），所以
`su - <user>` / `USER_ENV` / 建用户 / 补组 这些**一步都不会走**。要验它们用「空壳容器 + 假任务名」（见 §5）。

### 4.2 切用户与环境变量（`USER_ENV`）

容器内脚本是两个阶段：**root 阶段** → `su - <user>` 切到执行用户 → 跑 `main.py`。

**统一模式：把“切用户后要 export 的那一组”集中成一个 `USER_ENV`**（容器内脚本顶层定义）：

```bash
USER_ENV="export FOO=1; export PATH=...;"

# 供宿主 dry-run 展示（只打印、不执行任务）
if [ "${1:-}" = "--print-user-env" ]; then
    printf '%s\n' "${USER_ENV}" | tr ';' '\n' | sed 's/^[[:space:]]*//; /^$/d'
    exit 0
fi
...
exec su - "${EXEC_USER}" -c "${USER_ENV} MODELZOO_RUN_UID='…' bash '${SELF}' ${TASKS}"
```

硬性规则（用户 2026-09-18 定，两平台统一）：

- 切用户一律用 **`su - <user>`（login shell）**，**不要**用 `su -s /bin/bash <user> -c "PATH='$PATH' …"`。
- 属组统一 **`video` + `root`**；要再加别的组（如 `/dev/mem` 需要的 `kmem`）**必须先问用户**。
- **HOME 不迁移**：`useradd -m`（容器内 `/home/<user>`），绝不用 `-d` 指到宿主共享盘。
- `USER_ENV` 的内容按厂商定：**MetaX** 见 §7.2；**NVIDIA** 无平台专用变量，只需把「框架 CLI / python
  所在目录」补回 PATH。

> 为什么要有 `--print-user-env`：宿主脚本的 `--dry-run` 不经过容器内脚本（§4.1），靠它才能把
> 「切用户后到底会 export 什么」展示出来，而且**单一来源**（不会两边不同步）。

## 5. 校验（不改代码、不真跑）

生成后至少做静态校验。校验阶段**不要真的启动任务**（不跑 `--task`），只做语法与
渲染检查：

```bash
# 语法：JSON5（支持 // 注释与尾随逗号）
python -c "import json5,sys; json5.load(open(sys.argv[1]))" config.jsonc
```

若本机没有 `json5` 模块：去掉 `//` 注释后用 `json.loads` 解析即可
（注意别误伤字符串里的 URL 写法）。

生成的脚本也要静态检查（不跑任务、不起容器）：

```bash
bash -n run_nvidia.sh run_in_container_nvidia.sh run_metax.sh run_in_container_metax.sh
```

再跑一次**脚本自己的 `--dry-run`**（两层预演，见 §4.1）—— 它能顺带暴露渲染错误、镜像不存在、
任务名拼错，以及「切用户后会 export 什么」：

```bash
bash run_nvidia.sh <framework> <task> --dry-run
```

最后用**「空壳容器 + 假任务名」验 `su -` 那条链**（`--dry-run` 走不到它，见 §4.1）：
**不挂任何 GPU 设备**起一个空壳容器，`docker exec` 带齐宿主脚本平时会传的 `-e`，执行容器内脚本 +
一个**假任务名**（工具会在参数校验阶段就报错退出 ⇒ 不起 server、不加载权重，0 GPU 占用、几秒完成）：

```bash
docker run -d --name mz-probe --entrypoint bash -v <共享盘>:<共享盘> <镜像> -c 'sleep 600'
docker exec -e MODELZOO_RUN_UID="$(id -u)" -e MODELZOO_RUN_GID="$(id -g)" -e MODELZOO_RUN_USER="$(id -un)" \
    -e MODELZOO_BIN=<ModelzooTool>/bin/main.py -e CONFIG=<config.jsonc> -e LOG_DIR=<LOG_DIR> \
    mz-probe bash <容器内脚本> __probe_nonexistent__
docker rm -f mz-probe
```

看到 `[user] 当前执行用户: …`、`HOME=/home/<user>`、`PATH=…`（MetaX 还要有 `MACA_PATH=…`）
就说明切用户与环境变量都对了。

再做「不启动进程」的渲染自检：用 `str.format_map` 复刻
`bin/utils/command_builder.py` 的上下文（`task_info` 的所有键 +
`bs/input/output/prompts/modelPath/__LOG_PATH__/__FILE_NAME__`），并让
`__missing__` 报错，确认命令 / `env` / `extra_args` 里所有 `{...}` 都能命中，
没有落下必然报 `Missing` 的占位符（尤其别把字面量 `{}` 忘了写成 `{{}}`）。

## 6. 常见坑

- **⚠️ `useradd` 千万不要把 HOME 指到宿主目录**（宿主与容器共享同一块盘时最容易踩）：
  容器内的执行用户只用 `-m`（home 落在容器内 `/home/<user>`），**不要**用 `-d <宿主 HOME>`，
  `su` 时也**不要**再显式传 `HOME=`。理由：HOME 一旦指到共享盘里的宿主目录，容器内进程
  就会去读写宿主的 `~/.bashrc` / `~/.config/pip` / `~/.cache` / `~/.local`，后果：
  ① pip 配置、缓存、甚至 `pip install --user` 装出来的包会落到宿主目录（污染宿主环境）；
  ② 宿主 HOME 下若出现 `.local/lib/python3.X/site-packages`，它会插到 `sys.path` **最前面**，
  可能把镜像自带的 numpy / torch / vllm / sglang 顶掉（版本或 ABI 不匹配就 import 失败）。
  只对齐 **uid/gid**（保证产物属主正确）就够了 —— 正确写法见 `references/run_template.sh`：
  `useradd -m -l -u ${uid} -s /bin/bash ${user}`（`-m` 不指向任何宿主路径）。
- **⚠️ 切用户一律用 `su - <user>`（login shell），不要用 `su -s /bin/bash <user> -c "PATH='$PATH' …"`**
  （用户 2026-09-18 裁定，两平台统一）；属组统一 **`video` + `root`**（要再加别的组必须先问用户）；
  HOME 只对齐 uid/gid、**不迁移**（见上一条）。
  **为什么不再用非 login 写法**（实测，两个沐曦镜像）：`su -` 确实会重置 PATH，但**镜像自带的 conda
  配置在 `/etc/profile.d/`，login shell 会读** ⇒ `/opt/conda/bin` 仍在 PATH 里
  （`python3`/`pip3`/`vllm`/`sglang` 都能找到，`HOME=/home/<user>`）。
  真正会被清掉的是 **Docker ENV 里额外追加的目录**：MetaX 的 `/opt/maca/*`、`/opt/mxdriver/bin`，
  以及某些镜像的 `/opt/sglang/bin`、`/usr/local/cuda/bin` ⇒ **统一做法是：切用户后由一份 `USER_ENV`
  显式补回来**（MetaX 见 §7.2；NVIDIA 只需把「框架 CLI / python 所在目录」前置回 PATH）。模式见 §4.2。
  附带坑：`su - <user> -c ...` 是 login 但**非交互** —— `/etc/profile.d/*.sh` 会读，而
  `~/.bashrc` 在开头的 `case $- in *i*) ;; *) return;; esac` 处直接 return。所以「迁 HOME 换
  conda/ais_bench 可用」在自动化编排里**根本不成立**（只有手动交互登录才生效），别为了这个去动 HOME。
- **任务段缺 `type`** → 工具直接报「缺少 type 字段」，整个任务不执行。
- **字面量 `{}` 未转义** → 渲染期 `Missing` 报错。写成 `{{}}`。
- **保留名被 task_info 覆盖**：`input`/`output`/`bs`/`port` 等别和保留名冲突。
- **`type: e2e` 的 server 只启一次**：e2e 段里的 server `extra_args` 只在首个 case 生效，
  依赖 per-case 的 `{bs}{input}{output}` 的 server 参数不会逐 case 变化；需要逐 case
  独立 server 请用 `type: pair`。
- **非 vLLM 服务卡在等待就绪**：默认 `readyTag` 是 vLLM 的日志，其他服务匹配不到会
  一直等。按该服务自身就绪日志在任务段配 `readyTag`（数组兜底）。
- **抓 triton 忘开清缓存**：想要旧 `TritonDump` 的效果，任务段加
  `"cleanTritonCache": true`。
- **client 固定命令 vs 覆盖命令**：只想改参数就用 `extra_args`，想换整条命令才写 `cmd`。
- **`$((...))` 不要被 JSON 转义破坏**：保持原样写进字符串即可。
- **容器内脚本用 `su - <user> -c "<命令字符串>"` 传递**（不再用 heredoc），所以字符串里的 `$` 要
  注意转义层级：让它在**切用户后才展开**就写 `\$PATH`；想在**当前 shell 就展开**就直接写 `${VAR}`。
  `USER_ENV` 里的 `${MACA_PATH}` / `$PATH` 属于前者（延迟展开）—— 写错了会得到一堆空值而不是报错。
- **config 文件名即 `{__FILE_NAME__}`**：会给日志目录带来一层以文件名命名的子目录，
  命名时保持可读。
- **client 若调用 AISBench（mmengine 系工具），别在它的配置文件里 `import os` 后用环境变量**：
  `mmengine.Config.fromfile()` 默认 `use_lazy_import=True`，配置里的 `import xxx` 会被换成
  LazyObject/LazyAttr，任何**调用**（`os.environ.get(...)`）都直接 `RuntimeError`，工具侧再包成
  `TMAN-CFG-001 invaild syntax in config content`。可用 `_os = __import__("os")`（内建函数、
  不是 import 语句，不会被 lazy 化）后再 `_os.environ.get(...)`。

- **⚠️ 生成的脚本必须区分厂商（NVIDIA / MetaX）**：只写 NVIDIA 的 `--gpus all` 在沐曦机器上起不来
  （设备节点、补组、环境变量、镜像来源全都不同），反之亦然。对照表、MetaX 默认环境变量与常见坑见 §7。
- **外部评测工具（AISBench 等）的环境变量放它自己的 `xxx_env.sh`，不要写进 jsonc 的 `client.env`**：
  实测这类「客户端环境」（`AIS_BENCH_BIN` / `AIS_BENCH_ROOT` / 数据缓存目录等）在 NVIDIA 与 MetaX
  机器上**完全一样**，写进 jsonc 只会把机器路径混进两家共用的配置、还要同步两处。
  推荐：机器相关的值集中在 `accuracy/aisbench_env.sh` 这类环境文件里，运行脚本发现变量为空时 source 它
  （`XXX_ENV_FILE` 可覆盖路径、置空可禁用），jsonc 里写 `"env": {}`。
  换言之 `client.env` 只留给**真正随配置变**的东西（例如只有某任务才需要的开关）；
  平台/模型相关的性能开关则相反（见 §7.4）。

## 7. 双厂商：NVIDIA / MetaX（生成的 bash 必须两家都能跑）

**同一份 `config.jsonc` 两家共用**（任务名、server/client 命令、`task_info` 都不变），
差别只在「容器怎么起、容器里的环境怎么准备」，所以脚本按厂商各出一套。
唯一会写进 config 的平台相关内容是 **MetaX 自己的性能开关**（`MACA_*` → `server.env`，见 §7.4），
它在 NVIDIA 上被忽略、设了也无害，因此不需要平台分支。

| 厂商 | 宿主机脚本 | 容器内脚本 |
|------|-----------|-----------|
| NVIDIA | `run_nvidia.sh` | `run_in_container_nvidia.sh` |
| MetaX（沐曦） | `run_metax.sh` | `run_in_container_metax.sh` |

模板：`references/run_host_template.sh`（宿主机）+ `references/run_template.sh`（容器内），
两者都用 `VENDOR=nvidia|metax` 分支；生成时按目标厂商裁剪。

### 7.1 差异对照（照这张表生成）

| 事项 | NVIDIA | MetaX |
|------|--------|-------|
| 选卡 | `--gpus all` / `--gpus '"device=0,1"'` | `--device=/dev/dri --device=/dev/mxcd --device=/dev/infiniband` + `--group-add video`；die 号用 `CUDA_VISIBLE_DEVICES` |
| 其它容器参数 | `--network host --ipc host --shm-size 64g --privileged` | 同上，另加 `--uts=host --device=/dev/mem --security-opt apparmor=unconfined --security-opt seccomp=unconfined --shm-size 100gb --ulimit memlock=-1` |
| 框架命令的 PATH | 镜像 ENV 里已有 `sglang` / `vllm` | **非交互路径没有**：`vllm`/`pip`/`python3` 在 `/opt/conda/bin`（交互式才由 `/etc/profile.d/conda.sh` 加进去）→ 容器内先探测并前置，再用与 vllm 同目录的解释器 |
| 设备权限 | `--gpus` 已处理 | `/dev/dri`、`/dev/mxcd` 属 `root:video(660)`，而 `su` 会按 `/etc/group` **重置补组** → 执行用户必须 `usermod -aG video,root`（缺组会 `get device failed` → Segmentation fault） |
| 厂商环境变量 | 一般不需要 | 默认 export `MACA_*`（见 7.2） |
| pip 源 | 视机器而定 | 机器可达的 pip 源（如内网源，需同时设 `install.trusted-host <host>`） |
| 容器生命周期 | `--rm`，退出即删 | `docker run -dit` + `docker exec`，跑完 `docker rm -f`（`--keep` 可留） |

两家都要遵守的：**只对齐 uid/gid、不对齐 HOME**；切用户统一用 **`su - <user>`（login shell）**，
切用户后要 export 的环境变量集中成 `USER_ENV`（模式与硬性规则见 §4.2）。

### 7.2 MetaX 的环境变量（即 `USER_ENV` 的内容）

在容器内「执行用户阶段」export（**不要**写进 `.bashrc` —— 非交互路径不读它）。顺序与写法照抄：

```bash
export MACA_PATH=/opt/maca
export MACA_SMALL_PAGESIZE_ENABLE=1
export LD_LIBRARY_PATH=/opt/mxdriver/lib:${MACA_PATH}/lib:${MACA_PATH}/ompi/lib:${MACA_PATH}/mxgpu_llvm/lib:${LD_LIBRARY_PATH}
export PATH=${MACA_PATH}/bin/:$PATH
export MACA_DIRECT_DISPATCH=1
```

- **为什么必须 export**：`su -` 是 login shell，会把 Docker ENV 里追加的 `/opt/maca/*`、
  `/opt/mxdriver/bin` 清掉（2026-09-18 实测）；而 `/opt/conda/bin` **会**保留（镜像的 conda 配置在
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

### 7.3 MetaX 侧的常见坑

- **镜像版本要对**：镜像必须带目标模型实现与所需参数（如 DeepSeek-V4.1 要带 `vllm_metax 0.28.0`
  的那类），否则报 `unrecognized arguments: --engram-config`。别把镜像名写死不给退路 → 提供 `--image`。
- **`vllm --help` 报 `pymxsml.NVMLError_InvalidArgument`**：是设备没挂进容器（缺 `/dev/dri`、
  `/dev/mxcd`、`--group-add video`），不是环境变量问题。
- **权重加载完（如 `48/48 shards`）后静默几分钟**：在编译 kernel（TileLang），不是卡死。
- **单 die 显存要按 `mx-smi` 实际值算**，别把多个 die 当成共享显存；起服务前确认这些 die 空闲。
- **client 侧外部工具（AISBench 等）的环境变量集中在自己的 `xxx_env.sh`**（见 §6），不写进 jsonc ——
  这类配置两家机器一模一样，放脚本里才能两家共用一份 jsonc。

### 7.4 MetaX 性能环境变量（写进 config 的 `server.env`，与模型绑定，必须问）

有些环境变量**只影响 MetaX 上的性能**，而且**与模型绑定** —— 不是每个模型都需要，所以不能默认写死；
生成时按 §1 第 4 条**启发式问一句**。写法是 config 的 `server.env`（顶层默认即可、全部任务生效，
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

- DeepSeek-V4.1-Flash @ MetaX **需要这 4 个**（用户 2026-09-16 确认）——可作写法模板，
  但别的模型必须重新确认，不要照抄。
- **对 NVIDIA 无效但无害**：被框架忽略，不影响执行与性能 ⇒ 不做平台分支，两家共用一份 config。
- 值写 `1`（数字）或 `"1"`（字符串）都行：ModelzooTool `_merge_env`
  （`bin/utils/command_builder.py`）会把 int/float 转成 str。
- 与 §7.2 的区别：**§7.2 那些是"让 MACA 环境跑起来"的容器级变量，由容器内脚本 export；
  本节这些是"让模型跑得快"的模型/平台开关，写在 config 里、随配置走**。
  `MACA_SMALL_PAGESIZE_ENABLE` / `MACA_DIRECT_DISPATCH` 两处都出现是正常的（一个管容器环境、
  一个管 server 进程），值保持一致即可。
- 换模型/换平台时回头核对这一段：它属于"模型专属配置"，**不要**照抄到别的模型配置里。
