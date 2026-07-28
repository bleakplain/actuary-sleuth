#!/usr/bin/env python3
"""输出审核主链的数据就绪扫描报告。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from lib.compliance.readiness import scan_readiness


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读扫描审核数据就绪状态")
    parser.add_argument("--kb-root", type=Path, required=True)
    parser.add_argument("--references-dir", type=Path, required=True)
    parser.add_argument("--product-dir", type=Path, required=True)
    parser.add_argument("--topic-keywords", type=Path, required=True)
    parser.add_argument("--version", default="v5")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parse_args(arguments)
    report = scan_readiness(
        kb_root=args.kb_root,
        references_dir=args.references_dir,
        product_dir=args.product_dir,
        topic_keywords_path=args.topic_keywords,
        version=args.version,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 1 if report.status == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
