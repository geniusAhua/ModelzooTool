# 使用说明

## 命令
通过--help查看命令帮助
***目前可以使用测试功能的是-E功能，请勿使用其他的功能测试***，**还在优化中**

## config.json
命令可以使用魔法变量进行替代，魔法变量有以下这些：
```bash
#! 注意！命令中需要保留{}符号不被解析，则多套一层即可
-O '{{"full_cuda_graph": true}}'
#模型名称
{modelName}
#模型路径
{modelPath}
#batch size
{bs}
#input_len
{input}
#output_len
{output}
#tp
{tp}
#port
{port}
#prompts数量，同promptRatio相关，其值为：(bs * promptRatio)
{prompts}
```

```jsonc
//举例
{
    //version
    "MACA": "v3.3",
    "backend": "vllm-v0.11.0",
    //Mission
    "modelName": "ERNIE-4_5-VL-28B-A3B-Thinking",
    "modelPath": "/mxstorage/pde_ai/models/llm/ERNIE/ERNIE-4.5-VL-28B-A3B-Thinking/",
    "tp": 2,
    "port": 4567,
    "promptRatio": 10,
    "server":{
        "cmd": "vllm serve {modelPath} --distributed-executor-backend ray --trust-remote-code --port {port} -tp {tp} --gpu-memory-utilization 0.91 --no-enable-prefix-caching"
    },
    "client": {
        "cmd": "python /sw_home/m01088/ModelZoo.LLM.Inference/vllm/code/src/benchmark_serving.py  --model {modelPath} --dataset-name custom_multiModal --dataset-path /sw_home/m01088/ModelZoo.LLM.Inference/vllm/data  --backend openai-chat --endpoint /v1/chat/completions --custom-input-len {input} --custom-output-len {output}  --num-prompts {prompts} --port {port} --trust-remote-code --max-concurrency {bs} --ignore-eos --metric-percentiles 95,99 --profile"
    },
    "Profiler":{
        "bs_in_out":[
            [32, 1024, 32],
            [32, 1024, 32]
        ]
    },
    "GemmShape":{
        "bs_in_out":[
            []
        ]
    },
    "FlashAttnShape":{
        "bs_in_out":[
            []
        ]
    },
    "TritonDump":{
        "bs_in_out":[
            []
        ]
    },
    "E2E":{
        "bs_in_out":[
            [1, 1024, 1024],
            [1, 2048, 1024],
            [16, 1024, 1024],
            [16, 2048, 1024],
            [32, 1024, 1024],
            [32, 2048, 1024],
            [64, 1024, 1024],
            [64, 2048, 1024]
        ]
    }
}
```

***

推荐的执行脚本如下：
```bash
# user `id -u` to get your user_id
uid=
user=

platform=$1
: "${platform:?ERROR: 该脚本需要一个参数 platform 不能为空}"

if id "$user" &>/dev/null; then
    echo "用户 $user 已存在，跳过创建"
else
    useradd -m -l -u ${uid} -s /bin/bash ${user}
    usermod -aG video,root ${user}
fi

pip install vllm==0.11.0 pandas datasets json5 decord

su - ${user} << EOF
    mkdir -p /home/${user}/.cache/huggingface/modules/transformers_modules/
    cp /mxstorage/pde_ai/models/llm/ERNIE/ERNIE-4.5-VL-28B-A3B-Thinking/Roboto-Regular.ttf /home/${user}/.cache/huggingface/modules/transformers_modules/
    python /sw_home/${user}/scripts/ModelzooTool/bin/main.py --config /sw_home/${user}/scripts/modelzooTask/jiyun/ERNIE-4.5-VL-28B-A3B/ERNIE-4_5-VL-28B.jsonc -E -o /sw_home/${user}/scripts/modelzooTask/jiyun/ERNIE-4.5-VL-28B-A3B/${platform}/
EOF
```