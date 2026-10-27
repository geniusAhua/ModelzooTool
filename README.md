# 使用说明

ModelzooTool 用一份 JSON5 配置，把「server 启动命令 + client 压测/抓取命令」参数化成任务，
按 `bs_in_out` 遍历用例批量执行，并收集日志与结果。适合 vLLM / SGLang 的端到端压测、
Profiler、以及 TlasShape / BlasShape / FlashAttnShape / Triton 抓取。

| 概念 | 说明 |
|------|------|
| 配置 | `--config <config.jsonc>`，JSON5（支持 `//` 注释与尾随逗号） |
| 任务段 | 配置里的顶层对象（名字自定），必须写 `type`：`e2e` / `pair` |
| 用例 | `bs_in_out` 里的一行 `[bs, input, output]` |
| 入口 | `bin/main.py` |

## 命令

通过 `python bin/main.py --help` 查看完整帮助。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--config <path>` | `bin/test/config.jsonc` | 要执行的 JSON5 配置；**不传时会回落到自带的示例配置**，建议总是显式指定 |
| `--task <name> [<name> ...]` | 无（必填） | **可写多个**，按顺序执行；任务名取自配置里的自定义任务段。名字不存在时会报错并列出全部可用任务名 |
| `-o, --output-dir <dir>` | `bin/../result` | 日志与结果根目录，不存在会自动创建 |
| `--tag <suffix>` | 空 | 加在结果目录名末尾，用于区分同名任务的多次运行；**值为空时不要传** |
| `--dry-run` | 关 | **只渲染并打印**每个 case 的 server/client 命令与将注入的环境变量；不建日志目录、不清 triton 缓存、不起任何进程 |
| `--list` | 关 | 列出配置里的任务名后退出；**必须同时给 `--config`**（不会回落默认配置）；不建目录、不跑任务 |
| `-h, --help` | — | 打印帮助 |

常用示例：

```bash
# 跑多个任务（按顺序）
python bin/main.py --config <config.jsonc> --task profiler tlas -o <log_dir>

# 先看会跑什么（零副作用，不建目录、不起进程）
python bin/main.py --config <config.jsonc> --task profiler --dry-run

# 列出配置里的任务名
python bin/main.py --config <config.jsonc> --list

