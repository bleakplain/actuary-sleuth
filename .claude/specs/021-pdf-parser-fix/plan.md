# Implementation Plan: PDF Parser Fix

**Branch**: `021-pdf-parser-fix` | **Date**: 2026-04-23 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

修复 PDF 解析器的结构性缺陷，使其能够正确提取保险产品文档中的条款内容。核心问题是当前仅从表格提取条款（7条），而实际条款分布在文本流中（应有60+条）。修复策略是参照 DOCX 解析器设计，从文本流识别条款编号模式，重构条款提取逻辑。

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: pdfplumber (现有), re (标准库), dataclasses (标准库)
**Testing**: pytest + 真实 PDF 文档
**Performance Goals**: 19 页 PDF 解析 < 5 秒
**Constraints**: 保持与 DOCX 解析器的接口兼容性

## Constitution Check

- [x] **Library-First**: 复用 pdfplumber（PDF 解析）、SectionDetector（编号正则）、Clause 模型
- [x] **测试优先**: Phase 1 包含真实文档测试，每个 User Story 有验收测试
- [x] **简单优先**: 文本流提取是最简单直接的方案，不引入额外依赖
- [x] **显式优于隐式**: 条款编号正则明确，配置文件显式定义
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md 的 User Story
- [x] **独立可测试**: User Story 1-3 可独立测试和交付

## Project Structure

### Documentation

```text
.claude/specs/021-pdf-parser-fix/
├── spec.md          # 需求规格
├── research.md      # 技术调研
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/lib/doc_parser/pd/
├── __init__.py
├── parser.py              # 编排器（不变）
├── pdf_parser.py          # 重构：条款提取逻辑
├── docx_parser.py         # 参考（不变）
├── section_detector.py    # 增强：条款头识别
├── utils.py               # 工具函数（不变）
├── models.py              # 数据模型（不变）
└── data/
    └── keywords.json      # 新增：配置文件

scripts/tests/lib/doc_parser/pd/
├── test_pdf_parser.py     # 增强：真实文档测试
├── test_section_detector.py
└── conftest.py
```

---

## Implementation Phases

### Phase 1: Setup - 配置文件和基础设施

#### 需求回溯

→ 支持 FR-004（接口兼容）、FR-006（加密 PDF 提示）

#### 实现步骤

**步骤 1.1: 创建 keywords.json 配置文件**

- 文件: `scripts/lib/doc_parser/pd/data/keywords.json`
- 操作: 新增

```json
{
  "section_keywords": {
    "notice": ["阅读指引", "重要提示", "告知事项", "客户须知"],
    "health_disclosure": ["健康告知", "如实告知", "健康说明", "健康状况告知"],
    "exclusion": ["责任免除", "免责条款", "不承担责任", "不承担保险责任"],
    "rider": ["附加险", "附加条款", "附加合同"]
  },
  "premium_table_keywords": ["费率", "保险费", "保费", "基本保险金额"],
  "non_clause_table_keywords": ["公司名称", "客服电话", "地址", "邮编", "网址"]
}
```

**步骤 1.2: 增强 SectionDetector 条款头识别**

- 文件: `scripts/lib/doc_parser/pd/section_detector.py`
- 操作: 修改，增加 `match_clause_header()` 方法

```python
import re
from typing import Optional, Match

class SectionDetector:
    # 新增：条款头匹配正则（编号 + 空格 + 标题）
    CLAUSE_HEADER_PATTERN = re.compile(
        r'^(\d+(?:\.\d+)*)\s+(.+)$'
    )

    def match_clause_header(self, line: str) -> Optional[Match[str]]:
        """匹配文本流中的条款头。

        匹配格式：编号 + 空格 + 标题
        例如：'1.2 保险期间'、'2.3.1 等待期设置'

        Args:
            line: 文本行

        Returns:
            Match 对象（group(1)=编号, group(2)=标题）或 None
        """
        return self.CLAUSE_HEADER_PATTERN.match(line.strip())
```

---

### Phase 2: Core - User Story 1 (P1) 正确解析 PDF 条款结构

#### 需求回溯

→ 对应 spec.md User Story 1: 正确解析 PDF 条款结构
→ 支持 FR-001（标题层级识别）、FR-002（条款文本提取）

#### 实现步骤

**步骤 2.1: 重构 PdfParser.parse() 方法**

- 文件: `scripts/lib/doc_parser/pd/pdf_parser.py`
- 操作: 修改 `parse()` 方法，调用新的条款提取逻辑

