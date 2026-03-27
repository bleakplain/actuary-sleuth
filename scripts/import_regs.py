#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入法规数据到数据库
从 markdown 文件解析法规条款并导入到 LanceDB 和 BM25 索引
"""
import sys
import argparse
from pathlib import Path

# 添加 scripts 目录到路径
scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))

from lib.rag_engine import RegulationDataImporter, get_config


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='导入法规数据到数据库（LanceDB + BM25）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 导入所有法规
  python import_regs.py

  # 强制重建索引
  python import_regs.py --rebuild

  # 导入单个文件
  python import_regs.py --file 01_保险法相关监管规定.md

  # 测试模式：只解析不导入
  python import_regs.py --test
        """
    )

    parser.add_argument(
        '--refs-dir',
        type=str,
        default='./references',
        help='法规文档目录路径 (默认: ./references)'
    )
    parser.add_argument(
        '--file',
        type=str,
        help='导入单个文件（指定文件名）'
    )
    parser.add_argument(
        '--rebuild',
        action='store_true',
        help='强制重建向量索引'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='测试模式：解析文档但不导入'
    )
    parser.add_argument(
        '--pattern',
        type=str,
        default='*.md',
        help='文件匹配模式 (默认: *.md)'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("法规数据导入工具")
    print("=" * 60)

    # 创建导入器配置
    config = get_config(regulations_dir=args.refs_dir)
    importer = RegulationDataImporter(config)

    # 解析文档
    if args.file:
        print(f"\n解析单个文件: {args.file}")
        documents = importer.parse_single_file(args.file)
    else:
        print(f"\n从 {args.refs_dir} 解析法规文档")
        documents = importer.parse_documents(args.pattern)

    if not documents:
        print("没有解析到任何文档")
        return 1

    print(f"成功解析 {len(documents)} 条法规")

    # 测试模式
    if args.test:
        print("\n测试模式 - 显示前 3 条法规:")
        for i, doc in enumerate(documents[:3], 1):
            law_name = doc.metadata.get('law_name', 'N/A')
            article_num = doc.metadata.get('article_number', 'N/A')
            print(f"\n{i}. [{law_name}] {article_num}")
            print(f"   {doc.text[:100]}...")
        return 0

    # 执行导入
    print("\n开始导入到数据库...")

    stats = importer.import_all(
        file_pattern=args.pattern,
        force_rebuild=args.rebuild,
    )

    # 显示导入结果
    print("\n" + "=" * 60)
    print("导入完成")
    print("=" * 60)
    print(f"解析文档: {stats.get('parsed', 0)} 条")
    print(f"向量索引: {stats.get('vector', 0)} 条")
    print(f"BM25 索引: {stats.get('bm25', 0)} 条")
    print("=" * 60)

    return 0 if stats.get('parsed', 0) > 0 else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n导入已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n错误: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
