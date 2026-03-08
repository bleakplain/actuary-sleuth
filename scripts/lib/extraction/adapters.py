#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
格式适配器

将不同格式的保险产品文档转换为统一的中间表示。
"""
import re
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


logger = logging.getLogger(__name__)


class BaseFormatAdapter(ABC):
    """格式适配器基类"""

    @abstractmethod
    def extract_clauses(self, document: str) -> List[Dict[str, Any]]:
        """
        提取条款列表

        Args:
            document: 文档内容

        Returns:
            条款列表，每个条款包含 text 和 reference
        """
        pass

    @abstractmethod
    def extract_product_info(self, document: str) -> Dict[str, Any]:
        """
        提取产品信息

        Args:
            document: 文档内容

        Returns:
            产品信息字典
        """
        pass

    @abstractmethod
    def get_suggested_chunker(self) -> str:
        """
        返回建议的分块策略名称

        Returns:
            分块器名称：table_splitter, section_splitter, semantic_splitter
        """
        pass


class HTMLTableAdapter(BaseFormatAdapter):
    """HTML 表格格式适配器（适用于 feishu2md 转换的表格型条款）"""

    def extract_clauses(self, document: str) -> List[Dict[str, Any]]:
        """从 HTML 表格提取条款"""
        rows = re.findall(r'<tr>(.*?)</tr>', document, re.DOTALL)
        if not rows:
            logger.debug("HTML表格: 未找到<tr>标签")
            return []

        def _strip_html(text: str) -> str:
            """去除HTML标签和加粗标记"""
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'\*\*([^*]*)\*\*', r'\1', text)
            return text.strip()

        current_ref = None
        current_texts = []
        clauses = []

        for row in rows:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(tds) == 2:
                ref = _strip_html(tds[0])
                body = _strip_html(tds[1])
                # 有编号的行：开始新条款
                if re.match(r'^\d[\d.]*$', ref):
                    if current_ref and current_texts:
                        full_text = '\n'.join(current_texts)
                        if len(full_text) > 10:
                            clauses.append({'reference': current_ref, 'text': full_text})
                    current_ref = ref
                    current_texts = [body] if body else []
                # 无编号的延续行
                elif not ref and body and current_ref is not None:
                    current_texts.append(body)
            elif len(tds) == 3:
                # 3-td 行：中间是子项内容（如疾病定义）
                body = _strip_html(tds[1])
                if body and current_ref is not None:
                    current_texts.append(body)

        # 保存最后一条
        if current_ref and current_texts:
            full_text = '\n'.join(current_texts)
            if len(full_text) > 10:
                clauses.append({'reference': current_ref, 'text': full_text})

        logger.debug(f"HTML表格: 提取到 {len(clauses)} 条条款")
        return clauses

    def extract_product_info(self, document: str) -> Dict[str, Any]:
        """从 HTML 表格提取产品信息（委托给规则提取器）"""
        from lib.hybrid_extractor import RuleExtractor
        extractor = RuleExtractor()
        result = extractor.extract(document)
        return result.data

    def get_suggested_chunker(self) -> str:
        return 'table_splitter'


class MarkdownAdapter(BaseFormatAdapter):
    """Markdown 格式适配器"""

    def extract_clauses(self, document: str) -> List[Dict[str, Any]]:
        """从 Markdown 提取条款"""
        clauses = []
        lines = document.split('\n')
        current_clause = []
        current_ref = ""

        # 支持多种条款模式
        clause_patterns = [
            r'^第([一二三四五六七八九十百千]+|\d+)[条章节]\s*(.+)?',
            r'^#+\s*(.+)',  # Markdown 标题
            r'^\s*\d+[\.\、]\s*(.+)',  # 数字列表
        ]

        for line in lines:
            matched = False
            for pattern in clause_patterns:
                match = re.match(pattern, line)
                if match:
                    # 保存上一条
                    if current_clause:
                        text = '\n'.join(current_clause).strip()
                        if len(text) > 10:
                            clauses.append({'text': text, 'reference': current_ref})
                    # 开始新条款
                    current_ref = match.group(1) if match.groups() else str(len(clauses) + 1)
                    current_clause = [line]
                    matched = True
                    break

            if not matched and current_clause:
                current_clause.append(line)

        # 保存最后一条
        if current_clause:
            text = '\n'.join(current_clause).strip()
            if len(text) > 10:
                clauses.append({'text': text, 'reference': current_ref})

        logger.debug(f"Markdown: 提取到 {len(clauses)} 条条款")
        return clauses

    def extract_product_info(self, document: str) -> Dict[str, Any]:
        """从 Markdown 提取产品信息（委托给规则提取器）"""
        from lib.hybrid_extractor import RuleExtractor
        extractor = RuleExtractor()
        result = extractor.extract(document)
        return result.data

    def get_suggested_chunker(self) -> str:
        return 'section_splitter'


class PlainTextAdapter(BaseFormatAdapter):
    """纯文本格式适配器"""

    def extract_clauses(self, document: str) -> List[Dict[str, Any]]:
        """从纯文本提取条款（按段落分割）"""
        # 先尝试按双换行分割
        paragraphs = re.split(r'\n\s*\n', document)
        clauses = []

        for i, para in enumerate(paragraphs):
            para = para.strip()
            if len(para) > 20:  # 纯文本段落阈值更高
                clauses.append({
                    'text': para,
                    'reference': f"段落{i+1}"
                })

        logger.debug(f"纯文本: 提取到 {len(clauses)} 条条款")
        return clauses

    def extract_product_info(self, document: str) -> Dict[str, Any]:
        """纯文本产品信息提取（仅用规则）"""
        from lib.hybrid_extractor import RuleExtractor
        extractor = RuleExtractor()
        result = extractor.extract(document)
        return result.data

    def get_suggested_chunker(self) -> str:
        return 'semantic_splitter'


class MixedAdapter(BaseFormatAdapter):
    """混合格式适配器（组合多种适配器）"""

    def __init__(self):
        self._sub_adapters = [
            HTMLTableAdapter(),
            MarkdownAdapter(),
            PlainTextAdapter(),
        ]

    def extract_clauses(self, document: str) -> List[Dict[str, Any]]:
        """尝试所有适配器，合并结果"""
        all_clauses = []
        seen_references = set()

        for adapter in self._sub_adapters:
            try:
                clauses = adapter.extract_clauses(document)
                # 去重（按 reference）
                for clause in clauses:
                    ref = clause.get('reference', '')
                    if ref and ref not in seen_references:
                        seen_references.add(ref)
                        all_clauses.append(clause)
            except Exception as e:
                logger.warning(f"MixedAdapter子适配器失败: {e}")

        return all_clauses

    def extract_product_info(self, document: str) -> Dict[str, Any]:
        """合并各适配器的产品信息"""
        merged = {}
        for adapter in self._sub_adapters:
            try:
                info = adapter.extract_product_info(document)
                # 后来的适配器补充缺失字段
                for k, v in info.items():
                    if v and (k not in merged or not merged[k]):
                        merged[k] = v
            except Exception as e:
                logger.warning(f"MixedAdapter产品信息提取失败: {e}")
        return merged

    def get_suggested_chunker(self) -> str:
        return 'section_splitter'


# 适配器工厂
_ADAPTERS = {
    'HTML_TABLE': HTMLTableAdapter(),
    'MARKDOWN': MarkdownAdapter(),
    'PLAIN_TEXT': PlainTextAdapter(),
    'MIXED': MixedAdapter(),
}


def get_adapter(profile) -> BaseFormatAdapter:
    """
    根据格式特征获取适配器

    Args:
        profile: FormatProfile 实例

    Returns:
        BaseFormatAdapter: 适配器实例
    """
    adapter = _ADAPTERS.get(profile.primary_type)
    if adapter is None:
        logger.warning(f"未找到格式 {profile.primary_type} 的适配器，使用纯文本适配器")
        return PlainTextAdapter()
    return adapter
