# 生成流程与交付物

> 由 `SKILL.md` 按需加载。含 §3 生成流程、§4 交付物、§4.1 CLI 透传、§4.2 切用户与 `USER_ENV`。

## 3. 生成流程

0. **【先定形态，[gate.md](./gate.md)】** 逐条确认：**平台（A0）** · 脚本是 client / server / 框架 · 跑在 host / container（host→2 个脚本，container→1 个，与平台无关）· 执行用户 + uid（仅框架脚本）·
   哪些易变值要做成参数。**未确认前不要写文件**；用户只要「先给个模板」时，按最简假设产出，并在交付说明里列明假定。
1. 确认三样输入，扫描命令做 [heuristics.md](./heuristics.md) 的推导。**同时把必问清单逐条弹对话框问完**
   （形态 A0–A4 + 口径 ① cudagraph ② prefix cache ③ mem-fraction / gpu-util ④ `readyTag`
   ⑤ `--ignore-eos` ⑥ 环境变量复核 ⑦ 命令参数复核），列出「推导结果 + 用户逐条确认结果」。
   ⚠️ 不能合并成一句「还有别的要加的吗」—— 逐条问、逐条留痕。
2. 复制 `references/config_template.jsonc`，按推导结果填充：
   - 顶层 `modelPath`、`task_info`、`readyTag`（非 vLLM 服务记得改）
   - 默认 `server` / `client`（cmd + env），把会变的参数替换成 `{...}`
   - 每个任务段都写 `type`（`e2e` 或 `pair`）；需要覆盖的 task 段落才写，
     不需要的任务段**整段删掉**（工具对缺失任务会跳过）
   - 任务级 `env` / `extra_args` / `readyTag` / `cleanTritonCache` 按需填
3. **按形态生成脚本（[gate.md](./gate.md) §0-B）**：
   - **容器内运行** → 只生成 **1 个**脚本（即容器内执行脚本，host 形态的第 ② 个）；
   - **宿主机运行** → 生成 **2 个、对应两个步骤**：`references/run_host_template.sh`（① 启动容器）+ `references/run_template.sh`（② 容器内执行），
     先问清**镜像（IMAGE）**再填；**按目标厂商各一套**（`VENDOR=nvidia|metax` 分支，见 [vendors.md](./vendors.md)），填 `user` / `uid` / `configs` /
     `ModelzooTool_entry_PATH` / `LOG_DIR` 等；外部评测工具（AISBench 等）的环境变量放它自己的
     `xxx_env.sh`，**不**放 jsonc 的 `client.env`（理由见 [pitfalls.md](./pitfalls.md)）。
   - 拆两步的意义：容器内脚本可**复用**——现场只有容器可用（容器已存在/别人起的）时，直接跑第 ② 个就行。
   - **容器名一律 `<基础名>-<工号>`**（如 `mz-run-m01088`）：工号写进脚本顶部变量 `USER_SUFFIX`，
     **生成时必须问用户**，未填就报错退出；`--keep` / `docker rm -f` 只能针对这个名字（[gate.md](./gate.md) §0-G）。
   - **一律保持最简**（[gate.md](./gate.md) §0-C）：不加结果汇总、重试、轮询、进度条、参数解析器。
   - **server / client 脚本：一个脚本只对应一个任务** —— 命令与参数全部写死、**不接收参数、不做兼容分支**，
     代码量最小优先（用户明确要求参数化时除外）。注意与框架脚本相反：框架脚本必须透传 `--task/--tag/--dry-run`。
   - **默认不建 server/client 脚本**：用户没要求就把命令直接写进 config 的 `cmd`；
     建了就必须 `set -x`（或显式 `echo`）**在执行前打印最终命令**，否则日志里看不到真实执行内容（[gate.md](./gate.md) §0-A-2）。
   ★ 框架脚本模板已内置 **`--tag` 透传** 与 **两层 `--dry-run`**（含 `--print-user-env`，见 §4.1/§4.2），
   生成时**不要删掉**这两项能力；也不要为了省事把 `su -` 改回 `su -s /bin/bash`。
4. **【回执确认——仅在本次要真正开跑时做】** 把最终产物复述给用户并等确认（对应必问项 ⑥ ⑦）：
   **若只是交付模板（[gate.md](./gate.md) §0-F），跳过 dry-run / 验证**，改为在交付说明里逐条列出「假定项 + 待用户确认项」：
   - **环境变量表**：合并后的最终 env（顶层 `server.env` ＋ 任务级 `env` ＋ 容器级 `USER_ENV`），
     逐条列出，并标注每个变量"从哪来、覆盖了谁"；
   - **命令参数**：渲染后的完整 server / client 命令（代表性 case 或全部 case），逐条列出，
     指出哪些是固定参数、哪些随 case 变、`extra_args` 追加了什么；
   - 有 `--dry-run` 就**先用它渲染**（不建目录、不起进程、不占卡），把它的输出当依据；
   - 用户确认或改口后再进入下一步。**未经确认不得开跑**（一轮 8 卡任务的代价远超多问一次）。
