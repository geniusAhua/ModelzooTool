from contextlib import contextmanager
from pathlib import Path


import sys


@contextmanager
def temporary_sys_path(*paths):
    """临时将路径加入 sys.path，退出时自动恢复"""
    original = sys.path.copy()
    sys.path[:0] = [str(Path(p).resolve()) for p in paths]  # 插入到最前面
    try:
        yield
    finally:
        sys.path = original