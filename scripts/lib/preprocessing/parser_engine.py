#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专用解析器集合

对高度结构化的内容使用代码解析，替代 LLM，提升准确率和性能。
"""
import json
import logging
import re
from typing import Dict, List, Any, Optional

from .utils.dependency_checker import check_bs4
from .utils.json_parser import parse_llm_json_response

logger = logging.getLogger(__name__)


class PremiumTableParser:
    """费率表专用解析器"""

    _bs4_available: Optional[bool] = None
    _bs4_version: Optional[str] = None

    def __init__(self):
        """初始化费率表解析器"""
        # 预编译常用正则
        self.html_table_pattern = re.compile(r'<table[^>]*>(.*?)</table>', re.DOTALL)
        self.markdown_table_delimiter = re.compile(r'^\|?[\s\-:]+\|?$', re.MULTILINE)

        # 检查 BeautifulSoup4 可用性（仅检查一次）
        if PremiumTableParser._bs4_available is None:
            PremiumTableParser._bs4_version = check_bs4()
            PremiumTableParser._bs4_available = PremiumTableParser._bs4_version is not None

    def parse(self, content: str) -> Dict[str, Any]:
        """
        解析费率表

        Args:
            content: 表格内容

        Returns:
            解析结果: {headers: [...], data: [...], parser: '...'}
        """
        # 1. 识别表格结构
        structure = self._identify_structure(content)

        logger.info(f"识别到费率表结构类型: {structure['type']}")

        # 2. 根据结构选择解析策略
        if structure['type'] == 'html_table':
            return self._parse_html_table(content)
        elif structure['type'] == 'markdown_table':
            return self._parse_markdown_table(content)
        elif structure['type'] == 'text_grid':
            return self._parse_text_grid(content)
        else:
            logger.warning(f"不支持的表格结构: {structure['type']}")
            return {}

    def _identify_structure(self, content: str) -> Dict[str, str]:
        """
        识别表格结构类型

        Args:
            content: 表格内容

        Returns:
            结构类型信息
        """
        if '<table>' in content or '<tr>' in content or '<td>' in content:
            return {'type': 'html_table'}

        # 检查 Markdown 表格（连续多行都有 | 分隔符）
        lines = content.split('\n')[:10]
        pipe_count = sum(1 for line in lines if '|' in line and line.strip())
        if pipe_count >= 3:
            return {'type': 'markdown_table'}

        # 检查文本网格（对齐的列）
        if self._has_grid_pattern(content):
            return {'type': 'text_grid'}

        return {'type': 'unstructured'}

    def _has_grid_pattern(self, content: str) -> bool:
        """检查是否有文本网格模式（对齐的列）"""
        lines = content.split('\n')
        if len(lines) < 3:
            return False

        # 检查是否有连续空格（通常对齐点）
        for line in lines[:5]:
            if re.search(r'\s{4,}', line):
                return True

        return False

    def _parse_html_table(self, content: str) -> Dict[str, Any]:
        """
        解析 HTML 表格

        Args:
            content: HTML 表格内容

        Returns:
            解析结果
        """
        if not PremiumTableParser._bs4_available:
            logger.warning("BeautifulSoup4 未安装或版本不满足要求，使用正则解析")
            return self._parse_html_with_regex(content)

        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(content, 'html.parser')

            table = soup.find('table')
            if not table:
                return {}

            # 提取表头
            headers = []
            for th in table.find_all('th'):
                headers.append(th.get_text(strip=True))

            # 如果没有 th，尝试从第一行 tr 提取
            if not headers:
                first_row = table.find('tr')
                if first_row:
                    for td in first_row.find_all('td'):
                        headers.append(td.get_text(strip=True))

            # 提取数据行
            data = []
            for tr in table.find_all('tr')[1 if headers else 0:]:
                row = {}
                tds = tr.find_all('td')
                for i, td in enumerate(tds):
                    if i < len(headers):
                        row[headers[i]] = td.get_text(strip=True)
                    else:
                        row[f'column_{i}'] = td.get_text(strip=True)
                if row:
                    data.append(row)

            return {
                'headers': headers,
                'data': data,
                'row_count': len(data),
                'parser': 'html_table',
                'bs4_version': PremiumTableParser._bs4_version
            }

        except Exception as e:
            logger.error(f"HTML 表格解析失败: {e}，回退到正则解析")
            return self._parse_html_with_regex(content)

    def _parse_html_with_regex(self, content: str) -> Dict[str, Any]:
        """使用正则表达式解析 HTML 表格（回退方案）"""
        # 简化实现：提取表格单元格
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', content, re.DOTALL | re.IGNORECASE)

        if not cells:
            return {}

        # 简单的行逻辑（假设表格结构规整）
        # 这是一个简化实现，可能不适用于复杂表格
        return {
            'headers': ['列1', '列2', '列3'],
            'data': [{'列1': cell.strip() for cell in cells[i:i+3]} for i in range(0, len(cells), 3)],
            'parser': 'html_regex',
            '_fallback': True
        }

    def _parse_markdown_table(self, content: str) -> Dict[str, Any]:
        """
        解析 Markdown 表格

        Args:
            content: Markdown 表格内容

        Returns:
            解析结果
        """
        lines = content.split('\n')
        table_lines = []

        # 识别表格范围
        in_table = False
        for line in lines:
            stripped = line.strip()
            if '|' in line and stripped:
                table_lines.append(line)
                in_table = True
            elif in_table:
                break

        if not table_lines:
            return {}

        # 解析表头
        headers_line = table_lines[0]
        headers = [h.strip() for h in headers_line.split('|') if h.strip()]

        # 跳过分隔行（|---|---|）
        data_lines = table_lines[2:] if len(table_lines) > 2 else []

        # 解析数据行
        data = []
        for line in data_lines:
            if '|' in line:
                values = [v.strip() for v in line.split('|') if v.strip()]
                if values:
                    row = dict(zip(headers, values)) if headers else {'value': values[0]}
                    data.append(row)

        return {
            'headers': headers,
            'data': data,
            'row_count': len(data),
            'parser': 'markdown_table'
        }

    def _parse_text_grid(self, content: str) -> Dict[str, Any]:
        """
        解析文本网格（对齐的列）

        Args:
            content: 文本网格内容

        Returns:
            解析结果
        """
        lines = [line for line in content.split('\n') if line.strip()]
        if not lines:
            return {}

        # 查找列边界
        col_boundaries = self._find_column_boundaries(lines)

        # 解析数据
        data = []
        for line in lines:
            values = []
            for i in range(len(col_boundaries) - 1):
                start, end = col_boundaries[i], col_boundaries[i + 1]
                value = line[start:end].strip() if start < len(line) else ''
                values.append(value)

            if any(v for v in values):  # 至少有一个非空值
                data.append(values)

        # 第一行作为表头
        if data:
            headers = data[0]
            data_rows = data[1:] if len(data) > 1 else []

            # 转换为字典格式
            formatted_data = []
            for row in data_rows:
                row_dict = {}
                for i, value in enumerate(row):
                    if i < len(headers):
                        row_dict[headers[i]] = value
                formatted_data.append(row_dict)

            return {
                'headers': headers,
                'data': formatted_data,
                'row_count': len(formatted_data),
                'parser': 'text_grid'
            }

        return {}

    def _find_column_boundaries(self, lines: List[str]) -> List[int]:
        """
        查找列边界位置

        Args:
            lines: 文本行列表

        Returns:
            边界位置列表
        """
        if not lines:
            return [0, 100]

        # 使用第一行作为参考
        first_line = lines[0]
        boundaries = [0]

        # 查找连续空格（通常对齐点）
        for match in re.finditer(r'\s{3,}', first_line):
            boundaries.append(match.start())

        boundaries.append(len(first_line))
        return sorted(set(boundaries))


class DiseaseListParser:
    """病种列表专用解析器"""

    # 预编译正则模式
    PATTERNS = [
        # 格式1: 编号 + 疾病名称 + 说明
        re.compile(r'(\d+\.?\d*)\s*([^\n、]{2,20})[：:：]?\s*([^。\n]*)'),
        # 格式2: • 疾病名称
        re.compile(r'[•·]\s*([^\n]{2,30})'),
        # 格式3: 疾病名称（轻症/中症/重症）
        re.compile(r'([^、\n]{2,30})(（|\()?\s*(轻症|中症|重症)\s*(）|\))?'),
    ]

    def parse(self, content: str) -> List[Dict[str, Any]]:
        """
        解析病种列表

        Args:
            content: 病种列表内容

        Returns:
            病种列表
        """
        diseases = []

        # 1. 尝试各种模式
        for pattern in self.PATTERNS:
            matches = pattern.findall(content)
            if len(matches) > 3:  # 找到足够多的匹配
                for match in matches:
                    disease = self._parse_disease_match(match)
                    if disease:
                        diseases.append(disease)
                break

        # 2. 如果正则失败，尝试 LLM
        if not diseases:
            logger.info("正则解析失败，使用 LLM 解析病种列表")
            diseases = self._parse_with_llm(content)

        logger.info(f"解析到 {len(diseases)} 个病种")
        return diseases

    def _parse_disease_match(self, match: tuple) -> Optional[Dict[str, Any]]:
        """
        解析单个病种匹配结果

        Args:
            match: 正则匹配结果

        Returns:
            病种信息字典
        """
        if not match:
            return None

        # 根据匹配格式解析
        if len(match) >= 3 and match[0] and match[0].replace('.', '').isdigit():
            # 格式1: 编号 + 名称 + 说明
            return {
                'number': match[0],
                'name': match[1].strip(),
                'description': match[2].strip() if len(match) > 2 else None,
                'grade': self._infer_grade(match[2] if len(match) > 2 else match[1])
            }
        elif '轻症' in match or '中症' in match or '重症' in match:
            # 格式3: 带分级
            grade = next((m for m in match if m in ['轻症', '中症', '重症']), None)
            name = next((m for m in match if m != grade), None)
            if name:
                return {
                    'name': name.strip(),
                    'grade': grade
                }
        else:
            # 格式2: 只有名称
            return {
                'name': match[0].strip() if isinstance(match, (list, tuple)) else match
            }

        return None

    def _infer_grade(self, text: str) -> Optional[str]:
        """
        从文本推断疾病分级

        Args:
            text: 疾病描述文本

        Returns:
            分级 (轻症/中症/重症) 或 None
        """
        if not text:
            return None

        text_lower = text.lower()
        if '重症' in text_lower or '重大' in text_lower:
            return '重症'
        elif '中症' in text_lower:
            return '中症'
        elif '轻症' in text_lower:
            return '轻症'
        return None

    def _parse_with_llm(self, content: str, llm_client=None) -> List[Dict[str, Any]]:
        """
        使用 LLM 解析病种列表（回退方案）

        Args:
            content: 病种列表内容
            llm_client: LLM 客户端（可选）

        Returns:
            病种列表
        """
        if not llm_client:
            logger.warning("未提供 LLM 客户端，返回空列表")
            return []

        prompt = f"""从以下内容中提取病种列表：

