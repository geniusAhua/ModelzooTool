---
name: modelzoo-config-builder
description: 为 ModelzooTool 启发式生成 config.jsonc 与执行 bash 脚本。当用户想跑 vllm/推理服务的端到端压测、Profiler 或 TlasShape/BlasShape/FlashAttnShape/Triton 抓取，或提到"生成 Modelzoo config""写个跑 ModelzooTool 的脚本""server 命令 + client 命令""--task"时使用。⚠️ 动手前先过 §0 门禁：先问平台（NVIDIA / MetaX / 其他）；再分清脚本是 client 还是 server（不清就问）；再分清跑在宿主机还是容器——**host 必出 2 个脚本（起容器 + 容器内执行），container 只出 1 个（不管什么平台都是这条规则，与平台正交）**；执行用户/uid 只由框架脚本负责且必须问；环境变量一律进 env 不要塞进 cmd；易变值做成脚本参数；脚本一律最简，先给模板不现场验证。创建任务前还必须逐条弹框确认口径 7 项（cudagraph、prefix cache、mem-fraction/gpu-util、readyTag、--ignore-eos、env 复核、命令复核）。
---

# ModelzooTool 配置生成器

本技能把「一堆散乱的 server/client 命令」变成 ModelzooTool 可直接运行的
`config.jsonc` + 执行脚本。

**脚本数量由「跑在哪」决定，与厂商无关（二者正交）**：

| 跑在哪 | 出几个脚本 | 说明 |
|--------|-----------|------|
| **host（宿主机）** | **2 个**：① 启动容器的脚本 + ② 在容器里执行的脚本 | 这就是 host 流程的**两个步骤，必须分开**；**宿主机不得执行应当在容器内执行的操作**，必须先起容器再 `docker exec` |
| **container（容器内）** | **1 个**：容器内执行的脚本（即 host 形态的第 ② 个） | 不用考虑建容器 / 设备挂载 / 镜像，容器已经存在 |

**为什么 host 必须拆成两个**：容器的启动与容器内执行是两件事，第 ② 个（容器内脚本）是一份**可复用的资产**——
当现场**只有容器环境可用**时（容器已存在、别人起的、只能用 `docker exec`），**直接复用第 ② 个脚本即可，不需要新写**。
合并成一个脚本就失去这种复用能力。

厂商（NVIDIA / MetaX）只决定「起容器的参数、镜像、`USER_ENV`」——见 §7；
**不管 NVIDIA 还是 MetaX，都先按上表定脚本数量**：host 就是起容器 + 容器内两个，container 就只要容器内那一个。
⚠️ **设计前必须先问平台是哪个**（必问项 A0），**host 形态还要问用哪个镜像**（必问项 A2）。

宿主机形态的模板：NVIDIA 用 `run_nvidia.sh`（起容器）+ `run_in_container_nvidia.sh`（容器内），
MetaX 用 `run_metax.sh` + `run_in_container_metax.sh`。

核心原则：**用户只提供三样东西 —— 环境变量、server 命令、client 命令。**
其余字段（`modelPath`、`task_info`、`readyTag`、任务段（名字与 `type`）、
`bs_in_out`、`extra_args`、脚本骨架）由你**先从命令里推导，再启发式补问**，
不要一上来就让用户填 JSON。

---

## 0. 开工前门禁（每次动手前 30 秒过一遍）

> 按「先问平台 → 定形态 → 定复杂度 → 定细节」排序，**不得跳过、不得自行拍板**。
> 一句话记住：**先问清「哪个平台、谁的脚本、在哪跑、谁执行」，再写最简的一版；不验证，先交模板。**
> ⚠️ **host / container 与平台无关**：任何平台都是 host 出 2 个脚本、container 出 1 个（见 §0-B）。

### A. 先分清脚本是谁（client / server / 框架）

