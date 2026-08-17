#!/usr/bin/env python3
"""对冻结产品运行法规触发与动态条款证据 A/B/C 离线体量测试。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from lib.compliance.trigger_ab_measurement import (
    render_trigger_ab_markdown,
    run_trigger_ab_measurement,
)
from lib.config import get_kb_version_dir


_DEFAULT_MANIFEST = (
    Path(__file__).parent
    / "tests" / "fixtures" / "compliance_audit" / "v1" / "manifest.json"
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    kb_dir = Path(get_kb_version_dir())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-json", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    parser.add_argument("--products-dir", type=Path, default=kb_dir.parent / "products")
    parser.add_argument("--kb-dir", type=Path, default=kb_dir)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_trigger_ab_measurement(
        args.manifest,
        args.products_dir,
        args.kb_dir,
        args.pilot_json,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(
        render_trigger_ab_markdown(report),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
