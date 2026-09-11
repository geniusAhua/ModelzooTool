from concurrent.futures import ThreadPoolExecutor
import re
import os, signal, subprocess, sys
from multiprocessing import Event, Process
import threading
from typing import Callable, Optional


# server 启动完成的默认日志标志（可在配置文件中通过 readyTag 覆盖）
DEFAULT_READY_TAG = "Application startup complete"
READY_LOG = DEFAULT_READY_TAG

class ModelzooProcess():
    def __init__(self,role: "str", cmd: "str", env: "dict", log_path: "str", ready_event: "Event", error_event: "Event", callback: "Optional[Callable[[str], None]]" = None):
        self._role = role
        self._cmd = cmd
        self._env = env
        self._log_path = log_path
        self._ready_event = ready_event
        self._error_event = error_event
        self._proc = None
        self._callback = callback
        self._log_mod = "w"
        self._returncode = 0


    def start(self):
        try:
            self._head_title_print()

            preexec_fn = os.setsid
            self._proc = subprocess.Popen(
                self._cmd, shell=True, env=self._env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, preexec_fn=preexec_fn
            )

            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

            pool = ThreadPoolExecutor(max_workers = 1)
            future = pool.submit(self._log_worker)
            future.result() # through this function can catch the exception from thread

            self._proc.wait()
            self._returncode = self._proc.poll()
            if self._returncode != 0:
                raise RuntimeError(f"{self._role} 进程异常退出: {self._returncode}")
        
        except KeyboardInterrupt:
            pass

        except RuntimeError as e:
            print(f"{self._role} 进程内部异常: \n\t{e}")
            self._error_event.set()    # 主动通知主进程：崩了
            sys.exit(1)
        
        finally:
            if self._returncode != 0:
                self._error_event.set() if not self._error_event.is_set() else None
            # 这里可以保证外部进程被终止时proc的进程也会一并终止
            print(f"{self._role} 进程终止中...")
            if self._proc and self._proc.poll() is None:  # still running
                print(f"终止 {self._role}(pid: {self._proc.pid}) 及其进程组(pgid:{os.getpgid(self._proc.pid)})...")
                try:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
                except Exception as e:
                    print(f"{self._role} 进程 {self._proc.pid} 初次终止失败！\n [Cause] {e}")
                    pass
                try:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
                except Exception as e:
                    print(f"{self._role} 进程 {self._proc.pid} 终止失败！\n [Cause] {e}")
                    sys.exit(1)
            print(f"{self._role} 进程结束!")


    def _log_worker(self):
        with open(self._log_path, self._log_mod, encoding="utf-8") as f:
            f.write(f"run: {self._cmd}\n")
            for line in self._proc.stdout:
                f.write(line)
                f.flush()
                if self._callback:
                    self._callback(line)

    
    def _head_title_print(self):
        print(f"{self._role} 进程启动，查看log请执行:", flush=True)
        print(f"tail -f {self._log_path}", flush=True)


    def _signal_handler(self, signum, frame):
        sys.exit(0)


class ServerProc(ModelzooProcess):
    def __init__(self, cmd: "str", env: "dict", ready_event: "Event", error_event: "Event", log_path: "str", ready_tag: "str" = READY_LOG):
        super().__init__("Server", cmd, env, log_path, ready_event, error_event, self._log_check)
        self._log_mod = "w"
        # ready_tag 支持字符串或字符串列表，命中任意一个即认为 server 就绪
        self._ready_tags = [ready_tag] if isinstance(ready_tag, str) else list(ready_tag)


    def _log_check(self, line):
        if not self._ready_event.is_set():
            for tag in self._ready_tags:
                if tag and tag in line:
                    self._ready_event.set()
                    print(f"Server 已就绪（命中标志: {tag}）→ 通知 Client 可以启动")
                    break

        if "CUDA out of memory" in line or "Segmentation fault" in line:
            raise RuntimeError(f"检测到严重错误: {line}")


class ClientProc(ModelzooProcess):
    def __init__(self, cmd: "str", env: "dict", ready_event: "Event", error_event: "Event", log_path: "str"):
        super().__init__("Client", cmd, env, log_path, ready_event, error_event)
        self._log_mod = "a"


    def _head_title_print(self):
        print("等待 Server 进程准备完毕...")
        self._ready_event.wait()
        super()._head_title_print()