| 脚本 | 职责 | 典型内容 |
|------|------|----------|
| **server 脚本** | 只负责起推理服务 | 一条 `vllm serve ...`（+ 少量变量） |
| **client 脚本** | 只负责压测 / 精度评测 / 抓数据 | 一条 `lm_eval ...` / `bench serve ...` |
| **框架脚本** | 只负责「准备容器 + 在容器里启动 ModelzooTool」 | `docker run` / `docker exec` + `main.py --config ... --task ...` |

- 用户说「写个脚本」却**没说清是 client 还是 server** → **必须先问**，不要猜、不要一次给两个。
- 识别线索：`serve` / `launch_server` / `ray start` → server；`bench` / `lm_eval` / `python xxx_test.py` → client；`docker run` / `main.py` → 框架。

### B. 再分清脚本在哪跑（host / container）——**与平台无关，全平台同一规则**

| 运行位置 | 需要几个脚本 | 说明 |
|----------|-------------|------|
| **container 内** | **只做一个** | 不用考虑创建容器 / 设备挂载 / 镜像 / 容器名；容器已存在，脚本只需把那条命令拉起来。**就是 host 形态的第 ② 个脚本**，可复用 |
| **host（宿主机）** | **必须两个，且分两步**：① 启动容器的脚本；② 进容器后真正跑命令的脚本 | **宿主机不得执行应当在容器内执行的操作**（如 `vllm serve` / `lm_eval`）。**不要合并成一个**：分开后，只有容器可用（容器已存在 / 别人起的）时可以**直接复用第 ② 个** |

- **必须问用户**：「这个脚本跑在宿主机还是容器里？」问不清就写明假设（host 两个 / container 一个）让用户确认。
- **host 形态还必须问：用哪个镜像（IMAGE）？** 镜像跟模型/框架/厂商绑定（沐曦还要带对应 vllm_metax 版本），拿不到镜像名就先不写死、做成变量。
- 平台（NVIDIA / MetaX）只影响「起容器的参数」，**不改变脚本个数**：宿主机上 NVIDIA 也要 `run_nvidia.sh`+`run_in_container_nvidia.sh` 两个，MetaX 也要 `run_metax.sh`+`run_in_container_metax.sh` 两个；容器内形态两家都只写一个。

### C. 脚本越简单越好（硬性）

- 目的只有一个：**启动 ModelzooTool**（框架脚本）或**执行那条 server/client 命令**（server/client 脚本）。
- 默认**不**加：结果解析、汇总表格、失败重试、超时轮询、日志轮转、参数解析器、多任务编排。
- 用户明确要才加；能一行 `exec` 解决的不要写 20 行 `if`。

### D. 执行用户 / uid：只归框架脚本，且必须问

- **client / server 脚本里不写**任何 `useradd` / `su` / `id -u` / uid 判断 —— 那是框架脚本的职责。
- 框架脚本里**必须问**：执行用户 `user`、`uid`（以及要不要补 `video,root` 组），并给建议默认值。
- 框架脚本用 `useradd -m -l -u <uid>` + `su - <user>`（§4.2）；client/server 脚本只管被调用。

### E. 配置里的环境变量：进 `env`，不进 `cmd`

| 情况 | 做法 |
|------|------|
| 固定环境变量（`MACA_*`、`HF_ENDPOINT`、`CUDA_*` …） | 写进 config 的 `server.env` / `client.env`（任务级覆盖顶层） |
| **容易变的值**（端口、并发、条数、fewshot、输出路径） | **做成脚本参数/顶部变量**，不要当成 env 去检查，也不要写死进 cmd |
| 需要随 case 变的值 | 用 `{bs}` / `{input}` / `{output}` / `{port}` 等魔法变量 |

- 禁止 `FOO=1 bash xxx.sh` 这种把 env 塞进 `cmd` 的写法（难检索、与 `env` 重复、任务级覆盖关系看不清）。

### F. 交付节奏：先模板，不验证，有疑问先问

