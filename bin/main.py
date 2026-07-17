#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json5
import subprocess
import signal
import sys
import time
import os
from pathlib import Path
from typing import Any, Dict, TYPE_CHECKING, Optional, List
from multiprocessing import Process, Event
from core.modelzooProcessor import ServerProc, ClientProc
from core.config_parse import _Config
from utils.command_builder import CommandBuilder
from task.base_strategy import Case
from task.e2e_strategy import E2EStrategy
from task.pair_strategy import PairStrategy




SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


TASKS = {
    "p": {
        "TASK": "Profiler"
    },
    "b": {
        "TASK": "BlasShape"
    },
    "t": {
        "TASK": "TlasShape"
    },
    "f": {
        "TASK": "FlashAttnShape"
    },
    "d": {
        "TASK": "TritonDump"
    },
    "E": {"TASK": "E2E"},
}

def clean_triton_cache():
    commands = [
        "rm -rf /root/.triton/*",
        "rm -rf /root/.cache/vllm/*",
        "rm -rf ~/.cache/vllm",
    ]
    print("正在清理 Triton 编译缓存...")

    for cmd in commands:
        print(f"  执行: {cmd}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  成功")
        else:
            print(f"  失败: {result.stderr.strip() or '无输出'}")
    
    print(" Triton 缓存目录，清理完成")


ready_event = Event()  # Server, Client进程间通信, 只要需要启动Server就要重置
error_event = Event()  # 异常通知, 无需重置, set了就结束整个工具
server_p: 'Process' = None
client_p: 'Process' = None
# def start_modelzoo(task_name: "str", server_cmd: "str", client_cmd: "str", env: "dict", server_log: "str", client_log: "str", is_pair_mode: "bool") -> bool:
#     try:
#         print(f"\n{'-'*100}")
#         print(f" [{task_name}-Server]: {server_cmd}")
#         print(f" [{task_name}-Client]: {client_cmd}")
#         print("")
#         print(f" Server日志 → {server_log}")
#         print(f" Client日志 → {client_log}")
#         print(f"{'-'*100}")
#         
#         server_runner = ServerProc(server_cmd, env, ready_event, error_event, server_log)
#         client_runner = ClientProc(client_cmd, env, ready_event, error_event, client_log)
#         # 启动两个独立进程
#         if server_cmd:
#             ready_event.clear()
#             server_p = Process(
#                 target=server_runner.start,
#                 daemon=True
#             )
#             server_p.start()
#         
#         client_p = Process(
#             target=client_runner.start,
#             daemon=True
#         )
#         client_p.start()
# 
#         while True:
#             if error_event.is_set():
#                 print(" Server Error, 请检查 Server 命令, 后续任务将会停止")
#                 client_p.terminate()
#                 client_p.join(timeout=5) or client_p.kill()
#                 return False
#             
#             if ready_event.is_set():
#                 break
# 
#             if server_cmd and not server_p.is_alive() and not ready_event.is_set():
#                 # Server 死了但没发 ready → 肯定是异常
#                 print("Server 意外终止！")
#                 error_event.set()
#                 continue
# 
#             time.sleep(1)
# 
#         # 主进程等待 client 结束
#         client_p.join()
#         returncode = client_p.exitcode
#         client_p = None
# 
#         # client 结束后，杀掉 server
#         # 在 start_modelzoo 函数最后增加判断
#         if is_pair_mode and server_cmd and server_p and server_p.is_alive():
#             print("Pair 模式：Client 结束，终止当前 Server...")
#             try:
#                 os.kill(server_p.pid, signal.SIGINT)
#                 server_p.join(timeout=10)
#             except Exception as e:
#                 print(f"终止 Server 失败: {e}")
#             server_p = None
#         # if task_name != "E2E" and server_cmd and server_p.is_alive():
#         #     print("Client 结束 → 终止 Server 进程...")
#         #     try:
#         #         os.kill(server_p.pid, signal.SIGINT)    # 发送SIGINT，可以使得进程走向finally
#         #     except Exception as e:
#         #         print(f"在终止 Server 进程时出现了问题: {e}")
#         #     server_p.join()
#         #     server_p = None
# 
#         success = (returncode == 0)
#         return success
#     except KeyboardInterrupt:
#         if client_p and client_p.is_alive():
#             client_p.join()
#         if server_p and server_p.is_alive():
#             server_p.join()
#         raise

ready_event = Event()
error_event = Event()
server_p: Optional[Process] = None
client_p: Optional[Process] = None


