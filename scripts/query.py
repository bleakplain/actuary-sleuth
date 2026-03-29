#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法规查询脚本
"""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description='法规查询脚本')
    parser.add_argument('--query', help='查询内容（条款编号或关键词）')
    parser.add_argument('--searchType', default='semantic',
                       choices=['semantic', 'hybrid'],
                       help='搜索类型：semantic(语义)、hybrid(混合)，默认semantic')
    args = parser.parse_args()

    if not args.query:
        parser.error("--query is required")

    params = {
        'query': args.query,
        'searchType': args.searchType
    }

    try:
        result = execute(params)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
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

    from lib.rag_engine import RAGEngine, RAGConfig

    config = RAGConfig()
    engine = RAGEngine(config)
    use_hybrid = search_type == 'hybrid'

    results = engine.search(query_text, top_k=5, use_hybrid=use_hybrid)

    return {
        'success': True,
        'query': query_text,
        'search_type': search_type,
        'results': results[:5],
        'count': len(results[:5])
    }

if __name__ == '__main__':
    sys.exit(main())
