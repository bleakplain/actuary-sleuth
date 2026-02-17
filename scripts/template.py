#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Actuary Sleuth Script Template
统一脚本接口规范
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))


# 配置文件路径（相对于脚本目录）
CONFIG_PATH = Path(__file__).parent / 'config' / 'settings.json'


def load_config() -> Dict[str, Any]:
    """
    加载配置文件

    Returns:
        dict: 配置字典，如果文件不存在则返回空字典
    """
    config = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load config file: {e}", file=sys.stderr)
    return config


def main():
    parser = argparse.ArgumentParser(description='Actuary Sleuth Script')
    parser.add_argument('--input', required=True, help='JSON input file')
    args = parser.parse_args()

    # 读取输入
    with open(args.input, 'r', encoding='utf-8') as f:
        params = json.load(f)

    # 执行业务逻辑
    try:
        result = execute(params)
        # 输出结果（JSON格式）
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        # 错误输出
        error_result = {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }
        print(json.dumps(error_result, ensure_ascii=False), file=sys.stderr)
        return 1

def execute(params):
    """具体业务逻辑实现 - 子类必须覆盖"""
    raise NotImplementedError("Subclasses must implement execute()")

if __name__ == '__main__':
    sys.exit(main())
