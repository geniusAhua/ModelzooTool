from typing import List
from .base_strategy import BaseTaskStrategy, Case


class PairStrategy(BaseTaskStrategy):
    """
    Pair 策略（适用于 Profiler、GemmShape、FlashAttnShape、TritonDump 等）：
    - 每个 case 都成对启动 Server + Client
    - 每个 case 执行完后立即杀死对应的 Server
    """

    def should_start_server(self) -> bool:
        # Pair 模式下，每个 case 都需要重新启动 Server
        return True

    def should_kill_server_after_case(self) -> bool:
        # 执行完当前 case 后立即杀死 Server
        return True