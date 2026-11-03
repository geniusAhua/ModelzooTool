# PD 分离部署支持 — 新建任务参考部署

本目录是 ModelzooTool 的 PD 分离支持文档与参考实现：

| 路径 | 内容 |
| --- | --- |
| [example/](example/) | 参考实现：`config/launch.py`、`launch.sh`、`pd.jsonc`、`topology-1p1d.yaml`、`wait_gateway.sh`、`http_ok.py`、`tools/detect_nic.sh` |
| [skills/pd-task/SKILL.md](../skills/pd-task/SKILL.md) | 新增/修改任务的 skill：流程、脚本契约、入口模板 |

完整的可运行部署包在共享盘（新建任务时自行命名），下文用 `<包>` 指代；`example/` 只收录下表中标 ★ 的文件，服务脚本、入口脚本和 `vendor/` 需从部署包补齐。

按 `config/topology-*.yaml` 编排，每台机器跑一个入口脚本：

- 一台机器可配**任意多个实例**（GPU、端口、命令都在拓扑里）；
- 支持**多 P 多 D**，coordinator 等齐所有节点后起 router，再跑 client（默认 3 次）；
- 换 prefill/decode 脚本、router、client 都只改 YAML；
- 自带 **1P1D**、**1P2D**、**2P2D** 三套拓扑。

服务全部由容器队列拉起，入口脚本不手工拼 IP/网卡；节点间只靠共享目录会合。

## 快速上手

1. 整个目录放到多机共享存储的**同一路径**；或给所有机器设同一个 `PD_RUN_DIR`。
2. 队列每台机器提交自己的入口（同时提交即可）：

### 1P1D（两台）

| 机器 | 角色 | 队列命令 |
| --- | --- | --- |
| master | prefill DP4PP4 + router + client | `bash <包>/config/start.sh` |
| worker | 2× decode DP8EP8 | `bash <包>/config/start-worker.sh` |

按 decode 实例数看是 1 个 prefill + 2 个 decode（常说的“1P2D”）；工具里按**机器数**命名为 **1P1D**，即 1 台 P 机 + 1 台 D 机。

### 1P2D（三台）

| 机器 | 角色 | 队列命令 |
| --- | --- | --- |
| p0 | prefill + coordinator + router + client | `bash <包>/config/nodes/1p2d/p0.sh` |
| d0 | 2× decode | `bash <包>/config/nodes/1p2d/d0.sh` |
| d1 | 2× decode | `bash <包>/config/nodes/1p2d/d1.sh` |

这里是按**机器数**命名：1 台 P 机 + 2 台 D 机，共 4 个 decode 实例。每台 D 机默认 2 个 decode；只跑 1 个就删掉 `decode1`。

### 2P2D（四台）

| 机器 | 角色 | 队列命令 |
| --- | --- | --- |
| p0 | prefill + coordinator + router + client | `bash <包>/config/nodes/2p2d/p0.sh` |
| p1 | prefill | `bash <包>/config/nodes/2p2d/p1.sh` |
| d0 | 2× decode | `bash <包>/config/nodes/2p2d/d0.sh` |
| d1 | 2× decode | `bash <包>/config/nodes/2p2d/d1.sh` |

默认 client 在 `<包>/config/run_client.sh`：连 `GATEWAY_HOST:GATEWAY_PORT`（与 router 相同，默认本机 IP + `8001`），数据集默认 `/path/to/dataset.jsonl`（`DATASET_PATH` 可覆盖），**连续跑 3 次**（`NUM_RUNS` 或拓扑 `client.runs` 可改）。
只起服务不跑 client 用 `SERVICE_ONLY=1` 或 `client.mode: none`（都会保持运行）；client 跑完保留集群用 `KEEP_ALIVE=1`。收到 SIGTERM 都会清理本机子进程。
模型默认 `/path/to/model`（见拓扑 `defaults.model_path`，也可用 `MODEL_PATH` 覆盖）。

## 目录

部署包结构如下，★ = `example/` 已收录：

