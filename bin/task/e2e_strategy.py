from typing import List
from .base_strategy import BaseTaskStrategy, Case


class E2EStrategy(BaseTaskStrategy):
    """
    E2E 策略：
    - 整个任务只启动一次 Server（在第一个 case 时启动）
    - 后续 case 复用已启动的 Server
    - 所有 case 执行完后，由上层统一杀死 Server
    """

    def __init__(self, task_name: str, cases: List[Case]):
        super().__init__(task_name, cases)
        self._server_has_started = False

    def should_start_server(self) -> bool:
        if not self._server_has_started:
            self._server_has_started = True
            return True
        return False

    def should_kill_server_after_case(self) -> bool:
        # E2E 模式下不在这里杀死 Server，由上层在所有 case 执行完后统一处理
        return False

    def is_last_case(self) -> bool:
        return self.current_index == len(self.cases) - 1