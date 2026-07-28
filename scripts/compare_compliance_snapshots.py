#!/usr/bin/env python3
"""离线比较旧、新合规审核结果快照。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from lib.compliance.shadow_comparison import run_shadow_comparison


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="比较两个已序列化审核快照，不调用在线 LLM",
    )
    parser.add_argument("--old", required=True, type=Path, help="旧链路 JSON 快照")
    parser.add_argument("--new", required=True, type=Path, help="新链路 JSON 快照")
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="compliance-audit-v1 manifest",
    )
    parser.add_argument("--output-dir", required=True, type=Path, help="JSON/CSV 输出目录")
    parser.add_argument("--stem", help="可选输出文件名（不含扩展名）")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    report, files = run_shadow_comparison(
        args.old,
        args.new,
        args.manifest,
        args.output_dir,
        stem=args.stem,
    )
    print(
        json.dumps(
            {
                "json": str(files.json_path),
                "csv": str(files.csv_path),
                "cutover_blocked": report.cutover_blocked,
                "cutover_reasons": report.cutover_reasons,
            },
            ensure_ascii=False,
        )
    )
    return 2 if report.cutover_blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
