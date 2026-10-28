# 配置心智模型（写 config 前必须理解）

> 由 `SKILL.md` 按需加载。模板见 [config_template.jsonc](./config_template.jsonc)。

**魔法变量渲染**发生在 `bin/utils/command_builder.py`：命令、`env` 里的每个
字符串都会做 `{key}` 替换。可用变量：

| 变量 | 来源 | 备注 |
|------|------|------|
| `{bs}` `{input}` `{output}` | 当前 case | 由 `bs_in_out` 注入 |
| `{prompts}` | 工具计算 | = `bs × task_info.promptRatio`（默认 1） |
| `{modelPath}` | 顶层 `modelPath` | 也可直接写死在命令里 |
| `{__LOG_PATH__}` | 工具计算 | 当前 case 的日志目录，**每 case 独立** |
| `{__PORT__}` | 工具计算 | **自动探测的可用端口**；同一任务内 server/client 拿到**同一个值**（首次渲染时探测，随后缓存） |
| `{__FILE_NAME__}` | 工具计算 | 当前 config 文件名（不含扩展名） |
| `{任意task_info键}` | `task_info` | 自定义魔法变量 |

> 注意：`bs/input/output/prompts/modelPath/__LOG_PATH__/__PORT__/__FILE_NAME__` 是**保留名**，
> 即使写进 `task_info` 也会被覆盖。
>
> `{__PORT__}` 与 `task_info.port`（即 `{port}`）不冲突：前者是自动探测值，后者是手动写死的值；
> 需要“同一任务内 server/client 自动对齐端口”就用 `{__PORT__}`，不要两处分别写死。
>
> `pair` 模式同样安全：case 与任务都是**严格串行**的 —— Client 结束后先杀掉 Server 并清理，
> 才进入下一个 case（`bin/main.py` 的 `start_modelzoo`）⇒ 同一任务复用同一端口不会冲突。

**命令拼装规则**（server 与 client 同规则）：

```
最终命令 = (任务级 cmd 若非 null ? 任务级 cmd : 默认 cmd) + 渲染后的 extra_args
```

- 任务级 `cmd: null` → 用默认命令；给了字符串 → **整条覆盖**默认命令。
- `extra_args` 永远追加在末尾。
- `env`：默认 env 与任务级 env 合并，任务级同名键覆盖默认。

**client 的 `warmup`**：为 `true` 时，client 变成 `基础命令 && 基础命令+extra_args`
（先跑一遍热身，再跑带 `--profile` 等的目标命令）。
**只有 profile 抓取才开**；attn / mcblas / mctlass 三类抓取**不开**（见 [vendors.md](./vendors.md) §7.6）。

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