| 路径 | 用途 | 示例 |
| --- | --- | --- |
| `<包>/config/launch.py` | 通用编排器：实例、健康检查、registry、router、client | ★ |
| `<包>/config/launch.sh` | 入口 bootstrap：PATH、vendor、依赖检查、网卡探测 | ★ |
| `<包>/config/topology-1p1d.yaml` | 1P1D 拓扑模板 | ★ |
| `<包>/config/topology-1p2d.yaml` | 1P2D 拓扑 | |
| `<包>/config/topology-2p2d.yaml` | 2P2D 拓扑 | |
| `<包>/config/start.sh` / `config/start-worker.sh` | 1P1D 的 p0 / d0 入口（只设节点名 + 拓扑） | |
| `<包>/config/nodes/1p2d/*.sh` | 1P2D 三台机器的入口 | |
| `<包>/config/nodes/2p2d/*.sh` | 2P2D 四台机器的入口 | |
| `<包>/config/pd.jsonc` | ModelzooTool 配置：gateway 守卫 + client | ★ |
| `<包>/config/wait_gateway.sh` | server.cmd：等 `/v1/models`，打印 `GATEWAY-READY` 后常驻 | ★ |
| `<包>/config/http_ok.py` | 无 curl 的服务探活 | ★ |
| `<包>/config/run_client.sh` | client.cmd：默认 `sglang.bench_serving` 连跑 3 次 | |
| `<包>/tools/prefill_dp4pp4.sh` | prefill，16 die | |
| `<包>/tools/decode_ep8.sh` | decode，单机多实例 | |
| `<包>/tools/router_ori.sh` | router/minilb，支持任意数量 P/D | |
| `<包>/tools/detect_nic.sh` | 自动探测服务网卡、本机 IP、IB HCA | ★ |
| `<包>/ModelzooTool/` `vendor/` | 新版工具（`readyTag` / e2e / `--task`）与内置 Python 依赖 | |
| `<包>/pd-run/` | 运行目录（自动创建）：`registry/`、日志、ModelzooTool 结果 | |

`example/` 是模板，不能直接运行：补上 `tools/` 里的服务脚本、每机入口和 `vendor/` 依赖后再用，详见 [example/README.md](example/README.md)。
示例文件同步自部署包，改 `launch.py`/`launch.sh`/配置时两边一起改。

## 拓扑

一个节点就是一台机器；`instances` 是这台机器上的服务。最小例子：

```yaml
coordinator: p0

nodes:
  p0:
    ip: auto
    instances:
      - name: prefill
        kind: prefill
        gpus: "0,1,2,3,4,7,6,5,8,9,10,11,12,15,14,13"
        port: 9292
        bootstrap_port: 8988
        cmd: 'bash "$BUNDLE_DIR/tools/prefill_dp4pp4.sh" 0.0.0.0 "$PORT" "$BOOTSTRAP_PORT" true false true'
  d0:
    ip: auto
    instances:
      - name: decode0
        kind: decode
        gpus: "0,1,2,3,4,7,6,5"
        port: 9392
        dist_init_port: 5000
        cmd: 'bash "$BUNDLE_DIR/tools/decode_ep8.sh" 0.0.0.0 "$PORT" "$DIST_INIT_PORT" 1 0 true'

router:
  node: p0            # 必须等于 coordinator
  host: auto
  port: 8001

client:
  mode: modelzoo
```

常用字段：

| 字段 | 说明 |
| --- | --- |
| `nodes.<id>.ip` | `auto` = 用探测到的 `LOCAL_IP`；也可写死服务网段地址 |
| `instances[].name` | 节点内唯一；registry 和日志用它 |
| `kind` | `prefill` / `decode`；router 按这个聚合 |
| `gpus` | 导出为 `CUDA_VISIBLE_DEVICES` |
| `port` | 服务端口；`register` 实例必填 |
| `bootstrap_port` | prefill 必填，参与 router 的 `bootstrap-ports` |
| `dist_init_port` | 只导出给实例，decode 用 |
| `cmd` | shell 命令；可用变量见下表 |
| `health` / `health_path` | 默认 `http://<节点IP>:<port>/health` |
| `ready_delay` | 无 health 时，进程存活多少秒算就绪 |
| `register` | 默认 prefill/decode 为 true；辅助进程设 false |
| `env` / `cwd` / `log` | 实例环境、工作目录、日志文件；相对 `cwd` 按包目录解析，相对 `log` 按 `RUN_DIR` 解析 |
| `start_timeout` | 单实例就绪超时，默认 1800s |
| `rank` / `nnodes` | 导出为 `NODE_RANK` / `NNODES`，给自定义多机脚本用 |

