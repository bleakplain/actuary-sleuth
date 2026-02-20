#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书文档导出器

FeishuExporter类：负责飞书在线文档创建和内容导出功能

功能：
- 创建飞书在线文档
- 写入富文本块格式内容
- 返回文档URL
"""
import sys
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional

from lib.config import get_config
from lib.exceptions import FeishuAPIException, MissingConfigurationException


# 飞书 API 配置
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


class FeishuExporter:
    """
    飞书文档导出器

    负责将报告内容导出为飞书在线文档
    """

    def __init__(self, app_id: Optional[str] = None, app_secret: Optional[str] = None):
        """
        初始化飞书导出器

        Args:
            app_id: 飞书应用ID，如果为None则从配置读取
            app_secret: 飞书应用密钥，如果为None则从配置读取
        """
        self._app_id = app_id
        self._app_secret = app_secret
        self._access_token: Optional[str] = None

    def get_app_id(self) -> Optional[str]:
        """获取飞书应用ID"""
        if self._app_id:
            return self._app_id

        config = get_config()
        return config.feishu.app_id

    def get_app_secret(self) -> Optional[str]:
        """获取飞书应用密钥"""
        if self._app_secret:
            return self._app_secret

        config = get_config()
        return config.feishu.app_secret

    def get_access_token(self) -> str:
        """
        获取飞书访问令牌

        Returns:
            str: 访问令牌

        Raises:
            MissingConfigurationException: 缺少飞书配置
            FeishuAPIException: 获取令牌失败
            requests.RequestException: 网络请求失败
        """
        if self._access_token:
            return self._access_token

        app_id = self.get_app_id()
        app_secret = self.get_app_secret()

        if not app_id or not app_secret:
            raise MissingConfigurationException("feishu.app_id 或 feishu.app_secret")

        url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
        payload = {"app_id": app_id, "app_secret": app_secret}

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0:
                self._access_token = data.get("tenant_access_token")
                return self._access_token
            else:
                raise FeishuAPIException(f"获取令牌失败: {data.get('msg')}")
        except requests.RequestException as e:
            raise FeishuAPIException(f"网络请求失败: {str(e)}")

    def create_document(self, title: str, blocks: List[Dict[str, Any]]) -> str:
        """
        创建飞书在线文档

        Args:
            title: 文档标题
            blocks: 飞书文档块列表

        Returns:
            str: 文档URL

        Raises:
            FeishuAPIException: 创建文档失败
            requests.RequestException: 网络请求失败
        """
        access_token = self.get_access_token()

        # 创建文档
        create_url = f"{FEISHU_API_BASE}/docx/v1/documents"
        create_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        create_payload = {
            "title": title,
            "folder_token": ""  # 空字符串表示根目录
        }

        try:
            create_response = requests.post(create_url, headers=create_headers, json=create_payload, timeout=10)

            # 打印调试信息
            print(f"飞书 API 响应状态: {create_response.status_code}", file=sys.stderr)
            if create_response.status_code != 200:
                print(f"飞书 API 响应内容: {create_response.text}", file=sys.stderr)

            create_response.raise_for_status()
            create_data = create_response.json()

            if create_data.get("code") != 0:
                raise FeishuAPIException(f"创建文档失败: {create_data.get('msg')}")

            document_id = create_data.get("data", {}).get("document", {}).get("document_id")

            if not document_id:
                raise FeishuAPIException("未能获取文档 ID")

        except requests.RequestException as e:
            raise FeishuAPIException(f"创建文档网络请求失败: {str(e)}")

        # 对于新创建的文档，直接使用 document_id 作为 page_block_id
        page_block_id = document_id
        print(f"📝 使用文档ID作为页面块 ID: {page_block_id}", file=sys.stderr)

        # 写入文档内容
        if blocks:
            self._write_document_content(access_token, document_id, page_block_id, blocks)

        # 返回文档链接
        doc_url = f"https://feishu.cn/docx/{document_id}"
        return doc_url

    def _write_document_content(
        self,
        access_token: str,
        document_id: str,
        page_block_id: str,
        blocks: List[Dict[str, Any]]
    ) -> None:
        """
        写入文档内容

        Args:
            access_token: 访问令牌
            document_id: 文档ID
            page_block_id: 页面块ID
            blocks: 文档块列表

        Raises:
            Exception: 写入内容失败
        """
        print(f"准备写入 {len(blocks)} 个块", file=sys.stderr)

        # 验证块数据结构
        print(f"验证 {len(blocks)} 个块的数据结构...", file=sys.stderr)
        for idx, block in enumerate(blocks[:5]):  # 检查前5个块
            if not isinstance(block, dict):
                print(f"块 {idx+1} 不是字典类型: {type(block)}", file=sys.stderr)
            if 'block_type' not in block:
                print(f"块 {idx+1} 缺少 block_type 字段", file=sys.stderr)

        # 批量写入文档内容（每次最多 50 个块，飞书API限制）
        batch_size = 50
        for i in range(0, len(blocks), batch_size):
            chunk = blocks[i:i+batch_size]
            print(f"准备写入块 {i+1}-{min(i+batch_size, len(blocks))}，共 {len(chunk)} 个", file=sys.stderr)

            update_url = f"{FEISHU_API_BASE}/docx/v1/documents/{document_id}/blocks/{page_block_id}/children"

            update_payload = {
                "children": chunk
            }

            print(f"请求数据: children 数量 = {len(chunk)}, 第一个块类型 = {chunk[0].get('block_type') if chunk else 'empty'}", file=sys.stderr)

            print(f"写入块 {i+1}-{min(i+batch_size, len(blocks))}", file=sys.stderr)

            update_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            update_response = requests.post(update_url, headers=update_headers, json=update_payload, timeout=30)
            print(f"块写入响应: {update_response.status_code}", file=sys.stderr)

            if update_response.status_code != 200:
                print(f"更新文档失败: {update_response.text}", file=sys.stderr)
                raise FeishuAPIException(f"写入内容失败: HTTP {update_response.status_code} - {update_response.text}")
            else:
                update_data = update_response.json()
                code = update_data.get('code')
                print(f"块写入结果 code: {code}", file=sys.stderr)
                if code != 0:
                    msg = update_data.get('msg', 'Unknown error')
                    raise FeishuAPIException(f"写入内容失败: {msg}")

    def export(
        self,
        blocks: List[Dict[str, Any]],
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        导出报告到飞书文档

        Args:
            blocks: 飞书文档块列表
            title: 文档标题（可选）

        Returns:
            dict: 包含导出结果的字典
                - success: 是否成功
                - document_url: 文档URL（成功时）
                - title: 文档标题（成功时）
                - export_time: 导出时间（成功时）
                - error: 错误信息（失败时）
        """
        # 设置默认标题
        if title is None:
            title = f"审核报告-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        try:
            # 创建文档
            doc_url = self.create_document(title, blocks)

            return {
                'success': True,
                'document_url': doc_url,
                'title': title,
                'export_time': datetime.now().isoformat()
            }

        except (FeishuAPIException, MissingConfigurationException, requests.RequestException) as e:
            return {
                'success': False,
                'error': str(e)
            }

    def create_text_block(self, text: str) -> Dict[str, Any]:
        """创建文本块"""
        return {
            "block_type": 2,
            "text": {
                "elements": [{
                    "text_run": {
                        "content": text,
                        "style": {}
                    }
                }]
            }
        }

    def create_bold_text_block(self, text: str) -> Dict[str, Any]:
        """创建粗体文本块"""
        return {
            "block_type": 2,
            "text": {
                "elements": [{
                    "text_run": {
                        "content": text,
                        "style": {
                            "bold": True
                        }
                    }
                }]
            }
        }

    def create_heading_2_block(self, text: str) -> Dict[str, Any]:
        """创建二级标题块"""
        return {
            "block_type": 2,
            "text": {
                "elements": [{
                    "text_run": {
                        "content": text,
                        "style": {
                            "bold": True,
                            "text_size": "large"
                        }
                    }
                }]
            }
        }

    def create_table_blocks(self, table_data: List[List[str]]) -> List[Dict[str, Any]]:
        """
        创建表格块（使用文本块模拟）

        Args:
            table_data: 表格数据，二维数组

        Returns:
            list: 文档块列表
        """
        blocks = []

        for row_idx, row in enumerate(table_data):
            is_header = (row_idx == 0)

            # 对齐列（使用固定宽度）
            col_widths = [8, 20, 15, 15, 20]
            row_parts = []
            for col_idx, cell in enumerate(row):
                if col_idx < len(col_widths):
                    width = col_widths[col_idx]
                    # 左对齐或右对齐
                    if is_header or col_idx in [0]:
                        cell_text = f"{cell:<{width}}"
                    else:
                        cell_text = f"{cell:>{width}}"
                    row_parts.append(cell_text)

            row_text = " | ".join(row_parts)

            blocks.append({
                "block_type": 2,
                "text": {
                    "elements": [{
                        "text_run": {
                            "content": row_text,
                            "style": {
                                "bold": is_header,
                                "font_family": "Courier New"
                            }
                        }
                    }]
                }
            })

        return blocks


# 便捷函数，保持向后兼容
def export_to_feishu(blocks: List[Dict[str, Any]], title: str = None) -> Dict[str, Any]:
    """
    导出报告到飞书文档（便捷函数）

    Args:
        blocks: 飞书文档块列表
        title: 文档标题（可选）

    Returns:
        dict: 导出结果
    """
    exporter = FeishuExporter()
    return exporter.export(blocks, title)