---
name: pd-task
description: 新建/修改 PD 分离部署任务：在部署包里新建/修改 topology、每机入口脚本，替换 prefill/decode/router/client，配置端口/GPU/模型/client 次数，并用 stub 测试验证。当用户说“新加一个任务”“换 prefill/decode 脚本”“加机器/加 decode”“1P2D/2P2D 怎么配”时使用。
---

# PD 任务创建

## 0. 约定

- 部署包：新建任务时自行命名，下文用 `<包>` 指代（各机器同一共享路径）。只动 `config/`、`tools/` 和自建脚本目录，不改 `ModelzooTool/`（它是未改动的上游工具，PD 适配都在 `config/`）。
- 参考实现：仓库内的 [`../../pd_runs/example/`](../../pd_runs/example/)（launcher + 1P1D 模板）。从零起任务时优先以它为基础。
- 命名按**机器数**：1P1D = 1 台 P + 1 台 D（D 机跑 2 个 decode）；1P2D = 1 台 P + 2 台 D（共 4 个 decode）；2P2D = 2 台 P + 2 台 D。
- 每台机器一个入口脚本；全部机器共享同一个 `RUN_DIR`；服务由容器队列拉起，不手工启动。
- 临时调试文件放独立临时目录（如 `<临时目录>/claudecode/`），不放 `/tmp`；stub 只在离线测试用，不真跑模型。

## 1. 先判断改动类型

| 需求 | 改哪里 |
| --- | --- |
| 只改机器/GPU/端口/模型/client 次数 | 新建或改 topology YAML，**不用改 launcher** |
| 换 prefill/decode 命令或脚本 | topology 的 `instances[].cmd` |
| 换 router 命令或脚本 | topology 的 `router.cmd` |
| 换 client 命令/次数/数据集 | topology 的 `client`，或 `config/run_client.sh`、`config/pd.jsonc` |
| 新机器数/新节点名 | 新建 topology + 每机入口脚本 |
| router 独立机器、跨机单服务 | 当前 launcher 不支持，需要改 `config/launch.py` |

## 2. 创建新任务

### 2.1 复制最接近的拓扑

```bash
cd <包>
cp config/topology-2p2d.yaml config/topology-<任务名>.yaml
```

没有合适的现成拓扑时，从 [`../../pd_runs/example/config/topology-1p1d.yaml`](../../pd_runs/example/config/topology-1p1d.yaml) 起手，按需加节点/实例（示例里的服务脚本名是占位符）。

必须检查的字段：

- `coordinator`：恰好一个节点；**router 只能在该节点**（`router.node` 必须相同）。
- `run.dir`：所有机器可访问的同一路径。**并发任务用独立子目录**，例如 `${BUNDLE_DIR}/pd-run/<任务名>`，否则 `registry/` 串台。
- `nodes.<id>.ip: auto`：用 `detect_nic.sh` 探测的 `LOCAL_IP`；不要填 `0.0.0.0`。
- `instances[]`：`name` 节点内唯一；`kind` 为 `prefill`/`decode`；`port` 必填；prefill 还要 `bootstrap_port`。
- `gpus`：导出为 `CUDA_VISIBLE_DEVICES`，decode 单实例用 8 die。
- `cwd`/`log`：带 `${NODE_ID}`，避免共享盘重名。内置拓扑已带。
- `defaults.model_path`：模型目录；也可用 `MODEL_PATH` 覆盖。
- `client`：`mode: modelzoo`（默认）、`direct`、`none`；`runs` 默认 3。

### 2.2 每台机器一个入口

复制现有入口，只改两行：

```bash
mkdir -p config/nodes/<任务名>
cp config/nodes/2p2d/p0.sh config/nodes/<任务名>/p0.sh
# 编辑 p0.sh：NODE_ID="p0"；PD_TOPOLOGY="${PD_TOPOLOGY:-$CONFIG_DIR/topology-<任务名>.yaml}"
```

入口模板：

```bash
#!/bin/bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$(cd "$HERE/../.." && pwd)"
export NODE_ID="<节点名>"
export PD_TOPOLOGY="${PD_TOPOLOGY:-$CONFIG_DIR/topology-<任务名>.yaml}"
exec bash "$CONFIG_DIR/launch.sh" "$@"
```

`NODE_ID` 必须等于 topology 里的节点名；机器数量必须等于入口脚本数量。

### 2.3 换脚本

脚本放包内（`tools/` 或 `scripts/`），`cmd` 用 `$BUNDLE_DIR` 绝对路径，不要依赖 cwd。

| 变量 | 用途 |
| --- | --- |
| `BUNDLE_DIR` `RUN_DIR` `NODE_ID` `NODE_IP`/`LOCAL_IP` | 包目录、运行目录、节点、服务 IP |
| `LLM_LOCAL_IP` | decode 绑定地址（默认 = 本机 IP） |
| `MODEL_PATH` | 模型目录 |
| `INSTANCE_NAME` `KIND` `PORT` `BOOTSTRAP_PORT` `DIST_INIT_PORT` | 本实例参数 |
| `GPU_IDS` `CUDA_VISIBLE_DEVICES` | GPU 列表 |
| `NODE_RANK` `NNODES` `TS` | 自定义脚本可用 |

