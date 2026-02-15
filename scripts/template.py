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

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

def main():
    parser = argparse.ArgumentParser(description='Actuary Sleuth Script')
    parser.add_argument('--input', required=True, help='JSON input file')
    parser.add_argument('--config', default='./config/settings.json', help='Config file')
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
