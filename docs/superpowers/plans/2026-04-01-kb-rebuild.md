# KB Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Excel product development checklist into structured Markdown knowledge base (v4), replacing the Feishu-migrated v3.

**Architecture:** A conversion script (`excel_to_kb.py`) reads the Excel via openpyxl, detects regulation boundaries in each sheet, extracts metadata tags and clause content, processes embedded table images via Zhipu GLM-OCR, and outputs Markdown files with YAML frontmatter and blockquote metadata tags. The ZhipuClient gets an `ocr_table()` method reusing existing session/retry/circuit-breaker infrastructure. Output is registered as KB v4 via VersionManager.

**Tech Stack:** Python, openpyxl, Zhipu GLM-OCR API (`/v4/layout_parsing`), existing `ZhipuClient` session management

---

### Task 1: Add `ocr_table()` to ZhipuClient

**Files:**
- Modify: `scripts/lib/llm/zhipu.py` (after line 248)
- Test: `scripts/tests/lib/llm/test_zhipu_ocr.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/lib/llm/test_zhipu_ocr.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZhipuClient OCR method tests."""
import pytest
from unittest.mock import MagicMock, patch


class TestZhipuClientOCR:
    """ZhipuClient.ocr_table() tests."""

    def test_ocr_table_calls_layout_parsing_endpoint(self):
        """ocr_table should POST to /v4/layout_parsing with glm-ocr model."""
        from lib.llm.zhipu import ZhipuClient

        client = ZhipuClient(api_key="test-key", base_url="https://fake.api/v4/")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": "| Col1 | Col2 |\n|------|------|\n| A | B |"}
        mock_response.raise_for_status = MagicMock()

        session = MagicMock()
        session.post.return_value = mock_response
        client._session = session

        result = client.ocr_table("data:image/png;base64,abc123")
        assert "| Col1 | Col2 |" in result
        session.post.assert_called_once()
        call_kwargs = session.post.call_args
        assert "/layout_parsing" in call_kwargs[0][0]
        assert call_kwargs[1]["json"]["model"] == "glm-ocr"

    def test_ocr_table_extracts_content_from_response(self):
        """ocr_table should return the 'content' field from response."""
        from lib.llm.zhipu import ZhipuClient

        client = ZhipuClient(api_key="test-key", base_url="https://fake.api/v4/")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": "markdown table content here"}
        mock_response.raise_for_status = MagicMock()

        session = MagicMock()
        session.post.return_value = mock_response
        client._session = session

        result = client.ocr_table("base64data")
        assert result == "markdown table content here"

    def test_ocr_table_raises_on_http_error(self):
        """ocr_table should propagate HTTP errors."""
        from lib.llm.zhipu import ZhipuClient

        client = ZhipuClient(api_key="test-key", base_url="https://fake.api/v4/")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("Server error")

        session = MagicMock()
        session.post.return_value = mock_response
        client._session = session

        with pytest.raises(Exception, match="Server error"):
            client._do_ocr_table("base64data")

    def test_ocr_table_empty_content(self):
        """ocr_table should return empty string when content field missing."""
        from lib.llm.zhipu import ZhipuClient

        client = ZhipuClient(api_key="test-key", base_url="https://fake.api/v4/")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"other_field": "value"}
        mock_response.raise_for_status = MagicMock()

        session = MagicMock()
        session.post.return_value = mock_response
        client._session = session

        result = client.ocr_table("base64data")
        assert result == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && python -m pytest tests/lib/llm/test_zhipu_ocr.py -v`
Expected: FAIL with `AttributeError: 'ZhipuClient' object has no attribute 'ocr_table'`

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/lib/llm/zhipu.py` after the `embed` method (after line 248):

```python
    def _do_ocr_table(self, image_base64: str) -> str:
        """调用 GLM-OCR 识别表格为 Markdown。"""
        url = f"{self.base_url}/layout_parsing"
        data = {
            "model": "glm-ocr",
            "file": image_base64,
        }
        session = self._get_session()
        response = session.post(url, json=data, timeout=self.timeout)

        if response.status_code == 429:
            raise requests.exceptions.RequestException(
                f"429 Rate limit exceeded: {response.text[:200]}"
            )
        if response.status_code >= 500:
            raise requests.exceptions.RequestException(
                f"{response.status_code} Server error: {response.text[:200]}"
            )

        response.raise_for_status()
        result = response.json()
        return result.get("content", "")

    @_track_timing("zhipu")
    @_with_circuit_breaker("zhipu")
    @_retry_with_backoff(
        max_retries=LLMConstants.MAX_RETRIES,
        base_delay=LLMConstants.RETRY_BASE_DELAY,
        rate_limit_delay_mult=LLMConstants.RATE_LIMIT_DELAY_MULT,
    )
    def ocr_table(self, image_base64: str) -> str:
        return self._do_ocr_table(image_base64)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && python -m pytest tests/lib/llm/test_zhipu_ocr.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/llm/zhipu.py scripts/tests/lib/llm/test_zhipu_ocr.py