**每机多实例**：在 `instances` 里加条目，保证同机 `name`、端口不重复、GPU 不冲突。launcher 会检查同机端口冲突。

**多 P 多 D**：加节点、加实例即可。router 按 YAML 顺序聚合所有 `register` 的 prefill/decode，`bootstrap-ports` 与 prefill 顺序一一对应。不同机器的服务端口可以相同，同一台机器内必须唯一。

> **限制**：`prefill_dp4pp4.sh` 是单机 16 die 服务，2P 就是两个**独立** prefill，router 聚合，不是一个跨机 prefill。要让一个服务跨机，需自带启动脚本；launcher 只提供 `NODE_RANK`/`NNODES`，不做多机启动栅栏。

**共享盘重名**：内置拓扑的 `log`/`cwd` 都已按 `${NODE_ID}` 隔离（prefill 会往 cwd 写 `./env`）。自定义拓扑照做，避免多机互相覆盖。

## 换脚本 / router / client

**换 prefill/decode**：改 `instances[].cmd`。launcher 导出的变量：

| 变量 | 含义 |
| --- | --- |
| `BUNDLE_DIR` `RUN_DIR` `NODE_ID` `NODE_IP`/`LOCAL_IP` | 包目录、运行目录、节点、服务 IP |
| `LLM_LOCAL_IP` | decode 的绑定地址（本机服务 IP） |
| `MODEL_PATH` | 模型目录 |
| `INSTANCE_NAME` `KIND` `PORT` `BOOTSTRAP_PORT` `DIST_INIT_PORT` | 本实例参数 |
| `GPU_IDS` `CUDA_VISIBLE_DEVICES` | GPU 列表 |
| `NODE_RANK` `NNODES` `TS` | 自定义脚本可用 |

**换 router**：改 `router.cmd`，默认是：

```text
router_ori.sh --host $GATEWAY_HOST --port $GATEWAY_PORT \
  prefill $PREFILL_ADDRS decode $DECODE_ADDRS bootstrap-ports $BOOTSTRAP_PORTS
```

可用变量：`GATEWAY_HOST` `GATEWAY_PORT` `PREFILL_ADDRS` `DECODE_ADDRS` `BOOTSTRAP_PORTS`（空格分隔），以及逐项 `PREFILL_0..` `DECODE_0..` `BOOTSTRAP_PORT_0..`。
router 只有 coordinator 会起，所以 `router.node` 必须等于 `coordinator`。

**换 client**：

- `mode: modelzoo`（默认）：跑 ModelzooTool，配置 `client.modelzoo.config/task/out`；`runs` 导出为 `NUM_RUNS`。
- `mode: direct`：任意命令，重复 `runs` 次（`NUM_RUNS` 可覆盖）：

```yaml
client:
  mode: direct
  cmd: 'bash "$BUNDLE_DIR/config/run_client.sh"'
  runs: 1          # run_client.sh 自己会按 NUM_RUNS 跑 3 次，这里别重复放大
  cwd: "${RUN_DIR}"
```

- `mode: none`：只起服务并保持运行。
- client 的 `cwd` 默认 `RUN_DIR`：压测细节文件（`sglang_*.jsonl`）落共享盘，不写进部署包。

client 环境里有 `GATEWAY_HOST` `GATEWAY_PORT` `NUM_RUNS` `TAG`，以及继承的 `CLIENT_CMD` / `DATASET_PATH` 等。

## 时序与会合

每台机器：

