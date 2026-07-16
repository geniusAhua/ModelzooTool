from abc import ABC, abstractmethod
from functools import partial
from typing import Any, Dict, List, Optional, Callable, Type
from dataclasses import dataclass
from pathlib import Path

import copy
import yaml
import sys
import importlib.util

from .MxYamlLoader import MxYamlLoader
from .evaluation import DelayedEvaluation, EvaluationContext
# from .security import safe_import_function, safe_import_class
from .utils import temporary_sys_path


# ------------------------------------------------------------------------------------------------ #
#                                             BaseClass                                            #
# ------------------------------------------------------------------------------------------------ #
class DelyTag(ABC):
    tag: str = None


    def __init_subclass__(cls):
        super().__init_subclass__()
        if "tag" not in cls.__dict__:
            raise TypeError(
                f"Class '{cls.__name__}' must define its own class attribute 'tag', for it's a subclass of {cls.__class__.__base__[0]}.\n"
                "Hint: Add 'tag = \"yaml_tag\"' in the class body."
            )
        if not isinstance(cls.tag, str) or not cls.tag.strip():
            raise ValueError(f"{cls.__name__} is a subclass of {cls.__class__.__base__[0]}, so the 'tag' must be a non-empty string, got {repr(cls.tag)}")


    def __init__(self, data: Any, loader: 'MxYamlLoader', suffix: Optional[str] = None):
        self.data = data
        self.loader = loader
        self.suffix = suffix  # !new 等专用


    def resolve(self, root_cfg: 'Dict', path_stack: 'List' = []) -> Any:
        resolved_data = self.loader.resolve_cfg(self.data, root_cfg, path_stack)
        return self._resolve_self(resolved_data, root_cfg, path_stack)

    @abstractmethod
    def _resolve_self(self, resolved_data: 'Any', root_cfg: 'Dict', path_stack: 'List') -> Any:
        pass


# ------------------------------------------ BaseClasee ------------------------------------------ #

@MxYamlLoader.register(is_multi = False)
class RefTag(DelyTag):
    tag = '!ref'

    def __init__(self, data: 'Any', loader: 'MxYamlLoader'):
        super().__init__(data, loader)

    def _resolve_self(self, resolved_data: 'Any', root_cfg: 'Dict', path_stack: 'List'):
        current = root_cfg
        parts = resolved_data if isinstance(resolved_data, list) else resolved_data.split('.')
        for part in parts:
            current = current[part]
        return copy.deepcopy(current)


@MxYamlLoader.register(is_multi = True)
class FuncTag(DelyTag):
    tag = '!func'

    def __init__(self, data: 'Any', loader: 'MxYamlLoader', suffix: str):
        super().__init__(data, loader, suffix)

    def import_module(self, package_path: 'str', module_part: 'str'):
        # 从文件路径导入模块
        assert package_path is not None, f"Tag[{self.tag}] doesn't receive the parameter 'path'"
        dir_path = Path(package_path).resolve()
        dir_str = str(dir_path)

        unique_module_name = f"__dynamic_{hash(dir_path)}_{module_part.replace('.', '_')}"

        with temporary_sys_path(dir_str):
            # 先检查缓存
            if unique_module_name in sys.modules:
                return sys.modules[unique_module_name]

            try:
                module = importlib.import_module(module_part)
            except ModuleNotFoundError as e:
                raise ModuleNotFoundError(f"Cannot find module '{module_part}' in dir '{dir_path}': {e}")

            sys.modules[unique_module_name] = module

            return module

    def _resolve_self(self, resolved_data: 'Any', root_cfg: 'Dict', path_stack: 'List'):
        args = resolved_data.get('args', [])
        kwargs = resolved_data.get('kwargs', {})

        dir = Path(resolved_data['path'])
        if not dir.is_absolute():
            package_path = Path(self.loader.name).parent / dir

        if package_path.is_file():
            raise ValueError(f"Tag[{self.tag}] The provided path must be a directory! not a file!")

        parts = self.suffix.split('.')
        if len(parts) < 2:
            raise ValueError(f"Tag[{self.tag}] Suffix must contain at least one '.' (module.func)")

        func_name = parts[-1]
        module_part = '.'.join(parts[:-1])

        module = self.import_module(package_path, module_part)
        
        # 获取函数
        func = getattr(module, func_name)

        # 返回 partial callable
        return partial(func, *args, **kwargs)



class Reference_ref:
    tag = "!ref"


    def construct(self, loader, node):
        if isinstance(node, yaml.ScalarNode):
            data = loader.construct_scalar(node)
        
    
    def resolve(self, context_stack: 'List[Dict[str, Any]]') -> Any:
        if not context_stack:
            raise RuntimeError("No context available for reference resolution")
        
        # 从当前配置项（栈顶）开始解析
        current = context_stack[-1]
        
        # 处理绝对路径（以/开头）
        if self.path.startswith('/'):
            parts = [p for p in self.path[1:].split('/') if p]
            value = current
            for part in parts:
                if isinstance(value, dict):
                    # ✅ 关键：字段名原样使用，不拆分点号
                    if part in value:
                        value = value[part]
                    else:
                        raise KeyError(
                            f"Field '{part}' not found in path '{self.path}'. "
                            f"Available fields: {list(value.keys())}"
                        )
                else:
                    raise TypeError(
                        f"Cannot traverse into non-dict at '{'/'.join(parts[:parts.index(part)+1])}': "
                        f"got {type(value).__name__}"
                    )
            return value
        
        raise ValueError(f"Unsupported reference path: '{self.path}' (must start with '/')")


@dataclass
class FunctionCall(DelayedEvaluation[Any]):
    """
    函数调用：!function:module.func
    约定：params 必须包含 module_path 和 target_name（func_name）
    """
    def _import_target(self, module_path: str, target_name: str, context: EvaluationContext) -> Callable:
        return safe_import_function(module_path, target_name, context.allowed_modules)
    
    def _execute(self, func: Callable, resolved_params: Dict[str, Any], context: EvaluationContext) -> Any:
        return func(**resolved_params)