# 同一任务跑多次时加 tag 区分
python bin/main.py --config <config.jsonc> --task profiler -o <log_dir> --tag v2
```

多个任务按 `--task` 给出的顺序依次执行；**某个任务失败不会中断后续任务**，会继续尝试剩下的任务，
全部执行完后若有失败的任务则以非零退出码（`1`）结束（并在结尾打印失败任务名）。

**结果目录**：`<output-dir>/<配置文件名>/<任务名>/<时间戳[+tag]>/`；
`pair` 模式下每个 case 再分 `bs{bs}-in{input}-out{output}/` 子目录。
日志文件为 `Server-*.log` / `Client-*.log`。

任务类型由任务段里的 `type` 字段决定（与任务名称无关，任务名随便起）：

| 类型 | 说明 |
|------|------|
| `e2e`  | 端到端：只启动一次 server，然后串行跑完所有 case |
| `pair` | 成对：每个 case 一对 server + client（每个 case 会重启 server），适合抓 profiler / shape 等 |

任务段示例（名称自定，只需写 `type`）：

```jsonc
"my_task": {
    // 必填，任务类型：e2e / pair
    "type": "pair",
    "bs_in_out": [[1, 1000, 16], [4, 2500, 16]],
    "server": { "cmd": null, "env": {}, "extra_args": ["--enforce-eager"] },
    "client": { "cmd": null, "env": {}, "extra_args": [] },
    // 可选：任务开始前清理 triton 编译缓存（原 TritonDump 的行为）
    "cleanTritonCache": true
}
```

## config.json
`task_info` 中的自定义字段，以及工具内置的变量，都可以在 **server/client 命令、环境变量、`extra_args`** 中写成 `{名称}` 引用，运行时被替换成真实值。

| 变量 | 含义 |
|------|------|
| `{bs}` `{input}` `{output}` | 当前 case 的并发 / 输入长度 / 输出长度（来自 `bs_in_out`）。 **client 不需要这些值时也要给个占位值**，否则 client 不会启动 |
| `{prompts}` | 工具计算：`bs × task_info.promptRatio`（默认 1） |
| `{modelPath}` | 顶层 `modelPath` |
| `{任意 task_info 键}` | 自定义值，例如 `{tp}` `{chunk_size}` `{port}` |
| `{__LOG_PATH__}` | 当前 case 的 server/client 日志目录 |
| `{__FILE_NAME__}` | 当前配置文件名（不含扩展名） |
| `{__PORT__}` | **自动探测的可用端口**，详见下方 |

### 关于 `{__PORT__}`（自动端口）

- 工具在首次渲染时用 socket 向内核申请一个空闲端口，**同一任务内 server 与 client 拿到同一个值**；不同任务各自独立。
- `--dry-run` 也会探测，并在输出里打印 `[<任务名>-PORT]: <端口>`。
- 运行后 server/client 日志头部会多一行 `[Server-PORT] <端口>` / `[Client-PORT] <端口>`，事后可对账。
- 与 `task_info.port`（`{port}`）**不冲突**：`{port}` 是你手写的值，`{__PORT__}` 是工具自动探测的值；不想手工改端口就用 `{__PORT__}`。
  ```jsonc
  {
      "server": { "cmd": "vllm serve {modelPath} --port {__PORT__}" },
      "client": { "cmd": "vllm bench serve --model {modelPath} --port {__PORT__}" }
  }
  ```
- `pair` 模式下 case 串行执行（Client 结束后先杀 Server 再进下一个），同一任务复用同一端口是安全的。

注意事项：

- `bs` / `input` / `output` / `prompts` / `modelPath` / `__LOG_PATH__` / `__PORT__` / `__FILE_NAME__` 是**保留名**，即使写进 `task_info` 也会被内置值覆盖。
- 如果字符串里需要字面量 `{}`，请多加一层写成 `{{}}`，否则会被当成魔法变量而报 `Missing`。

### 关于 server 就绪标志 `readyTag`（可选）

工具默认以 server 日志中出现 `Application startup complete` 作为“启动完成”信号（命中后才会启动 client）。
该标志可在配置中自定义：顶层写 `readyTag` 作为全局默认值，或在某个任务段内写 `readyTag` 覆盖它。
值只能是**单个字符串**（写数组会在加载配置时直接报错）。

> 非 vLLM 的服务（如 SGLang）启动日志不同，必须换成它自己的就绪行，否则工具会一直等下去（**不设等待超时**）。

```jsonc
//举例
{
    // ==================== 基础信息 ====================
    // task_info里面的字段可以作为魔法变量，用于渲染出真正的server cmd和client cmd。此时就需要保证命令中的待填充变量名和字段名相同
    "modelPath": "/metax0402/models/jd-opensource/JoyAI-LLM-Flash",
    // server 启动完成的日志标志（可选，默认 "Application startup complete"），只能是单个字符串
    // 也可以在具体任务段里写 readyTag 覆盖顶层的值
    "readyTag": "Application startup complete",
    // 自定义可填充项，命令/环境变量/额外参数中如果使用{}包起来，表示当前值需要被填充，如果在task_info中存在，将会使用该值进行替代
    "task_info":{
        "tp": 2,
        "chunk_size": 12,
        // 手写端口；也可以把命令里的 --port {port} 换成 --port {__PORT__}，让工具自动挑一个空闲端口
        "port": 1136
    },
    
    // 默认的命令，当任务类型不提供补充信息或者覆盖信息时，使用该默认命令来处理任务，默认命令是必须要提供的
    "server": {
        "cmd": "vllm serve {modelPath} --trust-remote-code --gpu-memory-utilization 0.9 -tp {tp} --port {port} --tool-call-parser qwen3_coder --enable-auto-tool-choice --max-num-batched-tokens $(({chunk_size} * 1024))",
        "env": {
            "MACA_VLLM_ENABLE_MCTLASS_FUSED_MOE": 1,
            "MACA_VLLM_ENABLE_MCTLASS_PYTHON_API": 1,
            "MACA_SMALL_PAGESIZE_ENABLE":1,
            "MACA_DIRECT_DISPATCH": 1,
            "CUDA_VISIBLE_DEVICES": "0,1,2,3"
        }
    },

    "client": {
        "cmd": "vllm bench serve --model {modelPath} --port {port} --dataset_name random --random-input-len {input} --random-output-len {output} --num-prompts {prompts} --trust-remote-code --max-concurrency {bs} --ignore-eos --backend openai-chat --endpoint /v1/chat/completions",
        "env": {}
    },

    // ==================== E2E 任务 ====================
    "E2E": {
        // 任务类型：e2e=只启动一次 server，串行跑完所有 case；pair=每 case 一对 server+client
        "type": "e2e",
        // 具体的case，分别表示bs, input, output, 是可填充项，填充名称为{bs}, {input}, {output}
        "bs_in_out": [
            [0, 0, 0]
        ],

        "server": {
            // cmd字段如果提供就会覆盖默认的命令
            "cmd": null,
            "env": {},
            // 会在基础命令之后添加额外的参数，基础命令可以是默认命令也可以是覆盖后的命令
            "extra_args": []
        },

        "client": {
            "cmd": "python /home/huitian/$USER/JoyAI/bash_file/jd_find_best_case.py -p {port} --cache --log-path {__LOG_PATH__}",
            "env": {},
            "extra_args": []
        }
    },

    // ==================== Profiler 任务（非 E2E，使用 Pair 模式） ====================
    "Profiler": {
        "type": "pair",
        "bs_in_out": [
            [1, 1000, 16],
            [1, 2500, 16],
            [1, 9000, 16],
            [1, 20000, 16],
            [4, 1000, 16],
            [4, 2500, 16],
            [4, 9000, 16],
            [4, 20000, 16]
        ],

        "server": {
            "cmd": null,
            "env": {},
            "extra_args": [
                "--profiler-config", "'{{\"profiler\":\"torch\", \"torch_profiler_dir\": \"{__LOG_PATH__}/{__FILE_NAME__}-tp{tp}-bs{bs}-in{input}-out{output}\"}}'"
            ]
        },

        "client": {
            "cmd": null,
            "env": {},
            // 选择是否要进行warmup，如果为true，则会使用&&拼接基础命令和补充后的目标命令
            "warmup": true,
            "extra_args": ["--profile"]
        }
    },


    "TlasShape": {
        "type": "pair",
        "bs_in_out": [
            [1, 1000, 16],
            [1, 2500, 16],
            [1, 9000, 16],
            [1, 20000, 16],
            [4, 1000, 16],
            [4, 2500, 16],
            [4, 9000, 16],
            [4, 20000, 16]
        ],

        "server": {
            "cmd": null,
            "env": {
                "MACA_LAUNCH_BLOCKING": 1,
                "MCTLASS_LOG_ENABLE": "ON",
                "MXLOG_LEVEL": "err,MCTLASSEX=debug"
            },
            "extra_args": ["--enforce-eager"]
        },

        "client": {
            "cmd": null,
            "env": {},
            "extra_args": []
        }
    },

    "BlasShape": {
        "type": "pair",
        "bs_in_out": [
            [1, 1000, 16],
            [1, 2500, 16],
            [1, 9000, 16],
            [1, 20000, 16],
            [4, 1000, 16],
            [4, 2500, 16],
            [4, 9000, 16],
            [4, 20000, 16]
        ],

        "server": {
            "cmd": null,
            "env": {
                "MACA_LAUNCH_BLOCKING": 1,
                "MXLOG_LEVEL": "err,MCBLAS=info,MCBLASLT=info"
            },
            "extra_args": ["--enforce-eager"]
        },

        "client": {
            "cmd": null,
            "env": {},
            "extra_args": []
        }
    },

    "FlashAttnShape": {
        "type": "pair",
        "bs_in_out": [
            [1, 1000, 16],
            [1, 2500, 16],
            [1, 9000, 16],
            [1, 20000, 16],
            [4, 1000, 16],
            [4, 2500, 16],
            [4, 9000, 16],
            [4, 20000, 16]
        ],

        "server": {
            "cmd": null,
            "env": {
                "MACA_LAUNCH_BLOCKING": 1,
                "MHA_LOG_ENABLE": 1,
                "MHA_PRINT_PARA": "ON",
                "MHA_INPUT_COLLECTION": "{__LOG_PATH__}/{__FILE_NAME__}-tp{tp}-bs{bs}-in{input}-out{output}"
            },
            "extra_args": ["--enforce-eager"]
        },

        "client": {
            "cmd": null,
            "env": {},
            "extra_args": []
        }
    }
}
```

***

推荐的执行脚本如下（**最简示例**，只演示「建用户 → 切用户 → 批量跑 config」；
容器命名要带用户名后缀、`--tag`/`--dry-run` 透传、`USER_ENV` 等完整约定：
```bash
# user `id -u` to get your user_id
# set -x

