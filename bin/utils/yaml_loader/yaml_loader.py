# config_loader.py
import yaml
import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ==================== 安全策略 ====================
_ALLOWED_MODULES = ["bencht_test", "my_project"]  # 白名单

def _safe_import(module_path: str, name: str, is_class: bool = False) -> Any:
    """安全导入：白名单校验 + 类型检查"""
    if not any(module_path == m or module_path.startswith(f"{m}.") for m in _ALLOWED_MODULES):
        raise PermissionError(f"Module '{module_path}' not in whitelist")
    
    obj = getattr(importlib.import_module(module_path), name)
    if is_class and not isinstance(obj, type):
        raise TypeError(f"{module_path}.{name} is not a class")
    if not is_class and not callable(obj):
        raise TypeError(f"{module_path}.{name} is not callable")
    return obj


# ==================== 延迟求值对象 ====================
class Reference:
    """字段引用：!ref [name] 或 !ref [serve_config, tp]"""
    def __init__(self, path: List[str]):
        self.path = path  # 如 ['name'] 或 ['serve_config', 'tp']
    
    def evaluate(self, context_stack: List[Dict]) -> Any:
        if not context_stack:
            raise RuntimeError("No context for reference resolution")
        
        # 从当前配置项（栈顶）开始查找
        obj = context_stack[-1]
        for i, key in enumerate(self.path):
            if not isinstance(obj, dict) or key not in obj:
                raise KeyError(f"Field '{key}' not found at level {i} in path {self.path}")
            obj = obj[key]
        return obj


class FunctionCall:
    """函数调用：!function:module.func {param: value}"""
    def __init__(self, module_path: str, func_name: str, params: Dict):
        self.module_path = module_path
        self.func_name = func_name
        self.params = params
    
    def evaluate(self, context_stack: List[Dict]) -> Any:
        # 先解析参数中的引用
        resolved = _resolve_value(self.params, context_stack)
        # 再导入并调用
        func = _safe_import(self.module_path, self.func_name)
        return func(**resolved)


class NewInstance:
    """类实例化：!new:module.Class {param: value}"""
    def __init__(self, module_path: str, class_name: str, params: Dict):
        self.module_path = module_path
        self.class_name = class_name
        self.params = params
    
    def evaluate(self, context_stack: List[Dict]) -> Any:
        resolved = _resolve_value(self.params, context_stack)
        cls = _safe_import(self.module_path, self.class_name, is_class=True)
        return cls(**resolved)


# ==================== YAML 构造器 ====================
def _ref_constructor(loader: yaml.Loader, node):
    """!ref [name] → Reference(['name'])"""
    if isinstance(node, yaml.SequenceNode):
        path = loader.construct_sequence(node, deep=True)
    else:
        raise TypeError(f"!ref requires sequence or scalar, got {type(node)}")
    return Reference(path)

def _tag_constructor(loader, suffix, node):
    """统一处理 !function: 和 !new: 标签"""
    print('=='*100)
    print(f"loader.__class__.__name__: {loader.__class__.__name__}")

    module_path, target_name = suffix.rsplit('.', 1)
    params = loader.construct_mapping(node) if isinstance(node, yaml.MappingNode) else {}

    
    
    if loader.__class__.__name__.startswith('Function'):
        return FunctionCall(module_path, target_name, params)
    else:  # NewConstructor
        return NewInstance(module_path, target_name, params)

# 注册到 SafeLoader
yaml.SafeLoader.add_constructor('!ref', _ref_constructor)
yaml.SafeLoader.add_multi_constructor('!function', _tag_constructor)
yaml.SafeLoader.add_multi_constructor('!new', _tag_constructor)


# ==================== 上下文解析器 ====================
def _resolve_value(value: Any, context_stack: List[Dict]) -> Any:
    """递归解析值：处理引用/函数调用/嵌套结构"""
    # 延迟对象：求值
    if isinstance(value, (Reference, FunctionCall, NewInstance)):
        return value.evaluate(context_stack)
    
    # 字典：递归解析每个值
    if isinstance(value, dict):
        return {k: _resolve_value(v, context_stack) for k, v in value.items()}
    
    # 列表：递归解析每个元素
    if isinstance(value, list):
        # 配置项列表：压入上下文
        if all(isinstance(item, dict) and 'name' in item for item in value):
            resolved = []
            for item in value:
                context_stack.append(item)  # 压入当前配置项
                try:
                    resolved.append(_resolve_value(item, context_stack))
                finally:
                    context_stack.pop()  # 确保弹出
            return resolved
        else:
            return [ _resolve_value(item, context_stack) for item in value ]
    
    # 普通值：直接返回
    return value


# ==================== 公共API ====================
def load_config(yaml_path: Path | str, allowed_modules: Optional[List[str]] = None) -> Any:
    """
    安全加载YAML配置，支持上下文引用
    
    示例配置:
      - name: "Llama2-7B.v1.0"
        benchmark:
          python: !function:bencht_test.get_test
            model: !ref [name]          # → "Llama2-7B.v1.0"
            tp: !ref [serve_config, tp] # → 4
    """
    global _ALLOWED_MODULES
    if allowed_modules:
        _ALLOWED_MODULES = allowed_modules
    
    # 阶段1: 安全解析（不执行代码）
    with open(yaml_path, 'r', encoding='utf-8') as f:
        raw = yaml.load(f, Loader=yaml.SafeLoader)
    
    # 阶段2: 上下文感知求值
    return _resolve_value(raw, context_stack=[])


load_config(Path("/sw_home/m01088/tmp/batched_test/dailytest_models_C500_test.yaml"))