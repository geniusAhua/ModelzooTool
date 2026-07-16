# config_loader/evaluation.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypeVar, Generic, Union

T = TypeVar('T')  # 返回值类型

@dataclass
class EvaluationContext:
    """评估上下文：封装安全策略与运行时状态"""
    allowed_modules: 'List[str]'
    context_stack: 'List[Dict[str, Any]]' = field(default_factory=list)
    
    def get_current_config(self) -> Dict[str, Any]:
        """获取当前配置项（栈顶）"""
        if not self.context_stack:
            raise RuntimeError("No active configuration context")
        return self.context_stack[-1]
    
    def resolve_reference(self, ref: 'Reference') -> Any:
        """解析引用（委托给Reference自身）"""
        return ref.resolve(self.context_stack)

@dataclass
class Reference:
    path: 'List[Union[str, int]]'  # 统一存储为字符串列表
    
    def resolve(self, context_stack: 'List[Dict[str, Any]]') -> Any:
        if not context_stack:
            raise RuntimeError("No context available for reference resolution")
        
        current = context_stack[-1]  # 从当前配置项开始
        value = current
        
        for i, part in enumerate(self.path):
            value = value[part]
        
        return value


@dataclass
class DelayedEvaluation(ABC, Generic[T]):
    """
    延迟求值抽象基类：统一参数解析与安全校验
    """
    params: Dict[str, Any] = field(default_factory=dict)
    
    @abstractmethod
    def _import_target(self, module_path: str, target_name: str, context: EvaluationContext) -> Any:
        """
        导入目标对象（函数/类）
        子类实现具体导入逻辑
        """
        pass
    
    @abstractmethod
    def _execute(self, target: Any, resolved_params: Dict[str, Any], context: EvaluationContext) -> T:
        """
        执行目标（调用函数/实例化类）
        子类实现具体执行逻辑
        """
        pass
    
    def evaluate(self, context: EvaluationContext) -> T:
        """
        公共评估入口：参数解析 → 导入 → 执行
        """
        # 1. 解析参数中的引用
        resolved_params = self._resolve_params(self.params, context)
        
        # 2. 提取模块路径与目标名（约定：params 必须包含 module_path 和 target_name）
        module_path = resolved_params.pop('module_path', None)
        target_name = resolved_params.pop('target_name', None)
        
        if not module_path or not target_name:
            raise ValueError(
                f"Missing required params 'module_path' and 'target_name' for {self.__class__.__name__}. "
                f"Available params: {list(self.params.keys())}"
            )
        
        # 3. 导入目标对象
        target = self._import_target(module_path, target_name, context)
        
        # 4. 执行并返回结果
        return self._execute(target, resolved_params, context)
    
    @staticmethod
    def _resolve_params(params: Dict[str, Any], context: EvaluationContext) -> Dict[str, Any]:
        """
        递归解析参数中的引用（公共逻辑）
        """
        resolved = {}
        for key, value in params.items():
            if isinstance(value, Reference):
                resolved[key] = context.resolve_reference(value)
            elif isinstance(value, DelayedEvaluation):
                resolved[key] = value.evaluate(context)
            elif isinstance(value, dict):
                resolved[key] = DelayedEvaluation._resolve_params(value, context)
            elif isinstance(value, list):
                resolved[key] = [
                    DelayedEvaluation._resolve_params({i: item}, context)[i] 
                    if isinstance(item, dict) else item
                    for i, item in enumerate(value)
                ]
            else:
                resolved[key] = value
        return resolved