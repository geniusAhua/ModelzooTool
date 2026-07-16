import yaml
from .tags import Reference, FunctionCall, NewInstance

def _parse_tag_suffix(suffix: str) -> tuple[str, str]:
    """解析 !function:module.func -> ('module', 'func')"""
    if '.' not in suffix:
        raise ValueError(f"Invalid tag suffix '{suffix}', expected 'module.func'")
    return suffix.rsplit('.', 1)

def _function_constructor(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> FunctionCall:
    module_path, func_name = _parse_tag_suffix(suffix)
    params = loader.construct_mapping(node) if isinstance(node, yaml.MappingNode) else {}
    return FunctionCall(module_path, func_name, params)

def _new_constructor(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> NewInstance:
    module_path, class_name = _parse_tag_suffix(suffix)
    params = loader.construct_mapping(node) if isinstance(node, yaml.MappingNode) else {}
    return NewInstance(module_path, class_name, params)

def _ref_constructor(loader: yaml.SafeLoader, node: yaml.Node) -> Reference:
    """!ref /path/to/field -> Reference('/path/to/field')"""
    path = loader.construct_scalar(node)
    if not path.startswith('/'):
        raise ValueError(f"Reference path must start with '/': '{path}'")
    return Reference(path)