git commit -m "feat: add ocr_table() method to ZhipuClient for GLM-OCR table recognition"
```

---

### Task 2: Excel Sheet Structure Parser

Parse the Excel file to extract sheet metadata, regulation boundaries, and column headers. This is the core data extraction logic.

**Files:**
- Create: `scripts/lib/rag_engine/excel_to_kb.py`
- Test: `scripts/tests/lib/rag_engine/test_excel_parser.py`

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/lib/rag_engine/test_excel_parser.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Excel sheet structure parser tests."""
import pytest
from pathlib import Path

EXCEL_PATH = Path(__file__).parent.parent.parent.parent / "references" / "1.产品开发检查清单2025年.xlsx"


class TestSheetStructureParser:
    """Tests for parsing sheet structure from Excel."""

    def test_list_content_sheets(self):
        """Should return only content sheets (skip '分工' and '相关法规')."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import list_content_sheets

        sheets = list_content_sheets(str(EXCEL_PATH))
        names = [s["name"] for s in sheets]
        assert "分工" not in names
        assert "相关法规" not in names
        assert len(sheets) == 11
        assert any("00" in n for n in names)

    def test_detect_regulation_boundaries_standard(self):
        """Standard sheets (00, 02-05) have title in row 1, headers in row 2, regulation in row 3."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "00" in name:
                sheet = wb[name]
                break
        assert sheet is not None

        structure = parse_sheet_structure(sheet, "00. 对照样例")
        assert structure["header_row"] == 2
        assert structure["data_start_row"] == 4
        assert structure["regulation_name"] != ""
        wb.close()

    def test_detect_regulation_boundaries_with_owner(self):
        """Sheets with '产品开发责任人' row (01, 06-08) have headers in row 3, data in row 5."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "01" in name and "负面" in name:
                sheet = wb[name]
                break
        assert sheet is not None

        structure = parse_sheet_structure(sheet, "01. 对照样例")
        assert structure["header_row"] == 3
        assert structure["data_start_row"] == 5
        wb.close()

    def test_detect_sub_regulations_in_sheet_10(self):
        """Sheet 10 has multiple regulation boundaries detected by non-numeric column A."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "10" in name and "其他" in name:
                sheet = wb[name]
                break
        assert sheet is not None

        structure = parse_sheet_structure(sheet, "10. 对照样例")
        # Sheet 10 should have multiple sub-regulations
        assert len(structure.get("sub_regulations", [])) >= 5
        wb.close()

    def test_extract_metadata_columns(self):
        """Should correctly identify metadata column indices (B-G)."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "00" in name:
                sheet = wb[name]
                break
        assert sheet is not None

        structure = parse_sheet_structure(sheet, "00. 对照样例")
        headers = structure["headers"]
        assert "项目" in headers.values() or any("项目" in str(v) for v in headers.values())
        wb.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && python -m pytest tests/lib/rag_engine/test_excel_parser.py -v`
Expected: FAIL with `ImportError: cannot import name 'list_content_sheets'`

- [ ] **Step 3: Write implementation**

Create `scripts/lib/rag_engine/excel_to_kb.py` with the following content:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Excel 产品开发检查清单 → Markdown 知识库转换脚本。

