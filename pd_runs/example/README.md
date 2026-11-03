# PD 分离参考示例

ModelzooTool 接 PD 分离服务的最小参考：编排脚本 + 配置模板。
服务脚本（prefill/decode/router）和运行依赖不在示例里，补齐后才能跑。

## 目录

| 路径 | 作用 |
| --- | --- |
| `config/launch.py` | 通用编排器：实例、健康检查、registry 会合、router、client |
| `config/launch.sh` | 入口 bootstrap：PATH、vendor、依赖检查、网卡探测 |
| `config/topology-1p1d.yaml` | 1 台 P 机 + 1 台 D 机（2 个 decode）的编排模板 |
| `config/pd.jsonc` | ModelzooTool 配置：`readyTag` 守卫 + `pd_e2e` + client |
| `config/wait_gateway.sh` | `server.cmd`：等 `/v1/models`，打印 `GATEWAY-READY` 后常驻 |
| `config/http_ok.py` | 无 curl 探活 |
| `tools/detect_nic.sh` | 探测服务网卡、`LOCAL_IP`、IB HCA |

## 使用前补齐

- **服务脚本**：topology 里的 `tools/prefill.sh`、`tools/decode.sh` 是占位名，换成实际脚本；端口用 `$PORT`、`$BOOTSTRAP_PORT`、`$DIST_INIT_PORT`，不要写死。
- **router**：示例没写 `router.cmd`，默认找 `tools/router_ori.sh`；补这个脚本，或在 topology 里写 `router.cmd`。
- **client**：`pd.jsonc` 引用 `config/run_client.sh`（示例未带），modelzoo 模式还要求 `ModelzooTool/` 与 `config/` 同级；不用 ModelzooTool 时把 `client.mode` 改成 `direct` 或 `none`。
- **数据集**：`run_client.sh` 默认读 `/path/to/dataset.jsonl`，也可用 `DATASET_PATH` 覆盖。
- **入口脚本**：每台机器一个，只设 `NODE_ID` 和 `PD_TOPOLOGY`，模板见 [../../skills/pd-task/SKILL.md](../../skills/pd-task/SKILL.md)。
- **依赖**：`json5`/`pyyaml`。`launch.sh` 会把 `$BUNDLE_DIR/vendor` 加进 `PYTHONPATH`；缺失时按内网源安装。
- **环境参数**：模型路径、GPU、端口按本机改；`launch.sh` 的 PATH 和内网 pip 源是 MetaX 镜像默认值，换环境时改这段。

补齐后单机入口：

```bash
NODE_ID=p0 bash config/launch.sh
```

完整部署说明见 [../README.md](../README.md)。示例文件同步自部署包，改动请两边一起改。

注意：`pd.jsonc` 里用 `$VAR`，不要写 `${VAR}`——花括号会被 ModelzooTool 当占位符渲染。
