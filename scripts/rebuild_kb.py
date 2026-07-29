#!/usr/bin/env python3
"""安全重建、验收、切换或恢复一个法规知识库版本。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from lib.rag_engine.kb_identity import sha256_file
from lib.rag_engine.kb_rebuild import (
    KnowledgeBaseRebuildError,
    StagingRequest,
    default_stage_dir,
    promote_staged_knowledge_base,
    restore_knowledge_base_backup,
    stage_knowledge_base,
    validate_staged_build,
)


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--kb-root", type=Path, required=True)
    parser.add_argument("--references-dir", type=Path, required=True)
    parser.add_argument("--version", default="v5")


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 staging 安全重建法规知识库",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage = subparsers.add_parser("stage", help="只构建和验收 staging")
    _add_common_paths(stage)
    stage.add_argument("--excel", type=Path, required=True)
    stage.add_argument("--stage-dir", type=Path)
    stage.add_argument("--expected-documents", type=int)
    stage.add_argument("--expected-chunks", type=int)

    validate = subparsers.add_parser("validate", help="重新验收 staging")
    validate.add_argument("--stage-dir", type=Path, required=True)
    validate.add_argument("--version", default="v5")

    promote = subparsers.add_parser(
        "promote",
        help="服务停止后切换已通过验收的 staging",
    )
    _add_common_paths(promote)
    promote.add_argument("--stage-dir", type=Path, required=True)
    promote.add_argument("--identity-path", type=Path, required=True)
    promote.add_argument("--backup-root", type=Path)
    promote.add_argument(
        "--expected-live-manifest-sha256",
        required=True,
        help="防止审核后生产基线发生变化",
    )
    promote.add_argument(
        "--confirm-service-stopped",
        action="store_true",
        help="确认 API 和 worker 已全部停止",
    )

    rollback = subparsers.add_parser(
        "rollback",
        help="服务停止后恢复 promote 生成的旧版本备份",
    )
    _add_common_paths(rollback)
    rollback.add_argument("--backup-dir", type=Path, required=True)
    rollback.add_argument("--identity-path", type=Path, required=True)
    rollback.add_argument(
        "--confirm-service-stopped",
        action="store_true",
        help="确认 API 和 worker 已全部停止",
    )

    fingerprint = subparsers.add_parser(
        "fingerprint",
        help="只读输出当前构建清单 SHA-256",
    )
    fingerprint.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parse_args(arguments)
    try:
        if args.command == "stage":
            stage_dir = args.stage_dir or default_stage_dir(
                args.kb_root,
                args.version,
            )
            stage_result = stage_knowledge_base(StagingRequest(
                source_excel=args.excel,
                production_references_dir=args.references_dir,
                kb_root=args.kb_root,
                stage_dir=stage_dir,
                version=args.version,
                expected_documents=args.expected_documents,
                expected_chunks=args.expected_chunks,
            ))
            print(json.dumps(
                stage_result.to_dict(),
                ensure_ascii=False,
                indent=2,
            ))
            return 0 if stage_result.validation.valid else 2
        if args.command == "validate":
            validation_result = validate_staged_build(
                args.stage_dir,
                args.version,
            )
            print(json.dumps(
                validation_result.to_dict(),
                ensure_ascii=False,
                indent=2,
            ))
            return 0 if validation_result.validation.valid else 2
        if args.command == "promote":
            promotion_result = promote_staged_knowledge_base(
                stage_dir=args.stage_dir,
                kb_root=args.kb_root,
                production_references_dir=args.references_dir,
                identity_path=args.identity_path,
                expected_live_manifest_sha256=(
                    args.expected_live_manifest_sha256
                ),
                version=args.version,
                backup_root=args.backup_root,
                service_stopped=args.confirm_service_stopped,
            )
            print(json.dumps(
                promotion_result.to_dict(),
                ensure_ascii=False,
                indent=2,
            ))
            return 0
        if args.command == "rollback":
            restore_result = restore_knowledge_base_backup(
                backup_dir=args.backup_dir,
                kb_root=args.kb_root,
                production_references_dir=args.references_dir,
                identity_path=args.identity_path,
                version=args.version,
                service_stopped=args.confirm_service_stopped,
            )
            print(json.dumps(
                restore_result.to_dict(),
                ensure_ascii=False,
                indent=2,
            ))
            return 0
        print(sha256_file(args.manifest))
        return 0
    except KnowledgeBaseRebuildError as exc:
        print(json.dumps(
            {"status": "failed", "error": str(exc)},
            ensure_ascii=False,
            indent=2,
        ))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