- **prefill**：`prefill_dp4pp4.sh <host> <port> <bootstrap_port> <hicache> <disable_radix> <kvint8> [额外 sglang 参数...]`，第 7 个参数起透传。换脚本时端口必须用 `$PORT`/`$BOOTSTRAP_PORT`。
- **decode**：`decode_ep8.sh <master_ip> <port> <dist_init_port> <nnodes> <rank> <kvint8>`，**没有透传**，加参数要改脚本本身。
- **router**：默认 `router_ori.sh --host "$GATEWAY_HOST" --port "$GATEWAY_PORT" prefill $PREFILL_ADDRS decode $DECODE_ADDRS bootstrap-ports $BOOTSTRAP_PORTS`。可用 `$GATEWAY_HOST/PORT`、`$PREFILL_ADDRS`、`$DECODE_ADDRS`、`$BOOTSTRAP_PORTS` 和逐项 `$PREFILL_0..` 等。
- **健康检查**：默认 `http://$NODE_IP:$PORT/health`；脚本没有 `/health` 时设 `health_path`、完整 `health` 或 `ready_delay`。
- **辅助进程**：`register: false`，否则会被当成 P/D 参与聚合。

### 2.4 client

- `mode: modelzoo`：跑 ModelzooTool（`client.modelzoo.config/task/out`），`runs` 导出为 `NUM_RUNS`。需要 `$BUNDLE_DIR/ModelzooTool/bin/main.py` 和 `config/run_client.sh`；从 `pd_runs/example` 起手时两者都要补，否则用 `direct`/`none`。
- `mode: direct`：`cmd` 由 launcher 重复 `runs` 次。若命令是 `config/run_client.sh`（它自己会跑 3 次），这里设 `runs: 1`，否则会放大成 9 次。
- `mode: none`：只起服务并保持运行。
- client 必须连 `GATEWAY_HOST:GATEWAY_PORT`（router），不是 prefill 端口。
- client 的 `cwd` 默认 `RUN_DIR`；压测细节文件（`sglang_*.jsonl`）随之落共享盘，不要指回部署包。

## 3. 验证

```bash
cd <包>
python3 - <<'PY'
import yaml
cfg = yaml.safe_load(open("config/topology-<任务名>.yaml"))
coord = cfg["coordinator"]
assert coord in cfg["nodes"], coord
assert cfg.get("router", {}).get("node", coord) == coord
for nid, node in cfg["nodes"].items():
    ports = set()
    for inst in node.get("instances") or []:
        kind = inst.get("kind", "other")
        if not inst.get("register", kind in ("prefill", "decode")):
            continue
        assert inst.get("port"), ("缺 port", nid, inst.get("name"))
        assert inst["port"] not in ports, ("端口重复", nid, inst["port"])
        ports.add(inst["port"])
        if kind == "prefill":
            assert inst.get("bootstrap_port"), ("prefill 缺 bootstrap_port", nid)
print("topology ok")
PY
for f in config/nodes/<任务名>/*.sh; do bash -n "$f"; done
find . -name __pycache__ -o -name '*.pyc'   # 不应有输出
```

launcher 启动时只校验本机节点；上面这段一次检查所有节点（router 位置、每机端口唯一、prefill bootstrap）。

离线 stub（单机模拟多节点，不跑真服务）：

```bash
cd <临时目录>/pd_stub
source stub_env.sh && sync_config
# 参考 run_1p2d_test.sh：把真拓扑复制成单机测试版（端口全局错开）后启动各节点入口
# 全套回归：
for t in run_default_test.sh run_stub_test.sh run_stub_test2.sh run_1p2d_test.sh run_2p2d_test.sh run_keepalive_test.sh; do
    timeout 240 bash "$t"
done
```

新增拓扑形状时，按现有测试复制一个：起各节点入口 → 等 coordinator 退出 → 断言 router 聚合的 P/D 数、client 次数、各节点 ready 内容。

## 4. 提交与使用

所有机器同时提交自己的入口（容器队列），不要手工起服务：

| 拓扑 | 机器 | 命令 |
| --- | --- | --- |
| 1P1D | master | `bash <包>/config/start.sh` |
| 1P1D | worker | `bash <包>/config/start-worker.sh` |
| 1P2D | p0/d0/d1 | `bash <包>/config/nodes/1p2d/{p0,d0,d1}.sh` |
| 2P2D | p0/p1/d0/d1 | `bash <包>/config/nodes/2p2d/{p0,p1,d0,d1}.sh` |
| 自定义 | 任意 | `NODE_ID=<节点> PD_TOPOLOGY=<yaml> bash <包>/config/launch.sh` |

常用 env：`PD_RUN_DIR`、`PD_TOPOLOGY`、`MODEL_PATH`、`GATEWAY_HOST`/`GATEWAY_PORT`、`NUM_RUNS`、`CLIENT_CMD`、`DATASET_PATH`、`SERVICE_ONLY=1`、`KEEP_ALIVE=1`、`TAG`、`LOCAL_IP`/`SOCKET_IFNAME`/`HCA_LIST`、`PD_PYTHON`。

日志和会合文件都在 `<包>/pd-run/`：`registry/<node>.ready|failed`、`*_*.log`、`logs/`、`nic_<node>_*.txt`。

## 5. 排错

- 一直等节点：确认对方入口已提交、`PD_RUN_DIR` 是同一共享路径、`ls registry/` 有对方 ready。
- decode 日志已 ready 但节点不就绪：健康检查探的 IP 与 decode 绑定的 `LLM_LOCAL_IP` 不一致；用 `health`/`LOCAL_IP` 修正。
- gateway 起了但 client 连不上：client 的 host/port 必须是 router 的 `GATEWAY_HOST:GATEWAY_PORT`。
- 起不来先看 `registry/<node>.failed` 和对应服务日志；coordinator 启动时会清上一轮会合文件，多机要同时提交。
- 退出时残留进程：用 SIGTERM 触发清理；确认入口不是被 `kill -9`。
