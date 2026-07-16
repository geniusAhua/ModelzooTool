from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class Case:
    """表示一个测试用例"""
    bs: int
    input_len: int
    output_len: int


class BaseTaskStrategy(ABC):
    """
    任务调度策略基类
    负责控制 Server 的生命周期：
    - 何时启动 Server
    - 何时杀死 Server
    """

    def __init__(self, task_name: str, cases: List[Case]):
        self.task_name = task_name
        self.cases = cases
        self.current_index = 0

    @abstractmethod
    def should_start_server(self) -> bool:
        """当前 case 是否需要启动 Server"""
        pass

    @abstractmethod
    def should_kill_server_after_case(self) -> bool:
        """当前 case 执行完成后是否需要杀死 Server"""
        pass

    def move_next(self):
        """移动到下一个 case"""
        self.current_index += 1

    def has_next(self) -> bool:
        return self.current_index < len(self.cases)

    def get_current_case(self) -> Case:
        if self.current_index >= len(self.cases):
            raise IndexError("已经没有更多的 case 了")
        return self.cases[self.current_index]

    def reset(self):
        self.current_index = 0