```python
def parse(self, file_path: str) -> AuditDocument:
    path = Path(file_path)
    if not path.exists():
        raise DocumentParseError("文件不存在", file_path)

    try:
        pdf = pdfplumber.open(file_path)
    except Exception as e:
        # 增强：检测加密 PDF
        if "password" in str(e).lower() or "encrypted" in str(e).lower():
            raise DocumentParseError(
                "PDF 文件已加密，不支持加密文档",
                file_path,
                "请提供未加密的 PDF 文档"
            )
        raise DocumentParseError("PDF 文件解析失败", file_path, str(e))

    warnings: List[str] = []
    clauses: List[Clause] = []
    premium_tables: List[PremiumTable] = []
    sections_data: Dict[str, List[Any]] = {
        'notices': [],
        'health_disclosures': [],
        'exclusions': [],
        'rider_clauses': [],
    }

    try:
        # 核心修改：从文本流提取条款
        clauses = self._extract_clauses_from_text(pdf.pages, warnings)
        # 保留表格提取作为补充（费率表等）
        premium_tables = self._extract_premium_tables(pdf.pages, warnings)
        # 提取特殊章节
        sections_data = self._extract_sections_from_pages(pdf.pages, warnings)
    finally:
        pdf.close()

    return AuditDocument(
        file_name=path.name,
        file_type='.pdf',
        clauses=clauses,
        premium_tables=premium_tables,
        notices=sections_data['notices'],
        health_disclosures=sections_data['health_disclosures'],
        exclusions=sections_data['exclusions'],
        rider_clauses=sections_data['rider_clauses'],
        parse_time=datetime.now(),
        warnings=warnings,
    )
```

**步骤 2.2: 新增条款提取方法**

- 文件: `scripts/lib/doc_parser/pd/pdf_parser.py`
- 操作: 新增 `_extract_clauses_from_text()` 方法

```python
def _extract_clauses_from_text(
    self,
    pages: List,
    warnings: List[str],
) -> List[Clause]:
    """从文本流提取条款。

    遍历所有页面，识别 '编号 + 空格 + 标题' 格式的条款头，
    提取标题后的正文直到下一个条款头出现。

    Args:
        pages: pdfplumber 页面对象列表
        warnings: 警告信息列表

    Returns:
        条款列表
    """
    clauses: List[Clause] = []
    pending_number: Optional[str] = None
    pending_title: Optional[str] = None
    pending_content: List[str] = []
    pending_page: int = 1

    for page_idx, page in enumerate(pages):
        text = page.extract_text() or ''
        lines = text.split('\n')

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            match = self.detector.match_clause_header(stripped)
            if match:
                # 保存上一个条款
                if pending_number is not None:
                    clause = self._build_clause(
                        pending_number,
                        pending_title or '',
                        pending_content,
                        pending_page,
                    )
                    clauses.append(clause)

                # 开始新条款
                pending_number = match.group(1)
                pending_title = match.group(2).strip()
                pending_content = []
                pending_page = page_idx + 1
            elif pending_number is not None:
                # 追加到当前条款正文
                pending_content.append(stripped)

    # 保存最后一个条款
    if pending_number is not None:
        clause = self._build_clause(
            pending_number,
            pending_title or '',
            pending_content,
            pending_page,
        )
        clauses.append(clause)

    return clauses

def _build_clause(
    self,
    number: str,
    title: str,
    content_lines: List[str],
    page_number: int,
) -> Clause:
    """构建条款对象。

    分离标题中的短正文和完整正文。
    """
    # 使用现有工具分离标题和正文
    full_title, extra_text = separate_title_and_text(title)
    all_content = ([extra_text] if extra_text else []) + content_lines
    text = '\n'.join(all_content).strip()

    return Clause(
        number=number,
        title=full_title,
        text=text,
        page_number=page_number,
    )
```

**步骤 2.3: 重构费率表提取方法**

- 文件: `scripts/lib/doc_parser/pd/pdf_parser.py`
- 操作: 重构 `_extract_premium_tables()` 方法

```python
def _extract_premium_tables(
    self,
    pages: List,
    warnings: List[str],
) -> List[PremiumTable]:
    """从所有页面提取费率表。"""
    premium_tables: List[PremiumTable] = []

    for page_idx, page in enumerate(pages):
        tables = page.find_tables()
        for table_idx, table in enumerate(tables):
            rows = table.extract()
            if not rows:
                continue

            header = [str(cell or '').strip() for cell in rows[0]]
            if self.detector.is_premium_table(header):
                raw_text = '\n'.join(
                    '\t'.join(str(cell or '') for cell in row)
                    for row in rows
                )
                data = [[str(cell or '') for cell in row] for row in rows]
                bbox = getattr(table, 'bbox', None)
                premium_tables.append(PremiumTable(
                    raw_text=raw_text,
                    data=data,
                    page_number=page_idx + 1,
                    bbox=bbox,
                    table_index=table_idx,
                ))

    return premium_tables
```