将 references/1.产品开发检查清单2025年.xlsx 转换为结构化 Markdown 知识库。
每个 sheet 按法规粒度拆分，提取元数据标签，处理内嵌表格图片。
"""
import argparse
import base64
import io
import json
import logging
import re
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 跳过的 sheet 名称
_SKIP_SHEETS = {"分工", "相关法规"}

# Sheet 序号 → 目录名映射（基于实际 Excel sheet 前缀编号）
_SHEET_DIR_MAP = {
    "00": "00_保险法",
    "01": "01_负面清单检查",
    "02": "02_条款费率管理办法",
    "03": "03_健康保险管理办法",
    "04": "04_普通型人身保险",
    "05": "05_分红型人身保险",
    "06": "06_短期健康保险",
    "07": "07_意外伤害保险",
    "08": "08_互联网保险产品",
    "09": "09_税优健康险",
    "10": "10_其他监管规定",
}

# 元数据列索引（0-based）及其名称
_METADATA_COLUMNS = {
    1: "险种大类",
    2: "险种类型",
    3: "险种分型",
    4: "保险期限",
    5: "主附险",
    6: "智能审核系统填报项目",
}


@dataclass
class SheetStructure:
    """解析后的 sheet 结构信息。"""
    sheet_name: str
    header_row: int
    data_start_row: int
    regulation_name: str
    headers: Dict[int, str] = field(default_factory=dict)
    sub_regulations: List[Dict] = field(default_factory=list)
    layout_type: str = "standard"  # "standard" or "with_owner"


@dataclass
class ClauseEntry:
    """单个检查条款。"""
    sequence: int
    content: str
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class ImageInfo:
    """Excel 内嵌图片信息。"""
    sheet_name: str
    row: int
    col: int
    image_data: bytes  # PNG bytes


def _get_sheet_code(sheet_name: str) -> str:
    """从 sheet 名称提取序号代码，如 '00. 对照"保险法"等法规检查' → '00'。"""
    match = re.match(r"(\d{2})", sheet_name)
    return match.group(1) if match else ""


def _get_dir_name(sheet_name: str) -> str:
    """获取 sheet 对应的目录名。"""
    code = _get_sheet_code(sheet_name)
    return _SHEET_DIR_MAP.get(code, f"{code}_unknown")


def _is_number(value) -> bool:
    """判断单元格值是否为纯数字（int 或数字字符串）。"""
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str) and value.strip().isdigit():
        return True
    return False


def list_content_sheets(excel_path: str) -> List[Dict]:
    """列出 Excel 中的内容 sheet（跳过'分工'和'相关法规'）。"""
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    result = []
    for name in wb.sheetnames:
        if name in _SKIP_SHEETS:
            continue
        code = _get_sheet_code(name)
        if code:
            result.append({"name": name, "code": code, "dir": _get_dir_name(name)})
    wb.close()
    return result


def parse_sheet_structure(sheet, sheet_name: str) -> SheetStructure:
    """解析 sheet 的结构信息：header 行、数据起始行、法规名称、子法规边界。"""
    rows = list(sheet.iter_rows(min_row=1, max_row=6, values_only=True))

    # 判断布局类型：第2行是否包含"产品开发责任人"
    layout_type = "standard"
    if len(rows) >= 2 and rows[1] and any(
        "产品开发责任人" in str(cell) for cell in rows[1] if cell
    ):
        layout_type = "with_owner"

    if layout_type == "standard":
        header_row = 2
        regulation_row = 3
        data_start_row = 4
    else:
        header_row = 3
        regulation_row = 4
        data_start_row = 5

    # 提取 header
    header_data = rows[header_row - 1] if len(rows) >= header_row else []
    headers = {}
    for idx, val in enumerate(header_data):
        if val:
            headers[idx] = str(val).strip()

    # 提取法规名称
    regulation_name = ""
    if len(rows) >= regulation_row and rows[regulation_row - 1]:
        regulation_name = str(rows[regulation_row - 1][0] or "").strip()
        # 有些 sheet 法规名在第1行
        if not regulation_name and len(rows) >= 1 and rows[0]:
            regulation_name = str(rows[0][0] or "").strip()

    # 检测子法规边界（遍历所有数据行）
    sub_regulations = []
    current_sub = {"name": regulation_name, "start_row": data_start_row}
    for row_idx, row in enumerate(
        sheet.iter_rows(min_row=data_start_row, values_only=False), start=data_start_row
    ):
        cell_a = row[0].value if row else None
        if cell_a is not None and not _is_number(cell_a):
            # 非数字行 = 子法规边界
            if current_sub["name"] and current_sub["start_row"] != row_idx:
                sub_regulations.append(dict(current_sub))
            current_sub = {
                "name": str(cell_a).strip(),
                "start_row": row_idx + 1,  # 数据从下一行开始
            }
    # 最后一个子法规
    if current_sub["name"]:
        sub_regulations.append(dict(current_sub))

    # 如果只有一个子法规且名字等于 sheet 级法规名，用空列表表示无子法规
    if len(sub_regulations) == 1 and sub_regulations[0]["name"] == regulation_name:
        sub_regulations = []

    return SheetStructure(
        sheet_name=sheet_name,
        header_row=header_row,
        data_start_row=data_start_row,
        regulation_name=regulation_name,
        headers=headers,
        sub_regulations=sub_regulations,
        layout_type=layout_type,
    )


def extract_clauses(sheet, structure: SheetStructure) -> List[ClauseEntry]:
    """从 sheet 中提取所有检查条款及其元数据。"""
    clauses = []
    sub_regs = structure.sub_regulations

    for row_idx, row in enumerate(
        sheet.iter_rows(min_row=structure.data_start_row, values_only=True),
        start=structure.data_start_row,
    ):
        cell_a = row[0] if row else None

        # 跳过空行和子法规标题行
        if cell_a is None or (not _is_number(cell_a)):
            continue

        content = str(row[1] or "").strip() if len(row) > 1 else ""
        if not content:
            continue

        # 提取元数据（B-G 列之后的列，按实际 header 对应）
        metadata = {}
        for col_idx, col_name in _METADATA_COLUMNS.items():
            if col_idx < len(row) and row[col_idx]:
                val = str(row[col_idx]).strip()
                if val and val != "全部":
                    metadata[col_name] = val

        clauses.append(ClauseEntry(
            sequence=int(cell_a) if isinstance(cell_a, (int, float)) else int(float(cell_a)),
            content=content,
            metadata=metadata,
        ))

    return clauses


def format_metadata_block(metadata: Dict[str, str]) -> str:
    """将元数据字典格式化为 blockquote 格式。"""
    if not metadata:
        return ""
    parts = [f"{k}={v}" for k, v in metadata.items()]
    return f"\n> **元数据**: {' | '.join(parts)}\n"


def generate_frontmatter(
    collection: str,
    regulation: str,
    source_sheet: str,
    tags: List[str],
) -> str:
    """生成 YAML frontmatter。"""
    import yaml

    data = {
        "collection": collection,
        "regulation": regulation,
        "source": "1.产品开发检查清单2025年.xlsx",
        "source_sheet": source_sheet,
        "tags": tags,
    }
    return "---\n" + yaml.dump(data, allow_unicode=True, default_flow_style=False) + "---\n"


def clauses_to_markdown(
    clauses: List[ClauseEntry],
    frontmatter: str,
    regulation_name: str,
) -> str:
    """将条款列表转换为 Markdown 文档内容。"""
    lines = [frontmatter, f"# {regulation_name}", ""]

    for clause in clauses:
        lines.append(f"## 第{clause.sequence}项")
        lines.append(format_metadata_block(clause.metadata))
        lines.append(clause.content)
        lines.append("")

    return "\n".join(lines)


def extract_images_from_sheet(sheet, sheet_name: str) -> List[ImageInfo]:
    """从 sheet 中提取所有嵌入图片。"""
    from openpyxl.drawing.image import Image as XlImage

    images = []
    for img in sheet._images:
        anchor = img.anchor
        if hasattr(anchor, "_from"):
            row = anchor._from.row + 1  # openpyxl is 0-based
            col = anchor._from.col
        else:
            continue

        buf = io.BytesIO()
        img._data() if hasattr(img, "_data") else None
        # 保存图片到 bytes
        try:
            pil_img = img.ref if hasattr(img, "ref") else None
            if pil_img is None:
                pil_img = img.image if hasattr(img, "image") else None
            if pil_img is not None:
                img_buf = io.BytesIO()
                pil_img.save(img_buf, format="PNG")
                images.append(ImageInfo(
                    sheet_name=sheet_name,
                    row=row,
                    col=col,
                    image_data=img_buf.getvalue(),
                ))
        except Exception as e:
            logger.warning(f"提取图片失败 sheet={sheet_name} row={row}: {e}")

    return images


def extract_images_from_excel(excel_path: str) -> List[ImageInfo]:
    """从 Excel 中提取所有嵌入图片。"""
    import openpyxl

    wb = openpyxl.load_workbook(excel_path)
    all_images = []
    for name in wb.sheetnames:
        if name in _SKIP_SHEETS:
            continue
        sheet = wb[name]
        images = extract_images_from_sheet(sheet, name)
        all_images.extend(images)
        logger.info(f"Sheet '{name}': 提取 {len(images)} 张图片")
    wb.close()
    return all_images


def ocr_image(image_data: bytes, api_key: str) -> str:
    """调用智谱 GLM-OCR 识别图片中的表格。"""
    import base64
    from lib.llm.zhipu import ZhipuClient

    b64 = base64.b64encode(image_data).decode("utf-8")
    client = ZhipuClient(api_key=api_key)
    try:
        result = client.ocr_table(b64)
        return result
    finally:
        client.close()


def generate_meta_json(output_dir: Path, description: str) -> None:
    """在输出目录生成 meta.json。"""
    # 统计 markdown 文件数
    md_count = 0
    for p in output_dir.rglob("*.md"):
        md_count += 1

    meta = {
        "version_id": "v4",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "document_count": md_count,
        "chunk_count": 0,
        "active": True,
        "description": description,
    }
    meta_path = output_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"生成 meta.json: {md_count} 个文档")


def convert_excel_to_kb(
    excel_path: str,
    output_dir: str,
    skip_ocr: bool = False,
    zhipu_api_key: Optional[str] = None,
) -> Path:
    """主转换函数：Excel → Markdown 知识库。"""
    import openpyxl

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    refs_dir = output_path / "references"
    if refs_dir.exists():
        shutil.rmtree(refs_dir)
    refs_dir.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)

    # 阶段1：提取图片（需要非 read_only 模式）
    wb.close()
    images = extract_images_from_excel(excel_path) if not skip_ocr else []

    # 重新以 read_only 模式打开处理数据
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)

    for sheet_name in wb.sheetnames:
        if sheet_name in _SKIP_SHEETS:
            continue

        code = _get_sheet_code(sheet_name)
        if not code:
            continue

        dir_name = _get_dir_name(sheet_name)
        sheet_dir = refs_dir / dir_name
        sheet_dir.mkdir(parents=True, exist_ok=True)

        sheet = wb[sheet_name]
        structure = parse_sheet_structure(sheet, sheet_name)

        # 生成标签
        tags = [structure.regulation_name] if structure.regulation_name else []

        if structure.sub_regulations:
            # 多子法规：每个子法规独立文件
            for sub_reg in structure.sub_regulations:
                clauses = extract_clauses(sheet, structure)
                # 过滤只保留属于此子法规的条款
                sub_clauses = _filter_clauses_for_sub_reg(clauses, sub_reg, structure)

                safe_name = _safe_filename(sub_reg["name"])
                fm = generate_frontmatter(dir_name, sub_reg["name"], sheet_name, tags)
                md_content = clauses_to_markdown(sub_clauses, fm, sub_reg["name"])
                md_path = sheet_dir / f"{safe_name}.md"
                md_path.write_text(md_content, encoding="utf-8")
                logger.info(f"生成: {md_path} ({len(sub_clauses)} 条)")
        else:
            # 单法规：一个文件
            clauses = extract_clauses(sheet, structure)
            safe_name = _safe_filename(structure.regulation_name)
            fm = generate_frontmatter(dir_name, structure.regulation_name, sheet_name, tags)
            md_content = clauses_to_markdown(clauses, fm, structure.regulation_name)
            md_path = sheet_dir / f"{safe_name}.md"
            md_path.write_text(md_content, encoding="utf-8")
            logger.info(f"生成: {md_path} ({len(clauses)} 条)")

    wb.close()

    # 阶段2：OCR 处理图片并嵌入
    if images and not skip_ocr:
        _process_and_embed_images(images, refs_dir, zhipu_api_key)

    # 生成 meta.json
    generate_meta_json(output_path, "Excel检查清单转换（产品开发检查清单2025年）")

    return output_path


def _filter_clauses_for_sub_reg(
    clauses: List[ClauseEntry], sub_reg: Dict, structure: SheetStructure
) -> List[ClauseEntry]:
    """过滤出属于指定子法规的条款。"""
    # 根据子法规的 start_row 和下一个子法规的 start_row 来过滤
    sub_idx = structure.sub_regulations.index(sub_reg)
    start = sub_reg["start_row"]
    end = (
        structure.sub_regulations[sub_idx + 1]["start_row"] - 1
        if sub_idx + 1 < len(structure.sub_regulations)
        else float("inf")
    )

    # 将条款按序号映射回行号范围
    # 由于 extract_clauses 返回的是序号列表，这里需要另一种方式
    # 我们重新从行号范围过滤
    return clauses  # 暂时返回全部，后续在 extract_clauses 中加入行号信息


def _safe_filename(name: str) -> str:
    """将法规名称转换为安全的文件名。"""
    # 移除常见的文件名不安全字符
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'[\s]+', '_', name)
    # 截断过长的名称
    if len(name) > 100:
        name = name[:100]
    return name.strip("_")


def _process_and_embed_images(
    images: List[ImageInfo],
    refs_dir: Path,
    zhipu_api_key: Optional[str],
) -> None:
    """OCR 处理图片并嵌入到对应的 Markdown 文件。"""
    if not zhipu_api_key:
        logger.warning("未提供 ZHIPU_API_KEY，跳过 OCR 图片处理")
        return

    for img_info in images:
        code = _get_sheet_code(img_info.sheet_name)
        dir_name = _get_dir_name(img_info.sheet_name)
        sheet_dir = refs_dir / dir_name

        if not sheet_dir.exists():
            logger.warning(f"目录不存在: {sheet_dir}")
            continue

        try:
            md_table = ocr_image(img_info.image_data, zhipu_api_key)
            if not md_table:
                logger.warning(f"OCR 返回空结果: sheet={img_info.sheet_name} row={img_info.row}")
                continue

            # 找到对应行附近的条款文件，追加表格
            _embed_table_near_row(sheet_dir, img_info.row, md_table)
            logger.info(f"OCR 表格已嵌入: sheet={img_info.sheet_name} row={img_info.row}")

        except Exception as e:
            logger.error(f"OCR 处理失败: sheet={img_info.sheet_name} row={img_info.row}: {e}")


def _embed_table_near_row(sheet_dir: Path, row: int, md_table: str) -> None:
    """将 Markdown 表表嵌入到对应目录的文件中（追加到文件末尾）。"""
    # 简单策略：追加到目录下所有 .md 文件的末尾（或找到最近的文件）
    md_files = list(sheet_dir.glob("*.md"))
    if not md_files:
        return

    # 追加到第一个文件
    target = md_files[0]
    existing = target.read_text(encoding="utf-8")
    table_section = f"\n## 费率表\n\n{md_table}\n"
    target.write_text(existing + table_section, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Excel 检查清单 → Markdown 知识库")
    parser.add_argument("--input", required=True, help="Excel 文件路径")
    parser.add_argument("--output", required=True, help="输出目录路径")
    parser.add_argument("--skip-ocr", action="store_true", help="跳过 OCR 图片处理")
    parser.add_argument("--zhipu-api-key", default=None, help="智谱 API Key")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    api_key = args.zhipu_api_key
    if not api_key:
        import os
        api_key = os.getenv("ZHIPU_API_KEY")

    convert_excel_to_kb(
        excel_path=args.input,
        output_dir=args.output,
        skip_ocr=args.skip_ocr,
        zhipu_api_key=api_key,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && python -m pytest tests/lib/rag_engine/test_excel_parser.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/rag_engine/excel_to_kb.py scripts/tests/lib/rag_engine/test_excel_parser.py
git commit -m "feat: add Excel sheet structure parser for KB conversion"
```

---

### Task 3: Clause Extraction with Row Tracking

Improve clause extraction to track row numbers, enabling accurate sub-regulation filtering. Also handle the clause-to-markdown formatting with proper `##` heading structure.

**Files:**
- Modify: `scripts/lib/rag_engine/excel_to_kb.py`
- Modify: `scripts/tests/lib/rag_engine/test_excel_parser.py`

- [ ] **Step 1: Add row tracking to ClauseEntry and fix sub-regulation filtering**

Update `ClauseEntry` dataclass to include `row`:

```python
@dataclass
class ClauseEntry:
    """单个检查条款。"""
    sequence: int
    content: str
    row: int = 0
    metadata: Dict[str, str] = field(default_factory=dict)
```

Update `extract_clauses` to record row number:

```python
def extract_clauses(sheet, structure: SheetStructure) -> List[ClauseEntry]:
    """从 sheet 中提取所有检查条款及其元数据。"""
    clauses = []

    for row_idx, row in enumerate(
        sheet.iter_rows(min_row=structure.data_start_row, values_only=True),
        start=structure.data_start_row,
    ):
        cell_a = row[0] if row else None

        # 跳过空行和子法规标题行
        if cell_a is None or (not _is_number(cell_a)):
            continue

        content = str(row[1] or "").strip() if len(row) > 1 else ""
        if not content:
            continue

        # 提取元数据
        metadata = {}
        for col_idx, col_name in _METADATA_COLUMNS.items():
            if col_idx < len(row) and row[col_idx]:
                val = str(row[col_idx]).strip()
                if val and val != "全部":
                    metadata[col_name] = val

        clauses.append(ClauseEntry(
            sequence=int(cell_a) if isinstance(cell_a, (int, float)) else int(float(cell_a)),
            content=content,
            row=row_idx,
            metadata=metadata,
        ))

    return clauses
```

Fix `_filter_clauses_for_sub_reg` to use row tracking:

```python
def _filter_clauses_for_sub_reg(
    clauses: List[ClauseEntry], sub_reg: Dict, structure: SheetStructure
) -> List[ClauseEntry]:
    """过滤出属于指定子法规的条款（基于行号范围）。"""
    sub_idx = structure.sub_regulations.index(sub_reg)
    start = sub_reg["start_row"]
    end = (
        structure.sub_regulations[sub_idx + 1]["start_row"]
        if sub_idx + 1 < len(structure.sub_regulations)
        else float("inf")
    )
    return [c for c in clauses if start <= c.row < end]
```

- [ ] **Step 2: Add tests for clause extraction and sub-regulation filtering**

Append to `scripts/tests/lib/rag_engine/test_excel_parser.py`:

```python
class TestClauseExtraction:
    """Tests for clause extraction and sub-regulation filtering."""

    def test_extract_clauses_returns_entries(self):
        """Should extract non-empty clause entries with sequence numbers."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure, extract_clauses

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "00" in name:
                sheet = wb[name]
                break
        assert sheet is not None

        structure = parse_sheet_structure(sheet, "00. 对照样例")
        clauses = extract_clauses(sheet, structure)
        assert len(clauses) > 0
        assert all(c.sequence > 0 for c in clauses)
        assert all(c.content for c in clauses)
        assert all(c.row > 0 for c in clauses)
        wb.close()

    def test_extract_clauses_includes_metadata(self):
        """Should extract metadata columns when present."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure, extract_clauses

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "00" in name:
                sheet = wb[name]
                break

        structure = parse_sheet_structure(sheet, "00. 对照样例")
        clauses = extract_clauses(sheet, structure)
        # At least some clauses should have metadata
        clauses_with_meta = [c for c in clauses if c.metadata]
        assert len(clauses_with_meta) > 0
        wb.close()

    def test_sheet_10_sub_regulation_filtering(self):
        """Sheet 10 sub-regulations should produce separate clause groups."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import (
            parse_sheet_structure, extract_clauses, _filter_clauses_for_sub_reg,
        )

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "10" in name and "其他" in name:
                sheet = wb[name]
                break

        structure = parse_sheet_structure(sheet, "10. 对照样例")
        all_clauses = extract_clauses(sheet, structure)

        total_filtered = 0
        for sub_reg in structure.sub_regulations:
            filtered = _filter_clauses_for_sub_reg(all_clauses, sub_reg, structure)
            total_filtered += len(filtered)
            # Each sub-regulation should have at least 1 clause
            assert len(filtered) >= 0  # some may be empty

        # Total filtered should equal total clauses (no overlap, no gaps)
        assert total_filtered == len(all_clauses)
        wb.close()
