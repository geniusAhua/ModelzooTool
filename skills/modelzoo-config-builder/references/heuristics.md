# 启发式推导与必问清单

> 由 `SKILL.md` 按需加载。**先推导（能推的绝不问），再按 12 项逐条弹框确认。**

## 1. 启发式推导（先做，能推的绝不问）

拿到三条命令后，先扫描命令文本，按下表自动落位；只有推不出来时才问。

| 命令里的线索 | 推导结果 |
|--------------|----------|
| 模型路径（`vllm serve <PATH>` 或 `--model <PATH>`） | 顶层 `modelPath`，命令中替换为 `{modelPath}` |
| `--port <N>` / `-p <N>` | `task_info.port`，替换为 `{port}`；若用户不想管端口，改用 **`{__PORT__}`**（同一任务内 server/client 自动对齐） |
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
   —— 它们对 NVIDIA 无效但无害，所以写进共用 config、不做平台分支，详见 [vendors.md](./vendors.md) §7.4。
5. 命令里含义不明的参数：不确定是"固定参数"还是"随 case 变"时，问一句，别猜。

6. **【必问清单】创建任何任务/脚本前必须逐条弹对话框问（形态组 + 口径组，一项都不能省）**：
   **形态组（A0–A4）**：**平台是哪个（NVIDIA / MetaX / 其他）** · 脚本是 client / server / 框架 · 跑在 host / container · 执行用户 + uid（仅框架脚本）· 哪些易变值要做成脚本参数；
   **口径组（①–⑦）**：cudagraph 开/关 · prefix cache 关/不关 · mem-fraction 或 gpu-memory-utilization 数值
   · `readyTag` · client 是否 `--ignore-eos` · 最终环境变量复核 · 最终命令参数复核。
   完整问法、默认建议与「为什么必须问」见下方「⚠️ 必问清单」。

一次问齐，别来回拉扯；能默认的给默认值让用户确认。

## ⚠️ 必问清单（12 项 = 形态 5 项 + 口径 7 项，**不得自己拍板**）

> 用 `vscode_askQuestions` **弹对话框逐条确认**，**12 项一项都不能省**。选错会让结果直接失效
> （性能数字不可比 / 打点完全消失 / 服务等不到就绪 / 白跑一轮 8 卡 / 脚本数目与形态错），且事后再补成本极高。
> 每项都要给**默认建议**（见下表），让用户确认或改口，而不是让用户从零填。

**第 1 组：形态（先问，决定要生成几个文件、每个文件写什么）**

| # | 必问项 | 默认建议 / 怎么问 | 为什么必须问 |
|---|--------|------------------|-------------|
| A0 | **跑在哪个平台（NVIDIA / MetaX / 其他）？** | 按机器名 / 驱动 / 现有镜像给建议（沐曦：`mx-smi`、`/opt/maca`；NVIDIA：`nvidia-smi`） | 平台决定起容器的设备参数、镜像、`USER_ENV`（[vendors.md](./vendors.md)）；**但不影响脚本数量**（host/container 与平台正交） |
| A1 | **这个脚本是 client 还是 server？**（还是要「起容器 + 跑 ModelzooTool」的框架脚本）；**还要问：是否真的需要单独脚本？用户没要求就直接写进 config** | 按命令关键词给建议（`serve`→server，`bench`/`lm_eval`→client，`docker`/`main.py`→框架）；**不清就直问** | 类型搞错 = 白写一个脚本；两者内容、位置、职责完全不同（[gate.md](./gate.md) §0-A）；默认不建脚本可避免「日志只看到 `run: bash xxx.sh`」 |
| A2 | **脚本跑在宿主机还是容器里？**（host 还要问**用哪个镜像**） | container → **只出 1 个**（不管什么平台）；host → **出 2 个、分两步**：起容器 + 容器内执行 | 决定交付几个文件；宿主机不得执行容器内该做的操作；镜像拿不准就做成变量（[gate.md](./gate.md) §0-B） |
| A3 | **执行用户 user + uid（属组）取多少？**（仅框架脚本需要）；host 形态还要给**容器名工号后缀** | 由用户给出用户名与 uid（一般与宿主执行用户一致）；属组按平台确认（如 `video` + `root`）；容器名固定为 `<基础名>-$USER`（展开后如 `mz-run-<工号>`） | 产出文件属主错了宿主上打不开；`su -` 还会重置环境（[delivery.md](./delivery.md) §4.2）；**容器名共用通用名会撞掉别人的容器**（[gate.md](./gate.md) §0-G） |
| A4 | **（仅框架脚本）哪些值容易变、要不要做成脚本参数？** | 框架脚本：端口/并发/条数/fewshot/输出目录/dataset 路径 → 顶部变量或 CLI 参数；固定开关 → `env`。**server/client 脚本不问**：一个脚本一个任务，直接写死、不传参（[gate.md](./gate.md) §0-A） | 框架脚本写死就要改脚本；server/client 加参数化会让「一个任务一个脚本」失真、代码变长 |

**第 2 组：结果口径（原 7 项，编号不变）**

