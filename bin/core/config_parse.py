# from typing import Optional, Tuple
# import json5
# import os
# import yaml
# from packaging import version
# from pathlib import Path
# 
# SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# class _Config:
#     """私有单例配置类"""
#     _instance = None
#     _initialized = False
# 
#     def __new__(cls, *args, **kwargs):
#         if cls._instance is None:
#             cls._instance = super().__new__(cls)
#         return cls._instance
# 
#     def __init__(self, configPath: "str" = None):
#         if self._initialized:
#             return  # 防止重复初始化
# 
#         self.maca: "str"            = None
#         self.backend: "str"         = None
#         self.backendVersion: "str"  = None
#         self.modelName: "str"       = None
#         self.modlePath: "str"       = None
#         self.tp: "int"              = None
#         self.port: "int"            = None
#         self.promptRatio: "int"     = None
#         self.server_cmd: "str"      = None
#         self.client_cmd: "str"      = None
#         self.Profiler: "Optional[dict]"         = None
#         self.GemmShape: "Optional[dict]"        = None
#         self.E2E: "Optional[dict]"              = None
#         self.FlashAttnShape: "Optional[dict]"   = None
#         self.TritonDump: "Optional[dict]"       = None
# 
#         config_path = Path(SCRIPT_DIR)/ ".." / "test" / "config.jsonc" if configPath is None else Path(configPath)
#         config_path = config_path.resolve()
#         self.config_name = config_path.stem
#         print(f"config path is: {config_path}")
# 
#         if not config_path.exists():
#             raise FileNotFoundError(f"Configuration file doesn't exist: {config_path}")
# 
#         with open(config_path, 'r', encoding='utf-8') as f:
#             raw_data = f.read().strip()
#             if config_path.suffix in {'.json', '.jsn', '.jsonc'}:
#                 self._data = json5.loads(raw_data)
#             elif config_path.suffix in {'.yaml', '.yml'}:
#                 self._data = yaml.safe_load(raw_data)
#             else:
#                 raise ValueError(f"Unsupported file format: '{config_path.suffix}'.\nSupported formats: .yaml, .yml .")
#         
#         self.maca       = self._data.get("MACA", None)
#         self.modelName  = self._data["modelName"]
#         self.modlePath  = self._data["modelPath"]
#         self.tp         = self._data["tp"]
#         self.port       = self._data["port"]
#         self.promptRatio= self._data["promptRatio"]
#         self.server_cmd = self._data["server"]["cmd"]
#         self.client_cmd = self._data["client"]["cmd"]
#         self.Profiler   = self._data.get("Profiler", None)
#         self.GemmShape  = self._data.get("GemmShape", None)
#         self.E2E        = self._data.get("E2E", None)
#         self.FlashAttnShape = self._data.get("FlashAttnShape", None)
#         self.TritonDump     = self._data.get("TritonDump", None)
#         self.backend        = self._data.get("backend", None)
#         # self.tasks_config, self.backend_config = self._get_task_backend_config()
# 
#         # print(f"tasks_config: {self.tasks_config}")
#         # print(f"vllm_config: {self.backend_config}")
#         
#         self._initialized = True
#         print(f"配置已加载: {config_path.resolve()}")
# 
# 
#     def __getitem__(self, item: "str"):
#         if item in self.__dict__:
#             return self.__dict__[item]
#         elif item == "Custom":
#             return None
#         else:
#             raise ValueError(f"not found {item} in {self.__class__.__name__}")
#     
# 
#     def _get_version_config(self, config_file: "str", requested_version: "str" = None) -> "dict":
#         with open(config_file, 'r') as f:
#             config = yaml.safe_load(f)
#         
#         all_versions = sorted(config['versions'].keys(), key=version.parse)  # 按版本排序：['v1.0', 'v1.1', 'v2.0', 'v2.1']
#         latest_version = all_versions[-1]  # 最新：'v2.1'
#         
#         if requested_version is None:  # 要求2：未提供 → 用最新
#             print(f"未明确版本号，使用最新版本{latest_version}")
#             return config['versions'][latest_version]
#         
#         if requested_version in config['versions']:  # 有精确匹配 → 直接用
#             print(f"找到对应版本({requested_version})配置")
#             return config['versions'][requested_version]
#         
#         # 要求3：没找到 → 找不高于它的最新版本
#         candidates = [v for v in all_versions if version.parse(v) <= version.parse(requested_version)]
#         if candidates:
#             closest = sorted(candidates, key=version.parse)[-1]
#             print(f"未找到目标版本，将使用不高于提供版本的最新版本: {closest}")
#             return config['versions'][closest]
#         else:
#             raise ValueError(f"No version <= {requested_version} found.")
#     
# 
#     def _get_task_backend_config(self) -> "Tuple[dict, dict]":
#         tasks_config_path = (Path(SCRIPT_DIR) / ".." / "version-config" / "tasks-cfg.yaml").resolve()
#         backend_config_dict = {
#             "vllm": (Path(SCRIPT_DIR) / ".." / "version-config" / "vllm-cfg.yaml").resolve(),
#             "sglang": None
#         }
# 
#         backend_config_path = backend_config_dict[self.backend.lower()]
# 
#         tasks_config = self._get_version_config(tasks_config_path, self.maca)
#         backend_config = self._get_version_config(backend_config_path, self.backendVersion)
# 
#         return tasks_config, backend_config

# bin/core/config_parse.py

from typing import Dict, Any, List, Optional
import json5
import os
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


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

        # 解析各个任务类型
        known_keys = {"modelName", "task_info", "server", "client"}
        for key, value in data.items():
            if key not in known_keys and isinstance(value, dict):
                self.tasks[key] = value

    # ==================== 便捷方法 ====================

    def get_task_config(self, task_name: str) -> Dict[str, Any]:
        return self.tasks.get(task_name, {})

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

    def __getitem__(self, key: str):
        if key in self.__dict__:
            return self.__dict__[key]
        if key in self.tasks:
            return self.tasks[key]
        raise KeyError(f"配置中不存在 key: {key}")