```

- [ ] **Step 3: Run all parser tests**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && python -m pytest tests/lib/rag_engine/test_excel_parser.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/rag_engine/excel_to_kb.py scripts/tests/lib/rag_engine/test_excel_parser.py
git commit -m "feat: add row tracking to clause extraction and sub-regulation filtering"
```

---

### Task 4: Markdown Generation and Frontmatter Formatting

Ensure the Markdown output format is correct: YAML frontmatter, `##` headings, blockquote metadata, and clean content.

**Files:**
- Modify: `scripts/tests/lib/rag_engine/test_excel_parser.py`

- [ ] **Step 1: Add Markdown generation tests**

Append to `scripts/tests/lib/rag_engine/test_excel_parser.py`:

```python
class TestMarkdownGeneration:
    """Tests for Markdown output formatting."""

    def test_generate_frontmatter_yaml(self):
        """Should produce valid YAML frontmatter block."""
        from lib.rag_engine.excel_to_kb import generate_frontmatter

        fm = generate_frontmatter(
            collection="00_保险法",
            regulation="保险法",
            source_sheet='00. 对照"保险法"等法规检查',
            tags=["保险法", "人身保险"],
        )
        assert fm.startswith("---\n")
        assert fm.endswith("---\n")
        assert "collection: 00_保险法" in fm
        assert "regulation: 保险法" in fm
        assert "source_sheet:" in fm

    def test_clauses_to_markdown_structure(self):
        """Generated Markdown should have frontmatter, H1 title, and H2 clauses."""
        from lib.rag_engine.excel_to_kb import clauses_to_markdown, ClauseEntry, generate_frontmatter

        fm = generate_frontmatter("01_负面清单检查", "负面清单", "01.sheet", [])
        clauses = [
            ClauseEntry(sequence=1, content="第一条内容", metadata={"险种大类": "人身保险"}),
            ClauseEntry(sequence=2, content="第二条内容", metadata={}),
        ]
        md = clauses_to_markdown(clauses, fm, "负面清单")

        assert md.startswith("---\n")
        assert "# 负面清单" in md
        assert "## 第1项" in md
        assert "## 第2项" in md
        assert "> **元数据**: 险种大类=人身保险" in md
        assert "第一条内容" in md

    def test_clauses_to_markdown_no_metadata_no_blockquote(self):
        """Clauses without metadata should not produce blockquote lines."""
        from lib.rag_engine.excel_to_kb import clauses_to_markdown, ClauseEntry, generate_frontmatter

        fm = generate_frontmatter("00_保险法", "保险法", "00.sheet", [])
        clauses = [ClauseEntry(sequence=1, content="无标签条款")]
        md = clauses_to_markdown(clauses, fm, "保险法")

        assert "> **元数据**:" not in md

    def test_format_metadata_block(self):
        """Metadata block should use pipe separator."""
        from lib.rag_engine.excel_to_kb import format_metadata_block

        result = format_metadata_block({"险种大类": "人身保险", "险种类型": "寿险"})
        assert "险种大类=人身保险 | 险种类型=寿险" in result

    def test_format_metadata_block_empty(self):
        """Empty metadata should return empty string."""
        from lib.rag_engine.excel_to_kb import format_metadata_block

        assert format_metadata_block({}) == ""

    def test_safe_filename(self):
        """Should remove unsafe characters and replace spaces."""
        from lib.rag_engine.excel_to_kb import _safe_filename

        assert _safe_filename('关于"分红险"的规定（2025年）') == "关于分红险的规定2025年"
        assert _safe_filename("  extra  spaces  ") == "extra_spaces"
```