| # | 必问项 | 默认建议 / 怎么问 | 为什么必须问 |
|---|--------|------------------|-------------|
| ① | **cudagraph 开还是关？** | **压测 / 性能测试** → 建议**开**：server 命令**不传** `--enforce-eager` / `--no-async-scheduling`（vLLM 默认就走 cudagraph）。**抓 shape / 抓 kernel 打点** → 建议**关**：加 `--enforce-eager` | 这两类的要求**正好相反**；开着 cudagraph 时 capture 之后 Python 层不再执行，打点 / `print` **全部消失**。量化依据见下方「为什么 cudagraph 必须问」 |
| ② | **prefix cache 关还是不关？** | 建议**跟随框架默认**，但必须**显式问一次**并写进口径说明；做 A/B 对比时两边必须一致 | 两家默认不同且都**默认开**：vLLM v1 `enable_prefix_caching=True`（`vllm/config/cache.py:91`，关闭用 `--no-enable-prefix-caching`）；SGLang 的 radix cache 默认开（关闭用 `--disable-radix-cache`）。命中前缀缓存会把 TTFT / 吞吐抬得极高 ⇒ 开关不一致，两次结果**不可比**。⚠️ 参数名以**目标镜像的 `--help`** 为准 |
| ③ | **mem-fraction / gpu-memory-utilization 取多少？** | 要用户给**具体数值**（如 SGLang `--mem-fraction-static 0.8`、vLLM `--gpu-memory-utilization 0.9`），**不要**留空走默认 | 它决定 KV cache 池大小 ⇒ 直接决定**并发上限**与会不会 OOM；共享机器上别人占用/释放会污染池预算（同一配置多次运行，可用量可能出现几十 GB 级差异）。⚠️ 两家参数名不同，别混用 |
| ④ | **`readyTag` 用默认值 / 继承顶层 / 任务级自定义？** | 三选一**显式确认**：**默认**（`Application startup complete`，vLLM 适用）/ **继承顶层**（顶层已写、任务段不写）/ **自定义**（任务段覆写，如 SGLang 的 `The server is fired up and ready to roll!`） | 匹配不到就绪，client **永远不启动、工具静默挂住**——而且工具**刻意不设等待超时**（避免大模型冷启/TileLang 编译被误杀），所以会一直挂着。⚠️ **只支持单个字符串**，写数组会在加载配置时 `ValueError`（见 [config-model.md](./config-model.md)） |
| ⑤ | **client 是否加 `--ignore-eos`？** | 加 = 输出压满 `--output-len`（口径固定、可比）；不加 = 尊重模型自然停止（贴近真实业务、长度不定）。**两家默认值相反**：**SGLang bench 默认开启**（要自然停止得显式关掉）、**vLLM bench 默认不开启**（要压满得显式加 `--ignore-eos`） | 决定「压满固定长度」还是「自然早停」，两种口径的吞吐 / TPOT **不可比**；默认值相反还会让「两边都不写」变成**口径不一致**。vLLM 侧已核实：`--ignore-eos` 是 `store_true`（`vllm/benchmarks/serve.py:1434`）。建议统一口径：SGLang 任务**不传**、vLLM 任务**显式传**。⚠️ SGLang 侧默认值以该版本 `--help` 为准 |
| ⑥ | **把最终环境变量逐条复述，请用户确认** | 生成后把**合并后的最终 env 列成表**发回逐条确认：顶层 `server.env` + 任务级 `env` + 容器级 `USER_ENV`（含厂商/模型开关）。**attn / mcblas / mctlass 三类抓取任务必须按 [vendors.md](./vendors.md) §7.5 的整张表逐项列出发给用户审核**，确认后才写进配置。有 `--dry-run` 就用它输出的 `[<task>-Server-ENV]` / `[<task>-Client-ENV]` / `[<task>-ENV:inherited]` 三行当依据 | 环境变量最常「**以为设了、其实没设**」：任务级会覆盖顶层；`su -` 会**清掉**镜像 Docker ENV 追加的目录（[vendors.md](./vendors.md) §7.2）；同一个变量可能同时出现在 `USER_ENV` 与 config 里（如 `MACA_SMALL_PAGESIZE_ENABLE`，[vendors.md](./vendors.md) §7.4 已注明两处都要一致） |
| ⑦ | **把最终命令参数逐条复述，请用户确认** | 生成后把**渲染后的完整 server / client 命令**列出来逐条确认（至少代表性 case，最好全部 case）：参数有没有漏、`{bs}/{input}/{output}` 是否落到该落的位置、`extra_args` 是否按预期追加、字面量 `{}` 是否写成 `{{}}`。用 `--dry-run` 的输出当确认依据最省事 | `cmd` 是**整条覆盖**语义（任务级一旦给字符串就不再拼默认命令），`extra_args` 又**永远追加**在末尾 ⇒ 很容易多一个少一个参数而没人发现，跑到一半才发现口径不对 |

顺带一并确认（视任务，别默认替用户决定）：

- **die 编号** —— 别依赖脚本默认值；共享机器上 die 常被占满。
- **容器名工号后缀** —— 一律 `<基础名>-$USER`（如 `mz-run-<工号>`），脚本里用 `USER_SUFFIX="${USER:-}"`，**不要写死工号、不要用 `$(id -un)` 猜、不要留空**（[gate.md](./gate.md) §0-G）。
- **是否要 `--save-result --result-dir`** —— 不加则没有每 case 的 `*.json`，结果只能从 `Client-*.log` 里翻。
- profile 类任务**固定**关 cudagraph + 关多 stream，属已定规则，**不必问**。

**为什么 cudagraph 这件事必须问（量化依据，vLLM 0.30.1.dev0 源码）**：`cudagraph_capture_sizes` 的单位是
**token、不是请求数**，上限 = `min(max_num_seqs × (num_speculative_tokens + 1) × 2, 512)`（非 Blackwell 平台为 512）；
列表按 `n × query_len` 生成且**只保留 `≤ 上限` 的项**。⇒ 开投机解码（γ=5 ⇒ `query_len=6`）时最多覆盖
**n ≤ 85 个请求**，再有请求数网格（`1,2,4,8,16,…`）限制，实际最大命中 **n=80 → 480 token**；因此
`bs ≥ 128` 的 case（768 / 1536 token）**拿不到图**、性能数字会偏低，要覆盖必须显式
`--max-cudagraph-capture-size`。反过来，抓 shape 时开着 cudagraph，打点连执行机会都没有。
