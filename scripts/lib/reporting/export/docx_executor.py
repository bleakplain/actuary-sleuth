#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docx执行器

负责执行Node.js生成docx文件和验证
"""
import os
import subprocess
from pathlib import Path
from typing import Dict, Any

from lib.common.exceptions import ExportException
from lib.common.logger import get_logger

logger = get_logger('docx_executor')


class _DocxExecutor:
    """Docx执行器 - 负责执行Node.js和验证"""

    DOCX_SKILL_PATH = "/root/.agents/skills/docx"
    DEFAULT_EXECUTION_TIMEOUT = 30
    DEFAULT_VALIDATION_TIMEOUT = 30

    def __init__(
        self,
        execution_timeout: int | None = None,
        validation_timeout: int | None = None
    ):
        self._execution_timeout = execution_timeout or self.DEFAULT_EXECUTION_TIMEOUT
        self._validation_timeout = validation_timeout or self.DEFAULT_VALIDATION_TIMEOUT
        self._docx_skill_path = Path(self.DOCX_SKILL_PATH)

    def write_temp_js(self, js_code: str, output_dir: str, title: str) -> str:
        js_file = os.path.join(output_dir, f"{title}.js")
        logger.debug(f"写入临时JavaScript文件: {js_file}")
        try:
            with open(js_file, 'w', encoding='utf-8') as f:
                f.write(js_code)
            return js_file
        except Exception:
            if os.path.exists(js_file):
                os.remove(js_file)
            raise

    def execute_docx_generation(self, js_file: str, output_dir: str, title: str) -> str:
        docx_file = os.path.join(output_dir, f"{title}.docx")

        try:
            env = os.environ.copy()
            env['NODE_PATH'] = '/usr/lib/node_modules'

            logger.debug(f"执行 Node.js 生成文档: {js_file}")
            result = subprocess.run(
                ['node', js_file],
                capture_output=True,
                text=True,
                timeout=self._execution_timeout,
                check=True,
                env=env
            )

            logger.debug(f"Node.js 输出: {result.stdout.strip()}")

            if not os.path.exists(docx_file):
                raise ExportException(f"文档生成失败，文件不存在: {docx_file}")

            return docx_file

        except subprocess.CalledProcessError as e:
            raise ExportException(f"Node.js执行失败: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise ExportException(f"文档生成超时（超过{self._execution_timeout}秒）")
        except (OSError, IOError) as e:
            raise ExportException(f"文档生成异常: {str(e)}")

    def validate_docx(self, docx_file: str) -> Dict[str, Any]:
        try:
            validate_script = self._docx_skill_path / "scripts/office/validate.py"

            result = subprocess.run(
                [
                    'python3',
                    str(validate_script),
                    docx_file,
                    '--auto-repair'
                ],
                capture_output=True,
                text=True,
                timeout=self._validation_timeout,
                env={
                    'PYTHONPATH': str(self._docx_skill_path / "scripts/office")
                }
            )

            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr
            }

        except (subprocess.TimeoutExpired, OSError, IOError) as e:
            logger.error(f"文档验证失败: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