def start_modelzoo(
    task_name: str,
    server_cmd: Optional[str],
    client_cmd: str,
    env: dict,
    server_log: str,
    client_log: str,
    is_pair_mode: bool = False
) -> bool:
    """
    启动 Server + Client
    is_pair_mode: 是否为 Pair 模式（非 E2E）
    """
    global server_p, client_p

    try:
        # 创建 Server 进程（如果需要）
        if server_cmd:
            ready_event.clear()
            server_runner = ServerProc(
                cmd=server_cmd,
                env=env,
                ready_event=ready_event,
                error_event=error_event,
                log_path=server_log
            )
            server_p = Process(target=server_runner.start, daemon=True)
            server_p.start()

        # 创建 Client 进程
        client_runner = ClientProc(
            cmd=client_cmd,
            env=env,
            ready_event=ready_event,
            error_event=error_event,
            log_path=client_log
        )
        client_p = Process(target=client_runner.start, daemon=True)
        client_p.start()

        # 等待 Server 就绪 或 出错
        while True:
            if error_event.is_set():
                print("检测到错误，准备清理进程...")
                _cleanup_processes()
                return False

            if ready_event.is_set():
                break

            # Server 意外退出但没发 ready
            if server_p and not server_p.is_alive() and not ready_event.is_set():
                print("Server 进程意外退出！")
                error_event.set()
                continue

            time.sleep(0.5)

        # 等待 Client 执行完成
        client_p.join()
        success = (client_p.exitcode == 0)
        client_p = None

        # Pair 模式下，Client 结束后杀死 Server
        if is_pair_mode and server_p and server_p.is_alive():
            _terminate_process(server_p, "Server")

        return success

    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在清理进程...")
        _cleanup_processes()
        raise

    except Exception as e:
        print(f"start_modelzoo 发生异常: {e}")
        _cleanup_processes()
        raise


def _terminate_process(proc: Process, role: str, timeout: int = 10):
    """尝试优雅终止进程"""
    if proc and proc.is_alive():
        try:
            proc.terminate()
            proc.join(timeout=timeout)
            if proc.is_alive():
                proc.kill()
        except Exception as e:
            print(f"终止 {role} 进程时出错: {e}")


def _cleanup_processes():
    """清理所有残留进程"""
    global server_p, client_p

    if client_p and client_p.is_alive():
        _terminate_process(client_p, "Client")

    if server_p and server_p.is_alive():
        _terminate_process(server_p, "Server")

    server_p = None
    client_p = None


def render_magic(template_obj: "list[str, dict]", **kwargs):
    """
    安全地渲染环境变量中的 {key} 占位符
    - 有 {} 就填充
    - 没有 {} 保持原样
    - 找不到的 key 也不报错（返回原占位符或空）
    """
    # 构造一个「带默认值的映射」：找不到 key 时返回 {key} 本身
    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "-Missing}"  # 找不到就原样返回，防止 KeyError
    if template_obj is None:
        return None
    if isinstance(template_obj, dict):
        return {k: str(v).format_map(SafeDict(kwargs)) for k, v in template_obj.items()}
    if isinstance(template_obj, str):
        return template_obj.format_map(SafeDict(kwargs))