{content[:2000]}

**输出格式** (JSON):
{{
  "diseases": [
    {{"name": "恶性肿瘤", "grade": "重症", "description": "..."}}],
    {{"name": "急性心肌梗死", "grade": "重症", "description": "..."}}
  ]
}}

请只返回 JSON，不要其他内容。"""

        try:
            response = llm_client.generate(prompt, max_tokens=2000, temperature=0.1)
            result = parse_llm_json_response(response)
            return result.get('diseases', [])
        except Exception as e:
            logger.error(f"LLM 解析病种列表失败: {e}")
            return []


class ParserEngine:
    """专用解析器集合"""

    def __init__(self):
        self._premium_table_parser = PremiumTableParser()
        self._disease_list_parser = DiseaseListParser()

    def parse_premium_table(self, content: str) -> Dict[str, Any]:
        """解析费率表"""
        return self._premium_table_parser.parse(content)

    def parse_disease_list(self, content: str) -> List[Dict[str, Any]]:
        """解析病种列表"""
        return self._disease_list_parser.parse(content)

    def get_parser(self, content_type: str):
        """
        获取指定类型的解析器

        Args:
            content_type: 内容类型 (premium_table, disease_list)

        Returns:
            对应的解析器实例
        """
        parsers = {
            'premium_table': self._premium_table_parser,
            'disease_list': self._disease_list_parser,
        }
        return parsers.get(content_type)

    def supports(self, content_type: str) -> bool:
        """
        检查是否支持指定内容类型

        Args:
            content_type: 内容类型

        Returns:
            是否支持
        """
        return content_type in ['premium_table', 'disease_list']
