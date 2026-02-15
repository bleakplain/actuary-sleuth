#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法规查询脚本
"""
import argparse
import json
import sys
from pathlib import Path

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

def main():
    parser = argparse.ArgumentParser(description='法规查询脚本')
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
    """执行法规查询"""
    try:
        from lib import db, vector_store, ollama
    except ImportError as e:
        return {
            "success": False,
            "error": f"Failed to import modules: {str(e)}"
        }

    query_text = params.get('query', '')
    search_type = params.get('searchType', 'hybrid')

    if not query_text:
        return {
            "success": False,
            "error": "Missing required parameter: query"
        }

    results = []

    # 精确查询
    if search_type in ['exact', 'hybrid']:
        try:
            exact = db.find_regulation(query_text)
            if exact:
                results.append({
                    'type': 'exact',
                    'content': exact.get('content', ''),
                    'law_name': exact.get('law_name', ''),
                    'article_number': exact.get('article_number', ''),
                    'category': exact.get('category', ''),
                    'score': 1.0
                })
        except Exception as e:
            # 精确查询失败，继续其他查询方式
            pass

    # 关键词查询
    if search_type in ['exact', 'hybrid']:
        try:
            keyword_results = db.search_regulations(query_text)
            for kw in keyword_results:
                results.append({
                    'type': 'keyword',
                    'content': kw.get('content', ''),
                    'law_name': kw.get('law_name', ''),
                    'article_number': kw.get('article_number', ''),
                    'category': kw.get('category', ''),
                    'score': 0.8
                })
        except Exception as e:
            # 关键词查询失败，继续其他查询方式
            pass

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