5. 给用户一份「如何跑 + 如何回退 + 哪些是假定」的简短说明；**默认不做现场验证**（不装依赖、不起容器、不跑任务）。
   **由用户先检查产出**，用户认为需要验证时再按 [validation.md](./validation.md) 做，且只做点名的项。

## 4. 交付物

> **先按 [gate.md](./gate.md) §0-B 定形态（与平台无关）**：容器内运行 → **只交一个脚本**（不管 NVIDIA/MetaX）；宿主机运行 → **交两个、分两步**（① 启动容器 + ② 容器内执行，**不要合并**）。
> **host 形态先问镜像（IMAGE）**；容器内脚本是复用资产，现场只有容器可用时直接用它。
> client/server 脚本只是「把那条命令拉起来」，**不要**塞编排逻辑；用户/uid 的切换只出现在**框架脚本**里（§4.2）。
> 宿主机脚本的**容器名必须带工号后缀**（`mz-run-<工号>`），共享机器上裸名会撞掉别人的容器（[gate.md](./gate.md) §0-G）。
> 先交**最简模板**，不现场验证；潜在问题先问用户（[gate.md](./gate.md) §0-F）。

| 文件 | 内容 |
|------|------|
| `config.jsonc` | ModelzooTool 配置（JSON5，支持 `//` 注释），**两个厂商共用** |
| `run_nvidia.sh` | 【NVIDIA】宿主机：起容器（`--gpus`）→ 调容器内脚本 |
| `run_in_container_nvidia.sh` | 【NVIDIA】容器内：装依赖 → 建用户 → `su` 切用户 → 跑各 config |
| `run_metax.sh` | 【沐曦】宿主机：起容器（设备节点 + die）→ 调容器内脚本 |
| `run_in_container_metax.sh` | 【沐曦】容器内：前置 `/opt/conda/bin` → 装依赖 → 建用户（补 `video,root`）→ `su` 切用户 → export `MACA_*` → 跑各 config |

> 只做一家也可以，但**先问清楚跑在哪家**，别默认只有 NVIDIA（差异见 [vendors.md](./vendors.md)）。

模板见：
- [config_template.jsonc](./config_template.jsonc)
- [run_host_template.sh](./run_host_template.sh)（宿主机，`VENDOR` 分支）
- [run_template.sh](./run_template.sh)（容器内，`VENDOR` 分支）

执行入口为：

```bash
python "<ModelzooTool>/bin/main.py" --config "<config.jsonc>" --task <NAME> [<NAME> ...] -o "<LOG_DIR>"
```

- `--task` 可跟**多个任务名**，按顺序执行；任务名取自 config 里的自定义任务段。
- 某任务失败**只记录、不中断**，后续任务继续执行；全部跑完后若有失败，以**退出码 1** 结束。

### 4.1 生成的脚本必须透传 ModelzooTool 的 CLI 参数

> 每个参数的**含义与默认值**见 [cli.md](./cli.md)；这里只讲**生成的脚本怎么透传**它们。

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
| `--keep` | 跑完保留容器（调试）；两厂商语义不同，见 [vendors.md](./vendors.md) §7.1 | —— |

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
`su - <user>` / `USER_ENV` / 建用户 / 补组 这些**一步都不会走**。要验它们用「空壳容器 + 假任务名」（见 [validation.md](./validation.md)）。

### 4.2 切用户与环境变量（`USER_ENV`）

> ⚠️ **本节只适用于框架脚本**。client / server 脚本里**不要**写 `useradd` / `su` / uid 判断——
> 执行用户由框架脚本统一负责，且 user/uid **必须问用户**（[gate.md](./gate.md) §0-D）。

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

硬性规则（两平台统一）：

- 切用户一律用 **`su - <user>`（login shell）**，**不要**用 `su -s /bin/bash <user> -c "PATH='$PATH' …"`。
- 属组统一 **`video` + `root`**；要再加别的组（如 `/dev/mem` 需要的 `kmem`）**必须先问用户**。
- **HOME 不迁移**：`useradd -m`（容器内 `/home/<user>`），绝不用 `-d` 指到宿主共享盘。
- `USER_ENV` 的内容按厂商定：**MetaX** 见 [vendors.md](./vendors.md) §7.2；**NVIDIA** 无平台专用变量，只需把「框架 CLI / python
  所在目录」补回 PATH。

> 为什么要有 `--print-user-env`：宿主脚本的 `--dry-run` 不经过容器内脚本（§4.1），靠它才能把
> 「切用户后到底会 export 什么」展示出来，而且**单一来源**（不会两边不同步）。
