#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pytest配置和共享fixtures
"""
import pytest
import sys
import os
from pathlib import Path


def pytest_configure(config):
    """Ensure scripts/ is first in sys.path so api package resolves correctly."""
    scripts_dir = str(Path(__file__).parent.parent)
    if scripts_dir in sys.path:
        sys.path.remove(scripts_dir)
    sys.path.insert(0, scripts_dir)


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
    from tests.utils.fixtures import temp_output_dir, sample_docx_file
    from tests.utils.mocks import MockLLMClient
except ImportError:
    pass