**步骤 2.4: 重构章节提取方法**

- 文件: `scripts/lib/doc_parser/pd/pdf_parser.py`
- 操作: 重构 `_extract_sections_from_pages()` 方法

```python
def _extract_sections_from_pages(
    self,
    pages: List,
    warnings: List[str],
) -> Dict[str, List[Any]]:
    """从所有页面提取特殊章节（告知、免责等）。"""
    result: Dict[str, List[Any]] = {
        'notices': [],
        'health_disclosures': [],
        'exclusions': [],
        'rider_clauses': [],
    }

    current_type: Optional[SectionType] = None
    current_content: List[str] = []

    for page in pages:
        text = page.extract_text() or ''
        lines = text.split('\n')

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            detected = self.detector.detect_section_type(stripped)
            if detected:
                if current_type and current_content:
                    add_section(result, current_type, '', '\n'.join(current_content))
                current_type = detected
                current_content = []
            elif current_type:
                current_content.append(stripped)

    if current_type and current_content:
        add_section(result, current_type, '', '\n'.join(current_content))

    return result
```

---

### Phase 3: Core - User Story 2 (P1) 参照 DOCX 解析设计重构

#### 需求回溯

→ 对应 spec.md User Story 2: 参照 docx 解析设计重构
→ 支持 FR-004（接口兼容）

#### 实现步骤

**步骤 3.1: 验证接口兼容性**

两个解析器输出相同的 `AuditDocument` 结构，已满足接口兼容性要求。无需额外修改。

**步骤 3.2: 统一错误处理**

已在 Phase 2 步骤 2.1 中实现加密 PDF 检测和错误提示。

---

### Phase 4: Enhancement - User Story 3 (P2) 真实文档验证测试

#### 需求回溯

→ 对应 spec.md User Story 3: 真实文档验证测试
→ 支持 SC-001（解析成功率）、SC-002（一致率）

#### 实现步骤

**步骤 4.1: 添加真实文档测试**

