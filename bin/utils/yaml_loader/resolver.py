from typing import Any, Dict, List

from yaml import SafeLoader
from .tags import Reference, FunctionCall, NewInstance

class MzYamlLoader(SafeLoader):
    """上下文感知解析器：维护配置项栈以支持字段引用"""
    
    def __init__(self, allowed_modules: List[str]):
        self.allowed_modules = allowed_modules
        self.context_stack: List[Dict[str, Any]] = []
    
    def resolve(self,  data: Any) -> Any:
        if isinstance(data, list):
            return [self._resolve_list_item(i, item) for i, item in enumerate(data)]
        return self._resolve_value(data)
    
    def _resolve_list_item(self, index: int, item: Any) -> Any:
        """处理配置列表项：压入当前项作为上下文"""
        if isinstance(item, dict):
            self.context_stack.append(item)
            try:
                resolved = self._resolve_dict(item)
            finally:
                self.context_stack.pop()  # 确保弹出
            return resolved
        return self._resolve_value(item)
    
    def _resolve_dict(self,  data: Dict[str, Any]) -> Dict[str, Any]:
        resolved = {}
        for k, v in data.items():
            resolved[k] = self._resolve_value(v)
        return resolved
    
    def _resolve_value(self, value: Any) -> Any:
        if isinstance(value, (FunctionCall, NewInstance)):
            return value.evaluate(self.context_stack, self.allowed_modules)
        elif isinstance(value, Reference):
            return value.resolve(self.context_stack)
        elif isinstance(value, dict):
            return self._resolve_dict(value)
        elif isinstance(value, list):
            return [self._resolve_value(item) for item in value]
        return value