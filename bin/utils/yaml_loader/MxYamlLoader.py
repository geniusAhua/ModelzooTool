from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, TYPE_CHECKING

from .tags import DelyTag

import yaml

class MxYamlLoader(yaml.SafeLoader):
    _ref_classes: 'Dict' = {}
    
    def __init__(self, ):
        # super().__init__(stream)
        self.resolvers: 'Dict[str, Callable]' = {}

        for tag, (dely_ref_cls, is_multi) in self._ref_classes.items():
            if is_multi:
                def multi_wrapper(loader, suffix, node, cls=dely_ref_cls):
                    data = loader.construct_mapping(node, deep=True)
                    return cls(data, loader, suffix=suffix)
                self.add_multi_constructor(tag, multi_wrapper)
            else:
                def fixed_wrapper(loader, node, cls=dely_ref_cls):
                    if isinstance(node, yaml.MappingNode):
                        data = loader.construct_mapping(node, deep=True)
                    elif isinstance(node, yaml.SequenceNode):
                        data = loader.construct_sequence(node)
                    elif isinstance(node, yaml.ScalarNode):
                        data = loader.construct_scalar(node)
                    else:
                        data = None
                    return cls(data, loader)
                self.add_constructor(tag, fixed_wrapper)
    
    
    def resolve_cfg(self, obj: 'Any', root_cfg: 'Dict', path_stack: 'List' = []) -> Any:
        if isinstance(obj, DelyTag):
            return obj.resolve(root_cfg, path_stack)

        if isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = self.resolve_cfg(v, root_cfg, path_stack + [k])
            return obj

        if isinstance(obj, list):
            return [self.resolve_cfg(item, root_cfg, path_stack + [i]) for i, item in enumerate(obj)]

        return obj



def register(is_multi: bool = False):
    def decorator(dely_ref_class):
        if not issubclass(dely_ref_class, DelyTag):
            raise TypeError("Must inherit from DelyTag")
        
        tag = dely_ref_class.tag

        if MxYamlLoader._ref_classes.get(tag, None):
            MxYamlLoader._ref_classes.setdefault(tag, (dely_ref_class, is_multi))
        else:
            raise ValueError("Cannot registe an already registed object")

        return dely_ref_class

    return decorator