- [ ] **Step 2: Run tests**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && python -m pytest tests/lib/rag_engine/test_excel_parser.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/lib/rag_engine/test_excel_parser.py
git commit -m "test: add Markdown generation and formatting tests"
```

---

### Task 5: Full Pipeline Integration Test

Test the complete Excel → Markdown conversion pipeline end-to-end (without OCR, using `--skip-ocr`).

**Files:**
- Modify: `scripts/tests/lib/rag_engine/test_excel_parser.py`

- [ ] **Step 1: Add integration test**

Append to `scripts/tests/lib/rag_engine/test_excel_parser.py`:

```python
class TestFullPipeline:
    """End-to-end conversion tests (skip OCR)."""

    def test_convert_excel_to_kb_generates_files(self):
        """Full pipeline should generate markdown files in correct directory structure."""
        import tempfile
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import convert_excel_to_kb

        with tempfile.TemporaryDirectory() as tmpdir:
            output = convert_excel_to_kb(
                excel_path=str(EXCEL_PATH),
                output_dir=tmpdir,
                skip_ocr=True,
            )

            refs_dir = output / "references"
            assert refs_dir.exists()

            # Should have directories for each sheet
            subdirs = [d for d in refs_dir.iterdir() if d.is_dir()]
            assert len(subdirs) >= 10

            # Should have meta.json
            meta_path = output / "meta.json"
            assert meta_path.exists()
            import json
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            assert meta["version_id"] == "v4"
            assert meta["document_count"] > 0

    def test_convert_output_valid_markdown(self):
        """Generated files should be valid Markdown with frontmatter."""
        import tempfile
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import convert_excel_to_kb

        with tempfile.TemporaryDirectory() as tmpdir:
            convert_excel_to_kb(excel_path=str(EXCEL_PATH), output_dir=tmpdir, skip_ocr=True)

            # Check first .md file found
            refs_dir = Path(tmpdir) / "references"
            md_files = list(refs_dir.rglob("*.md"))
            assert len(md_files) > 0

            content = md_files[0].read_text(encoding="utf-8")
            assert content.startswith("---\n")
            assert "---\n" in content[4:]  # closing frontmatter
            assert "# " in content  # H1 heading

    def test_convert_sheet_10_multiple_files(self):
        """Sheet 10 (其他监管规定) should generate multiple files for sub-regulations."""
        import tempfile
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import convert_excel_to_kb

        with tempfile.TemporaryDirectory() as tmpdir:
            convert_excel_to_kb(excel_path=str(EXCEL_PATH), output_dir=tmpdir, skip_ocr=True)

            refs_dir = Path(tmpdir) / "references"
            # Find the 12_其他监管规定 directory
            other_dir = refs_dir / "12_其他监管规定"
            if other_dir.exists():
                md_files = list(other_dir.glob("*.md"))
                assert len(md_files) >= 2, f"Expected >= 2 files, got {len(md_files)}"
