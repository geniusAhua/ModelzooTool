from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
import copy
import socket
from core.config_parse import _Config


class CommandBuilder:
    def __init__(self):
        self.config = _Config()
        # 每个任务一个端口（同一任务下 server/client 共用），首次渲染时探测
        self._task_ports: Dict[str, int] = {}

    @staticmethod
    def _pick_free_port() -> int:
        """向内核要一个当前可用的空闲端口（绑定 0 号端口后立即释放）。"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("", 0))
            return int(sock.getsockname()[1])

    def get_task_port(self, task_name: str) -> int:
        """同一任务下 server/client 共用同一个端口；每个任务只探测一次。

        注意：探测与释放之间理论上存在被抢占的窗口，属可接受的常见做法。
        """
        if task_name not in self._task_ports:
            self._task_ports[task_name] = self._pick_free_port()
        return self._task_ports[task_name]

    def _get_render_context(
        self,
        task_name: str,
        bs: int,
        input_len: int,
        output_len: int,
        log_path: 'Path'
    ) -> Dict[str, Any]:
        if not log_path:
            raise ValueError("__LOG_PATH__ 不能为空")

        context = {}
        context.update(self.config.task_info)
        context.update({
            "bs": str(bs),
            "input": str(input_len),
            "output": str(output_len),
        })

        context["__FILE_NAME__"] = str(self.config.fileName)
        context["modelPath"] = str(self.config.modelPath)

        context["__LOG_PATH__"] = str(log_path)

        # __PORT__：自动探测的可用端口，同一任务内 server/client 拿到同一个值
        context["__PORT__"] = str(self.get_task_port(task_name))

        prompt_ratio = self.config.task_info.get("promptRatio", 1)
        context["prompts"] = str(bs * prompt_ratio)
        return context

    def _render(self, template: Optional[str], context: Dict[str, Any]) -> str:
        if not template:
            return ""
        class SafeDict(dict):
            def __missing__(self, key):
                raise ValueError("{" + key + "-Missing}")
        try:
            return str(template).format_map(SafeDict(context))
        except Exception as e:
            print(f"[CommandBuilder] 渲染失败: {e}, origin template: {template}")
            raise e

    def _build_final_cmd(
        self,
        default_cmd: Optional[str],
        task_cmd: Optional[str],
        extra_args: Optional[List[str]],
        context: Dict[str, Any]
    ) -> str:
        """构建最终命令（支持 extra_args 追加）"""
        if task_cmd:  # 覆盖模式
            base = self._render(task_cmd, context)
        else:
            base = self._render(default_cmd, context) or ""

        if extra_args:
            rendered_args = [self._render(arg, context) for arg in extra_args]
            base = base.strip() + " " + " ".join(rendered_args)

        return base

    def _merge_env(
        self,
        default_env: dict,
        task_env: dict,
        context: Dict[str, Any]
    ) -> Dict[str, str]:
        merged = copy.deepcopy(default_env or {})
        task_env_copy = copy.deepcopy(task_env or {})
        merged.update(task_env_copy)

        for key, value in list(merged.items()):
            if isinstance(value, (int, float)):
                merged[key] = str(value)
            elif isinstance(value, str):
                merged[key] = self._render(value, context)
            else:
                merged[key] = str(value)   # 兜底处理
        return merged

    # ==================== Client 构建（支持 warmup） ====================

    def build_client_command(
        self,
        task_name: str,
        bs: int,
        input_len: int,
        output_len: int,
        log_path: 'Path'
    ) -> Tuple[str, Dict[str, str]]:
        context = self._get_render_context(task_name, bs, input_len, output_len, log_path)

        default_client = self.config.get_default_client()
        task_client = self.config.get_client_config(task_name)

        default_cmd = default_client.get("cmd")
        task_cmd = task_client.get("cmd")
        extra_args = task_client.get("extra_args", [])
        task_env = task_client.get("env", {})
        warmup = task_client.get("warmup", False)

        if warmup:
            # Warmup 模式：base_cmd && final_cmd
            if task_cmd:
                base_cmd = self._render(task_cmd, context)
            else:
                base_cmd = self._render(default_cmd, context)

            # 在 base_cmd 基础上添加 extra_args
            final_cmd = self._build_final_cmd(
                default_cmd=base_cmd,
                task_cmd=None,
                extra_args=extra_args,
                context=context
            )

            final_client_cmd = f"{base_cmd} && {final_cmd}"
        else:
            # 普通模式
            final_client_cmd = self._build_final_cmd(
                default_cmd=default_cmd,
                task_cmd=task_cmd,
                extra_args=extra_args,
                context=context
            )

        final_env = self._merge_env(
            default_client.get("env", {}),
            task_env,
            context
        )

        return final_client_cmd, final_env

    # ==================== Server 构建（保持不变） ====================

    def build_server_command(
        self,
        task_name: str,
        bs: int,
        input_len: int,
        output_len: int,
        log_path: 'Path'
    ) -> Tuple[str, Dict[str, str]]:
        context = self._get_render_context(task_name, bs, input_len, output_len, log_path)

        default_server = self.config.get_default_server()
        task_server = self.config.get_server_config(task_name)

        final_cmd = self._build_final_cmd(
            default_server.get("cmd"),
            task_server.get("cmd"),
            task_server.get("extra_args", []),
            context
        )

        final_env = self._merge_env(
            default_server.get("env", {}),
            task_server.get("env", {}),
            context
        )

        return final_cmd, final_env