uid=
user=

if id "$user" &>/dev/null; then
    echo "用户 $user 已存在，跳过创建"
else
    useradd -m -l -u ${uid} -s /bin/bash ${user}
    usermod -aG video,root ${user}
fi


configs=(
    # config path
)

SCRIPT="${ModelzooTool_entry_PATH}"
LOG_DIR="${LOG_DIR}"

# pip source
pip3 config set global.index-url https://repo.metax-tech.com/r/pypi/simple
pip3 config set install.trusted-host repo.metax-tech.com
python -c "import json5" 2>/dev/null || pip install json5
# dependence
# pip uninstall transformers -y
# pip install transformers==5.6.0


cmd=""
for config in "${configs[@]}"; do
    cmd+="echo \">>> 开始执行: $config\""$'\n'
    # main execution, change the arg for your own project
    cmd+="python \"$SCRIPT\" --config \"$config\" --task <任务名> -o \"$LOG_DIR\""$'\n'
    cmd+="echo \">>> 完成: $config\""$'\n'
    cmd+="echo \"----------------------------------------\""$'\n'
done

# 再传给 su
su - "${user}" << EOF
    if [ -n "$CUDA_VISIBLE_DEVICES" ]; then
        export CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES
    fi

    if true; then
        export MACA_PATH=/opt/maca
        export LD_LIBRARY_PATH=/opt/mxdriver/lib:${MACA_PATH}/lib:${MACA_PATH}/ompi/lib:${MACA_PATH}/mxgpu_llvm/lib:${LD_LIBRARY_PATH}
        export PATH=${MACA_PATH}/bin/:$PATH
    fi

    if true; then
        $cmd
        echo "所有任务执行完毕！"
    fi
