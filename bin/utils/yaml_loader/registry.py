from pathlib import Path
from typing import Any, Dict, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .tags import DelyTag


class MxYamlConstructorRegistry:
    
    """私有单例配置类"""
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return  # 防止重复初始化
        
        self._ref_classes: 'Dict[str, Tuple[DelyTag, bool]]' = {}
    

    @classmethod
    def register(cls, *, is_multi: bool = False):
        def decorator(dely_ref_class):
            if not issubclass(dely_ref_class, DelyTag):
                raise TypeError("Must inherit from DelyTag")
            
            tag = dely_ref_class.tag

            if cls._ref_classes.get(tag, None):
                cls._ref_classes.setdefault(tag, (dely_ref_class, is_multi))
            else:
                raise ValueError("Cannot registe an already registed object")

            return dely_ref_class

        return decorator