READY_LOG  = "Application startup complete"
# def run_task(taskNName: "str", out_dir: "Path") -> "bool":
#     config = _Config()
# 
#     tp_size = config.tp
#     port = config.port
#     server_cmd_base = config.server_cmd
#     client_cmd_base = config.client_cmd
#     model_name = config.modelName
#     model_path = config.modlePath
# 
#     taskConfig = TASKS[taskNName]
#     env_vars = taskConfig.get("ENV", None)
#     task_name = taskConfig["TASK"]
#     
#     task_env = None
#     timestamp = time.strftime("%Y%m%d_%H_%M")
# 
#     # 同一类同一批任务的时间戳应当相同
#     log_dir = out_dir / f"{model_name}-{task_name}" / f"{timestamp}"
#     log_dir.mkdir(parents=True, exist_ok=True)
# 
#     bs_in_out_list = config[task_name]["bs_in_out"]
#     
#     # TritonDump需要先清理缓存避免无法找到dumpKernel
#     if task_name == "TritonDump":
#         clean_triton_cache()
# 
#     # 若端到端未配置cases，则默认用户提供了自定义的脚本执行
#     if not any(bs_in_out_list):
# 
#         log_file_name = f"{model_name}-{task_name}-{{role}}-customize.log"
#         log_file_pattern = str(log_dir / log_file_name)
# 
#         env = {**os.environ}
#         server_cmd = render_magic(server_cmd_base, modelPath = model_path, tp = tp_size, port = port)
#         client_cmd = render_magic(client_cmd_base, modelPath = model_path, tp = tp_size, port = port)
# 
#         print(f"\n{'='*100}")
#         print(f" 执行任务 [{task_name}] | Case: 用户自定义 Client |")
#         print(f" 环境变量: {task_env} ")
#         print(f"{'='*100}")
#         success = start_modelzoo(task_name, server_cmd, client_cmd, env, log_file_pattern.format(role = "Server"), log_file_pattern.format(role = "Client"))
#         print(f"任务 {task_name}-{model_name}:[用户自定义 Client] 完成 → {'成功' if success else '失败'}")
#         return success
# 
#     # 非customized任务
#     firstE2E = True
#     for batch_size, input_len, output_len in bs_in_out_list:
# 
#         if env_vars:
#             task_env = {**render_magic({**env_vars}, modelName = model_name, prompts = batch_size * config.promptRatio, bs = batch_size, input = input_len, output = output_len, tp = tp_size, port = port)}
#         
#         server_log_file_name = f"{model_name}-{task_name}-Server-{config.config_name}.log"
#         client_log_file_name = f"{model_name}-{task_name}-Client-{config.config_name}-All-Cases.log"
#         server_log_file = str(log_dir / server_log_file_name)
#         client_log_file = str(log_dir / client_log_file_name)
# 
#         env = {**os.environ, **(task_env or {})}
# 
#         server_cmd = render_magic(server_cmd_base, modelPath = model_path, prompts = batch_size * config.promptRatio, bs = batch_size, input = input_len, output = output_len, tp = tp_size, port = port)
#         client_cmd = render_magic(client_cmd_base, modelPath = model_path, prompts = batch_size * config.promptRatio, bs = batch_size, input = input_len, output = output_len, tp = tp_size, port = port)
# 
#         if task_name == "E2E":
#             if firstE2E:
#                 firstE2E = False
#             else:
#                 server_cmd = None
# 
#         if task_name == "TritonDump":
#             # 避免dumpKernel的结果到其他目录下
#             server_cmd = f"cd {out_dir} && {server_cmd}"
#         
#         # extra_args is a list
#         extra_args = taskConfig.get("extra-args", None)
#         if extra_args:
#             print(f" 任务 {task_name} 有额外参数 {extra_args} 已自动为您添加")
#             server_cmd += " " + " ".join(extra_args)
# 
#         print(f"\n{'='*100}")
#         print(f" 执行任务 [{task_name}] | Case: bs{batch_size}-input{input_len}-output{output_len} |")
#         print(f" 环境变量: {task_env} ")
#         print(f"{'='*100}")
#         success = start_modelzoo(task_name, server_cmd, client_cmd, env, server_log_file, client_log_file)
#         print(f"任务 {task_name}-{model_name}:[bs{batch_size}-input{input_len}-output{output_len}] 完成 → {'成功' if success else '失败'}")
#         if not success: return success
#     
#     if task_name == "E2E" and server_p and server_p.is_alive():
#         print("Client 结束 → 终止 Server 进程...")
#         try:
#             os.kill(server_p.pid, signal.SIGINT)    # 发送SIGINT，可以使得进程走向finally
#         except Exception as e:
#             print(f"在终止 Server 进程时出现了问题: {e}")
#         server_p.join()
#     print("\n")
#     return True

def get_strategy(task_name: str, cases: List[Case]):
    """根据任务类型返回对应的策略"""
    if task_name == "E2E":
        return E2EStrategy(task_name, cases)
    else:
        return PairStrategy(task_name, cases)