EOF
```

***

## skills（agent 技能）

`skills/` 目录存放 agent 技能真身，随仓库一起评审、演进、复用；每台机器上只需在 agent 的技能目录里放一个软链接指过来。
目录约定、`SKILL.md` 规范、安装/卸载命令、现有技能清单统一见 [`skills/README.md`](skills/README.md)。

### 技能一览

| 技能 | 用途 | 典型场景 |
|------|------|----------|
| `modelzoo-config-builder` | 启发式生成 `config.jsonc` 与执行脚本 | 端到端压测、Profiler、TlasShape / BlasShape / FlashAttnShape / Triton 抓取 |
| `trace-analyzer` | 解析 torch.profiler trace，出算子分类与阶段耗时报告 | 算子耗时占比、prefill/decode 耗时、两次 profile 对比 |
| `project-knowledge-base` | 维护项目内本地知识库 `.project-kb/PROJECT_KNOWLEDGE.md` | 接手 / 排查任何项目的第一步 |
| `git-commit` | Git 提交规范 | 任何 `git commit` 之前 |

#### `modelzoo-config-builder`

把「server 启动命令 + client 压测/抓取命令」写进一份 JSON5 配置，本工具按 `bs_in_out` 批量执行。
该技能负责**动手前把口径问清楚**（平台、脚本是 client 还是 server、跑在宿主机还是容器、执行用户等），
再按模板产出配置与最简脚本。

- 产物：`config.jsonc` + 执行脚本（host 场景 2 个：起容器 + 容器内执行；container 场景 1 个）
- 建议先 `python bin/main.py --config <cfg> --task <任务名> --dry-run` 确认会跑什么
- 细节见 `skills/modelzoo-config-builder/SKILL.md`

#### `trace-analyzer`

直接读取 torch.profiler 导出的 trace（`.json` / `.json.gz` / 含 trace 的 `zip`、`tar.gz`、目录，
**无需手动解压**），统计算子（大类 + 子类）与各阶段耗时，产出 Markdown 报告 + Excel。

- 口径：整体 GPU 耗时 = 全部 kernel `dur` 累加；prefill 取全部纯 prefill 段；
  **decode 只采样最后 5 段**；阶段外 kernel 不丢；自校验「各阶段之和 == GPU 总耗时」
- 算子大类耗时同时按 **prefill / decode** 拆分，混合段单列
- 多个 case 一次跑完，只产出一份 md + 一份 xlsx（每张表带 `case` 列）
- 脚本：`skills/trace-analyzer/scripts/tpa.py`

```bash
# 1) 先看有哪些 trace（多 rank 时弹框与用户确认，默认推荐 rank0）
python skills/trace-analyzer/scripts/tpa.py list <日志目录> --json

