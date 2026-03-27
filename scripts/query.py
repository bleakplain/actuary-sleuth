#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法规查询脚本
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any

from lib.config import get_config
from lib import vector_store
from lib import ollama


def main():
    parser = argparse.ArgumentParser(description='法规查询脚本')
    parser.add_argument('--query', help='查询内容（条款编号或关键词）')
    parser.add_argument('--searchType', default='semantic',
                       choices=['semantic', 'hybrid'],
                       help='搜索类型：semantic(语义)、hybrid(混合)，默认semantic')
    args = parser.parse_args()

    # 验证必填参数
    if not args.query:
        parser.error("--query is required")

    # 构建参数
    params = {
        'query': args.query,
        'searchType': args.searchType
    }

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
    """执行法规查询"""
    query_text = params.get('query', '')
    search_type = params.get('searchType', 'semantic')

    if not query_text:
        return {
            "success": False,
            "error": "Missing required parameter: query"
        }

    results = []

    # 语义检索
    if search_type in ['semantic', 'hybrid']:
        try:
            query_vec = ollama.embed(query_text)
            semantic = vector_store.VectorDB.search(query_vec, top_k=5)
            for item in semantic:
                results.append({
                    'type': 'semantic',
                    'content': item.get('content', ''),
                    'law_name': item.get('metadata', {}).get('law_name', ''),
                    'article_number': item.get('metadata', {}).get('article_number', ''),
                    'score': item.get('score', 0)
                })
        except Exception as e:
            # 语义检索失败，记录错误但继续
            pass

    # 排序返回
    results.sort(key=lambda x: x.get('score', 0), reverse=True)

    return {
        'success': True,
        'query': query_text,
        'search_type': search_type,
        'results': results[:5],
        'count': len(results[:5])
    }

if __name__ == '__main__':
    sys.exit(main())