def run_task(task_flag: str, out_dir: Path) -> bool:
    config = _Config()
    task_info = TASKS[task_flag]
    task_name = task_info["TASK"]

    bs_in_out_list = config.get_bs_in_out(task_name)
    if not bs_in_out_list:
        print(f"[跳过] 任务 {task_name} 没有 bs_in_out 配置")
        return True

    cases = [Case(bs=bs, input_len=inp, output_len=out) for bs, inp, out in bs_in_out_list]
    strategy = get_strategy(task_name, cases)
    builder = CommandBuilder()

    timestamp = time.strftime("%Y%m%d_%H_%M")
    log_dir = out_dir / f"{config.fileName}" / task_name / timestamp
    log_dir.mkdir(parents=True, exist_ok=True)

    if task_name == "TritonDump":
        clean_triton_cache()

    is_e2e = (task_name == "E2E")
    is_pair_mode = not is_e2e

    while strategy.has_next():
        case = strategy.get_current_case()
        bs, input_len, output_len = case.bs, case.input_len, case.output_len

        if is_e2e:
            log_path = log_dir
        else:
            log_path = log_dir / f"bs{bs}-in{input_len}-out{output_len}"
            log_path.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*80}")
        print(f"[{task_name}] Case: bs={bs}, input={input_len}, output={output_len}")
        print(f"日志路径: {log_path}")
        print(f"{'='*80}")

        # 构建命令
        server_cmd, server_env = builder.build_server_command(
            task_name=task_name, bs=bs, input_len=input_len,
            output_len=output_len, log_path=log_path
        )
        client_cmd, client_env = builder.build_client_command(
            task_name=task_name, bs=bs, input_len=input_len,
            output_len=output_len, log_path=log_path
        )

        env = {**os.environ, **server_env, **client_env}

        # E2E 模式下，只有第一个 case 需要传 server_cmd
        current_server_cmd = server_cmd if strategy.should_start_server() else None


        client_log_name = f"Client-{task_name}-AllCase.log" if not is_pair_mode else f"Client-{task_name}-bs{bs}-in{input_len}-out{output_len}.log"
        server_log_name = f"Server-{task_name}.log" if not is_pair_mode else f"Server-{task_name}-bs{bs}-in{input_len}-out{output_len}.log"
        client_log = str(log_path / client_log_name)
        server_log = str(log_path / server_log_name)

        print(f"\n{'-'*100}")
        print(f" [{task_name}-Server-ENV]: {' '.join([key + '=' + value for key,value in server_env.items()])} ")
        print(f" [{task_name}-Server]: {server_cmd}")
        print(f" [{task_name}-Client-ENV]: {' '.join([key + '=' + value for key,value in client_env.items()])} ")
        print(f" [{task_name}-Client]: {client_cmd}")
        if current_server_cmd:
            print(f" Server日志 → {server_log}")
        print(f" Client日志 → {client_log}")
        print(f"{'-'*100}")

        success = start_modelzoo(
            task_name=task_name,
            server_cmd=current_server_cmd,
            client_cmd=client_cmd,
            env=env,
            server_log=server_log,
            client_log=client_log,
            is_pair_mode=is_pair_mode
        )

        if not success:
            print(f"任务 {task_name} 执行失败，停止")
            # E2E 失败时也要尝试清理 server
            if is_e2e:
                from main import _cleanup_processes   # 根据实际位置调整
                _cleanup_processes()
            return False

        strategy.move_next()

    # ===================== E2E 特殊处理 =====================
    # 所有 Client 执行完后，清理 Server
    if is_e2e:
        print(f"\n[{task_name}] 所有 Client 执行完毕，正在清理 Server 进程...")
        from main import _cleanup_processes
        _cleanup_processes()

    print(f"\n任务 {task_name} 执行完成\n")
    return True


def create_parser():
    parser = argparse.ArgumentParser(
        description="Modelzoo最强工具集",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="个人配置config路径"
    )

    parser.add_argument(
        "-p", "--profiler",
        action="store_true",
        help="执行torch profiler抓取算子数据",
    )

    parser.add_argument(
        "-t", "--tlas-shape",
        action="store_true",
        help="抓取mctlas shape",
    )

    parser.add_argument(
        "-b", "--blas-shape",
        action="store_true",
        help="抓取mcblas shape",
    )

    parser.add_argument(
        "-f", "--flash-attn-shape",
        action="store_true",
        help="抓取flash attention shape",
    )

    parser.add_argument(
        "-d", "--dump-triton",
        action="store_true",
        help="抓取triton kernel",
    )

    parser.add_argument(
        "-E", "--E2E",
        action="store_true",
        help="执行端到端测试命令",
    )

    parser.add_argument(
        "-o", "--output-dir",
        type=str, default = f"{SCRIPT_DIR}/../result",
        help = "log及结果输出目录，如果目录不存在则会自动创建目录"
    )

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    result_dir = Path(args.output_dir).resolve()
    result_dir.mkdir(parents=True, exist_ok=True)

    _Config(args.config)

    selected = []
    if args.profiler: selected.append("p")
    if args.tlas_shape: selected.append("t")
    if args.blas_shape: selected.append("b")
    if args.flash_attn_shape: selected.append("f")
    if args.dump_triton: selected.append("d")
    if args.E2E: selected.append("E")

    if not selected:
        parser.error("至少要选择一个任务！请查看 --help")
    
    try:
        for name in selected:
            if not run_task(name, result_dir): 
                print(f"任务 {TASKS[name]['TASK']} 失败，停止后续任务\n")
                sys.exit(1)

        print(f"Auto Modelzoo Tool 执行完毕!")
    except KeyboardInterrupt:
        print(f"Auto Modelzoo Tool 被终止.")
        pass

if __name__ == "__main__":
    main()