---
name: modelzoo-config-builder
description: 为 ModelzooTool 启发式生成 config.jsonc 与执行 bash 脚本。当用户想跑 vllm / sglang 推理服务的端到端压测、Profiler 或 TlasShape/BlasShape/FlashAttnShape/Triton 抓取，或提到"生成 Modelzoo config""写个跑 ModelzooTool 的脚本""server 命令 + client 命令""--task""--dry-run"时使用。⚠️ 动手前先过门禁：先问平台（NVIDIA / MetaX / 其他）；再分清脚本是 client 还是 server（不清就问）；再分清跑在宿主机还是容器——host 必出 2 个脚本（起容器 + 容器内执行），container 只出 1 个（与平台正交）；执行用户/uid 只由框架脚本负责且必须问；环境变量一律进 env 不要塞进 cmd；易变值做成脚本参数；脚本一律最简，先给模板不现场验证。**server/client 脚本一个脚本只对应一个任务、参数写死不传参、不做兼容适配、代码量最小；用户没要求不建单独脚本（直接写进 config），建了必须打印最终执行命令**。创建任务前还必须逐条弹框确认口径 12 项。
argument-hint: server 命令 + client 命令 + 环境变量（并说明平台与 host/container）
---

# ModelzooTool 配置生成器

把「一堆散乱的 server/client 命令」变成 ModelzooTool 可直接运行的
`config.jsonc` + 执行脚本。

**核心原则：用户只提供三样东西 —— 环境变量、server 命令、client 命令。**
其余字段（`modelPath`、`task_info`、`readyTag`、任务段（名字与 `type`）、`bs_in_out`、
`extra_args`、脚本骨架）由你**先从命令里推导，再启发式补问**，不要一上来就让用户填 JSON。

## 脚本数量由「跑在哪」决定（与厂商无关）

| 跑在哪 | 出几个脚本 | 说明 |
|--------|-----------|------|
| **host（宿主机）** | **2 个**：① 启动容器的脚本 + ② 在容器里执行的脚本 | 这是**两个步骤，必须分开**；宿主机不得执行应当在容器内执行的操作 |
| **container（容器内）** | **1 个**：容器内执行的脚本（即 host 形态的第 ② 个） | 容器已存在，不用管建容器 / 挂载 / 镜像 |

**为什么 host 必须拆成两个**：第 ② 个脚本是一份**可复用资产** —— 现场只有容器可用
（容器已存在、别人起的、只能用 `docker exec`）时，直接复用第 ② 个即可。

厂商（NVIDIA / MetaX）只决定「起容器的参数、镜像、`USER_ENV`」，**不改变脚本数量**。
模板：NVIDIA `run_nvidia.sh` + `run_in_container_nvidia.sh`；MetaX `run_metax.sh` + `run_in_container_metax.sh`。

## 门禁与必问清单（动手前必做）

**形态组（先问，决定生成几个文件）**

| # | 必问项 |
|---|--------|
| A0 | **跑在哪个平台**（NVIDIA / MetaX / 其他）？决定容器参数、镜像、`USER_ENV` |
| A1 | **脚本是 client / server / 框架**？不清就直问，不要猜、不要一次给两个；**并先问「是否真要单独脚本」——用户没要求就不建，命令直接写进 config** |
| A2 | **跑在宿主机还是容器**？host 还要问**镜像**；host=2 个脚本，container=1 个 |
| A3 | **执行用户 user + uid / 属组**？（仅框架脚本；client/server 脚本不写 `useradd`/`su`）；host 形态还要定**容器名的工号后缀**（`<名字>-<工号>`） |
| A4 | **（仅框架脚本）哪些易变值做成参数**？（端口、并发、条数、fewshot、输出目录）。server / client 脚本**不参数化**：一个脚本一个任务、直接写死 |

**口径组（判断标准，一项都不能省）**

| # | 必问项 |
|---|--------|
| ① | cudagraph 开 / 关（压测→开；抓 shape/kernel→关 `--enforce-eager`） |
| ② | prefix cache 关 / 不关（两家默认都开，A/B 两边必须一致） |
| ③ | mem-fraction 或 gpu-memory-utilization 的**具体数值** |
| ④ | `readyTag`：默认 / 继承顶层 / 任务级自定义（**只支持单个字符串**） |
| ⑤ | client 是否 `--ignore-eos`（SGLang 默认开、vLLM 默认关） |
| ⑥ | **最终环境变量逐条复述**请用户确认（attn / mcblas / mctlass 抓取任务必须把整张 env 表逐项发出审核） |
| ⑦ | **最终命令参数逐条复述**请用户确认 |