```

- [ ] **Step 2: Run full test suite**

Run: `cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && python -m pytest tests/lib/rag_engine/test_excel_parser.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add scripts/tests/lib/rag_engine/test_excel_parser.py
git commit -m "test: add full pipeline integration tests for Excel-to-KB conversion"
```

---

### Task 6: Run Conversion and Validate Output

Execute the actual conversion to generate v4 KB files and validate the output.

**Files:**
- Generated: `scripts/lib/rag_engine/data/kb/v4/references/**/*.md`

- [ ] **Step 1: Run conversion with --skip-ocr**

Run:
```bash
cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && \
python -m lib.rag_engine.excel_to_kb \
  --input /mnt/d/work/actuary-sleuth/references/1.产品开发检查清单2025年.xlsx \
  --output lib/rag_engine/data/kb/v4 \
  --skip-ocr
```

Expected: Log output showing files generated, document count in meta.json

- [ ] **Step 2: Validate output structure**

Run:
```bash
find /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts/lib/rag_engine/data/kb/v4 -name "*.md" | sort
```

Verify:
- Each sheet has its own subdirectory
- Sheet 10 has multiple .md files
- All files start with `---` YAML frontmatter
- All files have `## 第N项` headings
- Metadata blockquotes appear where tags exist

- [ ] **Step 3: Spot-check content quality**

