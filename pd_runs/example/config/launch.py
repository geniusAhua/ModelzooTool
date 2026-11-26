#!/usr/bin/env python3
"""PD 分离通用启动器。

读一份 topology YAML，只启动本节点（--node）的实例；所有节点把就绪信息写到
共享盘的 $RUN_DIR/registry/<node>.ready，coordinator 节点等齐所有节点后聚合
prefill/decode 地址，启动 router，再跑 client。

设计约束：
  - 每台机器执行一个入口脚本，脚本数量 = 机器数量；
  - 一台机器上可以配置任意多个实例（GPU、端口、命令都在 YAML 里）；
  - prefill/decode 脚本、router、client 都是 YAML 里的命令串，可替换；
  - 会合只依赖共享目录，不需要队列注入 IP。
"""

import argparse
import glob
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

try:
    import yaml
except ImportError:
    sys.stderr.write("缺少 pyyaml：本包 vendor/ 应已提供；或 pip install pyyaml\n")
    sys.exit(2)

DEFAULT_MODEL_PATH = "/path/to/model"
DEFAULT_ROUTER_CMD = (
    'bash "$BUNDLE_DIR/tools/router_ori.sh" --host "$GATEWAY_HOST" '
    '--port "$GATEWAY_PORT" prefill $PREFILL_ADDRS decode $DECODE_ADDRS '
    'bootstrap-ports $BOOTSTRAP_PORTS'
)

VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def log(*args):
    print("[launch]", *args, flush=True)


def expand(value, ctx):
    """展开 ${VAR}/$VAR：优先用 ctx，其次进程环境；命令串不要走这里。"""
    if not isinstance(value, str):
        return value

    def repl(match):
        key = match.group(1) or match.group(2)
        if key in ctx:
            return str(ctx[key])
        if key in os.environ:
            return os.environ[key]
        return match.group(0)

    return os.path.expanduser(VAR_RE.sub(repl, value))


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("", "0", "false", "no", "off", "none")


def resolve_path(value, base, ctx):
    """展开变量并转绝对路径；相对路径按部署包目录解析。"""
    path = expand(str(value), ctx)
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    return os.path.abspath(path)


def http_ok(url, timeout=3.0):
    try:
        with HTTP_OPENER.open(url, timeout=timeout) as resp:
            code = getattr(resp, "status", resp.getcode())
            return 200 <= code < 300
    except Exception:
        return False


