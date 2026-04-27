#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 文档解析器"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber

from ..models import AuditDocument, Clause, DataTable, DocumentParseError, SectionType, TableType
from .header_footer_filter import HeaderFooterFilter
from .layout_analyzer import LayoutAnalyzer
from .section_detector import SectionDetector
from .table_classifier import TableClassifier
from .toc_detector import TocDetector
from .utils import add_section, split_title_and_content

logger = logging.getLogger(__name__)


class PdfParser:
    """PDF 文档解析器"""

    def __init__(self, section_detector: Optional[SectionDetector] = None):
        self.detector = section_detector or SectionDetector()
        self.layout_analyzer = LayoutAnalyzer()
        self.header_footer_filter = HeaderFooterFilter()
        self.table_classifier = TableClassifier()
        self.toc_detector = TocDetector()

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.pdf']

    def parse(self, file_path: str) -> AuditDocument:
        path = Path(file_path)
        if not path.exists():
            raise DocumentParseError("文件不存在", file_path)

        try:
            pdf = pdfplumber.open(file_path)
        except Exception as e:
            error_msg = str(e).lower()
            if "password" in error_msg or "encrypted" in error_msg:
                raise DocumentParseError(
                    "PDF 文件已加密，不支持加密文档",
                    file_path,
                    "请提供未加密的 PDF 文档"
                )
            raise DocumentParseError("PDF 文件解析失败", file_path, str(e))

        warnings: List[str] = []

        try:
            clauses = self._extract_clauses(pdf.pages, warnings)
            tables = self._extract_tables(pdf.pages, warnings)
            sections_data = self._extract_special_sections(pdf.pages, warnings)
        finally:
            pdf.close()

        return AuditDocument(
            file_name=path.name,
            file_type='.pdf',
            clauses=clauses,
            tables=tables,
            notices=sections_data['notices'],
            health_disclosures=sections_data['health_disclosures'],
            exclusions=sections_data['exclusions'],
            rider_clauses=sections_data['rider_clauses'],
            parse_time=datetime.now(),
            warnings=warnings,
        )

    def _extract_clauses(self, pages: List, warnings: List[str]) -> List[Clause]:
        """提取条款内容。

        从文本流识别条款编号和标题，合并跨页重复条款。
        直接使用 extract_text() 获取文本，避免从 chars 重建的复杂性。
        后处理过滤页眉页脚行。
        """
        clauses_dict: Dict[str, Clause] = {}

        pending_number: Optional[str] = None
        pending_title: Optional[str] = None
        pending_content: List[str] = []
        pending_page: int = 1

        # 页眉页脚过滤模式（用于后处理）
        footer_patterns = [
            r'第\s*\d+\s*页', r'Page\s*\d+', r'共\s*\d+\s*页',
            r'\d+\s*/\s*\d+', r'第\s*页', r'共\s*页',
            r'^\d+\s+\d+$',  # 纯数字组合如 "9 18"
        ]

        for page_idx, page in enumerate(pages):
            # 目录页检测与过滤
            is_toc, toc_clean_text = self.toc_detector.detect(page, page_idx)

            if is_toc:
                text = toc_clean_text
            else:
                # 直接使用 extract_text()，后处理过滤页眉页脚
                text = page.extract_text() or ''

            if not text:
                continue

            lines = text.split('\n')

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue

                # 后处理：过滤页眉页脚行
                is_footer = False
                for pattern in footer_patterns:
                    import re
                    if re.search(pattern, stripped, re.IGNORECASE):
                        is_footer = True
                        break
                if is_footer:
                    continue

                match = self._match_clause_line(stripped)
                if match:
                    number = match.group(1)
                    title = match.group(2).strip()

                    if pending_number is not None and pending_number != number:
                        self._merge_clause(
                            clauses_dict,
                            pending_number,
                            pending_title or '',
                            pending_content,
                            pending_page,
                        )
                        pending_content = []

                    pending_number = number
                    pending_title = title
                    pending_page = page_idx + 1
                elif pending_number is not None:
                    pending_content.append(stripped)

        if pending_number is not None:
            self._merge_clause(
                clauses_dict,
                pending_number,
                pending_title or '',
                pending_content,
                pending_page,
            )

        clauses = list(clauses_dict.values())

        def sort_key(c: Clause) -> List[int]:
            parts = c.number.split('.')
            return [int(p) for p in parts]

        clauses.sort(key=sort_key)
        return clauses

    def _match_clause_line(self, line: str):
        """匹配条款行：编号 + 空格 + 标题。

        只匹配 X.Y 格式的条款编号（至少包含一个点），
        过滤掉单数字格式的章节标题（如 "1 被保险人范围"）。
        """
        stripped = line.strip()
        import re
        match = re.match(r'^(\d+\.\d+(?:\.\d+)*)\s+(.+)$', stripped)
        if match:
            return match
        return None

    def _merge_clause(
        self,
        clauses_dict: Dict[str, Clause],
        number: str,
        title: str,
        content_lines: List[str],
        page_number: int,
    ) -> None:
        """合并条款到字典，处理跨页重复和章节标题干扰。"""
        filtered_lines = [line for line in content_lines if not self._is_chapter_header(line)]

        if number in clauses_dict:
            existing = clauses_dict[number]
            combined_text = existing.text
            if filtered_lines:
                new_text = '\n'.join(filtered_lines).strip()
                if new_text:
                    combined_text = f"{combined_text}\n{new_text}" if combined_text else new_text
            clauses_dict[number] = Clause(
                number=existing.number,
                title=existing.title or title,
                text=combined_text,
                page_number=existing.page_number,
            )
        else:
            clause = self._build_clause(number, title, filtered_lines, page_number)
            clauses_dict[number] = clause

    def _is_chapter_header(self, line: str) -> bool:
        """检测章节标题行（用于过滤目录页干扰）。"""
        stripped = line.strip()
        chapter_titles = [
            '其他事项', '合同效力', '保险费', '保险金的申请及给付',
            '名词释义', '投保范围', '保险责任及责任免除',
        ]
        return any(stripped.endswith(t) and len(stripped) < 20 for t in chapter_titles)

    def _build_clause(
        self,
        number: str,
        title: str,
        content_lines: List[str],
        page_number: int,
    ) -> Clause:
        """构建条款对象。"""
        full_title, extra_text = split_title_and_content(title)
        all_content = ([extra_text] if extra_text else []) + content_lines
        text = '\n'.join(all_content).strip()

        return Clause(
            number=number,
            title=full_title,
            text=text,
            page_number=page_number,
        )

    def _extract_tables(self, pages: List, warnings: List[str]) -> List[DataTable]:
        """提取数据表格。

        使用 TableClassifier 分类表格类型。
        过滤单行表格（装饰性章节标题）。
        提取表格上方的表名（如"附表一"）作为 remark。
        """
        tables: List[DataTable] = []

        for page_idx, page in enumerate(pages):
            page_text = page.extract_text() or ''
            page_tables = page.find_tables()
            for table_idx, table in enumerate(page_tables):
                classification = self.table_classifier.classify(table)

                rows = table.extract()
                if not rows or len(rows) < 2:
                    continue

                header = [str(cell or '').strip() for cell in rows[0]]
                non_empty_header = [h for h in header if h]
                if len(non_empty_header) < 2:
                    continue

                raw_text = '\n'.join(
                    '\t'.join(str(cell or '') for cell in row)
                    for row in rows
                )
                data = [[str(cell or '') for cell in row] for row in rows]
                bbox = getattr(table, 'bbox', None)

                # 提取表格上方文本作为表名
                table_title = self._extract_table_title(page, table)

                # 检查是否为跨页续表：从已创建的表格列表中查找同列数的前一个表格
                # 续表特征：表格在页面顶部，且前一个表格在上一页底部
                table_type = classification.table_type
                prev_table: Optional[DataTable] = None
                if bbox and tables:
                    page_height = page.height
                    # 表格顶部靠近页面顶部 → 可能是续表
                    if bbox[1] < page_height * 0.15:
                        # 只检查最近创建的表格
                        last_table = tables[-1]
                        # 前一个表格在不同页，且列数相同
                        if last_table.page_number != page_idx + 1 and len(last_table.data[0]) == len(header):
                            prev_table = last_table

                # 续表处理：继承已创建表格的表头和表名
                if prev_table:
                    # 继承表名
                    if not table_title and prev_table.remark:
                        table_title = prev_table.remark
                    # 继承表头
                    prev_header = prev_table.data[0]
                    if len(prev_header) == len(data[0]):
                        data = [prev_header] + data[1:]
                        raw_text = '\n'.join(
                            '\t'.join(str(cell or '') for cell in row)
                            for row in data
                        )

                # 其他分类逻辑
                if table_type == TableType.OTHER:
                    context_pages = [page_text]
                    if page_idx > 0:
                        context_pages.append(pages[page_idx - 1].extract_text() or '')
                    context_text = '\n'.join(context_pages)
                    table_type = self._classify_by_context(
                        context_text, data, table_title, prev_table.table_type if prev_table else None
                    )

                tables.append(DataTable(
                    data=data,
                    table_type=table_type,
                    raw_text=raw_text,
                    remark=table_title,
                    page_number=page_idx + 1,
                    bbox=bbox,
                    table_index=table_idx,
                ))

                if classification.table_type == TableType.UNKNOWN:
                    warnings.append(
                        f"Page {page_idx + 1} table {table_idx} 类型未知"
                    )

        return tables

    def _classify_by_context(
        self,
        page_text: str,
        data: List[List[str]],
        table_title: str,
        prev_table_type: Optional[TableType] = None,
    ) -> TableType:
        """利用页面上下文辅助表格分类

        当表头分类结果为 OTHER 时，检查：
        1. 上一页同类型表格（续表）
        2. 表名是否包含 "附表" 等关键词
        3. 表格内容特征（如包含分期指标 "Ⅰ期"、"Ⅱ期"）
        4. 跨页上下文中的附表标题行（独立行格式）

        Args:
            page_text: 页面文本（含前后页面上下文）
            data: 表格数据
            table_title: 表名
            prev_table_type: 上一页底部表格的类型（用于续表检测）

        Returns:
            TableType 或 OTHER
        """
        # 续表：沿用上一页表格的类型
        if prev_table_type and prev_table_type != TableType.OTHER:
            return prev_table_type

        # 检查表名
        if table_title:
            if '附表' in table_title or '附录' in table_title:
                return TableType.APPENDIX

        # 检查表格内容是否有分期指标（TNM 分期表特征）
        staging_indicators = ['Ⅰ期', 'Ⅱ期', 'Ⅲ期', 'ⅣA期', 'ⅣB期', 'ⅣC期']
        for row in data[:5]:
            for cell in row:
                cell_str = str(cell or '')
                # 精确匹配分期指标（必须包含"期"）
                if any(indicator in cell_str for indicator in staging_indicators):
                    return TableType.APPENDIX

        # 检查跨页上下文中的附表标题行
        # 注意：目录中的"附表"引用不算（如"见附表一"），只有独立标题行才算
        for line in page_text.split('\n'):
            stripped = line.strip()
            if stripped.startswith('附表') or stripped.startswith('附录'):
                return TableType.APPENDIX

        return TableType.OTHER

    def _extract_table_title(self, page, table) -> str:
        """提取表格上方的表名（如"附表一 恶性肿瘤分期表"）

        Args:
            page: pdfplumber 页面对象
            table: pdfplumber 表格对象

        Returns:
            表名或空字符串
        """
        bbox = getattr(table, 'bbox', None)
        if not bbox:
            return ''

        table_top = bbox[1]  # y0
        chars = page.chars

        # 收集表格上方 50-80px 范围内的字符
        above_chars = [
            c for c in chars
            if c['top'] < table_top and c['top'] > table_top - 80
        ]

        if not above_chars:
            return ''

        # 按 y 坐标分组
        y_tolerance = 3.0
        lines_by_y: Dict[float, List[str]] = {}
        for c in above_chars:
            y_key = round(c['top'] / y_tolerance) * y_tolerance
            if y_key not in lines_by_y:
                lines_by_y[y_key] = []
            lines_by_y[y_key].append(c['text'])

        # 从最靠近表格的行开始，查找包含"附表"或表名特征的行
        sorted_y = sorted(lines_by_y.keys(), reverse=True)
        for y in sorted_y:
            line_text = ''.join(lines_by_y[y]).strip()
            if not line_text:
                continue
            # 检查是否为表名（包含"附表"或短标题行）
            if '附表' in line_text or '附录' in line_text:
                return line_text
            # 短行（< 30字）可能是表名
            if len(line_text) < 30 and not any(kw in line_text for kw in ['注', '说明', '本公司']):
                return line_text

        return ''

    def _extract_special_sections(self, pages: List, warnings: List[str]) -> Dict[str, List[Any]]:
        """提取特殊章节（告知事项、健康告知、附加条款）。

        注意：责任免除条款（如 2.6）已在 clauses 中提取，此处不再重复。
        exclusions 只用于无编号的独立声明（如投保须知中的免责声明）。
        """
        result: Dict[str, List[Any]] = {
            'notices': [],
            'health_disclosures': [],
            'exclusions': [],
            'rider_clauses': [],
        }

        current_type: Optional[SectionType] = None
        current_content: List[str] = []

        for page_idx, page in enumerate(pages):
            # 目录页整体跳过
            is_toc, _ = self.toc_detector.detect(page, page_idx)
            if is_toc:
                continue

            text = self.header_footer_filter.filter(page)
            if not text:
                text = page.extract_text() or ''

            lines = text.split('\n')

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue

                detected = self.detector.detect_section_type(stripped)
                if detected:
                    # EXCLUSION 类型跳过（已在 clauses 中）
                    if detected == SectionType.EXCLUSION:
                        continue
                    # 同类型章节标题视为延续，不重新开始
                    if detected == current_type:
                        current_content.append(stripped)
                    else:
                        if current_type and current_content:
                            add_section(result, current_type, '', '\n'.join(current_content))
                        current_type = detected
                        current_content = []
                elif current_type:
                    current_content.append(stripped)

        if current_type and current_content:
            add_section(result, current_type, '', '\n'.join(current_content))

        return result
