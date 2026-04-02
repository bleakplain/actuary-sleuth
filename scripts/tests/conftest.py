#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pytest configuration."""
import os
import sys
from pathlib import Path


def pytest_configure(config):
    """Ensure scripts/ is first in sys.path so lib package resolves correctly."""
    scripts_dir = str(Path(__file__).parent.parent)
    if scripts_dir in sys.path:
        sys.path.remove(scripts_dir)
    sys.path.insert(0, scripts_dir)

    # Load environment variables
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

    # Register RAG fixtures plugin after sys.path is set
    config.pluginmanager.import_plugin("tests.utils.rag_fixtures")