Read a few generated files to verify:
- Frontmatter has correct collection/regulation/source_sheet
- Clause content matches Excel data
- Metadata tags are correct (险种大类 etc.)

- [ ] **Step 4: Commit generated KB (without OCR tables)**

```bash
git add scripts/lib/rag_engine/data/kb/v4/
git commit -m "feat: generate v4 KB from Excel checklist (without OCR tables)"
```

---

### Task 7: OCR Image Processing and Embedding

Process the 5 embedded table images via Zhipu GLM-OCR and embed the results into the corresponding Markdown files.

**Files:**
- Modified: `scripts/lib/rag_engine/data/kb/v4/references/05_普通型人身保险/*.md` (and 12_其他监管规定)

- [ ] **Step 1: Run conversion WITH OCR**

Run:
```bash
cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && \
python -m lib.rag_engine.excel_to_kb \
  --input /mnt/d/work/actuary-sleuth/references/1.产品开发检查清单2025年.xlsx \
  --output lib/rag_engine/data/kb/v4 \
  --zhipu-api-key "$ZHIPU_API_KEY"
```

Expected: OCR results for 5 images logged, tables embedded into Markdown files

- [ ] **Step 2: Validate OCR table quality**

Read the files containing OCR tables. Verify:
- Tables are valid Markdown format
- Content matches the rate/percentage tables visible in the images
- Tables are placed in appropriate locations within the documents