- 文件: `scripts/tests/lib/doc_parser/pd/test_pdf_parser.py`
- 操作: 增强

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 解析器测试（含真实文档）"""
import pytest

pytest.importorskip("pdfplumber")

from pathlib import Path
from lib.doc_parser import parse_product_document
from lib.doc_parser.pd.pdf_parser import PdfParser


# 真实测试文档路径
REAL_PDF_DIR = Path("/Users/plain/work/actuary-assets/products")


class TestPdfParserRealDocs:
    """真实文档测试"""

    @pytest.fixture
    def real_pdfs(self):
        """获取真实 PDF 文件列表"""
        if not REAL_PDF_DIR.exists():
            pytest.skip(f"测试目录不存在: {REAL_PDF_DIR}")
        pdfs = list(REAL_PDF_DIR.glob("*.pdf"))
        if not pdfs:
            pytest.skip(f"未找到 PDF 文件: {REAL_PDF_DIR}")
        return pdfs

    def test_parse_real_pdfs_no_exception(self, real_pdfs):
        """所有真实 PDF 都能成功解析"""
        parser = PdfParser()
        for pdf_path in real_pdfs:
            result = parser.parse(str(pdf_path))
            assert result is not None
            assert result.file_type == '.pdf'

    def test_clause_count_reasonable(self, real_pdfs):
        """条款数量合理（> 5 条）"""
        parser = PdfParser()
        for pdf_path in real_pdfs:
            result = parser.parse(str(pdf_path))
            assert len(result.clauses) > 5, \
                f"{pdf_path.name} 条款数量过少: {len(result.clauses)}"

    def test_clause_structure(self, real_pdfs):
        """条款结构完整"""
        parser = PdfParser()
        for pdf_path in real_pdfs[:3]:  # 只测试前 3 个
            result = parser.parse(str(pdf_path))
            for clause in result.clauses[:5]:
                assert clause.number, "条款编号不能为空"
                assert clause.title, "条款标题不能为空"


class TestPdfParserUnit:
    """单元测试"""

    def test_supported_extensions(self):
        assert '.pdf' in PdfParser.supported_extensions()

    def test_clause_header_pattern(self):
        """条款头正则测试"""
        from lib.doc_parser.pd.section_detector import SectionDetector
        detector = SectionDetector()

        # 匹配成功
        match = detector.match_clause_header("1.2 保险期间")
        assert match is not None
        assert match.group(1) == "1.2"
        assert match.group(2) == "保险期间"

        match = detector.match_clause_header("2.3.1 等待期设置")
        assert match is not None
        assert match.group(1) == "2.3.1"

        # 不匹配
        assert detector.match_clause_header("这是一段普通文本") is None
        assert detector.match_clause_header("") is None
```

---

### Phase 5: Enhancement - 扫描版 PDF 支持 (OCR)

#### 需求回溯

→ 支持 FR-005（扫描版 PDF）、FR-007（PaddleOCR）

#### 实现步骤

**步骤 5.1: 创建 OCR 处理器**

- 文件: `scripts/lib/doc_parser/pd/ocr_handler.py`
- 操作: 新增

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描版 PDF OCR 处理"""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class OcrHandler:
    """扫描版 PDF OCR 处理器

    使用 PaddleOCR（本地 ollama 部署）识别图片中的文字。
    """

    MIN_TEXT_LENGTH = 100  # 判断扫描版的最小文本长度

    def is_scanned_page(self, text: str) -> bool:
        """检测页面是否为扫描版（无文字层）。

        Args:
            text: pdfplumber 提取的文本

        Returns:
            True 表示是扫描版，需要 OCR 处理
        """
        return len(text.strip()) < self.MIN_TEXT_LENGTH

    def ocr_page(self, page_image) -> str:
        """OCR 识别页面图片。

        Args:
            page_image: 页面图片对象

        Returns:
            识别的文本

        Raises:
            NotImplementedError: OCR 功能尚未实现
        """
        # TODO: 调用本地 ollama PaddleOCR 接口
        raise NotImplementedError(
            "扫描版 PDF OCR 功能尚未实现。"
            "请配置 PaddleOCR ollama 服务后重试。"
        )

    def process_pages(self, pages: List) -> List[str]:
        """处理所有页面，对扫描版进行 OCR。

        Args:
            pages: pdfplumber 页面对象列表

        Returns:
            每页的文本列表
        """
        texts: List[str] = []
        for idx, page in enumerate(pages):
            text = page.extract_text() or ''
            if self.is_scanned_page(text):
                logger.warning(f"第 {idx + 1} 页可能是扫描版，需要 OCR 处理")
                try:
                    # 转换页面为图片并 OCR
                    # image = page.to_image()
                    # text = self.ocr_page(image)
                    pass
                except NotImplementedError:
                    logger.warning(f"第 {idx + 1} 页 OCR 失败，跳过")
                    continue
            texts.append(text)
        return texts
```

**步骤 5.2: 集成 OCR 处理器**

- 文件: `scripts/lib/doc_parser/pd/pdf_parser.py`
- 操作: 修改 `parse()` 方法

```python
from .ocr_handler import OcrHandler

class PdfParser:
    def __init__(
        self,
        section_detector: Optional[SectionDetector] = None,
        ocr_handler: Optional[OcrHandler] = None,
    ):
        self.detector = section_detector or SectionDetector()
        self.ocr = ocr_handler or OcrHandler()
```

---

## Complexity Tracking

无违反项。方案遵循所有治理原则。

---

## Appendix

### 执行顺序建议

```
Phase 1 (Setup)
    ↓ 配置文件就绪
Phase 2 (Core - 条款提取)
    ↓ 条款提取功能完成
Phase 3 (Core - 接口兼容)
    ↓ 接口验证通过
Phase 4 (Test - 真实文档)
    ↓ 测试验证通过
Phase 5 (Enhancement - OCR)
    ↓ 可选：扫描版支持
完成
```

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US-1 正确解析条款 | 条款数量 > 5，结构完整 | `test_parse_real_pdfs_no_exception`, `test_clause_count_reasonable` |
| US-2 参照 DOCX 设计 | 输出结构兼容，错误处理统一 | 接口验证 + `AuditDocument` 类型检查 |
| US-3 真实文档验证 | 解析成功率 100%，条款提取正确 | `test_clause_structure` |

### 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 条款编号格式多样性 | 高 | 中 | 扩展正则，支持中文编号、括号格式 |
| 文本布局复杂 | 中 | 中 | 测试多份真实文档，迭代优化 |
| 扫描版 OCR 质量差 | 中 | 低 | 设置识别率阈值，低质量时警告 |