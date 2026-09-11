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
from core.modelzooProcessor import ServerProc, ClientProc, DEFAULT_READY_TAG
from core.config_parse import _Config
from utils.command_builder import CommandBuilder
from task.base_strategy import Case
from task.task_types import (
    E2E_TASK_TYPE,
    describe_task_types,
    get_strategy,
    get_task_type_meta,
)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


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
    is_pair_mode: bool = False,
    ready_tag: Optional[str] = None
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
                log_path=server_log,
                ready_tag=ready_tag if ready_tag is not None else DEFAULT_READY_TAG
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



def run_task(task_name: str, out_dir: Path, log_tag: 'Optional[str]') -> bool:
    config = _Config()

    available = config.get_task_names()
    if task_name not in available:
        print(f"[错误] 配置中不存在任务: {task_name}（可用: {', '.join(available) or '无'}）")
        return False

    task_type = config.get_task_type(task_name)
    if not task_type:
        print(f"[错误] 任务 \"{task_name}\" 缺少 type 字段；可用类型: {describe_task_types()}")
        return False
    try:
        get_task_type_meta(task_type)
    except ValueError as e:
        print(f"[错误] {e}")
        return False

    bs_in_out_list = config.get_bs_in_out(task_name)
    if not bs_in_out_list:
        print(f"[跳过] 任务 {task_name} 没有 bs_in_out 配置")
        return True

    cases = [Case(bs=bs, input_len=inp, output_len=out) for bs, inp, out in bs_in_out_list]
    strategy = get_strategy(task_type, task_name, cases)
    builder = CommandBuilder()
    ready_tag = config.get_ready_tag(task_name)

    timestamp = time.strftime("%Y%m%d_%H_%M")
    log_dir = out_dir / f"{config.fileName}" / task_name / (timestamp + ('+'+log_tag if log_tag is not None else ''))
    log_dir.mkdir(parents=True, exist_ok=True)

    if config.should_clean_triton_cache(task_name):
        clean_triton_cache()

    is_e2e = (task_type == E2E_TASK_TYPE)
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
            is_pair_mode=is_pair_mode,
            ready_tag=ready_tag
        )

        if not success:
            print(f"任务 {task_name} 执行失败，停止")
            # E2E 失败时也要尝试清理 server
            if is_e2e:
                _cleanup_processes()
            return False

        strategy.move_next()

    # ===================== E2E 特殊处理 =====================
    # 所有 Client 执行完后，清理 Server
    if is_e2e:
        print(f"\n[{task_name}] 所有 Client 执行完毕，正在清理 Server 进程...")
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
        "--tag",
        type=str,
        default=None,
        help="给最终的log路径名称添加tag，方便区分。默认是时间命名，添加该参数可以在末尾添加tag"
    )

    parser.add_argument(
        "--task",
        nargs="+",
        default=None,
        metavar="NAME",
        help=f"要执行的任务名称（可写多个，按顺序执行；取自配置文件中自定义的任务段）。任务类型: {describe_task_types()}",
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

    log_tag = args.tag

    _Config(args.config)
    config = _Config()

    task_names = args.task
    if not task_names:
        parser.error(
            "请用 --task 指定要执行的任务名称（可多个）。"
            f"配置中的任务: {', '.join(config.get_task_names()) or '无'}"
        )

    available = config.get_task_names()
    unknown = [name for name in task_names if name not in available]
    if unknown:
        parser.error(
            f"配置中不存在这些任务: {', '.join(unknown)}；"
            f"可用任务: {', '.join(available) or '无'}"
        )

    failed = []
    try:
        for name in task_names:
            # 每个任务开始前清空错误标志并清理残留进程，
            # 保证前一个任务的失败不会影响后续任务的启动
            error_event.clear()
            _cleanup_processes()

            if not run_task(name, result_dir, log_tag):
                print(f"任务 {name} 失败，继续执行后续任务\n")
                failed.append(name)

        if failed:
            print(f"\n以下任务失败: {', '.join(failed)}")
            print(f"其余任务已执行完毕!")
            sys.exit(1)

        print(f"Auto Modelzoo Tool 执行完毕!")
    except KeyboardInterrupt:
        print(f"Auto Modelzoo Tool 被终止.")
        pass

if __name__ == "__main__":
    main()