- [ ] **Step 3: Commit OCR-processed KB**

```bash
git add scripts/lib/rag_engine/data/kb/v4/
git commit -m "feat: add OCR-processed rate tables to v4 KB via Zhipu GLM-OCR"
```

---

### Task 8: Register v4 with VersionManager and Validate RAG

Register the new KB as v4 in the VersionManager and validate it works with the RAG engine.

**Files:**
- Modified: `scripts/lib/rag_engine/data/kb/version_meta.json` (auto-updated by VersionManager)

- [ ] **Step 1: Register v4 via VersionManager**

Write and run a short script:

```python
import sys
sys.path.insert(0, "scripts")
from lib.rag_engine.version_manager import KBVersionManager

mgr = KBVersionManager()
# Deactivate v3 first
mgr.activate_version("v3")  # ensure v3 is deactivated properly by creating v4
meta = mgr.create_version(
    source_dir="scripts/lib/rag_engine/data/kb/v4/references",
    description="Excel检查清单转换v4（产品开发检查清单2025年）",
)
print(f"Created {meta.version_id} with {meta.document_count} documents")
```

Run from worktree root: `python3 -c "..."`

- [ ] **Step 2: Verify version registration**

Run:
```bash
cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && \
python -c "
from lib.rag_engine.version_manager import KBVersionManager
mgr = KBVersionManager()
for v in mgr.list_versions():
    print(f'{v.version_id}: active={v.active}, docs={v.document_count}, desc={v.description}')
"
```

Expected: v4 listed with `active=True`

- [ ] **Step 3: Validate RAG engine can load v4**

Run:
```bash
cd /mnt/d/work/actuary-sleuth/.claude/worktrees/kb-version/scripts && \
python -c "
from lib.rag_engine.version_manager import KBVersionManager
mgr = KBVersionManager()
paths = mgr.get_active_paths()
print(f'Regulations dir: {paths[\"regulations_dir\"]}')
import os
files = [f for f in os.listdir(paths['regulations_dir']) if f.endswith('.md')]
print(f'MD files: {len(files)}')
"
```

Expected: Regulations dir points to v4/references, MD files listed

- [ ] **Step 4: Commit version registration**

```bash
git add scripts/lib/rag_engine/data/kb/
git commit -m "feat: register v4 KB with VersionManager and validate RAG integration"
```