- **先交付一版最简模板**，不做现场验证（不装依赖、不起容器、不跑任务）；用户会逐步补充。
- 不做「预防性」的复杂校验（目录检查、重试、锁、进度条）。潜在问题**先问用户**，并给出你的建议。
- 交付时用一句话说明「哪些是假定、哪些需要用户确认」，方便后续迭代。

---

## ModelzooTool 的 CLI 参数（速查 —— 写配置 / 生成脚本前先看这一节）

入口固定是 `bin/main.py`，`--help` 实测输出：

```
usage: main.py [-h] [--config CONFIG] [--tag TAG] [--task NAME [NAME ...]]
               [-o OUTPUT_DIR] [--dry-run] [--list]
```

| 参数 | 默认值 | 说明与注意事项 |
|------|--------|----------------|
| `--config <路径>` | `None` ⇒ **回落 `bin/test/config.jsonc`**（仓库自带的示例配置，**不是**用户自己的配置） | 指定要跑的 JSON5 配置。⚠️ 生成脚本时把它做成「默认取同目录 `config.jsonc`、允许覆盖」，否则会静默跑到示例配置上 |
| `--task <名字...>` | `None` | **可跟多个任务名**，按顺序执行；名字取自配置里的自定义任务段。缺省、或名字不存在，都会 `parser.error` **并列出配置里的全部任务名**（可顺带当"列任务"用） |
| `-o, --output-dir <目录>` | `bin/../result` | 日志与结果根目录，不存在会自动创建。实际落点见下方"结果目录" |
| `--tag <后缀>` | `None`（纯时间戳命名） | 加在**结果目录名末尾**，用于区分同名任务的多次运行。⚠️ **值为空时不要传**（会生成带 `+` 结尾的怪目录），写法见 §4.1 |
| `--dry-run` | `False` | **只渲染并打印**每个 case 的 server/client 命令与将注入的环境变量；**不启动任何进程、不建日志目录、不清 triton 缓存**。本技能里「零成本自检 + 开跑前回执确认」主要靠它（见 §3 步骤 4、§5） |
| `--list` | `False` | 列出 `--config` 里定义的所有任务名（按配置书写顺序）后退出；**必须同时给 `--config`**（它**不会**回落默认配置）；不建目录、不跑任务 |
| `-h, --help` | — | 打印帮助（本节的 usage 即来自它） |

**任务类型不是 CLI 参数**，而是写在配置的任务段里（`--task` 的 help 会顺带打印）：
`e2e`（只启动一次 server，串行跑完所有 case）／`pair`（每个 case 一对 server+client，每 case 重启 server）。

**标准执行入口**：

```bash
python "<ModelzooTool>/bin/main.py" --config "<config.jsonc>" --task <NAME> [<NAME> ...] \
    -o "<LOG_DIR>" [--tag <后缀>]
```

**行为约定**（生成脚本时要用到）：

- 某任务失败**只记录、不中断**，后续任务继续执行；全部跑完后若有失败，以**退出码 1** 结束。
- **结果目录**：`<LOG_DIR>/<config 文件名>/<任务名>/<时间戳[+tag]>/`，
  内含 `Server-*.log`（服务端）与 `Client-*.log`（客户端）。
- `--list` 与 `--dry-run` **都不创建任何目录**，可以在裸宿主机上放心试。
- 生成的宿主机脚本**必须能透传这些开关**（尤其 `--tag` 与两层 `--dry-run`）；
  职责划分与实现要点见 §4.1。

## 0.1 用户输入（只问这三样）

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
   例（具体模型需逐个确认）：`MACA_VLLM_ENABLE_MCTLASS_FUSED_MOE`、
   `MACA_VLLM_ENABLE_MCTLASS_PYTHON_API`、`MACA_SMALL_PAGESIZE_ENABLE`、`MACA_DIRECT_DISPATCH`
   —— 它们对 NVIDIA 无效但无害，所以写进共用 config、不做平台分支，详见 §7.4。
