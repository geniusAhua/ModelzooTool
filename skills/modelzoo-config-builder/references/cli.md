# ModelzooTool 的 CLI 参数（速查）

> 由 `SKILL.md` 按需加载。**写配置 / 生成脚本前先看这一节。**

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
| `--tag <后缀>` | `None`（纯时间戳命名） | 加在**结果目录名末尾**，用于区分同名任务的多次运行。⚠️ **值为空时不要传**（会生成带 `+` 结尾的怪目录），写法见 [delivery.md](./delivery.md) §4.1 |
| `--dry-run` | `False` | **只渲染并打印**每个 case 的 server/client 命令与将注入的环境变量；**不启动任何进程、不建日志目录、不清 triton 缓存**。本技能里「零成本自检 + 开跑前回执确认」主要靠它（见 [delivery.md](./delivery.md) §3 步骤 4、[validation.md](./validation.md)） |
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
  职责划分与实现要点见 [delivery.md](./delivery.md) §4.1。