> 用 `vscode_askQuestions` **逐条弹框**，不能合并成一句「还有别的要加的吗」。
> 完整问法、默认建议与「为什么必须问」见 [heuristics.md](./references/heuristics.md#-必问清单12-项--形态-5-项--口径-7-项不得自己拍板)。

## 五步流程

0. **定形态** —— 逐条确认 A0–A4，**未确认前不要写文件**。见 [gate.md](./references/gate.md)。
1. **推导 + 问口径** —— 扫描命令做启发式落位，再逐条问 ①–⑦。
   见 [heuristics.md](./references/heuristics.md)。
2. **填配置** —— 复制 [config_template.jsonc](./references/config_template.jsonc)，
   按推导结果填 `modelPath` / `task_info` / `readyTag` / `server` / `client` / 各任务段。
   规则见 [config-model.md](./references/config-model.md)
   （魔法变量、`cmd` 覆盖语义、`extra_args` 追加、`readyTag` 取用顺序、`{}` 转义）。
3. **生成脚本** —— 按形态出 1 个或 2 个，**一律最简**（不加汇总/重试/轮询/参数解析器）。
   **server / client 脚本：一个脚本只对应一个任务** —— 参数写死、不传参、不做兼容分支、代码量最小优先；
   **默认不建这类脚本**（命令直接写进 config 的 `cmd`），用户明确要才建；建了必须 `set -x` 打印最终命令；
   需要验证的部分先不验证，交付后由用户检查再定。
   模板：[run_host_template.sh](./references/run_host_template.sh)（① 起容器）、
   [run_template.sh](./references/run_template.sh)（② 容器内）。
   CLI 透传与切用户规则见 [delivery.md](./references/delivery.md) §4.1 / §4.2
   （`--tag` 空值不传、`--dry-run` 两层预演、`su - <user>` + `USER_ENV`）。
4. **回执确认**（仅真正开跑时）—— 把合并后的 env 表与渲染后的 server/client 命令逐条发回，
   用户确认后才开跑；有 `--dry-run` 先用它。**只是交模板则跳过**，改为列出「假定项 + 待确认项」。

## 交付物

| 文件 | 内容 |
|------|------|
| `config.jsonc` | ModelzooTool 配置（JSON5），**两个厂商共用** |
| `run_<vendor>.sh` | 宿主机：起容器 → 调容器内脚本 |
| `run_in_container_<vendor>.sh` | 容器内：装依赖 → 建用户 → `su` 切用户 → 跑各 config |

> **server / client 脚本**另算：**一个脚本只对应一个具体任务**，命令与参数写死、**不传参、不做兼容适配**，
> 代码量最小优先（用户明确要求参数化时除外）。**用户没要求就不建单独脚本**，命令直接写进 config；
> 一旦建了，脚本**必须打印最终执行命令**（`set -x` 即可），否则 client 日志里看不到真实命令。
> 详见 [gate.md](./references/gate.md) §0-A。

执行入口：

```bash
python "<ModelzooTool>/bin/main.py" --config "<config.jsonc>" --task <NAME> [<NAME> ...] -o "<LOG_DIR>"
```

- `--task` 可跟**多个任务名**，按顺序跑；任务失败**只记录、不中断**，全部跑完若有失败以**退出码 1** 结束。
- 结果目录：`<LOG_DIR>/<config 文件名>/<任务名>/<时间戳[+tag]>/`。
- 全部 CLI 参数见 [cli.md](./references/cli.md)。

## 参考资料索引（按需加载，都在一层）

| 文件 | 什么时候看 |
|------|-----------|
| [gate.md](./references/gate.md) | 门禁 A–F、用户输入三件套 |
| [cli.md](./references/cli.md) | `main.py` 参数含义、默认值、行为约定 |
| [heuristics.md](./references/heuristics.md) | 命令 → 配置字段的推导表、12 项必问清单 |
| [config-model.md](./references/config-model.md) | 魔法变量、命令拼装、`readyTag`、转义 |
| [delivery.md](./references/delivery.md) | 生成流程细节、交付物、CLI 透传、`USER_ENV` |
| [validation.md](./references/validation.md) | JSON5 / `bash -n` / 两层 dry-run / 空壳容器自检 |
| [pitfalls.md](./references/pitfalls.md) | 常见坑（HOME、`su -`、e2e、AISBench…） |
| [vendors.md](./references/vendors.md) | NVIDIA / MetaX 差异、`MACA_*` 变量 |
| [config_template.jsonc](./references/config_template.jsonc) | 配置模板 |
| [run_host_template.sh](./references/run_host_template.sh) | 宿主脚本模板（`VENDOR` 分支） |
| [run_template.sh](./references/run_template.sh) | 容器内脚本模板（`VENDOR` 分支） |