5. 命令里含义不明的参数：不确定是"固定参数"还是"随 case 变"时，问一句，别猜。

6. **【必问清单】创建任何任务/脚本前必须逐条弹对话框问（形态组 + 口径组，一项都不能省）**：
   **形态组（A0–A4）**：**平台是哪个（NVIDIA / MetaX / 其他）** · 脚本是 client / server / 框架 · 跑在 host / container · 执行用户 + uid（仅框架脚本）· 哪些易变值要做成脚本参数；
   **口径组（①–⑦）**：cudagraph 开/关 · prefix cache 关/不关 · mem-fraction 或 gpu-memory-utilization 数值
   · `readyTag` · client 是否 `--ignore-eos` · 最终环境变量复核 · 最终命令参数复核。
   完整问法、默认建议与「为什么必须问」见下方「⚠️ 必问清单」。

一次问齐，别来回拉扯；能默认的给默认值让用户确认。

### ⚠️ 必问清单（12 项 = 形态 5 项 + 口径 7 项，**不得自己拍板**）

> 用 `vscode_askQuestions` **弹对话框逐条确认**，**12 项一项都不能省**。选错会让结果直接失效
> （性能数字不可比 / 打点完全消失 / 服务等不到就绪 / 白跑一轮 8 卡 / 脚本数目与形态错），且事后再补成本极高。
> 每项都要给**默认建议**（见下表），让用户确认或改口，而不是让用户从零填。

**第 1 组：形态（先问，决定要生成几个文件、每个文件写什么）**

| # | 必问项 | 默认建议 / 怎么问 | 为什么必须问 |
|---|--------|------------------|-------------|
| A0 | **跑在哪个平台（NVIDIA / MetaX / 其他）？** | 按机器名 / 驱动 / 现有镜像给建议（沐曦：`mx-smi`、`/opt/maca`；NVIDIA：`nvidia-smi`） | 平台决定起容器的设备参数、镜像、`USER_ENV`（§7）；**但不影响脚本数量**（host/container 与平台正交） |
| A1 | **这个脚本是 client 还是 server？**（还是要「起容器 + 跑 ModelzooTool」的框架脚本） | 按命令关键词给建议（`serve`→server，`bench`/`lm_eval`→client，`docker`/`main.py`→框架）；**不清就直问** | 类型搞错 = 白写一个脚本；两者内容、位置、职责完全不同（§0-A） |
| A2 | **脚本跑在宿主机还是容器里？**（host 还要问**用哪个镜像**） | container → **只出 1 个**（不管什么平台）；host → **出 2 个、分两步**：起容器 + 容器内执行 | 决定交付几个文件；宿主机不得执行容器内该做的操作；镜像拿不准就做成变量（§0-B） |
| A3 | **执行用户 user + uid（属组）取多少？**（仅框架脚本需要） | 由用户给出用户名与 uid（一般与宿主执行用户一致）；属组按平台确认（如 `video` + `root`） | 产出文件属主错了宿主上打不开；`su -` 还会重置环境（§4.2） |
| A4 | **哪些值容易变、要不要做成脚本参数？** | 端口/并发/条数/fewshot/输出目录/dataset 路径 → 做成顶部变量或 CLI 参数；固定开关 → `env` | 写死就要改脚本，当 env 检查又会到处散落（§0-E） |

**第 2 组：结果口径（原 7 项，编号不变）**

