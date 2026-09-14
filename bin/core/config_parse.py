from typing import Dict, Any, List, Optional
import json5
import os
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# server 启动完成的默认日志标志
DEFAULT_READY_TAG = "Application startup complete"


def parse_ready_tag(value: Any, where: str = "") -> str:
    """readyTag 只允许单个字符串（不再支持数组），否则直接报错。"""
    if isinstance(value, str):
        return value
    raise ValueError(
        f"{where}readyTag 必须是单个字符串（已不再支持数组），当前为: {value!r}"
    )


class _Config:
    """配置单例类（已适配最新 config 结构）"""
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, configPath: Optional[str] = None):
        if self._initialized:
            return

        # ==================== 基础字段 ====================
        self.fileName: str = ""
        self.task_info: Dict[str, Any] = {}
        self.default_server: Dict[str, Any] = {}
        self.default_client: Dict[str, Any] = {}
        self.tasks: Dict[str, Dict[str, Any]] = {}   # 各任务类型配置
        self.ready_tag: str = DEFAULT_READY_TAG      # server 启动完成标志（顶层默认值，单个字符串）

        # ==================== 解析配置 ====================
        if configPath is None:
            config_path = Path(SCRIPT_DIR) / ".." / "test" / "config.jsonc"
        else:
            config_path = Path(configPath)

        config_path = config_path.resolve()
        print(f"config_path: {config_path}", flush=True)
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        # 初始化文件名称信息
        self.fileName = config_path.stem

        with open(config_path, 'r', encoding='utf-8') as f:
            self._raw_data: Dict[str, Any] = json5.loads(f.read())

        self._parse()

        self._initialized = True
        print(f"[Config] 配置加载完成: {config_path}")

    def _parse(self):
        data = self._raw_data

        self.modelPath = data.get("modelPath")
        # task_info
        self.task_info = data.get("task_info", {})

        # 默认 server / client
        self.default_server = data.get("server", {})
        self.default_client = data.get("client", {})

        # server 启动完成标志：顶层 readyTag（只允许单个字符串）
        self.ready_tag = parse_ready_tag(data.get("readyTag", DEFAULT_READY_TAG), "顶层")

        # 解析各个任务类型
        known_keys = {"modelName", "modelPath", "readyTag", "task_info", "server", "client"}
        for key, value in data.items():
            if key not in known_keys and isinstance(value, dict):
                self.tasks[key] = value

        # 任务级 readyTag（可选，覆写顶层）同样只允许单个字符串
        for name, task_cfg in self.tasks.items():
            if "readyTag" in task_cfg:
                parse_ready_tag(task_cfg["readyTag"], f'任务 "{name}" 的')

    # ==================== 便捷方法 ====================

    def get_task_config(self, task_name: str) -> Dict[str, Any]:
        return self.tasks.get(task_name, {})

    def get_task_names(self) -> List[str]:
        """配置文件中定义的所有任务名称（顺序为配置书写顺序）。"""
        return list(self.tasks.keys())

    def get_task_type(self, task_name: str) -> Optional[str]:
        """任务类型（决定调度行为），对应任务段里的 type 字段。"""
        return self.get_task_config(task_name).get("type")

    def should_clean_triton_cache(self, task_name: str) -> bool:
        """任务开始前是否清理 triton 编译缓存，对应任务段里的 cleanTritonCache 字段。"""
        return bool(self.get_task_config(task_name).get("cleanTritonCache", False))

    def get_bs_in_out(self, task_name: str) -> List[List[int]]:
        return self.get_task_config(task_name).get("bs_in_out", [])

    def get_server_config(self, task_name: str) -> Dict[str, Any]:
        task_cfg = self.get_task_config(task_name)
        return task_cfg.get("server", {})

    def get_client_config(self, task_name: str) -> Dict[str, Any]:
        task_cfg = self.get_task_config(task_name)
        return task_cfg.get("client", {})

    def get_default_server(self) -> Dict[str, Any]:
        return self.default_server

    def get_default_client(self) -> Dict[str, Any]:
        return self.default_client

    def get_task_info(self) -> Dict[str, Any]:
        return self.task_info

    def get_ready_tag(self, task_name: Optional[str] = None) -> str:
        """server 启动完成标志（单个字符串）。任务级 readyTag 优先于顶层 readyTag。"""
        if task_name:
            task_tag = self.get_task_config(task_name).get("readyTag")
            if task_tag is not None:
                return task_tag
        return self.ready_tag

    def __getitem__(self, key: str):
        if key in self.__dict__:
            return self.__dict__[key]
        if key in self.tasks:
            return self.tasks[key]
        raise KeyError(f"配置中不存在 key: {key}")
