#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docx文档导出器 - 完整流程

DocxExporter类：整合文档生成和推送的完整导出流程

职责：
- 整合 _DocxGenerator（文档生成）和 _FeishuPusher（文档推送）
- 提供一站式导出接口
- 简化调用方的使用
"""
from typing import Dict, Any, Optional, TYPE_CHECKING
from pathlib import Path

from lib.exceptions import ExportException, ValidationException
from lib.logger import get_logger
from .docx_generator import _DocxGenerator
from .feishu_pusher import _FeishuPusher
from .result import ExportResult, GenerationResult, PushResult

if TYPE_CHECKING:
    from lib.reporting.model import EvaluationContext


logger = get_logger('docx_exporter')


class DocxExporter:
    """
    Docx文档导出器 - 完整流程

    整合文档生成和推送，提供一站式导出服务
    """

    def __init__(
        self,
        output_dir: Optional[str] = None,
        validate: bool = False,
        auto_push: bool = True,
        generator: Optional[_DocxGenerator] = None,
        pusher: Optional[_FeishuPusher] = None
    ):
        """
        初始化Docx文档导出器

        Args:
            output_dir: 输出目录
            validate: 是否验证生成的文档
            auto_push: 是否自动推送到飞书
            generator: 文档生成器（可选，用于依赖注入）
            pusher: 文档推送器（可选，用于依赖注入）
        """
        self._generator = generator or _DocxGenerator(output_dir=output_dir, validate=validate)
        self._pusher = pusher or (_FeishuPusher() if auto_push else None)
        self._auto_push = auto_push and self._pusher is not None

    def export(
        self,
        context: 'EvaluationContext',
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        导出Docx文档（完整流程）

        Args:
            context: 评估上下文对象
            title: 文档标题（可选）

        Returns:
            dict: 包含导出结果的字典
                - success: 是否成功
                - file_path: 本地文件路径
                - file_size: 文件大小
                - title: 文档标题
                - generation_result: 文档生成结果
                - push_result: 推送结果（auto_push=True时）
                - error: 错误信息（失败时）
        """
        try:
            # 1. 生成文档
            generation_result = self._generator.generate(context, title)

            if not generation_result['success']:
                error = generation_result.get('error', '文档生成失败')
                logger.error(f"文档生成失败: {error}")
                return ExportResult.failure_with(error).to_dict()

            # 2. 推送文档
            push_result = None
            if self._auto_push and self._pusher:
                file_path = generation_result['file_path']
                doc_title = generation_result['title']
                push_result = self._pusher.push(file_path, doc_title)

            # 3. 返回完整结果
            return {
                'success': True,
                'file_path': generation_result['file_path'],
                'file_size': generation_result['file_size'],
                'title': generation_result['title'],
                'generation_result': generation_result,
                'push_result': push_result
            }

        except ValidationException as e:
            logger.error(f"验证失败: {str(e)}", exc_info=True)
            return ExportResult.failure_with(f"验证失败: {str(e)}").to_dict()
        except ExportException as e:
            logger.error(f"导出失败: {str(e)}", exc_info=True)
            return ExportResult.failure_with(str(e)).to_dict()
        except Exception as e:
            logger.error(f"导出异常: {str(e)}", exc_info=True)
            return ExportResult.failure_with(f"导出异常: {str(e)}").to_dict()

    def generate_only(
        self,
        context: 'EvaluationContext',
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        仅生成文档（不推送）

        Args:
            context: 评估上下文对象
            title: 文档标题（可选）

        Returns:
            dict: 生成结果
        """
        try:
            return self._generator.generate(context, title)
        except Exception as e:
            logger.error(f"生成文档失败: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def push_only(
        self,
        file_path: str,
        title: str,
        message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        仅推送文档（不生成）

        Args:
            file_path: 文档文件路径
            title: 文档标题
            message: 伴随消息（可选）

        Returns:
            dict: 推送结果
        """
        if not self._pusher:
            logger.error("推送器未初始化")
            return {
                'success': False,
                'error': '推送器未初始化，请在初始化时设置 auto_push=True'
            }

        try:
            return self._pusher.push(file_path, title, message)
        except Exception as e:
            logger.error(f"推送文档失败: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}


# 便捷函数
def export_docx(
    context: 'EvaluationContext',
    title: Optional[str] = None,
    validate: bool = False,
    auto_push: bool = True
) -> Dict[str, Any]:
    """
    导出Docx文档（便捷函数）

    Args:
        context: 评估上下文对象
        title: 文档标题（可选）
        validate: 是否验证文档
        auto_push: 是否自动推送

    Returns:
        dict: 导出结果
    """
    exporter = DocxExporter(validate=validate, auto_push=auto_push)
    return exporter.export(context, title)
