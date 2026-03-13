#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 引擎测试入口 - 正确设置 Python 路径
"""
import sys
from pathlib import Path

# 确保 scripts 目录在 Python 路径中
project_root = Path(__file__).parent.parent
scripts_dir = project_root / 'scripts'
sys.path.insert(0, str(scripts_dir))

# 导入并运行测试
from tests.rag_engine.test_qa_engine import (
    test_user_qa,
    test_audit_query,
    test_data_importer,
    test_async_query
)

if __name__ == '__main__':
    try:
        # 运行所有测试
        test_data_importer()
        test_user_qa()
        test_audit_query()
        # test_async_query()  # 可选

        print("\n" + "=" * 60)
        print("所有测试完成!")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)