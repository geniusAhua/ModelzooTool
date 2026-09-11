# 使用说明

## 命令
通过--help查看命令帮助

`-E`会启动端到端测试，该测试仅启动一次server，然后遍历提供的case，串行启动client

其余类型的任务，server和client是成对调度，每一个case都对应一对server命令和client命令, `-ptfb` 表示执行profile，tlas， flash attn，blas

## config.json
`task_info`中是自定义魔法变量，可在 命令/环境变量/额外参数 中，通过 `{}` 包起来使用对应的魔法变量值
工具默认提供的魔法变量名称为：
1. `__LOG_PATH__`
    当前case的server log和client log的生成路径
2. `__FILE_NAME__`
    当前作业的配置文件名称
3. `bs, input, output`
    当前case对应的bs，input，output。由于必须提供case才能启动client，如果**client不需要这些参数值**，也可以设置一个**无意义的值**用于**占位**来正常启动client
4. 关于`{}`使用事项
    如果字符串中需要提供`{}`，请多加一层，写为`{{}}`,这样python可以将其正确解释为`{}`否则会认为是一个魔法变量尝试渲染
5. 关于 server 就绪标志 `readyTag`（可选）
    工具默认以 server 日志中出现 `Application startup complete` 作为“启动完成”信号（命中后才会启动 client）。
    该标志可在配置中自定义：顶层写 `readyTag` 作为全局默认值，或在某个任务段内写 `readyTag` 覆盖它。
    值可以是字符串，也可以是字符串数组（命中任意一个即认为就绪）。

```jsonc
//举例
{
    // ==================== 基础信息 ====================
    // task_info里面的字段可以作为魔法变量，用于渲染出真正的server cmd和client cmd。此时就需要保证命令中的待填充变量名和字段名相同
    "modelPath": "/metax0402/models/jd-opensource/JoyAI-LLM-Flash",
    // server 启动完成的日志标志（可选，默认 "Application startup complete"）
    // 支持字符串或字符串数组（命中任意一个即认为就绪）；也可以在具体任务段里写 readyTag 覆盖顶层
    "readyTag": "Application startup complete",
    // 自定义可填充项，命令/环境变量/额外参数中如果使用{}包起来，表示当前值需要被填充，如果在task_info中存在，将会使用该值进行替代
    "task_info":{
        "tp": 2,
        "chunk_size": 12,
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
            "cmd": "python /home/huitian/m01088/JoyAI/bash_file/jd_find_best_case.py -p {port} --cache --log-path {__LOG_PATH__}",
            "env": {},
            "extra_args": []
        }
    },

    // ==================== Profiler 任务（非 E2E，使用 Pair 模式） ====================
    "Profiler": {
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

推荐的执行脚本如下：
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
    cmd+="python \"$SCRIPT\" --config \"$config\" -E -o \"$LOG_DIR\""$'\n'
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
