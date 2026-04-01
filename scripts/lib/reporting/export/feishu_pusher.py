#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书推送器（内部实现）

_FeishuPusher类：通过OpenClaw推送Docx文档到飞书群组

功能：
- 使用OpenClaw message tool推送docx文件到飞书群组
- 处理推送结果和错误
- 支持文本消息推送（不附带文件）

注意：此模块为内部实现，不直接对外暴露
"""
import os
import subprocess
import re
from typing import Dict, Any, Optional

from lib.common.exceptions import ExportException
from lib.config import get_config
from lib.common.logger import get_logger
from .result import PushResult
from .validation import validate_file_path, sanitize_message, validate_group_id


logger = get_logger('feishu_pusher')


class _FeishuPusher:
    """
    飞书推送器（内部实现）

    负责通过OpenClaw推送文档到飞书群组
    """

    # OpenClaw配置（从配置读取）
    DEFAULT_OPENCLAW_BIN = "/usr/bin/openclaw"

    # 默认超时时间（秒）
    DEFAULT_PUSH_TIMEOUT = 30

    # 消息长度限制
    MAX_MESSAGE_LENGTH = 100
    MAX_TITLE_LENGTH = 40

    def __init__(
        self,
        openclaw_bin: Optional[str] = None,
        target_group_id: Optional[str] = None,
        timeout: Optional[int] = None,
        allowed_output_dir: Optional[str] = None
    ):
        config = get_config()
        self._openclaw_bin = openclaw_bin or config.get('openclaw.bin', self.DEFAULT_OPENCLAW_BIN)
        self._timeout = timeout or self.DEFAULT_PUSH_TIMEOUT
        self._allowed_output_dir = allowed_output_dir

        raw_group_id = target_group_id or config.feishu_group_id
        if raw_group_id:
            self._target_group_id = validate_group_id(raw_group_id)
        else:
            raise ExportException("未配置飞书目标群组ID。请在配置文件中设置 feishu.target_group_id 或通过环境变量 FEISHU_TARGET_GROUP_ID 指定")

        self._validate_openclaw_binary()

        logger.debug(f"初始化推送器: group={self._target_group_id}, openclaw={self._openclaw_bin}, timeout={self._timeout}")

    def _validate_openclaw_binary(self) -> None:
        if not os.path.exists(self._openclaw_bin):
            raise ExportException(f"OpenClaw 二进制文件不存在: {self._openclaw_bin}")

        if not os.access(self._openclaw_bin, os.X_OK):
            raise ExportException(f"OpenClaw 二进制文件不可执行: {self._openclaw_bin}")

    def _execute_openclaw_command(self, command_args: list) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                command_args,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
                shell=False
            )

            output = result.stdout
            message_id = self._extract_message_id(output)

            return {
                'success': True,
                'message_id': message_id,
                'group_id': self._target_group_id,
                'output': output
            }

        except subprocess.CalledProcessError as e:
            error_msg = self._parse_error_message(e.stderr)
            logger.error(f"推送失败: {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }
        except subprocess.TimeoutExpired:
            logger.error(f"推送超时（超过{self._timeout}秒）")
            return {
                'success': False,
                'error': f'推送超时（超过{self._timeout}秒）'
            }
        except Exception as e:
            logger.error("推送异常", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def _parse_error_message(self, stderr: str) -> str:
        """
        解析错误消息，提供更友好的错误描述

        Args:
            stderr: 标准错误输出

        Returns:
            str: 解析后的错误消息
        """
        if "No such file" in stderr or "cannot find" in stderr.lower():
            return "文件不存在或无法访问"
        elif "Permission denied" in stderr:
            return "权限不足，无法推送文件"
        elif "Network" in stderr or "connection" in stderr.lower():
            return "网络连接失败"
        elif "target" in stderr.lower() or "group" in stderr.lower():
            return "目标群组ID无效或无权限"
        else:
            return f"推送失败: {stderr}"

    def push(
        self,
        file_path: str,
        title: str,
        message: Optional[str] = None
    ) -> Dict[str, Any]:
        validated_path = validate_file_path(file_path, allowed_dir=self._allowed_output_dir)

        logger.info(f"推送文档到飞书", file=validated_path, group=self._target_group_id)

        if message is None:
            message = self._build_message(title)
        else:
            message = sanitize_message(message)

        command_args = [
            self._openclaw_bin,
            'message', 'send',
            '--channel', 'feishu',
            '--target', self._target_group_id,
            '--media', validated_path,
            '--message', message
        ]

        return self._execute_openclaw_command(command_args)

    def push_text(
        self,
        message: str
    ) -> Dict[str, Any]:
        logger.debug(f"推送文本消息")

        cleaned_message = sanitize_message(message)

        command_args = [
            self._openclaw_bin,
            'message', 'send',
            '--channel', 'feishu',
            '--target', self._target_group_id,
            '--message', cleaned_message
        ]

        return self._execute_openclaw_command(command_args)

    def _build_message(self, title: str) -> str:
        """构建推送消息"""
        prefix = "📊 "
        # 检查总长度是否超过限制
        if len(prefix) + len(title) > self.MAX_MESSAGE_LENGTH:
            # 计算可保留的标题长度（预留prefix和"..."的空间）
            max_title_len = self.MAX_TITLE_LENGTH - len(prefix) - 3
            return f"{prefix}{title[:max_title_len]}..."
        return f"{prefix}{title}"

    def _extract_message_id(self, output: str) -> Optional[str]:
        """
        从输出中提取消息ID（使用正则表达式验证）

        Args:
            output: OpenClaw命令输出

        Returns:
            Optional[str]: 提取的消息ID，如果未找到则返回None
        """
        # 匹配 "Message ID: xxx" 格式，ID应包含字母数字、下划线、连字符
        pattern = r'Message ID:\s*([a-zA-Z0-9_-]{10,})'
        match = re.search(pattern, output)
        return match.group(1) if match else None


# 便捷函数
def export_to_feishu(
    file_path: str,
    title: str,
    message: Optional[str] = None
) -> Dict[str, Any]:
    """
    推送文档到飞书（便捷函数）

    Args:
        file_path: 文档文件路径
        title: 文档标题
        message: 伴随消息（可选）

    Returns:
        dict: 推送结果
    """
    pusher = _FeishuPusher()
    return pusher.push(file_path, title, message)
