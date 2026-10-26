# 校验（可选；只交模板时跳过）

> 由 `SKILL.md` 按需加载。**默认不验证**：交付后先由**用户检查**，用户点名要验时再做本节；
> 用户只要求「给个模板」时同样跳过（[gate.md](./gate.md) §0-F）。

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

再跑一次**脚本自己的 `--dry-run`**（两层预演，见 [delivery.md](./delivery.md) §4.1）—— 它能顺带暴露渲染错误、镜像不存在、
任务名拼错，以及「切用户后会 export 什么」：

```bash
bash run_nvidia.sh <framework> <task> --dry-run
```

最后用**「空壳容器 + 假任务名」验 `su -` 那条链**（`--dry-run` 走不到它，见 [delivery.md](./delivery.md) §4.1）：
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