def atomic_write(path, text):
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def sanitize(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def terminate_process(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    for sig, timeout in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            continue


class Launcher:
    def __init__(self, argv):
        parser = argparse.ArgumentParser(description="PD 分离通用启动器")
        parser.add_argument("--node", default=os.environ.get("NODE_ID"),
                            help="本机节点名，对应 topology 的 nodes.<id>")
        parser.add_argument("--config", default=os.environ.get("PD_TOPOLOGY"),
                            help="topology YAML 路径")
        args = parser.parse_args(argv)

        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.bundle = os.environ.get("BUNDLE_DIR") or os.path.dirname(self.script_dir)
        self.cfg_path = os.path.abspath(
            args.config or os.path.join(self.script_dir, "topology-1p1d.yaml")
        )
        self.cfg = self.load_config(self.cfg_path)

        if not args.node:
            nodes = list(self.cfg["nodes"])
            if len(nodes) != 1:
                self.die("必须指定 --node 或 NODE_ID；可选节点: %s" % ", ".join(nodes))
            args.node = nodes[0]
        self.node_id = str(args.node)
        self.nodes = {str(k): (v or {}) for k, v in self.cfg["nodes"].items()}
        if self.node_id not in self.nodes:
            self.die("未知节点 %r；topology 里的节点: %s"
                     % (self.node_id, ", ".join(self.nodes)))
        self.node_cfg = self.nodes[self.node_id]

        defaults = self.cfg.get("defaults") or {}
        run_cfg = self.cfg.get("run") or {}
        self.defaults = defaults
        self.heartbeat = float(run_cfg.get("heartbeat", 10))
        self.health_interval = float(run_cfg.get("health_interval", 5))
        self.start_timeout = float(
            defaults.get("start_timeout", run_cfg.get("start_timeout", 1800))
        )
        self.wait_timeout = float(run_cfg.get("wait_timeout", 1800))
        self.router_timeout = float(run_cfg.get("router_timeout", 600))

        # coordinator 负责起 router、跑 client；router 必须与它在同一台机器
        coord = self.cfg.get("coordinator")
        if coord is None:
            found = [nid for nid, ncfg in self.nodes.items() if as_bool(ncfg.get("coordinator"))]
            if len(found) != 1:
                self.die("topology 里必须恰好有一个 coordinator（顶层字段或节点标记）")
            coord = found[0]
        self.coordinator = str(coord)
        if self.coordinator not in self.nodes:
            self.die("coordinator %r 不在 nodes 里" % self.coordinator)
        self.is_coordinator = self.node_id == self.coordinator

        self.router_cfg = self.cfg.get("router") or {}
        router_node = str(self.router_cfg.get("node", self.coordinator))
        if router_node != self.coordinator:
            self.die("router.node=%s 必须等于 coordinator=%s：router 只能由本机启动"
                     % (router_node, self.coordinator))

        self.client_cfg = self.cfg.get("client") or {}

        # 共享运行目录：必须是所有节点都能看到的同一个路径
        run_dir = (
            os.environ.get("PD_RUN_DIR")
            or os.environ.get("RUN_DIR")
            or run_cfg.get("dir")
            or os.path.join(self.bundle, "pd-run")
        )
        self.run_dir = resolve_path(
            run_dir, self.bundle, {"BUNDLE_DIR": self.bundle})
        self.registry_dir = os.path.join(self.run_dir, "registry")
        os.makedirs(self.registry_dir, exist_ok=True)

        self.node_ip = self.resolve_ip()
        self.ts = time.strftime("%m%d_%H%M%S")

        model_path = (
            os.environ.get("MODEL_PATH")
            or defaults.get("model_path")
            or DEFAULT_MODEL_PATH
        )
        model_path = resolve_path(
            model_path, self.bundle,
            {"BUNDLE_DIR": self.bundle, "RUN_DIR": self.run_dir})

        self.ctx = {
            "BUNDLE_DIR": self.bundle,
            "CONFIG_DIR": self.script_dir,
            "RUN_DIR": self.run_dir,
            "PD_RUN_DIR": self.run_dir,
            "NODE_ID": self.node_id,
            "NODE_IP": self.node_ip,
            "LOCAL_IP": self.node_ip,
            "MODEL_PATH": model_path,
            "TS": self.ts,
        }
        self.base_env = self.build_base_env()
        self.node_env = dict(self.base_env)
        for k, v in (defaults.get("env") or {}).items():
            self.node_env[str(k)] = str(expand(v, self.ctx))
        for k, v in (self.node_cfg.get("env") or {}).items():
            self.node_env[str(k)] = str(expand(v, self.ctx))

        self.stop = threading.Event()
        self.failure_event = threading.Event()
        self.fail_lock = threading.Lock()
        self.failure_reason = ""
        self.ready_written = False
        self.router_proc = None
        self.router_log = None
        self.router_logf = None
        self.heartbeat_thread = None
        self.gateway_host = ""
        self.gateway_port = 0
        self.gateway_probe = ""
        self.local_logs = []

        self.instances = self.build_local_instances()
        self.expected, self.expected_by_node = self.build_expected()
        self.validate()

    # ------------------------------------------------------------------ config

    def die(self, msg, rc=2):
        print("[launch] 配置错误: %s" % msg, file=sys.stderr, flush=True)
        sys.exit(rc)

    def load_config(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
        except OSError as exc:
            self.die("读不到 topology %s: %s" % (path, exc))
        except yaml.YAMLError as exc:
            self.die("topology YAML 解析失败 %s: %s" % (path, exc))
        if not isinstance(cfg, dict):
            self.die("topology 顶层必须是 YAML 映射: %s" % path)
        if not isinstance(cfg.get("nodes"), dict) or not cfg["nodes"]:
            self.die("topology 缺少 nodes")
        return cfg

    def resolve_ip(self):
        cfg = self.node_cfg.get("ip", "auto")
        if cfg is None or str(cfg).strip().lower() in ("", "auto", "detect"):
            ip = os.environ.get("LOCAL_IP", "").strip()
            if not ip:
                try:
                    for info in socket.getaddrinfo(socket.gethostname(), None,
                                                   socket.AF_INET):
                        addr = info[4][0]
                        if not addr.startswith("127."):
                            ip = addr
                            break
                except OSError:
                    pass
            if not ip:
                self.die("未探测到本机 IP；请设置 LOCAL_IP，或在 "
                         "nodes.%s.ip 写死服务网段地址" % self.node_id)
        else:
            ip = str(cfg).strip()
            if not ip:
                self.die("nodes.%s.ip 为空" % self.node_id)
        if ip in ("0.0.0.0", "::", "[::]"):
            self.die("nodes.%s.ip 不能是监听地址 %s；请写服务网段地址或 auto"
                     % (self.node_id, ip))
        if ip.startswith("127.") and len(self.nodes) > 1:
            log("WARN 节点 %s 的 IP 是回环地址 %s，其它机器访问不到"
                % (self.node_id, ip))
        return ip

    def build_base_env(self):
        env = os.environ.copy()
        env.update({k: str(v) for k, v in self.ctx.items()})
        env["LLM_LOCAL_IP"] = self.node_ip
        env["TOOL_DIR"] = os.path.join(self.bundle, "ModelzooTool")
        env["CONFIG_DIR"] = self.script_dir
        vendor = os.path.join(self.bundle, "vendor")
        old = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = vendor + (":" + old if old else "")
        return env

    def build_local_instances(self):
        raw_list = self.node_cfg.get("instances") or []
        if not isinstance(raw_list, list):
            self.die("nodes.%s.instances 必须是列表" % self.node_id)
        instances = []
        names = set()
        used_ports = {}
        for idx, raw in enumerate(raw_list):
            if not isinstance(raw, dict):
                self.die("nodes.%s.instances[%d] 必须是映射" % (self.node_id, idx))
            name = str(raw.get("name") or "instance%d" % idx)
            if name in names:
                self.die("nodes.%s 实例名重复: %s" % (self.node_id, name))
            names.add(name)
            kind = str(raw.get("kind") or "other")
            cmd = raw.get("cmd")
            if not cmd:
                self.die("实例 %s/%s 缺少 cmd" % (self.node_id, name))

            def port_of(key):
                val = raw.get(key)
                if val is None or val == "":
                    return None
                try:
                    return int(val)
                except (TypeError, ValueError):
                    self.die("实例 %s/%s 的 %s 不是整数: %r"
                             % (self.node_id, name, key, val))

            port = port_of("port")
            bootstrap = port_of("bootstrap_port")
            dist_port = port_of("dist_init_port")
            gpus = raw.get("gpus")
            if isinstance(gpus, list):
                gpus = ",".join(str(x) for x in gpus)
            gpus = str(gpus) if gpus is not None else ""

            register = as_bool(raw.get("register"), kind in ("prefill", "decode"))
            if register and port is None:
                self.die("实例 %s/%s register=true 但没有 port" % (self.node_id, name))
            if register and kind not in ("prefill", "decode"):
                self.die("实例 %s/%s register=true 但 kind=%s（只支持 prefill/decode）"
                         % (self.node_id, name, kind))

            ictx = dict(self.ctx)
            ictx.update({
                "INSTANCE_NAME": name,
                "KIND": kind,
                "PORT": "" if port is None else str(port),
                "BOOTSTRAP_PORT": "" if bootstrap is None else str(bootstrap),
                "DIST_INIT_PORT": "" if dist_port is None else str(dist_port),
                "GPU_IDS": gpus,
            })

            health_raw = raw.get("health", None)
            health = None
            health_path = expand(str(raw.get("health_path") or "/health"), ictx)
            if not health_path.startswith("/"):
                health_path = "/" + health_path
            if isinstance(health_raw, bool):
                if health_raw and port is not None:
                    health = "http://%s:%d%s" % (self.node_ip, port, health_path)
            elif health_raw is not None:
                text = str(health_raw).strip()
                if text.lower() not in ("", "none", "false", "no", "off"):
                    health = expand(text, ictx)
            elif port is not None:
                health = "http://%s:%d%s" % (self.node_ip, port, health_path)

            ready_delay = raw.get("ready_delay")
            if register and not health and ready_delay is None:
                self.die("实例 %s/%s register=true 但没有 health/port；"
                         "请设置 health 或 ready_delay" % (self.node_id, name))
            ready_delay = float(ready_delay or 0)

            log_name = str(raw.get("log") or "%s_%s.log" % (sanitize(name), self.ts))
            log_name = expand(log_name, ictx)
            if not os.path.isabs(log_name):
                log_name = os.path.join(self.run_dir, log_name)
            log_path = os.path.abspath(log_name)
            try:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
            except OSError as exc:
                self.die("实例 %s/%s 的日志目录无法创建 %s: %s"
                         % (self.node_id, name, os.path.dirname(log_path), exc))

            cwd = resolve_path(
                raw.get("cwd") or os.path.join(self.bundle, "tools"),
                self.bundle, ictx)
            try:
                os.makedirs(cwd, exist_ok=True)
            except OSError as exc:
                self.die("实例 %s/%s 的 cwd 无法创建 %s: %s"
                         % (self.node_id, name, cwd, exc))
            ienv = dict(self.node_env)
            for k, v in (raw.get("env") or {}).items():
                ienv[str(k)] = str(expand(v, ictx))
            ienv.update({k: str(v) for k, v in ictx.items()
                         if k in ("INSTANCE_NAME", "KIND", "PORT", "BOOTSTRAP_PORT",
                                  "DIST_INIT_PORT", "GPU_IDS")})
            if gpus:
                ienv["CUDA_VISIBLE_DEVICES"] = gpus
            rank = int(raw.get("rank", 0))
            nnodes = int(raw.get("nnodes", 1))
            ienv["NODE_RANK"] = str(rank)
            ienv["NNODES"] = str(nnodes)

            timeout = float(raw.get("start_timeout", self.start_timeout))
            for p, label in ((port, "port"), (bootstrap, "bootstrap_port"),
                             (dist_port, "dist_init_port")):
                if p is None:
                    continue
                if not 0 < p < 65536:
                    self.die("实例 %s/%s 的 %s 不是合法端口: %d"
                             % (self.node_id, name, label, p))
                if p in used_ports:
                    self.die("节点 %s 端口冲突: %d（%s 与 %s）"
                             % (self.node_id, p, used_ports[p], name))
                used_ports[p] = "%s.%s" % (name, label)

            instances.append({
                "name": name,
                "kind": kind,
                "cmd": str(cmd),
                "port": port,
                "bootstrap": bootstrap,
                "dist_init_port": dist_port,
                "gpus": gpus,
                "register": register,
                "health": health,
                "ready_delay": ready_delay,
                "cwd": os.path.abspath(cwd),
                "env": ienv,
                "log": log_path,
                "timeout": timeout,
                "proc": None,
                "logf": None,
            })
        self.local_ports = used_ports
        return instances

    def build_expected(self):
        expected = []
        by_node = {}
        prefill_count = 0
        decode_count = 0
        for nid, ncfg in self.nodes.items():
            regs = []
            seen = set()
            raw_list = ncfg.get("instances") or []
            if not isinstance(raw_list, list):
                self.die("nodes.%s.instances 必须是列表" % nid)
            for idx, raw in enumerate(raw_list):
                if not isinstance(raw, dict):
                    self.die("nodes.%s.instances[%d] 必须是映射" % (nid, idx))
                kind = str(raw.get("kind") or "other")
                register = as_bool(raw.get("register"), kind in ("prefill", "decode"))
                if not register:
                    continue
                name = str(raw.get("name") or "instance%d" % idx)
                if name in seen:
                    self.die("节点 %s 注册实例名重复: %s" % (nid, name))
                seen.add(name)
                if kind not in ("prefill", "decode"):
                    self.die("节点 %s 实例 %s register=true 但 kind=%s"
                             % (nid, name, kind))
                port = raw.get("port")
                if port is None:
                    self.die("节点 %s 实例 %s register=true 但没有 port" % (nid, name))
                try:
                    port = int(port)
                except (TypeError, ValueError):
                    self.die("节点 %s 实例 %s port 不是整数" % (nid, name))
                if not 0 < port < 65536:
                    self.die("节点 %s 实例 %s port 不是合法端口: %d"
                             % (nid, name, port))
                bootstrap = raw.get("bootstrap_port")
                if kind == "prefill" and bootstrap is None:
                    self.die("节点 %s 的 prefill %s 缺少 bootstrap_port" % (nid, name))
                if bootstrap is not None:
                    try:
                        bootstrap = int(bootstrap)
                    except (TypeError, ValueError):
                        self.die("节点 %s 实例 %s bootstrap_port 不是整数: %r"
                                 % (nid, name, bootstrap))
                    if not 0 < bootstrap < 65536:
                        self.die("节点 %s 实例 %s bootstrap_port 不是合法端口: %d"
                                 % (nid, name, bootstrap))
                if kind == "prefill":
                    prefill_count += 1
                else:
                    decode_count += 1
                regs.append({"name": name, "kind": kind, "port": port,
                             "bootstrap": bootstrap})
            if regs:
                expected.append(nid)
                by_node[nid] = regs
        if not expected:
            self.die("topology 里没有任何 register 实例")
        if prefill_count == 0 or decode_count == 0:
            self.die("至少要有 1 个 prefill 和 1 个 decode 注册实例"
                     "（当前 P=%d D=%d）" % (prefill_count, decode_count))
        return expected, by_node

    def validate(self):
        if not self.instances and not self.is_coordinator:
            self.die("非 coordinator 节点 %s 必须至少配置一个实例" % self.node_id)
        local_regs = {i["name"] for i in self.instances if i["register"]}
        expected_local = {i["name"] for i in self.expected_by_node.get(self.node_id, [])}
        if local_regs != expected_local:
            self.die("节点 %s 的注册实例配置不一致: local=%s expected=%s"
                     % (self.node_id, sorted(local_regs), sorted(expected_local)))
        for inst in self.instances:
            if not os.path.isdir(inst["cwd"]):
                self.die("实例 %s 的 cwd 不存在: %s" % (inst["name"], inst["cwd"]))

    # --------------------------------------------------------------- registry

    def marker(self, node, suffix):
        return os.path.join(self.registry_dir, "%s.%s" % (node, suffix))

    def own_marker(self, suffix):
        return self.marker(self.node_id, suffix)

    def remove_marker(self, path):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log("WARN 删除 %s 失败: %s" % (path, exc))

    def coordinator_cleanup_registry(self):
        # 与旧版一致：清掉上一轮会合文件，但把失败原因先打到日志里
        for path in sorted(glob.glob(os.path.join(self.registry_dir, "*.failed"))):
            content = read_text(path).strip()
            log("清理上一轮失败标记 %s: %s" % (os.path.basename(path), content))
            self.remove_marker(path)
        for path in sorted(glob.glob(os.path.join(self.registry_dir, "*.ready"))):
            self.remove_marker(path)
        # 兼容旧 1P1D 的会合文件；新版只认 registry/<node>.*
        for name in ("decode.ready", "decode.failed"):
            path = os.path.join(self.run_dir, name)
            if os.path.exists(path):
                content = read_text(path).strip()
                log("清理旧版会合文件 %s: %s" % (name, content))
                self.remove_marker(path)

    def remove_own_markers(self):
        self.remove_marker(self.own_marker("ready"))
        self.remove_marker(self.own_marker("failed"))

    def ready_payload(self):
        insts = []
        for inst in self.instances:
            if not inst["register"]:
                continue
            insts.append({
                "name": inst["name"],
                "kind": inst["kind"],
                "endpoint": "%s:%d" % (self.node_ip, inst["port"]),
                "bootstrap_port": inst["bootstrap"],
            })
        return {
            "node": self.node_id,
            "ip": self.node_ip,
            "time": time.time(),
            "instances": insts,
        }

    def write_ready(self):
        payload = self.ready_payload()
        atomic_write(self.own_marker("ready"),
                     json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return payload

    def write_failed(self, reason):
        text = ("%s node=%s ip=%s\n%s\n"
                % (time.strftime("%Y-%m-%d %H:%M:%S"), self.node_id,
                   self.node_ip, reason))
        try:
            atomic_write(self.own_marker("failed"), text)
        except OSError as exc:
            log("WARN 写失败标记失败: %s" % exc)

    # ---------------------------------------------------------------- process

    def set_failure(self, reason):
        with self.fail_lock:
            if not self.failure_reason:
                self.failure_reason = reason
        self.failure_event.set()

    def check_failure(self):
        if self.stop.is_set():
            return
        if self.failure_event.is_set():
            self.fail(self.failure_reason or "本地进程异常退出")

    def local_failure(self):
        if self.stop.is_set():
            return None
        for inst in self.instances:
            proc = inst.get("proc")
            if proc is not None and proc.poll() is not None:
                return ("实例 %s 已退出 rc=%s，日志 %s"
                        % (inst["name"], proc.returncode, inst["log"]))
        if self.router_proc is not None and self.router_proc.poll() is not None:
            return ("router 已退出 rc=%s，日志 %s"
                    % (self.router_proc.returncode, self.router_log))
        return None

    def fail(self, reason, rc=1):
        log("FAILED: %s" % reason)
        self.write_failed(reason)
        self.cleanup()
        sys.exit(rc)

    def start_instances(self):
        for inst in self.instances:
            try:
                logf = open(inst["log"], "w", encoding="utf-8", errors="replace")
            except OSError as exc:
                self.fail("打开日志 %s 失败: %s" % (inst["log"], exc))
            inst["logf"] = logf
            self.local_logs.append(logf)
            try:
                proc = subprocess.Popen(
                    inst["cmd"], shell=True, executable="/bin/bash",
                    cwd=inst["cwd"], env=inst["env"],
                    stdout=logf, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                self.fail("启动 %s 失败: %s" % (inst["name"], exc))
            inst["proc"] = proc
            log("start %s kind=%s port=%s pid=%d log=%s"
                % (inst["name"], inst["kind"], inst["port"], proc.pid, inst["log"]))

    def wait_local_ready(self):
        pending = {i["name"]: i for i in self.instances if i["register"]}
        started = time.time()
        while pending:
            if self.stop.is_set():
                return False
            self.check_failure()
            reason = self.local_failure()
            if reason:
                self.fail(reason)
            now = time.time()
            for name in list(pending):
                inst = pending[name]
                if inst["health"]:
                    if http_ok(inst["health"]):
                        log("%s ready (%s)" % (name, inst["health"]))
                        del pending[name]
                elif now - started >= inst["ready_delay"]:
                    log("%s ready (进程存活 %.0fs)" % (name, inst["ready_delay"]))
                    del pending[name]
                if name in pending and now - started > inst["timeout"]:
                    self.fail("等待 %s 就绪超时 (%.0fs)，探测 %s，日志 %s"
                              % (name, inst["timeout"],
                                 inst["health"] or "进程存活", inst["log"]))
            if pending:
                self.stop.wait(self.health_interval)
        return True

    def heartbeat_loop(self):
        while not self.stop.wait(self.heartbeat):
            reason = self.local_failure()
            if reason:
                self.set_failure(reason)
                return
            if self.ready_written:
                try:
                    self.write_ready()
                except OSError as exc:
                    self.set_failure("写 registry 失败: %s" % exc)
                    return

    # ------------------------------------------------------------------ peers

    def wait_peers(self):
        if not self.expected:
            return True
        peers = [n for n in self.expected if n != self.node_id]
        log("等待节点就绪: %s" % (", ".join(peers) if peers else "(无)"))
        started = time.time()
        last_log = started
        while True:
            if self.stop.is_set():
                return False
            self.check_failure()
            reason = self.local_failure()
            if reason:
                self.fail(reason)
            for nid in self.expected:
                if nid == self.node_id:
                    continue
                failed = self.marker(nid, "failed")
                if os.path.exists(failed):
                    self.fail("节点 %s 失败: %s" % (nid, read_text(failed).strip()))
            missing = []
            for nid in self.expected:
                path = self.marker(nid, "ready")
                if not os.path.exists(path):
                    missing.append(nid)
                    continue
                try:
                    data = json.loads(read_text(path) or "{}")
                except ValueError:
                    missing.append(nid)
                    continue
                names = {i.get("name") for i in data.get("instances", [])}
                want = {i["name"] for i in self.expected_by_node[nid]}
                if not want.issubset(names):
                    missing.append(nid)
            if not missing:
                log("所有节点已就绪")
                return True
            now = time.time()
            if now - started > self.wait_timeout:
                self.fail("等待节点超时 (%.0fs)，未就绪: %s；见 %s"
                          % (self.wait_timeout, missing, self.registry_dir))
            if now - last_log >= 60:
                log("仍未就绪: %s" % missing)
                last_log = now
            self.stop.wait(2)

    def collect_endpoints(self):
        prefills = []
        decodes = []
        for nid in self.expected:
            path = self.marker(nid, "ready")
            if not os.path.exists(path):
                self.fail("节点 %s 的就绪文件消失了: %s" % (nid, path))
            try:
                data = json.loads(read_text(path) or "{}")
            except ValueError as exc:
                self.fail("解析 %s 失败: %s" % (path, exc))
            by_name = {i.get("name"): i for i in data.get("instances", [])}
            for spec in self.expected_by_node[nid]:
                rec = by_name.get(spec["name"])
                if rec is None:
                    self.fail("节点 %s 的 ready 里缺少实例 %s" % (nid, spec["name"]))
                endpoint = rec.get("endpoint") or "%s:%d" % (data.get("ip"), spec["port"])
                if spec["kind"] == "prefill":
                    bootstrap = rec.get("bootstrap_port", spec["bootstrap"])
                    if bootstrap is None:
                        self.fail("prefill %s/%s 没有 bootstrap_port"
                                  % (nid, spec["name"]))
                    try:
                        bootstrap = int(bootstrap)
                    except (TypeError, ValueError):
                        self.fail("prefill %s/%s 的 bootstrap_port 无效: %r"
                                  % (nid, spec["name"], bootstrap))
                    prefills.append({"node": nid, "name": spec["name"],
                                     "endpoint": endpoint,
                                     "bootstrap": bootstrap})
                elif spec["kind"] == "decode":
                    decodes.append(endpoint)
        if not prefills or not decodes:
            self.fail("聚合后缺少 prefill 或 decode: P=%d D=%d"
                      % (len(prefills), len(decodes)))
        return prefills, decodes

    # ----------------------------------------------------------------- router

    def start_router(self, prefills, decodes):
        rcfg = self.router_cfg
        gh = os.environ.get("GATEWAY_HOST") or rcfg.get("host") or "auto"
        gh = str(gh).strip()
        if gh.lower() in ("", "auto", "detect"):
            gh = self.node_ip
        gp_raw = os.environ.get("GATEWAY_PORT") or rcfg.get("port") or 8001
        try:
            gp = int(gp_raw)
        except (TypeError, ValueError):
            self.fail("GATEWAY_PORT/router.port 不是整数: %r" % (gp_raw,))
        if not 0 < gp < 65536:
            self.fail("GATEWAY_PORT/router.port 不是合法端口: %d" % gp)
        probe = "127.0.0.1" if gh in ("0.0.0.0", "::", "[::]") else gh
        if gp in self.local_ports:
            self.fail("router 端口 %d 与本机实例 %s 冲突"
                      % (gp, self.local_ports[gp]))

        pref_addrs = [p["endpoint"] for p in prefills]
        boot_ports = [str(p["bootstrap"]) for p in prefills]
        env = dict(self.node_env)
        env.update({
            "GATEWAY_HOST": gh,
            "GATEWAY_PORT": str(gp),
            "GATEWAY_PROBE_HOST": probe,
            "PREFILL_ADDRS": " ".join(pref_addrs),
            "DECODE_ADDRS": " ".join(decodes),
            "BOOTSTRAP_PORTS": " ".join(boot_ports),
        })
        for i, addr in enumerate(pref_addrs):
            env["PREFILL_%d" % i] = addr
        for i, port in enumerate(boot_ports):
            env["BOOTSTRAP_PORT_%d" % i] = port
        for i, addr in enumerate(decodes):
            env["DECODE_%d" % i] = addr

        self.gateway_host = gh
        self.gateway_port = gp
        self.gateway_probe = probe

        cmd = str(rcfg.get("cmd") or DEFAULT_ROUTER_CMD)
        cwd = resolve_path(
            rcfg.get("cwd") or os.path.join(self.bundle, "tools"),
            self.bundle, self.ctx)
        if not os.path.isdir(cwd):
            self.fail("router cwd 不存在: %s" % cwd)
        log_name = str(rcfg.get("log") or "router_%s.log" % self.ts)
        self.router_log = os.path.abspath(
            expand(log_name, self.ctx) if os.path.isabs(log_name)
            else os.path.join(self.run_dir, expand(log_name, self.ctx))
        )
        try:
            os.makedirs(os.path.dirname(self.router_log), exist_ok=True)
        except OSError as exc:
            self.fail("router 日志目录无法创建 %s: %s"
                      % (os.path.dirname(self.router_log), exc))

        log("router endpoints: prefill=%s decode=%s bootstrap=%s"
            % (" ".join(pref_addrs), " ".join(decodes), " ".join(boot_ports)))
        try:
            self.router_logf = open(self.router_log, "w", encoding="utf-8",
                                    errors="replace")
        except OSError as exc:
            self.fail("router 日志无法打开 %s: %s" % (self.router_log, exc))
        self.local_logs.append(self.router_logf)
        try:
            self.router_proc = subprocess.Popen(
                cmd, shell=True, executable="/bin/bash", cwd=cwd, env=env,
                stdout=self.router_logf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            self.fail("启动 router 失败: %s" % exc)
        log("start router pid=%d log=%s" % (self.router_proc.pid, self.router_log))

        health = rcfg.get("health")
        if not health:
            path = expand(str(rcfg.get("health_path") or "/v1/models"),
                          dict(self.ctx, GATEWAY_HOST=gh, GATEWAY_PORT=str(gp),
                               GATEWAY_PROBE_HOST=probe))
            if not path.startswith("/"):
                path = "/" + path
            health = "http://%s:%d%s" % (probe, gp, path)
        health = expand(str(health), dict(self.ctx, GATEWAY_HOST=gh,
                                          GATEWAY_PORT=str(gp),
                                          GATEWAY_PROBE_HOST=probe))
        deadline = time.time() + self.router_timeout
        while time.time() < deadline:
            if self.stop.is_set():
                return False
            self.check_failure()
            rc = self.router_proc.poll()
            if rc is not None:
                self.fail("router 退出 rc=%s，日志 %s" % (rc, self.router_log))
            if http_ok(health):
                log("gateway ready: %s" % health)
                return True
            self.stop.wait(self.health_interval)
        self.fail("gateway 就绪超时 (%.0fs)，探测 %s，日志 %s"
                  % (self.router_timeout, health, self.router_log))
        return False

    # ----------------------------------------------------------------- client

    def run_foreground(self, cmd, env, cwd, shell=False):
        try:
            proc = subprocess.Popen(
                cmd, shell=shell, executable="/bin/bash" if shell else None,
                cwd=cwd, env=env, start_new_session=True,
            )
        except OSError as exc:
            self.fail("启动 client 失败: %s" % exc)
        while True:
            rc = proc.poll()
            if rc is not None:
                return rc
            if self.stop.is_set():
                terminate_process(proc)
                return 143
            if self.failure_event.is_set():
                terminate_process(proc)
                self.fail(self.failure_reason or "本地进程异常退出")
            time.sleep(0.5)

    def run_client(self):
        if as_bool(os.environ.get("SERVICE_ONLY")):
            log("SERVICE_ONLY=1：只起服务，不跑 client")
            return 0
        mode = str(self.client_cfg.get("mode", "modelzoo")).strip().lower()
        if mode in ("none", "skip", "off"):
            log("client.mode=%s：跳过 client" % mode)
            return 0

        env = dict(self.node_env)
        env.update({
            "GATEWAY_HOST": self.gateway_host,
            "GATEWAY_PORT": str(self.gateway_port),
            "GATEWAY_PROBE_HOST": self.gateway_probe,
        })

        if mode == "modelzoo":
            mz = self.client_cfg.get("modelzoo") or {}
            cfg_path = resolve_path(
                mz.get("config") or os.path.join(self.bundle, "config", "pd.jsonc"),
                self.bundle, self.ctx)
            task = str(mz.get("task") or "pd_e2e")
            out = resolve_path(
                mz.get("out") or os.path.join(self.run_dir, "logs"),
                self.run_dir, self.ctx)
            tag = os.environ.get("TAG") or self.ts
            if self.client_cfg.get("runs") is not None and not env.get("NUM_RUNS"):
                try:
                    runs = int(self.client_cfg["runs"])
                except (TypeError, ValueError):
                    self.fail("client.runs 必须是整数")
                if runs < 1:
                    self.fail("client.runs 必须 >= 1")
                env["NUM_RUNS"] = str(runs)
            main_py = os.path.join(self.bundle, "ModelzooTool", "bin", "main.py")
            if not os.path.isfile(main_py):
                self.fail("找不到 ModelzooTool: %s" % main_py)
            cmd = [sys.executable, main_py, "--config", cfg_path,
                   "--task", task, "-o", out, "--tag", tag]
            log("client: ModelzooTool task=%s out=%s tag=%s" % (task, out, tag))
            # cwd 用 RUN_DIR：压测细节文件（sglang_*.jsonl）落在共享盘，
            # 不污染部署包里的 config/
            return self.run_foreground(cmd, env, self.run_dir)

        if mode == "direct":
            cmd = str(self.client_cfg.get("cmd") or "")
            if not cmd:
                self.fail("client.mode=direct 但没有配置 client.cmd")
            try:
                runs = int(env.get("NUM_RUNS") or self.client_cfg.get("runs") or 3)
            except ValueError:
                self.fail("NUM_RUNS 必须是整数")
            if runs < 1:
                self.fail("client.runs/NUM_RUNS 必须 >= 1")
            cwd = resolve_path(self.client_cfg.get("cwd") or self.run_dir,
                               self.bundle, self.ctx)
            rc_all = 0
            for i in range(1, runs + 1):
                log("client run %d/%d start" % (i, runs))
                rc = self.run_foreground(cmd, env, cwd, shell=True)
                log("client run %d/%d end rc=%s" % (i, runs, rc))
                if rc:
                    rc_all = rc
                if self.stop.is_set():
                    break
            return rc_all

        self.fail("未知 client.mode=%s（支持 modelzoo/direct/none）" % mode)
        return 2

    # ------------------------------------------------------------------- main

    def dump_nic(self):
        if not shutil.which("mx-smi"):
            return
        env = dict(self.base_env)
        env.pop("_DETECT_NIC_DONE", None)
        script = ('source "$BUNDLE_DIR/tools/detect_nic.sh" >/dev/null 2>&1; '
                  'declare -F pd_ib_hca >/dev/null && pd_ib_hca -d')
        try:
            out = subprocess.run(["bash", "-c", script], env=env,
                                 capture_output=True, text=True, timeout=60)
        except Exception:
            return
        text = (out.stdout or "").strip()
        if not text:
            return
        path = os.path.join(self.run_dir, "nic_%s_%s.txt" % (self.node_id, self.ts))
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            log("NIC 明细 -> %s" % path)
        except OSError:
            pass

    def install_signals(self):
        def handler(signum, _frame):
            log("收到信号 %d，退出" % signum)
            self.stop.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass

    def stay_alive(self):
        while not self.stop.wait(5):
            self.check_failure()
            reason = self.local_failure()
            if reason:
                self.fail(reason)

    def cleanup(self):
        self.stop.set()
        if self.heartbeat_thread is not None:
            self.heartbeat_thread.join(timeout=3)
        terminate_process(self.router_proc)
        for inst in self.instances:
            terminate_process(inst.get("proc"))
        for logf in self.local_logs:
            try:
                logf.close()
            except OSError:
                pass
        if self.ready_written:
            self.remove_marker(self.own_marker("ready"))
            self.ready_written = False

    def log_banner(self):
        log("node=%s ip=%s coordinator=%s" % (self.node_id, self.node_ip,
                                              self.is_coordinator))
        log("topology=%s" % self.cfg_path)
        log("RUN_DIR=%s" % self.run_dir)
        for inst in self.instances:
            log("instance %s kind=%s port=%s gpus=%s register=%s health=%s"
                % (inst["name"], inst["kind"], inst["port"],
                   inst["gpus"] or "-", inst["register"], inst["health"] or "-"))

    def run(self):
        self.log_banner()
        if self.is_coordinator:
            self.coordinator_cleanup_registry()
        self.remove_own_markers()
        self.dump_nic()
        self.install_signals()

        self.start_instances()
        if not self.wait_local_ready():
            self.cleanup()
            return 0

        if any(i["register"] for i in self.instances):
            try:
                payload = self.write_ready()
            except OSError as exc:
                self.fail("写 registry 失败 %s: %s"
                          % (self.own_marker("ready"), exc))
            self.ready_written = True
            endpoints = " ".join(i["endpoint"] for i in payload["instances"])
            log("%s ready: %s -> %s" % (self.node_id, endpoints,
                                        self.own_marker("ready")))
        self.heartbeat_thread = threading.Thread(
            target=self.heartbeat_loop, name="heartbeat", daemon=True)
        self.heartbeat_thread.start()

        if not self.is_coordinator:
            log("节点就绪，保持运行")
            self.stay_alive()
            self.cleanup()
            return 0

        if not self.wait_peers():
            self.cleanup()
            return 0
        self.check_failure()
        prefills, decodes = self.collect_endpoints()
        if not self.start_router(prefills, decodes):
            self.cleanup()
            return 0

        rc = self.run_client()
        mode = str(self.client_cfg.get("mode", "modelzoo")).strip().lower()
        keep = (as_bool(os.environ.get("SERVICE_ONLY"))
                or as_bool(os.environ.get("KEEP_ALIVE"))
                or mode in ("none", "skip", "off"))
        if keep:
            log("保持运行（SERVICE_ONLY/KEEP_ALIVE/client.mode=%s）" % mode)
            self.stay_alive()
            self.cleanup()
            return 0
        self.cleanup()
        log("done rc=%s" % rc)
        return rc


def main():
    launcher = Launcher(sys.argv[1:])
    return launcher.run()


if __name__ == "__main__":
    sys.exit(main())
