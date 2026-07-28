"""旧版 Word `.doc` 产品条款解析器。"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import List

from ..models import AuditDocument, DocumentParseError
from .docx_parser import DocxParser


class LegacyDocParser:
    """将二进制 `.doc` 临时转换为 `.docx` 后复用现有结构解析器。"""

    @staticmethod
    def supported_extensions() -> List[str]:
        return [".doc"]

    def parse(self, file_path: str) -> AuditDocument:
        source = Path(file_path)
        if not source.exists():
            raise DocumentParseError("文件不存在", file_path)

        converter = shutil.which("soffice") or shutil.which("libreoffice")
        if converter is None:
            raise DocumentParseError(
                "旧版 Word 文件转换工具不可用",
                file_path,
                "请安装 LibreOffice 后重试",
            )

        with tempfile.TemporaryDirectory(prefix="actuary-doc-") as output_dir:
            profile_dir = Path(output_dir) / "libreoffice-profile"
            profile_dir.mkdir()
            try:
                completed = subprocess.run(
                    [
                        converter,
                        f"-env:UserInstallation={profile_dir.as_uri()}",
                        "--headless",
                        "--convert-to",
                        "docx",
                        "--outdir",
                        output_dir,
                        str(source),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DocumentParseError("旧版 Word 文件转换失败", file_path, str(exc)) from exc

            converted = Path(output_dir) / f"{source.stem}.docx"
            if completed.returncode != 0 or not converted.exists():
                detail = (completed.stderr or completed.stdout or "未生成 docx 文件").strip()
                raise DocumentParseError("旧版 Word 文件转换失败", file_path, detail)

            parsed = DocxParser().parse(str(converted))
            has_audit_content = any(
                (
                    parsed.clauses,
                    parsed.tables,
                    parsed.notices,
                    parsed.health_disclosures,
                    parsed.exclusions,
                    parsed.rider_clauses,
                )
            )
            if not has_audit_content and not parsed.product_name:
                raise DocumentParseError(
                    "旧版 Word 文件转换后未识别到产品条款内容",
                    file_path,
                )
            return replace(
                parsed,
                file_name=source.name,
                file_type=".doc",
                warnings=[*parsed.warnings, "旧版 .doc 已临时转换为 .docx 后解析"],
            )