1. 按拓扑启动本机实例；
2. 等 `health`（或 `ready_delay`），写 `$RUN_DIR/registry/<node>.ready`，之后每 10s 心跳重写；
3. 实例中途退出 → 写 `registry/<node>.failed` 并退出；
4. 非 coordinator 节点常驻；coordinator 继续下一步。

coordinator（p0）：

1. 启动时清掉上一轮 `registry/*.ready`，把旧 `*.failed` 和旧版 `decode.ready/decode.failed` 打印后删掉；
2. 等所有含 `register` 实例的节点都出现 ready（同时监控对方 failed）；
3. 按 YAML 顺序聚合 prefill/decode 地址，起 router；
4. 等 `http://<gateway>/v1/models`；
5. 跑 client（默认 ModelzooTool，3 次）。

**地址怎么传**：decode 用 `LLM_LOCAL_IP` 绑定 `--host`（只监听该地址，不是 `0.0.0.0`），所以健康检查也探这个 IP；默认优先选**默认路由网卡**（HCA 网段可能跨机不通）。router 的 prefill 地址也用节点 IP，worker 上的 decode 才能回连 prefill 的 bootstrap。

## 共享盘上的文件

| 路径 | 内容 |
| --- | --- |
| `$RUN_DIR/registry/<node>.ready` | 本节点注册实例的 JSON（endpoint / bootstrap_port） |
| `$RUN_DIR/registry/<node>.failed` | 失败原因；coordinator 看到立即中止 |
| `$RUN_DIR/prefill_*.log` `decode*_*.log` `router_*.log` | 1P1D 服务 / router 日志 |
| `$RUN_DIR/p0_prefill_*.log` `d0_decode*_*.log` `d1_decode*_*.log` … | 1P2D / 2P2D 日志（带节点前缀） |
| `$RUN_DIR/nic_<node>_*.txt` | 网卡探测明细 |
| `$RUN_DIR/logs/` | ModelzooTool 结果（按 config/task/时间戳+tag 分层） |
| `$RUN_DIR/sglang_*.jsonl` | 压测细节（client cwd 默认在 `RUN_DIR`） |

`PD_RUN_DIR` 所有机器必须一致；默认是**部署包内、与 `ModelzooTool/` 同级的 `pd-run/`**。
包在共享盘上，日志在包内 `pd-run/`，随包放在共享盘上。

## 常用开关

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `MODEL_PATH` | 见拓扑 | 模型目录 |
| `PD_RUN_DIR` / `RUN_DIR` | `<包>/pd-run` | 多机共享运行目录 |
| `PD_TOPOLOGY` | 入口脚本自带 | 换拓扑文件（所有入口脚本都可被覆盖） |
| `NODE_ID` | 入口脚本自带 | 自定义节点时指定 |
| `GATEWAY_HOST` / `GATEWAY_PORT` | 本机 IP / `8001` | router 绑定、client 连接；`0.0.0.0` 表示监听所有网卡，client 自动改 `127.0.0.1` |
| `NUM_RUNS` / `client.runs` | `3` | client 次数（modelzoo/direct 都生效） |
| `CLIENT_CMD` | 见 `run_client.sh` | 覆盖默认压测命令（仍重复 `NUM_RUNS` 次） |
| `SERVICE_ONLY` | `0` | `1` = 只起服务、不跑 client，保持运行 |
| `KEEP_ALIVE` | `0` | `1` = client 跑完保持运行 |
| `TAG` | 时间戳 | ModelzooTool 结果目录后缀 |
| `DATASET_PATH` | `/path/to/dataset.jsonl` | 压测数据集 |
| `SOCKET_IFNAME` / `HCA_LIST` / `LOCAL_IP` | 自动探测 | 覆盖网卡/IP |
| `PD_PYTHON` | `python3` | 指定 launcher 用的 Python |

## 新增任务

从 `<包>/config/topology-*.yaml` 或 [example/config/topology-1p1d.yaml](example/config/topology-1p1d.yaml) 起手；用 `example/` 时先按 [example/README.md](example/README.md) 补齐服务脚本、入口、client 和依赖。