| # | 必问项 | 默认建议 / 怎么问 | 为什么必须问 |
|---|--------|------------------|-------------|
| ① | **cudagraph 开还是关？** | **压测 / 性能测试** → 建议**开**：server 命令**不传** `--enforce-eager` / `--no-async-scheduling`（vLLM 默认就走 cudagraph）。**抓 shape / 抓 kernel 打点** → 建议**关**：加 `--enforce-eager` | 这两类的要求**正好相反**；开着 cudagraph 时 capture 之后 Python 层不再执行，打点 / `print` **全部消失**。量化依据见下方「为什么 cudagraph 必须问」 |
| ② | **prefix cache 关还是不关？** | 建议**跟随框架默认**，但必须**显式问一次**并写进口径说明；做 A/B 对比时两边必须一致 | 两家默认不同且都**默认开**：vLLM v1 `enable_prefix_caching=True`（`vllm/config/cache.py:91`，关闭用 `--no-enable-prefix-caching`）；SGLang 的 radix cache 默认开（关闭用 `--disable-radix-cache`）。命中前缀缓存会把 TTFT / 吞吐抬得极高 ⇒ 开关不一致，两次结果**不可比**。⚠️ 参数名以**目标镜像的 `--help`** 为准 |
| ③ | **mem-fraction / gpu-memory-utilization 取多少？** | 要用户给**具体数值**（如 SGLang `--mem-fraction-static 0.8`、vLLM `--gpu-memory-utilization 0.9`），**不要**留空走默认 | 它决定 KV cache 池大小 ⇒ 直接决定**并发上限**与会不会 OOM；共享机器上别人占用/释放会污染池预算（同一配置多次运行，可用量可能出现几十 GB 级差异）。⚠️ 两家参数名不同，别混用 |
| ④ | **`readyTag` 用默认值 / 继承顶层 / 任务级自定义？** | 三选一**显式确认**：**默认**（`Application startup complete`，vLLM 适用）/ **继承顶层**（顶层已写、任务段不写）/ **自定义**（任务段覆写，如 SGLang 的 `The server is fired up and ready to roll!`） | 匹配不到就绪，client **永远不启动、工具静默挂住**——而且工具**刻意不设等待超时**（避免大模型冷启/TileLang 编译被误杀），所以会一直挂着。⚠️ **只支持单个字符串**，写数组会在加载配置时 `ValueError`（见 §2） |
| ⑤ | **client 是否加 `--ignore-eos`？** | 加 = 输出压满 `--output-len`（口径固定、可比）；不加 = 尊重模型自然停止（贴近真实业务、长度不定）。**两家默认值相反**：**SGLang bench 默认开启**（要自然停止得显式关掉）、**vLLM bench 默认不开启**（要压满得显式加 `--ignore-eos`） | 决定「压满固定长度」还是「自然早停」，两种口径的吞吐 / TPOT **不可比**；默认值相反还会让「两边都不写」变成**口径不一致**。vLLM 侧已核实：`--ignore-eos` 是 `store_true`（`vllm/benchmarks/serve.py:1434`）。建议统一口径：SGLang 任务**不传**、vLLM 任务**显式传**。⚠️ SGLang 侧默认值以该版本 `--help` 为准 |
| ⑥ | **把最终环境变量逐条复述，请用户确认** | 生成后把**合并后的最终 env 列成表**发回逐条确认：顶层 `server.env` + 任务级 `env` + 容器级 `USER_ENV`（含厂商/模型开关）。有 `--dry-run` 就用它输出的 `[<task>-Server-ENV]` / `[<task>-Client-ENV]` / `[<task>-ENV:inherited]` 三行当依据 | 环境变量最常「**以为设了、其实没设**」：任务级会覆盖顶层；`su -` 会**清掉**镜像 Docker ENV 追加的目录（§7.2）；同一个变量可能同时出现在 `USER_ENV` 与 config 里（如 `MACA_SMALL_PAGESIZE_ENABLE`，§7.4 已注明两处都要一致） |
| ⑦ | **把最终命令参数逐条复述，请用户确认** | 生成后把**渲染后的完整 server / client 命令**列出来逐条确认（至少代表性 case，最好全部 case）：参数有没有漏、`{bs}/{input}/{output}` 是否落到该落的位置、`extra_args` 是否按预期追加、字面量 `{}` 是否写成 `{{}}`。用 `--dry-run` 的输出当确认依据最省事 | `cmd` 是**整条覆盖**语义（任务级一旦给字符串就不再拼默认命令），`extra_args` 又**永远追加**在末尾 ⇒ 很容易多一个少一个参数而没人发现，跑到一半才发现口径不对 |

