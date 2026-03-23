#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docx文档生成器（内部实现）

_DocxGenerator类：负责将EvaluationContext转换为Word文档

职责：
- 将EvaluationContext转换为docx-js JavaScript代码
- 调用Node.js执行生成.docx文件
- 可选：使用docx skill验证生成的文档

注意：此模块为内部实现，不直接对外暴露
"""
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional

from lib.common.exceptions import ExportException
from lib.common.logger import get_logger
from .result import GenerationResult
from .validation import validate_evaluation_context, validate_title
from .docx_templates import _DocxTemplateGenerator
from .docx_executor import _DocxExecutor

logger = get_logger('docx_generator')


class _DocxGenerator:
    """Docx文档生成器（内部实现）"""

    DEFAULT_EXECUTION_TIMEOUT = 30
    DEFAULT_VALIDATION_TIMEOUT = 30

    def __init__(
        self,
        output_dir: Optional[str] = None,
        validate: bool = False,
        execution_timeout: Optional[int] = None,
        validation_timeout: Optional[int] = None
    ):
        self._output_dir = output_dir or tempfile.gettempdir()
        self._validate = validate
        self._execution_timeout = execution_timeout or self.DEFAULT_EXECUTION_TIMEOUT
        self._validation_timeout = validation_timeout or self.DEFAULT_VALIDATION_TIMEOUT

        self._template_gen = _DocxTemplateGenerator(self._output_dir)
        self._executor = _DocxExecutor(execution_timeout, validation_timeout)

    def generate(
        self,
        context: 'EvaluationContext',
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        try:
            validate_evaluation_context(context)

            logger.info(f"开始生成文档", product=context.product.name)

            if title is None:
                timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
                product_name = context.product.name or "未命名产品"
                title = f"{product_name}_审核报告_{timestamp}"

            title = validate_title(title)

            logger.debug("生成 docx-js 代码")
            js_code = self._template_gen.generate_docx_js_code(context, title)

            js_file = self._executor.write_temp_js(js_code, self._output_dir, title)

            logger.debug("执行 Node.js 生成文档")
            docx_file = self._executor.execute_docx_generation(js_file, self._output_dir, title)

            validation_result = None
            if self._validate:
                logger.debug("验证文档")
                validation_result = self._executor.validate_docx(docx_file)

            import os
            file_size = os.path.getsize(docx_file)

            return {
                'success': True,
                'file_path': docx_file,
                'file_size': file_size,
                'title': title,
                'validation_result': validation_result
            }

        except (ValueError, TypeError, OSError, ExportException) as e:
            logger.error(f"文档生成失败: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
