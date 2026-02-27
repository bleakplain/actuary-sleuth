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
import subprocess
from typing import Dict, Any, Optional

from lib.exceptions import ExportException
from lib.config import get_config


class _FeishuPusher:
    """
    飞书推送器（内部实现）

    负责通过OpenClaw推送文档到飞书群组
    """

    # OpenClaw配置
    OPENCLAW_BIN = "/usr/bin/openclaw"

    def __init__(
        self,
        openclaw_bin: Optional[str] = None,
        target_group_id: Optional[str] = None
    ):
        """
        初始化飞书导出器

        Args:
            openclaw_bin: OpenClaw二进制文件路径
            target_group_id: 飞书目标群组ID（默认从配置读取）
        """
        self._openclaw_bin = openclaw_bin or self.OPENCLAW_BIN
        self._target_group_id = target_group_id or self._get_default_target_group()

    def _get_default_target_group(self) -> str:
        """从配置获取默认目标群组"""
        config = get_config()
        group_id = config.feishu.target_group_id

        if not group_id:
            raise ExportException(
                "未配置飞书目标群组ID。"
                "请在配置文件中设置 feishu.target_group_id "
                "或通过环境变量 FEISHU_TARGET_GROUP_ID 指定"
            )

        return group_id

    def push(
        self,
        file_path: str,
        title: str,
        message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        推送文档到飞书群组

        Args:
            file_path: 文档文件路径
            title: 文档标题
            message: 伴随消息（可选）

        Returns:
            dict: 包含推送结果的字典
                - success: 是否成功
                - message_id: 消息ID（成功时）
                - group_id: 群组ID
                - output: 命令输出
                - error: 错误信息（失败时）
        """
        try:
            if message is None:
                message = self._build_message(title)

            result = subprocess.run(
                [
                    self._openclaw_bin,
                    'message', 'send',
                    '--channel', 'feishu',
                    '--target', self._target_group_id,
                    '--media', file_path,
                    '--message', message
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=True
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
            return {
                'success': False,
                'error': e.stderr
            }
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': '推送超时'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def push_text(
        self,
        message: str
    ) -> Dict[str, Any]:
        """
        推送文本消息到飞书群组

        Args:
            message: 消息内容

        Returns:
            dict: 推送结果
        """
        try:
            result = subprocess.run(
                [
                    self._openclaw_bin,
                    'message', 'send',
                    '--channel', 'feishu',
                    '--target', self._target_group_id,
                    '--message', message
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=True
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
            return {
                'success': False,
                'error': e.stderr
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _build_message(self, title: str) -> str:
        """构建推送消息"""
        message = f"📊 {title}"
        if len(message) > 100:
            message = f"📊 {title[:40]}..."
        return message

    def _extract_message_id(self, output: str) -> Optional[str]:
        """从输出中提取消息ID"""
        if 'Message ID:' in output:
            for line in output.split('\n'):
                if 'Message ID:' in line:
                    try:
                        return line.split('Message ID:')[1].strip()
                    except (IndexError, AttributeError):
                        continue
        return None


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
    exporter = FeishuExporter()
    return exporter.push(file_path, title, message)