顺带一并确认（视任务，别默认替用户决定）：

- **die 编号** —— 别依赖脚本默认值；共享机器上 die 常被占满，且默认容器名可能撞掉别人的容器。
- **是否要 `--save-result --result-dir`** —— 不加则没有每 case 的 `*.json`，结果只能从 `Client-*.log` 里翻。
- profile 类任务**固定**关 cudagraph + 关多 stream，属已定规则，**不必问**。

**为什么 cudagraph 这件事必须问（量化依据，vLLM 0.30.1.dev0 源码）**：`cudagraph_capture_sizes` 的单位是
**token、不是请求数**，上限 = `min(max_num_seqs × (num_speculative_tokens + 1) × 2, 512)`（非 Blackwell 平台为 512）；
列表按 `n × query_len` 生成且**只保留 `≤ 上限` 的项**。⇒ 开投机解码（γ=5 ⇒ `query_len=6`）时最多覆盖
**n ≤ 85 个请求**，再有请求数网格（`1,2,4,8,16,…`）限制，实际最大命中 **n=80 → 480 token**；因此
`bs ≥ 128` 的 case（768 / 1536 token）**拿不到图**、性能数字会偏低，要覆盖必须显式
`--max-cudagraph-capture-size`。反过来，抓 shape 时开着 cudagraph，打点连执行机会都没有。

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
- **只支持单个字符串**（`62650ec` 起）：写数组会在**加载配置时**直接抛 `ValueError`
  （fail loud，不会静默取第一个）。要按任务区分，就写在**任务段**里覆写顶层。
- 取用顺序：**任务段的 `readyTag` > 顶层 `readyTag` > 默认 `Application startup complete`**。
  ⇒ 必问项 ④ 的「默认 / 继承顶层 / 自定义」三选一，对应的就是这三种写法。
- **等非 vLLM 服务（如基于 uvicorn 的 SGLang）就绪，靠的就是它**：不同服务的
  就绪日志不一样，别去翻源码，直接在任务段里配置与服务日志对应的关键字；
  拿不准就把**该任务段**的那一个字符串换得更准（**不能**用数组兜底）。

示例：