# 2) 单 case / 多 case（多 case 合并成一份报告）
python skills/trace-analyzer/scripts/tpa.py analyze <caseA> [<caseB> ...] --outdir <输出目录>

# 3) 改动前后对比（沿用原 torch_profile_analysis 的 Performance 口径）
python skills/trace-analyzer/scripts/tpa.py compare <ctl> <exp> --outdir <输出目录>
```

#### `project-knowledge-base`

强制流程：只要任务涉及某个项目，先读（没有就生成）该项目的 `.project-kb/PROJECT_KNOWLEDGE.md`，
记录用途、目录地图、运行/调试方法，以及「翻代码很慢、但查文档/上网很快」的经验，之后随代码变化增量更新。
知识库本身不提交（已在 `.gitignore` 中忽略）。

#### `git-commit`

统一提交口径：msg 必须以 `[refine/fix/doc/refactor/feature/test/chore/perf/build/ci]` 开头、
**只用英文**、非 fix 只写一行、fix 需空行后写 `root cause` / `solution`、混合类型必须拆成多次提交、
提交前用弹框把 msg 交给用户审核。

以 `modelzoo-config-builder` 为例（在仓库根目录下执行）：

```bash
REPO=$(git rev-parse --show-toplevel)     # 本仓库根目录
NAME=modelzoo-config-builder              # skills/ 下的技能目录名
DEST=~/.agents/skills                     # agent 读取全局技能的目录

mkdir -p "$DEST"
ln -sfn "../../$(realpath --relative-to="$HOME" "$REPO")/skills/$NAME" "$DEST/$NAME"
```

验证（能打印出 SKILL.md 的头部即成功）：

```bash
head -n 3 ~/.agents/skills/$NAME/SKILL.md
```

注意事项：

- **必须用相对路径**。同一份文件在不同平台看到的路径不同（Linux 侧 `/sw_home/<user>/...`，Windows 侧 `C:\Users\<user>\...`），绝对路径在另一端解析不了。
- `~/.agents/skills` 下若已有同名目录，`ln -s` **不会覆盖**它 —— 先 `rm -rf ~/.agents/skills/$NAME` 再建链接（或直接用 `ln -sfn`）。
- 新增技能不用改这里：把技能目录放进 `skills/`，对每个技能重复上面两条命令即可。
- 卸载只删链接，不动仓库里的真身：`rm ~/.agents/skills/$NAME`。
