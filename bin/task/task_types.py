"""任务类型注册表。

任务类型决定调度行为（server / client 的生命周期），与任务名称解耦：
配置里每个任务通过 `type` 指定类型，任务名称可以随意自定义，
执行时用 `--task <任务名> [<任务名> ...]` 选择要跑的任务。
"""
from typing import Dict, List

from .base_strategy import BaseTaskStrategy, Case
from .e2e_strategy import E2EStrategy
from .pair_strategy import PairStrategy

# 内置任务类型（名称保持简洁好记）：
#   e2e  —— 端到端：只启动一次 server，串行跑完所有 case
#   pair —— 成对：每个 case 一对 server + client（每个 case 会重启 server）
E2E_TASK_TYPE = "e2e"
PAIR_TASK_TYPE = "pair"

TASK_TYPES: Dict[str, Dict] = {
    E2E_TASK_TYPE: {
        "strategy": E2EStrategy,
        "desc": "只启动一次 server，串行跑完所有 case",
    },
    PAIR_TASK_TYPE: {
        "strategy": PairStrategy,
        "desc": "每个 case 一对 server + client（每个 case 重启 server）",
    },
}

DEFAULT_TASK_TYPE = PAIR_TASK_TYPE


def list_task_types() -> List[str]:
    return list(TASK_TYPES.keys())


def describe_task_types() -> str:
    return "; ".join(f"{name}({meta['desc']})" for name, meta in TASK_TYPES.items())


def get_task_type_meta(task_type: str) -> Dict:
    if task_type not in TASK_TYPES:
        raise ValueError(f"未知任务类型: {task_type}；可用类型: {describe_task_types()}")
    return TASK_TYPES[task_type]


def get_strategy(task_type: str, task_name: str, cases: List[Case]) -> BaseTaskStrategy:
    """按任务类型创建对应的调度策略。"""
    return get_task_type_meta(task_type)["strategy"](task_name, cases)