```jsonc
"task_info": { "tp": 4, "port": 1136 },
"readyTag": "Application startup complete",   // 顶层全局默认
"sglang": {
    "type": "e2e",
    "readyTag": "The server is fired up and ready to roll!",   // 任务段覆写；⚠️ 只能单个字符串
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

0. **【先定形态，§0】** 逐条确认：**平台（A0）** · 脚本是 client / server / 框架 · 跑在 host / container（host→2 个脚本，container→1 个，与平台无关）· 执行用户 + uid（仅框架脚本）·
   哪些易变值要做成参数。**未确认前不要写文件**；用户只要「先给个模板」时，按最简假设产出，并在交付说明里列明假定。
1. 确认三样输入，扫描命令做第 1 节的推导。**同时把必问清单逐条弹对话框问完**
   （形态 A0–A4 + 口径 ① cudagraph ② prefix cache ③ mem-fraction / gpu-util ④ `readyTag`
   ⑤ `--ignore-eos` ⑥ 环境变量复核 ⑦ 命令参数复核），列出「推导结果 + 用户逐条确认结果」。
   ⚠️ 不能合并成一句「还有别的要加的吗」—— 逐条问、逐条留痕。
2. 复制 `references/config_template.jsonc`，按推导结果填充：
   - 顶层 `modelPath`、`task_info`、`readyTag`（非 vLLM 服务记得改）
   - 默认 `server` / `client`（cmd + env），把会变的参数替换成 `{...}`
   - 每个任务段都写 `type`（`e2e` 或 `pair`）；需要覆盖的 task 段落才写，
     不需要的任务段**整段删掉**（工具对缺失任务会跳过）
   - 任务级 `env` / `extra_args` / `readyTag` / `cleanTritonCache` 按需填
3. **按形态生成脚本（§0-B）**：
   - **容器内运行** → 只生成 **1 个**脚本（即容器内执行脚本，host 形态的第 ② 个）；
   - **宿主机运行** → 生成 **2 个、对应两个步骤**：`references/run_host_template.sh`（① 启动容器）+ `references/run_template.sh`（② 容器内执行），
     先问清**镜像（IMAGE）**再填；**按目标厂商各一套**（`VENDOR=nvidia|metax` 分支，见 §7），填 `user` / `uid` / `configs` /
     `ModelzooTool_entry_PATH` / `LOG_DIR` 等；外部评测工具（AISBench 等）的环境变量放它自己的
     `xxx_env.sh`，**不**放 jsonc 的 `client.env`（理由见 §6）。
   - 拆两步的意义：容器内脚本可**复用**——现场只有容器可用（容器已存在/别人起的）时，直接跑第 ② 个就行。
   - **一律保持最简**（§0-C）：不加结果汇总、重试、轮询、进度条、参数解析器。
   ★ 框架脚本模板已内置 **`--tag` 透传** 与 **两层 `--dry-run`**（含 `--print-user-env`，见 §4.1/§4.2），
   生成时**不要删掉**这两项能力；也不要为了省事把 `su -` 改回 `su -s /bin/bash`。
4. **【回执确认——仅在本次要真正开跑时做】** 把最终产物复述给用户并等确认（对应必问项 ⑥ ⑦）：
   **若只是交付模板（§0-F），跳过 dry-run / 验证**，改为在交付说明里逐条列出「假定项 + 待用户确认项」：
   - **环境变量表**：合并后的最终 env（顶层 `server.env` ＋ 任务级 `env` ＋ 容器级 `USER_ENV`），
     逐条列出，并标注每个变量"从哪来、覆盖了谁"；
   - **命令参数**：渲染后的完整 server / client 命令（代表性 case 或全部 case），逐条列出，
     指出哪些是固定参数、哪些随 case 变、`extra_args` 追加了什么；
   - 有 `--dry-run` 就**先用它渲染**（不建目录、不起进程、不占卡），把它的输出当依据；
   - 用户确认或改口后再进入下一步。**未经确认不得开跑**（一轮 8 卡任务的代价远超多问一次）。
5. 给用户一份「如何跑 + 如何回退 + 哪些是假定」的简短说明；**不做现场验证**（不装依赖、不起容器、不跑任务）。

## 4. 交付物

> **先按 §0-B 定形态（与平台无关）**：容器内运行 → **只交一个脚本**（不管 NVIDIA/MetaX）；宿主机运行 → **交两个、分两步**（① 启动容器 + ② 容器内执行，**不要合并**）。
> **host 形态先问镜像（IMAGE）**；容器内脚本是复用资产，现场只有容器可用时直接用它。
> client/server 脚本只是「把那条命令拉起来」，**不要**塞编排逻辑；用户/uid 的切换只出现在**框架脚本**里（§4.2）。
> 先交**最简模板**，不现场验证；潜在问题先问用户（§0-F）。

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

> 每个参数的**含义与默认值**见开头「ModelzooTool 的 CLI 参数」一节；这里只讲**生成的脚本怎么透传**它们。

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

> ⚠️ **本节只适用于框架脚本**。client / server 脚本里**不要**写 `useradd` / `su` / uid 判断——
> 执行用户由框架脚本统一负责，且 user/uid **必须问用户**（§0-D）。

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
- `USER_ENV` 的内容按厂商定：**MetaX** 见 §7.2；**NVIDIA** 无平台专用变量，只需把「框架 CLI / python
  所在目录」补回 PATH。

> 为什么要有 `--print-user-env`：宿主脚本的 `--dry-run` 不经过容器内脚本（§4.1），靠它才能把
> 「切用户后到底会 export 什么」展示出来，而且**单一来源**（不会两边不同步）。

## 5. 校验（可选；只交模板时跳过，见 §0-F）

> 用户只要求「给个模板」时**不做任何验证**；用户要求开跑 / 要求确认能跑时，才做本节。
> 即使做，也**不要真的启动任务**（不跑 `--task`），只做语法与渲染检查：

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
  （两平台统一）；属组统一 **`video` + `root`**（要再加别的组必须先问用户）；
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
  一直等（工具**不设等待超时**，会一直挂住）。按该服务自身就绪日志在任务段配 `readyTag`
  —— ⚠️ **只能填单个字符串**，填数组会在加载配置时 `ValueError`。
- **⚠️ 必问清单没问全就动手**：先问**形态组**（client/server/框架 · host/container · user+uid · 易变参数），
  再问**口径组**（cudagraph / prefix cache / mem-fraction 或 gpu-util / `readyTag` / `--ignore-eos` /
  环境变量复核 / 命令参数复核）—— 漏问任何一项都可能让整轮 8 卡任务白跑或白写一个脚本。
  见 §1「⚠️ 必问清单」。
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

**脚本形态 / 复杂度相关的坑（详见 §0）**：

- **没问平台 / host-container / 镜像就开始写** → 先问 A0 平台，再问 A2 跑在哪（host 还要问镜像）：容器内只需 1 个脚本，宿主机必须 2 个、分两步（① 起容器 + ② 容器内）。
  这条**不分厂商**（NVIDIA / MetaX 同一规则）；合并成一个"全能脚本"后就无法在「只有容器可用」时复用，直接返工。
- **在 client / server 脚本里写 `useradd` / `su` / uid 判断** → 职责越界；执行用户只由**框架脚本**负责，且必须问用户。
- **把环境变量塞进 `cmd`（`FOO=1 bash xxx.sh`）** → 与 config 的 `env` 重复、任务级覆盖关系看不清；
  固定变量一律写 `env`，易变值（端口/并发/条数/fewshot/输出目录）做成脚本参数或顶部变量。
- **给 client/server 脚本堆功能**（结果汇总、重试、轮询、参数解析器）→ 偏离"只负责拉那条命令"的定位；
  用户明确要才加。
- **为了"验证"去装依赖 / 起容器 / 真跑任务** → 用户只要求模板时不要现场验证；
  潜在问题先问用户并给建议（§0-F）。

## 7. 双厂商：NVIDIA / MetaX（生成的 bash 必须两家都能跑）

> **先看 §0-B**：不管 NVIDIA 还是 MetaX，脚本数量规则一样——**host 两个、分两步**（① 起容器 + ② 容器内），
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

### 7.3 MetaX 侧的常见坑

- **镜像版本要对**：镜像必须带目标模型实现与所需参数，否则会报 `unrecognized arguments: <某参数>`。
  别把镜像名写死不给退路 → 提供 `--image`。
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

- 上面这 4 个只是写作模板：不同模型/平台需要的开关不同，**必须按目标模型重新确认，不要照抄**。
- **对 NVIDIA 无效但无害**：被框架忽略，不影响执行与性能 ⇒ 不做平台分支，两家共用一份 config。
- 值写 `1`（数字）或 `"1"`（字符串）都行：ModelzooTool `_merge_env`
  （`bin/utils/command_builder.py`）会把 int/float 转成 str。
- 与 §7.2 的区别：**§7.2 那些是"让 MACA 环境跑起来"的容器级变量，由容器内脚本 export；
  本节这些是"让模型跑得快"的模型/平台开关，写在 config 里、随配置走**。
  `MACA_SMALL_PAGESIZE_ENABLE` / `MACA_DIRECT_DISPATCH` 两处都出现是正常的（一个管容器环境、
  一个管 server 进程），值保持一致即可。
- 换模型/换平台时回头核对这一段：它属于"模型专属配置"，**不要**照抄到别的模型配置里。
