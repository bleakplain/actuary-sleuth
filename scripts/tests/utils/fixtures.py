#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test fixtures."""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_output_dir():
    """Temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