1. 复制最接近的拓扑，改 `nodes`/`instances`/`router`/`client`；**并发任务用不同的 `run.dir`**（例如 `${BUNDLE_DIR}/pd-run/<任务名>`），避免 registry 串台。
2. 每台机器建一个入口脚本：只设 `NODE_ID` 和 `PD_TOPOLOGY`，模板见 [skills/pd-task/SKILL.md](../skills/pd-task/SKILL.md) §2.2（`example/` 不带入口脚本）。
3. 新 prefill/decode/router/client 脚本放包内（`tools/` 或自建目录），`cmd` 里用 `$BUNDLE_DIR`；端口用 `$PORT`/`$BOOTSTRAP_PORT`/`$DIST_INIT_PORT`，不要写死。
4. 校验：YAML 能解析、`bash -n` 入口脚本，跑 skill §3 的全节点检查；真跑前先用 stub 模拟（不启动真实服务）走一遍。

## 验证与排错

```bash
# 网卡探测（任一机器容器里）
source <包>/tools/detect_nic.sh && pd_ib_hca -d

# 服务探活（镜像没有 curl，用包内脚本）
python3 <包>/config/http_ok.py http://<node_ip>:9292/health
python3 <包>/config/http_ok.py http://<p0_ip>:8001/v1/models

# 会合/失败
ls  <包>/pd-run/registry/
cat <包>/pd-run/registry/d0.failed
tail -n 100 <包>/pd-run/prefill_*.log <包>/pd-run/decode*_*.log
```

- 日志前缀是 `[launch]`。起不来先看 `registry/<node>.failed` 和对应服务日志。
- 一直“等待节点就绪”：确认对方入口已提交、`PD_RUN_DIR` 是同一个共享路径、`ls registry` 能看到对方 ready。
- 探测为空或选错网卡：日志里有 `source=override/route/hca/fallback` 和 `candidates:`；用 `LOCAL_IP` / `SOCKET_IFNAME` 覆盖。
- decode 日志已 ready 但节点未就绪：看失败信息里的探测 URL；decode 只监听 `LOCAL_IP`，该地址跨机不通时用 `LOCAL_IP` 覆盖成服务网段。
- gateway 起了但 client 连不上：client 必须走 `GATEWAY_HOST:GATEWAY_PORT`（router 同一地址），不是 prefill 的 9292。
- 同机跑 client 会与 prefill 抢 CPU；压测数据偏低可把 client 挪到别的机器（改 `client` / 入口）。
- coordinator 启动时会清上一轮会合文件；多机请同时提交，不要把上一轮的失败标记当成本轮原因。

## 注意事项

1. **必须共享存储**：`config/`、`tools/`、`ModelzooTool/` 所有机器都要能访问；`PD_RUN_DIR` 必须指向同一个共享路径。
2. **入口脚本数量 = 机器数量**：1P1D 两个、1P2D 三个、2P2D 四个；加机器就复制入口脚本并改 `NODE_ID`（拓扑里也要加节点）。
3. **镜像依赖**：只需 `python3` + `mx-smi` + `sglang`；`json5`/`pyyaml` 已随包放 `vendor/`，由 `launch.sh` 加入 `PYTHONPATH`。vendor 失效时 `launch.sh` 会用内网源补装：

   ```bash
   pip config set global.index-url https://repo.metax-tech.com/r/pypi/simple
   pip config set install.trusted-host repo.metax-tech.com
   pip install json5 pyyaml
   ```

   探活用 `config/http_ok.py`，**不需要 curl**；网卡探测纯 Python，**不需要 ip/iproute2**。
4. **模型/数据集**：权重、sglang 镜像不在包内；数据集已随包（约 187M）。
5. **端口**：同一台机器内必须唯一（launcher 会检查，含 router 端口）；不同机器可重复。
6. **并发任务**：多个任务同时跑时各用独立的 `run.dir`，否则 `registry/` 会互相覆盖。
7. **router 位置**：当前 launcher 只允许 `router.node == coordinator`；要独立 router 机器，需单独起 router 并把 `client` 指过去。
8. **prefill 多机**：见上文限制；2P2D 是多个独立 prefill，不是跨机单服务。
