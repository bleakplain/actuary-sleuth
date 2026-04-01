#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Excel 产品开发检查清单 → Markdown 知识库转换脚本。

将 references/1.产品开发检查清单2025年.xlsx 转换为结构化 Markdown 知识库。
每个 sheet 按法规粒度拆分，提取元数据标签，处理内嵌表格图片。
"""
import argparse
import io
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

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


@dataclass(frozen=True)
class SheetStructure:
    """解析后的 sheet 结构信息。"""
    sheet_name: str
    header_row: int
    data_start_row: int
    regulation_name: str
    headers: Dict[int, str] = field(default_factory=dict)
    sub_regulations: List[Dict] = field(default_factory=list)
    layout_type: str = "standard"  # "standard" or "with_owner"


@dataclass(frozen=True)
class ClauseEntry:
    """单个检查条款。"""
    sequence: int
    content: str
    row: int = 0
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
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
            row=row_idx,
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
    images = []
    for img in sheet._images:
        anchor = img.anchor
        if hasattr(anchor, "_from"):
            row = anchor._from.row + 1  # openpyxl is 0-based
            col = anchor._from.col
        else:
            continue

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

    # 阶段1：提取图片（需要非 read_only 模式）
    images = extract_images_from_excel(excel_path) if not skip_ocr else []

    # 以 read_only 模式处理数据
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

        tags = [structure.regulation_name] if structure.regulation_name else []

        if structure.sub_regulations:
            all_clauses = extract_clauses(sheet, structure)
            for sub_reg in structure.sub_regulations:
                sub_clauses = _filter_clauses_for_sub_reg(all_clauses, sub_reg, structure)
                safe_name = _safe_filename(sub_reg["name"])
                fm = generate_frontmatter(dir_name, sub_reg["name"], sheet_name, tags)
                md_content = clauses_to_markdown(sub_clauses, fm, sub_reg["name"])
                md_path = sheet_dir / f"{safe_name}.md"
                md_path.write_text(md_content, encoding="utf-8")
                logger.info(f"生成: {md_path} ({len(sub_clauses)} 条)")
        else:
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

    generate_meta_json(output_path, "Excel检查清单转换（产品开发检查清单2025年）")

    return output_path


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


def _safe_filename(name: str) -> str:
    """将法规名称转换为安全的文件名。"""
    # Remove ASCII unsafe chars and full-width/CJK punctuation
    name = re.sub(r'[<>:"/\\|?*（）【】《》、，。！？；：""\'\'…—〔〕「」]', '', name)
    name = re.sub(r'[\s]+', '_', name)
    # Keep filename under 240 bytes (leaving room for .md suffix and path prefix).
    # Truncate by bytes to handle multi-byte UTF-8 characters safely.
    max_bytes = 240
    encoded = name.encode("utf-8")
    if len(encoded) > max_bytes:
        encoded = encoded[:max_bytes]
        # Decode back, ignoring any partial multi-byte sequence at the end
        name = encoded.decode("utf-8", errors="ignore")
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

            _embed_table_near_row(sheet_dir, img_info.row, md_table)
            logger.info(f"OCR 表格已嵌入: sheet={img_info.sheet_name} row={img_info.row}")

        except Exception as e:
            logger.error(f"OCR 处理失败: sheet={img_info.sheet_name} row={img_info.row}: {e}")


def _embed_table_near_row(sheet_dir: Path, row: int, md_table: str) -> None:
    """将 Markdown 表格嵌入到对应目录的文件中（追加到文件末尾）。"""
    md_files = list(sheet_dir.glob("*.md"))
    if not md_files:
        return

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
