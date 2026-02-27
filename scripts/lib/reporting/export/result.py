#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出结果类

统一的导出结果封装，替代原有的字典返回方式
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, TypeVar
from datetime import datetime

T = TypeVar('T')


@dataclass
class ExportResult:
    """
    导出结果类

    统一的导出结果封装，提供类型安全和一致的处理方式
    """
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def success_with(cls, data: T) -> 'ExportResult[T]':
        """创建成功结果"""
        return cls(success=True, data=data)

    @classmethod
    def failure_with(cls, error: str) -> 'ExportResult':
        """创建失败结果"""
        return cls(success=False, error=error)

    def is_success(self) -> bool:
        """是否成功"""
        return self.success

    def get_error(self) -> str:
        """获取错误信息"""
        return self.error or "未知错误"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（向后兼容）"""
        result = {
            'success': self.success,
            'timestamp': self.timestamp
        }
        if self.success:
            result['data'] = self.data
        else:
            result['error'] = self.error
        return result


@dataclass
class GenerationResult(ExportResult):
    """
    文档生成结果

    扩展自 ExportResult，添加生成特定的字段
    """
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    title: Optional[str] = None
    validation_result: Optional[Dict[str, Any]] = None

    @classmethod
    def success_with_file(cls, file_path: str, file_size: int, title: str) -> 'GenerationResult':
        """创建成功的生成结果"""
        return cls(
            success=True,
            data={'file_path': file_path, 'file_size': file_size, 'title': title},
            file_path=file_path,
            file_size=file_size,
            title=title
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = super().to_dict()
        if self.success:
            result['file_path'] = self.file_path
            result['file_size'] = self.file_size
            result['title'] = self.title
            result['generation_result'] = result.get('data')
        if self.validation_result:
            result['validation_result'] = self.validation_result
        return result


@dataclass
class PushResult(ExportResult):
    """
    文档推送结果

    扩展自 ExportResult，添加推送特定的字段
    """
    message_id: Optional[str] = None
    group_id: Optional[str] = None
    output: Optional[str] = None

    @classmethod
    def success_with_message(cls, message_id: str, group_id: str, output: str) -> 'PushResult':
        """创建成功的推送结果"""
        return cls(
            success=True,
            data={'message_id': message_id, 'group_id': group_id},
            message_id=message_id,
            group_id=group_id,
            output=output
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = super().to_dict()
        if self.success:
            result['message_id'] = self.message_id
            result['group_id'] = self.group_id
            result['push_result'] = result.get('data')
        return result
