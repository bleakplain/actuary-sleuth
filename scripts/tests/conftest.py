#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pytest配置和共享fixtures
"""
import pytest
import sys
import os
from pathlib import Path

# 添加lib目录到路径
lib_dir = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_dir))

# 加载环境变量
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

# 导入共享的fixtures
try:
    from tests.utils.fixtures import *
    from tests.utils.mocks import *
    from tests.utils.rag_fixtures import *
except ImportError:
    pass
